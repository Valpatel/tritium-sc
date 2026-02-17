"""SyntheticSensorNode — a virtual sensor node driven by scenario timelines."""

from __future__ import annotations

import threading
import time
from typing import Any

import cv2
import numpy as np

from amy.nodes.base import SensorNode, Position
from .schema import Scenario, ScenarioEvent, EventKind, Position2D


class WorldClock:
    """Time source with configurable scale factor.

    time_scale < 1.0 runs faster than real time.
    time_scale = 1.0 is real time.
    """

    def __init__(self, time_scale: float = 1.0):
        self.time_scale = time_scale
        self._start: float = 0.0
        self._running = False

    def start(self) -> None:
        self._start = time.monotonic()
        self._running = True

    @property
    def elapsed(self) -> float:
        """Scenario time elapsed (scaled)."""
        if not self._running:
            return 0.0
        real_elapsed = time.monotonic() - self._start
        return real_elapsed / self.time_scale if self.time_scale > 0 else real_elapsed

    def real_delay(self, scenario_seconds: float) -> float:
        """Convert scenario seconds to real seconds for sleeping."""
        return scenario_seconds * self.time_scale


class WorldState:
    """Tracks current positions and states of all entities."""

    def __init__(self):
        self._lock = threading.Lock()
        self._people: dict[str, dict] = {}  # person_id -> {position, height_ratio, color, visible}
        self._objects: dict[str, dict] = {}
        self._current_speech: str | None = None
        self._speech_lock = threading.Lock()

    def add_person(
        self,
        person_id: str,
        position: Position2D,
        height_ratio: float = 0.6,
        color: tuple[int, int, int] = (60, 60, 180),
    ) -> None:
        with self._lock:
            self._people[person_id] = {
                "position": position,
                "height_ratio": height_ratio,
                "color": color,
                "visible": True,
            }

    def remove_person(self, person_id: str) -> None:
        with self._lock:
            if person_id in self._people:
                self._people[person_id]["visible"] = False

    def move_person(self, person_id: str, position: Position2D) -> None:
        with self._lock:
            if person_id in self._people:
                self._people[person_id]["position"] = position

    def set_speech(self, text: str | None) -> None:
        with self._speech_lock:
            self._current_speech = text

    def get_speech(self) -> str | None:
        with self._speech_lock:
            text = self._current_speech
            self._current_speech = None  # Consume
            return text

    def get_visible_people(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "position": p["position"],
                    "height_ratio": p["height_ratio"],
                    "color": p["color"],
                }
                for p in self._people.values()
                if p["visible"]
            ]

    def snapshot(self) -> dict:
        """Get current world state for frame generation."""
        return {
            "people": self.get_visible_people(),
            "timestamp": time.monotonic(),
        }


