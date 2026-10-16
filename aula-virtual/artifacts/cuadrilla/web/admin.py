"""Administrator screens (spec §6): courses, malla and brochure, users and roles, manual Coins,
redemptions, movements, parameters with history and course closing."""

import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ai import jobs
from auth.deps import admin_actual, csrf_valido
from config import settings
from db.models import Canje, Curso, Inscripcion, LlamadaIA, Movimiento, Tema, Usuario
from db.session import get_db
from rules.params import DEFINICIONES
from services import admin, course_deletion, curriculum, ledger
from services import params as params_service
from services.admin import AdminError
from services.params import cargar
from services.redemption import CanjeInvalido, corregir
from web.views import page, volver

router = APIRouter(prefix="/admin")
POST = [Depends(csrf_valido)]
MAX_MALLA_BYTES = 2 * 1024 * 1024
MAX_BROCHURE_BYTES = 25 * 1024 * 1024


def _curso(db, curso_id: int) -> Curso:
    curso = db.scalar(select(Curso).where(Curso.id == curso_id).with_for_update(read=True, key_share=True))
    if curso is None:
        raise HTTPException(status_code=404, detail="No encontramos ese curso.")
    return curso


def _alumno_por_dni(db, dni: str) -> Usuario:
    usuario = db.scalar(select(Usuario).where(Usuario.dni == dni.strip()))
    if usuario is None:
        raise AdminError("No hay un usuario con ese DNI.")
    return usuario


