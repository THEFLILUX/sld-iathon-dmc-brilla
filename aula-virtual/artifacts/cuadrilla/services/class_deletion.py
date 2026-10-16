"""Hard-delete a class and its live dependencies, then rebuild derived learning state."""

import logging
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import and_, delete, func, or_, select, update

from ai import jobs
from config import settings
from db.models import (
    VERIFICABLES, AgendaRepaso, AuditoriaReto, Clase, ClaseTema, Curso, DominioTema, FuenteSemanal, Intento,
    LlamadaIA, Mensaje, Movimiento, Quiz, QuizItem, Reto, RetoReporte, RetoSemanal,
    RetoSemanalAlumno, RetoVersion, ResumenClase, Revision, SenalRiesgo, TareaHecha, Tema, Usuario,
)
from rules import levels, mastery, scoring, spacing
from rules.calendar import ahora
from services import ledger
from services.classes import ClaseInvalida
from services.params import cargar
from services.progress import ORIGEN_LEJANO

logger = logging.getLogger("aulavirtualdmc.eliminar_clase")


def _referencias(columna, grupos):
    return or_(*(and_(func.split_part(columna, ":", 1) == prefijo,
                     func.split_part(columna, ":", 2).in_([str(i) for i in ids]))
                 for prefijo, ids in grupos.items()))


def _plan(db, clase):
    """Materialize IDs before deleting: challenges can be reused in later quizzes/weekly work."""
    temas = set(db.scalars(select(ClaseTema.tema_id).where(ClaseTema.clase_id == clase.id)))
    retos = set(db.scalars(select(Reto.id).where(Reto.clase_id == clase.id)))
    # A teacher may have changed the mapping after these challenges were generated.
    temas.update(db.scalars(select(Reto.tema_id).where(Reto.id.in_(retos))))
    semanales = set()
    fuentes = select(FuenteSemanal.semanal_id)
    # Older weekly work predates source tracking. Purge possible derivatives conservatively.
    legado = and_(RetoSemanal.curso_id == clase.curso_id, RetoSemanal.tema_visto.is_(True),
                  RetoSemanal.tema_id.in_(temas), RetoSemanal.id.not_in(fuentes),
                  RetoSemanal.creado_en >= clase.publicada_en) if clase.publicada_en else False
    while True:
        anteriores = (len(retos), len(semanales))
        semanales.update(db.scalars(select(RetoSemanal.id).where(or_(
            RetoSemanal.reto_id.in_(retos), legado,
            RetoSemanal.id.in_(select(FuenteSemanal.semanal_id).where(FuenteSemanal.clase_id == clase.id))))))
        retos.update(i for i in db.scalars(select(RetoSemanal.reto_id).where(
            RetoSemanal.id.in_(semanales))) if i is not None)
        retos.update(db.scalars(select(Reto.id).where(or_(Reto.es_variante_de.in_(retos),
                                                          Reto.reemplaza_a.in_(retos)))))
        if anteriores == (len(retos), len(semanales)):
            break
    if db.scalar(select(Reto.id).where(Reto.id.in_(retos), Reto.curso_id != clase.curso_id).limit(1)):
        raise ClaseInvalida("Hay retos relacionados de otro curso. Pide al administrador que revise esas referencias.")
    versiones = set(db.scalars(select(RetoVersion.id).where(RetoVersion.reto_id.in_(retos))))
    propios = set(db.scalars(select(Quiz.id).where(Quiz.clase_id == clase.id)))
    items = set(db.scalars(select(QuizItem.id).where(or_(
        QuizItem.quiz_id.in_(propios), QuizItem.reto_id.in_(retos), QuizItem.reto_version_id.in_(versiones)))))
    afectados = set(db.scalars(select(QuizItem.quiz_id).where(QuizItem.id.in_(items)))) - propios
    # A pathological empty dependent quiz cannot be resumed, so purge that shell too.
    vacios = {q for q in afectados if not db.scalar(select(QuizItem.id).where(
        QuizItem.quiz_id == q, QuizItem.id.not_in(items)).limit(1))}
    quizzes = propios | vacios
    afectados -= vacios
    intentos = set(db.scalars(select(Intento.id).where(or_(
        Intento.reto_id.in_(retos), Intento.reto_version_id.in_(versiones),
        Intento.quiz_item_id.in_(items), Intento.semanal_id.in_(semanales)))))
    grupos = {"clase": {clase.id}, "reto": retos, "quiz": quizzes, "quiz_item": items,
              "intento": intentos, "semanal": semanales}
    revisiones = set(db.scalars(select(Revision.id).where(or_(
        Revision.reto_id.in_(retos), Revision.intento_id.in_(intentos),
        _referencias(Revision.referencia, {**grupos, "quiz": quizzes | afectados})))))
    grupos["revision"] = revisiones
    movimiento = and_(Movimiento.curso_id == clase.curso_id, _referencias(Movimiento.referencia, grupos))
    temas.update(db.scalars(select(Reto.tema_id).where(Reto.id.in_(retos))))
    temas.update(db.scalars(select(Intento.tema_id).where(Intento.id.in_(intentos))))
    return {"temas": temas, "retos": retos, "versiones": versiones, "semanales": semanales,
            "quizzes": quizzes, "afectados": afectados, "items": items, "intentos": intentos,
            "revisiones": revisiones, "grupos": grupos, "movimiento": movimiento}


