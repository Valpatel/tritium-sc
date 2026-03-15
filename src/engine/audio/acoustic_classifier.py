# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Acoustic event classifier for the Tritium sensing pipeline.

Classifies audio events into categories like gunshot, voice, vehicle,
animal, glass break, etc. Three classification tiers:

1. Rule-based: energy/frequency thresholds (always available, no deps)
2. Pure-Python KNN: MFCC-like DCT features + euclidean KNN (no ML deps)
3. MFCC+KNN (scipy/sklearn): Real 13-coefficient MFCC via mel filterbank
   + sklearn KNeighborsClassifier (k=5). Falls back to tier 2 if deps
   missing or no training data.

The ML classifier trains on a built-in dataset of labeled audio feature
profiles. Each sound class has characteristic MFCC patterns, spectral
centroids, zero-crossing rates, and energy profiles. Can also train on
real WAV files (e.g. ESC-50) for dramatically improved accuracy.

Integration:
- Receives audio features via MQTT on `tritium/{site}/audio/{device}/raw`
- Publishes classified events to `tritium/{site}/audio/{device}/event`
- Events feed into the TargetTracker for sensor fusion
"""

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from loguru import logger

from tritium_lib.models import (
    AcousticTrainingExample,
    AcousticTrainingSet,
    TrainingSource,
)

# Optional ML dependencies — graceful degradation
_HAS_SCIPY = False
_HAS_SKLEARN = False
_HAS_NUMPY = False

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]

try:
    from scipy.fft import dct  # type: ignore[import-untyped]
    _HAS_SCIPY = True
except ImportError:
    dct = None  # type: ignore[assignment]

try:
    from sklearn.neighbors import KNeighborsClassifier as SklearnKNN  # type: ignore[import-untyped]
    from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]
    _HAS_SKLEARN = True
except ImportError:
    SklearnKNN = None  # type: ignore[assignment]
    StandardScaler = None  # type: ignore[assignment]


class AcousticEventType(str, Enum):
    """Types of acoustic events that can be classified."""

    GUNSHOT = "gunshot"
    VOICE = "voice"
    VEHICLE = "vehicle"
    ANIMAL = "animal"
    GLASS_BREAK = "glass_break"
    EXPLOSION = "explosion"
    SIREN = "siren"
    ALARM = "alarm"
    FOOTSTEPS = "footsteps"
    MACHINERY = "machinery"
    MUSIC = "music"
    UNKNOWN = "unknown"


@dataclass
class AcousticEvent:
    """A classified acoustic event."""

    event_type: AcousticEventType
    confidence: float  # 0.0 - 1.0
    timestamp: float = field(default_factory=time.time)
    duration_ms: int = 0
    peak_frequency_hz: float = 0.0
    peak_amplitude_db: float = 0.0
    device_id: str = ""
    location: Optional[tuple[float, float]] = None  # lat, lng
    model_version: str = "rule_based_v1"


@dataclass
class AudioFeatures:
    """Extracted features from an audio segment."""

    rms_energy: float = 0.0
    peak_amplitude: float = 0.0
    zero_crossing_rate: float = 0.0
    spectral_centroid: float = 0.0
    spectral_bandwidth: float = 0.0
    duration_ms: int = 0
    # MFCC coefficients (13 standard) — populated when edge sends them
    mfcc: Optional[list[float]] = None
    spectral_rolloff: float = 0.0
    spectral_flatness: float = 0.0


# ============================================================================
# Built-in training dataset — labeled audio feature profiles
# ============================================================================
# Each entry: (class_name, [13 MFCCs], spectral_centroid, zcr, rms_energy,
#              spectral_bandwidth, duration_ms)
# These are synthetic profiles based on published acoustic research for
# environmental sound classification. Enough to bootstrap a useful classifier.

TRAINING_DATA: list[tuple[str, list[float], float, float, float, float, int]] = [
    # --- GUNSHOT: high energy, impulsive, broad spectrum, very short ---
    ("gunshot", [-40, 12, -5, 3, -2, 1, -1, 0.5, -0.3, 0.2, -0.1, 0.05, -0.02],
     3500, 0.15, 0.92, 4000, 80),
    ("gunshot", [-38, 14, -6, 4, -3, 1.5, -0.8, 0.4, -0.2, 0.15, -0.08, 0.04, -0.01],
     3800, 0.18, 0.95, 4500, 50),
    ("gunshot", [-42, 11, -4, 2.5, -1.5, 0.8, -0.5, 0.3, -0.15, 0.1, -0.05, 0.03, -0.01],
     3200, 0.12, 0.88, 3800, 120),
    ("gunshot", [-35, 15, -7, 5, -3.5, 2, -1.2, 0.6, -0.35, 0.25, -0.12, 0.06, -0.03],
     4000, 0.20, 0.97, 5000, 30),

    # --- VOICE: moderate energy, 85-3000 Hz centroid, moderate ZCR ---
    ("voice", [-20, 8, 6, -3, 2, -1, 0.5, -0.3, 0.2, -0.1, 0.05, -0.03, 0.01],
     800, 0.08, 0.25, 1200, 1500),
    ("voice", [-18, 9, 7, -4, 3, -1.5, 0.8, -0.4, 0.25, -0.12, 0.06, -0.04, 0.02],
     650, 0.07, 0.30, 1000, 2000),
    ("voice", [-22, 7, 5, -2, 1.5, -0.8, 0.4, -0.2, 0.15, -0.08, 0.04, -0.02, 0.01],
     1200, 0.09, 0.20, 1500, 800),
    ("voice", [-15, 10, 8, -5, 4, -2, 1, -0.5, 0.3, -0.15, 0.08, -0.05, 0.02],
     500, 0.06, 0.35, 900, 3000),

    # --- VEHICLE: low frequency, sustained, low ZCR ---
    ("vehicle", [-30, 5, -2, 1, -0.5, 0.3, -0.2, 0.1, -0.05, 0.03, -0.02, 0.01, -0.005],
     250, 0.03, 0.35, 400, 5000),
    ("vehicle", [-28, 6, -3, 1.5, -0.8, 0.4, -0.25, 0.12, -0.06, 0.04, -0.02, 0.01, -0.005],
     180, 0.02, 0.40, 350, 8000),
    ("vehicle", [-32, 4, -1.5, 0.8, -0.4, 0.2, -0.1, 0.08, -0.04, 0.02, -0.01, 0.005, -0.002],
     320, 0.04, 0.28, 500, 3000),
    ("vehicle", [-25, 7, -4, 2, -1, 0.5, -0.3, 0.15, -0.08, 0.05, -0.03, 0.015, -0.008],
     200, 0.025, 0.45, 380, 10000),

    # --- GLASS_BREAK: high frequency, impulsive, high ZCR ---
    ("glass_break", [-35, 10, -8, 6, -4, 3, -2, 1.5, -1, 0.7, -0.5, 0.3, -0.2],
     5000, 0.25, 0.75, 6000, 200),
    ("glass_break", [-33, 11, -9, 7, -5, 3.5, -2.5, 1.8, -1.2, 0.8, -0.6, 0.35, -0.22],
     5500, 0.28, 0.80, 6500, 150),
    ("glass_break", [-37, 9, -7, 5, -3, 2.5, -1.5, 1.2, -0.8, 0.55, -0.4, 0.25, -0.15],
     4500, 0.22, 0.70, 5500, 300),

    # --- SIREN: sustained, mid-high freq, oscillating, moderate energy ---
    ("siren", [-25, 6, 4, -2, 3, -1, 2, -0.5, 1, -0.3, 0.5, -0.2, 0.1],
     1200, 0.06, 0.45, 800, 5000),
    ("siren", [-23, 7, 5, -3, 4, -1.5, 2.5, -0.8, 1.2, -0.4, 0.6, -0.25, 0.12],
     1500, 0.07, 0.50, 900, 8000),
    ("siren", [-27, 5, 3, -1.5, 2, -0.8, 1.5, -0.4, 0.8, -0.2, 0.4, -0.15, 0.08],
     900, 0.05, 0.40, 700, 3000),

    # --- ANIMAL: variable, typically 300-4000 Hz, short bursts ---
    ("animal", [-28, 7, 3, -1, 2, -0.8, 0.5, -0.3, 0.2, -0.1, 0.08, -0.04, 0.02],
     1800, 0.10, 0.30, 2000, 500),
    ("animal", [-26, 8, 4, -2, 3, -1.2, 0.7, -0.4, 0.25, -0.12, 0.09, -0.05, 0.025],
     2500, 0.12, 0.35, 2500, 300),
    ("animal", [-30, 6, 2, -0.5, 1.5, -0.6, 0.3, -0.2, 0.15, -0.08, 0.06, -0.03, 0.015],
     1200, 0.08, 0.25, 1500, 800),

    # --- EXPLOSION: massive energy, very broad spectrum, longer than gunshot ---
    ("explosion", [-45, 15, -8, 5, -4, 2.5, -2, 1, -0.8, 0.5, -0.3, 0.2, -0.1],
     2000, 0.10, 0.98, 5000, 500),
    ("explosion", [-48, 16, -9, 6, -5, 3, -2.5, 1.2, -1, 0.6, -0.4, 0.25, -0.12],
     1800, 0.08, 0.99, 5500, 800),

    # --- MACHINERY: sustained low-mid, repetitive spectral pattern ---
    ("machinery", [-32, 4, -2, 1.5, -1, 0.8, -0.5, 0.3, -0.2, 0.12, -0.08, 0.05, -0.03],
     600, 0.04, 0.30, 800, 10000),
    ("machinery", [-30, 5, -3, 2, -1.2, 1, -0.6, 0.35, -0.22, 0.14, -0.09, 0.06, -0.035],
     450, 0.035, 0.35, 700, 15000),

    # --- MUSIC: harmonic structure, moderate energy, sustained ---
    ("music", [-15, 10, 8, -4, 5, -2, 3, -1, 2, -0.5, 1, -0.3, 0.5],
     2000, 0.06, 0.25, 3000, 10000),
    ("music", [-12, 11, 9, -5, 6, -2.5, 3.5, -1.2, 2.2, -0.6, 1.2, -0.35, 0.55],
     1500, 0.05, 0.30, 2500, 15000),

    # --- FOOTSTEPS: low-mid, impulsive, rhythmic, low energy ---
    ("footsteps", [-35, 3, -1, 0.5, -0.3, 0.2, -0.1, 0.05, -0.03, 0.02, -0.01, 0.005, -0.002],
     400, 0.05, 0.15, 500, 300),
    ("footsteps", [-37, 2, -0.8, 0.4, -0.2, 0.15, -0.08, 0.04, -0.02, 0.015, -0.008, 0.004, -0.002],
     350, 0.04, 0.12, 450, 250),

    # --- ALARM: high-pitched, sustained, periodic ---
    ("alarm", [-20, 8, 5, -3, 4, -2, 3, -1.5, 2, -1, 1.5, -0.8, 0.5],
     2800, 0.08, 0.55, 1000, 5000),
    ("alarm", [-18, 9, 6, -4, 5, -2.5, 3.5, -1.8, 2.2, -1.2, 1.7, -0.9, 0.55],
     3200, 0.09, 0.60, 1200, 8000),
]


def _euclidean_distance(a: list[float], b: list[float]) -> float:
    """Compute euclidean distance between two feature vectors."""
    total = 0.0
    for x, y in zip(a, b):
        total += (x - y) ** 2
    return math.sqrt(total)


def _mel_filterbank(n_fft: int, sample_rate: int, n_mels: int = 26) -> "np.ndarray":
    """Build a mel-scale triangular filterbank matrix.

    Returns an (n_mels, n_fft//2+1) numpy array of filter weights.
    """
    def hz_to_mel(hz: float) -> float:
        return 2595.0 * math.log10(1.0 + hz / 700.0)

    def mel_to_hz(mel: float) -> float:
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    low_mel = hz_to_mel(0)
    high_mel = hz_to_mel(sample_rate / 2)
    mel_points = np.linspace(low_mel, high_mel, n_mels + 2)
    hz_points = np.array([mel_to_hz(m) for m in mel_points])
    bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

    n_bins = n_fft // 2 + 1
    filters = np.zeros((n_mels, n_bins))

    for i in range(n_mels):
        left = bin_points[i]
        center = bin_points[i + 1]
        right = bin_points[i + 2]
        for j in range(left, center):
            if center > left:
                filters[i, j] = (j - left) / (center - left)
        for j in range(center, right):
            if right > center:
                filters[i, j] = (right - j) / (right - center)

    return filters


def extract_mfcc_scipy(
    samples: list[float],
    sample_rate: int,
    n_mfcc: int = 13,
    n_fft: int = 2048,
    hop_length: int = 512,
    n_mels: int = 26,
) -> Optional[list[float]]:
    """Extract real MFCC coefficients using scipy/numpy.

    Implements the standard MFCC pipeline:
    1. STFT with Hann window
    2. Mel filterbank energy
    3. Log compression
    4. DCT to get cepstral coefficients
    5. Average across frames to get 13 summary coefficients

    Returns None if scipy/numpy are not available.
    """
    if not _HAS_SCIPY or not _HAS_NUMPY:
        return None

    arr = np.array(samples, dtype=np.float64)
    n = len(arr)
    if n < n_fft:
        return None

    # Build mel filterbank
    mel_fb = _mel_filterbank(n_fft, sample_rate, n_mels)

    # Hann window
    window = np.hanning(n_fft)

    # STFT frames
    n_frames = max(1, (n - n_fft) // hop_length + 1)
    mfcc_frames = []

    for i in range(n_frames):
        start = i * hop_length
        frame = arr[start:start + n_fft]
        if len(frame) < n_fft:
            frame = np.pad(frame, (0, n_fft - len(frame)))
        windowed = frame * window

        # Power spectrum
        spectrum = np.abs(np.fft.rfft(windowed)) ** 2

        # Mel energies
        mel_energies = mel_fb @ spectrum
        mel_energies = np.maximum(mel_energies, 1e-10)
        log_mel = np.log(mel_energies)

        # DCT to get cepstral coefficients
        cepstral = dct(log_mel, type=2, norm="ortho")
        mfcc_frames.append(cepstral[:n_mfcc])

    if not mfcc_frames:
        return None

    # Average MFCCs across all frames
    mfcc_mean = np.mean(mfcc_frames, axis=0)
    return mfcc_mean.tolist()


def _extract_wav_features(wav_path: str) -> Optional[tuple[str, list[float], float, float, float, float, int]]:
    """Extract features from a WAV file and return in TRAINING_DATA format.

    Returns a tuple (label, mfcc_13, centroid, zcr, rms, bandwidth, duration_ms)
    or None if extraction fails. Label is empty string (caller must fill).

    Security: validates file extension, resolves symlinks, checks file size,
    and relies on Python's wave module for format validation.

    No numpy/scipy/librosa required -- pure stdlib.
    """
    import os
    import struct
    import wave as wave_mod

    # Security: validate file extension
    if not wav_path.lower().endswith(".wav"):
        logger.warning("Rejected non-WAV file: {}", wav_path)
        return None

    # Security: resolve symlinks and validate the path exists as a regular file
    try:
        real_path = os.path.realpath(wav_path)
        if not os.path.isfile(real_path):
            logger.warning("WAV path is not a regular file: {}", wav_path)
            return None
    except (OSError, ValueError):
        return None

    # Security: reject excessively large files (>100 MB) to prevent DoS
    MAX_WAV_SIZE = 100 * 1024 * 1024
    try:
        file_size = os.path.getsize(real_path)
        if file_size > MAX_WAV_SIZE:
            logger.warning("WAV file too large ({} bytes): {}", file_size, wav_path)
            return None
        if file_size < 44:  # Minimum WAV header size
            logger.warning("WAV file too small ({} bytes): {}", file_size, wav_path)
            return None
    except OSError:
        return None

    try:
        with wave_mod.open(real_path, "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            # Security: reject unreasonable frame counts that could cause memory exhaustion
            max_frames = MAX_WAV_SIZE // (n_channels * max(sample_width, 1))
            if n_frames > max_frames:
                logger.warning("WAV file has too many frames ({}): {}", n_frames, wav_path)
                return None
            raw_data = wf.readframes(n_frames)
    except Exception:
        return None

    duration_ms = int(n_frames / framerate * 1000) if framerate > 0 else 0

    # Convert to float samples
    try:
        if sample_width == 2:
            fmt = f"<{n_frames * n_channels}h"
            samples_int = struct.unpack(fmt, raw_data)
        elif sample_width == 4:
            fmt = f"<{n_frames * n_channels}i"
            samples_int = struct.unpack(fmt, raw_data)
        else:
            samples_int = [b - 128 for b in raw_data]
    except Exception:
        return None

    # Mix to mono
    if n_channels > 1:
        mono = []
        for i in range(0, len(samples_int), n_channels):
            mono.append(sum(samples_int[i:i + n_channels]) / n_channels)
        samples_int = mono

    max_val = 2 ** (sample_width * 8 - 1)
    samples = [s / max_val for s in samples_int]
    n = len(samples)
    if n < 256:
        return None

    # RMS energy
    rms = math.sqrt(sum(s * s for s in samples) / n)

    # Zero crossing rate
    crossings = sum(1 for i in range(1, n) if (samples[i] >= 0) != (samples[i - 1] >= 0))
    zcr = crossings / n if n > 1 else 0.0

    # Approximate spectral centroid from ZCR-based frequency
    if crossings > 0:
        avg_period = n / (crossings / 2)
        dominant_freq = framerate / avg_period if avg_period > 0 else 0.0
    else:
        dominant_freq = 0.0
    centroid = max(0.0, min(dominant_freq, framerate / 2))
    bandwidth = centroid * 0.5

    # Try real MFCC extraction via scipy first, fall back to DCT approximation
    mfcc = extract_mfcc_scipy(samples, framerate)
    if mfcc is None:
        # Fallback: MFCC-like coefficients via windowed energy + DCT
        frame_size = min(1024, n // 4)
        hop = frame_size // 2
        n_frames_local = max(1, (n - frame_size) // hop + 1)
        frame_energies = []
        for i in range(n_frames_local):
            start = i * hop
            end = min(start + frame_size, n)
            frame = samples[start:end]
            energy = sum(s * s for s in frame) / len(frame)
            frame_energies.append(math.log(energy + 1e-10))

        m = len(frame_energies)
        mfcc = []
        for k in range(13):
            coeff = 0.0
            for j in range(m):
                coeff += frame_energies[j] * math.cos(math.pi * k * (2 * j + 1) / (2 * m))
            mfcc.append(coeff / m)

    return ("", mfcc, centroid, zcr, rms, bandwidth, duration_ms)


def train_from_wav_directory(
    wav_dir: str,
    category_map: Optional[dict[str, str]] = None,
    metadata_csv: Optional[str] = None,
    max_per_category: int = 10,
) -> list[tuple[str, list[float], float, float, float, float, int]]:
    """Extract training data from a directory of WAV files.

    Supports two modes:
    1. ESC-50 style: metadata CSV with filename, category columns
    2. Subdirectory style: wav_dir/category_name/file.wav

    Args:
        wav_dir: Path to directory containing WAV files.
        category_map: Mapping from dataset category names to Tritium classes.
        metadata_csv: Path to metadata CSV (ESC-50 format).
        max_per_category: Maximum samples per category to extract.

    Returns:
        List of training tuples compatible with MFCCClassifier.train().
    """
    import csv
    from pathlib import Path

    training_data: list[tuple[str, list[float], float, float, float, float, int]] = []
    wav_path = Path(wav_dir).resolve()

    # Security: ensure the directory exists and is actually a directory
    if not wav_path.is_dir():
        logger.warning("WAV training directory does not exist: {}", wav_dir)
        return training_data

    if metadata_csv:
        # ESC-50 style: CSV with filename, category
        csv_path = Path(metadata_csv)
        if not csv_path.exists():
            logger.warning("Metadata CSV not found: {}", metadata_csv)
            return training_data

        category_counts: dict[str, int] = {}
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cat = row.get("category", "")
                label = cat
                if category_map:
                    label = category_map.get(cat, "")
                    if not label or label == "unknown":
                        continue

                if category_counts.get(label, 0) >= max_per_category:
                    continue

                filename = row.get("filename", "")
                # Security: reject path traversal in CSV filenames
                if ".." in filename or filename.startswith("/"):
                    logger.warning("Rejected suspicious filename in CSV: {}", filename)
                    continue
                fpath = wav_path / filename
                # Security: ensure resolved path stays under wav_path
                try:
                    fpath.resolve().relative_to(wav_path)
                except ValueError:
                    logger.warning("Path traversal attempt blocked: {}", filename)
                    continue
                if not fpath.exists():
                    continue

                result = _extract_wav_features(str(fpath))
                if result is None:
                    continue

                _, mfcc, centroid, zcr, rms, bw, dur = result
                training_data.append((label, mfcc, centroid, zcr, rms, bw, dur))
                category_counts[label] = category_counts.get(label, 0) + 1

    else:
        # Subdirectory style
        if not wav_path.is_dir():
            return training_data
        for subdir in sorted(wav_path.iterdir()):
            if not subdir.is_dir():
                continue
            cat = subdir.name
            label = cat
            if category_map:
                label = category_map.get(cat, "")
                if not label or label == "unknown":
                    continue

            count = 0
            for wav_file in sorted(subdir.glob("*.wav")):
                if count >= max_per_category:
                    break
                result = _extract_wav_features(str(wav_file))
                if result is None:
                    continue
                _, mfcc, centroid, zcr, rms, bw, dur = result
                training_data.append((label, mfcc, centroid, zcr, rms, bw, dur))
                count += 1

    logger.info(
        "Extracted {} training samples from WAV files ({} classes)",
        len(training_data),
        len(set(t[0] for t in training_data)),
    )
    return training_data


# Default ESC-50 category mapping for train_from_wav_directory()
ESC50_CATEGORY_MAP: dict[str, str] = {
    "dog": "animal", "cat": "animal", "rooster": "animal", "pig": "animal",
    "cow": "animal", "frog": "animal", "hen": "animal", "crow": "animal",
    "sheep": "animal", "insects": "animal", "crickets": "animal",
    "chirping_birds": "animal",
    "siren": "siren",
    "car_horn": "vehicle", "engine": "vehicle", "train": "vehicle",
    "helicopter": "vehicle", "airplane": "vehicle",
    "fireworks": "explosion", "thunderstorm": "explosion",
    "glass_breaking": "glass_break",
    "chainsaw": "machinery", "vacuum_cleaner": "machinery",
    "washing_machine": "machinery", "hand_saw": "machinery",
    "clock_alarm": "alarm", "church_bells": "alarm",
    "laughing": "voice", "crying_baby": "voice", "coughing": "voice",
    "sneezing": "voice", "breathing": "voice", "snoring": "voice",
    "footsteps": "footsteps",
}


class MFCCClassifier:
    """K-Nearest Neighbors classifier on MFCC + spectral features.

    Two backends:
    - sklearn KNeighborsClassifier (k=5) with StandardScaler — used when
      sklearn is available. Provides proper distance-weighted voting.
    - Pure-Python KNN with z-score normalization — fallback when sklearn
      is not installed.

    Feature vector = 13 MFCCs + spectral_centroid + zcr + rms_energy +
                     spectral_bandwidth + duration_ms (normalized).

    Can be retrained on real WAV files (e.g. ESC-50) for improved accuracy
    via train_from_wavs() or by passing extracted data to train().
    """

    MODEL_VERSION = "mfcc_knn_v3"

    def __init__(self, k: int = 5) -> None:
        self.k = k
        self._training_vectors: list[tuple[str, list[float]]] = []
        self._trained = False
        self._feature_means: list[float] = []
        self._feature_stds: list[float] = []
        self._training_sample_count: int = 0
        self._training_class_count: int = 0
        self._use_sklearn: bool = _HAS_SKLEARN and _HAS_NUMPY
        self._sklearn_knn: Optional[object] = None  # SklearnKNN instance
        self._sklearn_scaler: Optional[object] = None  # StandardScaler instance
        self._label_list: list[str] = []  # ordered labels for sklearn

    @property
    def uses_sklearn(self) -> bool:
        """Whether sklearn backend is active."""
        return self._use_sklearn and self._sklearn_knn is not None

    @property
    def uses_scipy_mfcc(self) -> bool:
        """Whether scipy-based MFCC extraction is available."""
        return _HAS_SCIPY and _HAS_NUMPY

    def train(self, data: Optional[list] = None) -> None:
        """Train on built-in or custom dataset."""
        dataset = data or TRAINING_DATA
        if not dataset:
            return

        # Build raw feature vectors
        raw_vectors: list[tuple[str, list[float]]] = []
        for entry in dataset:
            label, mfcc, centroid, zcr, rms, bw, dur = entry
            fv = list(mfcc) + [centroid, zcr, rms, bw, float(dur)]
            raw_vectors.append((label, fv))

        n_features = len(raw_vectors[0][1])
        n_samples = len(raw_vectors)

        # Try sklearn backend first
        if self._use_sklearn:
            try:
                X = np.array([fv for _, fv in raw_vectors])
                y = [label for label, _ in raw_vectors]

                scaler = StandardScaler()
                X_scaled = scaler.fit_transform(X)

                knn = SklearnKNN(
                    n_neighbors=min(self.k, n_samples),
                    weights="distance",
                    metric="euclidean",
                )
                knn.fit(X_scaled, y)

                self._sklearn_knn = knn
                self._sklearn_scaler = scaler
                self._label_list = y

                # Also store pure-python stats for export compatibility
                self._feature_means = scaler.mean_.tolist()
                self._feature_stds = scaler.scale_.tolist()
                self._training_vectors = []
                for label, fv in raw_vectors:
                    norm_fv = [(v - m) / s for v, m, s in zip(fv, self._feature_means, self._feature_stds)]
                    self._training_vectors.append((label, norm_fv))

                self._trained = True
                self._training_sample_count = n_samples
                self._training_class_count = len(set(y))
                logger.info(
                    "MFCC classifier trained (sklearn KNN k={}) on {} samples, {} classes",
                    self.k, n_samples, self._training_class_count,
                )
                return
            except Exception as exc:
                logger.warning("sklearn training failed, falling back to pure-python: {}", exc)
                self._sklearn_knn = None
                self._sklearn_scaler = None

        # Pure-Python fallback: z-score normalization + manual KNN
        means = [0.0] * n_features
        for _, fv in raw_vectors:
            for i, v in enumerate(fv):
                means[i] += v
        means = [m / n_samples for m in means]

        stds = [0.0] * n_features
        for _, fv in raw_vectors:
            for i, v in enumerate(fv):
                stds[i] += (v - means[i]) ** 2
        stds = [math.sqrt(s / n_samples) if s > 0 else 1.0 for s in stds]
        stds = [s if s > 1e-10 else 1.0 for s in stds]

        self._feature_means = means
        self._feature_stds = stds

        self._training_vectors = []
        for label, fv in raw_vectors:
            norm_fv = [(v - m) / s for v, m, s in zip(fv, means, stds)]
            self._training_vectors.append((label, norm_fv))

        self._trained = True
        self._training_sample_count = n_samples
        self._training_class_count = len(set(label for label, _ in raw_vectors))
        logger.info(
            "MFCC classifier trained (pure-python KNN k={}) on {} samples, {} classes",
            self.k, n_samples, self._training_class_count,
        )

    def train_from_wavs(
        self,
        wav_dir: str,
        category_map: Optional[dict[str, str]] = None,
        metadata_csv: Optional[str] = None,
        max_per_category: int = 10,
        augment_with_builtin: bool = True,
    ) -> int:
        """Train classifier using real WAV files for dramatically better accuracy.

        Extracts MFCC features from WAV files and trains the KNN.
        Optionally augments with built-in synthetic profiles.

        Args:
            wav_dir: Path to directory containing WAV files.
            category_map: Mapping from dataset category names to Tritium classes.
            metadata_csv: Path to metadata CSV (ESC-50 format).
            max_per_category: Maximum samples per category.
            augment_with_builtin: Whether to also include built-in training data.

        Returns:
            Number of WAV-derived training samples used.
        """
        wav_data = train_from_wav_directory(
            wav_dir, category_map=category_map,
            metadata_csv=metadata_csv,
            max_per_category=max_per_category,
        )

        if not wav_data:
            logger.warning("No WAV training data extracted, falling back to built-in")
            self.train()
            return 0

        combined = list(wav_data)
        if augment_with_builtin:
            combined.extend(TRAINING_DATA)

        self.train(combined)
        return len(wav_data)

    def classify(self, features: AudioFeatures) -> tuple[str, float, list[dict]]:
        """Classify features using KNN.

        Uses sklearn backend if available, otherwise pure-python KNN.

        Returns:
            (best_class, confidence, top_predictions)
        """
        if not self._trained:
            self.train()

        # Build feature vector
        mfcc = features.mfcc if features.mfcc else [0.0] * 13
        mfcc = (mfcc + [0.0] * 13)[:13]
        fv = mfcc + [
            features.spectral_centroid,
            features.zero_crossing_rate,
            features.rms_energy,
            features.spectral_bandwidth,
            float(features.duration_ms),
        ]

        # sklearn backend
        if self._sklearn_knn is not None and self._sklearn_scaler is not None:
            return self._classify_sklearn(fv)

        # Pure-python fallback
        return self._classify_pure_python(fv)

    def _classify_sklearn(self, fv: list[float]) -> tuple[str, float, list[dict]]:
        """Classify using sklearn KNeighborsClassifier."""
        X = np.array([fv])
        X_scaled = self._sklearn_scaler.transform(X)  # type: ignore[union-attr]

        # Get probability estimates
        proba = self._sklearn_knn.predict_proba(X_scaled)[0]  # type: ignore[union-attr]
        classes = self._sklearn_knn.classes_  # type: ignore[union-attr]

        # Sort by probability
        class_proba = list(zip(classes, proba))
        class_proba.sort(key=lambda x: x[1], reverse=True)

        best_class = class_proba[0][0]
        confidence = round(float(class_proba[0][1]), 3)

        predictions = [
            {"class_name": str(cls), "confidence": round(float(p), 3)}
            for cls, p in class_proba[:5]
            if p > 0.001
        ]

        return best_class, confidence, predictions

    def _classify_pure_python(self, fv: list[float]) -> tuple[str, float, list[dict]]:
        """Classify using pure-python KNN (fallback)."""
        norm_fv = [
            (v - m) / s
            for v, m, s in zip(fv, self._feature_means, self._feature_stds)
        ]

        distances: list[tuple[float, str]] = []
        for label, train_fv in self._training_vectors:
            d = _euclidean_distance(norm_fv, train_fv)
            distances.append((d, label))

        distances.sort(key=lambda x: x[0])
        k_nearest = distances[: self.k]

        votes: dict[str, float] = {}
        for dist, label in k_nearest:
            weight = 1.0 / (dist + 1e-6)
            votes[label] = votes.get(label, 0.0) + weight

        total_weight = sum(votes.values())
        if total_weight <= 0:
            return "unknown", 0.0, []

        sorted_votes = sorted(votes.items(), key=lambda x: x[1], reverse=True)
        best_class = sorted_votes[0][0]
        confidence = sorted_votes[0][1] / total_weight

        predictions = [
            {"class_name": cls, "confidence": round(w / total_weight, 3)}
            for cls, w in sorted_votes[:5]
        ]

        return best_class, round(confidence, 3), predictions

    @property
    def is_trained(self) -> bool:
        return self._trained

    def to_training_set(self) -> AcousticTrainingSet:
        """Export the current training data as an AcousticTrainingSet model.

        Converts the raw tuple training data into structured
        AcousticTrainingExample instances for persistence or analysis.
        """
        ts = AcousticTrainingSet(name="acoustic_classifier")
        for label, fv in self._training_vectors:
            # Un-normalize the feature vector to recover original values
            orig_fv = [
                v * s + m
                for v, m, s in zip(fv, self._feature_means, self._feature_stds)
            ]
            ts.add(AcousticTrainingExample(
                audio_features=orig_fv,
                label=label,
                source=TrainingSource.SYNTHETIC,
            ))
        return ts

    @classmethod
    def from_training_set(cls, training_set: AcousticTrainingSet, k: int = 5) -> "MFCCClassifier":
        """Create and train an MFCCClassifier from an AcousticTrainingSet.

        Args:
            training_set: Structured training data from tritium-lib.
            k: Number of nearest neighbors for KNN.

        Returns:
            A trained MFCCClassifier instance.
        """
        classifier = cls(k=k)
        tuples = training_set.to_training_data()
        if tuples:
            classifier.train(tuples)
        return classifier


class AcousticClassifier:
    """Dual-mode acoustic event classifier: rule-based + ML (MFCC KNN).

    Uses audio features (energy, frequency distribution, duration) to classify
    sounds. Falls back to rule-based when MFCC features are unavailable.
    """

    # Classification thresholds (tuned empirically)
    GUNSHOT_ENERGY_THRESHOLD = 0.8
    GUNSHOT_DURATION_MAX_MS = 200
    VOICE_CENTROID_MIN_HZ = 85
    VOICE_CENTROID_MAX_HZ = 3000
    VEHICLE_CENTROID_MAX_HZ = 500
    SIREN_CENTROID_MIN_HZ = 600
    SIREN_CENTROID_MAX_HZ = 2000

    def __init__(self, enable_ml: bool = True) -> None:
        self._event_history: list[AcousticEvent] = []
        self._max_history = 1000
        self._ml_classifier: Optional[MFCCClassifier] = None

        if enable_ml:
            try:
                self._ml_classifier = MFCCClassifier(k=5)
                self._ml_classifier.train()
            except Exception as exc:
                logger.warning("ML classifier init failed, rule-based only: {}", exc)
                self._ml_classifier = None

    @property
    def ml_available(self) -> bool:
        """Whether the ML classifier is trained and available."""
        return self._ml_classifier is not None and self._ml_classifier.is_trained

    def classify(self, features: AudioFeatures) -> AcousticEvent:
        """Classify an audio segment based on its features.

        If MFCC features are available and the ML classifier is trained,
        uses KNN classification. Otherwise falls back to rule-based.
        """
        # Try ML classification first if MFCCs are available
        if self._ml_classifier and features.mfcc:
            try:
                return self._classify_ml(features)
            except Exception as exc:
                logger.debug("ML classification failed, falling back: {}", exc)

        return self._classify_rules(features)

    def _classify_ml(self, features: AudioFeatures) -> AcousticEvent:
        """Classify using the MFCC KNN model."""
        best_class, confidence, predictions = self._ml_classifier.classify(features)

        try:
            event_type = AcousticEventType(best_class)
        except ValueError:
            event_type = AcousticEventType.UNKNOWN

        event = AcousticEvent(
            event_type=event_type,
            confidence=confidence,
            duration_ms=features.duration_ms,
            peak_frequency_hz=features.spectral_centroid,
            peak_amplitude_db=features.peak_amplitude,
            model_version=MFCCClassifier.MODEL_VERSION,
        )
        self._record(event)
        return event

    def _classify_rules(self, features: AudioFeatures) -> AcousticEvent:
        """Classify using rule-based thresholds (original logic)."""
        # Gunshot: very high energy, very short duration
        if (features.peak_amplitude > self.GUNSHOT_ENERGY_THRESHOLD
                and features.duration_ms < self.GUNSHOT_DURATION_MAX_MS):
            event = AcousticEvent(
                event_type=AcousticEventType.GUNSHOT,
                confidence=min(0.95, features.peak_amplitude),
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Siren: sustained, mid-high frequency
        if (self.SIREN_CENTROID_MIN_HZ < features.spectral_centroid < self.SIREN_CENTROID_MAX_HZ
                and features.duration_ms > 1000
                and features.rms_energy > 0.3):
            event = AcousticEvent(
                event_type=AcousticEventType.SIREN,
                confidence=0.7,
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Vehicle: low frequency, sustained (check before voice — overlapping range)
        if (features.spectral_centroid < self.VEHICLE_CENTROID_MAX_HZ
                and features.duration_ms > 500
                and features.rms_energy > 0.2):
            event = AcousticEvent(
                event_type=AcousticEventType.VEHICLE,
                confidence=0.5,
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Voice: mid-range frequency, moderate energy
        if (self.VOICE_CENTROID_MIN_HZ < features.spectral_centroid < self.VOICE_CENTROID_MAX_HZ
                and features.rms_energy > 0.1
                and features.duration_ms > 200):
            event = AcousticEvent(
                event_type=AcousticEventType.VOICE,
                confidence=0.6,
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Glass break: high energy, short, high frequency
        if (features.spectral_centroid > 2000
                and features.peak_amplitude > 0.6
                and features.duration_ms < 500):
            event = AcousticEvent(
                event_type=AcousticEventType.GLASS_BREAK,
                confidence=0.55,
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Unknown
        event = AcousticEvent(
            event_type=AcousticEventType.UNKNOWN,
            confidence=0.3,
            duration_ms=features.duration_ms,
            peak_frequency_hz=features.spectral_centroid,
            peak_amplitude_db=features.peak_amplitude,
        )
        self._record(event)
        return event

    def get_recent_events(self, count: int = 50) -> list[AcousticEvent]:
        """Get the most recent classified events."""
        return self._event_history[-count:]

    def get_event_counts(self) -> dict[str, int]:
        """Get count of each event type in history."""
        counts: dict[str, int] = {}
        for event in self._event_history:
            t = event.event_type.value
            counts[t] = counts.get(t, 0) + 1
        return counts

    def _record(self, event: AcousticEvent) -> None:
        """Record event in history, trimming if needed."""
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
