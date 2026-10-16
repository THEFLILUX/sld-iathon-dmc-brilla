"""A fake LangChain chat model: answers each component with valid structured output and records every payload.

It mimics `chat_model.with_structured_output(schema, method="json_schema", include_raw=True)`,
which is the only way the app talks to a model (ai/proveedores.py → ai/llm.py).
"""

import json

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

NIVELES = ("basico", "intermedio", "avanzado", "maestria")
COMPONENTE = {"RetosIA": "generador", "MapeoIA": "mapeador", "EvaluacionAbiertaIA": "calificador",
              "PropuestaIA": "proponedor", "MallaPdfIA": "importador_malla", "ResumenClaseIA": "resumidor",
              "RespuestaAsistenteIA": "asistente_docente", "ConexionIA": "conexion_ia"}


def version(tipo="alternativas", nivel="intermedio", n=1):
    base = {"tipo": tipo, "enunciado": f"Pregunta {n} de nivel {nivel} sobre lo visto en clase", "opciones": [],
            "respuesta_correcta": "", "respuestas_aceptadas": [], "puntos_clave": [],
            "explicacion": "Se explicó en la clase con el ejemplo de ventas por ciudad.",
            "pista_1": "Piensa en el ejemplo.", "pista_2": "Revisa el paso clave.", "pista_3": "Casi: es la opción A."}
    if tipo == "alternativas":
        base.update(opciones=[f"Opción correcta {n}", f"Distractor {n}a", f"Distractor {n}b", f"Distractor {n}c"],
                    respuesta_correcta=f"Opción correcta {n}")
    elif tipo == "completar":
        base.update(enunciado=f"Completa la instrucción {n}: df.____()", respuesta_correcta="sum",
                    respuestas_aceptadas=["sum()"])
    else:
        base.update(puntos_clave=["Idea uno", "Idea dos"], respuesta_correcta="Respuesta modelo.")
    return base


def reto(posicion, tema, niveles, n=1, solo_verificables=False):
    maximo = NIVELES.index(tema.get("nivel_maximo", "avanzado"))
    versiones = {}
    for i, nivel in enumerate(NIVELES):
        if nivel in niveles and i <= maximo and not (nivel == "maestria" and len(tema.get("rubrica") or []) < 3):
            tipo = "alternativas" if solo_verificables or nivel in ("basico", "intermedio") else "caso"
            versiones[nivel] = version(tipo, nivel, n)
        else:
            versiones[nivel] = None
    return {"posicion": posicion, "tema_id": tema["tema_id"], "error_comun_que_detecta": "Confundir conceptos",
            "fuente": {"tipo": "transcript", "referencia": "lo primero que debemos hacer es traer data"},
            "versiones": versiones, "avisos": []}


