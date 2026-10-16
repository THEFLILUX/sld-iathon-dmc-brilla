"""AI components (AI behavior spec §2): mapper, generator, open-answer grader with feedback, proposer.

Inputs are anonymized before they get here; outputs are validated by ai/schemas.py.
"""

from ai import privacy, prompts
from ai.context import select_context
from ai.llm import IAError, llamar
from ai.schemas import (
    EvaluacionAbiertaIA, MallaPdfIA, MapeoIA, PropuestaIA, RetoGenerado, RetosIA, niveles_permitidos, validar_reto,
    veredicto_por_puntos,
)

MAX_TRANSCRIPT = 120_000
MAX_MATERIAL = 40_000


def _transcript(texto: str, consulta: str = "") -> str:
    texto = texto or ""
    if len(texto) <= MAX_TRANSCRIPT:
        return texto
    return select_context(texto, consulta, limit=MAX_TRANSCRIPT // 2400)


def _tema_publico(tema: dict) -> dict:
    return {k: tema.get(k) for k in ("tema_id", "nombre", "subtema", "objetivo", "nivel_maximo", "rubrica", "modulo")}


def mapear(transcript: str, temas: list[dict], referencia=None) -> list[dict]:
    resultado = llamar("mapeador", MapeoIA, prompts.MAPEADOR, {
        "temas_malla": [_tema_publico(t) for t in temas], "transcript": _transcript(transcript),
    }, referencia=referencia, max_tokens=4000)
    validos = {t["tema_id"] for t in temas}
    vistos, salida = set(), []
    for tema in sorted(resultado.temas, key=lambda t: -t.confianza):
        if tema.tema_id in validos and tema.tema_id not in vistos:
            vistos.add(tema.tema_id)
            salida.append({"tema_id": tema.tema_id, "evidencia": tema.evidencia.strip()[:600],
                           "confianza": max(0.0, min(1.0, float(tema.confianza)))})
    return salida


def _retos(modo: str, datos: dict, temas: list[dict], referencia, *, solo_verificables=False, niveles=None,
           max_tokens=20000) -> list[RetoGenerado]:
    sistema = prompts.GENERADOR + "\n" + modo
    respuesta = llamar("generador", RetosIA, sistema, datos, referencia=referencia, max_tokens=max_tokens,
                       timeout=300)
    por_id = {t["tema_id"]: t for t in temas}
    conocidos = privacy.conocidos()
    validos = []
    for reto in respuesta.retos:
        limpio = validar_reto(reto, por_id, conocidos, solo_verificables=solo_verificables, niveles=niveles)
        if limpio is not None:
            validos.append(limpio)
    return validos


def generar_retos_clase(temas: list[dict], transcript: str, material: str, posiciones: list[int],
                        evitar: list[str], referencia=None) -> list[RetoGenerado]:
    """One challenge per requested position; asks again once for missing positions."""
    obtenidos: dict[int, RetoGenerado] = {}
    pendientes = list(posiciones)
    for _ in range(2):
        if not pendientes:
            break
        datos = {
            "posiciones": pendientes, "temas_clase": [_tema_publico(t) for t in temas],
            "transcript_clase": _transcript(transcript), "material_apoyo": (material or "")[:MAX_MATERIAL],
            "retos_a_evitar": evitar[:40],
        }
        for reto in _retos(prompts.MODO_CLASE, datos, temas, referencia):
            if reto.posicion in pendientes and reto.posicion not in obtenidos:
                obtenidos[reto.posicion] = reto
                evitar = evitar + [next(iter(reto.versiones.values()))["enunciado"]]
        pendientes = [p for p in posiciones if p not in obtenidos]
    return [obtenidos[p] for p in posiciones if p in obtenidos]


def generar_reemplazo(tema: dict, transcript: str, material: str, posicion: int, evitar: list[str],
                      referencia=None) -> RetoGenerado:
    datos = {"posicion": posicion, "tema": _tema_publico(tema),
             "transcript_clase": _transcript(transcript, tema["nombre"] + " " + tema["objetivo"]),
             "material_apoyo": (material or "")[:MAX_MATERIAL], "retos_a_evitar": evitar[:40]}
    retos = _retos(prompts.MODO_REEMPLAZO, datos, [tema], referencia, max_tokens=8000)
    if not retos:
        raise IAError("La IA no produjo un reto válido. Vuelve a intentarlo o escribe tu propio reto.")
    retos[0].posicion = posicion
    return retos[0]


def generar_previo(temas: list[dict], brochure: str, referencia=None) -> RetoGenerado:
    datos = {"temas_clase_1": [_tema_publico(t) for t in temas], "brochure": (brochure or "")[:MAX_MATERIAL]}
    retos = _retos(prompts.MODO_PREVIO, datos, temas, referencia, solo_verificables=True, niveles=("basico",),
                   max_tokens=4000)
    if not retos:
        raise IAError("La IA no produjo un reto de conocimiento previo válido.")
    retos[0].posicion = None
    return retos[0]


def generar_semanal(tema: dict, niveles: tuple[str, ...], material: str, visto: bool, referencia=None) -> RetoGenerado:
    datos = {"tema": _tema_publico(tema), "niveles_pedidos": list(niveles), "tema_visto_en_clase": visto,
             "material": (material or "")[:MAX_MATERIAL]}
    retos = _retos(prompts.MODO_SEMANAL, datos, [tema], referencia, solo_verificables=True, niveles=niveles,
                   max_tokens=8000)
    if not retos:
        raise IAError("La IA no produjo un reto semanal verificable.")
    retos[0].posicion = None
    return retos[0]


def completar_niveles(tema: dict, version_docente: dict, nivel_docente: str, transcript: str, posicion,
                      referencia=None) -> dict:
    permitidos = tuple(n for n in niveles_permitidos(tema["nivel_maximo"], tema.get("rubrica", []))
                       if n != nivel_docente)
    if not permitidos:
        return {}
    datos = {"posicion": posicion or 0, "tema": _tema_publico(tema), "nivel_del_docente": nivel_docente,
             "version_del_docente": version_docente, "niveles_pedidos": list(permitidos),
             "transcript_clase": _transcript(transcript, version_docente.get("enunciado", ""))[:40_000]}
    retos = _retos(prompts.MODO_PROPIO, datos, [tema], referencia, niveles=permitidos, max_tokens=10000)
    return retos[0].versiones if retos else {}


def evaluar_abierta(*, alias: str, curso: str, tema: dict, version: dict, nivel: str, respuesta: str,
                    pistas_usadas: int, fuentes: str, referencia=None) -> dict:
    """Grader + tutor feedback in one structured call. The backend derives the final verdict."""
    resultado = llamar("calificador", EvaluacionAbiertaIA, prompts.CALIFICADOR, {
        "tarea": "calificar_abierta y dar_feedback", "alumno": alias, "curso": curso,
        "tema": tema["nombre"], "objetivo": tema["objetivo"], "nivel": nivel,
        "reto": {"tipo": version["tipo"], "enunciado": version["enunciado"],
                 "puntos_clave": version["puntos_clave"], "respuesta_modelo": version["respuesta_correcta"],
                 "explicacion": version["explicacion"]},
        "respuesta_alumno": respuesta, "pistas_usadas": pistas_usadas, "fuentes_tema": fuentes[:12000],
    }, referencia=referencia, max_tokens=2500, timeout=45)
    veredicto, revisar = veredicto_por_puntos(resultado.calificacion, len(version["puntos_clave"]))
    feedback = resultado.feedback.model_dump()
    feedback["veredicto"] = veredicto
    if veredicto == "correcto":
        feedback["ejemplo_o_pista"] = ""
    return {"resultado": veredicto, "revisar": revisar,
            "calificacion": resultado.calificacion.model_dump(), "feedback": feedback,
            "motivo_revision": resultado.calificacion.motivo_revision[:500]}


def extraer_malla_pdf(texto: str, referencia=None) -> dict:
    from ai.anonymize import anonimizar

    conocido = privacy.conocidos()
    resultado = llamar("importador_malla", MallaPdfIA, prompts.IMPORTADOR_MALLA,
                       {"texto_pdf": anonimizar(texto, conocido)}, referencia=referencia,
                       max_tokens=20000, timeout=300)
    return {"temas": [{k: anonimizar(v, conocido) if isinstance(v, str) else v
                        for k, v in t.model_dump().items()} for t in resultado.temas],
            "avisos": [anonimizar(a, conocido)[:1000] for a in resultado.avisos[:20]]}


def proponer(temas: list[dict], brochure: str, referencia=None) -> dict:
    resultado = llamar("proponedor", PropuestaIA, prompts.PROPONEDOR, {
        "malla": [_tema_publico(t) for t in temas], "brochure": (brochure or "")[:MAX_MATERIAL],
    }, referencia=referencia, max_tokens=12000, timeout=300)
    validos = {t["tema_id"] for t in temas}
    propuestas = {}
    for tema in resultado.temas:
        if tema.tema_id not in validos:
            continue
        rubrica = [{"criterio": c.criterio.strip()[:200], "descripcion": c.descripcion.strip()[:500]}
                   for c in tema.rubrica if c.criterio.strip()][:4]
        nivel = tema.nivel_maximo
        if nivel == "maestria" and len(rubrica) < 3:
            nivel, rubrica = "avanzado", []
        if nivel != "maestria":
            rubrica = []
        propuestas[tema.tema_id] = {"nivel_maximo": nivel, "es_fundamental": tema.es_fundamental,
                                    "rubrica": rubrica}
    modulos = [{"nombre": m.nombre.strip()[:200], "temas": [t for t in m.temas if t in validos]}
               for m in resultado.modulos if m.nombre.strip()]
    lenguajes = list(dict.fromkeys(l.strip()[:50] for l in resultado.lenguajes_codigo if l.strip()))[:10]
    return {"temas": propuestas, "modulos": modulos, "lenguajes": lenguajes}

