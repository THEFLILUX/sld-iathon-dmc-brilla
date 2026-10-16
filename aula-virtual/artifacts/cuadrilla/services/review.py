"""Teacher review inbox (PRD M9, spec D6): claims, anomalies, reported errors and tutor flags.

Nothing here punishes a student automatically. A corrected claim recalculates EXP and
mastery; Coins already paid are never subtracted.
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from db.models import Intento, Reto, RetoReporte, Revision, Tema
from rules import scoring
from rules.calendar import ahora
from services import ledger

ETIQUETA = {"reclamo": "Reclamo «No estoy de acuerdo»", "anomalia": "Anomalía", "error_reportado": "Error reportado",
            "marcado_ia": "Marcado por el tutor"}
ABIERTOS = ("definir", "caso")


class RevisionInvalida(ValueError):
    pass


def crear(db, *, curso_id: int, tipo: str, referencia: str, motivo: str, alumno_id=None, reto_id=None,
          intento_id=None) -> None:
    db.execute(insert(Revision).values(
        curso_id=curso_id, tipo=tipo, referencia=referencia[:60], motivo=motivo[:1000], alumno_id=alumno_id,
        reto_id=reto_id, intento_id=intento_id,
    ).on_conflict_do_nothing(constraint="revision_unica"))


def reclamar(db, alumno_id: int, intento: Intento, motivo: str) -> None:
    """'No estoy de acuerdo' (RF-28): only for graded open answers. The score stays until the teacher decides."""
    if intento.alumno_id != alumno_id or intento.tipo not in ABIERTOS or intento.estado != "completado":
        raise RevisionInvalida("Solo puedes reclamar la calificación de una respuesta abierta ya calificada.")
    crear(db, curso_id=intento.curso_id, tipo="reclamo", referencia=f"intento:{intento.id}", alumno_id=alumno_id,
          reto_id=intento.reto_id, intento_id=intento.id, motivo=motivo.strip() or "El alumno no está de acuerdo.")


def reportar_error(db, alumno_id: int, reto: Reto, motivo: str, params) -> bool:
    """3 reports from different students retire the challenge and send it to the inbox. Returns retired?"""
    db.execute(insert(RetoReporte).values(reto_id=reto.id, alumno_id=alumno_id, motivo=motivo.strip()[:500])
               .on_conflict_do_nothing(constraint="reporte_unico_por_alumno"))
    bloqueado = db.scalar(select(Reto).where(Reto.id == reto.id).with_for_update()
                          .execution_options(populate_existing=True))
    total = db.scalar(select(func.count()).select_from(RetoReporte).where(RetoReporte.reto_id == reto.id))
    if total >= params.reportes_retiro and bloqueado.estado in ("aprobado", "editado"):
        from services.validation import auditar
        bloqueado.estado = "retirado"
        auditar(db, reto.id, "retirado", None, f"{total} reportes de alumnos distintos")
        motivos = db.scalars(select(RetoReporte.motivo).where(RetoReporte.reto_id == reto.id)).all()
        crear(db, curso_id=reto.curso_id, tipo="error_reportado", referencia=f"reto:{reto.id}:r{reto.revision}",
              reto_id=reto.id, motivo=" · ".join(m for m in motivos if m) or f"{total} reportes de error")
        return True
    return False


def pendientes(db, curso_id: int) -> list[Revision]:
    return list(db.scalars(select(Revision).where(Revision.curso_id == curso_id).order_by(
        (Revision.estado != "pendiente"), Revision.creado_en.desc()).limit(200)))


def contar_pendientes(db, curso_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Revision).where(
        Revision.curso_id == curso_id, Revision.estado == "pendiente"))


def _cerrar(revision: Revision, usuario_id: int, estado: str, resolucion: str) -> None:
    revision.estado, revision.resolucion = estado, resolucion.strip()[:1000] or None
    revision.resuelto_por, revision.resuelto_en = usuario_id, ahora()


def resolver_calificacion(db, revision: Revision, usuario_id: int, nuevo_resultado: str | None, nota: str, params):
    """Claim or tutor flag: correct the verdict (EXP difference + mastery) or dismiss it."""
    if revision.estado != "pendiente" or revision.tipo not in ("reclamo", "marcado_ia"):
        raise RevisionInvalida("Esta revisión ya fue resuelta.")
    if nuevo_resultado is None:
        _cerrar(revision, usuario_id, "desestimada", nota or "Se mantiene la calificación.")
        return
    if nuevo_resultado not in scoring.PUNTAJE_BASE:
        raise RevisionInvalida("Elige correcto, parcial o incorrecto.")
    intento = db.scalar(select(Intento).where(Intento.id == revision.intento_id).with_for_update())
    anterior = intento.exp
    intento.resultado = nuevo_resultado
    intento.puntaje = scoring.puntaje_intento(nuevo_resultado, intento.pistas_usadas)
    intento.exp = (scoring.exp_semanal(nuevo_resultado, intento.pistas_usadas, params) if intento.semanal_id else
                   scoring.exp_reto(intento.nivel, nuevo_resultado, intento.pistas_usadas, intento.es_repaso, params))
    if intento.feedback:
        intento.feedback = {**intento.feedback, "veredicto": nuevo_resultado,
                            "falto": intento.feedback.get("falto", "") + " (Calificación revisada por tu docente.)"}
    ledger.registrar(db, alumno_id=intento.alumno_id, curso_id=intento.curso_id, tipo="EXP", origen="ajuste_reclamo",
                     referencia=f"revision:{revision.id}", cantidad=intento.exp - anterior,
                     motivo=nota or "Calificación corregida por el docente", creado_por=usuario_id)
    db.flush()
    if intento.cuenta_para_dominio:
        from services.progress import actualizar_dominio
        actualizar_dominio(db, intento.alumno_id, db.get(Tema, intento.tema_id), params)
    _cerrar(revision, usuario_id, "resuelta", nota or f"Calificación corregida a {nuevo_resultado}.")


def resolver_simple(db, revision: Revision, usuario_id: int, estado: str, nota: str) -> None:
    if revision.estado != "pendiente":
        raise RevisionInvalida("Esta revisión ya fue resuelta.")
    if estado not in ("resuelta", "desestimada"):
        raise RevisionInvalida("Acción inválida.")
    _cerrar(revision, usuario_id, estado, nota)
