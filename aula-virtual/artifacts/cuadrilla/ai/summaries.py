"""Study summaries covering the full anonymized transcript, including long sessions."""

import json

from ai import privacy, prompts
from ai.anonymize import anonimizar
from ai.llm import IAError, llamar
from ai.schemas import ResumenClaseIA

MAX_FRAGMENTO = 60_000


def _fragmentos(texto):
    while len(texto) > MAX_FRAGMENTO:
        corte = texto.rfind("\n", MAX_FRAGMENTO // 2, MAX_FRAGMENTO)
        if corte < 0:
            corte = texto.rfind(" ", MAX_FRAGMENTO // 2, MAX_FRAGMENTO)
        corte = corte if corte > 0 else MAX_FRAGMENTO
        yield texto[:corte]
        texto = texto[corte:].lstrip()
    if texto.strip():
        yield texto


def _generar(datos, referencia):
    resultado = llamar("resumidor", ResumenClaseIA, prompts.RESUMIDOR, datos,
                       referencia=referencia, max_tokens=6500, timeout=180)
    # Treat generated text as untrusted content too. Jinja escapes it when rendered.
    conocidos = privacy.conocidos()
    contenido = resultado.model_dump()
    contenido["introduccion"] = anonimizar(contenido["introduccion"].strip(), conocidos)
    for seccion in contenido["secciones"]:
        seccion.update({k: anonimizar(v.strip(), conocidos) for k, v in seccion.items()})
    puntos = [anonimizar(p.strip(), conocidos)[:400] for p in contenido["puntos_clave"] if p.strip()]
    contenido["puntos_clave"] = list(dict.fromkeys(puntos))
    return ResumenClaseIA.model_validate(contenido).model_dump()


def generar(transcript: str, *, referencia):
    texto = anonimizar(transcript or "", privacy.conocidos(forzar=True)).strip()
    if not texto:
        raise IAError("La clase todavía no tiene un transcript para resumir.")
    fragmentos = list(_fragmentos(texto))
    if len(fragmentos) == 1:
        return _generar({"transcript": texto}, referencia)
    parciales = [_generar({"transcript": parte, "fragmento": i + 1, "total": len(fragmentos)}, referencia)
                 for i, parte in enumerate(fragmentos)]
    # Reduce in bounded groups. Every piece of the transcript participates; no prefix truncation.
    while len(parciales) > 1:
        grupos, grupo, longitud = [], [], 0
        for parcial in parciales:
            tamano = len(json.dumps(parcial, ensure_ascii=False))
            if grupo and longitud + tamano > MAX_FRAGMENTO:
                grupos.append(grupo)
                grupo, longitud = [], 0
            grupo.append(parcial)
            longitud += tamano
        grupos.append(grupo)
        parciales = [_generar({"resumenes_parciales_en_orden": grupo}, referencia) if len(grupo) > 1 else grupo[0]
                     for grupo in grupos]
    return parciales[0]
