"""Dropout risk (PRD M9): inactivity or a mastery drop. It only alerts the teacher."""

from datetime import datetime


def senales(ultima_actividad: datetime | None, referencia_inactividad: datetime,
            dominio_hoy: float | None, dominio_antes: float | None, ahora: datetime, params) -> list[dict]:
    """referencia_inactividad: last activity, or the enrollment/first publication when there is none."""
    resultado = []
    desde = ultima_actividad or referencia_inactividad
    dias = (ahora - desde).total_seconds() / 86400
    if dias >= params.riesgo_inactividad_dias:
        resultado.append({
            "tipo": "inactividad",
            "referencia": desde.date().isoformat(),
            "detalle": f"{int(dias)} días sin actividad" + ("" if ultima_actividad else " (aún no practica)"),
        })
    if dominio_hoy is not None and dominio_antes is not None:
        caida = dominio_antes - dominio_hoy
        if caida >= params.riesgo_caida_puntos:
            resultado.append({
                "tipo": "caida",
                "referencia": (ultima_actividad or ahora).date().isoformat(),
                "detalle": f"El dominio promedio bajó {caida:.0f} puntos en {int(params.riesgo_caida_dias)} días",
            })
    return resultado
