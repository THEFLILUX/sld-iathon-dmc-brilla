"""Transcription service (PRD §8): local VTT/text cleanup and speech-to-text with the configured provider."""

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ai import llm, proveedores, runtime

MAX_TRANSCRIPT_CHARS = 300_000
MAX_TRANSCRIPTION_FILE_BYTES = 24 * 1024 * 1024
FFMPEG_SEGMENT_SECONDS = 20 * 60
INSTRUCCIONES = (
    "Clase en español de DMC Institute sobre tecnología, datos e inteligencia artificial. "
    "Vocabulario técnico: SQL, Python, dashboard, API, modelo, variable, prompt, RAG, transcript, "
    "DMC Coins, quiz, reto, clase, cohorte. Conserva estos términos sin traducirlos ni añadir contenido "
    "que no se escuche en el audio."
)


def ffmpeg() -> str | None:
    """System ffmpeg if installed; otherwise the static binary shipped with imageio-ffmpeg."""
    encontrado = shutil.which("ffmpeg")
    if encontrado:
        return encontrado
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class SourceProcessingError(ValueError):
    """A controlled error whose message is safe to show to the teacher."""


def clean_vtt(raw_text: str) -> str:
    lines: list[str] = []
    for line in raw_text.lstrip("\ufeff").splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or line.startswith(("NOTE", "STYLE", "REGION")):
            continue
        if "-->" in line or re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]*>", "", line)
        line = re.sub(r"&nbsp;", " ", line, flags=re.IGNORECASE)
        line = re.sub(r"&amp;", "&", line, flags=re.IGNORECASE)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _read_text_source(source: Path) -> str:
    if source.stat().st_size > MAX_TRANSCRIPT_CHARS * 4:
        raise SourceProcessingError("El transcript es demasiado grande. Divide la clase en archivos más pequeños.")
    try:
        content = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceProcessingError("El transcript debe estar codificado como texto UTF-8.") from exc
    transcript = clean_vtt(content) if source.suffix.lower() == ".vtt" else content.strip()
    return _validate_transcript(transcript)


def _validate_transcript(transcript: str) -> str:
    transcript = transcript.strip()
    if not transcript:
        raise SourceProcessingError("El archivo no contiene texto o una transcripción legible.")
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise SourceProcessingError(
            "La transcripción supera el límite de 300,000 caracteres. "
            "Divide la clase en archivos más pequeños."
        )
    return transcript


def _extract_audio_chunks(source: Path, output_dir: Path) -> list[Path]:
    pattern = output_dir / "segment-%03d.mp3"
    ejecutable = ffmpeg()
    if ejecutable is None:
        raise SourceProcessingError("No encontramos ffmpeg para extraer el audio de la clase. Instala ffmpeg.")
    try:
        result = subprocess.run(
            [
                ejecutable, "-v", "error", "-nostdin", "-i", str(source),
                "-vn", "-ac", "1", "-b:a", "64k", "-c:a", "libmp3lame",
                "-f", "segment", "-segment_time", str(FFMPEG_SEGMENT_SECONDS),
                "-reset_timestamps", "1", str(pattern),
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SourceProcessingError("No encontramos ffmpeg para extraer el audio de la clase.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceProcessingError("La extracción de audio excedió el tiempo permitido.") from exc
    chunks = sorted(output_dir.glob("segment-*.mp3"))
    if result.returncode != 0 or not chunks:
        raise SourceProcessingError(
            "No pudimos extraer audio. Comprueba que el archivo se pueda reproducir y que tenga audio."
        )
    if any(chunk.stat().st_size > MAX_TRANSCRIPTION_FILE_BYTES for chunk in chunks):
        raise SourceProcessingError("El audio de la clase es demasiado grande para transcribirlo de una vez.")
    return chunks


@runtime.snapshot
def transcribe_audio_source(source: Path, referencia=None) -> str:
    with tempfile.TemporaryDirectory(prefix="cuadrilla-audio-") as temp_name:
        chunks = _extract_audio_chunks(source, Path(temp_name))
        transcripts: list[str] = []
        config = runtime.actual()
        modelo = f"{config.transcriptor}:{config.modelo_audio}"
        for chunk in chunks:
            inicio = time.monotonic()
            try:
                text = proveedores.transcribir(chunk, INSTRUCCIONES)
            except Exception as error:
                llm.registrar_uso("transcripcion", modelo, referencia, None, inicio, False, type(error).__name__)
                raise
            llm.registrar_uso("transcripcion", modelo, referencia, None, inicio, True)
            if text.strip():
                transcripts.append(text.strip())
                _validate_transcript("\n\n".join(transcripts))
    return _validate_transcript("\n\n".join(transcripts))


def get_transcript(source: Path, source_type: str, referencia=None) -> str:
    if source_type == "texto":
        return _read_text_source(source)
    if source_type in {"video", "audio"}:
        return transcribe_audio_source(source, referencia)
    raise SourceProcessingError("El formato de origen de la clase no es compatible.")
