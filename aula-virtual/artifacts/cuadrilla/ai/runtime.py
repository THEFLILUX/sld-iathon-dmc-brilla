"""Immutable provider snapshots for a request/job; credentials always remain in server configuration."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import wraps

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from config import PROVEEDORES_IA, settings

_ACTUAL = ContextVar("configuracion_ia", default=None)


@dataclass(frozen=True)
class ConfigIA:
    proveedor: str
    modelo: str
    transcriptor: str
    modelo_audio: str
    razonamiento: str
    proyecto: str
    ubicacion: str
    opciones: dict
    version: int = 0

    @property
    def etiqueta(self):
        return {"openai": "OpenAI", "vertex": "Gemini · Vertex AI", "gemini": "Gemini · API"}[self.proveedor]

    def habilitada(self, entorno=None, *, audio=False):
        entorno = entorno or settings
        proveedor = self.transcriptor if audio else self.proveedor
        return bool(self.proyecto) if proveedor == "vertex" else bool(entorno.clave(proveedor))


def desde_entorno(entorno=None):
    e = entorno or settings
    opciones = {
        "modelo_openai": e.LLM_MODEL if e.LLM_PROVIDER == "openai" and e.LLM_MODEL else PROVEEDORES_IA["openai"]["modelo"],
        "audio_openai": e.TRANSCRIPTION_MODEL if e.TRANSCRIPTION_PROVIDER == "openai" and e.TRANSCRIPTION_MODEL else PROVEEDORES_IA["openai"]["transcripcion"],
        "modelo_vertex": e.LLM_MODEL if e.LLM_PROVIDER == "vertex" and e.LLM_MODEL else e.VERTEX_MODEL,
    }
    return ConfigIA(e.LLM_PROVIDER, e.LLM_MODEL or (e.VERTEX_MODEL if e.LLM_PROVIDER == "vertex" else PROVEEDORES_IA[e.LLM_PROVIDER]["modelo"]),
        e.TRANSCRIPTION_PROVIDER, e.TRANSCRIPTION_MODEL or PROVEEDORES_IA[e.TRANSCRIPTION_PROVIDER]["transcripcion"],
        e.LLM_REASONING_EFFORT, e.GOOGLE_CLOUD_PROJECT, e.GOOGLE_CLOUD_LOCATION, opciones)


def con_opciones(base, proveedor, opciones, version=0):
    modelo = opciones["modelo_openai" if proveedor == "openai" else "modelo_vertex"]
    return replace(base, proveedor=proveedor, modelo=modelo, transcriptor=proveedor,
                   modelo_audio=opciones["audio_openai"] if proveedor == "openai" else modelo,
                   opciones=dict(opciones), version=version)


def cargar(db=None):
    from db.models import ConfiguracionIA
    base = desde_entorno()
    if db is None:
        from db.session import SessionLocal
        with SessionLocal() as sesion:
            return cargar(sesion)
    try:
        fila = db.scalar(select(ConfiguracionIA).order_by(ConfiguracionIA.id.desc()).limit(1))
    except ProgrammingError as error:
        # Startup tools may run before create_all; never mask a connection or permissions error.
        if getattr(error.orig, "sqlstate", None) == "42P01":
            db.rollback()
            return base
        raise
    return con_opciones(base, fila.proveedor, fila.opciones, fila.id) if fila else base


def actual():
    return _ACTUAL.get() or cargar()


@contextmanager
def usar(configuracion=None):
    token = _ACTUAL.set(configuracion or actual())
    try:
        yield _ACTUAL.get()
    finally:
        _ACTUAL.reset(token)


def snapshot(funcion):
    @wraps(funcion)
    def ejecutar(*args, **kwargs):
        with usar():
            return funcion(*args, **kwargs)
    return ejecutar
