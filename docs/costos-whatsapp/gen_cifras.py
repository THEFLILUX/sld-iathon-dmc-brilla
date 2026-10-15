"""Genera cifras.tex con todas las cifras del informe, calculadas desde modelo.py."""
import modelo as M

def f(x, d=2):
    return f"{x:,.{d}f}"

lines = []
def put(key, val):
    lines.append(f"\\expandafter\\def\\csname c-{key}\\endcsname{{{val}}}")

put("TC", f(M.TC, 3))
for cat, r in M.RATE.items():
    put(f"rate-{cat}-usd", f(r, 4))
    put(f"rate-{cat}-pen", f(r * M.TC, 3))

# mensajes por alumno
for k, d in M.DISENOS.items():
    m = M.mensajes_por_alumno(d)
    fin = M.CLASES_MES * d["fin_clase_msgs"]
    rec = m["utilidad"] - fin
    put(f"msg-{k}-fin", f(fin, 0))
    put(f"msg-{k}-rec", f(rec, 1) if rec % 1 else f(rec, 0))
    put(f"msg-{k}-serv", f(m["servicio"], 0))
    put(f"msg-{k}-alert", f(m["alertas"], 2) if m["alertas"] else "0")
    total = m["utilidad"] + m["alertas"] + m["servicio"]
    put(f"msg-{k}-total", f(total, 1))
    usd = (m["utilidad"] + m["alertas"]) * M.RATE["utilidad"] + m["servicio"] * M.RATE["servicio"]
    put(f"msg-{k}-usd", f(usd, 3))
    put(f"msg-{k}-pen", f(usd * M.TC, 2))

variantes = {
    "base": dict(d="base"),
    "optimo": dict(d="optimo"),
    "basemkt": dict(d="base", cat_fin_clase="marketing"),
    "optimkt": dict(d="optimo", cat_fin_clase="marketing"),
    "twilio": dict(d="optimo", via_twilio=True),
    "tresnum": dict(d="optimo", numeros=3),
}
res = {}
for n in M.ESCENARIOS:
    for key, v in variantes.items():
        kw = {k: x for k, x in v.items() if k != "d"}
        c = M.costo_mes(n, M.DISENOS[v["d"]], **kw)
        res[(n, key)] = c
        put(f"{n}-{key}-usd", f(c["usd"]))
        put(f"{n}-{key}-pen", f(c["pen"]))
        put(f"{n}-{key}-penr", f(c["pen"], 0))
        put(f"{n}-{key}-alum", f(c["por_alumno_pen"]))
        put(f"{n}-{key}-alumusd", f(c["por_alumno_usd"], 3))
        put(f"{n}-{key}-anual", f(c["pen"] * 12, 0))
        put(f"{n}-{key}-raw", f"{c['pen']:.2f}")
    ahorro = 1 - res[(n, "optimo")]["usd"] / res[(n, "base")]["usd"]
    put(f"{n}-ahorro", f(ahorro * 100, 0))
    put(f"{n}-ahorro-pen", f(res[(n, "base")]["pen"] - res[(n, "optimo")]["pen"], 0))
    put(f"{n}-ahorro-anual", f((res[(n, "base")]["pen"] - res[(n, "optimo")]["pen"]) * 12, 0))

# Cascada de ahorros para 500 alumnos (en el orden en que se aplican)
N = 500
r = M.RATE["utilidad"]
pasos = [
    ("fin", N * M.CLASES_MES * (3 - 1) * r),
    ("tutor", N * M.PREGUNTAS_MES * (2 - 1) * M.RATE["servicio"]),
    ("rec", N * M.TAREAS_MES * (1 - M.PCT_SIN_ENTREGAR) * r),
    ("alert", N * M.PCT_ALERTA * r),
]
tot = 0
for k, usd in pasos:
    tot += usd
    put(f"paso-{k}-pen", f(usd * M.TC, 0))
check = res[(N, "base")]["usd"] - res[(N, "optimo")]["usd"]
assert abs(tot - check) < 1e-6, (tot, check)

# Sensibilidades
put("extra-pregunta-pen", f(M.RATE["servicio"] * M.TC, 3))
put("500-twilio-delta-pen", f(res[(500, "twilio")]["pen"] - res[(500, "optimo")]["pen"], 0))
put("500-twilio-delta-pct", f((res[(500, "twilio")]["usd"] / res[(500, "optimo")]["usd"] - 1) * 100, 0))
put("500-mkt-delta-pen", f(res[(500, "optimkt")]["pen"] - res[(500, "optimo")]["pen"], 0))
put("500-mkt-delta-pct", f((res[(500, "optimkt")]["usd"] / res[(500, "optimo")]["usd"] - 1) * 100, 0))
put("numero-extra-pen", f(1000 * M.RATE["servicio"] * M.TC, 0))
put("base-vs-opt-x", f(res[(500, "base")]["usd"] / res[(500, "optimo")]["usd"], 1))

with open("cifras.tex", "w") as fh:
    fh.write("% Generado por gen_cifras.py - no editar a mano\n")
    fh.write("\n".join(lines) + "\n")
    fh.write("\\newcommand{\\cifra}[1]{\\csname c-#1\\endcsname}\n")
print(f"{len(lines)} cifras escritas")
for n in M.ESCENARIOS:
    print(n, {k: round(res[(n, k)]['pen'], 2) for k in variantes})
