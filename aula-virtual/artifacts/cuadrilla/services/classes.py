"""Class upload and processing (spec §7.1): transcribe, anonymize, map to the malla, pregenerate 4 challenges."""

import io
import logging
from datetime import date, timedelta
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ai import jobs, privacy
from ai.anonymize import anonimizar
from config import settings
from db.models import Clase, ClaseTema, Curso, Reto, RetoVersion, Tema
from rules.calendar import ahora

logger = logging.getLogger("cuadrilla.clases")
VALIDACION_MINUTOS = 60  # Fixed by the spec: the teacher has one hour.
POSICIONES = (1, 2, 3, 4)
MAX_RECURSOS = 60_000


class ClaseInvalida(ValueError):
    pass


def tema_dict(tema: Tema, evidencia: str = "") -> dict:
    return {"tema_id": tema.id, "nombre": tema.etiqueta, "subtema": tema.subtema, "objetivo": tema.objetivo,
            "nivel_maximo": tema.nivel_maximo, "rubrica": tema.rubrica, "modulo": tema.modulo,
            "evidencia": evidencia}


def texto_de_recurso(nombre: str, contenido: bytes) -> str:
    if nombre.lower().endswith(".pdf"):
        try:
            lector = PdfReader(io.BytesIO(contenido))
            return " ".join(" ".join((p.extract_text() or "") for p in lector.pages[:80]).split())
        except Exception as error:
            raise ClaseInvalida(f"No pudimos leer el PDF «{nombre}».") from error
    try:
        return contenido.decode("utf-8-sig").strip()
    except UnicodeDecodeError as error:
        raise ClaseInvalida(f"«{nombre}» debe estar en UTF-8.") from error


def crear_clase(db, curso: Curso, usuario_id: int, *, numero: int, fecha: date, titulo: str, fuente_tipo: str,
                fuente_archivo: str | None, fuente_nombre: str, transcript: str | None,
                recursos: list[tuple[str, bytes]], tarea: str | None) -> Clase:
    if curso.estado != "activo":
        raise ClaseInvalida("El curso está cerrado.")
    if not db.scalar(select(func.count()).select_from(Tema).where(Tema.curso_id == curso.id)):
        raise ClaseInvalida("Primero carga la malla del curso: los retos se basan en sus temas.")
    if numero < 1 or numero > 500:
        raise ClaseInvalida("El número de clase debe estar entre 1 y 500.")
    if db.scalar(select(Clase.id).where(Clase.curso_id == curso.id, Clase.numero == numero)):
        raise ClaseInvalida(f"Ya existe la clase {numero} en este curso.")
    textos, nombres = [], []
    for nombre, contenido in recursos:
        texto = texto_de_recurso(nombre, contenido)
        if texto:
            textos.append(f"[{nombre}]\n{texto}")
            nombres.append({"nombre": nombre, "caracteres": len(texto)})
    conocidos = privacy.conocidos(forzar=True)
    clase = Clase(
        curso_id=curso.id, numero=numero, fecha=fecha, titulo=titulo.strip()[:250], fuente_tipo=fuente_tipo,
        fuente_archivo=fuente_archivo, fuente_nombre=fuente_nombre[:500], transcript=transcript,
        recursos=nombres, recursos_texto=anonimizar("\n\n".join(textos), conocidos)[:MAX_RECURSOS] or None,
        tarea=(tarea or "").strip()[:2000] or None, estado="procesando", creado_por=usuario_id,
    )
    db.add(clase)
    try:
        db.flush()
    except IntegrityError as error:
        raise ClaseInvalida(f"Ya existe la clase {numero} en este curso.") from error
    jobs.al_confirmar(db, procesar_clase, clase.id, pesado=True, curso_id=clase.curso_id)
    return clase


def reintentar(db, clase: Clase) -> None:
    if clase.estado != "error":
        raise ClaseInvalida("Solo se reintenta una clase con error.")
    clase.estado, clase.error_mensaje, clase.paso = "procesando", None, None
    jobs.al_confirmar(db, procesar_clase, clase.id, pesado=True, curso_id=clase.curso_id)


