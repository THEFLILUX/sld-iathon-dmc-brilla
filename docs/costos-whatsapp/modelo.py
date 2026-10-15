"""Modelo de costos de WhatsApp para Brilla (DMC Institute).

Tarifas Meta para destinatarios en Perú, vigentes desde el 1-oct-2026 (USD por mensaje entregado).
"""
import json

TC = 3.457  # S/ por USD, venta SUNAT 12-oct-2026

RATE = {
    "marketing": 0.0703,
    "utilidad": 0.0300,
    "servicio": 0.0300,   # tras 1.000 gratis por número al mes
}
FREE_SERVICE_PER_NUMBER = 1000
TWILIO_FEE = 0.005  # por mensaje, entrante o saliente

# ---- Supuestos por alumno activo al mes ----
CLASES_MES = 8          # 2 clases por semana
TAREAS_MES = 4          # 1 tarea por semana
PREGUNTAS_MES = 12      # preguntas que el alumno le hace a Brilla
PCT_SIN_ENTREGAR = 0.40 # alumnos que aún no entregan al momento del recordatorio
PCT_ALERTA = 0.05       # alumnos que generan una alerta a la asesora en el mes

DISENOS = {
    "base": dict(
        nombre="Diseño inicial (sin optimizar)",
        fin_clase_msgs=3,             # resumen, reto y recordatorio por separado
        recordatorio_a="todos",
        respuestas_por_pregunta=2,    # Brilla parte la respuesta en 2 burbujas
        alertas_por_whatsapp=True,
    ),
    "optimo": dict(
        nombre="Diseño recomendado",
        fin_clase_msgs=1,             # un solo mensaje por clase
        recordatorio_a="pendientes",
        respuestas_por_pregunta=1,    # una sola burbuja por respuesta
        alertas_por_whatsapp=False,   # aviso a la asesora por correo / panel
    ),
}


def mensajes_por_alumno(d):
    utilidad = CLASES_MES * d["fin_clase_msgs"]
    utilidad += TAREAS_MES * (1 if d["recordatorio_a"] == "todos" else PCT_SIN_ENTREGAR)
    servicio = PREGUNTAS_MES * d["respuestas_por_pregunta"]
    alertas = PCT_ALERTA if d["alertas_por_whatsapp"] else 0  # plantilla de utilidad a la asesora
    entrantes = PREGUNTAS_MES  # mensajes del alumno (gratis en Meta)
    return dict(utilidad=utilidad, servicio=servicio, alertas=alertas, entrantes=entrantes)


def costo_mes(alumnos, d, numeros=1, cat_fin_clase="utilidad", via_twilio=False):
    m = mensajes_por_alumno(d)
    fin_clase = alumnos * CLASES_MES * d["fin_clase_msgs"]
    recordatorios = alumnos * (m["utilidad"] - CLASES_MES * d["fin_clase_msgs"])
    alertas = alumnos * m["alertas"]
    servicio = alumnos * m["servicio"]
    servicio_cobrado = max(0.0, servicio - FREE_SERVICE_PER_NUMBER * numeros)
    usd = (fin_clase * RATE[cat_fin_clase]
           + recordatorios * RATE["utilidad"]
           + alertas * RATE["utilidad"]
           + servicio_cobrado * RATE["servicio"])
    if via_twilio:
        salientes = fin_clase + recordatorios + alertas + servicio
        usd += (salientes + alumnos * m["entrantes"]) * TWILIO_FEE
    return dict(
        usd=usd, pen=usd * TC,
        msgs_plantilla=fin_clase + recordatorios + alertas,
        msgs_servicio=servicio, servicio_cobrado=servicio_cobrado,
        por_alumno_usd=usd / alumnos, por_alumno_pen=usd * TC / alumnos,
    )


ESCENARIOS = [100, 500, 2000]

if __name__ == "__main__":
    out = {"supuestos": dict(CLASES_MES=CLASES_MES, TAREAS_MES=TAREAS_MES, PREGUNTAS_MES=PREGUNTAS_MES,
                             PCT_SIN_ENTREGAR=PCT_SIN_ENTREGAR, PCT_ALERTA=PCT_ALERTA, TC=TC),
           "mensajes": {k: mensajes_por_alumno(d) for k, d in DISENOS.items()},
           "escenarios": {}}
    for n in ESCENARIOS:
        fila = {}
        fila["base"] = costo_mes(n, DISENOS["base"])
        fila["optimo"] = costo_mes(n, DISENOS["optimo"])
        fila["base_marketing"] = costo_mes(n, DISENOS["base"], cat_fin_clase="marketing")
        fila["optimo_twilio"] = costo_mes(n, DISENOS["optimo"], via_twilio=True)
        fila["optimo_3numeros"] = costo_mes(n, DISENOS["optimo"], numeros=3)
        out["escenarios"][n] = fila
    print(json.dumps(out, indent=1, ensure_ascii=False))
    for n in ESCENARIOS:
        f = out["escenarios"][n]
        print(f"\n{n} alumnos:")
        for k, v in f.items():
            print(f"  {k:16s} US$ {v['usd']:9.2f}/mes  S/ {v['pen']:9.2f}/mes  "
                  f"US$ {v['por_alumno_usd']:.3f}/alumno  S/ {v['por_alumno_pen']:.3f}/alumno  "
                  f"plantillas {v['msgs_plantilla']:.0f}  servicio {v['msgs_servicio']:.0f} (cobrado {v['servicio_cobrado']:.0f})")
