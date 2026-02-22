"""Audio effects API -- list, stream, and query procedural sound effects.

Endpoints:
    GET /api/audio/effects           List all effects (optional ?category= filter)
    GET /api/audio/effects/{name}    Stream WAV bytes for a specific effect
    GET /api/audio/effects/{name}/metadata  Get effect metadata
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from amy.audio.audio_library import AudioLibrary

router = APIRouter(prefix="/api/audio", tags=["audio"])

# Singleton library instance (lazy generation on first request)
_library = AudioLibrary()


@router.get("/effects")
async def list_effects(category: str | None = None) -> list[dict]:
    """List all available sound effects with metadata.

    Optional query param ?category= filters by category (combat, ambient,
    alerts, game).
    """
    effects = _library.list_effects()
    if category:
        effects = [e for e in effects if e["category"] == category]
    return effects


@router.get("/effects/{name}")
async def get_effect(name: str) -> Response:
    """Stream WAV bytes for a specific sound effect.

    Generates the effect lazily on first request, then caches to disk.
    """
    try:
        wav_bytes = _library.get_wav_bytes(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown effect: {name}")

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'inline; filename="{name}.wav"',
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get("/effects/{name}/metadata")
async def get_effect_metadata(name: str) -> dict:
    """Get metadata for a specific sound effect."""
    effects = _library.list_effects()
    for effect in effects:
        if effect["name"] == name:
            return effect
    raise HTTPException(status_code=404, detail=f"Unknown effect: {name}")
