"""Central configuration, read from environment variables and an optional local `.env` file."""

import os
import re
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
# Real environment variables win over the file.
load_dotenv(APP_DIR / ".env", override=False)

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a"})
RECORDING_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
TEXT_EXTENSIONS = frozenset({".txt", ".vtt", ".md"})
CLASS_SOURCE_EXTENSIONS = RECORDING_EXTENSIONS | TEXT_EXTENSIONS
RESOURCE_EXTENSIONS = frozenset({".pdf", ".txt", ".md"})
# Peru has no daylight saving time; a fixed offset avoids depending on tzdata.
LIMA = timezone(timedelta(hours=-5), "America/Lima")

# Language-model providers supported through LangChain (ai/proveedores.py).
PROVEEDORES_IA = {
    "openai": {"clave": "OPENAI_API_KEY", "modelo": "gpt-6-luna", "transcripcion": "gpt-4o-mini-transcribe"},
    "gemini": {"clave": "GOOGLE_API_KEY", "modelo": "gemini-3.5-flash", "transcripcion": "gemini-3.5-flash"},
    "vertex": {"clave": "Credenciales de Google Cloud (ADC)", "modelo": "gemini-3.5-flash-lite", "transcripcion": "gemini-3.5-flash-lite"},
}


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).lower().strip()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name} debe ser true o false.")
    return value in {"true", "1", "yes"}


def env_positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} debe ser un entero mayor que cero.")
    return value


def _base_path() -> str:
    raw = os.getenv("BASE_PATH", "/").strip("/")
    return "/" + raw if raw else ""


def _proveedor(variable: str, defecto: str) -> str:
    return (os.getenv(variable) or defecto).strip().lower()


@dataclass(frozen=True)
class Settings:
    # AI behavior spec §1: provider and model are configuration, not code.
    LLM_PROVIDER: str = field(default_factory=lambda: _proveedor("LLM_PROVIDER", "openai"))
    LLM_MODEL: str = field(default_factory=lambda: (os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "").strip())
    LLM_REASONING_EFFORT: str = field(default_factory=lambda: os.getenv("LLM_REASONING_EFFORT", "low").strip())
    TRANSCRIPTION_PROVIDER: str = field(default_factory=lambda: _proveedor(
        "TRANSCRIPTION_PROVIDER", os.getenv("LLM_PROVIDER") or "openai"))
    TRANSCRIPTION_MODEL: str = field(default_factory=lambda: (
        os.getenv("TRANSCRIPTION_MODEL") or os.getenv("OPENAI_TRANSCRIPTION_MODEL") or "").strip())
    OPENAI_API_KEY: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip(), repr=False)
    GOOGLE_API_KEY: str = field(default_factory=lambda: (
        os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip(), repr=False)
    GOOGLE_CLOUD_PROJECT: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", "").strip())
    GOOGLE_CLOUD_LOCATION: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip())
    VERTEX_MODEL: str = field(default_factory=lambda: os.getenv("VERTEX_MODEL", "gemini-3.5-flash-lite").strip())
    DEMO_MODE: bool = field(default_factory=lambda: env_bool("DEMO_MODE", True))
    DEMO_PASSWORD: str = field(default_factory=lambda: os.getenv("DEMO_PASSWORD", "").strip() or "cuadrilla", repr=False)
    ADMIN_DNI: str = field(default_factory=lambda: os.getenv("ADMIN_DNI", "").strip())
    ADMIN_PASSWORD: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", "").strip(), repr=False)
    MAX_UPLOAD_MB: int = field(default_factory=lambda: env_positive_int("MAX_UPLOAD_MB", 300))
    SESSION_HOURS: int = field(default_factory=lambda: env_positive_int("SESSION_HOURS", 12))
    # Empty: an embedded PostgreSQL starts under APP_DIR/.local (db/local_pg.py).
    DATABASE_URL: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "").strip(), repr=False)
    DB_AUTO_CREATE: bool = field(default_factory=lambda: env_bool("DB_AUTO_CREATE", True))
    HOST: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1").strip())
    PORT: int = field(default_factory=lambda: env_positive_int("PORT", 8000))
    FORWARDED_ALLOW_IPS: str = field(default_factory=lambda: os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1").strip())
    BASE_PATH: str = field(default_factory=_base_path)
    SAMPLE_DIR: Path = APP_DIR / "sample_data"
    UPLOAD_DIR: Path = APP_DIR / "uploads"
    LOCAL_DIR: Path = APP_DIR / ".local"

    def __post_init__(self):
        for variable in ("LLM_PROVIDER", "TRANSCRIPTION_PROVIDER"):
            if getattr(self, variable) not in PROVEEDORES_IA:
                raise ValueError(f"{variable} debe ser uno de: {', '.join(PROVEEDORES_IA)}.")
        if self.ADMIN_DNI and not re.fullmatch(r"[0-9A-Za-z]{8,12}", self.ADMIN_DNI):
            raise ValueError("ADMIN_DNI debe tener entre 8 y 12 letras o dígitos.")

    @property
    def modelo_llm(self) -> str:
        return self.configuracion_ia().modelo

    @property
    def modelo_transcripcion(self) -> str:
        return self.configuracion_ia().modelo_audio

    def configuracion_ia(self):
        from ai import runtime
        return runtime.actual() if self is globals().get("settings") else runtime.desde_entorno(self)

    def clave(self, proveedor: str) -> str:
        return "" if proveedor == "vertex" else getattr(self, PROVEEDORES_IA[proveedor]["clave"])

    def variable_clave(self, proveedor: str | None = None) -> str:
        return PROVEEDORES_IA[proveedor or self.configuracion_ia().proveedor]["clave"]

    @property
    def ai_enabled(self) -> bool:
        return self.configuracion_ia().habilitada(self)

    @property
    def transcription_enabled(self) -> bool:
        return self.configuracion_ia().habilitada(self, audio=True)

    @property
    def demo_password_default(self) -> bool:
        return not os.getenv("DEMO_PASSWORD", "").strip()


settings = Settings()
