"""Idempotent startup records: the bootstrap administrator and, in DEMO_MODE, demo accounts and malla."""

from sqlalchemy import select

from auth.passwords import hash_password
from config import settings
from db.models import Usuario
from db.session import SessionLocal


def seed() -> None:
    with SessionLocal.begin() as db:
        if settings.ADMIN_DNI and settings.ADMIN_PASSWORD and not db.scalar(
                select(Usuario.id).where(Usuario.dni == settings.ADMIN_DNI)):
            db.add(Usuario(dni=settings.ADMIN_DNI, nombre="Administración", apellido="DMC", rol="admin",
                           password_hash=hash_password(settings.ADMIN_PASSWORD)))
        if settings.DEMO_MODE:
            from db import demo
            demo.cuentas_y_malla(db)