def _archivos(db, clase):
    nombre = clase.fuente_archivo
    if not nombre:
        return []
    raiz = settings.UPLOAD_DIR.resolve()
    ruta = raiz / nombre
    if Path(nombre).name != nombre or ruta.is_symlink() or ruta.resolve().parent != raiz:
        raise ClaseInvalida("El archivo de la clase tiene una ruta inválida. Pide al administrador que la revise.")
    compartido = db.scalar(select(Clase.id).where(Clase.id != clase.id, Clase.fuente_archivo == nombre).limit(1))
    if compartido:
        raise ClaseInvalida("El archivo está compartido con otra clase. Pide al administrador que separe los archivos antes de eliminar.")
    return [ruta] if ruta.is_file() else []


def resumen_eliminacion(db, clase):
    plan = _plan(db, clase)
    resumen = {clave: len(plan[clave]) for clave in ("retos", "versiones", "semanales", "quizzes", "afectados", "intentos")}
    resumen["archivos"] = len(_archivos(db, clase))
    for tipo in ("EXP", "COINS"):
        resumen[tipo.lower()] = int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
            plan["movimiento"], Movimiento.tipo == tipo)))
    return resumen


def _reparar_quizzes(db, plan, params):
    """Remove a deleted lesson's review item without erasing another class's answers."""
    from services.quiz import items as items_quiz

    for quiz in db.scalars(select(Quiz).where(Quiz.id.in_(plan["afectados"])).with_for_update()):
        anteriores = items_quiz(db, quiz)
        borrados_antes = sum(i.id in plan["items"] for i in anteriores[:quiz.indice_actual])
        for item in anteriores:
            if item.id in plan["items"]:
                db.execute(delete(QuizItem.__table__).where(QuizItem.id == item.id))
        restantes = [i for i in anteriores if i.id not in plan["items"]]
        # Ascending shifts only move an item into a previously removed/vacated position.
        for orden, item in enumerate(restantes, 1):
            if item.orden != orden:
                db.execute(update(QuizItem.__table__).where(QuizItem.id == item.id).values(orden=orden))
        quiz.tiene_repaso = any(i.etiqueta == "repaso" for i in restantes)
        quiz.indice_actual = len(restantes) if quiz.estado == "completado" else min(
            max(0, quiz.indice_actual - borrados_antes), len(restantes) - 1)
        intentos = list(db.scalars(select(Intento).where(Intento.quiz_item_id.in_([i.id for i in restantes]))))
        quiz.puntaje_verificable = scoring.puntaje_quiz([
            (i.resultado, i.pistas_usadas) for i in intentos if i.tipo in VERIFICABLES and i.resultado])
        if quiz.estado == "completado":
            bonos = scoring.bonos_quiz([(i.resultado, i.pistas_usadas) for i in intentos], len(restantes), params)
            limites = {f"quiz:{quiz.id}:completado": bonos["completado"], f"quiz:{quiz.id}:perfecto": bonos["perfecto"],
                       f"quiz:{quiz.id}": scoring.coins_quiz(quiz.puntaje_verificable, quiz.nivel_coins, params)}
            for movimiento in db.scalars(select(Movimiento).where(
                    Movimiento.curso_id == quiz.curso_id, Movimiento.alumno_id == quiz.alumno_id,
                    Movimiento.origen == "quiz", Movimiento.referencia.in_(limites))):
                cantidad = min(movimiento.cantidad, limites[movimiento.referencia])
                if cantidad:
                    db.execute(update(Movimiento.__table__).where(Movimiento.id == movimiento.id).values(cantidad=cantidad))
                else:
                    db.execute(delete(Movimiento.__table__).where(Movimiento.id == movimiento.id))
        quiz.exp_obtenido = sum(i.exp for i in intentos) + int(db.scalar(select(
            func.coalesce(func.sum(Movimiento.cantidad), 0)).where(Movimiento.alumno_id == quiz.alumno_id,
            Movimiento.tipo == "EXP", Movimiento.origen == "quiz", Movimiento.referencia.in_(
                [f"quiz:{quiz.id}:completado", f"quiz:{quiz.id}:perfecto"]))))
        quiz.coins_obtenidas = int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
            Movimiento.alumno_id == quiz.alumno_id, Movimiento.tipo == "COINS",
            Movimiento.origen == "quiz", Movimiento.referencia == f"quiz:{quiz.id}")))
        quiz.puesto_inicial = None  # The old baseline included the erased class's EXP.
    db.flush()


