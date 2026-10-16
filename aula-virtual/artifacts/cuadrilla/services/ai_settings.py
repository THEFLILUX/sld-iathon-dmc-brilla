"""Administrator model selection: verify text/audio before an optimistic, audited activation."""
import re
import time
from typing import Literal

from sqlalchemy import func, select

from ai import llm, proveedores, runtime
from ai.llm import IAError
from ai.schemas import Estricto
from config import APP_DIR
from db.models import ConfiguracionIA
from rules.calendar import ahora


class ConfiguracionInvalida(ValueError):
    pass


class ConexionIA(Estricto):
    estado: Literal["ok"]


def candidata(datos, base):
    proveedor = datos.get("proveedor", "")
    if proveedor not in ("openai", "vertex"):
        raise ConfiguracionInvalida("Selecciona OpenAI o Gemini con Vertex AI.")
    opciones = {k: str(datos.get(k, "")).strip() for k in ("modelo_openai", "audio_openai", "modelo_vertex")}
    for clave, valor in opciones.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,79}", valor) or valor.startswith("sk-"):
            raise ConfiguracionInvalida("Usa el identificador del modelo, con hasta 80 letras, números, puntos o guiones.")
    if not opciones["modelo_vertex"].startswith("gemini-"):
        raise ConfiguracionInvalida("El modelo de Vertex AI debe pertenecer a la familia Gemini.")
    config = runtime.con_opciones(base, proveedor, opciones, base.version)
    if not config.habilitada():
        raise ConfiguracionInvalida("Configura el proyecto de Google Cloud en el servidor para usar Vertex AI." if proveedor == "vertex"
                                   else "Falta OPENAI_API_KEY en el servidor. La clave se configura fuera del navegador.")
    return config


def probar(config):
    """Only a fixed, non-personal phrase is sent. No account/course content is used."""
    with runtime.usar(config):
        llm.llamar("conexion_ia", ConexionIA, "Comprobación de conexión. Devuelve el objeto JSON con estado igual a ok.",
                   {"comprobacion": "texto estructurado"}, referencia="configuracion:prueba", max_tokens=512, timeout=45)
        inicio = time.monotonic()
        try:
            texto = proveedores.transcribir(APP_DIR / "ai/fixtures/conexion.mp3",
                "Transcribe literalmente el audio en español. No añadas comentarios.")
            if len(texto.strip()) < 12 or "ventas" not in texto.casefold():
                raise IAError("El modelo respondió, pero no superó la comprobación de transcripción. Revisa el modelo de audio.")
        except Exception as error:
            llm.registrar_uso("conexion_audio", f"{config.transcriptor}:{config.modelo_audio}",
                              "configuracion:prueba", None, inicio, False, type(error).__name__)
            raise IAError(llm.mensaje_seguro(error)) from error
        llm.registrar_uso("conexion_audio", f"{config.transcriptor}:{config.modelo_audio}",
                          "configuracion:prueba", None, inicio, True)


def activar(db, config, admin_id, version):
    # Serialize the empty-table case too. The network checks have already finished outside this lock.
    db.execute(select(func.pg_advisory_xact_lock(263548019)))
    actual = runtime.cargar(db)
    if str(actual.version) != str(version):
        raise ConfiguracionInvalida("La configuración cambió en otra pestaña. Recarga y revisa el proveedor activo.")
    if actual.version and actual.proveedor == config.proveedor and actual.opciones == config.opciones:
        return actual.version
    fila = ConfiguracionIA(proveedor=config.proveedor, opciones=dict(config.opciones),
                           cambiado_por=admin_id, verificado_en=ahora())
    db.add(fila)
    db.flush()
    return fila.id
