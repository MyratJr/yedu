"""
app/processors/voice.py

Whisper speech-to-text.
WHISPER_MODE=local  → loads model in-process (GPU/CPU)
WHISPER_MODE=api    → calls OpenAI transcription endpoint
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def transcribe(audio_bytes: bytes) -> str:
    settings = get_settings()
    if settings.whisper_mode == "api":
        return await _transcribe_api(audio_bytes)
    return await _transcribe_local(audio_bytes)


async def _transcribe_local(audio_bytes: bytes) -> str:
    from faster_whisper import WhisperModel

    settings = get_settings()
    model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        segments, _ = model.transcribe(tmp_path)
        text = " ".join(s.text for s in segments).strip()
        logger.debug("faster-whisper transcribed: %s", text[:80])
        return text
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def _transcribe_api(audio_bytes: bytes) -> str:
    from openai import AsyncOpenAI

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "audio.wav"

    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
    )
    text = response.text.strip()
    logger.debug("Whisper API transcribed: %s", text[:80])
    return text