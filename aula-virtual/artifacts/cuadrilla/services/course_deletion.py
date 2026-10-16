"""Explicit administrator purge of one course; normal ledger operations stay append-only."""

import logging
import re
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import String, and_, cast, delete, func, or_, select

from ai import jobs
from config import settings
from db.models import (
    AgendaRepaso, AuditoriaReto, Clase, ClaseTema, Curso, DominioTema, FuenteSemanal, Inscripcion, Intento,
    LlamadaIA, Mensaje, Movimiento, Quiz, QuizItem, Reto, RetoReporte, RetoSemanal,
    RetoSemanalAlumno, RetoVersion, ResumenClase, Revision, SenalRiesgo, TareaHecha, Tema, Usuario,
)
from services import ledger
from services.admin import AdminError

logger = logging.getLogger("aulavirtualdmc.eliminar_curso")


def _filtros(db, curso_id):
    temas = select(Tema.id).where(Tema.curso_id == curso_id)
    clases = select(Clase.id).where(Clase.curso_id == curso_id)
    retos = select(Reto.id).where(Reto.curso_id == curso_id)
    quizzes = select(Quiz.id).where(Quiz.curso_id == curso_id)
    semanales = select(RetoSemanal.id).where(RetoSemanal.curso_id == curso_id)
    referencias = [LlamadaIA.referencia == f"curso:{curso_id}",
                   LlamadaIA.referencia.like(f"curso:{curso_id}:%")]
    for modelo, prefijo in ((Clase, "clase"), (Reto, "reto"), (Intento, "intento"), (RetoSemanal, "semanal")):
        referencias.append(and_(func.split_part(LlamadaIA.referencia, ":", 1) == prefijo,
                                func.split_part(LlamadaIA.referencia, ":", 2).in_(
                                    select(cast(modelo.id, String)).where(modelo.curso_id == curso_id))))
    # Children first. A single DELETE handles the self-references between this course's challenges.
    return [
        (LlamadaIA, or_(*referencias)),
        (Revision, Revision.curso_id == curso_id),
        (Intento, Intento.curso_id == curso_id),
        (RetoSemanalAlumno, RetoSemanalAlumno.semanal_id.in_(semanales)),
        (FuenteSemanal, or_(FuenteSemanal.semanal_id.in_(semanales), FuenteSemanal.clase_id.in_(clases))),
        (QuizItem, QuizItem.quiz_id.in_(quizzes)),
        (Quiz, Quiz.curso_id == curso_id),
        (RetoSemanal, RetoSemanal.curso_id == curso_id),
        (DominioTema, DominioTema.tema_id.in_(temas)),
        (AgendaRepaso, AgendaRepaso.tema_id.in_(temas)),
        (TareaHecha, TareaHecha.clase_id.in_(clases)),
        (RetoReporte, RetoReporte.reto_id.in_(retos)),
        (AuditoriaReto, AuditoriaReto.reto_id.in_(retos)),
        (RetoVersion, RetoVersion.reto_id.in_(retos)),
        (Reto, Reto.curso_id == curso_id),
        (ClaseTema, ClaseTema.clase_id.in_(clases)),
        (ResumenClase, ResumenClase.clase_id.in_(clases)),
        (Clase, Clase.curso_id == curso_id),
        (Tema, Tema.curso_id == curso_id),
        (Movimiento, Movimiento.curso_id == curso_id),
        (Mensaje, Mensaje.curso_id == curso_id),
        (SenalRiesgo, SenalRiesgo.curso_id == curso_id),
        (Inscripcion, Inscripcion.curso_id == curso_id),
        (Curso, Curso.id == curso_id),
    ]


def _archivos(db, curso_id):
    nombres = set(db.scalars(select(Clase.fuente_archivo).where(
        Clase.curso_id == curso_id, Clase.fuente_archivo.is_not(None))))
    raiz = settings.UPLOAD_DIR.resolve()
    archivos = []
    for nombre in sorted(nombres):
        # Never traverse the upload root or remove a recording still used by another course.
        if not nombre or Path(nombre).name != nombre:
            raise AdminError("Una grabación tiene una ruta inválida. Corrígela antes de eliminar el curso.")
        ruta = raiz / nombre
        if ruta.resolve().parent != raiz or ruta.is_symlink():
            raise AdminError("Una grabación está fuera de la carpeta de cargas. Revisa el archivo antes de eliminar.")
        compartido = db.scalar(select(Clase.id).where(Clase.curso_id != curso_id,
                                                     Clase.fuente_archivo == nombre).limit(1))
        if compartido is None and ruta.is_file():
            archivos.append(ruta)
    return archivos


