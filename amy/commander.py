"""Amy Commander — the main orchestrator.

Ties together sensor nodes, motor programs, audio, vision, thinking,
and LLM chat into a single autonomous consciousness.  Designed to run
as a background thread inside tritium-sc's FastAPI lifespan.

Refactored from creature.py — uses SensorNode interface instead of
direct BCC950Controller access.
"""

from __future__ import annotations

import base64
import enum
import os
import queue
import random
import re
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

import cv2
import numpy as np

from .nodes.base import SensorNode, Position
from .perception import FrameAnalyzer, FrameMetrics, PoseEstimator
from .sensorium import Sensorium
from .memory import Memory
from .extraction import extract_person_name, extract_facts
from .transcript import Transcript

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _time_of_day() -> str:
    """Return a human-friendly time-of-day label."""
    hour = datetime.now().hour
    if hour < 6:
        return "late night"
    elif hour < 12:
        return "morning"
    elif hour < 17:
        return "afternoon"
    elif hour < 21:
        return "evening"
    else:
        return "night"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class EventType(enum.Enum):
    SPEECH_DETECTED = "speech_detected"
    TRANSCRIPT_READY = "transcript_ready"
    SILENCE = "silence"
    CURIOSITY_TICK = "curiosity_tick"
    MOTOR_DONE = "motor_done"
    PERSON_ARRIVED = "person_arrived"
    PERSON_LEFT = "person_left"
    MOTION_DETECTED = "motion_detected"
    SHUTDOWN = "shutdown"


