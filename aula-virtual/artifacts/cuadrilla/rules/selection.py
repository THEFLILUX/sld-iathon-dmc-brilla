"""Pure selection rules for quizzes and the weekly challenge (spec §7.2, §7.3)."""

import random


def elegir_retos_clase(retos: list[dict], dominio_por_tema: dict, cantidad: int = 3) -> tuple[list[dict], list[dict]]:
    """Pick the class challenges, weakest topics first; the rest stay in reserve.

    retos: dicts with id, posicion and tema_id. A topic without data counts as the weakest.
    Returns (chosen ordered by position, reserve ordered by position).
    """
    def debilidad(reto):
        valor = dominio_por_tema.get(reto["tema_id"])
        return (-1 if valor is None else valor, reto["posicion"] or 99, reto["id"])

    elegidos = sorted(retos, key=debilidad)[:cantidad]
    ids = {r["id"] for r in elegidos}
    orden = lambda r: (r["posicion"] or 99, r["id"])  # noqa: E731
    return sorted(elegidos, key=orden), sorted((r for r in retos if r["id"] not in ids), key=orden)


def sortear_tema(temas: list[dict], semilla: str, excluir: int | None = None) -> int | None:
    """Weighted draw for the weekly challenge. Same seed, same topic: the challenge is equal for everyone.

    temas: dicts with id, es_fundamental, vencidos (overdue reviews in the course) and
    dominio (course average, None without data). Fundamental topics, overdue reviews
    and low mastery weigh more.
    """
    candidatos = [t for t in temas if t["id"] != excluir] or list(temas)
    if not candidatos:
        return None
    pesos = []
    for tema in candidatos:
        peso = 1.0
        if tema["es_fundamental"]:
            peso *= 2
        peso += min(tema.get("vencidos", 0), 10) * 0.5
        dominio = tema.get("dominio")
        peso *= 1.5 if dominio is None else 1 + (100 - dominio) / 100
        pesos.append(peso)
    rng = random.Random(semilla)
    return rng.choices([t["id"] for t in candidatos], weights=pesos, k=1)[0]
