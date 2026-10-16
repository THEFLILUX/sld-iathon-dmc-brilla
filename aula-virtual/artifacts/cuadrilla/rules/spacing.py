"""Spaced repetition (PRD M5): intervals of 1, 3, 7, 14 and 30 days, computed by the backend."""

INTERVALOS = (1, 3, 7, 14, 30)


def siguiente_intervalo(actual: int, resultado: str, pistas: int) -> int:
    """Clean success advances; success with hints (or partial) stays; a failure returns to 1 day."""
    if resultado == "incorrecto":
        return INTERVALOS[0]
    if resultado == "correcto" and pistas == 0:
        mayores = [i for i in INTERVALOS if i > actual]
        return mayores[0] if mayores else INTERVALOS[-1]
    return actual if actual in INTERVALOS else INTERVALOS[0]
