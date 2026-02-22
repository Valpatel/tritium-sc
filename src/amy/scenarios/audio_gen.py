"""AudioGenerator — synthesizes speech and ambient audio for scenarios."""

from __future__ import annotations

import hashlib
import os
import tempfile

import numpy as np


class AudioGenerator:
    """Generates synthetic audio for scenario testing.

    All output: 16kHz float32 mono (matches SensorNode contract).
    """

    SAMPLE_RATE = 16000

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._cache_dir = os.path.join(tempfile.gettempdir(), "amy_audio_cache")
        os.makedirs(self._cache_dir, exist_ok=True)

    def generate_speech(self, text: str) -> np.ndarray:
        """Generate speech audio from text.

        Tries:
        1. gTTS (Google TTS) -- best quality, needs internet
        2. Cached WAV from previous gTTS call
        3. Fallback: procedural "speech-like" tones

        Returns 16kHz float32 mono.
        """
        # Check cache first
        cache_key = hashlib.md5(text.encode()).hexdigest()
        cache_path = os.path.join(self._cache_dir, f"{cache_key}.wav")

        if os.path.exists(cache_path):
            return self._load_wav(cache_path)

        # Try gTTS
        try:
            return self._gtts_speech(text, cache_path)
        except Exception:
            pass

        # Fallback: procedural speech
        return self._procedural_speech(text)

    def _gtts_speech(self, text: str, cache_path: str) -> np.ndarray:
        """Use gTTS for high-quality speech synthesis."""
        from gtts import gTTS
        import io

        tts = gTTS(text=text, lang='en', slow=False)
        mp3_buf = io.BytesIO()
        tts.write_to_fp(mp3_buf)
        mp3_buf.seek(0)

        # Convert MP3 to WAV at 16kHz using pydub or raw decode
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_mp3(mp3_buf)
            audio = audio.set_frame_rate(self.sample_rate).set_channels(1)
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
            samples /= 32768.0  # Normalize int16 to float32

            # Cache for reuse
            import wave
            with wave.open(cache_path, 'w') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes((samples * 32767).astype(np.int16).tobytes())

            return samples
        except ImportError:
            raise  # Let outer handler catch and fall to procedural

    def _load_wav(self, path: str) -> np.ndarray:
        """Load a cached WAV file as float32."""
        import wave
        with wave.open(path, 'r') as wf:
            raw = wf.readframes(wf.getnframes())
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            samples /= 32768.0
        return samples

    def _procedural_speech(self, text: str) -> np.ndarray:
        """Generate procedural speech-like tones as fallback.

        Creates varying-frequency tone bursts that simulate speech rhythm.
        Not intelligible, but creates audio activity that Listener can detect.
        """
        # Duration: ~0.1s per character, capped at 5s
        duration = min(len(text) * 0.08, 5.0)
        n_samples = int(duration * self.sample_rate)
        t = np.linspace(0, duration, n_samples, dtype=np.float32)

        # Base frequency with variation (simulates speech formants)
        np.random.seed(hash(text) % (2**31))
        base_freq = 180 + np.random.randint(0, 80)

        # Create syllable-like bursts
        signal = np.zeros(n_samples, dtype=np.float32)
        syllable_len = int(0.12 * self.sample_rate)
        gap_len = int(0.04 * self.sample_rate)

        pos = 0
        syllable_idx = 0
        while pos + syllable_len < n_samples:
            freq = base_freq + 40 * np.sin(syllable_idx * 0.7)
            syllable_t = np.linspace(0, syllable_len / self.sample_rate,
                                      syllable_len, dtype=np.float32)
            # Tone with harmonics
            syllable = (
                0.5 * np.sin(2 * np.pi * freq * syllable_t) +
                0.3 * np.sin(2 * np.pi * freq * 2 * syllable_t) +
                0.1 * np.sin(2 * np.pi * freq * 3 * syllable_t)
            )
            # Envelope (fade in/out)
            env = np.ones(syllable_len, dtype=np.float32)
            fade = min(int(0.01 * self.sample_rate), syllable_len // 4)
            env[:fade] = np.linspace(0, 1, fade)
            env[-fade:] = np.linspace(1, 0, fade)
            syllable *= env

            end = min(pos + syllable_len, n_samples)
            signal[pos:end] = syllable[:end - pos]
            pos += syllable_len + gap_len
            syllable_idx += 1

        # Normalize to reasonable level
        signal *= 0.4
        return signal

    def generate_ambient(self, ambient_type: str, duration: float) -> np.ndarray:
        """Generate ambient background audio.

        Types:
        - "silence": near-zero gaussian noise
        - "office": 60Hz hum + random clicks
        - "footsteps": periodic impulse sounds
        """
        n_samples = int(duration * self.sample_rate)

        if ambient_type == "office":
            return self._ambient_office(n_samples)
        elif ambient_type == "footsteps":
            return self._ambient_footsteps(n_samples)
        else:
            # "silence" -- very quiet noise
            return np.random.normal(0, 0.001, n_samples).astype(np.float32)

    def _ambient_office(self, n_samples: int) -> np.ndarray:
        """Office ambient: 60Hz hum + random clicks."""
        t = np.linspace(0, n_samples / self.sample_rate, n_samples, dtype=np.float32)
        # 60Hz hum (electrical)
        hum = 0.02 * np.sin(2 * np.pi * 60 * t)
        # Random quiet clicks
        clicks = np.zeros(n_samples, dtype=np.float32)
        n_clicks = max(1, n_samples // (self.sample_rate * 2))
        for _ in range(n_clicks):
            pos = np.random.randint(0, n_samples)
            click_len = min(int(0.005 * self.sample_rate), n_samples - pos)
            clicks[pos:pos + click_len] = np.random.normal(0, 0.05, click_len)
        return (hum + clicks).astype(np.float32)

    def _ambient_footsteps(self, n_samples: int) -> np.ndarray:
        """Footstep sounds: periodic low-frequency impulses."""
        signal = np.zeros(n_samples, dtype=np.float32)
        # ~2 steps per second
        step_interval = int(self.sample_rate * 0.5)
        step_len = int(0.05 * self.sample_rate)

        pos = int(0.2 * self.sample_rate)  # Start after 200ms
        while pos + step_len < n_samples:
            t = np.linspace(0, step_len / self.sample_rate, step_len, dtype=np.float32)
            # Low frequency thump with quick decay
            step = 0.15 * np.sin(2 * np.pi * 80 * t) * np.exp(-t * 40)
            signal[pos:pos + step_len] = step
            # Vary timing slightly
            pos += step_interval + np.random.randint(-int(0.05 * self.sample_rate),
                                                      int(0.05 * self.sample_rate))
        return signal

    def mix_audio(self, *sources: np.ndarray,
                  levels: list[float] | None = None) -> np.ndarray:
        """Mix multiple audio sources with optional gain levels.

        Pads shorter sources to match the longest.
        """
        if not sources:
            return np.zeros(0, dtype=np.float32)

        if levels is None:
            levels = [1.0] * len(sources)

        max_len = max(len(s) for s in sources)
        result = np.zeros(max_len, dtype=np.float32)

        for src, level in zip(sources, levels):
            padded = np.zeros(max_len, dtype=np.float32)
            padded[:len(src)] = src
            result += padded * level

        # Clip to valid range
        return np.clip(result, -1.0, 1.0)