def resumen_eliminacion(db, curso: Curso):
    cantidades = {modelo.__tablename__: db.scalar(select(func.count()).select_from(modelo).where(filtro))
                  for modelo, filtro in _filtros(db, curso.id)}
    cantidades["archivos"] = len(_archivos(db, curso.id))
    cantidades["exp"] = db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
        Movimiento.curso_id == curso.id, Movimiento.tipo == "EXP"))
    cantidades["coins"] = db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
        Movimiento.curso_id == curso.id, Movimiento.tipo == "COINS"))
    return cantidades


def eliminar_curso(db, curso_id: int, *, nombre_confirmado: str, confirmo: str) -> bool:
    """Own the transaction and file staging. True means the purge also cleaned its recordings."""
    movidos = []
    carpeta = None
    with jobs.eliminando_curso(curso_id):
        try:
            curso = db.scalar(select(Curso).where(Curso.id == curso_id).with_for_update()
                              .execution_options(populate_existing=True))
            if curso is None:
                raise AdminError("El curso ya no existe.")
            if confirmo != "si" or nombre_confirmado.strip() != curso.nombre:
                raise AdminError("Escribe el nombre exacto del curso y confirma la eliminación definitiva.")
            trabajos = sum(db.scalar(select(func.count()).select_from(modelo).where(
                modelo.curso_id == curso_id, modelo.estado == estado))
                for modelo, estado in ((Clase, "procesando"), (Reto, "generando"),
                                       (RetoSemanal, "generando"), (Intento, "evaluando")))
            if trabajos or curso.propuesta_estado == "generando":
                raise AdminError("El curso tiene trabajo de IA pendiente. Espera a que termine antes de eliminarlo.")
            coins = db.execute(select(Movimiento.alumno_id, func.sum(Movimiento.cantidad)).where(
                Movimiento.curso_id == curso_id, Movimiento.tipo == "COINS")
                .group_by(Movimiento.alumno_id).order_by(Movimiento.alumno_id)).all()
            if coins:
                db.scalars(select(Usuario.id).where(Usuario.id.in_([u for u, _ in coins]))
                           .order_by(Usuario.id).with_for_update()).all()
            for alumno_id, cantidad in coins:
                if ledger.saldo_coins(db, alumno_id) - cantidad < 0:
                    raise AdminError("Hay Coins del curso que ya se canjearon. Corrige los canjes afectados en "
                                     "Administración → Canjes antes de eliminarlo; el saldo no puede quedar negativo.")
            filtros = _filtros(db, curso_id)
            archivos = _archivos(db, curso_id)
            if archivos:
                carpeta = Path(tempfile.mkdtemp(prefix=f".eliminar-{curso_id}-", dir=settings.UPLOAD_DIR))
                for origen in archivos:
                    destino = carpeta / origen.name
                    origen.rename(destino)
                    movidos.append((origen, destino))
            for modelo, filtro in filtros:
                # This explicit purge is the sole exception to the normal append-only ledger.
                db.execute(delete(modelo.__table__).where(filtro))
            db.commit()
        except BaseException:
            db.rollback()
            for origen, destino in reversed(movidos):
                destino.rename(origen)
            if carpeta is not None:
                carpeta.rmdir()
            raise
        if carpeta is not None:
            try:
                shutil.rmtree(carpeta)
            except OSError:
                logger.exception("Curso %s eliminado; quedan grabaciones por limpiar en %s", curso_id, carpeta)
                return False
    return True


def reconciliar_archivos_eliminados():
    """Finish post-commit cleanup, or restore staged files after an interrupted transaction."""
    from db.session import SessionLocal

    if not settings.UPLOAD_DIR.is_dir():
        return
    for carpeta in settings.UPLOAD_DIR.glob(".eliminar-*"):
        identificador = re.fullmatch(r"\.eliminar-(\d+)-[\w-]+", carpeta.name)
        if identificador is None or carpeta.is_symlink() or not carpeta.is_dir():
            continue
        curso_id = int(identificador.group(1))
        try:
            with jobs.eliminando_curso(curso_id):
                with SessionLocal() as db:
                    existe = db.scalar(select(Curso.id).where(Curso.id == curso_id)) is not None
                if not existe:
                    shutil.rmtree(carpeta)
                    continue
                for origen in carpeta.iterdir():
                    destino = settings.UPLOAD_DIR / origen.name
                    if origen.is_file() and not origen.is_symlink() and not destino.exists():
                        origen.rename(destino)
                if not any(carpeta.iterdir()):
                    carpeta.rmdir()
        except jobs.CursoEnUso:
            continue
        except OSError:
            logger.exception("No se pudo completar la limpieza o recuperación del curso %s", curso_id)
