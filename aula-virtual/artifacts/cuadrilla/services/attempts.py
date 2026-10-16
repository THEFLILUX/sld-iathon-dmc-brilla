"""Grading and recording of one attempt (quiz challenge or weekly challenge).

Verifiable challenges are graded by rule, instantly, with feedback built from the
challenge's own explanation and hints. Open answers go to the AI grader; if it fails,
the attempt stays pending without penalty and is retried later.
"""

import logging
import re
import unicodedata

from sqlalchemy import select

from ai import privacy
from ai.anonymize import anonimizar
from db.models import Clase, Curso, Intento, Quiz, QuizItem, Reto, RetoVersion, Tema, Usuario
from rules import scoring
from rules.calendar import ahora
from services import ledger, progress, review

logger = logging.getLogger("cuadrilla.intentos")
MAX_RESPUESTA = 8000
REINTENTOS_IA = 3


class RespuestaInvalida(ValueError):
    pass


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().casefold()
    texto = re.sub(r"\s+", " ", texto).strip().strip(" .;:\"'`«»")
    return texto


def calificar_verificable(version: RetoVersion, respuesta: str) -> str:
    if version.tipo == "alternativas":
        return "correcto" if respuesta == version.respuesta_correcta else "incorrecto"
    if version.tipo == "completar":
        dada = _normalizar(respuesta)
        aceptadas = {_normalizar(a) for a in [version.respuesta_correcta, *version.respuestas_aceptadas] if a}
        compactas = {a.replace(" ", "") for a in aceptadas}
        return "correcto" if dada in aceptadas or dada.replace(" ", "") in compactas else "incorrecto"
    # Code challenges need the isolated runner (P1), which this version does not include.
    return "incorrecto"


def feedback_verificable(version: RetoVersion, reto: Reto, resultado: str, pistas_usadas: int) -> dict:
    """Fixed order (RF-27): verdict, what went well, what was missing (from the class), hint if it failed."""
    if resultado == "correcto":
        bien = ("¡Bien! Llegaste a la respuesta correcta." if pistas_usadas == 0 else
                "Lo lograste con apoyo de pistas. La próxima vez intenta primero desde tu memoria.")
        falto = version.explicacion
        pista = ""
    else:
        bien = "Respondiste desde tu memoria: ese esfuerzo ya ayuda a fijar el tema."
        falto = (f"Ojo con esto: {reto.error_comun}" if reto.error_comun else
                 "Repasa el punto de la clase en el que se basa este reto.")
        siguientes = [p for p in version.pistas[pistas_usadas:] if p]
        pista = siguientes[0] if siguientes else (version.pistas[-1] if version.pistas else "")
    return {"veredicto": resultado, "bien": bien, "falto": falto, "ejemplo_o_pista": pista,
            "fuente_usada": reto.fuente_ref[:400]}


def validar_respuesta(version: RetoVersion, respuesta: str, params) -> str:
    respuesta = (respuesta or "").strip()
    if not respuesta:
        raise RespuestaInvalida("Escribe o elige una respuesta antes de enviar.")
    if len(respuesta) > MAX_RESPUESTA:
        raise RespuestaInvalida("La respuesta supera 8000 caracteres. Resume tu solución.")
    if version.tipo == "alternativas" and respuesta not in version.opciones:
        raise RespuestaInvalida("Elige una de las alternativas.")
    if version.tipo in ("definir", "caso") and len(respuesta) < params.abierta_min_caracteres:
        raise RespuestaInvalida(
            f"Desarrolla un poco más tu respuesta (mínimo {int(params.abierta_min_caracteres)} caracteres).")
    return respuesta


def crear_intento(db, *, alumno: Usuario, curso_id: int, reto: Reto, version: RetoVersion, origen: str,
                  es_repaso: bool, cuenta_para_dominio: bool, respuesta: str, pistas: int, presentado_en,
                  envio_id: str, quiz_item_id: int | None = None, semanal_id: int | None = None) -> Intento:
    usado = db.scalar(select(Intento.id).where(Intento.alumno_id == alumno.id, Intento.envio_id == envio_id[:64]))
    if usado is not None:
        # A form replayed on another challenge: never a second attempt from the same submission.
        raise RespuestaInvalida("Este formulario ya se envió. Recarga la página para responder el reto actual.")
    momento = ahora()
    intento = Intento(
        alumno_id=alumno.id, curso_id=curso_id, reto_id=reto.id, reto_version_id=version.id,
        tema_id=reto.tema_id, nivel=version.nivel, tipo=version.tipo, origen=origen, es_repaso=es_repaso,
        quiz_item_id=quiz_item_id, semanal_id=semanal_id,
        # Personal data shared in an answer is not stored nor sent to the AI.
        respuesta=anonimizar(respuesta, privacy.conocidos()), estado="evaluando", pistas_usadas=pistas,
        tiempo_respuesta_ms=int((momento - presentado_en).total_seconds() * 1000) if presentado_en else None,
        cuenta_para_dominio=cuenta_para_dominio, envio_id=envio_id[:64],
    )
    db.add(intento)
    db.flush()
    return intento


