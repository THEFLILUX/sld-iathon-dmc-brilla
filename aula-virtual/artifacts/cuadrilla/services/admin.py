"""Administrator operations (spec §6): users and roles, manual Coins, EXP adjustments, course closing."""

import csv
import io
import re
import secrets

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from ai import privacy
from auth.passwords import hash_password, validate_new_password
from db.models import ROLES, Curso, Inscripcion, Usuario
from rules import scoring
from rules.calendar import ahora
from services import ledger


class AdminError(ValueError):
    pass


def crear_usuario(db, *, dni: str, nombre: str, apellido: str, rol: str, password: str) -> Usuario:
    dni, nombre, apellido = dni.strip(), " ".join(nombre.split()), " ".join(apellido.split())
    if not re.fullmatch(r"[0-9A-Za-z]{8,12}", dni):
        raise AdminError("El DNI debe tener 8 dígitos (o hasta 12 caracteres para otros documentos).")
    if not nombre or not apellido or len(nombre) > 100 or len(apellido) > 100:
        raise AdminError("Nombre y apellido son obligatorios (hasta 100 caracteres).")
    if rol not in ROLES:
        raise AdminError("Rol inválido.")
    if error := validate_new_password(password):
        raise AdminError(error)
    if db.scalar(select(Usuario.id).where(Usuario.dni == dni)):
        raise AdminError("Ya existe un usuario con ese DNI.")
    usuario = Usuario(dni=dni, nombre=nombre, apellido=apellido, rol=rol, password_hash=hash_password(password))
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError as error:
        raise AdminError("Ya existe un usuario con ese DNI.") from error
    privacy.invalidar_cache()
    from services.profiles import crear
    crear(db, usuario)
    return usuario


def inscribir(db, usuario: Usuario, curso: Curso) -> None:
    rol = "docente" if usuario.rol == "docente" else "alumno"
    if usuario.rol == "admin":
        raise AdminError("El administrador ya ve todos los cursos.")
    db.execute(insert(Inscripcion).values(usuario_id=usuario.id, curso_id=curso.id, rol_en_curso=rol)
               .on_conflict_do_nothing())


def desinscribir(db, usuario_id: int, curso_id: int) -> None:
    fila = db.get(Inscripcion, (usuario_id, curso_id))
    if fila is not None:
        db.delete(fila)


def restablecer_password(db, usuario: Usuario, password: str) -> None:
    if error := validate_new_password(password):
        raise AdminError(error)
    usuario.password_hash = hash_password(password)
    from auth.sessions import cerrar_todas
    cerrar_todas(db, usuario.id)


def sumar_coins(db, admin_id: int, alumno: Usuario, cantidad: int, motivo: str) -> None:
    motivo = motivo.strip()
    if alumno.rol != "alumno":
        raise AdminError("Solo los alumnos reciben Coins.")
    if cantidad <= 0 or cantidad > 10_000:
        raise AdminError("La cantidad debe ser un número positivo (máximo 10 000).")
    if not motivo:
        raise AdminError("El motivo es obligatorio.")
    ledger.registrar(db, alumno_id=alumno.id, tipo="COINS", origen="ajuste_admin",
                     referencia=f"admin:{secrets.token_hex(8)}", cantidad=cantidad, motivo=motivo[:1000],
                     creado_por=admin_id)


def ajustar_exp(db, admin_id: int, alumno: Usuario, curso: Curso, cantidad: int, motivo: str) -> None:
    """For anomalies the teacher confirmed (EXP y Coins §8). Coins are never subtracted."""
    motivo = motivo.strip()
    if cantidad == 0 or abs(cantidad) > 100_000:
        raise AdminError("Indica un ajuste de EXP distinto de cero.")
    if not motivo:
        raise AdminError("El motivo es obligatorio.")
    ledger.registrar(db, alumno_id=alumno.id, curso_id=curso.id, tipo="EXP", origen="ajuste_admin",
                     referencia=f"admin:{secrets.token_hex(8)}", cantidad=cantidad, motivo=motivo[:1000],
                     creado_por=admin_id)


def cerrar_curso(db, admin_id: int, curso: Curso, params) -> list[dict]:
    """Final podium by course EXP; 120/90/60 Coins once; fewer places if fewer students have EXP."""
    curso = db.scalar(select(Curso).where(Curso.id == curso.id).with_for_update()
                      .execution_options(populate_existing=True))
    podio = [f for f in ledger.podio(db, curso.id) if f["exp"] > 0][:3]
    for fila in podio:
        alumno = db.get(Usuario, fila["alumno_id"])
        coins = scoring.coins_podio(fila["puesto"], params)
        if coins and not alumno.coins_pausadas:
            ledger.registrar(db, alumno_id=alumno.id, curso_id=curso.id, tipo="COINS", origen="podio_final",
                             referencia=f"curso:{curso.id}", cantidad=coins,
                             motivo=f"Puesto {fila['puesto']} del podio final", creado_por=admin_id)
    if curso.estado != "cerrado":
        curso.estado, curso.cerrado_en = "cerrado", ahora()
    return podio


def exportar_top3(db, curso: Curso) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["puesto", "nombre", "apellido", "dni", "exp"])
    for fila in [f for f in ledger.podio(db, curso.id) if f["exp"] > 0][:3]:
        alumno = db.get(Usuario, fila["alumno_id"])
        escritor.writerow([fila["puesto"], alumno.nombre, alumno.apellido, alumno.dni, fila["exp"]])
    return salida.getvalue()
