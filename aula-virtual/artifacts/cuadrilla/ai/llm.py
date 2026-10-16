"""The only module that calls the language model (spec §10: AI calls are isolated).

Calls go through LangChain (ai/proveedores.py), so the provider is configuration. The
structured output is validated again against the Pydantic model. Every call passes the
privacy guard and is logged without personal data (component, model, tokens, outcome).
"""

import json
import logging
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from ai import privacy, proveedores, runtime
from config import settings

logger = logging.getLogger("cuadrilla.ia")


class IAError(RuntimeError):
    """A failure whose message is safe to show to teachers and students."""


def _codigo_http(error: BaseException) -> int | None:
    """HTTP status of an OpenAI or Google error, also when LangChain wraps it."""
    vistos = set()
    while error is not None and id(error) not in vistos:
        vistos.add(id(error))
        for atributo in ("status_code", "code"):
            valor = getattr(error, atributo, None)
            if isinstance(valor, int) and 100 <= valor < 600:
                return valor
        respuesta = getattr(error, "response", None)
        if isinstance(getattr(respuesta, "status_code", None), int):
            return respuesta.status_code
        error = error.__cause__ or error.__context__
    return None


def _nombres(error: BaseException) -> str:
    nombres = []
    while error is not None and len(nombres) < 6:
        nombres.append(type(error).__name__.lower())
        error = error.__cause__ or error.__context__
    return " ".join(nombres)


def mensaje_seguro(error: Exception) -> str:
    if isinstance(error, (IAError, privacy.PrivacyViolation)):
        return str(error)
    variable = settings.variable_clave()
    codigo, nombres = _codigo_http(error), _nombres(error)
    if runtime.actual().proveedor == "vertex" and (codigo in (401, 403) or "defaultcredential" in nombres or "refresherror" in nombres):
        return "Vertex AI no pudo autorizar la solicitud. Revisa la cuenta de servicio, sus permisos y la API de Vertex AI del proyecto."
    if codigo in (401, 403) or "authentication" in nombres or "permissiondenied" in nombres:
        return f"El proveedor de IA rechazó la clave. Revisa {variable} y reinicia el servicio."
    if codigo == 429 or "ratelimit" in nombres or "resourceexhausted" in nombres:
        return "El proveedor de IA alcanzó un límite o no tiene crédito disponible. Inténtalo más tarde."
    if "timeout" in nombres:
        return "La IA tardó demasiado en responder. Inténtalo nuevamente."
    if "connection" in nombres or "connecterror" in nombres:
        return "No pudimos conectar con el proveedor de IA. Revisa la red e inténtalo nuevamente."
    if codigo == 404:
        return "El proveedor de IA no encontró el modelo. Revisa LLM_MODEL o TRANSCRIPTION_MODEL."
    if codigo == 400:
        return "El proveedor de IA rechazó la solicitud. Comprueba que LLM_MODEL sea un modelo disponible."
    if codigo:
        return f"El proveedor de IA devolvió un error HTTP {codigo}. Inténtalo más tarde."
    return "No se pudo completar el procesamiento con IA. Inténtalo nuevamente."


def registrar_uso(componente: str, modelo: str, referencia, uso, inicio: float, ok: bool, error: str | None = None):
    from db.models import LlamadaIA
    from db.session import SessionLocal

    uso = uso or {}
    try:
        with SessionLocal.begin() as db:
            db.add(LlamadaIA(
                componente=componente[:30], modelo=modelo[:80], referencia=(str(referencia)[:60] if referencia else None),
                tokens_entrada=int(uso.get("input_tokens") or 0), tokens_salida=int(uso.get("output_tokens") or 0),
                duracion_ms=int((time.monotonic() - inicio) * 1000), ok=ok, error_tipo=error,
            ))
    except Exception:  # Observability must never break the learning flow.
        logger.warning("No se pudo registrar el uso de IA de %s", componente)


def _texto(mensaje) -> str:
    contenido = getattr(mensaje, "content", "")
    if isinstance(contenido, str):
        return contenido
    return "".join(p.get("text", "") for p in contenido if isinstance(p, dict))


@runtime.snapshot
def llamar(componente: str, salida: type[BaseModel], sistema: str, datos: dict, *, referencia=None,
           max_tokens: int = 8000, timeout: float = 120.0):
    if not settings.ai_enabled:
        raise IAError(f"La IA no está configurada: falta {settings.variable_clave()}.")
    contenido = json.dumps(datos, ensure_ascii=False)
    privacy.verificar(sistema + "\n" + contenido, privacy.conocidos())
    mensajes = [SystemMessage(content=sistema), HumanMessage(content=contenido)]
    modelo = proveedores.nombre_modelo()
    try:
        cadena = proveedores.estructurado(salida, max_tokens=max_tokens, timeout=timeout)
    except Exception as error:
        registrar_uso(componente, modelo, referencia, None, time.monotonic(), False, type(error).__name__)
        raise IAError(mensaje_seguro(error)) from error
    for _ in range(2):
        inicio = time.monotonic()
        try:
            resultado = cadena.invoke(mensajes)
        except Exception as error:
            registrar_uso(componente, modelo, referencia, None, inicio, False, type(error).__name__)
            raise IAError(mensaje_seguro(error)) from error
        crudo = resultado.get("raw")
        registrar_uso(componente, modelo, referencia, getattr(crudo, "usage_metadata", None), inicio, True)
        parseado = resultado.get("parsed")
        if parseado is not None and resultado.get("parsing_error") is None:
            try:
                return salida.model_validate(parseado.model_dump() if isinstance(parseado, BaseModel) else parseado)
            except ValidationError:
                pass
        mensajes = mensajes + [
            AIMessage(content=_texto(crudo)[:20000]),
            HumanMessage(content="La respuesta no cumple el esquema JSON pedido. Devuelve el JSON completo y válido."),
        ]
    raise IAError("La IA devolvió un formato inválido dos veces. Puedes reintentarlo.")
