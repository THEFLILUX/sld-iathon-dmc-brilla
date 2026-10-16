"""Server-side sessions: the cookie holds a random token, the database only its SHA-256."""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select

from config import settings
from db.models import Sesion, Usuario
from rules.calendar import ahora

COOKIE = "cuadrilla_sesion"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def crear(db, usuario: Usuario) -> str:
    momento = ahora()
    db.execute(delete(Sesion).where(Sesion.expira_en < momento))
    token = secrets.token_urlsafe(32)
    db.add(Sesion(
        token_hash=_digest(token), usuario_id=usuario.id, csrf=secrets.token_urlsafe(24),
        expira_en=momento + timedelta(hours=settings.SESSION_HOURS),
    ))
    return token


def buscar(db, token: str | None) -> tuple[Sesion, Usuario] | None:
    if not token or len(token) > 100:
        return None
    fila = db.execute(
        select(Sesion, Usuario).join(Usuario, Usuario.id == Sesion.usuario_id)
        .where(Sesion.token_hash == _digest(token), Sesion.expira_en > ahora(), Usuario.activo.is_(True))
    ).first()
    return (fila[0], fila[1]) if fila else None


def cerrar(db, token: str | None):
    if token:
        db.execute(delete(Sesion).where(Sesion.token_hash == _digest(token)))


def cerrar_todas(db, usuario_id: int):
    db.execute(delete(Sesion).where(Sesion.usuario_id == usuario_id))
