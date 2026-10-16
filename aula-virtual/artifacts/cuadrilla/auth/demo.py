"""Explicit, opt-in access to the five original presentation accounts only."""

import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict, deque

from sqlalchemy import select

from db.models import Usuario

CUENTAS = (
    ("alumno-1", "70000001", "alumno"),
    ("alumno-2", "70000002", "alumno"),
    ("docente-1", "20000001", "docente"),
    ("docente-2", "20000002", "docente"),
    ("administrador", "10000001", "admin"),
)
ROLES = {"alumno": "Alumno", "docente": "Docente", "admin": "Administrador"}
COOKIE = "dmc_demo_nonce"
_SECRETO = secrets.token_bytes(32)
_ACCESOS = OrderedDict()
_LOCK = threading.Lock()
LIMITE, VENTANA = 30, 15 * 60


def participantes(db):
    usuarios = {u.dni: u for u in db.scalars(select(Usuario).where(
        Usuario.dni.in_([dni for _, dni, _ in CUENTAS]), Usuario.activo.is_(True)))}
    return [(clave, usuarios[dni]) for clave, dni, rol in CUENTAS
            if dni in usuarios and usuarios[dni].rol == rol]


def firmar(nonce):
    return hmac.new(_SECRETO, nonce.encode(), hashlib.sha256).hexdigest()


def csrf_valido(nonce, firma):
    return bool(nonce and len(nonce) == 43 and len(firma) == 64
                and hmac.compare_digest(firmar(nonce), firma))


def admitir(ip):
    """Bounded per-IP limiter; do not reuse password failure counters."""
    momento = time.monotonic()
    with _LOCK:
        cola = _ACCESOS.pop(ip, deque())
        while cola and momento - cola[0] > VENTANA:
            cola.popleft()
        permitido = len(cola) < LIMITE
        if permitido:
            cola.append(momento)
        _ACCESOS[ip] = cola
        while len(_ACCESOS) > 4096:
            _ACCESOS.popitem(last=False)
        return permitido
