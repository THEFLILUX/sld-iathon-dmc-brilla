"""Weekly challenge (PRD M6, spec §7.3): one per course and week, Monday 00:00 Lima, same for everyone.

Any topic of the malla, seen or not; always verifiable; one level above the student's
level in that topic; one attempt; no teacher validation. Without AI it falls back to
an approved verifiable challenge of a seen topic.
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ai import jobs
from config import settings
from db.models import (
    VERIFICABLES, AgendaRepaso, Clase, ClaseTema, Curso, DominioTema, FuenteSemanal, Intento, Reto, RetoSemanal, RetoSemanalAlumno,
    RetoVersion, Tema, Usuario,
)
from rules import levels
from rules.calendar import ahora, fin_semana, semana_de
from rules.selection import sortear_tema
from services import attempts, ledger, messages, progress
from services.classes import crear_reto, tema_dict
from services.validation import USABLES, versiones_vigentes


class SemanalError(ValueError):
    pass


def actual(db, curso: Curso) -> RetoSemanal | None:
    """This week's challenge, creating (and generating) it on first access."""
    if curso.estado != "activo":
        return None
    semana = semana_de(ahora())
    fila = db.scalar(select(RetoSemanal).where(RetoSemanal.curso_id == curso.id, RetoSemanal.semana == semana))
    if fila is not None:
        return fila
    if not db.scalar(select(func.count()).select_from(Tema).where(Tema.curso_id == curso.id)):
        return None
    nuevo = db.execute(insert(RetoSemanal).values(curso_id=curso.id, semana=semana, estado="generando")
                       .on_conflict_do_nothing(constraint="reto_semanal_unico").returning(RetoSemanal.id)).scalar()
    fila = db.scalar(select(RetoSemanal).where(RetoSemanal.curso_id == curso.id, RetoSemanal.semana == semana))
    if nuevo is not None:
        _sortear(db, fila)
        if settings.ai_enabled:
            jobs.al_confirmar(db, generar, fila.id, curso_id=curso.id)
        else:
            _desde_banco(db, fila)
    return fila


def _sortear(db, fila: RetoSemanal) -> None:
    temas = db.scalars(select(Tema).where(Tema.curso_id == fila.curso_id)).all()
    momento = ahora()
    vencidos = dict(db.execute(select(AgendaRepaso.tema_id, func.count()).where(
        AgendaRepaso.tema_id.in_([t.id for t in temas]), AgendaRepaso.proxima_fecha <= momento,
    ).group_by(AgendaRepaso.tema_id)).all())
    promedios = dict(db.execute(select(DominioTema.tema_id, func.avg(DominioTema.dominio)).where(
        DominioTema.tema_id.in_([t.id for t in temas]), DominioTema.dominio.is_not(None),
    ).group_by(DominioTema.tema_id)).all())
    anterior = db.scalar(select(RetoSemanal.tema_id).where(
        RetoSemanal.curso_id == fila.curso_id, RetoSemanal.semana < fila.semana,
    ).order_by(RetoSemanal.semana.desc()).limit(1))
    candidatos = [{"id": t.id, "es_fundamental": t.es_fundamental, "vencidos": vencidos.get(t.id, 0),
                   "dominio": float(promedios[t.id]) if t.id in promedios else None} for t in temas]
    fila.tema_id = sortear_tema(candidatos, f"{fila.curso_id}:{fila.semana.isoformat()}", excluir=anterior)
    fila.tema_visto = fila.tema_id in progress.temas_vistos(db, fila.curso_id)