def ajustar_temas(db, clase: Clase, tema_ids: list[int]) -> None:
    """Teacher adjusts the mapping; only topics of this course's malla. History is never rewritten."""
    validos = set(db.scalars(select(Tema.id).where(Tema.curso_id == clase.curso_id, Tema.id.in_(tema_ids or [0]))))
    if not validos:
        raise ClaseInvalida("Elige al menos un tema de la malla.")
    actuales = {ct.tema_id: ct for ct in db.scalars(select(ClaseTema).where(ClaseTema.clase_id == clase.id))}
    for tema_id, fila in actuales.items():
        if tema_id not in validos:
            db.delete(fila)
    for tema_id in validos - actuales.keys():
        db.add(ClaseTema(clase_id=clase.id, tema_id=tema_id, evidencia="", confianza=1.0, origen="docente"))


def temas_de_clase(db, clase_id: int) -> list[tuple[Tema, ClaseTema]]:
    return db.execute(select(Tema, ClaseTema).join(ClaseTema, ClaseTema.tema_id == Tema.id).where(
        ClaseTema.clase_id == clase_id,
    ).order_by(ClaseTema.confianza.desc(), Tema.orden)).all()


def guardar_versiones(db, reto: Reto, versiones: dict, revision: int | None = None) -> None:
    for nivel, datos in versiones.items():
        db.add(RetoVersion(reto_id=reto.id, revision=revision or reto.revision, nivel=nivel, **datos))


def crear_reto(db, *, curso_id: int, clase_id: int | None, generado, uso: str = "clase", posicion=None,
               estado: str = "propuesto", origen: str = "ia", reemplaza_a=None, vence=None) -> Reto:
    reto = Reto(curso_id=curso_id, clase_id=clase_id, tema_id=generado.tema_id, uso=uso, posicion=posicion,
                origen=origen, estado=estado, error_comun=generado.error_comun, fuente_tipo=generado.fuente_tipo,
                fuente_ref=generado.fuente_ref, avisos=generado.avisos, reemplaza_a=reemplaza_a,
                vence_validacion_en=vence)
    db.add(reto)
    db.flush()
    guardar_versiones(db, reto, generado.versiones)
    return reto


def _fallar(clase_id: int, mensaje: str) -> None:
    from db.session import SessionLocal
    with SessionLocal.begin() as db:
        clase = db.get(Clase, clase_id)
        if clase is not None and clase.estado == "procesando":
            clase.estado, clase.paso, clase.error_mensaje = "error", None, mensaje[:1000]


def _paso(clase_id: int, paso: str) -> None:
    from db.session import SessionLocal
    with SessionLocal.begin() as db:
        clase = db.get(Clase, clase_id)
        if clase is not None:
            clase.paso = paso


