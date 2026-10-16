"""OpenAI and Gemini through the real LangChain integrations, with the HTTP transport intercepted.

No network and no API key: requests are captured at httpx level, so these tests prove the
exact payload each provider receives and that switching LLM_PROVIDER is configuration only.
"""

import apoyo  # noqa: F401  (must be first)

import json
import tempfile
import wave
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import httpx
import httpx2
from sqlalchemy import select

from ai import llm, proveedores
from ai.llm import IAError
from ai.schemas import EvaluacionAbiertaIA, MallaPdfIA, MapeoIA, PropuestaIA, ResumenClaseIA, RetosIA
from ai.transcription import _extract_audio_chunks, ffmpeg
from db.models import LlamadaIA
from db.session import SessionLocal
from falso_llm import FalsoModelo

EJEMPLOS = {
    ResumenClaseIA: lambda: FalsoModelo().resumidor({"transcript": "clase"}, ""),
    MallaPdfIA: lambda: FalsoModelo().importador_malla({"texto_pdf": "Consultas SQL"}, ""),
    RetosIA: lambda: FalsoModelo().generador({"posiciones": [1, 2], "temas_clase": [
        {"tema_id": 1, "nivel_maximo": "maestria", "rubrica": [{}] * 3}]}, "MODO clase"),
    MapeoIA: lambda: FalsoModelo().mapeador({"temas_malla": [{"tema_id": 1}, {"tema_id": 2}]}, ""),
    EvaluacionAbiertaIA: lambda: FalsoModelo().calificador({"reto": {"puntos_clave": ["a", "b"]}}, ""),
    PropuestaIA: lambda: FalsoModelo().proponedor({"malla": [{"tema_id": 1}, {"tema_id": 2}]}, ""),
}


def respuesta_openai(contenido: dict) -> dict:
    return {"id": "c1", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(contenido)}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}


def respuesta_gemini(texto: str) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": texto}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 5, "totalTokenCount": 17}}


@contextmanager
def http_simulado(responder):
    """Every request of the OpenAI and Google SDKs (httpx or httpx2) goes to `responder(request)`.

    responder returns (status, body) where body is a dict (JSON) or a str (plain text).
    """
    capturas = []

    def transporte(modulo):
        def manejar(_transporte, request):
            request.read()
            capturas.append(request)
            estado, cuerpo = responder(request)
            if isinstance(cuerpo, str):
                return modulo.Response(estado, text=cuerpo, headers={"content-type": "text/plain"}, request=request)
            return modulo.Response(estado, json=cuerpo, request=request)
        return manejar
    with mock.patch.object(httpx.HTTPTransport, "handle_request", transporte(httpx)), \
            mock.patch.object(httpx2.HTTPTransport, "handle_request", transporte(httpx2)):
        yield capturas


class ProveedoresTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.demo()

    def usar(self, proveedor, **extra):
        valores = dict(LLM_PROVIDER=proveedor, TRANSCRIPTION_PROVIDER=proveedor, LLM_MODEL="", TRANSCRIPTION_MODEL="",
                       OPENAI_API_KEY="clave-openai", GOOGLE_API_KEY="clave-google", LLM_REASONING_EFFORT="low")
        apoyo.configurar(self, **(valores | extra))

    def test_openai_por_langchain(self):
        self.usar("openai")
        contenido = EJEMPLOS[EvaluacionAbiertaIA]()
        with http_simulado(lambda r: (200, respuesta_openai(contenido))) as capturas:
            resultado = llm.llamar("calificador", EvaluacionAbiertaIA, "sistema", {"respuesta_alumno": "texto"},
                                   referencia="intento:1", max_tokens=900)
        self.assertIsInstance(resultado, EvaluacionAbiertaIA)
        peticion = capturas[0]
        self.assertEqual((peticion.url.host, peticion.url.path), ("api.openai.com", "/v1/chat/completions"))
        self.assertEqual(peticion.headers["authorization"], "Bearer clave-openai")
        cuerpo = json.loads(peticion.content)
        self.assertEqual((cuerpo["model"], cuerpo["reasoning_effort"], cuerpo["max_completion_tokens"]),
                         ("gpt-6-luna", "low", 900))
        self.assertEqual(cuerpo["response_format"]["type"], "json_schema")
        self.assertTrue(cuerpo["response_format"]["json_schema"]["strict"])
        with SessionLocal() as db:
            uso = db.scalar(select(LlamadaIA))
        self.assertEqual((uso.modelo, uso.tokens_entrada, uso.tokens_salida, uso.ok), ("openai:gpt-6-luna", 11, 7, True))

    def test_gemini_por_langchain_solo_cambiando_la_configuracion(self):
        self.usar("gemini")
        contenido = EJEMPLOS[MapeoIA]()
        with http_simulado(lambda r: (200, respuesta_gemini(json.dumps(contenido)))) as capturas:
            resultado = llm.llamar("mapeador", MapeoIA, "sistema", {"transcript": "clase"})
        self.assertEqual([t.tema_id for t in resultado.temas], [1, 2])
        peticion = capturas[0]
        self.assertEqual(peticion.url.host, "generativelanguage.googleapis.com")
        self.assertTrue(peticion.url.path.endswith("/models/gemini-3.8-flash:generateContent"))
        self.assertEqual(peticion.headers["x-goog-api-key"], "clave-google")
        configuracion = json.loads(peticion.content)["generationConfig"]
        self.assertIn("responseJsonSchema", configuracion)
        self.assertIn("low", json.dumps(configuracion["thinkingConfig"]).lower())
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(LlamadaIA.modelo)), "gemini:gemini-3.8-flash")

    def test_todos_los_esquemas_funcionan_en_ambos_proveedores(self):
        for proveedor in ("openai", "gemini"):
            for esquema, ejemplo in EJEMPLOS.items():
                with self.subTest(proveedor=proveedor, esquema=esquema.__name__):
                    self.usar(proveedor)
                    contenido = ejemplo()
                    cuerpo = (respuesta_openai(contenido) if proveedor == "openai"
                              else respuesta_gemini(json.dumps(contenido)))
                    with http_simulado(lambda r, c=cuerpo: (200, c)):
                        resultado = llm.llamar("prueba", esquema, "sistema", {"dato": 1})
                    self.assertEqual(resultado.model_dump(), esquema.model_validate(contenido).model_dump())

    def test_modelo_configurable(self):
        self.usar("gemini", LLM_MODEL="gemini-3.1-pro-preview")
        self.assertEqual(proveedores.crear_chat().model.split("/")[-1], "gemini-3.1-pro-preview")
        self.usar("openai", LLM_MODEL="gpt-5-mini")
        self.assertEqual(proveedores.crear_chat().model_name, "gpt-5-mini")

    def test_errores_del_proveedor_se_explican_sin_detalles_internos(self):
        self.usar("gemini")
        with http_simulado(lambda r: (401, {"error": {"code": 401, "message": "API key not valid",
                                                         "status": "UNAUTHENTICATED"}})):
            with self.assertRaises(IAError) as contexto:
                llm.llamar("mapeador", MapeoIA, "sistema", {"transcript": "clase"})
        self.assertIn("GOOGLE_API_KEY", str(contexto.exception))
        self.usar("openai")
        with http_simulado(lambda r: (404, {"error": {"message": "model not found"}})):
            with self.assertRaises(IAError) as contexto:
                llm.llamar("mapeador", MapeoIA, "sistema", {"transcript": "clase"})
        self.assertIn("LLM_MODEL", str(contexto.exception))
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(LlamadaIA.ok).order_by(LlamadaIA.id.desc())), False)

    def test_sin_clave_no_se_llama_al_proveedor(self):
        apoyo.configurar(self, LLM_PROVIDER="gemini", GOOGLE_API_KEY="")
        with self.assertRaises(IAError) as contexto:
            llm.llamar("mapeador", MapeoIA, "sistema", {})
        self.assertIn("GOOGLE_API_KEY", str(contexto.exception))


class TranscripcionTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.carpeta = Path(tempfile.mkdtemp(prefix="cuadrilla-audio-test-"))
        self.audio = self.carpeta / "clase.wav"
        with wave.open(str(self.audio), "wb") as archivo:
            archivo.setnchannels(1)
            archivo.setsampwidth(2)
            archivo.setframerate(16000)
            archivo.writeframes(b"\x00\x00" * 16000)

    def test_ffmpeg_incluido_extrae_audio(self):
        self.assertIsNotNone(ffmpeg())
        partes = _extract_audio_chunks(self.audio, self.carpeta)
        self.assertEqual(len(partes), 1)
        self.assertGreater(partes[0].stat().st_size, 0)

    def test_transcripcion_con_gemini_envia_el_audio(self):
        apoyo.configurar(self, TRANSCRIPTION_PROVIDER="gemini", TRANSCRIPTION_MODEL="", GOOGLE_API_KEY="clave-google")
        with http_simulado(lambda r: (200, respuesta_gemini("Hola, hoy vemos pandas."))) as capturas:
            texto = proveedores.transcribir(self.audio, "Clase de DMC.")
        self.assertEqual(texto, "Hola, hoy vemos pandas.")
        partes = json.loads(capturas[0].content)["contents"][0]["parts"]
        self.assertTrue(any("inlineData" in p for p in partes))

    def test_transcripcion_con_openai_usa_su_endpoint(self):
        apoyo.configurar(self, TRANSCRIPTION_PROVIDER="openai", TRANSCRIPTION_MODEL="", OPENAI_API_KEY="clave-openai")
        with http_simulado(lambda r: (200, "Hola, hoy vemos pandas.")) as capturas:
            texto = proveedores.transcribir(self.audio, "Clase de DMC.")
        self.assertEqual(texto.strip(), "Hola, hoy vemos pandas.")
        self.assertEqual(capturas[0].url.path, "/v1/audio/transcriptions")
        self.assertIn(b"gpt-4o-mini-transcribe", capturas[0].content)
