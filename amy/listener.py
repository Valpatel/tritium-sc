"""Streaming speech-to-text with VAD + whisper.cpp GPU for Amy.

Uses Silero VAD for real-time voice activity detection and whisper.cpp
compiled with CUDA for GPU-accelerated transcription on the GB10.

Instead of fixed-duration chunks on CPU (30-60s per transcription),
this uses:
  - Silero VAD on 512-sample chunks (~32ms) for instant speech detection
  - whisper-server (GPU, persistent model) for <1s transcription
  - Continuous InputStream — no gaps in listening
"""

from __future__ import annotations

import io
import os
import re
import signal
import subprocess
import tempfile
import time
import wave

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
VAD_CHUNK_SAMPLES = 512  # Silero VAD needs 512 samples at 16kHz (~32ms)
SILENCE_PEAK_THRESHOLD = 0.015  # Legacy — used by is_silence() and tests

# Default paths for whisper.cpp (built with CUDA sm_121)
_WHISPER_CPP_DIR = os.path.expanduser("~/Code/whisper.cpp")
_DEFAULT_SERVER = os.path.join(_WHISPER_CPP_DIR, "build/bin/whisper-server")
_DEFAULT_CLI = os.path.join(_WHISPER_CPP_DIR, "build/bin/whisper-cli")
_DEFAULT_MODEL = os.path.join(_WHISPER_CPP_DIR, "models/ggml-large-v3-turbo.bin")
_SERVER_PORT = 8178


def find_mic(pattern: str = "BCC950") -> int | None:
    """Auto-detect a microphone by name pattern.

    Device indices change between reboots, so we search by name.
    Returns the device index, or None if not found.
    """
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and pattern in dev.get("name", ""):
            return i
    return None


