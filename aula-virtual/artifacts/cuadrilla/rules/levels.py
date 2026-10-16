"""Bloom levels and adaptation (PRD M4, spec §8). The AI never decides levels."""

NIVELES = ("basico", "intermedio", "avanzado", "maestria")
ETIQUETA = {"basico": "Básico", "intermedio": "Intermedio", "avanzado": "Avanzado", "maestria": "Maestría"}
BLOOM = {
    "basico": "Recordar y comprender",
    "intermedio": "Aplicar",
    "avanzado": "Analizar",
    "maestria": "Crear",
}
VERSION = {"basico": "Más fácil", "intermedio": "Base", "avanzado": "Más difícil", "maestria": "Maestría"}


def indice(nivel: str) -> int:
    return NIVELES.index(nivel)


def tope(nivel: str, maximo: str) -> str:
    return NIVELES[min(indice(nivel), indice(maximo))]


def subir(nivel: str, maximo: str) -> str:
    return NIVELES[min(indice(nivel) + 1, indice(maximo))]


def bajar(nivel: str) -> str:
    return NIVELES[max(indice(nivel) - 1, 0)]


def hasta(maximo: str) -> tuple[str, ...]:
    return NIVELES[: indice(maximo) + 1]


def siguiente_en_quiz(nivel_guardado: str, maximo: str, previos: list[tuple[str, str | None, int]]) -> str:
    """Level of the next challenge of a topic inside the same quiz.

    previos: (nivel, resultado, pistas) of earlier answered challenges of this topic,
    oldest first. A clean success raises one level, a failure keeps it, two
    consecutive failures lower it. Only the next challenge is affected.
    """
    if not previos:
        return tope(nivel_guardado, maximo)
    ultimo_nivel, ultimo_resultado, ultimas_pistas = previos[-1]
    if ultimo_resultado == "correcto" and ultimas_pistas == 0:
        return subir(ultimo_nivel, maximo)
    if len(previos) >= 2 and all(resultado == "incorrecto" for _, resultado, _ in previos[-2:]):
        return bajar(tope(ultimo_nivel, maximo))
    return tope(ultimo_nivel, maximo)


def nivel_guardado(nivel_actual: str, maximo: str, puntajes_en_nivel: list[float], params) -> str:
    """Stored level from the last N attempts at the current level (scores 0-100, oldest first).

    The score already halves answers with hints or partial answers, so the
    success rate is the mean score over 100.
    """
    nivel_actual = tope(nivel_actual, maximo)
    ventana = puntajes_en_nivel[-int(params.nivel_ventana):]
    if len(ventana) < int(params.nivel_minimo):
        return nivel_actual
    porcentaje = sum(ventana) / len(ventana)
    if porcentaje >= params.nivel_sube:
        return subir(nivel_actual, maximo)
    if porcentaje < params.nivel_baja:
        return bajar(nivel_actual)
    return nivel_actual


def mas_cercano(objetivo: str, disponibles) -> str | None:
    """Closest available version: the target, else the nearest lower level, else the nearest higher one."""
    disponibles = set(disponibles)
    if objetivo in disponibles:
        return objetivo
    i = indice(objetivo)
    for candidato in reversed(NIVELES[:i]):
        if candidato in disponibles:
            return candidato
    for candidato in NIVELES[i + 1:]:
        if candidato in disponibles:
            return candidato
    return None
