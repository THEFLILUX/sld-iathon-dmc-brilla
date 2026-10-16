"""EXP and Coins movements. Course EXP and the Coins balance are sums of movements."""

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert

from db.models import Inscripcion, Movimiento, Usuario


def registrar(db, *, alumno_id: int, tipo: str, origen: str, referencia: str, cantidad: int,
              curso_id: int | None = None, motivo: str = "", creado_por: int | None = None) -> bool:
    """Insert once per (student, type, origin, reference). A replay or reload does nothing."""
    if cantidad == 0:
        return False
    resultado = db.execute(
        insert(Movimiento).values(
            alumno_id=alumno_id, curso_id=curso_id, tipo=tipo, origen=origen, referencia=referencia,
            cantidad=cantidad, motivo=motivo, creado_por=creado_por,
        ).on_conflict_do_nothing(constraint="movimiento_unico").returning(Movimiento.id)
    ).scalar()
    return resultado is not None


def saldo_coins(db, alumno_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
        Movimiento.alumno_id == alumno_id, Movimiento.tipo == "COINS",
    )))


def exp_curso(db, alumno_id: int, curso_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
        Movimiento.alumno_id == alumno_id, Movimiento.curso_id == curso_id, Movimiento.tipo == "EXP",
    )))


def podio(db, curso_id: int) -> list[dict]:
    """All enrolled students by course EXP. Ties: whoever reached that total first."""
    exp = func.coalesce(func.sum(Movimiento.cantidad), 0)
    filas = db.execute(
        select(Usuario.id, Usuario.nombre, Usuario.apellido, exp.label("exp"),
               func.max(Movimiento.creado_en).label("alcanzado"))
        .join(Inscripcion, Inscripcion.usuario_id == Usuario.id)
        .outerjoin(Movimiento, and_(
            Movimiento.alumno_id == Usuario.id, Movimiento.curso_id == curso_id, Movimiento.tipo == "EXP",
        ))
        .where(Inscripcion.curso_id == curso_id, Inscripcion.rol_en_curso == "alumno", Usuario.activo.is_(True))
        .group_by(Usuario.id)
        .order_by(exp.desc(), func.max(Movimiento.creado_en).asc().nulls_last(), Usuario.apellido, Usuario.nombre)
    ).all()
    return [
        {"alumno_id": f.id, "nombre": f.nombre, "apellido": f.apellido, "exp": int(f.exp),
         "alcanzado": f.alcanzado, "puesto": i}
        for i, f in enumerate(filas, start=1)
    ]


def puesto(db, curso_id: int, alumno_id: int) -> int | None:
    return next((fila["puesto"] for fila in podio(db, curso_id) if fila["alumno_id"] == alumno_id), None)


def historial(db, alumno_id: int, tipo: str, curso_id: int | None = None, limite: int = 50):
    consulta = select(Movimiento).where(Movimiento.alumno_id == alumno_id, Movimiento.tipo == tipo)
    if curso_id is not None:
        consulta = consulta.where(Movimiento.curso_id == curso_id)
    return db.scalars(consulta.order_by(Movimiento.creado_en.desc(), Movimiento.id.desc()).limit(limite)).all()


ORIGEN_ETIQUETA = {
    "reto": "Reto", "quiz": "Quiz de clase", "reto_semanal": "Reto semanal", "podio_final": "Podio final",
    "ajuste_admin": "Ajuste del administrador", "ajuste_reclamo": "Reclamo resuelto", "canje": "Canje",
    "devolucion_canje": "Devolución de canje",
    "perfil": "Perfil completado",
}
