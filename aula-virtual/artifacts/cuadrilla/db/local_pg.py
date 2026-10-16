"""Embedded PostgreSQL for local development when DATABASE_URL is empty.

Uses the `pgserver` package (PostgreSQL binaries installed with pip; wheels for Python 3.11
and 3.12). Data lives in APP_DIR/.local/postgres and survives restarts. With a real server,
set DATABASE_URL instead.
"""

import logging
from pathlib import Path

logger = logging.getLogger("cuadrilla.db")
_SERVIDORES: dict[str, object] = {}


def uri(directorio: Path, *, borrar_al_salir: bool = False) -> str:
    try:
        import pgserver
    except ImportError as error:
        raise RuntimeError(
            "Falta DATABASE_URL y no está disponible la PostgreSQL embebida (pgserver, Python 3.11 o 3.12). "
            "Define DATABASE_URL en .env con tu PostgreSQL o ejecuta con Python 3.12 (`uv sync`)."
        ) from error
    clave = str(directorio.resolve())
    if clave not in _SERVIDORES:
        directorio.mkdir(parents=True, exist_ok=True)
        _SERVIDORES[clave] = pgserver.get_server(directorio, cleanup_mode="delete" if borrar_al_salir else "stop")
        logger.info("PostgreSQL embebida en %s", directorio)
    return _SERVIDORES[clave].get_uri()
