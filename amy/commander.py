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
from typing import TYPE_CHECKING

import cv2
import numpy as np

from .nodes.base import SensorNode, Position
from .sensorium import Sensorium
from .memory import Memory

if TYPE_CHECKING:
    pass


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
# EventBus — thread-safe pub/sub (matches web.py's EventBus)
# ---------------------------------------------------------------------------

class EventBus:
    """Simple thread-safe pub/sub for pushing events to subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def publish(self, event_type: str, data: dict | None = None) -> None:
        msg = {"type": event_type}
        if data is not None:
            msg["data"] = data
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass


# ---------------------------------------------------------------------------
# Audio thread
# ---------------------------------------------------------------------------

class AudioThread:
    """Continuous audio recording in a background thread."""

    def __init__(self, listener, event_queue: queue.Queue, chunk_duration: float = 4.0):
        self.listener = listener
        self.queue = event_queue
        self.chunk_duration = chunk_duration
        self._enabled = threading.Event()
        self._enabled.set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def disable(self) -> None:
        self._enabled.clear()

    def enable(self) -> None:
        self._enabled.set()

    def stop(self) -> None:
        self._stop.set()
        self._enabled.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._enabled.wait()
            if self._stop.is_set():
                break
            try:
                audio = self.listener.record(self.chunk_duration)
            except Exception as e:
                print(f"  [audio error: {e}]")
                self._stop.wait(timeout=2)
                continue
            if self.listener.is_silence(audio):
                self.queue.put(Event(EventType.SILENCE))
                continue
            self.queue.put(Event(EventType.SPEECH_DETECTED))
            text = self.listener.transcribe(audio)
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
        self._latest_detections: list[dict] = []
        self._detection_lock = threading.Lock()
        self._person_target: tuple[float, float] | None = None
        self._target_lock = threading.Lock()

        from ultralytics import YOLO
        import torch
        engine_path = model_name.replace(".pt", ".engine")
        onnx_path = model_name.replace(".pt", ".onnx")
        if os.path.exists(engine_path):
            self._model = YOLO(engine_path, task="detect")
            self._yolo_backend = "TensorRT"
        elif torch.cuda.is_available():
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

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
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
                self._detect(self._model, frame)
            self._stop.wait(timeout=self._interval)

    def _detect(self, model, frame: np.ndarray) -> None:
        results = model(frame, verbose=False, conf=0.4)

        if not results or len(results[0].boxes) == 0:
            with self._scene_lock:
                self._scene_summary = "Scene is empty — nothing detected."
            with self._detection_lock:
                self._latest_detections = []
            with self._target_lock:
                self._person_target = None
            if self._prev_people_count > 0:
                self._empty_frames += 1
                if self._empty_frames >= 3:
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

        if person_centroids:
            best = max(person_centroids, key=lambda p: p[2])
            with self._target_lock:
                self._person_target = (best[0], best[1])
        else:
            with self._target_lock:
                self._person_target = None

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
        if people != self._prev_people_count:
            if people > self._prev_people_count:
                self._event_bus.publish("event", {
                    "text": f"[YOLO: {people} person(s) detected]",
                })
                if self._event_queue is not None:
                    self._event_queue.put(Event(EventType.PERSON_ARRIVED, data=people))
            elif people == 0:
                self._event_bus.publish("event", {"text": "[everyone left]"})
                if self._event_queue is not None:
                    self._event_queue.put(Event(EventType.PERSON_LEFT))
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
        self.memory = Memory()
        self._memory_save_interval = 60
        self._last_memory_save: float = 0.0

        # Sensorium
        self.sensorium = Sensorium()

        # Deep model config
        self.deep_model = deep_model
        self._deep_observation: str = ""
        self._deep_lock = threading.Lock()

        # Store config for deferred init
        self._chat_model = chat_model
        self._whisper_model = whisper_model
        self._use_tts = use_tts
        self._think_interval = think_interval

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
            cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(frame, text, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        return frame

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

    def say(self, text: str) -> None:
        print(f'  Amy: "{text}"')
        self._last_spoke = time.monotonic()
        self._set_state(CreatureState.SPEAKING)
        self.event_bus.publish("transcript", {"speaker": "amy", "text": text})
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
        return auto_track(node, lambda: self.vision_thread.person_target if self.vision_thread else None)

    # --- Deep think ---

    def _deep_think(self) -> None:
        if hasattr(self, '_deep_thread') and self._deep_thread.is_alive():
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
                        "If nothing interesting, say '...'"
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

            total_obs = sum(len(v) for v in self.memory.spatial.values())
            if total_obs > 0 and total_obs % 5 == 0:
                self._update_room_summary()

            idle = self._state == CreatureState.IDLE
            quiet_long_enough = (time.monotonic() - self._last_spoke) > 10
            if idle and quiet_long_enough:
                scene_ctx = f"{scene}\n[You just noticed]: {observation}"
                scene_ctx += "\n[Share a brief, natural observation about what you see. 1 sentence max.]"
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

        self.event_bus.publish("context_update", {
            "scene": scene,
            "deep_observation": deep_obs,
            "tracking": f"({target[0]:.2f}, {target[1]:.2f})" if target else "none",
            "state": self._state.value,
            "history_len": len(self.chat_agent.history) if self.chat_agent else 0,
            "history_preview": history_preview,
            "memory": mem_data,
            "auto_chat": self._auto_chat,
            "sensorium_narrative": sensorium_narrative,
            "mood": sensorium_mood,
            "thinking_suppressed": thinking_suppressed,
            "nodes": {nid: {"name": n.name, "camera": n.has_camera, "ptz": n.has_ptz,
                            "mic": n.has_mic, "speaker": n.has_speaker}
                      for nid, n in self.nodes.items()},
        })

        now = time.monotonic()
        if now - self._last_memory_save > self._memory_save_interval:
            self.memory.save()
            self._last_memory_save = now

    # --- Respond ---

    def _respond(self, transcript: str) -> None:
        self._set_state(CreatureState.THINKING)
        if self.thinking:
            self.thinking.suppress(15)

        scene = self.vision_thread.scene_summary if self.vision_thread else ""
        with self._deep_lock:
            deep_obs = self._deep_observation

        scene_ctx = scene
        if deep_obs:
            scene_ctx += f"\n[Recent observation]: {deep_obs}"

        narrative = self.sensorium.narrative()
        if narrative and narrative != "No recent observations.":
            scene_ctx += f"\n[Recent awareness]:\n{narrative}"

        node = self.primary_ptz
        if node is not None:
            pos = node.get_position()
            mem_ctx = self.memory.build_context(pan=pos.pan, tilt=pos.tilt)
        else:
            mem_ctx = self.memory.build_context()
        if mem_ctx:
            scene_ctx += f"\n{mem_ctx}"

        print(f"  [responding ({self.chat_agent.model})]...")
        response = self.chat_agent.process_turn(
            transcript=transcript,
            scene_context=scene_ctx,
        )

        self.memory.add_event("conversation", f"User: {transcript} → Amy: {response[:80]}")
        self.sensorium.push("audio", f'Amy said: "{response[:60]}"')
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
            print("        Engine: Piper TTS")
            ack_phrases = ["Yes?", "Hmm?", "I'm here!", "What's up?"]
            for phrase in ack_phrases:
                wav = self.speaker.synthesize_raw(phrase)
                if wav:
                    self._ack_wavs.append(wav)
            if self._ack_wavs:
                print(f"        Pre-cached {len(self._ack_wavs)} acknowledgments")
        else:
            print("        TTS: disabled")

        # Listener (if any mic node exists)
        mic_node = self.primary_mic
        if mic_node is not None:
            print("  [3/8] Speech-to-text")
            from .listener import Listener
            self.listener = Listener(
                model_name=self._whisper_model,
                audio_device=None,  # Listener auto-detects
            )
            _warmup = np.zeros(16000, dtype=np.float32)
            self.listener.transcribe(_warmup)
            print(f"        Model: Whisper {self._whisper_model}")
            print(f"        Wake word: \"{self.wake_word}\"" if self.wake_word else "        Wake word: disabled")
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

        self.curiosity_timer = CuriosityTimer(self._event_queue)
        print("        Curiosity timer: 45-90s interval")

    def run(self) -> None:
        """Boot all subsystems and run the event loop.

        Designed to be called from a background thread:
            threading.Thread(target=commander.run, daemon=True).start()
        """
        self._boot()

        print()
        print("-" * 58)
        print("  All systems go. Bringing Amy online...")
        print("-" * 58)
        print()

        # Start subsystem threads
        if self.motor is not None:
            self.motor.set_program(self._default_motor())
            self.motor.start()

        if self.audio_thread is not None:
            self.audio_thread.start()

        self.curiosity_timer.start()
        self._running = True

        # Greeting
        self.say("Hello! I'm Amy, your AI commander. I'm online and watching over the command center.")

        # Start YOLO after greeting
        time.sleep(3)
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
                    listening_since = None

                    lower = transcript.lower().strip()
                    if any(w in lower for w in ("quit", "exit", "goodbye", "shut down")):
                        self.say("Goodbye! Switching to standby mode.")
                        break

                    query = self._check_wake_word(transcript)
                    if query is None:
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
                        with self._deep_lock:
                            deep_obs = self._deep_observation
                        ctx = scene
                        if deep_obs:
                            ctx += f"\n[Recent observation]: {deep_obs}"
                        ctx += "\n[A person just appeared. Greet them warmly but briefly.]"
                        response = self.chat_agent.process_turn(transcript=None, scene_context=ctx)
                        if response and response.strip().strip(".") != "":
                            self.say(response)

                elif event.type == EventType.PERSON_LEFT:
                    self.sensorium.push("yolo", "Everyone left", importance=0.7)
                    self.memory.add_event("person_left", "Everyone left the scene")

                elif event.type == EventType.CURIOSITY_TICK:
                    self.event_bus.publish("event", {"text": "[curiosity tick]"})
                    self._deep_think()
                    self._publish_context()

        except KeyboardInterrupt:
            print("\n\nInterrupted.")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        print("  Amy shutting down...")
        self._running = False
        self._auto_chat_stop.set()
        if self.thinking:
            self.thinking.stop()
        self.memory.add_event("shutdown", "Amy shutting down")
        self.memory.save()
        if self.vision_thread:
            self.vision_thread.stop()
        if self.curiosity_timer:
            self.curiosity_timer.stop()
        if self.audio_thread:
            self.audio_thread.stop()
        if self.motor:
            self.motor.stop()
        for node in self.nodes.values():
            node.stop()
        if self.speaker:
            self.speaker.shutdown()
        print("  Amy offline.")