class FalsoModelo:
    def __init__(self, calificacion=None, fallar=None):
        self.payloads: list[str] = []
        self.componentes: list[str] = []
        self.calificacion = calificacion or {"cubiertos": [True, True], "confianza": "alta", "revisar": False}
        self.fallar = set(fallar or ())
        self.contador = 0

    def with_structured_output(self, schema, *, method=None, include_raw=False, **_kwargs):
        assert method == "json_schema" and include_raw, "la app siempre pide json_schema con include_raw"
        componente = COMPONENTE[schema.__name__]

        def invocar(mensajes):
            self.componentes.append(componente)
            self.payloads.append("\n".join(str(m.content) for m in mensajes))
            if componente in self.fallar:
                raise RuntimeError("Fallo simulado de la IA")
            datos = json.loads(mensajes[1].content)
            respuesta = getattr(self, componente)(datos, mensajes[0].content)
            crudo = AIMessage(content=json.dumps(respuesta),
                              usage_metadata={"input_tokens": 120, "output_tokens": 80, "total_tokens": 200})
            try:
                return {"raw": crudo, "parsed": schema.model_validate(respuesta), "parsing_error": None}
            except ValidationError as error:
                return {"raw": crudo, "parsed": None, "parsing_error": error}
        return RunnableLambda(invocar)

    def resumidor(self, datos, _sistema):
        return {"introduccion": "En esta clase aprendiste a usar Python para automatizar el análisis de datos.",
                "secciones": [{"titulo": "Agrupar ventas con pandas", "contenido":
                    "Se explicó cómo cargar un Excel y agrupar las ventas por ciudad. Con groupby se reúnen las filas de cada ciudad y con sum se obtiene el importe total. Se comparó el procedimiento con una tabla dinámica de Excel."},
                    {"titulo": "Generar gráficos e informes", "contenido":
                    "La sesión mostró cómo crear gráficos y trasladarlos a una presentación. Se reutiliza la estructura del código y se cambian los nombres de columnas según el conjunto de datos."}],
                "puntos_clave": ["La extracción de datos es el primer paso del análisis.",
                                  "Automatizar evita repetir manualmente las mismas tareas."]}

    def asistente_docente(self, datos, _sistema):
        detalle = next((f for f in datos["fuentes"] if "alumno" in f["datos"]), None)
        fuente = detalle or datos["fuentes"][0]
        quien = fuente["datos"].get("alumno", "El grupo")
        return {"hallazgos": [{"texto": quien + " tiene registros disponibles para revisión.", "fuentes": [fuente["id"]]}],
                "recomendaciones": [{"texto": "Revisa los registros antes de proponer una práctica de refuerzo.",
                                      "fuentes": [fuente["id"]]}],
                "limites": ["Las tareas marcadas listas no acreditan una entrega verificada."]}

    def conexion_ia(self, datos, _sistema):
        return {"estado": "ok"}

    def mapeador(self, datos, _sistema):
        temas = datos["temas_malla"]
        return {"temas": [{"tema_id": t["tema_id"], "evidencia": "fragmento de la clase", "confianza": 0.9 - i / 10}
                          for i, t in enumerate(temas[:3])], "sin_mapeo": []}

    def generador(self, datos, sistema):
        self.contador += 1
        if "MODO previo" in sistema:
            return {"retos": [reto(0, datos["temas_clase_1"][0], ("basico",), self.contador, True)]}
        if "MODO semanal" in sistema:
            return {"retos": [reto(0, datos["tema"], tuple(datos["niveles_pedidos"]), self.contador, True)]}
        if "MODO completar" in sistema:
            return {"retos": [reto(datos["posicion"], datos["tema"], tuple(datos["niveles_pedidos"]), self.contador)]}
        if "MODO reemplazo" in sistema:
            return {"retos": [reto(datos["posicion"], datos["tema"], NIVELES, self.contador)]}
        temas = datos["temas_clase"]
        return {"retos": [reto(p, temas[(p - 1) % len(temas)], NIVELES, self.contador * 10 + p)
                          for p in datos["posiciones"]]}

    def calificador(self, datos, _sistema):
        c = self.calificacion
        cubiertos = c["cubiertos"][: len(datos["reto"]["puntos_clave"])]
        veredicto = "correcto" if all(cubiertos) else "incorrecto" if not any(cubiertos) else "parcial"
        return {"calificacion": {"veredicto": veredicto, "puntos_clave_cubiertos": cubiertos,
                                 "justificacion": "Cubre las ideas principales.", "confianza": c["confianza"],
                                 "marcar_para_revision": c["revisar"], "motivo_revision": "Dudoso" if c["revisar"] else ""},
                "feedback": {"veredicto": veredicto, "bien": "Explicaste la idea con tus palabras.",
                             "falto": "Te faltó relacionarlo con el ejemplo de la clase.",
                             "ejemplo_o_pista": "Recuerda el ejemplo de ventas por ciudad.",
                             "fuente_usada": "Clase 1"}}

    def importador_malla(self, datos, _sistema):
        return {"temas": [{"modulo": "Fundamentos", "tema": "Consultas SQL", "subtema": "SELECT",
                           "objetivo": "Consultar columnas de una tabla.", "objetivo_propuesto": False},
                          {"modulo": "Fundamentos", "tema": "Consultas SQL", "subtema": "JOIN",
                           "objetivo": "Combinar dos tablas mediante JOIN.", "objetivo_propuesto": True}],
                "avisos": ["Revisa el objetivo propuesto para JOIN."]}

    def proponedor(self, datos, _sistema):
        temas = datos["malla"]
        return {"temas": [{"tema_id": t["tema_id"], "nivel_maximo": "maestria" if i == 0 else "avanzado",
                           "es_fundamental": i < 2,
                           "rubrica": [{"criterio": f"Criterio {k}", "descripcion": "Observable"} for k in range(3)] if i == 0 else []}
                          for i, t in enumerate(temas)],
                "modulos": [{"nombre": "Módulo del brochure", "temas": [t["tema_id"] for t in temas]}],
                "lenguajes_codigo": ["Python", "SQL"]}
