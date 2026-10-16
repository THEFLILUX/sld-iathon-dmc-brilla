"""In-process background jobs. One Uvicorn worker: class processing runs one at a time,
short single-challenge generations run on a second small pool so they do not wait behind it.

Jobs are submitted after the caller's transaction commits, so they always see its rows.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from threading import Condition

from sqlalchemy import event

logger = logging.getLogger("cuadrilla.jobs")
_CLASES = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cuadrilla-clases")
_RETOS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cuadrilla-retos")
# Tests run jobs inline to keep them deterministic.
SINCRONO = False
_CONDICION = Condition()
_USOS_CURSO: dict[int, int] = {}
_ELIMINANDO: set[int] = set()


class CursoEnUso(ValueError):
    pass


@contextmanager
def usando_curso(curso_id: int):
    """Allow concurrent AI work, while a deletion holds off new work for this course."""
    with _CONDICION:
        _CONDICION.wait_for(lambda: curso_id not in _ELIMINANDO)
        _USOS_CURSO[curso_id] = _USOS_CURSO.get(curso_id, 0) + 1
    try:
        yield
    finally:
        with _CONDICION:
            restantes = _USOS_CURSO[curso_id] - 1
            if restantes:
                _USOS_CURSO[curso_id] = restantes
            else:
                _USOS_CURSO.pop(curso_id)
            _CONDICION.notify_all()


@contextmanager
def eliminando_curso(curso_id: int):
    """One application process: do not delete underneath an active AI call."""
    with _CONDICION:
        if _USOS_CURSO.get(curso_id) or curso_id in _ELIMINANDO:
            raise CursoEnUso("El curso tiene trabajo en curso. Espera a que termine e inténtalo de nuevo.")
        _ELIMINANDO.add(curso_id)
    try:
        yield
    finally:
        with _CONDICION:
            _ELIMINANDO.remove(curso_id)
            _CONDICION.notify_all()


def _ejecutar(funcion, args, curso_id=None):
    from ai import runtime
    try:
        with (usando_curso(curso_id) if curso_id is not None else nullcontext()), runtime.usar(runtime.cargar()):
            funcion(*args)
    except Exception:
        logger.exception("Falló el trabajo en segundo plano %s", getattr(funcion, "__name__", funcion))


def enviar(funcion, *args, pesado: bool = False, curso_id: int | None = None):
    if SINCRONO:
        _ejecutar(funcion, args, curso_id)
        return None
    return (_CLASES if pesado else _RETOS).submit(_ejecutar, funcion, args, curso_id)


def al_confirmar(db, funcion, *args, pesado: bool = False, curso_id: int | None = None):
    """Submit the job only if and when the session's transaction commits."""
    event.listen(db, "after_commit", lambda _session: enviar(funcion, *args, pesado=pesado, curso_id=curso_id), once=True)