def _reconstruir_progreso(db, temas, params):
    """Replay remaining evidence; do not retain mastery/spacing inherited from deleted answers."""
    pares = set(db.execute(select(DominioTema.alumno_id, DominioTema.tema_id).where(DominioTema.tema_id.in_(temas))).all())
    pares.update(db.execute(select(AgendaRepaso.alumno_id, AgendaRepaso.tema_id).where(AgendaRepaso.tema_id.in_(temas))).all())
    intentos = list(db.scalars(select(Intento).where(Intento.tema_id.in_(temas), Intento.estado == "completado",
                                                   Intento.cuenta_para_dominio.is_(True)).order_by(Intento.completado_en, Intento.id)))
    por_par = defaultdict(list)
    for intento in intentos:
        pares.add((intento.alumno_id, intento.tema_id))
        por_par[intento.alumno_id, intento.tema_id].append(intento)
    eventos = defaultdict(list)
    for alumno_id, tema_id, momento in db.execute(select(Quiz.alumno_id, Reto.tema_id, Quiz.completado_en)
            .join(QuizItem, QuizItem.quiz_id == Quiz.id).join(Reto, Reto.id == QuizItem.reto_id).where(
                Reto.tema_id.in_(temas), Quiz.estado == "completado", QuizItem.etiqueta == "clase",
                QuizItem.es_previo.is_(False)).distinct()):
        eventos[alumno_id, tema_id].append((momento, 0, None))
        pares.add((alumno_id, tema_id))
    for par in pares:
        db.execute(delete(DominioTema.__table__).where(DominioTema.alumno_id == par[0], DominioTema.tema_id == par[1]))
        db.execute(delete(AgendaRepaso.__table__).where(AgendaRepaso.alumno_id == par[0], AgendaRepaso.tema_id == par[1]))
        lista = por_par[par]
        agenda = None
        for i in lista:
            if i.origen in ("repaso", "semanal"):
                eventos[par].append((i.completado_en, i.id, i))
        for momento, _, intento in sorted(eventos[par], key=lambda e: (e[0], e[1])):
            if intento is None:
                if agenda is None:
                    agenda = (1, momento + timedelta(days=1), momento)
                continue
            actual = agenda[0] if agenda else 1
            db.execute(update(Intento.__table__).where(Intento.id == intento.id).values(intervalo_repaso=actual))
            intento.intervalo_repaso = actual
            intervalo = spacing.siguiente_intervalo(actual, intento.resultado, intento.pistas_usadas)
            agenda = (intervalo, momento + timedelta(days=intervalo), momento)
        if agenda:
            db.add(AgendaRepaso(alumno_id=par[0], tema_id=par[1], intervalo_actual=agenda[0],
                               proxima_fecha=agenda[1], actualizado_en=agenda[2]))
        if not lista:
            continue
        tema = db.get(Tema, par[1])
        nivel, desde = "basico", ORIGEN_LEJANO
        for indice, intento in enumerate(lista):
            ventana = [i.puntaje for i in lista[:indice + 1] if i.nivel == nivel and i.completado_en >= desde]
            nuevo = levels.nivel_guardado(nivel, tema.nivel_maximo, ventana, params)
            if nuevo != nivel:
                nivel, desde = nuevo, intento.completado_en
        valor = mastery.dominio([(i.nivel, i.puntaje) for i in lista], params)
        largo = any(i.resultado == "correcto" and (i.intervalo_repaso or 0) >= params.dominado_repaso_dias for i in lista)
        db.add(DominioTema(alumno_id=par[0], tema_id=par[1], nivel_actual=nivel, nivel_desde=desde,
                           dominio=valor, estado=mastery.estado(valor, nivel, tema.nivel_maximo, largo, params),
                           actualizado_en=ahora()))
    db.flush()


