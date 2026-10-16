"""Mastery, stored level and spaced-repetition agenda per student and topic (PRD M4, M5, M8)."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db.models import AgendaRepaso, Clase, ClaseTema, DominioTema, Intento, Tema
from rules import levels, mastery, spacing
from rules.calendar import ahora

ORIGEN_LEJANO = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _intentos_tema(db, alumno_id: int, tema_id: int, hasta: datetime | None = None) -> list[Intento]:
    consulta = select(Intento).where(
        Intento.alumno_id == alumno_id, Intento.tema_id == tema_id, Intento.estado == "completado",
        Intento.cuenta_para_dominio.is_(True),
    )
    if hasta is not None:
        consulta = consulta.where(Intento.completado_en <= hasta)
    return list(db.scalars(consulta.order_by(Intento.completado_en, Intento.id)))


def fila_dominio(db, alumno_id: int, tema_id: int, *, bloquear: bool = False) -> DominioTema:
    db.execute(insert(DominioTema).values(alumno_id=alumno_id, tema_id=tema_id, nivel_actual="basico",
                                          nivel_desde=ORIGEN_LEJANO).on_conflict_do_nothing())
    consulta = select(DominioTema).where(DominioTema.alumno_id == alumno_id, DominioTema.tema_id == tema_id)
    if bloquear:
        consulta = consulta.with_for_update().execution_options(populate_existing=True)
    return db.scalar(consulta)


def nivel_guardado(db, alumno_id: int, tema: Tema) -> str:
    fila = db.scalar(select(DominioTema).where(DominioTema.alumno_id == alumno_id, DominioTema.tema_id == tema.id))
    return levels.tope(fila.nivel_actual if fila else "basico", tema.nivel_maximo)


def actualizar_dominio(db, alumno_id: int, tema: Tema, params) -> DominioTema:
    """Recompute mastery from attempts and apply the stored-level rule to the current level's window."""
    fila = fila_dominio(db, alumno_id, tema.id, bloquear=True)
    intentos = _intentos_tema(db, alumno_id, tema.id)
    actual = levels.tope(fila.nivel_actual, tema.nivel_maximo)
    en_nivel = [i.puntaje for i in intentos if i.nivel == actual and i.completado_en >= fila.nivel_desde]
    nuevo = levels.nivel_guardado(actual, tema.nivel_maximo, en_nivel, params)
    if nuevo != fila.nivel_actual:
        fila.nivel_actual, fila.nivel_desde = nuevo, ahora()
    valor = mastery.dominio([(i.nivel, i.puntaje) for i in intentos], params)
    repaso_largo = any(
        i.resultado == "correcto" and (i.intervalo_repaso or 0) >= params.dominado_repaso_dias for i in intentos)
    fila.dominio = valor
    fila.estado = mastery.estado(valor, fila.nivel_actual, tema.nivel_maximo, repaso_largo, params)
    fila.actualizado_en = ahora()
    return fila


def agendar_si_falta(db, alumno_id: int, tema_id: int) -> None:
    """A topic touched by a completed quiz enters the agenda at 1 day (if it is not there yet)."""
    db.execute(insert(AgendaRepaso).values(
        alumno_id=alumno_id, tema_id=tema_id, intervalo_actual=spacing.INTERVALOS[0],
        proxima_fecha=ahora() + timedelta(days=spacing.INTERVALOS[0]),
    ).on_conflict_do_nothing())


def registrar_repaso(db, alumno_id: int, tema_id: int, resultado: str, pistas: int) -> int:
    """Move the topic in the agenda. Returns the interval that was being reviewed."""
    fila = db.scalar(select(AgendaRepaso).where(
        AgendaRepaso.alumno_id == alumno_id, AgendaRepaso.tema_id == tema_id,
    ).with_for_update().execution_options(populate_existing=True))
    if fila is None:
        fila = AgendaRepaso(alumno_id=alumno_id, tema_id=tema_id, intervalo_actual=spacing.INTERVALOS[0],
                            proxima_fecha=ahora())
        db.add(fila)
    revisado = fila.intervalo_actual
    fila.intervalo_actual = spacing.siguiente_intervalo(revisado, resultado, pistas)
    fila.proxima_fecha = ahora() + timedelta(days=fila.intervalo_actual)
    fila.actualizado_en = ahora()
    return revisado


def temas_vistos(db, curso_id: int) -> set[int]:
    return set(db.scalars(select(ClaseTema.tema_id).join(Clase, Clase.id == ClaseTema.clase_id).where(
        Clase.curso_id == curso_id, Clase.estado == "publicada")))


def progreso_alumno(db, alumno_id: int, curso_id: int) -> dict:
    """Mi progreso (A5) and the per-student report (D4)."""
    temas = db.scalars(select(Tema).where(Tema.curso_id == curso_id).order_by(Tema.orden)).all()
    dominios = {f.tema_id: f for f in db.scalars(select(DominioTema).where(
        DominioTema.alumno_id == alumno_id, DominioTema.tema_id.in_([t.id for t in temas] or [0])))}
    agenda = {f.tema_id: f for f in db.scalars(select(AgendaRepaso).where(
        AgendaRepaso.alumno_id == alumno_id, AgendaRepaso.tema_id.in_([t.id for t in temas] or [0])))}
    vistos = temas_vistos(db, curso_id)
    filas, conteo = [], defaultdict(int)
    for tema in temas:
        dominio = dominios.get(tema.id)
        estado = dominio.estado if dominio and dominio.dominio is not None else "sin_datos"
        conteo[estado] += 1
        filas.append({
            "tema": tema, "estado": estado, "visto": tema.id in vistos,
            "dominio": dominio.dominio if dominio else None,
            "nivel": levels.tope(dominio.nivel_actual if dominio else "basico", tema.nivel_maximo),
            "proximo_repaso": agenda[tema.id].proxima_fecha if tema.id in agenda else None,
            "repaso_vencido": tema.id in agenda and agenda[tema.id].proxima_fecha <= ahora(),
        })
    return {"temas": filas, "conteo": dict(conteo)}


def dominio_promedio_en(db, alumno_id: int, curso_id: int, momento: datetime, params) -> float | None:
    """Average mastery over topics with data at a given instant, recomputed from attempts."""
    intentos = db.scalars(select(Intento).where(
        Intento.alumno_id == alumno_id, Intento.curso_id == curso_id, Intento.estado == "completado",
        Intento.cuenta_para_dominio.is_(True), Intento.completado_en <= momento,
    ).order_by(Intento.completado_en, Intento.id)).all()
    por_tema = defaultdict(list)
    for intento in intentos:
        por_tema[intento.tema_id].append((intento.nivel, intento.puntaje))
    valores = [mastery.dominio(lista, params) for lista in por_tema.values()]
    valores = [v for v in valores if v is not None]
    return round(sum(valores) / len(valores), 1) if valores else None
