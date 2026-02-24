"""Synthetic audio generation for testing the audio pipeline."""

import numpy as np


def generate_ambient(duration: float = 5.0, sample_rate: int = 16000) -> np.ndarray:
    """Generate ambient outdoor sounds (pink noise + bird chirps)."""
    n_samples = int(duration * sample_rate)
    # Pink noise via filtering white noise
    white = np.random.randn(n_samples).astype(np.float32)
    # Simple 1/f approximation: cumulative sum with decay
    pink = np.zeros(n_samples, dtype=np.float32)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004709510]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    # Simple IIR filter for pink noise
    for i in range(len(b), n_samples):
        pink[i] = sum(b[j] * white[i-j] for j in range(len(b))) - sum(a[j] * pink[i-j] for j in range(1, len(a)))

    pink *= 0.05  # Keep quiet

    # Add random bird chirps (short sine bursts at high frequency)
    n_chirps = int(duration * 0.5)  # ~0.5 chirps/sec
    for _ in range(n_chirps):
        start = np.random.randint(0, max(1, n_samples - sample_rate // 4))
        freq = np.random.uniform(2000, 5000)
        chirp_len = int(sample_rate * np.random.uniform(0.05, 0.15))
        t = np.arange(chirp_len) / sample_rate
        envelope = np.sin(np.pi * t / (chirp_len / sample_rate))
        chirp = 0.03 * envelope * np.sin(2 * np.pi * freq * t)
        end = min(start + chirp_len, n_samples)
        pink[start:end] += chirp[:end-start].astype(np.float32)

    return np.clip(pink, -1.0, 1.0)


def generate_speech_tone(text: str = "test", duration: float = 1.0, sample_rate: int = 16000) -> np.ndarray:
    """Generate syllable-like tone bursts (not real speech)."""
    n_samples = int(duration * sample_rate)
    output = np.zeros(n_samples, dtype=np.float32)

    # Generate tone bursts for each "syllable"
    n_syllables = max(1, len(text.split()))
    syllable_dur = duration / n_syllables

    for i in range(n_syllables):
        start = int(i * syllable_dur * sample_rate)
        end = min(int((i + 0.7) * syllable_dur * sample_rate), n_samples)
        if start >= end:
            continue
        t = np.arange(end - start) / sample_rate
        freq = 200 + i * 50  # Varying pitch
        envelope = np.sin(np.pi * t / (t[-1] if len(t) > 0 else 1))
        output[start:end] = 0.3 * envelope * np.sin(2 * np.pi * freq * t)

    return np.clip(output, -1.0, 1.0)


def generate_gunshot(sample_rate: int = 16000) -> np.ndarray:
    """Generate a gunshot-like impulse with decay."""
    duration = 0.5
    n_samples = int(duration * sample_rate)
    output = np.zeros(n_samples, dtype=np.float32)

    # Sharp attack
    attack_samples = int(0.002 * sample_rate)
    output[:attack_samples] = np.linspace(0, 0.9, attack_samples)

    # Exponential decay with noise
    decay_t = np.arange(n_samples - attack_samples) / sample_rate
    decay = 0.9 * np.exp(-decay_t * 15)
    noise = np.random.randn(len(decay)).astype(np.float32) * 0.3
    output[attack_samples:] = decay * (1 + noise * np.exp(-decay_t * 5))

    return np.clip(output, -1.0, 1.0)