def _desde_banco(db, fila: RetoSemanal) -> None:
    """Fallback: an approved challenge with verifiable versions, preferring the drawn topic."""
    vistos = progress.temas_vistos(db, fila.curso_id)
    candidatos = db.scalars(select(Reto).join(Clase, Clase.id == Reto.clase_id).where(
        Reto.curso_id == fila.curso_id, Reto.uso == "clase", Reto.estado.in_(USABLES), Clase.estado == "publicada",
        Reto.tema_id.in_(list(vistos) or [0]),
    ).order_by((Reto.tema_id != (fila.tema_id or 0)), Reto.id)).all()
    for reto in candidatos:
        if any(v.tipo in VERIFICABLES for v in versiones_vigentes(db, reto).values()):
            fila.reto_id, fila.tema_id, fila.tema_visto, fila.estado = reto.id, reto.tema_id, True, "listo"
            return
    fila.estado, fila.error_mensaje = "error", "Esta semana no hay reto semanal disponible."


def _material(db, tema: Tema, visto: bool, fuentes=None) -> str:
    if not visto:
        hermanos = db.scalars(select(Tema).where(Tema.curso_id == tema.curso_id, Tema.nombre == tema.nombre)).all()
        return "Objetivo: " + tema.objetivo + "\nSubtemas de la malla: " + ", ".join(
            h.subtema for h in hermanos if h.subtema)
    from ai.context import select_context
    clases = db.scalars(select(Clase).join(ClaseTema, ClaseTema.clase_id == Clase.id).where(
        ClaseTema.tema_id == tema.id, Clase.estado == "publicada").order_by(Clase.id)).all()
    partes = [(c.id, select_context(c.transcript_anon or "", tema.nombre + " " + tema.objetivo, limit=4)) for c in clases]
    partes += [(c.id, (c.recursos_texto or "")[:6000]) for c in clases]
    salida = ""
    for clase_id, parte in partes:
        if not parte or len(salida) >= 40_000:
            continue
        prefijo = "\n\n" if salida else ""
        incluido = (prefijo + parte)[:40_000 - len(salida)]
        salida += incluido
        if fuentes is not None and len(incluido) > len(prefijo):
            fuentes.add(clase_id)
    return salida


def generar(semanal_id: int) -> None:
    from ai.components import generar_semanal
    from db.session import SessionLocal

    with SessionLocal() as db:
        fila = db.get(RetoSemanal, semanal_id)
        if fila is None or fila.estado != "generando" or fila.tema_id is None:
            return
        tema = db.get(Tema, fila.tema_id)
        maximo = tema.nivel_maximo
        niveles = ("basico",) if maximo == "basico" else levels.NIVELES[1: levels.indice(maximo) + 1]
        if "maestria" in niveles and len(tema.rubrica or []) < 3:
            niveles = niveles[:-1] or ("intermedio",)
        fuentes = set()
        datos, visto, material = tema_dict(tema), fila.tema_visto, _material(db, tema, fila.tema_visto, fuentes)
    try:
        generado = generar_semanal(datos, tuple(niveles), material, visto, referencia=f"semanal:{semanal_id}")
    except Exception:
        with SessionLocal.begin() as db:
            fila = db.get(RetoSemanal, semanal_id)
            if fila is not None and fila.estado == "generando":
                _desde_banco(db, fila)
        return
    with SessionLocal.begin() as db:
        fila = db.scalar(select(RetoSemanal).where(RetoSemanal.id == semanal_id).with_for_update())
        if fila is None or fila.estado != "generando":
            return
        reto = crear_reto(db, curso_id=fila.curso_id, clase_id=None, generado=generado, uso="semanal",
                          estado="aprobado")
        fila.reto_id, fila.estado = reto.id, "listo"
        for clase_id in fuentes:
            db.add(FuenteSemanal(semanal_id=fila.id, clase_id=clase_id))


def estado_para(db, alumno_id: int, fila: RetoSemanal | None) -> str:
    if fila is None or fila.estado == "error":
        return "no_disponible"
    if db.scalar(select(Intento.id).where(Intento.alumno_id == alumno_id, Intento.semanal_id == fila.id)):
        return "completado"
    if fila.estado == "generando":
        return "preparando"
    return "disponible"