def procesar_clase(clase_id: int) -> None:
    """Each step commits on its own, so a retry resumes after the last completed step."""
    from ai.components import generar_previo, generar_retos_clase, mapear
    from ai.llm import mensaje_seguro
    from ai.transcription import SourceProcessingError, get_transcript
    from db.session import SessionLocal

    try:
        with SessionLocal() as db:
            clase = db.get(Clase, clase_id)
            if clase is None or clase.estado != "procesando":
                return
            curso_id, numero = clase.curso_id, clase.numero
            necesita_transcript = not (clase.transcript or "").strip()
            archivo, tipo = clase.fuente_archivo, clase.fuente_tipo
        if necesita_transcript:
            if not settings.transcription_enabled and tipo != "texto":
                raise SourceProcessingError(
                    f"Configura {settings.variable_clave(settings.configuracion_ia().transcriptor)} para transcribir videos o audios.")
            _paso(clase_id, "transcribiendo")
            ruta = settings.UPLOAD_DIR / (archivo or "")
            if not archivo or not ruta.is_file():
                raise SourceProcessingError("No encontramos el archivo de la clase. Vuelve a subirla.")
            texto = get_transcript(ruta, tipo, referencia=f"clase:{clase_id}")
            with SessionLocal.begin() as db:
                db.get(Clase, clase_id).transcript = texto

        _paso(clase_id, "anonimizando")
        with SessionLocal.begin() as db:
            clase = db.get(Clase, clase_id)
            clase.transcript_anon = anonimizar(clase.transcript, privacy.conocidos(forzar=True))
            transcript = clase.transcript_anon
            material = clase.recursos_texto or ""
            mapeados = db.scalar(select(func.count()).select_from(ClaseTema).where(ClaseTema.clase_id == clase_id))
            temas_curso = [tema_dict(t) for t in db.scalars(select(Tema).where(Tema.curso_id == curso_id).order_by(Tema.orden))]
            brochure = db.get(Curso, curso_id).brochure_texto or ""
            from services.summaries import programar
            programar(db, clase)

        if not settings.ai_enabled:
            raise SourceProcessingError(f"Configura {settings.variable_clave()} para pregenerar el quiz con IA.")
        if not mapeados:
            _paso(clase_id, "mapeando")
            propuestos = mapear(transcript, temas_curso, referencia=f"clase:{clase_id}")
            if not propuestos:
                raise SourceProcessingError(
                    "La IA no encontró temas de la malla en esta clase. Elige los temas a mano y reintenta.")
            with SessionLocal.begin() as db:
                for fila in propuestos:
                    db.add(ClaseTema(clase_id=clase_id, tema_id=fila["tema_id"], evidencia=fila["evidencia"],
                                     confianza=fila["confianza"], origen="ia"))

        with SessionLocal() as db:
            temas = [tema_dict(t, ct.evidencia) for t, ct in temas_de_clase(db, clase_id)]
            existentes = db.scalar(select(func.count()).select_from(Reto).where(
                Reto.clase_id == clase_id, Reto.uso == "clase"))
            tiene_previo = db.scalar(select(func.count()).select_from(Reto).where(
                Reto.clase_id == clase_id, Reto.uso == "previo"))
        if not existentes:
            _paso(clase_id, "generando")
            generados = generar_retos_clase(temas, transcript, material, list(POSICIONES), [],
                                            referencia=f"clase:{clase_id}")
            if not generados:
                raise SourceProcessingError("La IA no logró retos sustentados en la clase. Reintenta en unos minutos.")
            with SessionLocal.begin() as db:
                obtenidas = set()
                for generado in generados:
                    crear_reto(db, curso_id=curso_id, clase_id=clase_id, generado=generado, posicion=generado.posicion)
                    obtenidas.add(generado.posicion)
                for posicion in POSICIONES:
                    if posicion not in obtenidas:
                        db.add(Reto(curso_id=curso_id, clase_id=clase_id, tema_id=temas[0]["tema_id"], uso="clase",
                                    posicion=posicion, estado="error",
                                    error_mensaje="La IA no produjo un reto válido para esta posición."))
        if numero == 1 and not tiene_previo:
            try:
                previo = generar_previo(temas, brochure, referencia=f"clase:{clase_id}:previo")
                with SessionLocal.begin() as db:
                    crear_reto(db, curso_id=curso_id, clase_id=clase_id, generado=previo, uso="previo")
            except Exception as error:  # The quiz still works: the 4th base challenge takes its place.
                logger.warning("Sin reto de conocimiento previo para la clase %s: %s", clase_id, type(error).__name__)

        with SessionLocal.begin() as db:
            clase = db.get(Clase, clase_id)
            if clase.estado == "procesando":
                momento = ahora()
                clase.estado, clase.paso, clase.error_mensaje = "por_validar", None, None
                clase.aviso_docente_en = momento
                clase.vence_validacion_en = momento + timedelta(minutes=VALIDACION_MINUTOS)
    except SourceProcessingError as error:
        _fallar(clase_id, str(error))
    except Exception as error:
        logger.warning("Falló el procesamiento de la clase %s (%s)", clase_id, type(error).__name__)
        _fallar(clase_id, mensaje_seguro(error))


def ruta_subida(nombre_original: str) -> tuple[str, Path]:
    import secrets
    sufijo = Path(nombre_original).suffix.lower()
    nombre = f"{secrets.token_hex(16)}{sufijo}"
    return nombre, settings.UPLOAD_DIR / nombre
