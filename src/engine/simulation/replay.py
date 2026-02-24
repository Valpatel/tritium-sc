"""ReplayRecorder -- captures game tick history for post-wave analysis.

Architecture
------------
ReplayRecorder sits alongside the simulation engine and records two streams
of data:

  1. **Snapshots** (position frames): Called by the engine tick loop at a
     throttled 2Hz rate.  Each snapshot captures every target's position,
     heading, health, fsm_state, alliance, asset_type, and status.  This
     is the data needed to replay unit movement and draw heat maps.

  2. **Events** (combat + wave): Subscribed via EventBus listener thread.
     Records projectile_fired, projectile_hit, target_eliminated,
     wave_start, wave_complete, and game_over events with timestamps.
     These form the event timeline for post-game analysis.

Memory is bounded at MAX_FRAMES (3000 = ~25 min at 2Hz).  When the cap is
reached, the oldest frames are dropped (ring buffer behavior via deque).

Data access:
  - get_frames()    -> list of snapshot frames
  - get_events()    -> list of event records
  - get_wave_summary(wave_num) -> stats for one wave
  - get_heatmap_data() -> position frequency per target (grid-quantized)
  - get_timeline()  -> chronological list of significant events
  - export_json()   -> full replay data as JSON-serializable dict
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from .target import SimulationTarget

# Maximum number of snapshot frames to keep in memory.
# At 2Hz this is ~25 minutes of recording.
MAX_FRAMES = 3000

# Grid cell size for heatmap quantization (meters).
HEATMAP_GRID_SIZE = 2.0

# Event types that the recorder captures from the EventBus.
_REPLAY_EVENT_TYPES = frozenset({
    "projectile_fired",
    "projectile_hit",
    "target_eliminated",
    "wave_start",
    "wave_complete",
    "game_over",
})


class ReplayRecorder:
    """Records game tick history for post-wave and post-game analysis."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._frames: deque[dict] = deque(maxlen=MAX_FRAMES)
        self._events: list[dict] = []
        self._recording = False
        self._lock = threading.Lock()

        # Listener thread for EventBus subscription
        self._listener_thread: threading.Thread | None = None
        self._listener_running = False

        # Metadata
        self._start_time: float | None = None

    # -- Properties ----------------------------------------------------------

    @property
    def frame_count(self) -> int:
        """Number of snapshot frames currently stored."""
        with self._lock:
            return len(self._frames)

    @property
    def event_count(self) -> int:
        """Number of events currently stored."""
        with self._lock:
            return len(self._events)

    @property
    def is_recording(self) -> bool:
        """Whether the recorder is actively capturing data."""
        return self._recording

    # -- Recording control ---------------------------------------------------

    def start(self) -> None:
        """Enable recording. Snapshots and events will be stored."""
        self._recording = True
        if self._start_time is None:
            self._start_time = time.time()

    def stop(self) -> None:
        """Disable recording. Data is preserved but no new data is captured."""
        self._recording = False

    def clear(self) -> None:
        """Reset the recorder, clearing all frames and events."""
        with self._lock:
            self._frames.clear()
            self._events.clear()
        self._recording = False
        self._start_time = None

    # -- Snapshot recording --------------------------------------------------

    def record_snapshot(self, targets: list[SimulationTarget]) -> None:
        """Record a single snapshot frame containing all target states.

        Each target is captured as a lightweight dict with position, heading,
        health, fsm_state, alliance, asset_type, and status.  Called from
        the engine tick loop (throttled to 2Hz by the caller).
        """
        if not self._recording:
            return

        now = time.time()
        target_snapshots = []
        for t in targets:
            target_snapshots.append({
                "target_id": t.target_id,
                "name": t.name,
                "alliance": t.alliance,
                "asset_type": t.asset_type,
                "position": {"x": t.position[0], "y": t.position[1]},
                "heading": t.heading,
                "health": t.health,
                "max_health": t.max_health,
                "fsm_state": t.fsm_state,
                "status": t.status,
            })

        frame = {
            "timestamp": now,
            "targets": target_snapshots,
        }

        with self._lock:
            self._frames.append(frame)

    # -- Event recording -----------------------------------------------------

    def record_event(self, event_type: str, data: dict) -> None:
        """Record a single event (combat, wave, or game event).

        Events are stored with a timestamp and the original event data.
        """
        if not self._recording:
            return

        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": dict(data),  # shallow copy to avoid mutation
        }

        with self._lock:
            self._events.append(event)

    # -- Data access ---------------------------------------------------------

    def get_frames(self) -> list[dict]:
        """Return a copy of all snapshot frames."""
        with self._lock:
            return list(self._frames)

    def get_events(self) -> list[dict]:
        """Return a copy of all recorded events."""
        with self._lock:
            return list(self._events)

    def get_wave_summary(self, wave_num: int) -> dict | None:
        """Return statistics for a specific wave.

        Returns None if the wave has not been recorded.  The summary includes:
          - wave_number, wave_name
          - eliminations, duration, score_bonus
          - shots_fired, shots_hit
        """
        with self._lock:
            events = list(self._events)

        # Find wave_start and wave_complete for this wave
        wave_start = None
        wave_complete = None
        for e in events:
            if e["event_type"] == "wave_start" and e["data"].get("wave_number") == wave_num:
                wave_start = e
            if e["event_type"] == "wave_complete" and e["data"].get("wave_number") == wave_num:
                wave_complete = e

        if wave_start is None:
            return None

        # Count combat events between wave_start and wave_complete timestamps
        start_ts = wave_start["timestamp"]
        end_ts = wave_complete["timestamp"] if wave_complete else time.time()

        shots_fired = 0
        shots_hit = 0
        eliminations = 0
        for e in events:
            if e["timestamp"] < start_ts or e["timestamp"] > end_ts:
                continue
            if e["event_type"] == "projectile_fired":
                shots_fired += 1
            elif e["event_type"] == "projectile_hit":
                shots_hit += 1
            elif e["event_type"] == "target_eliminated":
                eliminations += 1

        wave_name = wave_start["data"].get("wave_name", "")

        # Use wave_complete data if available, fall back to computed values
        if wave_complete:
            duration = wave_complete["data"].get("time_elapsed", end_ts - start_ts)
            score_bonus = wave_complete["data"].get("score_bonus", 0)
            wc_elims = wave_complete["data"].get("eliminations", eliminations)
        else:
            duration = end_ts - start_ts
            score_bonus = 0
            wc_elims = eliminations

        return {
            "wave_number": wave_num,
            "wave_name": wave_name,
            "eliminations": wc_elims,
            "duration": duration,
            "score_bonus": score_bonus,
            "shots_fired": shots_fired,
            "shots_hit": shots_hit,
        }

    def get_heatmap_data(self) -> dict[str, list[dict]]:
        """Return position frequency data for heat map generation.

        Returns a dict mapping target_id -> list of grid cells with counts.
        Positions are quantized into a grid of HEATMAP_GRID_SIZE meters.

        Each cell: {"x": float, "y": float, "count": int}
        """
        with self._lock:
            frames = list(self._frames)

        if not frames:
            return {}

        # Aggregate: target_id -> (grid_x, grid_y) -> count
        grid: dict[str, dict[tuple[int, int], int]] = {}

        for frame in frames:
            for tgt in frame["targets"]:
                tid = tgt["target_id"]
                px = tgt["position"]["x"]
                py = tgt["position"]["y"]
                gx = int(math.floor(px / HEATMAP_GRID_SIZE))
                gy = int(math.floor(py / HEATMAP_GRID_SIZE))
                if tid not in grid:
                    grid[tid] = {}
                cell_key = (gx, gy)
                grid[tid][cell_key] = grid[tid].get(cell_key, 0) + 1

        # Convert to serializable format
        result: dict[str, list[dict]] = {}
        for tid, cells in grid.items():
            result[tid] = [
                {
                    "x": gx * HEATMAP_GRID_SIZE,
                    "y": gy * HEATMAP_GRID_SIZE,
                    "count": count,
                }
                for (gx, gy), count in cells.items()
            ]
        return result

    def get_timeline(self) -> list[dict]:
        """Return all events in chronological order.

        Each entry: {"timestamp": float, "event_type": str, "data": dict}
        """
        with self._lock:
            events = list(self._events)
        events.sort(key=lambda e: e["timestamp"])
        return events

    # -- Export --------------------------------------------------------------

    def export_json(self) -> dict:
        """Export full replay data as a JSON-serializable dict.

        Returns:
            {
                "metadata": {
                    "total_frames": int,
                    "total_events": int,
                    "start_time": float | None,
                    "duration": float,
                },
                "frames": [...],
                "events": [...],
            }
        """
        with self._lock:
            frames = list(self._frames)
            events = list(self._events)

        now = time.time()
        duration = 0.0
        if self._start_time is not None:
            duration = now - self._start_time

        return {
            "metadata": {
                "total_frames": len(frames),
                "total_events": len(events),
                "start_time": self._start_time,
                "duration": round(duration, 2),
            },
            "frames": frames,
            "events": events,
        }

    # -- EventBus listener ---------------------------------------------------

    def start_listener(self) -> None:
        """Start a background thread that subscribes to EventBus events.

        The listener captures combat, wave, and game events and records them
        via record_event().  Snapshot recording is NOT done here -- it must be
        called explicitly from the engine tick loop at 2Hz.
        """
        if self._listener_running:
            return
        self._listener_running = True
        self._listener_thread = threading.Thread(
            target=self._event_listener_loop,
            name="replay-listener",
            daemon=True,
        )
        self._listener_thread.start()

    def stop_listener(self) -> None:
        """Stop the EventBus listener thread."""
        self._listener_running = False
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=2.0)
            self._listener_thread = None

    def _event_listener_loop(self) -> None:
        """Background loop: subscribe to EventBus, filter, and record events."""
        try:
            sub = self._event_bus.subscribe()
        except TypeError:
            # Gracefully handle test stubs that have incompatible subscribe()
            self._listener_running = False
            return
        try:
            while self._listener_running:
                try:
                    msg = sub.get(timeout=0.2)
                    event_type = msg.get("type")
                    if event_type in _REPLAY_EVENT_TYPES:
                        data = msg.get("data", {})
                        self.record_event(event_type, data)
                except Exception:
                    pass  # timeout or shutdown
        finally:
            try:
                self._event_bus.unsubscribe(sub)
            except Exception:
                pass  # test stubs may not have unsubscribe