def preparar(db, alumno: Usuario, fila: RetoSemanal) -> tuple[RetoSemanalAlumno, RetoVersion, Reto, Tema]:
    if fila.estado != "listo" or fila.reto_id is None:
        raise SemanalError("El reto semanal todavía se está preparando.")
    progreso = db.get(RetoSemanalAlumno, (alumno.id, fila.id))
    reto = db.get(Reto, fila.reto_id)
    tema = db.get(Tema, reto.tema_id)
    if progreso is None:
        versiones = {n: v for n, v in versiones_vigentes(db, reto).items() if v.tipo in VERIFICABLES}
        if not versiones:
            raise SemanalError("El reto semanal no tiene una versión verificable.")
        objetivo = levels.subir(progress.nivel_guardado(db, alumno.id, tema), tema.nivel_maximo)
        nivel = levels.mas_cercano(objetivo, versiones.keys())
        db.execute(insert(RetoSemanalAlumno).values(
            alumno_id=alumno.id, semanal_id=fila.id, nivel=nivel, reto_version_id=versiones[nivel].id,
            presentado_en=ahora(),
        ).on_conflict_do_nothing())
        progreso = db.get(RetoSemanalAlumno, (alumno.id, fila.id))
    return progreso, db.get(RetoVersion, progreso.reto_version_id), reto, tema


def _progreso_bloqueado(db, alumno_id: int, fila: RetoSemanal) -> RetoSemanalAlumno:
    progreso = db.scalar(select(RetoSemanalAlumno).where(
        RetoSemanalAlumno.alumno_id == alumno_id, RetoSemanalAlumno.semanal_id == fila.id,
    ).with_for_update().execution_options(populate_existing=True))
    if progreso is None:
        raise SemanalError("Abre el reto semanal antes de responder.")
    if ahora() >= fin_semana(fila.semana):
        raise SemanalError("Este reto semanal ya venció.")
    return progreso


def pedir_pista(db, alumno_id: int, fila: RetoSemanal) -> None:
    progreso = _progreso_bloqueado(db, alumno_id, fila)
    hecho = db.scalar(select(Intento.id).where(Intento.alumno_id == alumno_id, Intento.semanal_id == fila.id))
    if hecho is None and progreso.pistas_usadas < 3:
        progreso.pistas_usadas += 1


def responder(db, alumno: Usuario, fila: RetoSemanal, respuesta: str, envio_id: str, params) -> Intento:
    """One attempt only: a second submission returns the first one."""
    progreso = _progreso_bloqueado(db, alumno.id, fila)
    existente = db.scalar(select(Intento).where(Intento.alumno_id == alumno.id, Intento.semanal_id == fila.id))
    if existente is not None:
        return existente
    version = db.get(RetoVersion, progreso.reto_version_id)
    reto = db.get(Reto, fila.reto_id)
    respuesta = attempts.validar_respuesta(version, respuesta, params)
    puesto_antes = ledger.puesto(db, fila.curso_id, alumno.id)
    intento = attempts.crear_intento(
        db, alumno=alumno, curso_id=fila.curso_id, reto=reto, version=version, origen="semanal", es_repaso=False,
        cuenta_para_dominio=fila.tema_visto, respuesta=respuesta, pistas=progreso.pistas_usadas,
        presentado_en=progreso.presentado_en, envio_id=envio_id, semanal_id=fila.id,
    )
    resultado = attempts.calificar_verificable(version, respuesta)
    attempts.finalizar(db, intento, resultado,
                       attempts.feedback_verificable(version, reto, resultado, progreso.pistas_usadas), params)
    puesto_despues = ledger.puesto(db, fila.curso_id, alumno.id)
    if puesto_antes and puesto_despues and puesto_despues < puesto_antes:
        messages.encolar(db, alumno.id, fila.curso_id, "podio", f"semanal:{fila.id}")
    return intento


def coins_de(db, alumno_id: int, fila: RetoSemanal) -> int:
    from db.models import Movimiento
    return int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
        Movimiento.alumno_id == alumno_id, Movimiento.tipo == "COINS", Movimiento.origen == "reto_semanal",
        Movimiento.referencia == f"semanal:{fila.id}")))
