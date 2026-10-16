"""Privacy guard for every AI call (PRD RF-65, HU-44): no DNI, names or contact data leave."""

import re
import time

from sqlalchemy import select

from ai.anonymize import EMAIL, Conocidos, conocidos_desde

_CACHE: dict = {"momento": 0.0, "valor": None}
CACHE_SEGUNDOS = 60


class PrivacyViolation(RuntimeError):
    """Raised before sending. The message never contains the offending value."""


def conocidos(forzar: bool = False) -> Conocidos:
    from db.models import Usuario
    from db.session import SessionLocal

    if not forzar and _CACHE["valor"] is not None and time.monotonic() - _CACHE["momento"] < CACHE_SEGUNDOS:
        return _CACHE["valor"]
    with SessionLocal() as db:
        valor = conocidos_desde(db.scalars(select(Usuario)).all())
    _CACHE.update(momento=time.monotonic(), valor=valor)
    return valor


def invalidar_cache() -> None:
    _CACHE.update(momento=0.0, valor=None)


def verificar(texto: str, datos: Conocidos) -> None:
    if EMAIL.search(texto):
        raise PrivacyViolation("La solicitud a la IA contenía un correo electrónico y se bloqueó.")
    for dni in datos.dnis:
        if re.search(rf"(?<!\w){re.escape(dni)}(?!\w)", texto):
            raise PrivacyViolation("La solicitud a la IA contenía un DNI y se bloqueó.")
    plegado = texto.casefold()
    for nombre in datos.nombres_completos:
        if re.search(rf"(?<!\w){re.escape(nombre.casefold())}(?!\w)", plegado):
            raise PrivacyViolation("La solicitud a la IA contenía el nombre de una persona y se bloqueó.")
