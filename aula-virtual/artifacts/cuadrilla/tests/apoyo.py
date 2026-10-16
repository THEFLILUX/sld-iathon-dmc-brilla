"""Shared test setup. Import this module first in every test module.

Each run creates a disposable PostgreSQL schema (search_path), builds the tables there,
truncates them between tests and drops the schema at exit. Development data is never
touched. Without TEST_DATABASE_URL/DATABASE_URL an embedded PostgreSQL starts in a
temporary directory. Background jobs run inline and no test calls a real AI provider.

Run from artifacts/cuadrilla:   uv run python -m unittest discover -s tests -v
"""

import atexit
import os
import re
import socket
import tempfile
import unittest
import uuid
from pathlib import Path

# Safety net: tests never reach the network. Only local sockets (PostgreSQL) are allowed.
_LOCALES = {"localhost", "127.0.0.1", "::1", None, ""}
_connect, _getaddrinfo = socket.socket.connect, socket.getaddrinfo


def _solo_local(sock, address):
    if isinstance(address, (str, bytes)) or address[0] in _LOCALES:
        return _connect(sock, address)
    raise ConnectionRefusedError(f"Las pruebas no salen a la red ({address[0]}).")


def _resolver_solo_local(host, *args, **kwargs):
    if host not in _LOCALES and not str(host).startswith("127."):
        raise socket.gaierror(f"Las pruebas no salen a la red ({host}).")
    return _getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _solo_local
socket.getaddrinfo = _resolver_solo_local

# A developer's .env may hold a DATABASE_URL or API keys: tests use neither.
BASE_URL = os.environ.get("TEST_DATABASE_URL", "")
if not BASE_URL:
    from db.local_pg import uri as _pg_embebida
    BASE_URL = _pg_embebida(Path(tempfile.mkdtemp(prefix="cuadrilla-test-pg-")), borrar_al_salir=True)
SCHEMA = f"cuadrilla_test_{uuid.uuid4().hex[:10]}"
os.environ["DATABASE_URL"] = BASE_URL + ("&" if "?" in BASE_URL else "?") + f"options=-csearch_path%3D{SCHEMA}"
os.environ["DEMO_MODE"] = "true"
os.environ["DEMO_PASSWORD"] = "clave-de-prueba"
for _clave in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "LLM_MODEL", "OPENAI_MODEL", "TRANSCRIPTION_MODEL"):
    os.environ[_clave] = ""
os.environ["LLM_PROVIDER"] = os.environ["TRANSCRIPTION_PROVIDER"] = "openai"
os.environ["DB_AUTO_CREATE"] = "false"
os.environ["BASE_PATH"] = "/"

import psycopg  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

_raw = make_url(BASE_URL).set(drivername="postgresql")
with psycopg.connect(_raw.render_as_string(hide_password=False), autocommit=True) as conexion:
    conexion.execute(f'CREATE SCHEMA "{SCHEMA}"')

from ai import jobs, privacy  # noqa: E402
from auth import passwords  # noqa: E402
from config import settings  # noqa: E402
from db.models import Base, Sesion, Usuario  # noqa: E402
from db.session import SessionLocal, engine  # noqa: E402

Base.metadata.create_all(engine)
jobs.SINCRONO = True
# Hashing is deliberately slow; tests only need it to be correct.
_hash_rapido = {}
_original_hash = passwords.hash_password


def _hash_cacheado(password):
    if password not in _hash_rapido:
        _hash_rapido[password] = _original_hash(password)
    return _hash_rapido[password]


passwords.hash_password = _hash_cacheado
import db.demo  # noqa: E402
import services.admin  # noqa: E402
db.demo.hash_password = _hash_cacheado
services.admin.hash_password = _hash_cacheado


@atexit.register
def _drop_schema():
    engine.dispose()
    with psycopg.connect(_raw.render_as_string(hide_password=False), autocommit=True) as conexion:
        conexion.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')


def limpiar():
    tablas = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conexion:
        conexion.execute(text(f"TRUNCATE {tablas} RESTART IDENTITY CASCADE"))
    privacy.invalidar_cache()


def configurar(caso: unittest.TestCase, **valores):
    """Change frozen settings for one test (restored afterwards)."""
    originales = {k: getattr(settings, k) for k in valores}
    for clave, valor in valores.items():
        object.__setattr__(settings, clave, valor)
    caso.addCleanup(lambda: [object.__setattr__(settings, k, v) for k, v in originales.items()])


def activar_ia(caso: unittest.TestCase, modelo):
    """Pretend an API key exists and route every LangChain chat model to a fake one."""
    from ai import proveedores
    configurar(caso, OPENAI_API_KEY="clave-falsa", GOOGLE_API_KEY="clave-falsa")
    original = proveedores.crear_chat
    proveedores.crear_chat = lambda **_kwargs: modelo
    caso.addCleanup(lambda: setattr(proveedores, "crear_chat", original))


class Caso(unittest.TestCase):
    def setUp(self):
        limpiar()

    def demo(self, actividad: bool = False):
        from db import demo
        with SessionLocal.begin() as db:
            demo.cuentas_y_malla(db)
            if actividad:
                demo.actividad(db)
        with SessionLocal() as db:
            return demo.curso_demo(db)

    def cliente(self, dni: str | None = None, password: str = "clave-de-prueba"):
        from fastapi.testclient import TestClient
        from main import app
        cliente = TestClient(app, follow_redirects=False)
        if dni:
            respuesta = cliente.post("/ingresar", data={"dni": dni, "password": password})
            self.assertEqual(respuesta.status_code, 303, respuesta.text[:500])
        return cliente

    def csrf(self, dni: str) -> str:
        with SessionLocal() as db:
            usuario = db.scalar(select(Usuario).where(Usuario.dni == dni))
            return db.scalar(select(Sesion.csrf).where(Sesion.usuario_id == usuario.id)
                             .order_by(Sesion.id.desc()).limit(1))

    def usuario(self, dni: str) -> Usuario:
        with SessionLocal() as db:
            return db.scalar(select(Usuario).where(Usuario.dni == dni))

    def aceptar_consentimiento(self, cliente, dni: str):
        respuesta = cliente.post("/consentimiento", data={"_csrf": self.csrf(dni), "acepto": "si"})
        self.assertEqual(respuesta.status_code, 303)


def texto_visible(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
