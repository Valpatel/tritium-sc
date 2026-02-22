"""Audio Library Manager -- generates, caches, and serves WAV sound effects.

Stores effects as WAV files organized by category:
    data/synthetic/audio/
        combat/     nerf_shot, projectile_whoosh, impact_hit, explosion,
                    turret_rotate, drone_buzz, footstep
        ambient/    ambient_wind, ambient_birds
        alerts/     alert_tone, escalation_siren, dispatch_ack
        game/       wave_start, victory_fanfare, defeat_sting,
                    elimination_streak_killing_spree, elimination_streak_rampage,
                    elimination_streak_dominating, elimination_streak_godlike
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np

from .sound_effects import SoundEffectGenerator


# ---------------------------------------------------------------------------
# WAV writing (scipy preferred, pure-Python fallback)
# ---------------------------------------------------------------------------

def _write_wav(path: str, audio: np.ndarray, sample_rate: int) -> None:
    """Write float32 audio as 16-bit PCM WAV.

    Uses scipy.io.wavfile if available, otherwise writes a minimal
    RIFF/WAVE header with raw PCM16 data.
    """
    # Convert float32 [-1, 1] to int16
    pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

    try:
        from scipy.io import wavfile
        wavfile.write(path, sample_rate, pcm16)
    except ImportError:
        _write_wav_raw(path, pcm16, sample_rate)


def _write_wav_raw(path: str, pcm16: np.ndarray, sample_rate: int) -> None:
    """Write PCM16 data as a WAV file using pure Python."""
    n_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * n_channels * bits_per_sample // 8
    block_align = n_channels * bits_per_sample // 8
    data_size = len(pcm16) * block_align
    file_size = 36 + data_size  # RIFF header says file_size - 8, but convention is total - 8

    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", file_size))
        f.write(b"WAVE")

        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))  # chunk size
        f.write(struct.pack("<H", 1))   # PCM format
        f.write(struct.pack("<H", n_channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))

        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm16.tobytes())


# ---------------------------------------------------------------------------
# Effect catalog: name -> (category, method_name, duration, kwargs)
# ---------------------------------------------------------------------------

_EFFECT_CATALOG: dict[str, tuple[str, str, float, dict[str, Any]]] = {
    # Combat
    "nerf_shot":          ("combat",  "nerf_shot",          0.3,  {}),
    "projectile_whoosh":  ("combat",  "projectile_whoosh",  0.5,  {}),
    "impact_hit":         ("combat",  "impact_hit",         0.2,  {}),
    "explosion":          ("combat",  "explosion",          1.0,  {}),
    "turret_rotate":      ("combat",  "turret_rotate",      0.8,  {}),
    "drone_buzz":         ("combat",  "drone_buzz",         2.0,  {}),
    "footstep":           ("combat",  "footstep",           0.15, {}),
    # Ambient
    "ambient_wind":       ("ambient", "ambient_wind",       5.0,  {}),
    "ambient_birds":      ("ambient", "ambient_birds",      5.0,  {}),
    # Alerts
    "alert_tone":         ("alerts",  "alert_tone",         0.5,  {}),
    "escalation_siren":   ("alerts",  "escalation_siren",   2.0,  {}),
    "dispatch_ack":       ("alerts",  "dispatch_ack",       0.3,  {}),
    # Game
    "wave_start":         ("game",    "wave_start",         1.5,  {}),
    "victory_fanfare":    ("game",    "victory_fanfare",    3.0,  {}),
    "defeat_sting":       ("game",    "defeat_sting",       2.0,  {}),
    "elimination_streak_killing_spree": ("game", "elimination_streak", 1.5,
                                        {"streak_name": "KILLING SPREE"}),
    "elimination_streak_rampage":       ("game", "elimination_streak", 1.5,
                                        {"streak_name": "RAMPAGE"}),
    "elimination_streak_dominating":    ("game", "elimination_streak", 1.5,
                                        {"streak_name": "DOMINATING"}),
    "elimination_streak_godlike":       ("game", "elimination_streak", 1.5,
                                        {"streak_name": "GODLIKE"}),
}


# ---------------------------------------------------------------------------
# AudioLibrary
# ---------------------------------------------------------------------------

class AudioLibrary:
    """Manages generation, caching, and serving of procedural sound effects."""

    def __init__(self, library_path: str = "data/synthetic/audio") -> None:
        self.library_path = library_path
        self.gen = SoundEffectGenerator()

    def _effect_path(self, name: str) -> Path:
        """Return the expected file path for a named effect."""
        if name not in _EFFECT_CATALOG:
            raise KeyError(f"Unknown effect: {name!r}")
        category = _EFFECT_CATALOG[name][0]
        return Path(self.library_path) / category / f"{name}.wav"

    def _generate_effect(self, name: str) -> Path:
        """Generate a single effect and write to disk. Returns the path."""
        if name not in _EFFECT_CATALOG:
            raise KeyError(f"Unknown effect: {name!r}")

        category, method_name, duration, kwargs = _EFFECT_CATALOG[name]
        path = Path(self.library_path) / category / f"{name}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)

        audio = getattr(self.gen, method_name)(duration=duration, **kwargs)
        _write_wav(str(path), audio, self.gen.SAMPLE_RATE)
        return path

    def generate_all(self) -> dict[str, Path]:
        """Generate all sound effects, return {name: path}."""
        result: dict[str, Path] = {}
        for name in _EFFECT_CATALOG:
            result[name] = self._generate_effect(name)
        return result

    def get_effect(self, name: str) -> Path:
        """Get path to WAV file. Generate on first request (lazy)."""
        path = self._effect_path(name)
        if not path.exists():
            self._generate_effect(name)
        return path

    def list_effects(self) -> list[dict[str, Any]]:
        """List all effects with name, duration, file size, category."""
        result: list[dict[str, Any]] = []
        for name, (category, _, duration, _) in _EFFECT_CATALOG.items():
            path = self._effect_path(name)
            file_size = path.stat().st_size if path.exists() else 0
            result.append({
                "name": name,
                "category": category,
                "duration": duration,
                "file_size": file_size,
            })
        return result

    def get_wav_bytes(self, name: str) -> bytes:
        """Get raw WAV bytes for streaming. Generates lazily if needed."""
        path = self.get_effect(name)
        return path.read_bytes()

    @staticmethod
    def categories() -> list[str]:
        """Return list of all effect categories."""
        return sorted(set(cat for cat, _, _, _ in _EFFECT_CATALOG.values()))

    @staticmethod
    def effects_in_category(category: str) -> list[str]:
        """Return effect names in a given category."""
        return [name for name, (cat, _, _, _) in _EFFECT_CATALOG.items()
                if cat == category]