def finalizar(db, intento: Intento, resultado: str, feedback: dict, params, calificacion: dict | None = None) -> None:
    """Score, EXP/Coins movements, mastery and agenda in one transaction. Idempotent."""
    if intento.estado == "completado":
        return
    alumno = db.get(Usuario, intento.alumno_id)
    tema = db.get(Tema, intento.tema_id)
    momento = ahora()
    intento.resultado, intento.feedback, intento.calificacion = resultado, feedback, calificacion
    intento.puntaje = scoring.puntaje_intento(resultado, intento.pistas_usadas)
    if resultado != "correcto":
        intento.error_tag = db.scalar(select(Reto.error_comun).where(Reto.id == intento.reto_id)) or ""
    intento.estado, intento.completado_en = "completado", momento
    if intento.semanal_id is not None:
        intento.exp = scoring.exp_semanal(resultado, intento.pistas_usadas, params)
        ledger.registrar(db, alumno_id=alumno.id, curso_id=intento.curso_id, tipo="EXP", origen="reto_semanal",
                         referencia=f"semanal:{intento.semanal_id}", cantidad=intento.exp)
        coins = scoring.coins_semanal(intento.nivel, resultado, intento.pistas_usadas, params)
        if coins and not alumno.coins_pausadas:
            ledger.registrar(db, alumno_id=alumno.id, curso_id=intento.curso_id, tipo="COINS",
                             origen="reto_semanal", referencia=f"semanal:{intento.semanal_id}", cantidad=coins)
    else:
        intento.exp = scoring.exp_reto(intento.nivel, resultado, intento.pistas_usadas, intento.es_repaso, params)
        ledger.registrar(db, alumno_id=alumno.id, curso_id=intento.curso_id, tipo="EXP", origen="reto",
                         referencia=f"quiz_item:{intento.quiz_item_id}", cantidad=intento.exp)
    agenda = intento.origen == "repaso" or (intento.origen == "semanal" and intento.cuenta_para_dominio)
    if agenda:
        intento.intervalo_repaso = progress.registrar_repaso(db, alumno.id, tema.id, resultado, intento.pistas_usadas)
    db.flush()
    if intento.cuenta_para_dominio:
        progress.actualizar_dominio(db, alumno.id, tema, params)


def evaluar_abierta(intento_id: int, params) -> None:
    from ai import jobs
    from db.session import SessionLocal

    with SessionLocal() as db:
        curso_id = db.scalar(select(Intento.curso_id).where(Intento.id == intento_id))
    if curso_id is not None:
        with jobs.usando_curso(curso_id):
            _evaluar_abierta(intento_id, params)


def _evaluar_abierta(intento_id: int, params) -> None:
    """AI grading outside any transaction, then finalize. Failure → pending, never a penalty."""
    from ai.components import evaluar_abierta as calificar
    from ai.context import select_context
    from db.session import SessionLocal

    with SessionLocal() as db:
        intento = db.get(Intento, intento_id)
        if intento is None or intento.estado == "completado":
            return
        version = db.get(RetoVersion, intento.reto_version_id)
        reto = db.get(Reto, intento.reto_id)
        tema = db.get(Tema, intento.tema_id)
        alumno = db.get(Usuario, intento.alumno_id)
        curso = db.get(Curso, intento.curso_id)
        clase = db.get(Clase, reto.clase_id) if reto.clase_id else None
        datos_version = {c: getattr(version, c) for c in ("tipo", "enunciado", "puntos_clave",
                                                           "respuesta_correcta", "explicacion")}
        fuentes = reto.fuente_ref + "\n\n" + select_context(clase.transcript_anon or "", version.enunciado, limit=3) \
            if clase else reto.fuente_ref
        argumentos = dict(alias=alumno.alias, curso=curso.nombre, tema={"nombre": tema.etiqueta, "objetivo": tema.objetivo},
                          version=datos_version, nivel=version.nivel, respuesta=intento.respuesta,
                          pistas_usadas=intento.pistas_usadas, fuentes=fuentes, referencia=f"intento:{intento_id}")
    try:
        evaluacion = calificar(**argumentos)
    except Exception as error:
        logger.warning("Calificación pendiente del intento %s (%s)", intento_id, type(error).__name__)
        with SessionLocal.begin() as db:
            intento = db.scalar(select(Intento).where(Intento.id == intento_id).with_for_update())
            if intento is not None and intento.estado != "completado":
                intento.estado = "pendiente"
                intento.reintentos_ia += 1
        return
    with SessionLocal.begin() as db:
        intento = db.scalar(select(Intento).where(Intento.id == intento_id).with_for_update())
        if intento is None or intento.estado == "completado":
            return
        finalizar(db, intento, evaluacion["resultado"], evaluacion["feedback"], params, evaluacion["calificacion"])
        if evaluacion["revisar"]:
            review.crear(db, curso_id=intento.curso_id, tipo="marcado_ia", referencia=f"intento:{intento.id}",
                         alumno_id=intento.alumno_id, reto_id=intento.reto_id, intento_id=intento.id,
                         motivo=evaluacion["motivo_revision"] or "La calificación tiene confianza baja.")
        if intento.quiz_item_id:
            from services import quiz as quiz_service
            item = db.get(QuizItem, intento.quiz_item_id)
            quiz = db.get(Quiz, item.quiz_id)
            if quiz.estado == "completado":
                quiz_service.cerrar(db, quiz, params)


def reintentar_pendientes(params, limite: int = 10) -> int:
    from db.session import SessionLocal
    from config import settings

    if not settings.ai_enabled:
        return 0
    with SessionLocal() as db:
        ids = db.scalars(select(Intento.id).where(
            Intento.estado == "pendiente", Intento.reintentos_ia < REINTENTOS_IA,
        ).order_by(Intento.creado_en).limit(limite)).all()
    for intento_id in ids:
        evaluar_abierta(intento_id, params)
    return len(ids)

