"""Teacher screens (spec §5): D1 upload, D2 validation, D3/D4 reports, D5 risk, D6 inbox, D7 malla, D8 podium.

Administrators can open every course; teachers only their own.
"""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ai import jobs
from auth.deps import csrf_valido, curso_de_docente, cursos_de, docente_actual
from config import CLASS_SOURCE_EXTENSIONS, RECORDING_EXTENSIONS, RESOURCE_EXTENSIONS, VIDEO_EXTENSIONS, settings
from db.models import Clase, Curso, Intento, Reto, RetoReporte, RetoVersion, ResumenClase, Revision, Tema, Usuario
from db.session import get_db
from rules import levels
from rules.calendar import ahora
from services import class_deletion, classes, curriculum, ledger, reports, review, risk, validation
from services.classes import ClaseInvalida
from services.params import cargar
from web.views import page, volver

router = APIRouter(prefix="/docente")
POST = [Depends(csrf_valido)]
MAX_RECURSO_MB = 20


def _clase(db, usuario, clase_id: int) -> tuple[Clase, Curso]:
    clase = db.get(Clase, clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail="No encontramos esa clase.")
    curso = curso_de_docente(db, usuario, clase.curso_id)
    clase = db.scalar(select(Clase).where(Clase.id == clase_id).execution_options(populate_existing=True))
    if clase is None:
        raise HTTPException(status_code=404, detail="No encontramos esa clase.")
    return clase, curso


def _reto(db, usuario, reto_id: int) -> tuple[Reto, Clase | None, Curso]:
    reto = db.get(Reto, reto_id)
    if reto is None:
        raise HTTPException(status_code=404, detail="No encontramos ese reto.")
    curso = curso_de_docente(db, usuario, reto.curso_id)
    reto = db.scalar(select(Reto).where(Reto.id == reto_id).execution_options(populate_existing=True))
    if reto is None:
        raise HTTPException(status_code=404, detail="No encontramos ese reto.")
    return reto, (db.get(Clase, reto.clase_id) if reto.clase_id else None), curso


def _ir_a_clase(request, clase_id: int, ok: str | None = None, ancla: str | None = None):
    return volver(request, "teacher_class", ok=ok, ancla=ancla, clase_id=clase_id)


CAMPOS = ("tipo", "enunciado", "opciones", "respuesta_correcta", "respuestas_aceptadas", "puntos_clave",
          "explicacion", "pista_1", "pista_2", "pista_3")
TIPO_SUGERIDO = {"basico": "alternativas", "intermedio": "alternativas", "avanzado": "caso", "maestria": "caso"}


def _campos(version=None, enviado: dict | None = None, nivel: str = "intermedio") -> dict:
    """Form values for one version: what the teacher sent back, the stored version, or blanks."""
    if enviado:
        return {k: enviado.get(k, "") for k in CAMPOS}
    if version is None:
        return {k: "" for k in CAMPOS} | {"tipo": TIPO_SUGERIDO.get(nivel, "alternativas")}
    pistas = (list(version.pistas) + ["", "", ""])[:3]
    return {"tipo": version.tipo, "enunciado": version.enunciado, "opciones": "\n".join(version.opciones),
            "respuesta_correcta": version.respuesta_correcta,
            "respuestas_aceptadas": "\n".join(a for a in version.respuestas_aceptadas if a != version.respuesta_correcta),
            "puntos_clave": "\n".join(version.puntos_clave), "explicacion": version.explicacion,
            "pista_1": pistas[0], "pista_2": pistas[1], "pista_3": pistas[2]}