class SyntheticSensorNode(SensorNode):
    """Virtual sensor node driven by scenario timeline.

    Implements full SensorNode interface using FrameGenerator + AudioGenerator
    to produce synthetic camera frames and audio from scenario events.
    """

    def __init__(
        self,
        scenario: Scenario,
        node_id: str = "synthetic",
        name: str = "Synthetic Node",
        width: int = 320,
        height: int = 240,
    ):
        super().__init__(node_id, name)
        self._scenario = scenario
        self._width = width
        self._height = height

        # World simulation
        self.clock = WorldClock(scenario.time_scale)
        self.world = WorldState()

        # Frame state
        self._frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._frame_counter: int = 0

        # Audio state
        self._audio_buffer: np.ndarray | None = None
        self._audio_lock = threading.Lock()

        # PTZ simulation
        self._position = Position(
            pan=0.0,
            tilt=0.0,
            zoom=100.0,
            pan_min=-170.0,
            pan_max=170.0,
            tilt_min=-30.0,
            tilt_max=30.0,
        )
        self._ptz_lock = threading.Lock()

        # Speech capture (what Amy says)
        self._played_audio: list[tuple[bytes, int]] = []

        # Timeline processing
        self._timeline_thread: threading.Thread | None = None
        self._frame_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._finished = threading.Event()

        # Transcript injection queue (for when TTS/Whisper unavailable)
        self._transcript_queue: list[tuple[float, str]] = []
        self._transcript_lock = threading.Lock()

        # Ambient/object observation queue (pushed to sensorium by runner)
        self._ambient_queue: list[tuple[float, str]] = []

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

    def get_frame(self) -> np.ndarray | None:
        with self._frame_lock:
            if self._frame is not None:
                self._frame_counter += 1
                return self._frame.copy()
            return None

    def get_jpeg(self) -> bytes | None:
        frame = self.get_frame()
        if frame is None:
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes()

    @property
    def frame_id(self) -> int:
        return self._frame_counter

    def move(self, pan_dir: int, tilt_dir: int, duration: float) -> tuple[bool, bool]:
        with self._ptz_lock:
            pan_moved = False
            tilt_moved = False

            if pan_dir != 0:
                new_pan = self._position.pan + pan_dir * duration * 50
                if self._position.pan_min is not None:
                    new_pan = max(new_pan, self._position.pan_min)
                if self._position.pan_max is not None:
                    new_pan = min(new_pan, self._position.pan_max)
                if new_pan != self._position.pan:
                    self._position.pan = new_pan
                    pan_moved = True

            if tilt_dir != 0:
                new_tilt = self._position.tilt + tilt_dir * duration * 50
                if self._position.tilt_min is not None:
                    new_tilt = max(new_tilt, self._position.tilt_min)
                if self._position.tilt_max is not None:
                    new_tilt = min(new_tilt, self._position.tilt_max)
                if new_tilt != self._position.tilt:
                    self._position.tilt = new_tilt
                    tilt_moved = True

            return (pan_moved, tilt_moved)

    def get_position(self) -> Position:
        with self._ptz_lock:
            return Position(
                pan=self._position.pan,
                tilt=self._position.tilt,
                zoom=self._position.zoom,
                pan_min=self._position.pan_min,
                pan_max=self._position.pan_max,
                tilt_min=self._position.tilt_min,
                tilt_max=self._position.tilt_max,
            )

    def reset_position(self) -> None:
        with self._ptz_lock:
            self._position.pan = 0.0
            self._position.tilt = 0.0

    def record_audio(self, duration: float) -> np.ndarray | None:
        """Return current audio chunk. If speech is queued, mix it in."""
        from .audio_gen import AudioGenerator

        gen = AudioGenerator()
        ambient = gen.generate_ambient(self._scenario.ambient_type, duration)

        speech_text = self.world.get_speech()
        if speech_text:
            speech_audio = gen.generate_speech(speech_text)
            audio = gen.mix_audio(ambient, speech_audio, levels=[0.3, 0.7])
        else:
            audio = ambient

        return audio

    def play_audio(self, raw_pcm: bytes, sample_rate: int = 22050) -> None:
        self._played_audio.append((raw_pcm, sample_rate))

    @property
    def played_audio(self) -> list[tuple[bytes, int]]:
        return list(self._played_audio)

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def get_pending_transcripts(self) -> list[str]:
        """Get transcript texts injected by PERSON_SPEAK events (for transcript injection mode)."""
        with self._transcript_lock:
            now = self.clock.elapsed
            ready = [text for t, text in self._transcript_queue if t <= now]
            self._transcript_queue = [(t, text) for t, text in self._transcript_queue if t > now]
            return ready

    def get_pending_ambient(self) -> list[str]:
        """Get ambient/object observation texts ready for the sensorium."""
        with self._transcript_lock:
            now = self.clock.elapsed
            ready = [text for t, text in self._ambient_queue if t <= now]
            self._ambient_queue = [(t, text) for t, text in self._ambient_queue if t > now]
            return ready

    def start(self) -> None:
        """Start timeline processing and frame generation."""
        # Initialize people from scenario config
        for person in self._scenario.people:
            pass  # People enter via PERSON_ENTER events

        self.clock.start()

        self._timeline_thread = threading.Thread(target=self._timeline_loop, daemon=True)
        self._timeline_thread.start()

        self._frame_thread = threading.Thread(target=self._frame_loop, daemon=True)
        self._frame_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._timeline_thread:
            self._timeline_thread.join(timeout=3)
        if self._frame_thread:
            self._frame_thread.join(timeout=3)

    def _timeline_loop(self) -> None:
        """Process scenario events in order."""
        events = sorted(self._scenario.events, key=lambda e: e.time)
        event_idx = 0

        while not self._stop.is_set() and event_idx < len(events):
            elapsed = self.clock.elapsed

            # Process all events that should have fired by now
            while event_idx < len(events) and events[event_idx].time <= elapsed:
                self._process_event(events[event_idx])
                event_idx += 1

            if event_idx >= len(events):
                break

            # Sleep until next event (in real time)
            next_time = events[event_idx].time
            wait_real = self.clock.real_delay(next_time - elapsed)
            self._stop.wait(timeout=max(0.01, wait_real))

        # Wait for scenario duration to complete
        while not self._stop.is_set():
            if self.clock.elapsed >= self._scenario.duration:
                break
            self._stop.wait(timeout=0.1)

        self._finished.set()

    def _process_event(self, event: ScenarioEvent) -> None:
        """Handle a single scenario event."""
        if event.kind == EventKind.PERSON_ENTER:
            # Find person config
            person_cfg = None
            for p in self._scenario.people:
                if p.person_id == event.person_id:
                    person_cfg = p
                    break
            height = person_cfg.height_ratio if person_cfg else 0.6
            color = person_cfg.color if person_cfg else (60, 60, 180)
            self.world.add_person(
                event.person_id or "unknown",
                event.position,
                height_ratio=height,
                color=color,
            )

        elif event.kind == EventKind.PERSON_EXIT:
            self.world.remove_person(event.person_id or "unknown")

        elif event.kind == EventKind.PERSON_MOVE:
            self.world.move_person(event.person_id or "unknown", event.position)

        elif event.kind == EventKind.PERSON_SPEAK:
            if event.text:
                self.world.set_speech(event.text)
                # Also queue for transcript injection
                with self._transcript_lock:
                    self._transcript_queue.append((self.clock.elapsed, event.text))

        elif event.kind in (EventKind.AMBIENT_CHANGE, EventKind.OBJECT_APPEAR,
                             EventKind.OBJECT_REMOVE):
            # Push environmental observations for the thinking thread to notice
            if event.text:
                with self._transcript_lock:
                    self._ambient_queue.append((self.clock.elapsed, event.text))

        elif event.kind == EventKind.WAIT:
            pass  # Just a timeline marker

    def _frame_loop(self) -> None:
        """Generate frames at ~10fps."""
        from .frame_gen import FrameGenerator

        gen = FrameGenerator(self._width, self._height)

        while not self._stop.is_set() and not self._finished.is_set():
            state = self.world.snapshot()
            frame = gen.generate_frame(state)

            with self._frame_lock:
                self._frame = frame

            self._stop.wait(timeout=0.1)  # ~10fps
