"""Structured outputs of the AI components (AI behavior spec §6-9) and their backend validation.

The model's JSON is never trusted as is: a challenge version that fails a rule is
discarded, and levels above a topic's maximum are dropped.
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai.anonymize import Conocidos, anonimizar
from rules.levels import NIVELES, indice

TipoIA = Literal["alternativas", "completar", "definir", "caso"]


class Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionIA(Estricto):
    tipo: TipoIA
    enunciado: str
    opciones: list[str]
    respuesta_correcta: str
    respuestas_aceptadas: list[str]
    puntos_clave: list[str]
    explicacion: str
    pista_1: str
    pista_2: str
    pista_3: str


class VersionesIA(Estricto):
    basico: VersionIA | None
    intermedio: VersionIA | None
    avanzado: VersionIA | None
    maestria: VersionIA | None


class FuenteIA(Estricto):
    tipo: Literal["transcript", "material", "malla"]
    referencia: str


class RetoIA(Estricto):
    posicion: int
    tema_id: int
    error_comun_que_detecta: str
    fuente: FuenteIA
    versiones: VersionesIA
    avisos: list[str]


class RetosIA(Estricto):
    retos: list[RetoIA]


class TemaMapeadoIA(Estricto):
    tema_id: int
    evidencia: str
    confianza: float


class MapeoIA(Estricto):
    temas: list[TemaMapeadoIA]
    sin_mapeo: list[str]


class SeccionResumenIA(Estricto):
    titulo: str = Field(min_length=3, max_length=160)
    contenido: str = Field(min_length=20, max_length=2400)


class ResumenClaseIA(Estricto):
    introduccion: str = Field(min_length=20, max_length=1200)
    secciones: list[SeccionResumenIA] = Field(min_length=1, max_length=8)
    puntos_clave: list[str] = Field(min_length=1, max_length=6)


class CriterioIA(Estricto):
    criterio: str
    descripcion: str


class PropuestaTemaIA(Estricto):
    tema_id: int
    nivel_maximo: Literal["basico", "intermedio", "avanzado", "maestria"]
    es_fundamental: bool
    rubrica: list[CriterioIA]


class ModuloIA(Estricto):
    nombre: str
    temas: list[int]


class PropuestaIA(Estricto):
    temas: list[PropuestaTemaIA]
    modulos: list[ModuloIA]
    lenguajes_codigo: list[str]


class TemaPdfIA(Estricto):
    modulo: str
    tema: str
    subtema: str
    objetivo: str
    objetivo_propuesto: bool


class MallaPdfIA(Estricto):
    temas: list[TemaPdfIA]
    avisos: list[str]


class CalificacionIA(Estricto):
    veredicto: Literal["correcto", "parcial", "incorrecto"]
    puntos_clave_cubiertos: list[bool]
    justificacion: str
    confianza: Literal["alta", "media", "baja"]
    marcar_para_revision: bool
    motivo_revision: str


class FeedbackIA(Estricto):
    veredicto: Literal["correcto", "parcial", "incorrecto"]
    bien: str
    falto: str
    ejemplo_o_pista: str
    fuente_usada: str


class EvaluacionAbiertaIA(Estricto):
    calificacion: CalificacionIA
    feedback: FeedbackIA


@dataclass
class RetoGenerado:
    posicion: int | None
    tema_id: int
    error_comun: str
    fuente_tipo: str
    fuente_ref: str
    versiones: dict = field(default_factory=dict)
    avisos: list = field(default_factory=list)


def _limpio(texto: str, limite: int, conocidos: Conocidos) -> str:
    return anonimizar((texto or "").strip(), conocidos)[:limite]


def validar_version(version: VersionIA, conocidos: Conocidos, *, solo_verificables: bool = False) -> dict | None:
    """Clean dict for RetoVersion, or None when the version breaks a quality rule."""
    if solo_verificables and version.tipo not in ("alternativas", "completar"):
        return None
    enunciado = _limpio(version.enunciado, 4000, conocidos)
    explicacion = _limpio(version.explicacion, 3000, conocidos)
    pistas = [_limpio(p, 1000, conocidos) for p in (version.pista_1, version.pista_2, version.pista_3)]
    if len(enunciado) < 10 or not explicacion or not all(pistas):
        return None
    datos = {"tipo": version.tipo, "enunciado": enunciado, "explicacion": explicacion, "pistas": pistas,
             "opciones": [], "respuesta_correcta": "", "respuestas_aceptadas": [], "puntos_clave": [],
             "casos_de_prueba": []}
    if version.tipo == "alternativas":
        opciones = [_limpio(o, 600, conocidos) for o in version.opciones]
        if not 3 <= len(opciones) <= 6 or not all(opciones):
            return None
        if len({o.casefold() for o in opciones}) != len(opciones):
            return None
        correcta = version.respuesta_correcta.strip()
        letras = "ABCDEF"[: len(opciones)]
        if correcta in letras and correcta not in opciones:
            correcta = opciones[letras.index(correcta)]
        correcta = _limpio(correcta, 600, conocidos)
        if correcta not in opciones:
            return None
        datos.update(opciones=opciones, respuesta_correcta=correcta)
    elif version.tipo == "completar":
        aceptadas = [_limpio(a, 300, conocidos) for a in [version.respuesta_correcta, *version.respuestas_aceptadas]]
        aceptadas = list(dict.fromkeys(a for a in aceptadas if a))
        if not aceptadas:
            return None
        datos.update(respuesta_correcta=aceptadas[0], respuestas_aceptadas=aceptadas)
    else:
        puntos = [_limpio(p, 400, conocidos) for p in version.puntos_clave if p.strip()]
        if not 2 <= len(puntos) <= 4:
            return None
        datos.update(puntos_clave=puntos, respuesta_correcta=_limpio(version.respuesta_correcta, 3000, conocidos))
    return datos


def niveles_permitidos(nivel_maximo: str, rubrica: list) -> tuple[str, ...]:
    permitidos = NIVELES[: indice(nivel_maximo) + 1]
    if "maestria" in permitidos and len(rubrica or []) < 3:
        permitidos = permitidos[:-1]
    return permitidos


def validar_reto(reto: RetoIA, temas: dict[int, dict], conocidos: Conocidos, *, solo_verificables: bool = False,
                 niveles: tuple[str, ...] | None = None) -> RetoGenerado | None:
    tema = temas.get(reto.tema_id)
    if tema is None:
        return None
    permitidos = niveles or niveles_permitidos(tema["nivel_maximo"], tema.get("rubrica", []))
    versiones = {}
    for nivel in NIVELES:
        version = getattr(reto.versiones, nivel)
        if version is None or nivel not in permitidos:
            continue
        limpia = validar_version(version, conocidos, solo_verificables=solo_verificables)
        if limpia is not None:
            versiones[nivel] = limpia
    if not versiones:
        return None
    avisos = [_limpio(a, 300, conocidos) for a in reto.avisos if a.strip()][:5]
    faltantes = [n for n in permitidos if n not in versiones]
    if faltantes:
        avisos.append("Sin versión válida para: " + ", ".join(faltantes) + ".")
    return RetoGenerado(
        posicion=reto.posicion, tema_id=reto.tema_id,
        error_comun=_limpio(reto.error_comun_que_detecta, 600, conocidos),
        fuente_tipo=reto.fuente.tipo, fuente_ref=_limpio(reto.fuente.referencia, 900, conocidos),
        versiones=versiones, avisos=avisos,
    )


def veredicto_por_puntos(calificacion: CalificacionIA, total_puntos: int) -> tuple[str, bool]:
    """Backend verdict from key-point coverage. Doubt means partial and teacher review."""
    cubiertos = calificacion.puntos_clave_cubiertos
    revisar = calificacion.marcar_para_revision or calificacion.confianza == "baja"
    if len(cubiertos) == total_puntos and total_puntos:
        veredicto = "correcto" if all(cubiertos) else "incorrecto" if not any(cubiertos) else "parcial"
    else:
        veredicto = calificacion.veredicto
    if revisar:
        veredicto = "parcial"
    return veredicto, revisar
