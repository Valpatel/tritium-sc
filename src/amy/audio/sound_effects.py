"""Procedural sound effect generator for the Nerf war game.

All synthesis uses pure numpy/scipy -- no ML models, no external audio files.
Effects are designed with a cyberpunk/synthetic aesthetic: electronic tones,
synthesized impacts, modulated noise.

Techniques used:
    - Sine/square/sawtooth oscillators
    - ADSR envelopes
    - White/pink noise
    - Frequency sweeps via phase accumulation
    - Simple reverb via convolution with exponential decay
    - Low-pass filtering via moving average
    - All output: float32 arrays normalized to [-1.0, 1.0], 16 kHz mono
"""

from __future__ import annotations

import numpy as np


class SoundEffectGenerator:
    """Generate procedural sound effects for the Nerf war game."""

    SAMPLE_RATE: int = 16000

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _samples(self, duration: float) -> int:
        return int(duration * self.SAMPLE_RATE)

    def _time(self, n_samples: int) -> np.ndarray:
        return np.arange(n_samples, dtype=np.float32) / self.SAMPLE_RATE

    def _normalize(self, audio: np.ndarray) -> np.ndarray:
        """Clip to [-1, 1] and ensure float32."""
        return np.clip(audio, -1.0, 1.0).astype(np.float32)

    def _adsr(
        self,
        n_samples: int,
        attack: float = 0.01,
        decay: float = 0.1,
        sustain: float = 0.5,
        release: float = 0.2,
    ) -> np.ndarray:
        """ADSR envelope (all times in seconds)."""
        sr = self.SAMPLE_RATE
        a = int(attack * sr)
        d = int(decay * sr)
        r = int(release * sr)
        s = max(0, n_samples - a - d - r)

        env = np.zeros(n_samples, dtype=np.float32)
        idx = 0
        # Attack
        seg = min(a, n_samples - idx)
        if seg > 0:
            env[idx:idx + seg] = np.linspace(0, 1, seg, dtype=np.float32)
            idx += seg
        # Decay
        seg = min(d, n_samples - idx)
        if seg > 0:
            env[idx:idx + seg] = np.linspace(1, sustain, seg, dtype=np.float32)
            idx += seg
        # Sustain
        seg = min(s, n_samples - idx)
        if seg > 0:
            env[idx:idx + seg] = sustain
            idx += seg
        # Release
        seg = min(r, n_samples - idx)
        if seg > 0:
            env[idx:idx + seg] = np.linspace(sustain, 0, seg, dtype=np.float32)
        return env

    def _exp_decay(self, n_samples: int, rate: float = 5.0) -> np.ndarray:
        """Exponential decay envelope."""
        t = self._time(n_samples)
        return np.exp(-rate * t).astype(np.float32)

    def _moving_average(self, audio: np.ndarray, window: int = 5) -> np.ndarray:
        """Simple low-pass filter via moving average."""
        if window <= 1:
            return audio
        kernel = np.ones(window, dtype=np.float32) / window
        return np.convolve(audio, kernel, mode="same").astype(np.float32)

    def _simple_reverb(
        self, audio: np.ndarray, decay: float = 3.0, wet: float = 0.3
    ) -> np.ndarray:
        """Simple reverb via convolution with exponential impulse response."""
        ir_len = int(0.15 * self.SAMPLE_RATE)  # 150ms impulse response
        t = np.arange(ir_len, dtype=np.float32) / self.SAMPLE_RATE
        ir = np.exp(-decay * t).astype(np.float32)
        ir /= ir.sum()  # normalize
        reverbed = np.convolve(audio, ir, mode="full")[:len(audio)]
        return (audio * (1 - wet) + reverbed * wet).astype(np.float32)

    def _freq_sweep(
        self,
        n_samples: int,
        f_start: float,
        f_end: float,
        waveform: str = "sine",
    ) -> np.ndarray:
        """Frequency sweep via phase accumulation."""
        freqs = np.linspace(f_start, f_end, n_samples, dtype=np.float32)
        phase = np.cumsum(freqs / self.SAMPLE_RATE) * 2 * np.pi
        if waveform == "sine":
            return np.sin(phase).astype(np.float32)
        elif waveform == "square":
            return np.sign(np.sin(phase)).astype(np.float32)
        elif waveform == "sawtooth":
            return ((phase % (2 * np.pi)) / np.pi - 1).astype(np.float32)
        return np.sin(phase).astype(np.float32)

    # -----------------------------------------------------------------
    # Combat effects
    # -----------------------------------------------------------------

    def nerf_shot(self, duration: float = 0.3) -> np.ndarray:
        """Nerf gun firing: sharp attack, mid-freq pop, quick decay."""
        n = self._samples(duration)
        t = self._time(n)

        # Sharp transient: noise burst with fast decay
        noise = np.random.randn(n).astype(np.float32) * 0.6
        attack_env = self._exp_decay(n, rate=25.0)

        # Mid-frequency pop (600 Hz sine with fast decay)
        pop = np.sin(2 * np.pi * 600 * t).astype(np.float32)
        pop_env = self._exp_decay(n, rate=20.0)

        # High click (2500 Hz, very fast decay)
        click = np.sin(2 * np.pi * 2500 * t).astype(np.float32)
        click_env = self._exp_decay(n, rate=50.0)

        out = noise * attack_env * 0.4 + pop * pop_env * 0.4 + click * click_env * 0.2
        return self._normalize(out)

    def projectile_whoosh(self, duration: float = 0.5) -> np.ndarray:
        """Projectile in flight: frequency-swept filtered white noise."""
        n = self._samples(duration)

        # White noise
        noise = np.random.randn(n).astype(np.float32)

        # Bandpass effect: apply a moving average that changes width
        # Simulate doppler with frequency sweep modulation
        sweep = self._freq_sweep(n, 800, 200, waveform="sine")

        # Envelope: fade in, sustain, fade out
        env = self._adsr(n, attack=0.05, decay=0.05, sustain=0.8, release=0.15)

        # Modulate noise with sweep to create tonal whoosh
        filtered = self._moving_average(noise, window=8)
        out = (filtered * 0.5 + sweep * 0.3) * env * 0.7
        return self._normalize(out)

    def impact_hit(self, duration: float = 0.2) -> np.ndarray:
        """Projectile impact: short thud with high-freq crack."""
        n = self._samples(duration)
        t = self._time(n)

        # Low thud (150 Hz with fast decay)
        thud = np.sin(2 * np.pi * 150 * t).astype(np.float32)
        thud_env = self._exp_decay(n, rate=30.0)

        # High-freq crack (noise burst, first few ms)
        crack = np.random.randn(n).astype(np.float32)
        crack_env = self._exp_decay(n, rate=60.0)

        out = thud * thud_env * 0.6 + crack * crack_env * 0.4
        return self._normalize(out)

    def explosion(self, duration: float = 1.0) -> np.ndarray:
        """Explosion: low rumble + noise burst + reverb tail."""
        n = self._samples(duration)
        t = self._time(n)

        # Low rumble (50-80 Hz)
        rumble = np.sin(2 * np.pi * 55 * t).astype(np.float32)
        rumble += np.sin(2 * np.pi * 80 * t).astype(np.float32) * 0.5
        rumble_env = self._exp_decay(n, rate=3.0)

        # Noise burst (fast attack, medium decay)
        noise = np.random.randn(n).astype(np.float32)
        noise_env = self._exp_decay(n, rate=5.0)
        # Shape the attack
        attack_len = int(0.01 * self.SAMPLE_RATE)
        if attack_len > 0 and attack_len < n:
            noise_env[:attack_len] *= np.linspace(0, 1, attack_len)

        # Combine
        out = rumble * rumble_env * 0.4 + noise * noise_env * 0.5

        # Add reverb tail
        out = self._simple_reverb(out, decay=2.0, wet=0.4)
        return self._normalize(out * 0.8)

    def turret_rotate(self, duration: float = 0.8) -> np.ndarray:
        """Turret rotation: servo motor whirr (sawtooth + noise)."""
        n = self._samples(duration)
        t = self._time(n)

        # Sawtooth at servo frequency (~120 Hz)
        saw = ((120 * t * 2 * np.pi) % (2 * np.pi) / np.pi - 1).astype(np.float32)

        # Add mechanical noise
        noise = np.random.randn(n).astype(np.float32) * 0.1
        noise = self._moving_average(noise, window=4)

        # Slight pitch variation (wobble)
        wobble = np.sin(2 * np.pi * 3 * t).astype(np.float32) * 0.1
        saw_mod = ((120 * (1 + wobble) * t * 2 * np.pi) % (2 * np.pi) / np.pi - 1)

        # Envelope: ramp up, sustain, ramp down
        env = self._adsr(n, attack=0.1, decay=0.05, sustain=0.7, release=0.15)

        out = (saw_mod.astype(np.float32) * 0.5 + noise * 0.3) * env * 0.5
        return self._normalize(out)

    def drone_buzz(self, duration: float = 2.0) -> np.ndarray:
        """Drone propellers: modulated buzz (multi-freq square waves)."""
        n = self._samples(duration)
        t = self._time(n)

        # Multiple propeller frequencies
        prop1 = np.sign(np.sin(2 * np.pi * 180 * t)).astype(np.float32)
        prop2 = np.sign(np.sin(2 * np.pi * 195 * t)).astype(np.float32)
        prop3 = np.sign(np.sin(2 * np.pi * 210 * t)).astype(np.float32)
        prop4 = np.sign(np.sin(2 * np.pi * 225 * t)).astype(np.float32)

        # Modulate with low-frequency oscillation (flight dynamics)
        lfo = (1.0 + 0.15 * np.sin(2 * np.pi * 1.5 * t)).astype(np.float32)

        buzz = (prop1 + prop2 * 0.8 + prop3 * 0.6 + prop4 * 0.4) / 4.0
        buzz = buzz * lfo

        # Add slight noise for air turbulence
        noise = np.random.randn(n).astype(np.float32) * 0.05
        noise = self._moving_average(noise, window=6)

        # Gentle envelope
        env = self._adsr(n, attack=0.3, decay=0.1, sustain=0.8, release=0.5)

        out = (buzz * 0.6 + noise) * env * 0.4
        return self._normalize(out)

    def footstep(self, duration: float = 0.15) -> np.ndarray:
        """Single footstep: filtered noise burst."""
        n = self._samples(duration)

        # Short noise burst
        noise = np.random.randn(n).astype(np.float32)

        # Low-pass filter (moving average with large window)
        filtered = self._moving_average(noise, window=12)

        # Sharp envelope: fast attack, fast decay
        env = self._exp_decay(n, rate=35.0)
        # Add small attack ramp
        attack_len = min(int(0.005 * self.SAMPLE_RATE), n)
        if attack_len > 0:
            env[:attack_len] *= np.linspace(0, 1, attack_len)

        out = filtered * env * 0.7
        return self._normalize(out)

    # -----------------------------------------------------------------
    # Alert / UI effects
    # -----------------------------------------------------------------

    def alert_tone(self, duration: float = 0.5) -> np.ndarray:
        """Threat alert: ascending two-tone beep (cyberpunk style)."""
        n = self._samples(duration)
        t = self._time(n)

        half = n // 2

        # Two ascending tones
        tone1 = np.sin(2 * np.pi * 880 * t[:half]).astype(np.float32)
        tone2 = np.sin(2 * np.pi * 1320 * t[half:n]).astype(np.float32)

        out = np.zeros(n, dtype=np.float32)
        out[:half] = tone1
        out[half:n] = tone2

        # Add harmonics for cyberpunk edge
        harmonics = np.sin(2 * np.pi * 1760 * t).astype(np.float32) * 0.2
        harmonics += np.sin(2 * np.pi * 2640 * t).astype(np.float32) * 0.1

        # Envelope each tone separately
        env1 = self._adsr(half, attack=0.005, decay=0.02, sustain=0.8, release=0.02)
        env2_len = n - half
        env2 = self._adsr(env2_len, attack=0.005, decay=0.02, sustain=0.8, release=0.05)

        full_env = np.zeros(n, dtype=np.float32)
        full_env[:half] = env1
        full_env[half:n] = env2

        out = (out + harmonics) * full_env * 0.6
        return self._normalize(out)

    def escalation_siren(self, duration: float = 2.0) -> np.ndarray:
        """Escalation alert: rising frequency siren sweep."""
        n = self._samples(duration)

        # Rising sweep from 400 to 1800 Hz
        sweep = self._freq_sweep(n, 400, 1800, waveform="sine")

        # Add harmonic overtone
        sweep2 = self._freq_sweep(n, 800, 3600, waveform="sine")

        # Pulsing envelope (4 Hz pulse)
        t = self._time(n)
        pulse = (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)).astype(np.float32)

        # Overall envelope
        env = self._adsr(n, attack=0.1, decay=0.05, sustain=0.9, release=0.3)

        out = (sweep * 0.6 + sweep2 * 0.25) * pulse * env * 0.7
        return self._normalize(out)

    def dispatch_ack(self, duration: float = 0.3) -> np.ndarray:
        """Dispatch acknowledgment: short confirmation bleep."""
        n = self._samples(duration)
        t = self._time(n)

        # Two quick ascending bleeps
        third = n // 3

        bleep1 = np.sin(2 * np.pi * 1000 * t[:third]).astype(np.float32)
        bleep2 = np.sin(2 * np.pi * 1500 * t[third:2*third]).astype(np.float32)

        out = np.zeros(n, dtype=np.float32)
        out[:third] = bleep1 * 0.7
        out[third:2*third] = bleep2 * 0.8

        # Envelope
        env = self._adsr(n, attack=0.005, decay=0.02, sustain=0.6, release=0.1)
        out = out * env
        return self._normalize(out)

    # -----------------------------------------------------------------
    # Game state effects
    # -----------------------------------------------------------------

    def wave_start(self, duration: float = 1.5) -> np.ndarray:
        """Wave start: dramatic horn/synth stab."""
        n = self._samples(duration)
        t = self._time(n)

        # Power chord: root + fifth + octave
        root = 110  # A2
        chord = (
            np.sin(2 * np.pi * root * t).astype(np.float32) * 0.4
            + np.sin(2 * np.pi * root * 1.5 * t).astype(np.float32) * 0.3  # fifth
            + np.sin(2 * np.pi * root * 2 * t).astype(np.float32) * 0.2  # octave
        )

        # Add sawtooth grit
        saw = ((root * t * 2 * np.pi) % (2 * np.pi) / np.pi - 1).astype(np.float32)

        # Envelope: strong attack, hold, dramatic fade
        env = self._adsr(n, attack=0.02, decay=0.1, sustain=0.7, release=0.5)

        out = (chord + saw * 0.15) * env * 0.7

        # Reverb for drama
        out = self._simple_reverb(out, decay=2.5, wet=0.35)
        return self._normalize(out)

    def victory_fanfare(self, duration: float = 3.0) -> np.ndarray:
        """Victory: ascending notes with reverb."""
        n = self._samples(duration)
        out = np.zeros(n, dtype=np.float32)

        # Ascending notes: C5, E5, G5, C6
        notes = [523, 659, 784, 1047]
        note_len = n // (len(notes) + 1)  # leave room for reverb tail

        for i, freq in enumerate(notes):
            start = i * note_len
            end = min(start + note_len, n)
            seg_len = end - start
            t = self._time(seg_len)

            tone = np.sin(2 * np.pi * freq * t).astype(np.float32)
            # Add shimmer (slight vibrato)
            vibrato = np.sin(2 * np.pi * 5 * t).astype(np.float32) * 0.02
            tone = np.sin(2 * np.pi * freq * (1 + vibrato) * t).astype(np.float32)

            # Each note has its own envelope
            note_env = self._adsr(seg_len, attack=0.01, decay=0.05, sustain=0.8, release=0.15)
            out[start:end] += tone * note_env * 0.5

        # Add harmonics
        t_full = self._time(n)
        shimmer = np.sin(2 * np.pi * 2093 * t_full).astype(np.float32) * 0.08
        final_env = self._adsr(n, attack=0.05, decay=0.2, sustain=0.4, release=1.0)
        out += shimmer * final_env

        # Generous reverb
        out = self._simple_reverb(out, decay=1.5, wet=0.45)
        return self._normalize(out)

    def defeat_sting(self, duration: float = 2.0) -> np.ndarray:
        """Defeat: descending notes, low rumble."""
        n = self._samples(duration)
        out = np.zeros(n, dtype=np.float32)
        t_full = self._time(n)

        # Descending notes: C4, Ab3, F3, Db3 (diminished feel)
        notes = [262, 208, 175, 139]
        note_len = n // (len(notes) + 1)

        for i, freq in enumerate(notes):
            start = i * note_len
            end = min(start + note_len, n)
            seg_len = end - start
            t = self._time(seg_len)

            tone = np.sin(2 * np.pi * freq * t).astype(np.float32)
            note_env = self._adsr(seg_len, attack=0.02, decay=0.1, sustain=0.6, release=0.2)
            out[start:end] += tone * note_env * 0.4

        # Low rumble underneath
        rumble = np.sin(2 * np.pi * 60 * t_full).astype(np.float32)
        rumble_env = self._adsr(n, attack=0.3, decay=0.3, sustain=0.4, release=0.8)
        out += rumble * rumble_env * 0.25

        # Dark reverb
        out = self._simple_reverb(out, decay=1.8, wet=0.5)
        return self._normalize(out)

    def elimination_streak(self, streak_name: str, duration: float = 1.5) -> np.ndarray:
        """Elimination streak sound: escalating tones based on streak level.

        Higher streaks get more intense: higher pitches, more harmonics,
        longer sustain.
        """
        n = self._samples(duration)
        t = self._time(n)

        # Map streak name to intensity level
        intensity = {
            "KILLING SPREE": 1,
            "RAMPAGE": 2,
            "DOMINATING": 3,
            "GODLIKE": 4,
        }.get(streak_name, 1)

        # Base frequency rises with intensity
        base_freq = 300 + intensity * 150

        # Power chord with increasing harmonics
        chord = np.sin(2 * np.pi * base_freq * t).astype(np.float32)
        chord += np.sin(2 * np.pi * base_freq * 1.5 * t).astype(np.float32) * 0.4

        # More harmonics at higher intensity
        for h in range(2, intensity + 2):
            chord += (np.sin(2 * np.pi * base_freq * h * t).astype(np.float32)
                      * (0.2 / h))

        # Add noise burst proportional to intensity
        noise = np.random.randn(n).astype(np.float32) * 0.1 * intensity
        noise_env = self._exp_decay(n, rate=8.0)

        # Envelope gets more aggressive at higher intensity
        attack = max(0.005, 0.03 - intensity * 0.005)
        env = self._adsr(n, attack=attack, decay=0.1, sustain=0.6 + intensity * 0.05,
                         release=0.3)

        out = (chord * 0.5 + noise * noise_env) * env * 0.6

        # Reverb increases with intensity
        out = self._simple_reverb(out, decay=2.0 + intensity * 0.3,
                                  wet=0.3 + intensity * 0.05)
        return self._normalize(out)

    # -----------------------------------------------------------------
    # Ambient effects
    # -----------------------------------------------------------------

    def ambient_wind(self, duration: float = 5.0) -> np.ndarray:
        """Ambient wind: slow-modulated filtered noise."""
        n = self._samples(duration)
        t = self._time(n)

        # White noise, heavily filtered
        noise = np.random.randn(n).astype(np.float32)
        filtered = self._moving_average(noise, window=20)

        # Slow amplitude modulation (wind gusts)
        lfo = (0.3 + 0.7 * (
            0.5 * np.sin(2 * np.pi * 0.2 * t)
            + 0.3 * np.sin(2 * np.pi * 0.07 * t)
            + 0.2 * np.sin(2 * np.pi * 0.13 * t)
        )).astype(np.float32)

        out = filtered * lfo * 0.15
        return self._normalize(out)

    def ambient_birds(self, duration: float = 5.0) -> np.ndarray:
        """Birds: random chirps (short sine bursts at high freq)."""
        n = self._samples(duration)
        out = np.zeros(n, dtype=np.float32)

        # Background: very quiet pink-ish noise
        bg_noise = np.random.randn(n).astype(np.float32)
        bg_noise = self._moving_average(bg_noise, window=15)
        out += bg_noise * 0.02

        # Random chirps
        n_chirps = max(1, int(duration * 0.8))
        for _ in range(n_chirps):
            start = np.random.randint(0, max(1, n - self.SAMPLE_RATE // 4))
            freq = np.random.uniform(2500, 5500)
            chirp_dur = np.random.uniform(0.04, 0.12)
            chirp_len = int(chirp_dur * self.SAMPLE_RATE)
            if chirp_len <= 0:
                continue

            ct = self._time(chirp_len)
            # Frequency modulated chirp (rising pitch)
            freq_mod = freq + np.random.uniform(-500, 500) * ct / chirp_dur
            chirp = np.sin(2 * np.pi * freq_mod * ct).astype(np.float32)

            # Envelope: sine-shaped
            chirp_env = np.sin(np.pi * ct / chirp_dur).astype(np.float32)
            chirp = chirp * chirp_env * np.random.uniform(0.03, 0.08)

            end = min(start + chirp_len, n)
            out[start:end] += chirp[:end - start]

        return self._normalize(out)
