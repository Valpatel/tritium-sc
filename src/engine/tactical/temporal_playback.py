# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TemporalPlayback — replay tactical map state at any point in time.

Records snapshots of target positions, events, and alerts over time.
Allows scrubbing forward/backward through history to reconstruct
what the tactical picture looked like at any moment.

Usage
-----
    playback = TemporalPlayback()
    playback.record_snapshot(targets, events, timestamp)
    state = playback.get_state_at(timestamp)
"""

from __future__ import annotations

import bisect
import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_MAX_SNAPSHOTS = 10000
DEFAULT_SNAPSHOT_INTERVAL = 1.0  # seconds between auto-snapshots


@dataclass
class MapSnapshot:
    """A single recorded tactical map state."""

    timestamp: float
    targets: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "targets": self.targets,
            "events": self.events,
            "alerts": self.alerts,
            "target_count": len(self.targets),
        }


class TemporalPlayback:
    """Records and replays tactical map state over time.

    Thread-safe. Stores snapshots at configurable intervals and allows
    time-based queries to reconstruct any previous state.

    Parameters
    ----------
    max_snapshots:
        Maximum number of snapshots to retain. Oldest are pruned.
    snapshot_interval:
        Minimum seconds between accepting snapshots.
    """

    def __init__(
        self,
        max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
        snapshot_interval: float = DEFAULT_SNAPSHOT_INTERVAL,
    ) -> None:
        self._lock = threading.Lock()
        self._snapshots: list[MapSnapshot] = []
        self._timestamps: list[float] = []  # sorted, for bisect
        self._max_snapshots = max_snapshots
        self._snapshot_interval = snapshot_interval
        self._last_snapshot_time = 0.0
        # Playback state
        self._playback_active = False
        self._playback_time = 0.0
        self._playback_speed = 1.0

    def record_snapshot(
        self,
        targets: list[dict],
        events: list[dict] | None = None,
        alerts: list[dict] | None = None,
        timestamp: float | None = None,
    ) -> bool:
        """Record a tactical map snapshot.

        Returns True if the snapshot was accepted, False if rate-limited.
        """
        ts = timestamp if timestamp is not None else time.time()

        with self._lock:
            # Rate limiting
            if ts - self._last_snapshot_time < self._snapshot_interval:
                return False

            snap = MapSnapshot(
                timestamp=ts,
                targets=list(targets),
                events=list(events or []),
                alerts=list(alerts or []),
            )

            # Insert in sorted order
            idx = bisect.bisect_right(self._timestamps, ts)
            self._snapshots.insert(idx, snap)
            self._timestamps.insert(idx, ts)

            self._last_snapshot_time = ts

            # Prune oldest if over limit
            while len(self._snapshots) > self._max_snapshots:
                self._snapshots.pop(0)
                self._timestamps.pop(0)

        return True

    def get_state_at(self, timestamp: float) -> dict:
        """Reconstruct the tactical state at a given timestamp.

        Returns the snapshot closest to (but not after) the requested time.
        """
        with self._lock:
            if not self._snapshots:
                return {
                    "timestamp": timestamp,
                    "targets": [],
                    "events": [],
                    "alerts": [],
                    "target_count": 0,
                    "exact_match": False,
                    "snapshot_count": 0,
                }

            # Find the rightmost snapshot at or before timestamp
            idx = bisect.bisect_right(self._timestamps, timestamp) - 1
            if idx < 0:
                idx = 0

            snap = self._snapshots[idx]
            result = snap.to_dict()
            result["exact_match"] = abs(snap.timestamp - timestamp) < 0.1
            result["snapshot_count"] = len(self._snapshots)
            return result

    def get_time_range(self) -> dict:
        """Return the available time range for playback."""
        with self._lock:
            if not self._snapshots:
                return {
                    "start": 0.0,
                    "end": 0.0,
                    "duration_s": 0.0,
                    "snapshot_count": 0,
                }
            return {
                "start": self._timestamps[0],
                "end": self._timestamps[-1],
                "duration_s": self._timestamps[-1] - self._timestamps[0],
                "snapshot_count": len(self._snapshots),
            }

    def get_snapshots_between(
        self, start: float, end: float, max_count: int = 100
    ) -> list[dict]:
        """Return snapshots within a time range.

        Args:
            start: Start timestamp (inclusive).
            end:   End timestamp (inclusive).
            max_count: Maximum snapshots to return (evenly sampled).
        """
        with self._lock:
            start_idx = bisect.bisect_left(self._timestamps, start)
            end_idx = bisect.bisect_right(self._timestamps, end)
            candidates = self._snapshots[start_idx:end_idx]

        if not candidates:
            return []

        # Downsample if too many
        if len(candidates) > max_count:
            step = len(candidates) / max_count
            indices = [int(i * step) for i in range(max_count)]
            candidates = [candidates[i] for i in indices]

        return [s.to_dict() for s in candidates]

    # ------------------------------------------------------------------
    # Playback controls
    # ------------------------------------------------------------------

    def start_playback(
        self, start_time: float | None = None, speed: float = 1.0
    ) -> dict:
        """Start temporal playback from a given time.

        Args:
            start_time: Unix timestamp to start from (default: earliest).
            speed: Playback speed multiplier (1.0 = realtime, 2.0 = 2x).
        """
        with self._lock:
            if not self._snapshots:
                return {"error": "No snapshots available"}

            self._playback_active = True
            self._playback_speed = max(0.1, min(speed, 100.0))
            self._playback_time = (
                start_time if start_time is not None else self._timestamps[0]
            )

        return {
            "status": "playing",
            "time": self._playback_time,
            "speed": self._playback_speed,
        }

    def stop_playback(self) -> dict:
        """Stop temporal playback."""
        with self._lock:
            self._playback_active = False
        return {"status": "stopped", "time": self._playback_time}

    def seek(self, timestamp: float) -> dict:
        """Seek to a specific timestamp during playback."""
        with self._lock:
            self._playback_time = timestamp
        state = self.get_state_at(timestamp)
        state["playback_time"] = timestamp
        return state

    def get_playback_status(self) -> dict:
        """Return current playback state."""
        with self._lock:
            return {
                "active": self._playback_active,
                "time": self._playback_time,
                "speed": self._playback_speed,
                "range": self.get_time_range(),
            }

    # ------------------------------------------------------------------
    # Target trajectory extraction
    # ------------------------------------------------------------------

    def get_target_trajectory(
        self, target_id: str, start: float | None = None, end: float | None = None
    ) -> list[dict]:
        """Extract the movement trajectory of a specific target across snapshots.

        Returns a list of {timestamp, x, y, heading, speed} dicts.
        """
        with self._lock:
            snaps = self._snapshots
            if start is not None:
                s_idx = bisect.bisect_left(self._timestamps, start)
                snaps = snaps[s_idx:]
            if end is not None:
                e_idx = bisect.bisect_right(
                    self._timestamps[:len(snaps)], end
                )
                snaps = snaps[:e_idx]

        trajectory: list[dict] = []
        for snap in snaps:
            for target in snap.targets:
                tid = target.get("target_id") or target.get("id", "")
                if tid == target_id:
                    pos = target.get("position", {})
                    if isinstance(pos, dict):
                        x, y = pos.get("x", 0.0), pos.get("y", 0.0)
                    elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
                        x, y = pos[0], pos[1]
                    else:
                        continue

                    trajectory.append({
                        "timestamp": snap.timestamp,
                        "x": x,
                        "y": y,
                        "heading": target.get("heading", 0.0),
                        "speed": target.get("speed", 0.0),
                    })
                    break

        return trajectory

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all recorded snapshots."""
        with self._lock:
            self._snapshots.clear()
            self._timestamps.clear()
            self._playback_active = False
            self._playback_time = 0.0

    @property
    def snapshot_count(self) -> int:
        """Number of stored snapshots."""
        with self._lock:
            return len(self._snapshots)