def eliminar_clase(db, clase_id, *, confirmo):
    """Own the DB transaction and file quarantine. False means a cleanup retry is needed."""
    clase = db.get(Clase, clase_id)
    if clase is None:
        raise ClaseInvalida("La clase ya no existe.")
    curso_id = clase.curso_id
    carpeta, movidos = None, []
    with jobs.eliminando_curso(curso_id):
        try:
            curso = db.scalar(select(Curso).where(Curso.id == curso_id).with_for_update())
            clase = db.scalar(select(Clase).where(Clase.id == clase_id).with_for_update()
                              .execution_options(populate_existing=True))
            if clase is None:
                raise ClaseInvalida("La clase ya no existe.")
            if confirmo != "si":
                raise ClaseInvalida("Confirma la eliminación definitiva de la clase.")
            trabajo = sum(db.scalar(select(func.count()).select_from(modelo).where(
                modelo.curso_id == curso_id, modelo.estado == estado)) for modelo, estado in (
                    (Clase, "procesando"), (Reto, "generando"), (Intento, "evaluando"), (RetoSemanal, "generando")))
            if trabajo or curso.propuesta_estado == 'generando':
                raise ClaseInvalida("Hay trabajo de IA en el curso. Espera a que termine antes de eliminar la clase.")
            plan = _plan(db, clase)
            cambio_agregado = bool(clase.publicada_en or plan['intentos'] or plan['quizzes'] or plan['semanales'] or
                                   db.scalar(select(Movimiento.id).where(plan['movimiento']).limit(1)))
            archivos = _archivos(db, clase)
            params = cargar(db)
            # Protect account balances against a simultaneous redemption or another course purge.
            alumnos = set(db.scalars(select(Movimiento.alumno_id).where(Movimiento.curso_id == curso_id)))
            alumnos.update(db.scalars(select(Quiz.alumno_id).where(Quiz.id.in_(plan['afectados']))))
            db.scalars(select(Usuario.id).where(Usuario.id.in_(alumnos)).order_by(Usuario.id).with_for_update()).all()
            saldos = dict(db.execute(select(Movimiento.alumno_id, func.sum(Movimiento.cantidad)).where(
                Movimiento.tipo == "COINS", Movimiento.alumno_id.in_(alumnos)).group_by(Movimiento.alumno_id)).all())
            # Keep these IDs alive until the shared reference filters have all run.
            db.execute(delete(LlamadaIA.__table__).where(_referencias(LlamadaIA.referencia, plan['grupos'])))
            db.execute(delete(Revision.__table__).where(Revision.id.in_(plan['revisiones'])))
            db.execute(delete(Movimiento.__table__).where(plan['movimiento']))
            db.execute(delete(Intento.__table__).where(Intento.id.in_(plan['intentos'])))
            _reparar_quizzes(db, plan, params)
            for alumno_id in saldos:
                if ledger.saldo_coins(db, alumno_id) < 0:
                    raise ClaseInvalida("Hay Coins de esta clase que ya se canjearon. Pide al administrador que corrija los canjes afectados antes de eliminarla.")
            for modelo, filtro in (
                (RetoSemanalAlumno, RetoSemanalAlumno.semanal_id.in_(plan['semanales'])),
                (FuenteSemanal, or_(FuenteSemanal.semanal_id.in_(plan['semanales']), FuenteSemanal.clase_id == clase_id)),
                (QuizItem, QuizItem.quiz_id.in_(plan['quizzes'])),
                (Quiz, Quiz.id.in_(plan['quizzes'])),
                (RetoSemanal, RetoSemanal.id.in_(plan['semanales'])),
                (TareaHecha, TareaHecha.clase_id == clase_id),
                (RetoReporte, RetoReporte.reto_id.in_(plan['retos'])),
                (AuditoriaReto, AuditoriaReto.reto_id.in_(plan['retos'])),
                (RetoVersion, RetoVersion.id.in_(plan['versiones'])),
                (Reto, Reto.id.in_(plan['retos'])),
                (ClaseTema, ClaseTema.clase_id == clase_id),
                (ResumenClase, ResumenClase.clase_id == clase_id),
                (Clase, Clase.id == clase_id),
                (Mensaje, and_(Mensaje.curso_id == curso_id, or_(
                    _referencias(Mensaje.referencia, {**plan['grupos'], 'quiz': plan['quizzes'] | plan['afectados']}),
                    Mensaje.tipo.in_((['inactividad', 'repaso', 'podio'] if cambio_agregado else []) +
                                     (['reto_semanal'] if plan['semanales'] else []))))),
                (SenalRiesgo, and_(SenalRiesgo.curso_id == curso_id, cambio_agregado)),
            ):
                db.execute(delete(modelo.__table__).where(filtro))
            # Ranking baselines are cached aggregates of the previous course EXP.
            if cambio_agregado:
                db.execute(update(Quiz.__table__).where(Quiz.curso_id == curso_id).values(puesto_inicial=None))
                _reconstruir_progreso(db, plan['temas'], params)
            if archivos:
                carpeta = Path(tempfile.mkdtemp(prefix=f".eliminar-clase-{curso_id}-{clase_id}-", dir=settings.UPLOAD_DIR))
                for origen in archivos:
                    destino = carpeta / origen.name
                    origen.rename(destino)
                    movidos.append((origen, destino))
            db.commit()
        except BaseException:
            db.rollback()
            for origen, destino in reversed(movidos):
                destino.rename(origen)
            if carpeta:
                carpeta.rmdir()
            raise
        if carpeta:
            try:
                shutil.rmtree(carpeta)
            except OSError:
                logger.exception("Clase %s eliminada; pendiente limpieza de archivos", clase_id)
                return False
    return True


def reconciliar_archivos_eliminados():
    from db.session import SessionLocal

    if not settings.UPLOAD_DIR.is_dir():
        return
    for carpeta in settings.UPLOAD_DIR.glob('.eliminar-clase-*'):
        match = re.fullmatch(r'\.eliminar-clase-(\d+)-(\d+)-[\w-]+', carpeta.name)
        if not match or carpeta.is_symlink() or not carpeta.is_dir():
            continue
        curso_id, clase_id = map(int, match.groups())
        try:
            with jobs.eliminando_curso(curso_id):
                with SessionLocal() as db:
                    existe = db.get(Clase, clase_id) is not None
                if not existe:
                    shutil.rmtree(carpeta)
                else:
                    for origen in carpeta.iterdir():
                        destino = settings.UPLOAD_DIR / origen.name
                        if origen.is_file() and not origen.is_symlink() and not destino.exists():
                            origen.rename(destino)
                    if not any(carpeta.iterdir()):
                        carpeta.rmdir()
        except jobs.CursoEnUso:
            continue
        except OSError:
            logger.exception("No se pudo completar limpieza o recuperación de la clase %s", clase_id)