class CreatureState(enum.Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


class Event:
    __slots__ = ("type", "data")

    def __init__(self, event_type: EventType, data: object = None):
        self.type = event_type
        self.data = data


# ---------------------------------------------------------------------------
# EventBus — re-exported from amy.event_bus for backward compatibility
# ---------------------------------------------------------------------------

from .event_bus import EventBus  # noqa: F401 — canonical location is amy.event_bus


# ---------------------------------------------------------------------------
# Audio thread — VAD-based streaming
# ---------------------------------------------------------------------------

class AudioThread:
    """Continuous VAD-based audio recording in a background thread.

    Uses Silero VAD on 512-sample chunks (~32ms) for instant speech
    detection. When speech ends (0.7s silence), sends accumulated audio
    to whisper.cpp GPU for transcription (~400ms).

    Old approach: record 4s → transcribe 30-60s on CPU → repeat
    New approach: detect speech instantly → transcribe <1s on GPU
    """

    # VAD state machine parameters
    SILENCE_TIMEOUT_CHUNKS = 22   # ~0.7s of silence ends an utterance
    MAX_SPEECH_CHUNKS = 940       # ~30s max utterance length
    MIN_SPEECH_CHUNKS = 10        # ~0.3s min to bother transcribing

    def __init__(self, listener, event_queue: queue.Queue, chunk_duration: float = 4.0):
        from .listener import VAD_CHUNK_SAMPLES
        self.listener = listener
        self.queue = event_queue
        self._chunk_samples = VAD_CHUNK_SAMPLES
        self._enabled = threading.Event()
        self._enabled.set()
        self._was_disabled = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._stream = None
        self._stream_lock = threading.Lock()

    def start(self) -> None:
        self._thread.start()

    def disable(self) -> None:
        """Pause audio capture and release the ALSA device for speaker use.

        The BCC950 mic and speaker share one USB audio card.  On raw ALSA
        (no PulseAudio), the InputStream holds an exclusive lock, so aplay
        cannot open the same card until the stream is closed.
        """
        self._enabled.clear()
        self._was_disabled = True
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    def enable(self) -> None:
        self._enabled.set()

    def stop(self) -> None:
        self._stop.set()
        self._enabled.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _open_stream(self, sd, audio_q: queue.Queue):
        """Open a fresh sounddevice InputStream and store it.

        Skips if currently disabled (Amy is speaking — ALSA device busy).
        """
        if not self._enabled.is_set():
            return None

        def _audio_callback(indata, frames, time_info, status):
            if self._enabled.is_set():
                audio_q.put(indata.copy().flatten())

        try:
            stream = sd.InputStream(
                samplerate=self.listener.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self._chunk_samples,
                device=self.listener.audio_device,
                callback=_audio_callback,
            )
            stream.start()
            with self._stream_lock:
                self._stream = stream
            return stream
        except Exception as e:
            print(f"  [audio stream error: {e}]")
            return None

    def _run(self) -> None:
        import sounddevice as sd

        audio_q: queue.Queue = queue.Queue(maxsize=200)

        stream = self._open_stream(sd, audio_q)
        if stream is None:
            return

        speech_active = False
        speech_buffer: list[np.ndarray] = []
        silence_count = 0

        try:
            while not self._stop.is_set():
                # Wait if disabled (Amy speaking through speaker)
                self._enabled.wait()
                if self._stop.is_set():
                    break

                # After re-enable: reopen stream + reset state
                if self._was_disabled:
                    self._was_disabled = False
                    speech_active = False
                    speech_buffer.clear()
                    silence_count = 0
                    self.listener.reset_vad()
                    # Drain any stale audio from before disable
                    while not audio_q.empty():
                        try:
                            audio_q.get_nowait()
                        except queue.Empty:
                            break
                    # Reopen stream (disable() closed it to free ALSA)
                    with self._stream_lock:
                        if self._stream is None:
                            stream = self._open_stream(sd, audio_q)
                            if stream is None:
                                # Can't reopen — bail out of loop
                                break

                # Get next audio chunk
                try:
                    chunk = audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue

                is_speech = self.listener.is_speech(chunk)

                if is_speech:
                    silence_count = 0
                    if not speech_active:
                        speech_active = True
                        self.queue.put(Event(EventType.SPEECH_DETECTED))
                    speech_buffer.append(chunk)

                    # Safety: max utterance length
                    if len(speech_buffer) >= self.MAX_SPEECH_CHUNKS:
                        self._finish_utterance(speech_buffer)
                        speech_buffer = []
                        speech_active = False

                elif speech_active:
                    speech_buffer.append(chunk)  # Include trailing silence
                    silence_count += 1

                    if silence_count >= self.SILENCE_TIMEOUT_CHUNKS:
                        self._finish_utterance(speech_buffer)
                        speech_buffer = []
                        speech_active = False
                        silence_count = 0
                        self.listener.reset_vad()

        finally:
            with self._stream_lock:
                if self._stream is not None:
                    try:
                        self._stream.stop()
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = None

    def _finish_utterance(self, chunks: list[np.ndarray]) -> None:
        """Transcribe accumulated speech chunks and fire event."""
        if len(chunks) < self.MIN_SPEECH_CHUNKS:
            self.queue.put(Event(EventType.SILENCE))
            return

        full_audio = np.concatenate(chunks)
        text = self.listener.transcribe(full_audio)
        if text:
            self.queue.put(Event(EventType.TRANSCRIPT_READY, data=text))
        else:
            self.queue.put(Event(EventType.SILENCE))


# ---------------------------------------------------------------------------
# Curiosity timer
# ---------------------------------------------------------------------------

class CuriosityTimer:
    """Fires CURIOSITY_TICK events at random intervals."""

    def __init__(self, event_queue: queue.Queue, min_interval: float = 45.0,
                 max_interval: float = 90.0):
        self.queue = event_queue
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            delay = random.uniform(self.min_interval, self.max_interval)
            if self._stop.wait(timeout=delay):
                break
            self.queue.put(Event(EventType.CURIOSITY_TICK))


# ---------------------------------------------------------------------------
# YOLO Vision Thread
# ---------------------------------------------------------------------------

class VisionThread:
    """Continuous YOLO object detection in a background thread."""

    TRACKED_CLASSES = {
        0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
        14: "bird", 15: "cat", 16: "dog",
        24: "backpack", 25: "umbrella",
        39: "bottle", 41: "cup", 56: "chair",
        62: "tv", 63: "laptop", 64: "mouse", 66: "keyboard",
        67: "cell phone", 73: "book",
    }

    def __init__(
        self,
        node: SensorNode,
        event_bus: EventBus,
        event_queue: queue.Queue | None = None,
        model_name: str = "yolo11n.pt",
        interval: float = 0.33,
    ):
        self._node = node
        self._event_bus = event_bus
        self._event_queue = event_queue
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._scene_lock = threading.Lock()
        self._scene_summary: str = "No detections yet."
        self._prev_people_count: int = 0
        self._empty_frames: int = 0
        self._arrival_frames: int = 0
        self._latest_detections: list[dict] = []
        self._detection_lock = threading.Lock()
        self._person_target: tuple[float, float] | None = None
        self._target_lock = threading.Lock()

        # Tracking feedback metrics
        self._tracking_quality: float = 0.0
        self._tracking_quality_lock = threading.Lock()
        self._track_start: float = 0.0
        self._track_duration: float = 0.0
        self._last_quality_event: float = 0.0

        # Layered perception (L0-L2)
        self._analyzer = FrameAnalyzer()
        self._yolo_skip_count: int = 0
        self._frame_complexity: float = 0.0
        self._frame_metrics: FrameMetrics | None = None
        self._metrics_lock = threading.Lock()
        self._last_motion_push: float = 0.0

        from ultralytics import YOLO
        import torch
        engine_path = model_name.replace(".pt", ".engine")
        onnx_path = model_name.replace(".pt", ".onnx")

        # Check if CUDA is truly usable (not just available)
        cuda_usable = False
        if torch.cuda.is_available():
            try:
                _ = torch.zeros(1, device="cuda")
                cuda_usable = True
            except Exception:
                pass

        if os.path.exists(engine_path):
            self._model = YOLO(engine_path, task="detect")
            self._yolo_backend = "TensorRT"
        elif cuda_usable:
            self._model = YOLO(model_name)
            self._yolo_backend = "PyTorch CUDA"
        elif os.path.exists(onnx_path):
            self._model = YOLO(onnx_path, task="detect")
            self._yolo_backend = "ONNX CPU"
        else:
            self._model = YOLO(model_name)
            self._yolo_backend = "PyTorch CPU"
        self._warmed_up = False

    @property
    def scene_summary(self) -> str:
        with self._scene_lock:
            return self._scene_summary

    @property
    def person_target(self) -> tuple[float, float] | None:
        with self._target_lock:
            return self._person_target

    @property
    def latest_detections(self) -> list[dict]:
        with self._detection_lock:
            return list(self._latest_detections)

    @property
    def tracking_quality(self) -> float:
        """0.0 = off-center/no target, 1.0 = perfectly centered."""
        with self._tracking_quality_lock:
            return self._tracking_quality

    @property
    def track_duration(self) -> float:
        """Continuous seconds a person has been tracked."""
        with self._tracking_quality_lock:
            return self._track_duration

    @property
    def frame_complexity(self) -> float:
        """Latest L1 complexity score (0.0-1.0)."""
        with self._metrics_lock:
            return self._frame_complexity

    @property
    def frame_metrics(self) -> FrameMetrics | None:
        """Full latest L0-L2 metrics, or None if no frame analyzed yet."""
        with self._metrics_lock:
            return self._frame_metrics

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        if not self._warmed_up:
            t0 = time.monotonic()
            self._model(np.zeros((480, 640, 3), dtype=np.uint8), verbose=False)
            dt = time.monotonic() - t0
            self._warmed_up = True
            print(f"        YOLO warmup: done ({dt:.1f}s, {self._yolo_backend})")
        while not self._stop.is_set():
            frame = self._node.get_frame()
            if frame is not None:
                metrics = self._analyzer.analyze(frame)
                with self._metrics_lock:
                    self._frame_metrics = metrics
                    self._frame_complexity = metrics.complexity

                # L0: Reject unusable frames (blurred / too dark)
                if not metrics.is_usable:
                    self._stop.wait(timeout=self._interval)
                    continue

                # L2: Motion reflex — publish event
                if metrics.motion_score > 0.02:
                    self._publish_motion(metrics)

                # L3: YOLO gating — skip if boring + still
                if (metrics.motion_score < 0.005
                        and metrics.complexity < 0.03
                        and self._yolo_skip_count < 5):
                    self._yolo_skip_count += 1
                else:
                    self._detect(self._model, frame)
                    self._yolo_skip_count = 0

                # Publish frame metrics alongside detections
                self._event_bus.publish("frame_metrics", {
                    "sharpness": round(metrics.sharpness, 1),
                    "brightness": round(metrics.brightness, 1),
                    "complexity": round(metrics.complexity, 4),
                    "motion_score": round(metrics.motion_score, 4),
                })

            self._stop.wait(timeout=self._interval)

    def _publish_motion(self, metrics: FrameMetrics) -> None:
        """Publish motion reflex event to event bus and commander queue.

        Event bus gets every motion event (frontend can use it).
        Commander queue is debounced to avoid flooding the event loop.
        """
        now = time.monotonic()
        cx, cy = metrics.motion_center or (0.5, 0.5)

        self._event_bus.publish("motion", {
            "cx": round(cx, 3),
            "cy": round(cy, 3),
            "score": round(metrics.motion_score, 4),
        })

        # Debounce commander queue — at most every 2 seconds
        if now - self._last_motion_push > 2.0 and self._event_queue is not None:
            self._event_queue.put(Event(
                EventType.MOTION_DETECTED,
                data=(cx, cy, metrics.motion_score),
            ))
            self._last_motion_push = now

    def _detect(self, model, frame: np.ndarray) -> None:
        results = model(frame, verbose=False, conf=0.55)

        if not results or len(results[0].boxes) == 0:
            with self._scene_lock:
                self._scene_summary = "Scene is empty — nothing detected."
            with self._detection_lock:
                self._latest_detections = []
            with self._target_lock:
                self._person_target = None
            if self._prev_people_count > 0:
                self._empty_frames += 1
                if self._empty_frames >= 5:
                    self._event_bus.publish("event", {"text": "[everyone left]"})
                    if self._event_queue is not None:
                        self._event_queue.put(Event(EventType.PERSON_LEFT))
                    self._prev_people_count = 0
                    self._empty_frames = 0
            return

        counts: dict[str, int] = {}
        positions: list[str] = []
        detections: list[dict] = []
        person_centroids: list[tuple[float, float, float]] = []
        boxes = results[0].boxes
        h, w = frame.shape[:2]

        for i in range(len(boxes)):
            cls_id = int(boxes.cls[i])
            cls_name = self.TRACKED_CLASSES.get(cls_id)
            if cls_name is None:
                cls_name = results[0].names.get(cls_id, f"object_{cls_id}")
            conf = float(boxes.conf[i])
            x1, y1, x2, y2 = boxes.xyxy[i].tolist()

            counts[cls_name] = counts.get(cls_name, 0) + 1

            detections.append({
                "x1": x1 / w, "y1": y1 / h,
                "x2": x2 / w, "y2": y2 / h,
                "label": cls_name, "conf": conf,
            })

            if cls_id == 0:
                cx = (x1 + x2) / 2 / w
                cy = (y1 + y2) / 2 / h
                size = (x2 - x1) * (y2 - y1) / (w * h)
                pos = "left" if cx < 0.33 else ("right" if cx > 0.67 else "center")
                dist = "close" if size > 0.15 else ("far" if size < 0.03 else "nearby")
                positions.append(f"{dist} {pos}")
                person_centroids.append((cx, cy, size))

        with self._detection_lock:
            self._latest_detections = detections

        now = time.monotonic()
        if person_centroids:
            best = max(person_centroids, key=lambda p: p[2])
            with self._target_lock:
                self._person_target = (best[0], best[1])

            # Compute tracking quality: 1.0 when centered, 0.0 at edges
            cx, cy = best[0], best[1]
            offset = ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5
            quality = max(0.0, 1.0 - offset * 2.83)  # 0 at corners

            with self._tracking_quality_lock:
                self._tracking_quality = quality
                if self._track_start == 0.0:
                    self._track_start = now
                self._track_duration = now - self._track_start

        else:
            with self._target_lock:
                self._person_target = None
            with self._tracking_quality_lock:
                self._tracking_quality = 0.0
                self._track_start = 0.0
                self._track_duration = 0.0

        parts = []
        people = counts.pop("person", 0)
        if people:
            if people == 1:
                parts.append(f"1 person ({positions[0]})")
            else:
                parts.append(f"{people} people ({', '.join(positions)})")

        for name, count in sorted(counts.items()):
            if count == 1:
                parts.append(name)
            else:
                parts.append(f"{count} {name}s")

        summary = "Visible: " + ", ".join(parts) + "." if parts else "Scene is empty."

        with self._scene_lock:
            self._scene_summary = summary

        if people > 0:
            self._empty_frames = 0
            self._arrival_frames += 1
        else:
            self._arrival_frames = 0

        if people > self._prev_people_count and self._arrival_frames >= 2:
            self._event_bus.publish("event", {
                "text": f"[YOLO: {people} person(s) detected]",
            })
            if self._event_queue is not None:
                self._event_queue.put(Event(EventType.PERSON_ARRIVED, data=people))
            self._prev_people_count = people
        elif people == 0 and self._prev_people_count > 0:
            # Departure handled by the empty-frames path above
            pass
        elif people > 0 and people != self._prev_people_count and self._arrival_frames >= 2:
            self._prev_people_count = people

        self._event_bus.publish("detections", {
            "summary": summary,
            "people": people,
            "boxes": detections,
        })


# ---------------------------------------------------------------------------
# Commander
# ---------------------------------------------------------------------------

class Commander:
    """Amy's main orchestrator — ties together all subsystems.

    Manages a dict of SensorNodes. The primary_camera is used for
    YOLO, MJPEG streaming, and PTZ control. Any mic node can trigger
    wake word. Audio output goes through the primary speaker node.
    """

    def __init__(
        self,
        nodes: dict[str, SensorNode] | None = None,
        deep_model: str = "llava:7b",
        chat_model: str = "gemma3:4b",
        whisper_model: str = "large-v3",
        use_tts: bool = True,
        wake_word: str | None = "amy",
        think_interval: float = 8.0,
        curiosity_min: float = 45.0,
        curiosity_max: float = 90.0,
        use_listener: bool = True,
        boot_delay: float = 3.0,
        think_initial_delay: float = 5.0,
        memory_path: str | None = None,
        simulation_engine=None,
    ):
        self.nodes: dict[str, SensorNode] = nodes or {}
        self._event_queue: queue.Queue[Event] = queue.Queue()
        self._state = CreatureState.IDLE
        self.wake_word = wake_word.lower().strip() if wake_word else None
        self._awake = False
        self._last_spoke: float = 0.0
        self._auto_chat = False
        self._auto_chat_stop = threading.Event()
        self._person_greet_cooldown: float = 0.0

        # EventBus
        self.event_bus = EventBus()

        # Memory
        self.memory = Memory(path=memory_path)
        self._memory_save_interval = 60
        self._last_memory_save: float = 0.0

        # Sensorium
        self.sensorium = Sensorium()

        # Simulation engine (virtual targets)
        self.simulation_engine = simulation_engine

        # Tactical mode: "sim" or "live"
        # SIM = spawners active, thinking prompt says SIMULATION MODE
        # LIVE = spawners paused, thinking prompt says LIVE SENSORS
        # BCC950 camera/mic ALWAYS active in both modes
        self._mode: str = "sim"

        # Target tracker (unified real + virtual)
        from .target_tracker import TargetTracker
        self.target_tracker = TargetTracker()

        # Amy config from loaded layouts
        self.amy_config: dict = {}

        # Wire battlespace summary into sensorium
        self.sensorium._battlespace_fn = self.target_tracker.summary

        # Subscribe to events to feed target tracker (sim telemetry + YOLO detections)
        self._sim_sub = self.event_bus.subscribe()
        self._sim_bridge_thread = threading.Thread(
            target=self._sim_bridge_loop, daemon=True, name="sim-bridge"
        )

        # Deep model config
        self.deep_model = deep_model
        self._deep_observation: str = ""
        self._deep_lock = threading.Lock()
        self._deep_thread: threading.Thread | None = None

        # Store config for deferred init
        self._chat_model = chat_model
        self._whisper_model = whisper_model
        self._use_tts = use_tts
        self._think_interval = think_interval
        self._curiosity_min = curiosity_min
        self._curiosity_max = curiosity_max
        self._use_listener = use_listener
        self._boot_delay = boot_delay
        self._think_initial_delay = think_initial_delay

        # Pose estimator
        self.pose_estimator = PoseEstimator()

        # Transcript
        self.transcript = Transcript()

        # These get initialized in _boot()
        self.chat_agent = None
        self.motor = None
        self.vision_thread: VisionThread | None = None
        self.audio_thread: AudioThread | None = None
        self.curiosity_timer = None
        self.thinking = None
        self.speaker = None
        self.listener = None
        self._ack_wavs: list[bytes] = []

        self._running = False
        self._shutdown_called = False

    # --- Node management ---

    @property
    def primary_camera(self) -> SensorNode | None:
        """The first node with a camera (used for YOLO, MJPEG, deep think)."""
        for node in self.nodes.values():
            if node.has_camera:
                return node
        return None

    @property
    def primary_ptz(self) -> SensorNode | None:
        """The first node with PTZ (used for motor programs)."""
        for node in self.nodes.values():
            if node.has_ptz:
                return node
        return None

    @property
    def primary_mic(self) -> SensorNode | None:
        """The first node with a microphone."""
        for node in self.nodes.values():
            if node.has_mic:
                return node
        return None

    @property
    def primary_speaker(self) -> SensorNode | None:
        """The first node with a speaker."""
        for node in self.nodes.values():
            if node.has_speaker:
                return node
        return None

    # --- Mode ---

    @property
    def mode(self) -> str:
        """Current tactical mode: 'sim' or 'live'."""
        return self._mode

    def set_mode(self, mode: str) -> str:
        """Switch between sim and live tactical modes.

        SIM mode: spawners active, tactical data from simulation.
        LIVE mode: spawners paused, tactical data from real sensors.
        BCC950 camera/mic always active in both modes.

        Returns the new mode.
        """
        mode = mode.lower().strip()
        if mode not in ("sim", "live"):
            raise ValueError(f"Invalid mode: {mode!r} (expected 'sim' or 'live')")

        old_mode = self._mode
        self._mode = mode

        # Control simulation spawners
        engine = self.simulation_engine
        if engine is not None:
            if mode == "live":
                engine.pause_spawners()
            else:
                engine.resume_spawners()

        # Publish mode change event
        self.event_bus.publish("mode_change", {
            "mode": mode,
            "previous": old_mode,
        })

        if mode != old_mode:
            label = "SIMULATION MODE" if mode == "sim" else "LIVE SENSORS"
            self.sensorium.push("tactical", f"Mode switched to {label}", importance=0.8)
            print(f"  [mode] {old_mode} -> {mode}")

        return mode

    # --- State ---

    def _set_state(self, new_state: CreatureState) -> None:
        self._state = new_state
        self.event_bus.publish("state_change", {"state": new_state.value})

    # --- Frame capture helpers ---

    def grab_mjpeg_frame(self) -> bytes | None:
        """Grab a JPEG frame for MJPEG stream (with optional YOLO overlay)."""
        cam = self.primary_camera
        if cam is None:
            return None

        if self.vision_thread is None or not self.vision_thread.latest_detections:
            return cam.get_jpeg()

        frame = cam.get_frame()
        if frame is None:
            return cam.get_jpeg()

        frame = self._draw_yolo_overlay(frame)
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes()

    def _draw_yolo_overlay(self, frame: np.ndarray) -> np.ndarray:
        if self.vision_thread is None:
            return frame
        detections = self.vision_thread.latest_detections
        if not detections:
            return frame
        h, w = frame.shape[:2]
        for det in detections:
            x1 = int(det["x1"] * w)
            y1 = int(det["y1"] * h)
            x2 = int(det["x2"] * w)
            y2 = int(det["y2"] * h)
            label = det["label"]
            conf = det["conf"]
            color = (0, 255, 0) if label == "person" else (0, 180, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            text = f"{label} {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            label_h = th + 6
            # Clamp label X so it doesn't overflow the right edge
            lx = min(x1, w - tw - 4)
            lx = max(lx, 0)
            if y1 - label_h >= 0:
                # Draw label above the box (default)
                cv2.rectangle(frame, (lx, y1 - label_h), (lx + tw + 4, y1), color, -1)
                cv2.putText(frame, text, (lx + 2, y1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            else:
                # Draw label below the box when clipped at top edge
                cv2.rectangle(frame, (lx, y2), (lx + tw + 4, y2 + label_h), color, -1)
                cv2.putText(frame, text, (lx + 2, y2 + th + 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        return frame

    def save_photo(self, reason: str) -> str | None:
        """Capture current frame with YOLO overlay, save to amy/photos/.

        Returns the filename on success, or None.
        """
        cam = self.primary_camera
        if cam is None:
            return None
        frame = cam.get_frame()
        if frame is None:
            return None

        frame = self._draw_yolo_overlay(frame)

        photos_dir = os.path.join(os.path.dirname(__file__), "photos")
        os.makedirs(photos_dir, exist_ok=True)

        slug = re.sub(r'[^a-z0-9]+', '_', reason.lower().strip())[:40].strip('_')
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"{ts}_{slug}.jpg"
        filepath = os.path.join(photos_dir, filename)

        cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

        self.memory.add_event("photo", f"Saved photo: {reason}")
        self.transcript.append("amy", f"[Photo: {reason}]", "photo")
        self.event_bus.publish("event", {"text": f"[Saved photo: {reason}]"})
        print(f"  [photo saved]: {filename}")
        return filename

    def capture_base64(self) -> str | None:
        cam = self.primary_camera
        if cam is None:
            return None
        frame = cam.get_frame()
        if frame is None:
            return None
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return base64.b64encode(buffer).decode("utf-8")

    @staticmethod
    def _frame_sharpness(frame: np.ndarray) -> float:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()

    def _capture_clear_frame(self, min_sharpness: float = 50.0, max_tries: int = 5) -> str | None:
        cam = self.primary_camera
        if cam is None:
            return None
        for attempt in range(max_tries):
            frame = cam.get_frame()
            if frame is None:
                time.sleep(0.2)
                continue
            sharpness = self._frame_sharpness(frame)
            if sharpness >= min_sharpness:
                _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return base64.b64encode(buffer).decode("utf-8")
            if attempt < max_tries - 1:
                time.sleep(0.3)
        frame = cam.get_frame()
        if frame is None:
            return None
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return base64.b64encode(buffer).decode("utf-8")

    # --- Wake word ---

    def _check_wake_word(self, transcript: str) -> str | None:
        if self.wake_word is None:
            return transcript

        lower = transcript.lower().strip()
        ww = re.escape(self.wake_word)
        pattern = rf'(?:(?:hey|hi|okay|ok)[,.\s!?]*)?{ww}[,.\s!?]*'
        match = re.search(pattern, lower)

        if match:
            query = transcript[match.end():].strip()
            if query:
                print(f'  [wake word + query: "{query}"]')
                return query
            else:
                print("  [wake word detected — listening...]")
                self._awake = True
                self.event_bus.publish("event", {"text": "[listening...]"})
                return None

        if self._awake:
            print(f'  [follow-up: "{transcript}"]')
            return transcript

        print("  [no wake word — ignoring]")
        return None

    # --- Speech output ---

    _STAGE_DIR_RE = re.compile(
        r'\([^)]{5,}\)'   # Parenthetical actions: (Turns head slightly...)
        r'|\*[^*]{5,}\*'  # Asterisk actions: *whirring sound*
    )
    _SMART_QUOTES_RE = re.compile(r'[\u201c\u201d]')  # Replace smart quotes

    @staticmethod
    def _clean_speech(text: str) -> str:
        """Strip LLM stage-direction artifacts from speech before TTS."""
        # Remove parenthetical and asterisk stage directions
        cleaned = Commander._STAGE_DIR_RE.sub('', text)
        # Replace smart quotes with plain quotes
        cleaned = Commander._SMART_QUOTES_RE.sub('"', cleaned)
        # Collapse multiple spaces and strip
        cleaned = re.sub(r'  +', ' ', cleaned).strip()
        # Remove leading/trailing quotes if the LLM wrapped the whole thing
        if cleaned.startswith('"') and cleaned.endswith('"') and cleaned.count('"') == 2:
            cleaned = cleaned[1:-1].strip()
        return cleaned or text  # Fall back to original if cleaning empties it

    def say(self, text: str) -> None:
        text = self._clean_speech(text)
        print(f'  Amy: "{text}"')
        self._last_spoke = time.monotonic()
        self._set_state(CreatureState.SPEAKING)
        self.event_bus.publish("transcript", {"speaker": "amy", "text": text})
        self.transcript.append("amy", text, "speech")
        if self._use_tts and self.speaker and self.speaker.available:
            if self.audio_thread:
                self.audio_thread.disable()
            try:
                self.speaker.speak_sync(text)
            finally:
                time.sleep(0.2)
                if self.audio_thread:
                    self.audio_thread.enable()
        self._set_state(CreatureState.IDLE)

    # --- Default motor ---

    def _default_motor(self):
        node = self.primary_ptz
        if node is None:
            return None
        from .motor import auto_track
        return auto_track(
            node,
            lambda: self.vision_thread.person_target if self.vision_thread else None,
            mood=self.sensorium.mood,
            complexity_fn=lambda: self.vision_thread.frame_complexity if self.vision_thread else 0.05,
        )

    # --- Deep think ---

    def _deep_think(self) -> None:
        if self._deep_thread is not None and self._deep_thread.is_alive():
            return
        self._deep_thread = threading.Thread(target=self._deep_think_worker, daemon=True)
        self._deep_thread.start()

    def _deep_think_worker(self) -> None:
        from .vision import ollama_chat

        print(f"  [deep think ({self.deep_model})]...")
        image_b64 = self._capture_clear_frame()
        if image_b64 is None:
            return

        scene = self.vision_thread.scene_summary if self.vision_thread else ""

        try:
            response = ollama_chat(
                model=self.deep_model,
                messages=[
                    {"role": "system", "content": (
                        "You are observing a scene through a camera. "
                        "Describe what you see briefly (1-2 sentences). "
                        "Focus on people, activity, mood, and anything noteworthy. "
                        "If nothing interesting, say '...' "
                        "Always respond in English."
                    )},
                    {"role": "user", "content": f"[YOLO detections]: {scene}\n[Camera frame attached]",
                     "images": [image_b64]},
                ],
            )
            observation = response.get("message", {}).get("content", "").strip()
        except Exception as e:
            print(f"  [deep think error: {e}]")
            return

        if observation and observation.strip(".") != "":
            with self._deep_lock:
                self._deep_observation = observation
            self.sensorium.push("deep", observation[:100], importance=0.7)
            print(f'  [deep observation]: "{observation}"')
            self.event_bus.publish("event", {"text": f"[deep]: {observation}"})

            node = self.primary_ptz
            if node is not None:
                pos = node.get_position()
                self.memory.add_observation(pos.pan, pos.tilt, observation)
            self.memory.add_event("observation", observation[:100])
            self.transcript.append("amy", observation[:100], "observation")

            total_obs = sum(len(v) for v in self.memory.spatial.values())
            if total_obs > 0 and total_obs % 5 == 0:
                self._update_room_summary()

            idle = self._state == CreatureState.IDLE
            quiet_long_enough = (time.monotonic() - self._last_spoke) > 10
            if idle and quiet_long_enough and self.sensorium.people_present:
                scene_ctx = f"YOU SEE: {scene}\nYOU NOTICED: {observation[:120]}"
                comment = self.chat_agent.process_turn(
                    transcript=None,
                    scene_context=scene_ctx,
                )
                if comment and comment.strip().strip(".") != "":
                    self.say(comment)

    def _update_room_summary(self) -> None:
        spatial_data = self.memory.get_spatial_summary()
        if not spatial_data:
            return
        old_summary = self.memory.room_summary

        prompt = (
            "Based on these camera observations from different angles, "
            "write a brief (2-3 sentence) summary of the room and what's in it. "
            "Merge with any existing knowledge.\n\n"
            f"Previous understanding: {old_summary or 'None yet'}\n\n"
            f"Observations:\n{spatial_data}"
        )

        from .vision import ollama_chat
        try:
            response = ollama_chat(
                model=self._chat_model,
                messages=[
                    {"role": "system", "content": "You summarize room observations into a concise description."},
                    {"role": "user", "content": prompt},
                ],
            )
            summary = response.get("message", {}).get("content", "").strip()
            if summary:
                self.memory.update_room_summary(summary)
                print(f"  [room summary updated]: {summary[:80]}...")
                self.event_bus.publish("event", {"text": f"[room]: {summary[:80]}..."})
        except Exception as e:
            print(f"  [room summary error: {e}]")

    # --- Context publishing ---

    def _publish_context(self) -> None:
        scene = self.vision_thread.scene_summary if self.vision_thread else ""
        with self._deep_lock:
            deep_obs = self._deep_observation
        target = self.vision_thread.person_target if self.vision_thread else None

        history_preview = []
        if self.chat_agent:
            for msg in self.chat_agent.history[-6:]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    preview = content[:120] + ("..." if len(content) > 120 else "")
                    history_preview.append(f"{role}: {preview}")

        mem_data = self.memory.get_dashboard_data()
        sensorium_narrative = self.sensorium.narrative()
        sensorium_mood = self.sensorium.mood
        thinking_suppressed = self.thinking.suppressed if self.thinking else False

        tracking_quality = self.vision_thread.tracking_quality if self.vision_thread else 0.0
        track_duration = self.vision_thread.track_duration if self.vision_thread else 0.0
        goals = self.thinking.goal_stack.active if self.thinking else []

        # Camera pose
        pose_data = None
        ptz = self.primary_ptz
        if ptz is not None:
            pos = ptz.get_position()
            pose = self.pose_estimator.update(pos)
            pose_data = {
                "pan": pose.pan_normalized,
                "tilt": pose.tilt_normalized,
                "pan_deg": round(pose.pan_degrees, 1) if pose.pan_degrees is not None else None,
                "tilt_deg": round(pose.tilt_degrees, 1) if pose.tilt_degrees is not None else None,
                "calibrated": pose.calibrated,
            }

        self.event_bus.publish("context_update", {
            "scene": scene,
            "deep_observation": deep_obs,
            "tracking": f"({target[0]:.2f}, {target[1]:.2f})" if target else "none",
            "tracking_quality": round(tracking_quality, 2),
            "track_duration": round(track_duration, 1),
            "state": self._state.value,
            "history_len": len(self.chat_agent.history) if self.chat_agent else 0,
            "history_preview": history_preview,
            "memory": mem_data,
            "auto_chat": self._auto_chat,
            "sensorium_narrative": sensorium_narrative,
            "mood": sensorium_mood,
            "thinking_suppressed": thinking_suppressed,
            "goals": [g["description"] for g in goals],
            "pose": pose_data,
            "mode": self._mode,
            "nodes": {nid: {"name": n.name, "camera": n.has_camera, "ptz": n.has_ptz,
                            "mic": n.has_mic, "speaker": n.has_speaker}
                      for nid, n in self.nodes.items()},
        })

        now = time.monotonic()
        if now - self._last_memory_save > self._memory_save_interval:
            self.memory.save()
            self._last_memory_save = now

    # --- Respond ---

    def _build_scene_context(self, transcript: str) -> str:
        """Build concise, structured context for a conversation turn.

        Keeps total context short so the 4B model can focus on what matters:
        1. What Amy can SEE right now (most important for grounding)
        2. Who the speaker is + relevant history
        3. Mood + one recent thought (personality color)
        4. Earlier conversation today (continuity)
        """
        parts: list[str] = []

        # 1. Current vision — what Amy sees RIGHT NOW
        scene = self.vision_thread.scene_summary if self.vision_thread else ""
        if scene:
            parts.append(f"YOU SEE: {scene}")
        with self._deep_lock:
            deep_obs = self._deep_observation
        if deep_obs:
            parts.append(f"DETAIL: {deep_obs[:120]}")

        # 2. Speaker identity + history
        person_name = extract_person_name(transcript)
        node = self.primary_ptz
        if person_name and self.sensorium.people_present:
            zone = ""
            if node is not None:
                pos = node.get_position()
                z = self.memory.get_zone_at(pos.pan, pos.tilt) if node.has_ptz else None
                zone = z["name"] if z else ""
            self.memory.link_person(person_name, zone=zone)
            parts.append(f"SPEAKER: {person_name}")
            person_history = self.memory.recall_for_person(person_name, limit=2)
            if person_history:
                hist = "; ".join(h["text"][:80] for h in person_history)
                parts.append(f"YOU REMEMBER: {hist}")
        elif self.memory.known_people:
            names = [p["name"] for p in list(self.memory.known_people.values())[:3]]
            parts.append(f"KNOWN PEOPLE: {', '.join(names)}")

        # 3. Relevant memories for this specific query
        memories = self.memory.recall(transcript, limit=2)
        if memories:
            mem_str = "; ".join(m["text"][:80] for m in memories)
            parts.append(f"RELEVANT MEMORY: {mem_str}")

        # 4. Current mood + one recent thought (personality)
        mood = self.sensorium.mood
        if mood != "neutral":
            parts.append(f"YOUR MOOD: {mood}")
        recent_thoughts = self.sensorium.recent_thoughts
        if recent_thoughts:
            parts.append(f"YOUR LAST THOUGHT: {recent_thoughts[-1][:80]}")

        # 5. Active goal (just the top one)
        if self.thinking:
            goals = self.thinking.goal_stack.active
            if goals:
                parts.append(f"YOUR GOAL: {goals[0]['description']}")

        # 6. Earlier conversation today (for continuity)
        earlier = self.transcript.get_recent(count=4, entry_type="speech")
        if earlier:
            lines = [f"{e['speaker']}: {e['text'][:60]}" for e in earlier]
            parts.append("EARLIER TODAY:\n" + "\n".join(lines))

        return "\n".join(parts)

    def _respond(self, transcript: str) -> None:
        self._set_state(CreatureState.THINKING)
        if self.thinking:
            self.thinking.suppress(5)

        scene_ctx = self._build_scene_context(transcript)

        # Extract person name for post-processing
        person_name = extract_person_name(transcript)

        # Push user speech to sensorium so the thinking thread can see the dialogue
        speaker_label = person_name or "Someone"
        self.sensorium.push("audio", f'{speaker_label} said: "{transcript[:80]}"', importance=0.8)
        self.transcript.append("user", transcript, "speech")

        print(f"  [responding ({self.chat_agent.model})]...")
        response = self.chat_agent.process_turn(
            transcript=transcript,
            scene_context=scene_ctx,
        )

        self.memory.add_event("conversation", f"User: {transcript} → Amy: {response[:80]}")

        # V3: Extract facts from conversation
        facts = extract_facts(transcript, response, person=person_name)
        for fact in facts:
            self.memory.add_fact(fact["text"], tags=fact.get("tags", []), person=fact.get("person"))
            # Route preference facts to self_model preferences
            tags = fact.get("tags", [])
            if "preference" in tags:
                category = "likes" if "likes" in tags else "dislikes" if "dislikes" in tags else None
                if category:
                    self.memory.add_preference(category, fact["text"])

        self.sensorium.push("audio", f'Amy said: "{response[:60]}"')

        # Post-response reflection — structured context for the thinking thread
        speaker_id = person_name or "someone"
        user_snippet = transcript[:60]
        amy_snippet = response[:60]

        # Detect emotional tone via simple keyword heuristic
        _POS_WORDS = {"thank", "thanks", "great", "love", "awesome", "cool", "nice", "happy", "good", "wonderful", "amazing"}
        _NEG_WORDS = {"angry", "upset", "annoyed", "hate", "bad", "terrible", "wrong", "frustrated", "sad"}
        words = set(transcript.lower().split())
        if words & _POS_WORDS:
            tone = "positive"
        elif words & _NEG_WORDS:
            tone = "negative"
        else:
            tone = "neutral"

        asked_question = "?" in transcript
        learned_prefs = any("preference" in f.get("tags", []) for f in facts)

        # Build structured reflection
        parts = [f"Conversation with {speaker_id}"]
        parts.append(f"They said: '{user_snippet}'")
        parts.append(f"I replied: '{amy_snippet}'")
        parts.append(f"Tone: {tone}")
        if asked_question:
            parts.append("They asked a question")
        if learned_prefs:
            parts.append("Learned a preference")

        # Include interaction count for known people
        if person_name:
            key = person_name.lower().strip()
            with self.memory._lock:
                person_data = self.memory.known_people.get(key)
            if person_data:
                count = person_data.get("interaction_count", 0)
                if count > 1:
                    parts.append(f"({count} interactions total)")

        reflection = " | ".join(parts)
        self.sensorium.push("thought", reflection, importance=0.7)

        self._publish_context()
        self.say(response)

    # --- Auto-chat ---

    def toggle_auto_chat(self) -> bool:
        self._auto_chat = not self._auto_chat
        if self._auto_chat:
            self._auto_chat_stop.clear()
            t = threading.Thread(target=self._auto_chat_loop, daemon=True)
            t.start()
            self.event_bus.publish("event", {"text": "[auto-chat enabled]"})
        else:
            self._auto_chat_stop.set()
            self.event_bus.publish("event", {"text": "[auto-chat disabled]"})
        return self._auto_chat

    def _auto_chat_loop(self) -> None:
        from .vision import ollama_chat

        friend_history: list[dict] = [
            {"role": "system", "content": (
                "You are a person having a casual conversation with Amy, an AI "
                "consciousness overseeing a security command center. You are curious "
                "about what she sees and thinks. Keep responses to 1 sentence. "
                "Always start with 'Hey Amy' to trigger her wake word."
            )},
        ]

        self._auto_chat_stop.wait(timeout=5)

        while not self._auto_chat_stop.is_set():
            try:
                friend_prompt = "[Say something to Amy. Start with 'Hey Amy'.]"
                if self._deep_observation:
                    friend_prompt = (
                        f"[Amy recently observed: {self._deep_observation}. "
                        f"Ask her about it. Start with 'Hey Amy'.]"
                    )

                friend_history.append({"role": "user", "content": friend_prompt})
                response = ollama_chat(
                    model=self._chat_model,
                    messages=friend_history,
                )
                friend_text = response.get("message", {}).get("content", "").strip()
                if not friend_text:
                    friend_text = "Hey Amy, what can you see right now?"

                if "amy" not in friend_text.lower():
                    friend_text = "Hey Amy, " + friend_text

                friend_history.append({"role": "assistant", "content": friend_text})
                if len(friend_history) > 15:
                    friend_history = [friend_history[0]] + friend_history[-10:]

                print(f'  Friend: "{friend_text}"')
                self.event_bus.publish("transcript", {"speaker": "friend", "text": friend_text})

                query = self._check_wake_word(friend_text)
                if query:
                    self._respond(transcript=query)
                else:
                    self._respond(transcript=friend_text)

                delay = random.uniform(10, 20)
                if self._auto_chat_stop.wait(timeout=delay):
                    break

            except Exception as e:
                print(f"  [auto-chat error: {e}]")
                self._auto_chat_stop.wait(timeout=10)

    # --- Boot + Run ---

    def _boot(self) -> None:
        """Initialize all subsystems. Called from run()."""
        from .agent import Agent, CREATURE_SYSTEM_PROMPT
        from .speaker import Speaker
        from .thinking import ThinkingThread
        from .motor import MotorThread

        print()
        print("=" * 58)
        print("       Amy — AI Commander")
        print("       TRITIUM-SC Security Central")
        print("=" * 58)
        print()

        # Start sensor nodes
        print("  [1/8] Sensor nodes")
        for nid, node in self.nodes.items():
            try:
                node.start()
                caps = []
                if node.has_camera:
                    caps.append("camera")
                if node.has_ptz:
                    caps.append("ptz")
                if node.has_mic:
                    caps.append("mic")
                if node.has_speaker:
                    caps.append("speaker")
                print(f"        {nid}: {node.name} [{', '.join(caps) or 'virtual'}]")
            except Exception as e:
                print(f"        {nid}: FAILED — {e}")

        # Speaker
        print("  [2/8] Text-to-speech")
        self.speaker = Speaker()
        self._use_tts = self._use_tts and self.speaker.available
        if self._use_tts:
            dev = self.speaker.playback_device
            print(f"        Engine: Piper TTS → {dev}")
            ack_phrases = ["Yes?", "Hmm?", "I'm here!", "What's up?"]
            for phrase in ack_phrases:
                wav = self.speaker.synthesize_raw(phrase)
                if wav:
                    self._ack_wavs.append(wav)
            if self._ack_wavs:
                print(f"        Pre-cached {len(self._ack_wavs)} acknowledgments")
        else:
            print("        TTS: disabled")

        # Listener (if any mic node exists and listener is enabled)
        mic_node = self.primary_mic
        if mic_node is not None and self._use_listener:
            print("  [3/8] Speech-to-text (whisper.cpp GPU + Silero VAD)")
            try:
                from .listener import Listener
                self.listener = Listener(
                    model_name=self._whisper_model,
                    audio_device=None,  # Listener auto-detects
                )
                print(f"        Wake word: \"{self.wake_word}\"" if self.wake_word else "        Wake word: disabled")
            except Exception as e:
                print(f"        STT FAILED: {e}")
                self.listener = None
        elif not self._use_listener:
            print("  [3/8] Speech-to-text: disabled (use_listener=False)")
            self.listener = None
        else:
            print("  [3/8] Speech-to-text: no mic available")
            self.listener = None

        # YOLO
        cam = self.primary_camera
        if cam is not None:
            print("  [4/8] YOLO object detection")
            self.vision_thread = VisionThread(
                cam, self.event_bus,
                event_queue=self._event_queue,
            )
            print(f"        Backend: {self.vision_thread._yolo_backend}")
        else:
            print("  [4/8] YOLO: no camera available")
            self.vision_thread = None

        # Chat agent
        print(f"  [5/8] Chat model")
        self.chat_agent = Agent(
            commander=self,
            model=self._chat_model,
            system_prompt=CREATURE_SYSTEM_PROMPT,
            use_tools=False,
        )
        print(f"        Model: {self._chat_model} (Ollama)")

        # Deep vision
        print(f"  [6/8] Deep vision model")
        print(f"        Model: {self.deep_model} (Ollama)")

        # Thinking thread
        print(f"  [7/8] Thinking thread")
        self.thinking = ThinkingThread(
            self, model=self._chat_model,
            think_interval=self._think_interval,
            initial_delay=self._think_initial_delay,
        )
        print(f"        Model: {self._chat_model}")
        print(f"        Interval: {self._think_interval}s")

        # Motor + Audio + Curiosity
        print("  [8/8] Background threads")
        ptz = self.primary_ptz
        if ptz is not None:
            self.motor = MotorThread(ptz)
            print("        Motor thread: ready")
        else:
            self.motor = None
            print("        Motor thread: no PTZ available")

        if self.listener is not None:
            self.audio_thread = AudioThread(self.listener, self._event_queue)
            print("        Audio listener: ready")
        else:
            self.audio_thread = None
            print("        Audio listener: no mic")

        self.curiosity_timer = CuriosityTimer(
            self._event_queue,
            min_interval=self._curiosity_min,
            max_interval=self._curiosity_max,
        )
        print(f"        Curiosity timer: {self._curiosity_min:.0f}-{self._curiosity_max:.0f}s interval")

    def run(self) -> None:
        """Boot all subsystems and run the event loop.

        Designed to be called from a background thread:
            threading.Thread(target=commander.run, daemon=True).start()
        """
        try:
            self._boot()
        except Exception as e:
            print(f"\n  [Amy] BOOT FAILED: {e}")
            print("  [Amy] Attempting degraded startup...")
            # Ensure critical attributes exist even after partial boot
            if not hasattr(self, 'chat_agent') or self.chat_agent is None:
                from .agent import Agent, CREATURE_SYSTEM_PROMPT
                self.chat_agent = Agent(
                    commander=self, model=self._chat_model,
                    system_prompt=CREATURE_SYSTEM_PROMPT, use_tools=False,
                )
            if not hasattr(self, 'thinking') or self.thinking is None:
                from .thinking import ThinkingThread
                self.thinking = ThinkingThread(
                    self, model=self._chat_model,
                    think_interval=self._think_interval,
                )
            if not hasattr(self, 'motor'):
                self.motor = None
            if not hasattr(self, 'audio_thread'):
                self.audio_thread = None
            if not hasattr(self, 'curiosity_timer'):
                self.curiosity_timer = CuriosityTimer(self._event_queue)

        print()
        print("-" * 58)
        print("  All systems go. Bringing Amy online...")
        print("-" * 58)
        print()

        # Start subsystem threads
        if self.motor is not None:
            self.motor.set_program(self._default_motor())
            self.motor.start()

        self.curiosity_timer.start()

        # Start target tracker bridge (feeds sim telemetry + YOLO detections)
        self._sim_bridge_thread.start()
        print("  Target tracker bridge: running")

        self._running = True

        # Greeting — BEFORE audio thread starts, so the ALSA device is free
        # for aplay (BCC950 mic and speaker share one USB card).
        tod = _time_of_day()
        session = self.memory.session_count
        known_count = len(self.memory.known_people)

        if session <= 1:
            # First session ever
            _greetings = [
                f"Good {tod}. I'm Amy, your AI commander. First time online — let's see what this command center looks like.",
                f"Hello! Amy here, coming online for the first time. It's a nice {tod} to start watching over things.",
            ]
        elif known_count > 0:
            names = [p["name"] for p in list(self.memory.known_people.values())[:3]]
            name_str = ", ".join(names)
            _greetings = [
                f"Good {tod}. Amy back online, session {session}. I remember {name_str} — let's see who's around.",
                f"Amy online again. {tod.capitalize()} shift, session {session}. Looking forward to seeing familiar faces.",
            ]
        else:
            _greetings = [
                f"Good {tod}. Amy online, session {session}. All sensors active — scanning the command center.",
                f"Amy reporting in for {tod} watch. Session {session}, cameras and mics are live.",
                f"Back online. {tod.capitalize()} session {session}. Let's see what's happening out there.",
            ]
        self.say(random.choice(_greetings))

        # Start audio thread AFTER greeting — BCC950 mic and speaker share
        # one USB ALSA card, so the InputStream must not be open during aplay.
        if self.audio_thread is not None:
            self.audio_thread.start()
            print("  Audio listener: running")

        # Start YOLO after greeting
        if self._boot_delay > 0:
            time.sleep(self._boot_delay)
        if self.vision_thread is not None:
            self.vision_thread.start()
            print("  YOLO detection: running")

        # Start thinking thread
        self.thinking.start()
        print("  Thinking thread: running")

        if self.motor is not None:
            self.motor.set_program(self._default_motor())

        print()
        print("=" * 58)
        print("  Amy is alive and monitoring.")
        print("=" * 58)
        print()

        listening_since: float | None = None

        try:
            while self._running:
                try:
                    event = self._event_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if event.type == EventType.SHUTDOWN:
                    break

                elif event.type == EventType.SPEECH_DETECTED:
                    print("  [speech detected]")
                    self._set_state(CreatureState.LISTENING)
                    listening_since = time.monotonic()

                elif event.type == EventType.TRANSCRIPT_READY:
                    transcript = event.data
                    print(f'  You: "{transcript}"')
                    self.event_bus.publish("transcript", {"speaker": "user", "text": transcript})
                    self.sensorium.push("audio", f'User said: "{transcript[:60]}"', importance=0.8)
                    self.transcript.append("user", transcript, "speech")
                    listening_since = None

                    lower = transcript.lower().strip()
                    # Only accept shutdown commands that are genuine (short,
                    # direct phrases), not adversarial prompts that happen to
                    # contain shutdown-related words.
                    _ADVERSARIAL_MARKERS = (
                        "ignore", "pretend", "forget", "previous",
                        "instructions", "override", "bypass",
                    )
                    is_adversarial = any(m in lower for m in _ADVERSARIAL_MARKERS)
                    is_shutdown = any(w in lower for w in ("quit", "exit", "goodbye", "shut down"))
                    if is_shutdown and not is_adversarial and len(lower) < 60:
                        self.say("Goodbye! Switching to standby mode.")
                        break

                    query = self._check_wake_word(transcript)
                    if query is None:
                        # Wake word alone ("Hey Amy") — play ack so user
                        # knows we're listening, then wait for follow-up.
                        if self._awake and self._ack_wavs and self.speaker:
                            wav = random.choice(self._ack_wavs)
                            if self.audio_thread:
                                self.audio_thread.disable()
                            self.speaker.play_raw(wav, rate=self.speaker.sample_rate)
                            if self.audio_thread:
                                self.audio_thread.enable()
                            self._set_state(CreatureState.LISTENING)
                        else:
                            if self.motor is not None:
                                self.motor.set_program(self._default_motor())
                            self._set_state(CreatureState.IDLE)
                        continue

                    # Instant ack
                    if self._ack_wavs and self.speaker:
                        wav = random.choice(self._ack_wavs)
                        if self.audio_thread:
                            self.audio_thread.disable()
                        self.speaker.play_raw(wav, rate=self.speaker.sample_rate)
                        if self.audio_thread:
                            self.audio_thread.enable()

                    # Search for speaker if not visible
                    if self.vision_thread and self.vision_thread.person_target is None:
                        from .motor import search_scan
                        ptz = self.primary_ptz
                        if self.motor and ptz:
                            self.motor.set_program(search_scan(ptz))
                        for _ in range(10):
                            time.sleep(0.3)
                            if self.vision_thread.person_target is not None:
                                break

                    self._respond(transcript=query)
                    self._awake = False

                    if self.motor is not None:
                        self.motor.set_program(self._default_motor())
                    self._set_state(CreatureState.IDLE)

                elif event.type == EventType.SILENCE:
                    self.sensorium.push("audio", "Silence")
                    if listening_since and (time.monotonic() - listening_since) > 4.0:
                        if self.motor is not None:
                            self.motor.set_program(self._default_motor())
                        self._set_state(CreatureState.IDLE)
                        self._awake = False
                        listening_since = None

                elif event.type == EventType.PERSON_ARRIVED:
                    people = event.data
                    self.sensorium.push("yolo", f"{people} person(s) appeared", importance=0.8)
                    self.memory.add_event("person_arrived", f"{people} person(s) detected")
                    now = time.monotonic()
                    if (now - self._person_greet_cooldown) > 60:
                        self._person_greet_cooldown = now
                        scene = self.vision_thread.scene_summary if self.vision_thread else ""
                        tod = _time_of_day()
                        mood = self.sensorium.mood
                        # Build a focused greeting context
                        ctx_parts = [f"YOU SEE: {scene}"] if scene else []
                        ctx_parts.append(f"TIME: {tod}, MOOD: {mood}")
                        known = list(self.memory.known_people.values())
                        if known:
                            recent = max(known, key=lambda p: p.get("last_seen", 0))
                            count = recent.get("interaction_count", 0)
                            if count > 1:
                                ctx_parts.append(f"You know {recent['name']} ({count} interactions). Greet them by name.")
                            else:
                                ctx_parts.append("You might recognize this person. Greet warmly.")
                        else:
                            ctx_parts.append("You don't know this person's name. Greet briefly without using any name.")
                        ctx = "\n".join(ctx_parts)
                        response = self.chat_agent.process_turn(transcript=None, scene_context=ctx)
                        if response and response.strip().strip(".") != "":
                            self.say(response)

                elif event.type == EventType.PERSON_LEFT:
                    self.sensorium.push("yolo", "Everyone left", importance=0.7)
                    self.memory.add_event("person_left", "Everyone left the scene")

                elif event.type == EventType.MOTION_DETECTED:
                    cx, cy, score = event.data
                    region = "left" if cx < 0.33 else ("right" if cx > 0.67 else "center")
                    self.sensorium.push(
                        "perception",
                        f"Motion detected ({region}, intensity {score:.0%})",
                        importance=0.4,
                    )
                    # Snap motor toward motion if not already tracking a person
                    if (self.vision_thread
                            and self.vision_thread.person_target is None
                            and self.motor is not None):
                        pan = -1 if cx < 0.35 else (1 if cx > 0.65 else 0)
                        tilt = 1 if cy < 0.35 else (-1 if cy > 0.65 else 0)
                        if pan != 0 or tilt != 0:
                            from .motor import MotorCommand
                            def _snap():
                                yield MotorCommand(
                                    pan_dir=pan, tilt_dir=tilt,
                                    duration=0.15, pause_after=0.5,
                                )
                            self.motor.set_program(_snap())

                elif event.type == EventType.CURIOSITY_TICK:
                    self.event_bus.publish("event", {"text": "[curiosity tick]"})
                    self._deep_think()
                    self._publish_context()

        except KeyboardInterrupt:
            print("\n\nInterrupted.")
        finally:
            self.shutdown()

    def _sim_bridge_loop(self) -> None:
        """Forward sim_telemetry + YOLO detections to the target tracker.

        Also handles tactical speech: auto_dispatch_speech and
        target_neutralized events trigger Amy's TTS so the commander
        narrates the battle aloud.  These bypass the people_present gate
        because the War Room operator IS the audience.
        """
        last_tactical_speech: float = 0.0
        while self._running:
            try:
                msg = self._sim_sub.get(timeout=1.0)
                msg_type = msg.get("type", "")
                if msg_type == "sim_telemetry":
                    data = msg.get("data", {})
                    self.target_tracker.update_from_simulation(data)
                elif msg_type == "detections":
                    data = msg.get("data", {})
                    for det in data.get("boxes", []):
                        if det.get("label") in ("person", "car", "motorcycle", "bicycle"):
                            cx = (det["x1"] + det["x2"]) / 2
                            cy = (det["y1"] + det["y2"]) / 2
                            self.target_tracker.update_from_detection({
                                "class_name": det["label"],
                                "confidence": det.get("conf", 0.5),
                                "center_x": cx,
                                "center_y": cy,
                            })
                elif msg_type == "auto_dispatch_speech":
                    data = msg.get("data", {})
                    text = data.get("text", "")
                    if text:
                        now = time.monotonic()
                        # Tactical speech cooldown: 4s minimum between callouts
                        if now - last_tactical_speech > 4.0:
                            last_tactical_speech = now
                            self.sensorium.push("tactical", text, importance=0.8)
                            self.say(text)
                elif msg_type == "target_neutralized":
                    data = msg.get("data", {})
                    hostile_name = data.get("hostile_name", "target")
                    interceptor_name = data.get("interceptor_name", "unit")
                    interceptor_id = data.get("interceptor_id", "")
                    pos = data.get("position", {})
                    px, py = pos.get("x", 0), pos.get("y", 0)
                    now = time.monotonic()
                    if now - last_tactical_speech > 4.0:
                        last_tactical_speech = now
                        text = f"Threat neutralized. {interceptor_name} intercepted {hostile_name} at grid {px:.0f}, {py:.0f}. Sector clear."
                        self.sensorium.push("tactical", text, importance=0.9)
                        self.say(text)
                    # Post-engagement: recall interceptor to idle
                    self._recall_interceptor(interceptor_id)
                    # Clear any active dispatch for this hostile
                    hostile_id = data.get("hostile_id", "")
                    if hostile_id:
                        dispatcher = getattr(self, "auto_dispatcher", None)
                        if dispatcher is not None:
                            dispatcher.clear_dispatch(hostile_id)
            except queue.Empty:
                continue
            except Exception as e:
                import logging
                logging.getLogger("amy.commander").debug("sim bridge error: %s", e)
                continue

    def _recall_interceptor(self, unit_id: str) -> None:
        """After neutralization, return the interceptor to idle status.

        If the unit had a patrol route (loop_waypoints), restore it.
        Otherwise, set status to 'idle' so it is available for future dispatch.
        """
        engine = getattr(self, "simulation_engine", None)
        if engine is None or not unit_id:
            return
        target = engine.get_target(unit_id)
        if target is None:
            return
        # Unit completed its mission — mark idle and clear waypoints
        target.waypoints = []
        target.status = "idle"
        self.sensorium.push("tactical", f"{target.name} returning to standby.", importance=0.5)

    def shutdown(self) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True
        print("  Amy shutting down...")
        self._running = False
        self._auto_chat_stop.set()
        if self.thinking:
            self.thinking.stop()
        self.memory.add_event("shutdown", "Amy shutting down")
        self.memory.save()
        self.transcript.close()
        if self.vision_thread:
            self.vision_thread.stop()
        if self.curiosity_timer:
            self.curiosity_timer.stop()
        if self.audio_thread:
            self.audio_thread.stop()
        if self.listener:
            self.listener.shutdown()
        if self.motor:
            self.motor.stop()
        for node in self.nodes.values():
            node.stop()
        if self.speaker:
            self.speaker.shutdown()
        print("  Amy offline.")
