"""Dropout risk (PRD M9, spec D5): evaluated on demand; the teacher marks 'Contactado'."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from db.models import Clase, Inscripcion, Intento, SenalRiesgo, Usuario
from rules import risk
from rules.calendar import ahora
from services import progress


def evaluar(db, curso_id: int, params) -> list[dict]:
    """Current signals per student, persisted so the contact status survives."""
    momento = ahora()
    primera_publicacion = db.scalar(select(func.min(Clase.publicada_en)).where(
        Clase.curso_id == curso_id, Clase.estado == "publicada"))
    if primera_publicacion is None:
        return []
    alumnos = db.execute(select(Usuario, Inscripcion.creado_en).join(Inscripcion, Inscripcion.usuario_id == Usuario.id)
                         .where(Inscripcion.curso_id == curso_id, Inscripcion.rol_en_curso == "alumno",
                                Usuario.activo.is_(True)).order_by(Usuario.apellido, Usuario.nombre)).all()
    ultima = dict(db.execute(select(Intento.alumno_id, func.max(Intento.creado_en)).where(
        Intento.curso_id == curso_id).group_by(Intento.alumno_id)).all())
    resultado = []
    for alumno, inscrito in alumnos:
        hoy = progress.dominio_promedio_en(db, alumno.id, curso_id, momento, params)
        antes = progress.dominio_promedio_en(db, alumno.id, curso_id,
                                             momento - timedelta(days=params.riesgo_caida_dias), params)
        referencia = max(inscrito, primera_publicacion)
        for senal in risk.senales(ultima.get(alumno.id), referencia, hoy, antes, momento, params):
            db.execute(insert(SenalRiesgo).values(alumno_id=alumno.id, curso_id=curso_id, **senal)
                       .on_conflict_do_nothing(constraint="senal_unica"))
            fila = db.scalar(select(SenalRiesgo).where(
                SenalRiesgo.alumno_id == alumno.id, SenalRiesgo.curso_id == curso_id,
                SenalRiesgo.tipo == senal["tipo"], SenalRiesgo.referencia == senal["referencia"]))
            resultado.append({"alumno": alumno, "senal": fila, "ultima": ultima.get(alumno.id)})
    return resultado


def marcar_contactado(db, senal_id: int, curso_id: int, usuario_id: int) -> None:
    senal = db.get(SenalRiesgo, senal_id)
    if senal is None or senal.curso_id != curso_id:
        raise ValueError("No encontramos esa alerta.")
    senal.estado, senal.contactado_en, senal.contactado_por = "contactado", ahora(), usuario_id