class Listener:
    """Streaming VAD + whisper.cpp GPU transcription.

    Starts a whisper-server process that keeps the model loaded in GPU
    memory. Transcription requests are sent via HTTP — each one takes
    ~400ms instead of the old 30-60s with OpenAI Whisper on CPU.
    """

    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        audio_device: int | None = None,
        mic_pattern: str = "BCC950",
        whisper_server_path: str | None = None,
        whisper_cli_path: str | None = None,
        model_path: str | None = None,
        server_port: int = _SERVER_PORT,
    ):
        # Use specified device or system default (routed through PipeWire)
        if audio_device is None:
            detected = find_mic(mic_pattern)
            if detected is not None:
                audio_device = detected
                print(f"        Auto-detected mic '{mic_pattern}' at device {audio_device}")
            else:
                print("        Using default mic (PipeWire)")
        self.audio_device = audio_device
        self.sample_rate = SAMPLE_RATE

        # Resolve whisper.cpp paths
        self._server_bin = whisper_server_path or _DEFAULT_SERVER
        self._cli_bin = whisper_cli_path or _DEFAULT_CLI
        self._model_path = model_path or _DEFAULT_MODEL
        self._server_port = server_port
        self._server_proc: subprocess.Popen | None = None
        self._server_url = f"http://127.0.0.1:{server_port}/inference"

        if not os.path.exists(self._model_path):
            raise FileNotFoundError(f"Whisper model not found: {self._model_path}")

        # Load Silero VAD (runs on CPU — tiny model, <1ms per chunk)
        import torch
        self._torch = torch
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        self._vad_model = model
        self._vad_threshold = 0.5
        print("        Silero VAD: loaded")

        # Start whisper-server (keeps model in GPU memory)
        self._start_server()

    def _start_server(self) -> None:
        """Start whisper-server as a background process."""
        if not os.path.exists(self._server_bin):
            print(f"        WARNING: whisper-server not found at {self._server_bin}")
            print(f"        Falling back to whisper-cli (slower — reloads model each call)")
            return

        print(f"        Starting whisper-server (GPU, port {self._server_port})...")
        # whisper.cpp was compiled with CUDA sm_121 and CAN use the GPU,
        # even though PyTorch cannot.  Remove CUDA_VISIBLE_DEVICES=""
        # restriction that start.sh sets for the main process.
        env = os.environ.copy()
        env.pop("CUDA_VISIBLE_DEVICES", None)
        self._server_proc = subprocess.Popen(
            [
                self._server_bin,
                "-m", self._model_path,
                "-l", "en",
                "--port", str(self._server_port),
                "--host", "127.0.0.1",
                "-t", "4",
                "-nt",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
            env=env,
        )

        # Wait for server to be ready
        import urllib.request
        for attempt in range(30):
            time.sleep(0.5)
            if self._server_proc.poll() is not None:
                stderr = self._server_proc.stderr.read().decode() if self._server_proc.stderr else ""
                print(f"        whisper-server exited unexpectedly: {stderr[:200]}")
                self._server_proc = None
                return
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{self._server_port}/",
                    timeout=1,
                )
                print(f"        whisper-server: ready (GPU, {os.path.basename(self._model_path)})")
                return
            except Exception:
                continue

        print("        whisper-server: timed out waiting for ready")
        self._kill_server()

    def _kill_server(self) -> None:
        """Kill the whisper-server process."""
        if self._server_proc is not None:
            try:
                os.killpg(os.getpgid(self._server_proc.pid), signal.SIGTERM)
                self._server_proc.wait(timeout=5)
            except Exception:
                try:
                    self._server_proc.kill()
                except Exception:
                    pass
            self._server_proc = None

    # --- VAD ---

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """Run Silero VAD on a chunk. Returns True if speech detected.

        Chunk should be 512 samples at 16kHz (~32ms).
        """
        tensor = self._torch.from_numpy(audio_chunk).float()
        confidence = self._vad_model(tensor, SAMPLE_RATE).item()
        return confidence > self._vad_threshold

    def reset_vad(self) -> None:
        """Reset VAD internal state (call after disable/enable transitions)."""
        self._vad_model.reset_states()

    # --- Transcription ---

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio using whisper.cpp GPU.

        Tries whisper-server first (fast — model already loaded), falls
        back to whisper-cli if server is down.
        """
        if len(audio) < int(SAMPLE_RATE * 0.3):
            return ""

        if self._server_proc is not None and self._server_proc.poll() is None:
            text = self._transcribe_server(audio)
        elif os.path.exists(self._cli_bin):
            text = self._transcribe_cli(audio)
        else:
            print("  [STT] No whisper.cpp binary available")
            return ""

        return self._filter_hallucinations(text)

    def _audio_to_wav_bytes(self, audio: np.ndarray) -> bytes:
        """Convert float32 audio to WAV bytes."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    def _transcribe_server(self, audio: np.ndarray) -> str:
        """Send audio to whisper-server via HTTP POST."""
        import urllib.request

        wav_data = self._audio_to_wav_bytes(audio)

        boundary = b"----WhisperBoundary"
        body = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            b"Content-Type: audio/wav\r\n\r\n"
            + wav_data + b"\r\n"
            b"--" + boundary + b"--\r\n"
        )

        req = urllib.request.Request(
            self._server_url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                import json
                data = json.loads(resp.read().decode())
                return data.get("text", "").strip()
        except Exception as e:
            print(f"  [STT server error: {e}]")
            return self._transcribe_cli(audio)

    def _transcribe_cli(self, audio: np.ndarray) -> str:
        """Transcribe using whisper-cli subprocess (fallback)."""
        wav_data = self._audio_to_wav_bytes(audio)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_data)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [
                    self._cli_bin,
                    "-m", self._model_path,
                    "-f", tmp_path,
                    "--no-timestamps",
                    "-l", "en",
                    "-t", "4",
                ],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            print("  [whisper-cli timeout]")
            return ""
        except Exception as e:
            print(f"  [whisper-cli error: {e}]")
            return ""
        finally:
            os.unlink(tmp_path)

    # --- Hallucination filtering ---

    HALLUCINATIONS = {
        "thank you", "thank you.", "thanks for watching",
        "thank you for watching", "thank you for watching!",
        "thanks for watching!", "thank you so much",
        "thank you so much for watching",
        "you", "bye", "bye.", "the end", "the end.",
        "subscribe", "like and subscribe",
        "...", "\u2026",
    }

    HALLUCINATION_PATTERNS = [
        re.compile(r"welcome to (my|our|the) channel", re.I),
        re.compile(r"today (i|we) will (show|teach|make|learn)", re.I),
        re.compile(r"(delicious|simple|easy).{0,30}recipe", re.I),
        re.compile(r"(like|hit).{0,15}subscribe", re.I),
        re.compile(r"don'?t forget to", re.I),
        re.compile(r"see you (in the |in |next )", re.I),
        re.compile(r"please (subscribe|like|share|comment)", re.I),
        re.compile(r"chicken (breast|with)", re.I),
        re.compile(r"(this|the|my) video", re.I),
        re.compile(r"links? (in |below)", re.I),
        re.compile(r"in the description", re.I),
    ]

    def _filter_hallucinations(self, text: str) -> str:
        """Filter common Whisper hallucinations."""
        text = text.strip()
        if not text:
            return ""

        if text.lower().rstrip(".!?,") in self.HALLUCINATIONS:
            print(f"  [STT filtered (hallucination): {text!r}]")
            return ""

        for pat in self.HALLUCINATION_PATTERNS:
            if pat.search(text):
                print(f"  [STT filtered (pattern): {text!r}]")
                return ""

        return text

    # --- Legacy compatibility ---

    def record(self, duration: float = 4.0) -> np.ndarray:
        """Record fixed duration audio. Legacy — prefer VAD-based streaming."""
        samples = int(duration * self.sample_rate)
        audio = sd.rec(
            samples, samplerate=self.sample_rate,
            channels=1, dtype="float32", device=self.audio_device,
        )
        sd.wait()
        return audio.flatten()

    def is_silence(self, audio: np.ndarray) -> bool:
        """Check if audio is silence via peak amplitude."""
        peak = float(np.max(np.abs(audio)))
        return peak < SILENCE_PEAK_THRESHOLD

    def listen(self, duration: float = 4.0) -> str | None:
        """Legacy single-shot listen."""
        audio = self.record(duration)
        if self.is_silence(audio):
            return None
        text = self.transcribe(audio)
        return text if text else None

    # --- Lifecycle ---

    def shutdown(self) -> None:
        """Stop the whisper-server process."""
        self._kill_server()
