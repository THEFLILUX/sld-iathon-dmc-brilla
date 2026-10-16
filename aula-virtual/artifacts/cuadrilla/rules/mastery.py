"""Mastery per student and topic (spec §8): weighted moving average and states."""

PESO_NIVEL = {"basico": 1, "intermedio": 2, "avanzado": 3, "maestria": 4}
ESTADOS = ("dominado", "en_progreso", "debil", "sin_datos")
ETIQUETA_ESTADO = {
    "dominado": "Dominado", "en_progreso": "En progreso", "debil": "Débil",
    "sin_datos": "Sin datos", "no_visto": "No visto",
}


def dominio(intentos: list[tuple[str, float]], params) -> float | None:
    """intentos: (nivel, puntaje 0-100), oldest first. Weight = level weight × decay^age."""
    ultimos = intentos[-int(params.dominio_ventana):]
    if not ultimos:
        return None
    numerador = denominador = 0.0
    for edad, (nivel, puntaje) in enumerate(reversed(ultimos)):
        peso = PESO_NIVEL[nivel] * (params.dominio_decaimiento ** edad)
        numerador += peso * puntaje
        denominador += peso
    return round(numerador / denominador, 1)


def estado(valor: float | None, nivel_actual: str, nivel_maximo: str, repaso_largo_acertado: bool, params) -> str:
    """Dominado needs the threshold at the topic's maximum level and a correct review at >= N days."""
    if valor is None:
        return "sin_datos"
    if valor < params.estado_debil:
        return "debil"
    if valor >= params.estado_dominado and nivel_actual == nivel_maximo and repaso_largo_acertado:
        return "dominado"
    return "en_progreso"
