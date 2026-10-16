"""Student screens (spec §4): A1 course home, A2-A4 quiz, weekly challenge, A5 progress, A6 podium, A7 Coins."""

import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from auth.deps import alumno_actual, csrf_valido, curso_de_alumno, cursos_de
from db.models import Clase, Intento, Quiz, QuizItem, Reto, RetoSemanal, ResumenClase, Revision, TareaHecha
from db.session import get_db
from rules import redemption
from services import attempts, cursos_alumno, ledger, messages, progress, review, validation, weekly
from services import quiz as quiz_service
from services.params import cargar
from services.redemption import CanjeInvalido, canjear
from services.review import RevisionInvalida
from web.views import page, volver

router = APIRouter(prefix="/alumno")
POST = [Depends(csrf_valido)]


def _clase(db, curso_id: int, clase_id: int) -> Clase:
    clase = db.get(Clase, clase_id)
    if clase is None or clase.curso_id != curso_id or clase.estado != "publicada":
        raise HTTPException(status_code=404, detail="No encontramos ese quiz.")
    return clase


def _quiz(db, alumno_id: int, clase: Clase) -> Quiz | None:
    return db.scalar(select(Quiz).where(Quiz.alumno_id == alumno_id, Quiz.clase_id == clase.id))


def _cabecera(db, alumno, curso) -> dict:
    return {"curso": curso, "exp": ledger.exp_curso(db, alumno.id, curso.id), "coins": ledger.saldo_coins(db, alumno.id),
            "puesto": ledger.puesto(db, curso.id, alumno.id)}


