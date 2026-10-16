"""Attempt scores, EXP and Coins (spec §8.1-8.4, EXP y Coins §2-3). Backend only."""

PUNTAJE_BASE = {"correcto": 100, "parcial": 50, "incorrecto": 0}


def puntaje_intento(resultado: str, pistas: int) -> float:
    return PUNTAJE_BASE[resultado] * (0.5 if pistas > 0 else 1.0)


def exp_reto(nivel: str, resultado: str, pistas: int, es_repaso: bool, params) -> int:
    """Level value; half with hints or partial (never a quarter); ×1,5 for REPASO after the hint rule."""
    if resultado == "incorrecto":
        return 0
    valor = getattr(params, f"exp_{nivel}")
    if resultado == "parcial" or pistas > 0:
        valor = valor / 2
    if es_repaso:
        valor = valor * params.exp_repaso_factor
    return int(round(valor))


def exp_semanal(resultado: str, pistas: int, params) -> int:
    if resultado == "correcto" and pistas == 0:
        return int(params.exp_semanal_sin_pistas)
    if resultado in ("correcto", "parcial"):
        return int(params.exp_semanal_con_pistas)
    return int(params.exp_semanal_fallado)


def bonos_quiz(resultados: list[tuple[str | None, int]], total_retos: int, params) -> dict:
    """resultados: (resultado, pistas) of each finished challenge. Pending answers count as finished."""
    completado = len(resultados) == total_retos
    perfecto = completado and all(r == "correcto" and p == 0 for r, p in resultados)
    return {
        "completado": int(params.exp_quiz_completado) if completado else 0,
        "perfecto": int(params.exp_quiz_perfecto) if perfecto else 0,
    }


def puntaje_quiz(verificables: list[tuple[str, int]]) -> float | None:
    """Mean score of the verifiable challenges only. None when there is none."""
    if not verificables:
        return None
    return sum(puntaje_intento(r, p) for r, p in verificables) / len(verificables)


def coins_quiz(puntaje: float | None, nivel: str, params) -> int:
    if puntaje is None or puntaje < params.coins_quiz_umbral:
        return 0
    return int(getattr(params, f"coins_quiz_{nivel}"))


def coins_semanal(nivel: str, resultado: str, pistas: int, params) -> int:
    if resultado != "correcto" or pistas > 0:
        return 0
    clave = "intermedio" if nivel in ("basico", "intermedio") else nivel
    return int(getattr(params, f"coins_semanal_{clave}"))


def coins_podio(puesto: int, params) -> int:
    return int(getattr(params, f"coins_podio_{puesto}", 0)) if puesto in (1, 2, 3) else 0
