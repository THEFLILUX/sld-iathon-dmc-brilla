"""Predetermined message queue (spec §11): shown in the platform, at most 2 per entry, once each."""

from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert

from db.models import AgendaRepaso, Clase, Inscripcion, Intento, Mensaje, Tema
from rules.calendar import ahora
from rules.messages import MAXIMO_AL_INGRESAR, PRIORIDAD, TEXTOS


def encolar(db, alumno_id: int, curso_id: int, tipo: str, referencia: str) -> None:
    db.execute(insert(Mensaje).values(
        alumno_id=alumno_id, curso_id=curso_id, tipo=tipo, texto=TEXTOS[tipo], referencia=referencia,
    ).on_conflict_do_nothing(constraint="mensaje_unico"))


def encolar_clase_nueva(db, clase: Clase) -> None:
    alumnos = db.scalars(select(Inscripcion.usuario_id).where(
        Inscripcion.curso_id == clase.curso_id, Inscripcion.rol_en_curso == "alumno",
    ))
    for alumno_id in alumnos:
        encolar(db, alumno_id, clase.curso_id, "clase_nueva", f"clase:{clase.id}")


def _eventos_al_ingresar(db, alumno_id: int, curso_id: int, semanal_disponible: bool, params) -> None:
    momento = ahora()
    hoy = momento.date().isoformat()
    vencido = db.scalar(select(func.count()).select_from(AgendaRepaso).join(Tema, Tema.id == AgendaRepaso.tema_id).where(
        AgendaRepaso.alumno_id == alumno_id, Tema.curso_id == curso_id, AgendaRepaso.proxima_fecha <= momento,
    ))
    if vencido:
        encolar(db, alumno_id, curso_id, "repaso", f"repaso:{hoy}")
    if semanal_disponible:
        encolar(db, alumno_id, curso_id, "reto_semanal", f"semana:{hoy}")
    ultima = db.scalar(select(func.max(Intento.creado_en)).where(
        Intento.alumno_id == alumno_id, Intento.curso_id == curso_id,
    ))
    if ultima is not None and momento - ultima >= timedelta(days=params.riesgo_inactividad_dias):
        encolar(db, alumno_id, curso_id, "inactividad", f"inactividad:{ultima.date().isoformat()}")


def mostrar_al_ingresar(db, alumno_id: int, curso_id: int, semanal_disponible: bool, params) -> list[Mensaje]:
    _eventos_al_ingresar(db, alumno_id, curso_id, semanal_disponible, params)
    prioridad = case({tipo: i for i, tipo in enumerate(PRIORIDAD)}, value=Mensaje.tipo)
    pendientes = db.scalars(select(Mensaje).where(
        Mensaje.alumno_id == alumno_id, Mensaje.curso_id == curso_id, Mensaje.estado == "pendiente",
    ).order_by(prioridad, Mensaje.creado_en.desc()).limit(MAXIMO_AL_INGRESAR).with_for_update(skip_locked=True)).all()
    momento = ahora()
    for mensaje in pendientes:
        mensaje.estado = "mostrado"
        mensaje.mostrado_en = momento
    return pendientes
