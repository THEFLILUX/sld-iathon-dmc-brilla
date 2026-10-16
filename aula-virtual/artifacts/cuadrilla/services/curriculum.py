"""Malla and brochure (PRD M1, RF-01..03): closed list of topics per course."""

import csv
import io
import json
import unicodedata

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import func, select

from ai import jobs
from db.models import Curso, Tema
from rules.levels import NIVELES

MAX_FILAS = 500
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGINAS = 100
MAX_PDF_TEXTO = 120_000
COLUMNAS = {"modulo": "modulo", "tema": "nombre", "nombre": "nombre", "subtema": "subtema",
            "objetivo": "objetivo", "lenguaje": "lenguaje", "orden": "orden"}


class MallaInvalida(ValueError):
    def __init__(self, errores: list[str]):
        super().__init__("La malla tiene errores.")
        self.errores = errores


def _clave(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.strip().lower().replace(" ", "_")


def _decodificar(contenido: bytes) -> str:
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    raise MallaInvalida(["El archivo debe estar en UTF-8 o Windows-1252."])


def _filas_csv(texto: str) -> list[dict]:
    try:
        dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t")
    except csv.Error:
        dialecto = csv.excel
    lector = csv.DictReader(io.StringIO(texto), dialect=dialecto)
    if not lector.fieldnames:
        raise MallaInvalida(["El CSV no tiene encabezados. Usa: modulo, tema, subtema, objetivo."])
    return [{_clave(k or ""): (v or "") for k, v in fila.items()} for fila in lector]


def _filas_json(texto: str) -> list[dict]:
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as error:
        raise MallaInvalida([f"JSON inválido en la línea {error.lineno}: {error.msg}."]) from error
    if isinstance(datos, dict):
        datos = datos.get("temas")
    if not isinstance(datos, list) or not all(isinstance(f, dict) for f in datos):
        raise MallaInvalida(['El JSON debe ser una lista de temas o un objeto {"temas": [...]}.'])
    return [{_clave(str(k)): ("" if v is None else str(v)) for k, v in fila.items()} for fila in datos]


def leer_malla(nombre_archivo: str, contenido: bytes) -> list[dict]:
    """Parse and validate every row. Raises MallaInvalida with row-numbered errors; saves nothing."""
    if nombre_archivo.lower().endswith(".pdf"):
        return leer_malla_pdf(contenido)["temas"]
    if not nombre_archivo.lower().endswith((".csv", ".json")):
        raise MallaInvalida(["Sube la malla en CSV, JSON o PDF."])
    texto = _decodificar(contenido)
    filas = _filas_json(texto) if nombre_archivo.lower().endswith(".json") else _filas_csv(texto)
    errores, temas, vistos = [], [], {}
    if not filas:
        raise MallaInvalida(["El archivo no tiene filas."])
    if len(filas) > MAX_FILAS:
        raise MallaInvalida([f"La malla supera {MAX_FILAS} filas."])
    for numero, fila in enumerate(filas, start=2 if not nombre_archivo.lower().endswith(".json") else 1):
        datos = {destino: fila.get(origen, "").strip() for origen, destino in COLUMNAS.items() if fila.get(origen)}
        nombre, objetivo = datos.get("nombre", ""), datos.get("objetivo", "")
        subtema = datos.get("subtema", "")
        if not nombre:
            errores.append(f"Fila {numero}: falta el tema.")
        elif len(nombre) > 200 or len(subtema) > 200 or len(datos.get("modulo", "")) > 200:
            errores.append(f"Fila {numero}: el módulo, tema o subtema supera 200 caracteres.")
        if not objetivo:
            errores.append(f"Fila {numero}: falta el objetivo de aprendizaje.")
        elif len(objetivo) > 1000:
            errores.append(f"Fila {numero}: el objetivo supera 1000 caracteres.")
        if datos.get("orden") and not datos["orden"].isdigit():
            errores.append(f"Fila {numero}: el orden debe ser un número entero.")
        clave = (nombre.casefold(), subtema.casefold())
        if nombre and clave in vistos:
            errores.append(f"Fila {numero}: el tema «{nombre}{' · ' + subtema if subtema else ''}» "
                           f"está repetido (fila {vistos[clave]}).")
        vistos.setdefault(clave, numero)
        temas.append({"modulo": datos.get("modulo") or None, "nombre": nombre, "subtema": subtema,
                      "objetivo": objetivo, "lenguaje": (datos.get("lenguaje") or None),
                      "orden": int(datos["orden"]) if datos.get("orden", "").isdigit() else None})
    if errores:
        raise MallaInvalida(errores)
    return temas


def leer_malla_pdf(contenido: bytes, referencia=None) -> dict:
    """Extract a text PDF with AI, validate every row, and return an unsaved preview."""
    from ai.components import extraer_malla_pdf
    from ai.llm import mensaje_seguro
    from config import settings

    if len(contenido) > MAX_PDF_BYTES:
        raise MallaInvalida(["El PDF de la malla supera 25 MB."])
    try:
        lector = PdfReader(io.BytesIO(contenido))
        if lector.is_encrypted:
            raise MallaInvalida(["El PDF está protegido con contraseña. Desbloquéalo antes de subirlo."])
        if len(lector.pages) > MAX_PDF_PAGINAS:
            raise MallaInvalida(["La malla PDF supera 100 páginas. Divide el documento."])
        texto = "\n\n".join((pagina.extract_text() or "") for pagina in lector.pages).strip()
    except (PdfReadError, ValueError, OSError) as error:
        if isinstance(error, MallaInvalida):
            raise
        raise MallaInvalida(["No pudimos leer el PDF de la malla. Comprueba que el archivo sea válido."]) from error
    if len(texto) < 30:
        raise MallaInvalida(["El PDF no tiene texto legible. Si está escaneado, conviértelo a PDF con texto mediante OCR."])
    if len(texto) > MAX_PDF_TEXTO:
        raise MallaInvalida(["El PDF contiene demasiado texto. Divide la malla para cargarla completa."])
    if not settings.ai_enabled:
        raise MallaInvalida(["La IA no está disponible para interpretar el PDF. Configúrala o carga la malla en CSV o JSON."])
    try:
        borrador = extraer_malla_pdf(texto, referencia=referencia)
    except Exception as error:
        raise MallaInvalida(["No se pudo interpretar la malla PDF. " + mensaje_seguro(error)]) from error
    if not borrador["temas"]:
        raise MallaInvalida(borrador["avisos"] or ["No encontramos temas de una malla en este PDF."])
    temas = leer_malla("malla.json", json.dumps(borrador["temas"], ensure_ascii=False).encode())
    for tema, original in zip(temas, borrador["temas"]):
        tema["objetivo_propuesto"] = original["objetivo_propuesto"]
    return {"temas": temas, "avisos": borrador["avisos"]}


def guardar_malla(db, curso: Curso, temas: list[dict]) -> dict:
    """Upsert by (tema, subtema). Topics are never deleted: classes and attempts reference them."""
    existentes = {(t.nombre.casefold(), t.subtema.casefold()): t
                  for t in db.scalars(select(Tema).where(Tema.curso_id == curso.id))}
    siguiente = (db.scalar(select(func.max(Tema.orden)).where(Tema.curso_id == curso.id)) or 0) + 1
    creados = actualizados = 0
    for datos in temas:
        tema = existentes.get((datos["nombre"].casefold(), datos["subtema"].casefold()))
        if tema is None:
            tema = Tema(curso_id=curso.id, nombre=datos["nombre"], subtema=datos["subtema"],
                        objetivo=datos["objetivo"], orden=datos["orden"] or siguiente)
            siguiente = max(siguiente, tema.orden) + 1
            db.add(tema)
            creados += 1
        else:
            tema.objetivo = datos["objetivo"]
            if datos["orden"]:
                tema.orden = datos["orden"]
            actualizados += 1
        tema.modulo = datos["modulo"] or tema.modulo
        tema.lenguaje = datos["lenguaje"] or tema.lenguaje
    db.flush()
    return {"creados": creados, "actualizados": actualizados}


def leer_brochure(contenido: bytes) -> str:
    try:
        lector = PdfReader(io.BytesIO(contenido))
        texto = "\n".join((pagina.extract_text() or "") for pagina in lector.pages[:60])
    except (PdfReadError, ValueError, OSError) as error:
        raise ValueError("No pudimos leer el PDF del brochure.") from error
    texto = " ".join(texto.split())
    if len(texto) < 50:
        raise ValueError("El PDF no tiene texto legible (¿es una imagen escaneada?).")
    return texto[:200_000]


def solicitar_propuesta(db, curso: Curso) -> bool:
    """Ask the AI for max levels, rubrics, fundamental topics, modules and languages."""
    from config import settings
    if not settings.ai_enabled or not db.scalar(select(func.count()).select_from(Tema).where(Tema.curso_id == curso.id)):
        return False
    curso.propuesta_estado = "generando"
    curso.propuesta_error = None
    jobs.al_confirmar(db, aplicar_propuesta, curso.id, curso_id=curso.id)
    return True


def aplicar_propuesta(curso_id: int) -> None:
    from ai.components import proponer
    from ai.llm import mensaje_seguro
    from db.session import SessionLocal

    with SessionLocal() as db:
        curso = db.get(Curso, curso_id)
        if curso is None:
            return
        temas = db.scalars(select(Tema).where(Tema.curso_id == curso_id).order_by(Tema.orden)).all()
        entrada = [{"tema_id": t.id, "nombre": t.nombre, "subtema": t.subtema, "objetivo": t.objetivo,
                    "modulo": t.modulo, "nivel_maximo": t.nivel_maximo, "rubrica": t.rubrica} for t in temas]
        brochure = curso.brochure_texto or ""
    try:
        propuesta = proponer(entrada, brochure, referencia=f"curso:{curso_id}")
    except Exception as error:
        with SessionLocal.begin() as db:
            curso = db.get(Curso, curso_id)
            if curso is None:
                return
            curso.propuesta_estado, curso.propuesta_error = "error", mensaje_seguro(error)
        return
    with SessionLocal.begin() as db:
        curso = db.get(Curso, curso_id)
        if curso is None:
            return
        modulo_de = {tid: m["nombre"] for m in propuesta["modulos"] for tid in m["temas"]}
        for tema in db.scalars(select(Tema).where(Tema.curso_id == curso_id)):
            datos = propuesta["temas"].get(tema.id)
            if datos and not tema.ajustado_por_docente:
                tema.nivel_maximo = datos["nivel_maximo"] if datos["nivel_maximo"] in NIVELES else tema.nivel_maximo
                tema.es_fundamental = datos["es_fundamental"]
                tema.rubrica = datos["rubrica"]
                tema.propuesto_por_ia = True
            if not tema.modulo and tema.id in modulo_de:
                tema.modulo = modulo_de[tema.id]
        if propuesta["lenguajes"]:
            curso.lenguajes = propuesta["lenguajes"]
        curso.propuesta_estado, curso.propuesta_error = "lista", None


def ajustar_tema(db, tema: Tema, *, objetivo: str, nivel_maximo: str, es_fundamental: bool, rubrica: list[dict]):
    """Teacher edit (D7). Without Maestría there is no rubric; with it, 3 or 4 criteria are required."""
    if nivel_maximo not in NIVELES:
        raise ValueError("Nivel máximo inválido.")
    objetivo = objetivo.strip()
    if not objetivo or len(objetivo) > 1000:
        raise ValueError("El objetivo es obligatorio y tiene hasta 1000 caracteres.")
    rubrica = [c for c in rubrica if c["criterio"].strip()]
    if nivel_maximo == "maestria" and not 3 <= len(rubrica) <= 4:
        raise ValueError("Para Maestría la rúbrica necesita 3 o 4 criterios.")
    tema.objetivo = objetivo
    tema.nivel_maximo = nivel_maximo
    tema.es_fundamental = es_fundamental
    tema.rubrica = rubrica if nivel_maximo == "maestria" else []
    tema.ajustado_por_docente = True


def modulo_de_clase(numero: int) -> str:
    """Without modules in the malla, classes are grouped every 4 (RF-03)."""
    return f"Módulo {(numero - 1) // 4 + 1}"