@router.get("", name="student_home")
def home(request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    """Mis cursos: every course the student is (or was) enrolled in, with what is pending in each."""
    validation.publicar_vencidas(db)
    respuesta = page(request, "student/courses.html", {"page_title": "Mis cursos", "active_nav": "cursos",
                                                       **cursos_alumno.resumen(db, alumno)})
    db.commit()
    return respuesta


@router.get("/cursos/{curso_id}", name="student_course")
def course(curso_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    validation.publicar_vencidas(db)
    params = cargar(db)
    semanal = weekly.actual(db, curso)
    estado_semanal = weekly.estado_para(db, alumno.id, semanal)
    avisos = messages.mostrar_al_ingresar(db, alumno.id, curso.id, estado_semanal == "disponible", params)
    quizzes = quiz_service.lista_para_alumno(db, alumno.id, curso.id)
    resumenes = {r.clase_id: r for r in db.scalars(select(ResumenClase).where(
        ResumenClase.clase_id.in_([f["clase"].id for f in quizzes] or [0])))}
    clases_con_tarea = [f["clase"] for f in quizzes if f["clase"].tarea]
    hechas = set(db.scalars(select(TareaHecha.clase_id).where(
        TareaHecha.alumno_id == alumno.id, TareaHecha.clase_id.in_([c.id for c in clases_con_tarea] or [0]))))
    contexto = {"page_title": curso.nombre, "active_nav": "curso", "mensajes": avisos, "quizzes": quizzes,
                "semanal": semanal, "estado_semanal": estado_semanal, "tareas": clases_con_tarea, "hechas": hechas,
                "cursos": cursos_de(db, alumno), "resumenes": resumenes,
                **_cabecera(db, alumno, curso)}
    respuesta = page(request, "student/course.html", contexto)
    db.commit()
    return respuesta


@router.post("/cursos/{curso_id}/clases/{clase_id}/generar", name="student_generate", dependencies=POST)
def generate(curso_id: int, clase_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    if curso.estado != "activo":
        raise HTTPException(status_code=400, detail="El curso está cerrado.")
    clase = _clase(db, curso.id, clase_id)
    try:
        quiz_service.generar(db, alumno, clase, cargar(db))
    except quiz_service.QuizError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "student_quiz", curso_id=curso.id, clase_id=clase.id)


@router.get("/cursos/{curso_id}/clases/{clase_id}/quiz", name="student_quiz")
def quiz_view(curso_id: int, clase_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    clase = _clase(db, curso.id, clase_id)
    quiz = _quiz(db, alumno.id, clase)
    if quiz is None:
        return volver(request, "student_course", curso_id=curso.id)
    if quiz.estado == "completado":
        return volver(request, "student_quiz_final", curso_id=curso.id, clase_id=clase.id)
    return _pantalla_reto(request, db, alumno, curso, clase, quiz)


def _pantalla_reto(request, db, alumno, curso, clase, quiz, error: str | None = None, respuesta: str = "",
                   status_code: int = 200):
    item = quiz_service.item_actual(db, quiz)
    try:
        version, reto, tema = quiz_service.preparar(db, alumno, quiz, item)
    except quiz_service.QuizError as fallo:
        raise HTTPException(status_code=409, detail=str(fallo)) from fallo
    intento = quiz_service.intento_de(db, item)
    total = len(quiz_service.items(db, quiz))
    reclamado = intento is not None and db.scalar(select(Revision.id).where(
        Revision.tipo == "reclamo", Revision.referencia == f"intento:{intento.id}")) is not None
    contexto = {
        "page_title": f"Quiz · {clase.nombre}", "active_nav": "curso", "curso": curso, "clase": clase, "quiz": quiz,
        "item": item, "version": version, "reto": reto, "tema": tema, "intento": intento, "total": total,
        "etiqueta": quiz_service.etiqueta(quiz, item, total, clase.numero), "error": error, "respuesta": respuesta,
        "envio_id": secrets.token_urlsafe(16), "ultimo": item.orden == total, "reclamado": reclamado,
        "minimo": int(cargar(db).abierta_min_caracteres),
        "accion": {
            "pista": request.url_for("student_hint", curso_id=curso.id, clase_id=clase.id),
            "solucion": request.url_for("student_solution", curso_id=curso.id, clase_id=clase.id),
            "responder": request.url_for("student_answer", curso_id=curso.id, clase_id=clase.id),
            "seguir": request.url_for("student_next", curso_id=curso.id, clase_id=clase.id),
            "reportar": request.url_for("student_report", curso_id=curso.id, clase_id=clase.id),
            "desacuerdo": request.url_for("student_disagree", curso_id=curso.id, clase_id=clase.id),
            "salir": request.url_for("student_course", curso_id=curso.id),
        },
    }
    respuesta_http = page(request, "student/reto.html", contexto, status_code=status_code)
    db.commit()
    return respuesta_http


def _contexto_quiz(db, alumno, curso_id: int, clase_id: int):
    curso = curso_de_alumno(db, alumno, curso_id)
    clase = _clase(db, curso.id, clase_id)
    quiz = _quiz(db, alumno.id, clase)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Primero pulsa «Generar».")
    return curso, clase, quiz


@router.post("/cursos/{curso_id}/clases/{clase_id}/quiz/pista", name="student_hint", dependencies=POST)
def hint(curso_id: int, clase_id: int, request: Request, item_id: int = Form(...), db=Depends(get_db),
         alumno=Depends(alumno_actual)):
    curso, clase, quiz = _contexto_quiz(db, alumno, curso_id, clase_id)
    try:
        quiz_service.pedir_pista(db, quiz, item_id)
    except quiz_service.QuizError:
        pass
    db.commit()
    return volver(request, "student_quiz", curso_id=curso.id, clase_id=clase.id, ancla="pistas")


@router.post("/cursos/{curso_id}/clases/{clase_id}/quiz/solucion", name="student_solution", dependencies=POST)
def solution(curso_id: int, clase_id: int, request: Request, item_id: int = Form(...), db=Depends(get_db),
             alumno=Depends(alumno_actual)):
    curso, clase, quiz = _contexto_quiz(db, alumno, curso_id, clase_id)
    try:
        quiz_service.ver_solucion(db, quiz, item_id)
    except quiz_service.QuizError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "student_quiz", curso_id=curso.id, clase_id=clase.id, ancla="solucion")


@router.post("/cursos/{curso_id}/clases/{clase_id}/quiz/responder", name="student_answer", dependencies=POST)
def answer(curso_id: int, clase_id: int, request: Request, item_id: int = Form(...), respuesta: str = Form(""),
           envio_id: str = Form(...), db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso, clase, quiz = _contexto_quiz(db, alumno, curso_id, clase_id)
    params = cargar(db)
    try:
        intento, abierta = quiz_service.responder(db, alumno, quiz, item_id, respuesta, envio_id, params)
    except attempts.RespuestaInvalida as error:
        db.rollback()
        return _pantalla_reto(request, db, alumno, curso, clase, _quiz(db, alumno.id, clase), str(error), respuesta, 400)
    except quiz_service.QuizError:
        db.rollback()
        return volver(request, "student_quiz", curso_id=curso.id, clase_id=clase.id)
    db.commit()
    if abierta:
        # Graded now, outside any transaction; on failure it stays pending without penalty.
        attempts.evaluar_abierta(intento.id, params)
    return volver(request, "student_quiz", curso_id=curso.id, clase_id=clase.id, ancla="feedback")


@router.post("/cursos/{curso_id}/clases/{clase_id}/quiz/seguir", name="student_next", dependencies=POST)
def next_challenge(curso_id: int, clase_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso, clase, quiz = _contexto_quiz(db, alumno, curso_id, clase_id)
    try:
        terminado = quiz_service.seguir(db, quiz, cargar(db))
    except quiz_service.QuizError:
        db.rollback()
        return volver(request, "student_quiz", curso_id=curso.id, clase_id=clase.id)
    db.commit()
    destino = "student_quiz_final" if terminado else "student_quiz"
    return volver(request, destino, curso_id=curso.id, clase_id=clase.id)


@router.post("/cursos/{curso_id}/clases/{clase_id}/quiz/reportar", name="student_report", dependencies=POST)
def report(curso_id: int, clase_id: int, request: Request, reto_id: int = Form(...), motivo: str = Form(""),
           db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso, clase, quiz = _contexto_quiz(db, alumno, curso_id, clase_id)
    en_quiz = db.scalar(select(QuizItem.id).where(QuizItem.quiz_id == quiz.id, QuizItem.reto_id == reto_id))
    if en_quiz is None:
        raise HTTPException(status_code=404, detail="Ese reto no está en tu quiz.")
    review.reportar_error(db, alumno.id, db.get(Reto, reto_id), motivo, cargar(db))
    db.commit()
    return volver(request, "student_quiz", curso_id=curso.id, clase_id=clase.id, ok="reporte")


@router.post("/cursos/{curso_id}/clases/{clase_id}/quiz/desacuerdo", name="student_disagree", dependencies=POST)
def disagree(curso_id: int, clase_id: int, request: Request, intento_id: int = Form(...), motivo: str = Form(""),
             db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso, clase, _ = _contexto_quiz(db, alumno, curso_id, clase_id)
    intento = db.get(Intento, intento_id)
    if intento is None:
        raise HTTPException(status_code=404, detail="No encontramos esa respuesta.")
    try:
        review.reclamar(db, alumno.id, intento, motivo)
    except RevisionInvalida as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "student_quiz", curso_id=curso.id, clase_id=clase.id, ok="reclamo")


@router.get("/cursos/{curso_id}/clases/{clase_id}/quiz/final", name="student_quiz_final")
def quiz_final(curso_id: int, clase_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso, clase, quiz = _contexto_quiz(db, alumno, curso_id, clase_id)
    if quiz.estado != "completado":
        return volver(request, "student_quiz", curso_id=curso.id, clase_id=clase.id)
    lista = quiz_service.items(db, quiz)
    retos = [{"item": item, "intento": quiz_service.intento_de(db, item),
              "etiqueta": quiz_service.etiqueta(quiz, item, len(lista), clase.numero)} for item in lista]
    return page(request, "student/final.html", {
        "page_title": "¡Quiz completado!", "active_nav": "curso", "curso": curso, "clase": clase, "quiz": quiz,
        "resumen": quiz_service.resumen_final(db, quiz), "retos": retos})


def _semanal(db, curso) -> RetoSemanal | None:
    return weekly.actual(db, curso)


@router.get("/cursos/{curso_id}/semanal", name="student_weekly")
def weekly_view(curso_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    fila = _semanal(db, curso)
    estado = weekly.estado_para(db, alumno.id, fila)
    contexto = {"page_title": "Reto semanal", "active_nav": "curso", "curso": curso, "semanal": fila,
                "estado": estado, "envio_id": secrets.token_urlsafe(16), "minimo": int(cargar(db).abierta_min_caracteres)}
    if estado in ("disponible", "completado"):
        try:
            progreso, version, reto, tema = weekly.preparar(db, alumno, fila)
        except weekly.SemanalError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        intento = db.scalar(select(Intento).where(Intento.alumno_id == alumno.id, Intento.semanal_id == fila.id))
        contexto.update(progreso=progreso, version=version, reto=reto, tema=tema, intento=intento,
                        coins=weekly.coins_de(db, alumno.id, fila) if intento else 0)
    respuesta = page(request, "student/weekly.html", contexto)
    db.commit()
    return respuesta


@router.post("/cursos/{curso_id}/semanal/pista", name="student_weekly_hint", dependencies=POST)
def weekly_hint(curso_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    fila = _semanal(db, curso)
    try:
        weekly.pedir_pista(db, alumno.id, fila)
    except weekly.SemanalError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "student_weekly", curso_id=curso.id, ancla="pistas")


@router.post("/cursos/{curso_id}/semanal/responder", name="student_weekly_answer", dependencies=POST)
def weekly_answer(curso_id: int, request: Request, respuesta: str = Form(""), envio_id: str = Form(...),
                  db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    fila = _semanal(db, curso)
    try:
        weekly.responder(db, alumno, fila, respuesta, envio_id, cargar(db))
    except (weekly.SemanalError, attempts.RespuestaInvalida) as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "student_weekly", curso_id=curso.id, ancla="feedback")


@router.post("/cursos/{curso_id}/semanal/reportar", name="student_weekly_report", dependencies=POST)
def weekly_report(curso_id: int, request: Request, motivo: str = Form(""), db=Depends(get_db),
                  alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    fila = _semanal(db, curso)
    if fila is None or fila.reto_id is None:
        raise HTTPException(status_code=404, detail="No hay reto semanal.")
    review.reportar_error(db, alumno.id, db.get(Reto, fila.reto_id), motivo, cargar(db))
    db.commit()
    return volver(request, "student_weekly", curso_id=curso.id, ok="reporte")


@router.post("/cursos/{curso_id}/clases/{clase_id}/tarea", name="student_task_done", dependencies=POST)
def task_done(curso_id: int, clase_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    clase = _clase(db, curso.id, clase_id)
    if clase.tarea:
        # LISTO gives neither EXP nor Coins: it cannot be verified (RF-32).
        db.execute(insert(TareaHecha).values(alumno_id=alumno.id, clase_id=clase.id).on_conflict_do_nothing())
        db.commit()
    return volver(request, "student_course", curso_id=curso.id, ok="tarea", ancla="tareas")


@router.get("/cursos/{curso_id}/progreso", name="student_progress")
def my_progress(curso_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    return page(request, "student/progress.html", {
        "page_title": "Mi progreso", "active_nav": "progreso", "datos": progress.progreso_alumno(db, alumno.id, curso.id),
        "historial_exp": ledger.historial(db, alumno.id, "EXP", curso.id, 20), "origen": ledger.ORIGEN_ETIQUETA,
        **_cabecera(db, alumno, curso)})


@router.get("/cursos/{curso_id}/podio", name="student_podium")
def podium(curso_id: int, request: Request, db=Depends(get_db), alumno=Depends(alumno_actual)):
    curso = curso_de_alumno(db, alumno, curso_id)
    podio = ledger.podio(db, curso.id)
    return page(request, "student/podium.html", {
        "page_title": "Podio", "active_nav": "podio", "top": podio[:5],
        "mio": next((f for f in podio if f["alumno_id"] == alumno.id), None), **_cabecera(db, alumno, curso)})


@router.get("/coins", name="student_coins")
def coins(request: Request, porcentaje: int | None = None, db=Depends(get_db), alumno=Depends(alumno_actual)):
    params = cargar(db)
    saldo = ledger.saldo_coins(db, alumno.id)
    opciones = redemption.opciones(saldo, params)
    elegido = next((o for o in opciones if o["porcentaje"] == porcentaje and o["alcanza"]), None)
    return page(request, "student/coins.html", {
        "page_title": "Mis Coins", "active_nav": "coins", "saldo": saldo, "opciones": opciones, "elegido": elegido,
        "faltan": redemption.faltan_para_minimo(saldo, params),
        "nombres_cursos": {c.id: c.nombre for c in cursos_de(db, alumno)},
        "historial": ledger.historial(db, alumno.id, "COINS", limite=50), "origen": ledger.ORIGEN_ETIQUETA})


@router.post("/coins/canjear", name="student_redeem", dependencies=POST)
def redeem(request: Request, porcentaje: int = Form(...), confirmo: str = Form(""), db=Depends(get_db),
           alumno=Depends(alumno_actual)):
    if confirmo != "si":
        return RedirectResponse(str(request.url_for("student_coins")) + f"?porcentaje={porcentaje}", status_code=303)
    try:
        canjear(db, alumno, porcentaje, cargar(db))
    except CanjeInvalido as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return volver(request, "student_coins", ok="canje")