@router.get("", name="teacher_home")
def home(request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    cursos = cursos_de(db, usuario)
    return page(request, "teacher/courses.html", {"page_title": "Mis cursos", "active_nav": "cursos", "cursos": cursos})


@router.get("/cursos/{curso_id}", name="teacher_course")
def course(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    validation.publicar_vencidas(db)
    db.commit()
    curso = curso_de_docente(db, usuario, curso_id)
    params = cargar(db)
    clases = db.scalars(select(Clase).where(Clase.curso_id == curso.id).order_by(Clase.numero.desc())).all()
    riesgo = [r for r in risk.evaluar(db, curso.id, params) if r["senal"].estado == "nuevo"]
    db.commit()
    curso = curso_de_docente(db, usuario, curso_id)
    return page(request, "teacher/course.html", {
        "page_title": curso.nombre, "active_nav": "curso", "curso": curso, "clases": clases,
        "por_validar": [c for c in clases if c.estado == "por_validar"],
        "procesando": any(c.estado == "procesando" for c in clases), "riesgo": len({r["alumno"].id for r in riesgo}),
        "revisiones": review.contar_pendientes(db, curso.id), "no_cubiertos": reports.temas_no_cubiertos(db, curso.id),
        "temas": db.scalar(select(func.count()).select_from(Tema).where(Tema.curso_id == curso.id)),
        "modulo_de_clase": curriculum.modulo_de_clase, "ahora": ahora()})


@router.get("/cursos/{curso_id}/clases/nueva", name="teacher_upload")
def upload_form(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    siguiente = (db.scalar(select(func.max(Clase.numero)).where(Clase.curso_id == curso.id)) or 0) + 1
    return page(request, "teacher/upload.html", {"page_title": "Subir clase", "active_nav": "subir", "curso": curso,
                                                 "form": {"numero": siguiente, "fecha": date.today().isoformat()}})


def _guardar_archivo(archivo: UploadFile, permitidas, limite_mb: int) -> tuple[str, Path, str]:
    nombre_original = archivo.filename.replace("\\", "/").split("/")[-1].strip()
    sufijo = Path(nombre_original).suffix.lower()
    if sufijo not in permitidas:
        raise ClaseInvalida(f"Formato no permitido: {nombre_original}.")
    nombre, ruta = classes.ruta_subida(nombre_original)
    tamano, maximo = 0, limite_mb * 1024 * 1024
    try:
        with ruta.open("xb") as destino:
            while bloque := archivo.file.read(1024 * 1024):
                tamano += len(bloque)
                if tamano > maximo:
                    raise ClaseInvalida(f"El archivo supera el límite de {limite_mb} MB.")
                destino.write(bloque)
        if tamano == 0:
            raise ClaseInvalida("El archivo está vacío.")
    except BaseException:
        ruta.unlink(missing_ok=True)
        raise
    return nombre, ruta, nombre_original


@router.post("/cursos/{curso_id}/clases/nueva", name="teacher_upload_post", dependencies=POST)
def upload(curso_id: int, request: Request, numero: int = Form(...), fecha: date = Form(...), titulo: str = Form(""),
           transcript_texto: str = Form(""), usar_ejemplo: str = Form(""), tarea: str = Form(""),
           fuente: UploadFile | None = File(None), recursos: list[UploadFile] = File(default=[]),
           db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    form = {"numero": numero, "fecha": fecha.isoformat(), "titulo": titulo, "transcript_texto": transcript_texto,
            "tarea": tarea}
    guardado = None
    try:
        lecturas = []
        for recurso in recursos:
            if recurso and recurso.filename:
                if Path(recurso.filename).suffix.lower() not in RESOURCE_EXTENSIONS:
                    raise ClaseInvalida(f"Recurso no permitido: {recurso.filename}. Usa PDF, TXT o MD.")
                contenido = recurso.file.read(MAX_RECURSO_MB * 1024 * 1024 + 1)
                if len(contenido) > MAX_RECURSO_MB * 1024 * 1024:
                    raise ClaseInvalida(f"{recurso.filename} supera {MAX_RECURSO_MB} MB.")
                lecturas.append((recurso.filename.replace("\\", "/").split("/")[-1][:200], contenido))
        transcript, archivo, nombre_fuente, tipo = None, None, "Transcript pegado", "texto"
        if usar_ejemplo == "si" and settings.DEMO_MODE:
            from db.demo import _transcript
            transcript, nombre_fuente = _transcript(), "Transcript de ejemplo"
        elif fuente is not None and fuente.filename:
            archivo, guardado, nombre_fuente = _guardar_archivo(fuente, CLASS_SOURCE_EXTENSIONS, settings.MAX_UPLOAD_MB)
            sufijo = guardado.suffix.lower()
            tipo = "video" if sufijo in VIDEO_EXTENSIONS else "audio" if sufijo in RECORDING_EXTENSIONS else "texto"
        elif transcript_texto.strip():
            transcript = transcript_texto.strip()[:300_000]
        else:
            raise ClaseInvalida("Sube el video o audio de la clase, un transcript o pega su texto.")
        clase = classes.crear_clase(db, curso, usuario.id, numero=numero, fecha=fecha, titulo=titulo, fuente_tipo=tipo,
                                    fuente_archivo=archivo, fuente_nombre=nombre_fuente, transcript=transcript,
                                    recursos=lecturas, tarea=tarea)
        db.commit()
    except ClaseInvalida as error:
        db.rollback()
        if guardado is not None:
            guardado.unlink(missing_ok=True)
        return page(request, "teacher/upload.html", {"page_title": "Subir clase", "active_nav": "subir",
                                                     "curso": curso, "form": form, "error": str(error)}, status_code=400)
    return _ir_a_clase(request, clase.id, ok="subida")


@router.get("/clases/{clase_id}", name="teacher_class")
def class_detail(clase_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    clase, curso = _clase(db, usuario, clase_id)
    validation.publicar_vencidas(db)
    db.commit()
    clase, curso = _clase(db, usuario, clase_id)
    grupos = validation.resumen_validacion(db, clase)
    versiones = {r.id: validation.versiones_vigentes(db, r) for g in grupos.values() for r in g}
    reportes = dict(db.execute(select(RetoReporte.reto_id, func.count()).where(
        RetoReporte.reto_id.in_(list(versiones) or [0])).group_by(RetoReporte.reto_id)).all())
    return page(request, "teacher/class.html", {
        "page_title": clase.nombre, "active_nav": "curso", "curso": curso, "clase": clase, **grupos,
        "versiones": versiones, "reportes": reportes, "temas_clase": classes.temas_de_clase(db, clase.id),
        "temas_curso": db.scalars(select(Tema).where(Tema.curso_id == curso.id).order_by(Tema.orden)).all(),
        "temas": {t.id: t for t in db.scalars(select(Tema).where(Tema.curso_id == curso.id))},
        "auditoria": {r.id: validation.auditoria(db, r.id) for g in grupos.values() for r in g},
        "generando": any(r.estado == "generando" for g in grupos.values() for r in g) or clase.estado == "procesando",
        "resumen_clase": db.get(ResumenClase, clase.id), "ahora": ahora()})


@router.post("/clases/{clase_id}/resumen/reintentar", name="teacher_summary_retry", dependencies=POST)
def summary_retry(clase_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    from services import summaries
    clase, _ = _clase(db, usuario, clase_id)
    try:
        summaries.reintentar(db, clase)
    except ClaseInvalida as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return _ir_a_clase(request, clase.id, ok="resumen_encolado", ancla="resumen-clase")


def _pagina_eliminar_clase(request, db, clase, curso, error=None):
    try:
        resumen = class_deletion.resumen_eliminacion(db, clase)
    except ClaseInvalida as problema:
        resumen, error = None, str(problema)
    return page(request, "teacher/class_delete.html", {
        "page_title": "Eliminar clase", "active_nav": "curso", "clase": clase, "curso": curso,
        "resumen": resumen, "error": error}, status_code=400 if error else 200)


@router.get("/clases/{clase_id}/eliminar", name="teacher_class_delete")
def class_delete_preview(clase_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    clase, curso = _clase(db, usuario, clase_id)
    return _pagina_eliminar_clase(request, db, clase, curso)


@router.post("/clases/{clase_id}/eliminar", name="teacher_class_delete_post", dependencies=POST)
def class_delete(clase_id: int, request: Request, confirmo: str = Form(""), db=Depends(get_db),
                 usuario=Depends(docente_actual)):
    clase, curso = _clase(db, usuario, clase_id)
    curso_id = curso.id
    try:
        limpio = class_deletion.eliminar_clase(db, clase_id, confirmo=confirmo)
    except (ClaseInvalida, jobs.CursoEnUso) as error:
        db.rollback()
        clase, curso = _clase(db, usuario, clase_id)
        return _pagina_eliminar_clase(request, db, clase, curso, str(error))
    except (IntegrityError, OSError):
        db.rollback()
        clase, curso = _clase(db, usuario, clase_id)
        return _pagina_eliminar_clase(request, db, clase, curso,
            "No se pudo eliminar la clase. Se conservaron sus datos; pide al administrador que revise los archivos y referencias.")
    if not limpio:
        return page(request, "teacher/class_deleted.html", {
            "page_title": "Clase eliminada", "active_nav": "curso", "curso": curso})
    return volver(request, "teacher_course", curso_id=curso_id, ok="clase_eliminada")


@router.post("/clases/{clase_id}/temas", name="teacher_class_topics", dependencies=POST)
async def class_topics(clase_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    clase, _ = _clase(db, usuario, clase_id)
    formulario = await request.form()
    try:
        classes.ajustar_temas(db, clase, [int(t) for t in formulario.getlist("tema_id") if str(t).isdigit()])
    except ClaseInvalida as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return _ir_a_clase(request, clase.id, ok="guardado", ancla="temas")


@router.post("/clases/{clase_id}/reintentar", name="teacher_class_retry", dependencies=POST)
def class_retry(clase_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    clase, _ = _clase(db, usuario, clase_id)
    try:
        classes.reintentar(db, clase)
    except ClaseInvalida as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return _ir_a_clase(request, clase.id, ok="reintento")


@router.post("/clases/{clase_id}/publicar", name="teacher_class_publish", dependencies=POST)
def class_publish(clase_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    clase, _ = _clase(db, usuario, clase_id)
    validation.publicar(db, clase.id, usuario.id)
    db.commit()
    return _ir_a_clase(request, clase.id, ok="publicada")


@router.post("/retos/{reto_id}/aprobar", name="teacher_approve", dependencies=POST)
def approve(reto_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    reto, clase, _ = _reto(db, usuario, reto_id)
    try:
        validation.aprobar(db, reto, usuario.id)
    except ClaseInvalida as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return _ir_a_clase(request, clase.id, ok="aprobado", ancla=f"reto-{reto.id}")


@router.post("/retos/{reto_id}/rechazar", name="teacher_reject", dependencies=POST)
def reject(reto_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    reto, clase, _ = _reto(db, usuario, reto_id)
    try:
        nuevo = validation.rechazar(db, reto, usuario.id)
    except ClaseInvalida as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return _ir_a_clase(request, clase.id, ok="rechazado", ancla=f"reto-{nuevo.id}" if nuevo else None)


@router.post("/retos/{reto_id}/reintentar", name="teacher_reto_retry", dependencies=POST)
def reto_retry(reto_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    reto, clase, _ = _reto(db, usuario, reto_id)
    try:
        nuevo = validation.reintentar_generacion(db, reto, usuario.id)
    except ClaseInvalida as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return _ir_a_clase(request, clase.id, ancla=f"reto-{nuevo.id}")


@router.get("/retos/{reto_id}/editar", name="teacher_edit")
def edit_form(reto_id: int, request: Request, nivel: str = "intermedio", db=Depends(get_db),
              usuario=Depends(docente_actual)):
    reto, clase, curso = _reto(db, usuario, reto_id)
    tema = db.get(Tema, reto.tema_id)
    versiones = validation.versiones_vigentes(db, reto)
    if nivel not in levels.NIVELES or levels.indice(nivel) > levels.indice(tema.nivel_maximo):
        nivel = next(iter(versiones), "intermedio")
    return page(request, "teacher/edit.html", {
        "page_title": "Editar reto", "active_nav": "curso", "curso": curso, "clase": clase, "reto": reto, "tema": tema,
        "nivel": nivel, "versiones": versiones, "campos": _campos(versiones.get(nivel), nivel=nivel),
        "error_comun": reto.error_comun})


@router.post("/retos/{reto_id}/editar", name="teacher_edit_post", dependencies=POST)
async def edit(reto_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    reto, clase, curso = _reto(db, usuario, reto_id)
    datos = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    nivel = datos.get("nivel", "intermedio")
    try:
        estaba_retirado = reto.estado == "retirado"
        validation.editar(db, reto, usuario.id, nivel, datos, datos.get("error_comun"))
        if estaba_retirado:
            db.execute(RetoReporte.__table__.delete().where(RetoReporte.reto_id == reto.id))
            validation.auditar(db, reto.id, "reactivo", usuario.id, "Corregido desde la bandeja")
    except ClaseInvalida as error:
        db.rollback()
        versiones = validation.versiones_vigentes(db, reto)
        return page(request, "teacher/edit.html", {
            "page_title": "Editar reto", "active_nav": "curso", "curso": curso, "clase": clase, "reto": reto,
            "tema": db.get(Tema, reto.tema_id), "nivel": nivel, "versiones": versiones, "campos": _campos(enviado=datos),
            "error_comun": datos.get("error_comun", ""), "error": str(error)}, status_code=400)
    db.commit()
    if clase is None:
        return volver(request, "teacher_review", curso_id=curso.id, ok="guardado")
    return _ir_a_clase(request, clase.id, ok="guardado", ancla=f"reto-{reto.id}")


@router.get("/clases/{clase_id}/retos/nuevo", name="teacher_own")
def own_form(clase_id: int, request: Request, reemplaza: int | None = None, db=Depends(get_db),
             usuario=Depends(docente_actual)):
    clase, curso = _clase(db, usuario, clase_id)
    reemplazado = db.get(Reto, reemplaza) if reemplaza else None
    if reemplazado is not None and reemplazado.clase_id != clase.id:
        reemplazado = None
    return page(request, "teacher/own.html", {
        "page_title": "Agregar mi propio reto", "active_nav": "curso", "curso": curso, "clase": clase,
        "reemplaza": reemplazado, "campos": _campos(), "enviado": None,
        "temas": [t for t, _ in classes.temas_de_clase(db, clase.id)] or
        db.scalars(select(Tema).where(Tema.curso_id == curso.id).order_by(Tema.orden)).all()})


@router.post("/clases/{clase_id}/retos/nuevo", name="teacher_own_post", dependencies=POST)
async def own(clase_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    clase, curso = _clase(db, usuario, clase_id)
    datos = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    reemplaza = db.get(Reto, int(datos["reemplaza"])) if datos.get("reemplaza", "").isdigit() else None
    if reemplaza is not None and reemplaza.clase_id != clase.id:
        raise HTTPException(status_code=404, detail="No encontramos ese reto.")
    try:
        reto = validation.crear_propio(db, clase, usuario.id, tema_id=int(datos.get("tema_id") or 0),
                                       nivel=datos.get("nivel", "intermedio"), tipo=datos.get("tipo", "alternativas"),
                                       datos=datos, error_comun=datos.get("error_comun", ""), reemplaza=reemplaza)
    except (ClaseInvalida, ValueError) as error:
        db.rollback()
        return page(request, "teacher/own.html", {
            "page_title": "Agregar mi propio reto", "active_nav": "curso", "curso": curso, "clase": clase,
            "reemplaza": reemplaza, "error": str(error), "enviado": datos, "campos": _campos(enviado=datos),
            "temas": db.scalars(select(Tema).where(Tema.curso_id == curso.id).order_by(Tema.orden)).all()},
            status_code=400)
    db.commit()
    return _ir_a_clase(request, clase.id, ok="guardado", ancla=f"reto-{reto.id}")


@router.get("/clases/{clase_id}/reporte", name="teacher_class_report")
def class_report(clase_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    clase, curso = _clase(db, usuario, clase_id)
    return page(request, "teacher/class_report.html", {
        "page_title": f"Reporte · {clase.nombre}", "active_nav": "curso", "curso": curso, "clase": clase,
        "reporte": reports.reporte_clase(db, clase, cargar(db))})


@router.get("/cursos/{curso_id}/alumnos", name="teacher_students")
def students(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    return page(request, "teacher/students.html", {"page_title": "Alumnos", "active_nav": "alumnos", "curso": curso,
                                                   "alumnos": reports.lista_alumnos(db, curso.id)})


@router.get("/cursos/{curso_id}/alumnos/{alumno_id}", name="teacher_student")
def student(curso_id: int, alumno_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    alumno = db.get(Usuario, alumno_id)
    if alumno is None or alumno.id not in {a.id for a in reports.alumnos_del_curso(db, curso.id)}:
        raise HTTPException(status_code=404, detail="Ese alumno no está en el curso.")
    return page(request, "teacher/student.html", {
        "page_title": alumno.nombre_completo, "active_nav": "alumnos", "curso": curso, "alumno": alumno,
        "reporte": reports.reporte_alumno(db, curso.id, alumno)})


@router.get("/cursos/{curso_id}/alumnos/{alumno_id}/perfil", name="teacher_student_profile")
def student_profile(curso_id: int, alumno_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    from web.profile import mostrar
    curso = curso_de_docente(db, usuario, curso_id)
    alumno = db.get(Usuario, alumno_id)
    if alumno is None or alumno.id not in {a.id for a in reports.alumnos_del_curso(db, curso.id)}:
        raise HTTPException(status_code=404, detail="Ese alumno no está en el curso.")
    return mostrar(request, db, alumno, curso=curso,
                   origen=request.url_for("teacher_student", curso_id=curso.id, alumno_id=alumno.id))


@router.get("/cursos/{curso_id}/riesgo", name="teacher_risk")
def risk_panel(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    filas = risk.evaluar(db, curso.id, cargar(db))
    db.commit()
    return page(request, "teacher/risk.html", {"page_title": "Alumnos en riesgo", "active_nav": "riesgo",
                                               "curso": curso, "filas": filas, "params": cargar(db)})


@router.post("/cursos/{curso_id}/riesgo/{senal_id}/contactado", name="teacher_risk_contacted", dependencies=POST)
def risk_contacted(curso_id: int, senal_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    try:
        risk.marcar_contactado(db, senal_id, curso.id, usuario.id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    db.commit()
    return volver(request, "teacher_risk", curso_id=curso.id, ok="contactado")


@router.get("/cursos/{curso_id}/revision", name="teacher_review")
def review_inbox(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    filas = review.pendientes(db, curso.id)
    intentos = {r.intento_id: db.get(Intento, r.intento_id) for r in filas if r.intento_id}
    retos = {r.reto_id: db.get(Reto, r.reto_id) for r in filas if r.reto_id}
    versiones = {i.id: db.get(RetoVersion, i.reto_version_id) for i in intentos.values() if i}
    alumnos = {r.alumno_id: db.get(Usuario, r.alumno_id) for r in filas if r.alumno_id}
    return page(request, "teacher/review.html", {
        "page_title": "Bandeja de revisión", "active_nav": "revision", "curso": curso, "filas": filas,
        "intentos": intentos, "retos": retos, "versiones": versiones, "alumnos": alumnos, "etiqueta": review.ETIQUETA})


@router.post("/revisiones/{revision_id}", name="teacher_review_resolve", dependencies=POST)
def review_resolve(revision_id: int, request: Request, accion: str = Form(...), resultado: str = Form(""),
                   nota: str = Form(""), db=Depends(get_db), usuario=Depends(docente_actual)):
    revision = db.get(Revision, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="No encontramos esa revisión.")
    curso = curso_de_docente(db, usuario, revision.curso_id)
    try:
        if accion == "corregir":
            review.resolver_calificacion(db, revision, usuario.id, resultado, nota, cargar(db))
        elif accion == "mantener":
            review.resolver_calificacion(db, revision, usuario.id, None, nota, cargar(db))
        elif accion == "reactivar":
            validation.reactivar(db, db.get(Reto, revision.reto_id), usuario.id)
            review.resolver_simple(db, revision, usuario.id, "resuelta", nota or "Reto reactivado.")
        elif accion == "rechazar_reto":
            validation.rechazar(db, db.get(Reto, revision.reto_id), usuario.id)
            review.resolver_simple(db, revision, usuario.id, "resuelta", nota or "Reto rechazado y reemplazado.")
        elif accion in ("resuelta", "desestimada"):
            review.resolver_simple(db, revision, usuario.id, accion, nota)
        else:
            raise review.RevisionInvalida("Acción inválida.")
    except (review.RevisionInvalida, ClaseInvalida) as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "teacher_review", curso_id=curso.id, ok="resuelta")


@router.get("/cursos/{curso_id}/malla", name="teacher_curriculum")
def curriculum_view(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    temas = db.scalars(select(Tema).where(Tema.curso_id == curso.id).order_by(Tema.orden)).all()
    return page(request, "teacher/curriculum.html", {
        "page_title": "Malla y rúbricas", "active_nav": "malla", "curso": curso, "temas": temas,
        "no_cubiertos": {t.id for t in reports.temas_no_cubiertos(db, curso.id)}})


@router.post("/temas/{tema_id}", name="teacher_topic", dependencies=POST)
async def topic(tema_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    tema = db.get(Tema, tema_id)
    if tema is None:
        raise HTTPException(status_code=404, detail="No encontramos ese tema.")
    curso = curso_de_docente(db, usuario, tema.curso_id)
    datos = await request.form()
    rubrica = [{"criterio": str(datos.get(f"criterio_{i}", "")).strip()[:200],
                "descripcion": str(datos.get(f"descripcion_{i}", "")).strip()[:500]} for i in range(1, 5)]
    try:
        curriculum.ajustar_tema(db, tema, objetivo=str(datos.get("objetivo", "")),
                                nivel_maximo=str(datos.get("nivel_maximo", "")),
                                es_fundamental=datos.get("es_fundamental") == "si", rubrica=rubrica)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "teacher_curriculum", curso_id=curso.id, ok="guardado", ancla=f"tema-{tema.id}")


@router.get("/cursos/{curso_id}/podio", name="teacher_podium")
def podium(curso_id: int, request: Request, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    return page(request, "teacher/podium.html", {"page_title": "Podio del curso", "active_nav": "podio",
                                                 "curso": curso, "podio": ledger.podio(db, curso.id)})
