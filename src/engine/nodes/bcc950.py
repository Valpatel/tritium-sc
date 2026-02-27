"""BCC950 PTZ camera + mic + speaker sensor node.

Full-featured node: camera with YOLO-capable frames, PTZ motor control,
microphone input (via sounddevice), and speaker output (via aplay/Piper).
Uses the bcc950 Python package and optional native C++ backend.
"""

from __future__ import annotations

import glob
import os
import subprocess
import threading
import time

import cv2
import numpy as np

from .base import SensorNode, Position
from .frame_buffer import FrameBuffer


def _find_bcc950_alsa_card() -> int | None:
    """Find the BCC950/Conexant ALSA capture card number via ``arecord -l``.

    PortAudio sometimes reports 0 input channels for the Conexant chip,
    so we fall back to ALSA which sees it correctly.
    """
    try:
        r = subprocess.run(
            ["arecord", "-l"],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            upper = line.upper()
            if ("BCC950" in upper or "CONEXANT" in upper) and line.startswith("card "):
                # Format: "card 1: CX20590 [CONEXANT USB AUDIO], device 0: ..."
                card_str = line.split(":")[0].replace("card ", "").strip()
                return int(card_str)
    except Exception:
        pass
    return None


def _find_bcc950_device() -> str | None:
    """Scan /dev/video* for the BCC950 by V4L2 device name.

    Device numbers shift after USB replug, so we can't assume /dev/video0.
    """
    for dev in sorted(glob.glob("/dev/video*")):
        try:
            r = subprocess.run(
                ["v4l2-ctl", "-d", dev, "--info"],
                capture_output=True, text=True, timeout=2,
            )
            if "BCC950" in r.stdout:
                return dev
        except Exception:
            continue
    return None


class BCC950Node(SensorNode):
    """BCC950 ConferenceCam — PTZ camera + mic + speaker.

    Requires the bcc950 Python package (from logitech_bcc950 repo).
    Auto-detects native C++ backend for 55x faster PTZ control.
    """

    def __init__(
        self,
        node_id: str = "bcc950",
        name: str = "BCC950 Command Camera",
        device: str | None = None,
        audio_device: int | None = None,
    ):
        super().__init__(node_id, name)
        self._device = device
        self._audio_device = audio_device
        self._cap: cv2.VideoCapture | None = None
        self._cap_lock = threading.Lock()
        self._frame_buffer: FrameBuffer | None = None
        self._controller = None
        self._listener_device_rate: int = 16000
        self._use_arecord: bool = False
        self._alsa_card: int | None = None

    @property
    def has_camera(self) -> bool:
        return True

    @property
    def has_ptz(self) -> bool:
        return True

    @property
    def has_mic(self) -> bool:
        return True

    @property
    def has_speaker(self) -> bool:
        return True

    def start(self) -> None:
        from bcc950 import BCC950Controller, MotionVerifier
        import sys

        # Auto-detect device if not specified
        device = self._device
        if device is None:
            device = _find_bcc950_device()
            if device is None:
                raise RuntimeError("BCC950 camera not found")
        print(f"        [bcc950] device: {device}", flush=True)

        # Init controller with optional native backend
        try:
            from bcc950.native_backend import NativeV4L2Backend, is_available
            if is_available():
                backend = NativeV4L2Backend()
                self._controller = BCC950Controller(device=device, backend=backend)
                print("        [bcc950] native backend", flush=True)
            else:
                self._controller = BCC950Controller(device=device)
                print("        [bcc950] v4l2-ctl backend", flush=True)
        except ImportError:
            self._controller = BCC950Controller(device=device)
            print("        [bcc950] v4l2-ctl backend (fallback)", flush=True)

        # Skip reset_position on boot — v4l2-ctl can block in uvicorn
        print("        [bcc950] position: using current", flush=True)

        # Open video capture
        self._cap = cv2.VideoCapture(self._controller.device)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open video stream: {self._controller.device}")
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Set up locked motion verifier
        class LockedMotionVerifier(MotionVerifier):
            def __init__(self, cap, cap_lock, **kwargs):
                super().__init__(cap, **kwargs)
                self._cap_lock = cap_lock

            def grab_gray(self):
                with self._cap_lock:
                    return super().grab_gray()

            def grab_frame(self):
                with self._cap_lock:
                    return super().grab_frame()

        verifier = LockedMotionVerifier(self._cap, self._cap_lock)
        self._controller._motion.verifier = verifier

        # Start frame buffer
        self._frame_buffer = FrameBuffer(self._cap, self._cap_lock)
        self._frame_buffer.start()

        # Auto-detect mic
        self._setup_audio()

    def _setup_audio(self) -> None:
        """Detect BCC950 mic and determine native sample rate.

        The BCC950's mic is a Conexant chip that PortAudio sometimes can't
        enumerate as an input device (reports 0 channels).  When sounddevice
        fails to find it, fall back to ALSA detection via ``arecord -l`` and
        use ``arecord`` for recording (same pattern as play_audio uses aplay).
        """
        # Try sounddevice first
        try:
            import sounddevice as sd
            if self._audio_device is None:
                for i, dev in enumerate(sd.query_devices()):
                    name = dev.get("name", "")
                    if dev["max_input_channels"] > 0 and ("BCC950" in name or "CONEXANT" in name.upper()):
                        self._audio_device = i
                        break
            if self._audio_device is not None:
                dev_info = sd.query_devices(self._audio_device)
                self._listener_device_rate = int(dev_info["default_samplerate"])
                self._use_arecord = False
                return
        except ImportError:
            pass

        # Fallback: detect via ALSA (arecord -l)
        self._alsa_card = _find_bcc950_alsa_card()
        if self._alsa_card is not None:
            self._use_arecord = True
            self._listener_device_rate = 16000
            print(f"        [bcc950] mic: ALSA hw:{self._alsa_card},0 (arecord)", flush=True)
        else:
            self._use_arecord = False

    def stop(self) -> None:
        if self._frame_buffer is not None:
            self._frame_buffer.stop()
        if self._controller is not None:
            self._controller.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # --- Camera ---

    def get_frame(self) -> np.ndarray | None:
        if self._frame_buffer is None:
            return None
        return self._frame_buffer.frame

    def get_jpeg(self) -> bytes | None:
        if self._frame_buffer is None:
            return None
        return self._frame_buffer.jpeg

    @property
    def frame_id(self) -> int:
        if self._frame_buffer is None:
            return 0
        return self._frame_buffer.frame_id

    # --- PTZ ---

    def move(self, pan_dir: int, tilt_dir: int, duration: float) -> tuple[bool, bool]:
        if self._controller is None:
            return (False, False)
        return self._controller.move(pan_dir, tilt_dir, duration)

    def get_position(self) -> Position:
        if self._controller is None:
            return Position()
        pos = self._controller.position
        return Position(
            pan=pos.pan,
            tilt=pos.tilt,
            zoom=pos.zoom,
            pan_min=pos.pan_min,
            pan_max=pos.pan_max,
            tilt_min=pos.tilt_min,
            tilt_max=pos.tilt_max,
        )

    def reset_position(self) -> None:
        if self._controller is not None:
            self._controller.reset_position()

    # --- Audio ---

    def record_audio(self, duration: float) -> np.ndarray | None:
        if self._use_arecord and self._alsa_card is not None:
            return self._record_via_arecord(duration)

        import sounddevice as sd

        samples = int(duration * self._listener_device_rate)
        audio = sd.rec(
            samples,
            samplerate=self._listener_device_rate,
            channels=1,
            dtype="float32",
            device=self._audio_device,
        )
        sd.wait()
        audio = audio.flatten()

        # Resample to 16kHz if needed
        if self._listener_device_rate != 16000:
            target_len = int(len(audio) * 16000 / self._listener_device_rate)
            indices = np.linspace(0, len(audio) - 1, target_len)
            audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

        return audio

    def _record_via_arecord(self, duration: float) -> np.ndarray | None:
        """Record audio via ALSA arecord when PortAudio can't access the mic."""
        try:
            r = subprocess.run(
                [
                    "arecord",
                    "-D", f"hw:{self._alsa_card},0",
                    "-f", "S16_LE",
                    "-r", str(self._listener_device_rate),
                    "-c", "1",
                    "-d", str(int(duration)),
                    "-t", "raw",
                    "-q",
                ],
                capture_output=True, timeout=duration + 5,
            )
            if r.returncode != 0:
                print(f"  [BCC950 arecord error] rc={r.returncode}", flush=True)
                return None
            raw = r.stdout
            if len(raw) == 0:
                return None
            # Convert S16_LE PCM to float32
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            return audio
        except Exception as e:
            print(f"  [BCC950 arecord error] {e}", flush=True)
            return None

    def play_audio(self, raw_pcm: bytes, sample_rate: int = 22050) -> None:
        """Play raw PCM via aplay (never sounddevice — avoids segfaults)."""
        import subprocess
        try:
            subprocess.run(
                ["aplay", "-f", "S16_LE", "-r", str(sample_rate), "-c", "1", "-q"],
                input=raw_pcm,
                timeout=60,
            )
        except Exception as e:
            print(f"  [BCC950 playback error] {e}")

    # --- BCC950-specific helpers ---

    @property
    def controller(self):
        """Direct access to BCC950Controller for advanced operations."""
        return self._controller

    @property
    def frame_buffer(self) -> FrameBuffer | None:
        return self._frame_buffer
