"""Configurable parameters (PRD §7, EXP y Coins). Defaults are the documented values.

Fixed rules (4 retos por quiz, 1 hora de validación, 3 pistas, intervalos 1/3/7/14/30,
puntaje 100/50/0 × 1/0,5) are constants in the rule modules, not parameters.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParamDef:
    clave: str
    defecto: float
    etiqueta: str
    grupo: str
    minimo: float = 0
    maximo: float = 100_000
    entero: bool = True


DEFINICIONES = (
    ParamDef("exp_basico", 50, "EXP de un reto Básico", "EXP", 1),
    ParamDef("exp_intermedio", 100, "EXP de un reto Intermedio", "EXP", 1),
    ParamDef("exp_avanzado", 150, "EXP de un reto Avanzado", "EXP", 1),
    ParamDef("exp_maestria", 200, "EXP de un reto de Maestría", "EXP", 1),
    ParamDef("exp_repaso_factor", 1.5, "Multiplicador del reto de REPASO", "EXP", 1, 5, entero=False),
    ParamDef("exp_quiz_completado", 100, "Bono por quiz completado", "EXP"),
    ParamDef("exp_quiz_perfecto", 150, "Bono adicional por quiz perfecto", "EXP"),
    ParamDef("exp_semanal_sin_pistas", 500, "Reto semanal acertado sin pistas", "EXP"),
    ParamDef("exp_semanal_con_pistas", 250, "Reto semanal acertado con pistas", "EXP"),
    ParamDef("exp_semanal_fallado", 100, "Reto semanal intentado y fallado", "EXP"),
    ParamDef("coins_quiz_basico", 5, "Coins por quiz en nivel Básico", "Coins"),
    ParamDef("coins_quiz_intermedio", 5, "Coins por quiz en nivel Intermedio", "Coins"),
    ParamDef("coins_quiz_avanzado", 5, "Coins por quiz en nivel Avanzado", "Coins"),
    ParamDef("coins_quiz_maestria", 10, "Coins por quiz en nivel Maestría", "Coins"),
    ParamDef("coins_quiz_umbral", 75, "Puntaje mínimo del quiz para pagar Coins", "Coins", 1, 100),
    ParamDef("coins_semanal_intermedio", 5, "Coins del reto semanal Intermedio (o Básico)", "Coins"),
    ParamDef("coins_semanal_avanzado", 10, "Coins del reto semanal Avanzado", "Coins"),
    ParamDef("coins_semanal_maestria", 10, "Coins del reto semanal de Maestría", "Coins"),
    ParamDef("coins_podio_1", 120, "Coins al 1.er lugar del podio final", "Coins"),
    ParamDef("coins_podio_2", 90, "Coins al 2.º lugar del podio final", "Coins"),
    ParamDef("coins_podio_3", 60, "Coins al 3.er lugar del podio final", "Coins"),
    ParamDef("coin_porcentaje", 0.05, "Descuento por cada Coin (%)", "Canje", 0.01, 1, entero=False),
    ParamDef("nivel_ventana", 5, "Retos considerados para cambiar el nivel guardado", "Niveles", 1, 50),
    ParamDef("nivel_minimo", 3, "Mínimo de retos en el nivel para cambiarlo", "Niveles", 1, 50),
    ParamDef("nivel_sube", 80, "Porcentaje de aciertos para subir de nivel", "Niveles", 1, 100),
    ParamDef("nivel_baja", 50, "Por debajo de este porcentaje se baja de nivel", "Niveles", 0, 100),
    ParamDef("dominio_ventana", 10, "Intentos del promedio móvil de dominio", "Dominio", 1, 100),
    ParamDef("dominio_decaimiento", 0.9, "Decaimiento por intento más antiguo", "Dominio", 0.1, 1, entero=False),
    ParamDef("estado_debil", 50, "Dominio por debajo del cual el tema es Débil", "Dominio", 1, 100),
    ParamDef("estado_dominado", 80, "Dominio mínimo para Dominado", "Dominio", 1, 100),
    ParamDef("dominado_repaso_dias", 7, "Repaso acertado mínimo (días) para Dominado", "Dominio", 1, 30),
    ParamDef("riesgo_inactividad_dias", 5, "Días sin actividad para marcar riesgo", "Riesgo", 1, 60),
    ParamDef("riesgo_caida_puntos", 15, "Caída del dominio promedio para marcar riesgo", "Riesgo", 1, 100),
    ParamDef("riesgo_caida_dias", 14, "Ventana de la caída de dominio (días)", "Riesgo", 1, 60),
    ParamDef("participacion_minima", 5, "Alumnos con datos para 'dominado por la clase'", "Reportes", 1, 500),
    ParamDef("reportes_retiro", 3, "Reportes de error que retiran un reto", "Reportes", 1, 50),
    ParamDef("banco_repetir_dias", 30, "Días antes de repetir un reto ya visto", "Reportes", 1, 365),
    ParamDef("abierta_min_caracteres", 20, "Mínimo de caracteres en respuestas abiertas", "Quiz", 1, 2000),
    ParamDef("anomalia_segundos", 4, "Segundos por reto bajo los que el quiz es anómalo", "Quiz", 1, 120),
)
DEFAULTS = {d.clave: d.defecto for d in DEFINICIONES}
POR_CLAVE = {d.clave: d for d in DEFINICIONES}


class Params:
    """Read-only view: documented defaults overlaid with the administrator's values."""

    def __init__(self, overrides: dict | None = None):
        values = dict(DEFAULTS)
        for key, value in (overrides or {}).items():
            if key in values:
                values[key] = int(value) if POR_CLAVE[key].entero else float(value)
        object.__setattr__(self, "_values", values)

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        raise AttributeError("Los parámetros son de solo lectura.")

    def as_dict(self) -> dict:
        return dict(self._values)


DEFAULT_PARAMS = Params()
