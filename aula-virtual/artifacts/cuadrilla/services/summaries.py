"""Generate once per class, independently of quiz validation; recover interrupted work."""

import logging
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert

from ai import jobs
from config import settings
from db.models import Clase, ResumenClase
from rules.calendar import ahora

logger = logging.getLogger("aulavirtualdmc.resumenes")
MAX_INTENTOS = 3


def _reservar(db, resumen, clase):
    resumen.estado = "generando"
    resumen.intentos += 1
    resumen.error_mensaje = None
    resumen.proximo_intento_en = None
    resumen.actualizado_en = ahora()
    jobs.al_confirmar(db, generar, clase.id, pesado=True, curso_id=clase.curso_id)


def programar(db, clase):
    """After anonymization: repeated uploads/retries cannot charge for an existing summary."""
    if not settings.ai_enabled or not (clase.transcript_anon or clase.transcript or "").strip():
        return False
    nuevo = db.scalar(insert(ResumenClase).values(clase_id=clase.id, estado="pendiente", intentos=0)
                      .on_conflict_do_nothing().returning(ResumenClase.clase_id))
    if nuevo is None:
        return False
    _reservar(db, db.get(ResumenClase, clase.id), clase)
    return True


def reintentar(db, clase):
    from services.classes import ClaseInvalida
    if not settings.ai_enabled:
        raise ClaseInvalida("La IA no está disponible. Pide al administrador que revise su configuración.")
    if not (clase.transcript_anon or clase.transcript or "").strip():
        raise ClaseInvalida("Primero termina la transcripción de la clase.")
    if programar(db, clase):
        return
    resumen = db.scalar(select(ResumenClase).where(ResumenClase.clase_id == clase.id).with_for_update())
    if resumen.estado == "listo":
        raise ClaseInvalida("El resumen de esta clase ya está disponible.")
    if resumen.estado == "generando":
        raise ClaseInvalida("El resumen ya se está generando. Espera unos momentos.")
    resumen.intentos = 0
    _reservar(db, resumen, clase)


def generar(clase_id):
    from ai import proveedores
    from ai.llm import mensaje_seguro
    from ai.summaries import generar as resumir
    from db.session import SessionLocal

    with SessionLocal() as db:
        clase, resumen = db.get(Clase, clase_id), db.get(ResumenClase, clase_id)
        if clase is None or resumen is None or resumen.estado != "generando":
            return  # A queued job must never recreate a deleted class or its data.
        transcript = clase.transcript_anon or clase.transcript or ""
    try:
        contenido = resumir(transcript, referencia=f"clase:{clase_id}:resumen")
        with SessionLocal.begin() as db:
            resumen = db.get(ResumenClase, clase_id)
            if resumen is not None and resumen.estado == "generando":
                resumen.estado, resumen.contenido = "listo", contenido
                resumen.modelo = proveedores.nombre_modelo()
                resumen.error_mensaje, resumen.proximo_intento_en = None, None
                resumen.actualizado_en = ahora()
    except Exception as error:
        logger.warning("No se pudo resumir la clase %s (%s)", clase_id, type(error).__name__)
        with SessionLocal.begin() as db:
            resumen = db.get(ResumenClase, clase_id)
            if resumen is not None and resumen.estado == "generando":
                resumen.estado, resumen.error_mensaje = "error", mensaje_seguro(error)[:1000]
                resumen.actualizado_en = ahora()
                resumen.proximo_intento_en = (ahora() + timedelta(minutes=5)
                                             if resumen.intentos < MAX_INTENTOS else None)


def completar_pendientes(*, reinicio=False):
    """Backfill existing transcripts and retry failures with a bounded five-minute delay."""
    from db.session import SessionLocal
    with SessionLocal.begin() as db:
        if reinicio:
            db.execute(update(ResumenClase).where(ResumenClase.estado == "generando").values(
                estado="pendiente", proximo_intento_en=None))
        if not settings.ai_enabled:
            return
        existentes = db.scalars(select(Clase).where(
            Clase.estado != "procesando", Clase.transcript.is_not(None), Clase.transcript != "",
            ~select(ResumenClase.clase_id).where(ResumenClase.clase_id == Clase.id).exists()
        ).order_by(Clase.id).limit(10)).all()
        for clase in existentes:
            programar(db, clase)
        # Reserve under a lock so the timer and a teacher retry cannot schedule the same call twice.
        pendientes = db.scalars(select(ResumenClase).where(or_(
            ResumenClase.estado == "pendiente",
            (ResumenClase.estado == "error") & (ResumenClase.intentos < MAX_INTENTOS) &
            (ResumenClase.proximo_intento_en <= ahora())
        )).order_by(ResumenClase.clase_id).with_for_update(skip_locked=True).limit(10)).all()
        for resumen in pendientes:
            clase = db.get(Clase, resumen.clase_id)
            if clase is not None:
                _reservar(db, resumen, clase)
