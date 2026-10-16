"""Language-model providers through LangChain.

Switching from OpenAI to Gemini is configuration only: LLM_PROVIDER (and its API key),
optionally LLM_MODEL. Every component talks to a LangChain chat model; nothing else in
the app imports a provider SDK. To add a provider, register a factory in FABRICAS and
a transcriber in TRANSCRIPTORES.
"""

import base64
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from config import settings
from ai import runtime


def _openai(modelo: str, *, max_tokens: int, timeout: float) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    opciones = {"reasoning_effort": settings.LLM_REASONING_EFFORT} if settings.LLM_REASONING_EFFORT else {}
    return ChatOpenAI(model=modelo, api_key=settings.OPENAI_API_KEY, max_tokens=max_tokens, timeout=timeout,
                      max_retries=1, **opciones)


def _gemini(modelo: str, *, max_tokens: int, timeout: float) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    opciones = {"thinking_level": settings.LLM_REASONING_EFFORT} if settings.LLM_REASONING_EFFORT else {}
    return ChatGoogleGenerativeAI(model=modelo, google_api_key=settings.GOOGLE_API_KEY, max_output_tokens=max_tokens,
                                  vertexai=False, timeout=timeout, max_retries=1, **opciones)


def _vertex(modelo: str, *, max_tokens: int, timeout: float) -> BaseChatModel:
    import google.auth
    from langchain_google_genai import ChatGoogleGenerativeAI

    config = runtime.actual()
    credenciales, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    opciones = {"thinking_level": config.razonamiento} if config.razonamiento and modelo.startswith("gemini-3") else {}
    return ChatGoogleGenerativeAI(model=modelo, vertexai=True, project=config.proyecto, location=config.ubicacion,
        credentials=credenciales, max_output_tokens=max_tokens, timeout=timeout, max_retries=1, **opciones)


FABRICAS = {"openai": _openai, "gemini": _gemini, "vertex": _vertex}


def crear_chat(*, proveedor: str | None = None, modelo: str | None = None, max_tokens: int = 8000,
               timeout: float = 120.0) -> BaseChatModel:
    """The configured chat model. Tests replace this function with a fake model."""
    config = runtime.actual()
    proveedor = proveedor or config.proveedor
    return FABRICAS[proveedor](modelo or config.modelo, max_tokens=max_tokens, timeout=timeout)


def estructurado(salida: type[BaseModel], *, max_tokens: int, timeout: float):
    """Native JSON-schema structured output; the raw message is kept for token usage."""
    opciones = {"strict": True} if runtime.actual().proveedor == "openai" else {}
    return crear_chat(max_tokens=max_tokens, timeout=timeout).with_structured_output(
        salida, method="json_schema", include_raw=True, **opciones)


def nombre_modelo() -> str:
    config = runtime.actual()
    return f"{config.proveedor}:{config.modelo}"


# --- Speech to text -----------------------------------------------------------------------------

def _transcribir_openai(audio: Path, instrucciones: str) -> str:
    """OpenAI's dedicated transcription endpoint (cheaper and more literal than a chat model)."""
    from openai import OpenAI

    cliente = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=600.0, max_retries=1)
    with audio.open("rb") as archivo:
        resultado = cliente.audio.transcriptions.create(
            model=runtime.actual().modelo_audio, file=archivo, language="es", prompt=instrucciones,
            response_format="text")
    return resultado if isinstance(resultado, str) else getattr(resultado, "text", "")


def _transcribir_gemini(audio: Path, instrucciones: str) -> str:
    """Gemini is multimodal: the audio goes to the chat model through LangChain."""
    config = runtime.actual()
    modelo = crear_chat(proveedor=config.transcriptor, modelo=config.modelo_audio, max_tokens=32000, timeout=600.0)
    mensaje = HumanMessage(content=[
        {"type": "text", "text": "Transcribe literalmente este audio en español. Devuelve solo el texto hablado, "
                                 "sin comentarios ni marcas de tiempo. " + instrucciones},
        {"type": "audio", "base64": base64.b64encode(audio.read_bytes()).decode(), "mime_type": "audio/mpeg"},
    ])
    return modelo.invoke([mensaje]).text


TRANSCRIPTORES = {"openai": _transcribir_openai, "gemini": _transcribir_gemini, "vertex": _transcribir_gemini}


def transcribir(audio: Path, instrucciones: str) -> str:
    with runtime.usar() as config:
        return TRANSCRIPTORES[config.transcriptor](audio, instrucciones)
