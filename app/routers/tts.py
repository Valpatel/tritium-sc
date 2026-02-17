"""Piper TTS API — /api/tts/* endpoints.

Server-side text-to-speech using Piper. Falls back gracefully
when Piper binary or voice models are unavailable.
"""

from __future__ import annotations

import hashlib
import struct
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from amy.speaker import DEFAULT_PIPER_DIR, DEFAULT_PIPER_BIN, Speaker

router = APIRouter(prefix="/api/tts", tags=["tts"])

# Lazy-init singleton
_speaker: Speaker | None = None
_speaker_checked = False

# Simple LRU cache for synthesized audio
_cache: OrderedDict[str, bytes] = OrderedDict()
_CACHE_MAX = 32


def _get_speaker() -> Speaker | None:
    global _speaker, _speaker_checked
    if _speaker_checked:
        return _speaker
    _speaker_checked = True
    s = Speaker()
    if s.available:
        _speaker = s
    return _speaker


def _make_wav(pcm: bytes, sample_rate: int = 22050) -> bytes:
    """Prepend a 44-byte WAV header to raw PCM data."""
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + len(pcm), b'WAVE',
        b'fmt ', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b'data', len(pcm),
    )
    return header + pcm


def _cache_key(text: str, voice: str | None) -> str:
    return hashlib.md5(f"{text}|{voice}".encode()).hexdigest()


class SynthesizeRequest(BaseModel):
    text: str
    voice: str | None = None


@router.get("/voices")
async def list_voices() -> dict[str, Any]:
    """List available Piper voice models."""
    piper_dir = Path(DEFAULT_PIPER_DIR)
    piper_available = Path(DEFAULT_PIPER_BIN).is_file()

    voices: list[dict[str, str]] = []
    if piper_dir.is_dir():
        for onnx in sorted(piper_dir.glob("*.onnx")):
            # Parse voice name from filename: en_US-amy-medium.onnx
            parts = onnx.stem.split("-")
            lang = parts[0] if parts else "unknown"
            name = parts[1] if len(parts) > 1 else onnx.stem
            quality = parts[2] if len(parts) > 2 else "medium"
            voices.append({
                "id": onnx.stem,
                "name": name,
                "language": lang.replace("_", "-"),
                "quality": quality,
                "file": onnx.name,
            })

    return {
        "piper_available": piper_available,
        "voices": voices,
    }


@router.post("/synthesize")
async def synthesize(body: SynthesizeRequest) -> Response:
    """Synthesize text to WAV audio using Piper TTS."""
    if not body.text or not body.text.strip():
        return JSONResponse({"error": "Text is required"}, status_code=400)

    speaker = _get_speaker()
    if speaker is None:
        return JSONResponse(
            {"error": "Piper TTS not available"},
            status_code=503,
        )

    # Check cache
    key = _cache_key(body.text, body.voice)
    if key in _cache:
        _cache.move_to_end(key)
        return Response(content=_cache[key], media_type="audio/wav")

    # Synthesize in thread to avoid blocking event loop
    import asyncio
    loop = asyncio.get_event_loop()
    pcm = await loop.run_in_executor(None, speaker.synthesize_raw, body.text)

    if pcm is None:
        return JSONResponse(
            {"error": "Synthesis failed"},
            status_code=500,
        )

    wav = _make_wav(pcm, speaker.sample_rate)

    # Cache it
    _cache[key] = wav
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)

    return Response(content=wav, media_type="audio/wav")