@router.get("", name="admin_home")
def home(request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    cursos = db.scalars(select(Curso).order_by(Curso.estado, Curso.nombre)).all()
    conteos = dict(db.execute(select(Usuario.rol, func.count()).group_by(Usuario.rol)).all())
    uso_ia = db.execute(select(LlamadaIA.componente, func.count(), func.coalesce(func.sum(LlamadaIA.tokens_entrada), 0),
                               func.coalesce(func.sum(LlamadaIA.tokens_salida), 0))
                        .group_by(LlamadaIA.componente).order_by(LlamadaIA.componente)).all()
    return page(request, "admin/home.html", {"page_title": "Administración", "active_nav": "admin", "cursos": cursos,
                                             "conteos": conteos, "uso_ia": uso_ia})


@router.post("/demo", name="admin_demo", dependencies=POST)
def load_demo(request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="La demostración está desactivada.")
    from db import demo
    cargada = demo.actividad(db)
    db.commit()
    return volver(request, "admin_home", ok="demo" if cargada else "demo_existente")


@router.post("/cursos", name="admin_course_create", dependencies=POST)
def course_create(request: Request, nombre: str = Form(...), fecha_inicio: str = Form(""), fecha_fin: str = Form(""),
                  db=Depends(get_db), usuario=Depends(admin_actual)):
    nombre = " ".join(nombre.split())
    if not nombre or len(nombre) > 250:
        raise HTTPException(status_code=400, detail="El nombre del curso es obligatorio (hasta 250 caracteres).")
    try:
        curso = Curso(nombre=nombre, fecha_inicio=date.fromisoformat(fecha_inicio) if fecha_inicio else None,
                      fecha_fin=date.fromisoformat(fecha_fin) if fecha_fin else None)
        db.add(curso)
        db.commit()
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Fecha inválida.") from error
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ya existe un curso con ese nombre.") from error
    return volver(request, "admin_course", curso_id=curso.id, ok="guardado")


def _pagina_curso(request, db, curso, **extra):
    temas = db.scalars(select(Tema).where(Tema.curso_id == curso.id).order_by(Tema.orden)).all()
    inscritos = db.execute(select(Usuario, Inscripcion.rol_en_curso).join(
        Inscripcion, Inscripcion.usuario_id == Usuario.id).where(Inscripcion.curso_id == curso.id)
        .order_by(Inscripcion.rol_en_curso, Usuario.apellido)).all()
    podio = [f for f in ledger.podio(db, curso.id) if f["exp"] > 0][:5]
    return page(request, "admin/course.html", {"page_title": curso.nombre, "active_nav": "admin", "curso": curso,
                                               "temas": temas, "inscritos": inscritos, "podio": podio, **extra},
                status_code=400 if extra.get("errores") or extra.get("error") else 200)


@router.get("/cursos/{curso_id}", name="admin_course")
def course(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    return _pagina_curso(request, db, _curso(db, curso_id))


@router.post("/cursos/{curso_id}/malla", name="admin_curriculum_upload", dependencies=POST)
def curriculum_upload(curso_id: int, request: Request, archivo: UploadFile = File(...), db=Depends(get_db),
                      usuario=Depends(admin_actual)):
    curso = _curso(db, curso_id)
    nombre = archivo.filename or ""
    es_pdf = nombre.lower().endswith(".pdf")
    limite = curriculum.MAX_PDF_BYTES if es_pdf else MAX_MALLA_BYTES
    contenido = archivo.file.read(limite + 1)
    if len(contenido) > limite:
        return _pagina_curso(request, db, curso, errores=[f"El archivo de la malla supera {limite // 1024 // 1024} MB."])
    if not nombre.lower().endswith((".csv", ".json", ".pdf")):
        return _pagina_curso(request, db, curso, errores=["Sube la malla en CSV, JSON o PDF."])
    try:
        if es_pdf:
            with jobs.usando_curso(curso_id):
                db.expire_all()
                curso = _curso(db, curso_id)
                borrador = curriculum.leer_malla_pdf(contenido, referencia=f"curso:{curso_id}:malla_pdf")
                temas_json = json.dumps(borrador["temas"], ensure_ascii=False)
                return page(request, "admin/curriculum_preview.html", {
                    "page_title": "Revisar malla PDF", "active_nav": "admin", "curso": curso,
                    "archivo": nombre.replace("\\", "/").split("/")[-1][:300],
                    "temas_json": temas_json, **borrador})
        temas = curriculum.leer_malla(nombre, contenido)
    except curriculum.MallaInvalida as error:
        return _pagina_curso(request, db, curso, errores=error.errores)
    resumen = curriculum.guardar_malla(db, curso, temas)
    curriculum.solicitar_propuesta(db, curso)
    db.commit()
    return _pagina_curso(request, db, curso, resumen=resumen)


@router.post("/cursos/{curso_id}/malla/confirmar", name="admin_curriculum_confirm", dependencies=POST)
def curriculum_confirm(curso_id: int, request: Request, temas_json: str = Form(...), confirmo: str = Form(""),
                       db=Depends(get_db), usuario=Depends(admin_actual)):
    curso = _curso(db, curso_id)
    if confirmo != "si":
        return _pagina_curso(request, db, curso, errores=["Confirma que revisaste los temas y objetivos del PDF."])
    contenido = temas_json.encode()
    if len(contenido) > MAX_MALLA_BYTES:
        return _pagina_curso(request, db, curso, errores=["La malla extraída supera el límite de datos permitido."])
    try:
        temas = curriculum.leer_malla("malla.json", contenido)
    except curriculum.MallaInvalida as error:
        return _pagina_curso(request, db, curso, errores=error.errores)
    resumen = curriculum.guardar_malla(db, curso, temas)
    curriculum.solicitar_propuesta(db, curso)
    db.commit()
    return _pagina_curso(request, db, curso, resumen=resumen)


@router.post("/cursos/{curso_id}/temas", name="admin_topic_create", dependencies=POST)
def topic_create(curso_id: int, request: Request, nombre: str = Form(...), objetivo: str = Form(...),
                 modulo: str = Form(""), subtema: str = Form(""), db=Depends(get_db), usuario=Depends(admin_actual)):
    curso = _curso(db, curso_id)
    fila = {"modulo": modulo, "tema": nombre, "subtema": subtema, "objetivo": objetivo}
    try:
        temas = curriculum.leer_malla("formulario.json", json.dumps([fila]).encode())
    except curriculum.MallaInvalida as error:
        return _pagina_curso(request, db, curso, errores=[e.replace("Fila 1: ", "") for e in error.errores])
    resumen = curriculum.guardar_malla(db, curso, temas)
    db.commit()
    return _pagina_curso(request, db, curso, resumen=resumen)


@router.post("/cursos/{curso_id}/brochure", name="admin_brochure", dependencies=POST)
def brochure(curso_id: int, request: Request, archivo: UploadFile = File(...), db=Depends(get_db),
             usuario=Depends(admin_actual)):
    curso = _curso(db, curso_id)
    contenido = archivo.file.read(MAX_BROCHURE_BYTES + 1)
    if not (archivo.filename or "").lower().endswith(".pdf") or len(contenido) > MAX_BROCHURE_BYTES:
        return _pagina_curso(request, db, curso, error="Sube el brochure en PDF (máximo 25 MB).")
    try:
        curso.brochure_texto = curriculum.leer_brochure(contenido)
    except ValueError as error:
        return _pagina_curso(request, db, curso, error=str(error))
    curso.brochure_nombre = archivo.filename[:300]
    pedida = curriculum.solicitar_propuesta(db, curso)
    db.commit()
    return volver(request, "admin_course", curso_id=curso.id, ok="propuesta" if pedida else "guardado")


@router.post("/cursos/{curso_id}/propuesta", name="admin_proposal", dependencies=POST)
def proposal(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    curso = _curso(db, curso_id)
    if not curriculum.solicitar_propuesta(db, curso):
        raise HTTPException(status_code=400, detail=f"Carga la malla y configura {settings.variable_clave()} para pedir la propuesta.")
    db.commit()
    return volver(request, "admin_course", curso_id=curso.id, ok="propuesta")


@router.post("/cursos/{curso_id}/inscribir", name="admin_enroll", dependencies=POST)
def enroll(curso_id: int, request: Request, dni: str = Form(...), db=Depends(get_db), usuario=Depends(admin_actual)):
    curso = _curso(db, curso_id)
    try:
        admin.inscribir(db, _alumno_por_dni(db, dni), curso)
    except AdminError as error:
        return _pagina_curso(request, db, curso, error=str(error))
    db.commit()
    return volver(request, "admin_course", curso_id=curso.id, ok="guardado", ancla="inscritos")


@router.post("/cursos/{curso_id}/desinscribir/{usuario_id}", name="admin_unenroll", dependencies=POST)
def unenroll(curso_id: int, usuario_id: int, request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    curso = _curso(db, curso_id)
    admin.desinscribir(db, usuario_id, curso.id)
    db.commit()
    return volver(request, "admin_course", curso_id=curso.id, ok="guardado", ancla="inscritos")


@router.post("/cursos/{curso_id}/cerrar", name="admin_close", dependencies=POST)
def close(curso_id: int, request: Request, confirmo: str = Form(""), db=Depends(get_db), usuario=Depends(admin_actual)):
    curso = _curso(db, curso_id)
    if confirmo != "si":
        return _pagina_curso(request, db, curso, error="Marca la confirmación para cerrar el curso.")
    admin.cerrar_curso(db, usuario.id, curso, cargar(db))
    db.commit()
    return volver(request, "admin_course", curso_id=curso.id, ok="cerrado")


@router.get("/cursos/{curso_id}/top3.csv", name="admin_top3")
def top3(curso_id: int, db=Depends(get_db), usuario=Depends(admin_actual)):
    curso = _curso(db, curso_id)
    return Response(admin.exportar_top3(db, curso), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="podio-curso-{curso.id}.csv"'})


def _pagina_eliminacion(request, db, curso, error=None):
    try:
        resumen = course_deletion.resumen_eliminacion(db, curso)
    except AdminError as problema:
        return _pagina_curso(request, db, curso, error=str(problema))
    return page(request, "admin/course_delete.html", {"page_title": "Eliminar curso", "active_nav": "admin",
                "curso": curso, "resumen": resumen, "error": error}, status_code=400 if error else 200)


@router.get("/cursos/{curso_id}/eliminar", name="admin_course_delete")
def course_delete_preview(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    return _pagina_eliminacion(request, db, _curso(db, curso_id))


@router.post("/cursos/{curso_id}/eliminar", name="admin_course_delete_post", dependencies=POST)
def course_delete(curso_id: int, request: Request, nombre_confirmado: str = Form(""), confirmo: str = Form(""),
                  db=Depends(get_db), usuario=Depends(admin_actual)):
    _curso(db, curso_id)
    try:
        limpio = course_deletion.eliminar_curso(db, curso_id, nombre_confirmado=nombre_confirmado, confirmo=confirmo)
    except (AdminError, jobs.CursoEnUso) as error:
        db.rollback()
        return _pagina_eliminacion(request, db, _curso(db, curso_id), str(error))
    except (IntegrityError, OSError):
        db.rollback()
        return _pagina_eliminacion(request, db, _curso(db, curso_id),
                                  "No se pudo eliminar el curso. Se conservaron los datos; revisa sus archivos y referencias.")
    if not limpio:
        return page(request, "admin/course_deleted.html", {"page_title": "Curso eliminado", "active_nav": "admin"})
    return volver(request, "admin_home", ok="curso_eliminado")


@router.get("/usuarios", name="admin_users")
def users(request: Request, q: str = "", db=Depends(get_db), usuario=Depends(admin_actual)):
    consulta = select(Usuario).order_by(Usuario.rol, Usuario.apellido, Usuario.nombre)
    if q.strip():
        patron = f"%{q.strip()}%"
        consulta = consulta.where((Usuario.dni.ilike(patron)) | (Usuario.nombre.ilike(patron)) |
                                  (Usuario.apellido.ilike(patron)))
    return page(request, "admin/users.html", {
        "page_title": "Usuarios y roles", "active_nav": "usuarios", "usuarios": db.scalars(consulta.limit(300)).all(),
        "cursos": db.scalars(select(Curso).order_by(Curso.nombre)).all(), "q": q})


@router.get("/usuarios/{usuario_id}/perfil", name="admin_user_profile")
def user_profile(usuario_id: int, request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    from web.profile import mostrar
    persona = db.get(Usuario, usuario_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="No encontramos ese usuario.")
    return mostrar(request, db, persona, origen=request.url_for("admin_users"))


@router.post("/usuarios", name="admin_user_create", dependencies=POST)
def user_create(request: Request, dni: str = Form(...), nombre: str = Form(...), apellido: str = Form(...),
                rol: str = Form(...), password: str = Form(...), curso_id: str = Form(""), db=Depends(get_db),
                usuario=Depends(admin_actual)):
    try:
        nuevo = admin.crear_usuario(db, dni=dni, nombre=nombre, apellido=apellido, rol=rol, password=password)
        if curso_id.isdigit() and rol != "admin":
            admin.inscribir(db, nuevo, _curso(db, int(curso_id)))
    except AdminError as error:
        db.rollback()
        return page(request, "admin/users.html", {
            "page_title": "Usuarios y roles", "active_nav": "usuarios", "error": str(error),
            "usuarios": db.scalars(select(Usuario).order_by(Usuario.rol, Usuario.apellido).limit(300)).all(),
            "cursos": db.scalars(select(Curso).order_by(Curso.nombre)).all(), "q": "",
            "enviado": {"dni": dni, "nombre": nombre, "apellido": apellido, "rol": rol}}, status_code=400)
    db.commit()
    return volver(request, "admin_users", ok="usuario")


@router.post("/usuarios/{usuario_id}", name="admin_user_update", dependencies=POST)
def user_update(usuario_id: int, request: Request, accion: str = Form(...), password: str = Form(""),
                db=Depends(get_db), usuario=Depends(admin_actual)):
    objetivo = db.get(Usuario, usuario_id)
    if objetivo is None:
        raise HTTPException(status_code=404, detail="No encontramos ese usuario.")
    try:
        if accion == "activar":
            objetivo.activo = True
        elif accion == "desactivar":
            if objetivo.id == usuario.id:
                raise AdminError("No puedes desactivar tu propia cuenta.")
            objetivo.activo = False
            from auth.sessions import cerrar_todas
            cerrar_todas(db, objetivo.id)
        elif accion == "pausar_coins":
            objetivo.coins_pausadas = True
        elif accion == "reanudar_coins":
            objetivo.coins_pausadas = False
        elif accion == "password":
            admin.restablecer_password(db, objetivo, password)
        else:
            raise AdminError("Acción inválida.")
    except AdminError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "admin_users", ok="usuario")


@router.get("/coins", name="admin_coins")
def coins(request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    ajustes = db.execute(select(Movimiento, Usuario).join(Usuario, Usuario.id == Movimiento.alumno_id).where(
        Movimiento.origen.in_(("ajuste_admin", "devolucion_canje", "podio_final")))
        .order_by(Movimiento.creado_en.desc()).limit(50)).all()
    return page(request, "admin/coins.html", {"page_title": "Coins y EXP", "active_nav": "coins", "ajustes": ajustes,
                                              "cursos": db.scalars(select(Curso).order_by(Curso.nombre)).all(),
                                              "origen": ledger.ORIGEN_ETIQUETA})


@router.post("/coins", name="admin_coins_add", dependencies=POST)
def coins_add(request: Request, dni: str = Form(...), cantidad: int = Form(...), motivo: str = Form(""),
              db=Depends(get_db), usuario=Depends(admin_actual)):
    try:
        admin.sumar_coins(db, usuario.id, _alumno_por_dni(db, dni), cantidad, motivo)
    except AdminError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "admin_coins", ok="coins")


@router.post("/exp", name="admin_exp_adjust", dependencies=POST)
def exp_adjust(request: Request, dni: str = Form(...), curso_id: int = Form(...), cantidad: int = Form(...),
               motivo: str = Form(""), db=Depends(get_db), usuario=Depends(admin_actual)):
    try:
        admin.ajustar_exp(db, usuario.id, _alumno_por_dni(db, dni), _curso(db, curso_id), cantidad, motivo)
    except AdminError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "admin_coins", ok="exp")


@router.get("/canjes", name="admin_redemptions")
def redemptions(request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    filas = db.execute(select(Canje, Usuario).join(Usuario, Usuario.id == Canje.alumno_id)
                       .order_by(Canje.creado_en.desc()).limit(200)).all()
    return page(request, "admin/redemptions.html", {"page_title": "Canjes", "active_nav": "canjes", "filas": filas})


@router.post("/canjes/{canje_id}/corregir", name="admin_redemption_fix", dependencies=POST)
def redemption_fix(canje_id: int, request: Request, motivo: str = Form(""), db=Depends(get_db),
                   usuario=Depends(admin_actual)):
    canje = db.get(Canje, canje_id)
    if canje is None:
        raise HTTPException(status_code=404, detail="No encontramos ese canje.")
    try:
        corregir(db, canje, usuario.id, motivo)
    except CanjeInvalido as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "admin_redemptions", ok="coins")


@router.get("/movimientos", name="admin_movements")
def movements(request: Request, dni: str = "", db=Depends(get_db), usuario=Depends(admin_actual)):
    alumno = db.scalar(select(Usuario).where(Usuario.dni == dni.strip())) if dni.strip() else None
    filas = db.execute(select(Movimiento, Curso.nombre).outerjoin(Curso, Curso.id == Movimiento.curso_id).where(
        Movimiento.alumno_id == alumno.id).order_by(Movimiento.creado_en.desc()).limit(300)).all() if alumno else []
    return page(request, "admin/movements.html", {
        "page_title": "Movimientos", "active_nav": "movimientos", "dni": dni, "alumno": alumno, "filas": filas,
        "origen": ledger.ORIGEN_ETIQUETA, "saldo": ledger.saldo_coins(db, alumno.id) if alumno else 0})


@router.get("/parametros", name="admin_params")
def params_view(request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    grupos = {}
    for definicion in DEFINICIONES:
        grupos.setdefault(definicion.grupo, []).append(definicion)
    autores = {u.id: u for u in db.scalars(select(Usuario).where(Usuario.rol == "admin"))}
    return page(request, "admin/params.html", {
        "page_title": "Parámetros", "active_nav": "parametros", "grupos": grupos, "valores": cargar(db).as_dict(),
        "historial": params_service.historial(db), "autores": autores,
        "etiquetas": {d.clave: d.etiqueta for d in DEFINICIONES}})


@router.post("/parametros", name="admin_params_save", dependencies=POST)
async def params_save(request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    formulario = await request.form()
    try:
        for definicion in DEFINICIONES:
            valor = str(formulario.get(definicion.clave, "")).strip().replace(",", ".")
            if valor:
                params_service.guardar(db, usuario.id, definicion.clave, float(valor))
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error) if "usa" in str(error) else "Valor numérico inválido.") from error
    db.commit()
    return volver(request, "admin_params", ok="parametros")
