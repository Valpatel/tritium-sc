"""Piper TTS output for Amy.

Uses ``aplay`` for audio playback instead of sounddevice to avoid
PortAudio conflicts with concurrent audio recording.
"""

from __future__ import annotations

import os
import subprocess
import threading
import queue


DEFAULT_PIPER_DIR = os.path.expanduser("~/models/piper")
DEFAULT_PIPER_BIN = os.path.join(DEFAULT_PIPER_DIR, "piper")
DEFAULT_VOICE_MODEL = os.path.join(DEFAULT_PIPER_DIR, "en_US-amy-medium.onnx")


class Speaker:
    """Text-to-speech using Piper with queued playback.

    Playback uses ``aplay`` (ALSA) to avoid segfaults caused by
    concurrent sounddevice play/record operations.
    """

    def __init__(
        self,
        piper_bin: str = DEFAULT_PIPER_BIN,
        voice_model: str = DEFAULT_VOICE_MODEL,
        sample_rate: int = 22050,
    ):
        self.piper_bin = os.path.abspath(piper_bin)
        self.voice_model = os.path.abspath(voice_model)
        self.sample_rate = sample_rate
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    @property
    def available(self) -> bool:
        return os.path.isfile(self.piper_bin) and os.path.isfile(self.voice_model)

    def speak(self, text: str) -> None:
        self._queue.put(text)

    def speak_sync(self, text: str) -> None:
        self._synthesize_and_play(text)

    def shutdown(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)

    def _worker(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                break
            self._synthesize_and_play(text)

    def _synthesize_and_play(self, text: str) -> None:
        if not self.available:
            print(f'  [TTS unavailable] "{text}"')
            return

        try:
            piper = subprocess.Popen(
                [self.piper_bin, "--model", self.voice_model, "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            aplay = subprocess.Popen(
                ["aplay", "-f", "S16_LE", "-r", str(self.sample_rate),
                 "-c", "1", "-q"],
                stdin=piper.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            piper.stdout.close()
            piper.stdin.write(text.encode("utf-8"))
            piper.stdin.close()
            aplay.wait(timeout=60)
            piper.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("  [TTS timeout]")
            for p in (piper, aplay):
                try:
                    p.kill()
                except Exception:
                    pass
        except Exception as e:
            print(f"  [TTS error] {e}")

    def synthesize_raw(self, text: str) -> bytes | None:
        if not self.available:
            return None
        try:
            proc = subprocess.run(
                [self.piper_bin, "--model", self.voice_model, "--output-raw"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0 or not proc.stdout:
                return None
            return proc.stdout
        except Exception:
            return None

    def play_raw(self, raw_audio: bytes, rate: int | None = None) -> None:
        try:
            subprocess.run(
                ["aplay", "-f", "S16_LE", "-r", str(rate or self.sample_rate),
                 "-c", "1", "-q"],
                input=raw_audio,
                timeout=60,
            )
        except Exception as e:
            print(f"  [playback error] {e}")
