# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RSSI-based motion detection using variance analysis.

Detects movement in the RF environment by monitoring RSSI changes between
stationary radios (pair mode) and from single observers (device mode).

Theory: when a person or object moves through the RF path between two
stationary radios, the RSSI fluctuates due to absorption, reflection, and
multipath changes. A sliding window variance above a threshold indicates
motion. This is passive — no cameras, no additional hardware beyond the
radios already deployed.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger("rf-motion")

# -- Thresholds ----------------------------------------------------------------

# Variance thresholds (in dBm^2)
STATIC_VARIANCE_MAX = 2.0    # Below this = static (no motion)
MOTION_VARIANCE_MIN = 5.0    # Above this = motion detected
# Between 2.0 and 5.0 = indeterminate / possible motion

# Default sliding window duration (seconds)
DEFAULT_WINDOW_SECONDS = 60.0

# Minimum samples in window before we can make a determination
MIN_SAMPLES_FOR_DETECTION = 5

# How long a motion event stays "active" after last trigger (seconds)
MOTION_HOLD_TIME = 10.0


# -- Data classes --------------------------------------------------------------

@dataclass
class RSSISample:
    """A single RSSI reading with timestamp."""
    rssi: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class MotionEvent:
    """A detected motion event."""
    event_id: str
    pair_id: str               # "nodeA::nodeB" or "observer::device_mac"
    mode: str                  # "pair" or "device"
    variance: float            # Current RSSI variance
    mean_rssi: float           # Current mean RSSI
    confidence: float          # 0.0-1.0 based on variance strength
    estimated_position: tuple[float, float]  # Midpoint of pair or observer pos
    direction_hint: str        # "approaching", "departing", "crossing", "unknown"
    timestamp: float = field(default_factory=time.time)
    node_a: str = ""
    node_b: str = ""
    sample_count: int = 0

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "pair_id": self.pair_id,
            "mode": self.mode,
            "variance": round(self.variance, 2),
            "mean_rssi": round(self.mean_rssi, 1),
            "confidence": round(self.confidence, 3),
            "estimated_position": {
                "x": self.estimated_position[0],
                "y": self.estimated_position[1],
            },
            "direction_hint": self.direction_hint,
            "timestamp": self.timestamp,
            "node_a": self.node_a,
            "node_b": self.node_b,
            "sample_count": self.sample_count,
        }


@dataclass
class PairBaseline:
    """Baseline RSSI statistics for a radio pair."""
    pair_id: str
    node_a: str
    node_b: str
    mean_rssi: float = 0.0
    variance: float = 0.0
    sample_count: int = 0
    last_motion: float = 0.0        # timestamp of last motion detection
    motion_active: bool = False
    position_a: tuple[float, float] = (0.0, 0.0)
    position_b: tuple[float, float] = (0.0, 0.0)

    @property
    def midpoint(self) -> tuple[float, float]:
        return (
            (self.position_a[0] + self.position_b[0]) / 2.0,
            (self.position_a[1] + self.position_b[1]) / 2.0,
        )

    def to_dict(self) -> dict:
        return {
            "pair_id": self.pair_id,
            "node_a": self.node_a,
            "node_b": self.node_b,
            "mean_rssi": round(self.mean_rssi, 1),
            "variance": round(self.variance, 2),
            "sample_count": self.sample_count,
            "motion_active": self.motion_active,
            "last_motion": self.last_motion,
            "position_a": {"x": self.position_a[0], "y": self.position_a[1]},
            "position_b": {"x": self.position_b[0], "y": self.position_b[1]},
            "midpoint": {"x": self.midpoint[0], "y": self.midpoint[1]},
        }


# -- Sliding window ------------------------------------------------------------

class SlidingRSSIWindow:
    """Maintains a time-bounded sliding window of RSSI samples."""

    def __init__(self, window_seconds: float = DEFAULT_WINDOW_SECONDS) -> None:
        self._samples: list[RSSISample] = []
        self._window_seconds = window_seconds

    def add(self, rssi: float, timestamp: float | None = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        self._samples.append(RSSISample(rssi=rssi, timestamp=ts))
        self._prune(ts)

    def _prune(self, now: float | None = None) -> None:
        if now is None:
            now = time.time()
        cutoff = now - self._window_seconds
        self._samples = [s for s in self._samples if s.timestamp >= cutoff]

    @property
    def count(self) -> int:
        self._prune()
        return len(self._samples)

    @property
    def mean(self) -> float:
        self._prune()
        if not self._samples:
            return 0.0
        return sum(s.rssi for s in self._samples) / len(self._samples)

    @property
    def variance(self) -> float:
        self._prune()
        n = len(self._samples)
        if n < 2:
            return 0.0
        m = self.mean
        return sum((s.rssi - m) ** 2 for s in self._samples) / (n - 1)

    @property
    def trend(self) -> float:
        """Linear trend of RSSI over window. Positive = getting stronger."""
        self._prune()
        n = len(self._samples)
        if n < 3:
            return 0.0
        # Simple linear regression slope
        t0 = self._samples[0].timestamp
        sum_t = sum_r = sum_tr = sum_t2 = 0.0
        for s in self._samples:
            t = s.timestamp - t0
            sum_t += t
            sum_r += s.rssi
            sum_tr += t * s.rssi
            sum_t2 += t * t
        denom = n * sum_t2 - sum_t * sum_t
        if abs(denom) < 1e-9:
            return 0.0
        return (n * sum_tr - sum_t * sum_r) / denom

    def clear(self) -> None:
        self._samples.clear()


# -- Motion Detector -----------------------------------------------------------

class RSSIMotionDetector:
    """Detects motion using RSSI variance between fixed radio pairs and
    per-device RSSI from single observers.

    Usage:
        detector = RSSIMotionDetector()
        detector.set_node_position("node-a", (10.0, 20.0))
        detector.set_node_position("node-b", (30.0, 20.0))
        detector.record_pair_rssi("node-a", "node-b", -55.0)
        events = detector.detect()
    """

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        static_threshold: float = STATIC_VARIANCE_MAX,
        motion_threshold: float = MOTION_VARIANCE_MIN,
    ) -> None:
        self._window_seconds = window_seconds
        self._static_threshold = static_threshold
        self._motion_threshold = motion_threshold

        # Pair windows: "nodeA::nodeB" -> SlidingRSSIWindow
        self._pair_windows: dict[str, SlidingRSSIWindow] = {}
        # Device windows: "observer::device_mac" -> SlidingRSSIWindow
        self._device_windows: dict[str, SlidingRSSIWindow] = {}

        # Node positions: node_id -> (x, y)
        self._node_positions: dict[str, tuple[float, float]] = {}

        # Baselines: pair_id -> PairBaseline
        self._baselines: dict[str, PairBaseline] = {}

        # Event counter for unique IDs
        self._event_counter = 0

        # Recent events for dedup
        self._recent_events: list[MotionEvent] = []

        self._lock = threading.Lock()

    @staticmethod
    def make_pair_id(node_a: str, node_b: str) -> str:
        """Canonical pair ID — sorted so order doesn't matter."""
        a, b = sorted([node_a, node_b])
        return f"{a}::{b}"

    def set_node_position(self, node_id: str, position: tuple[float, float]) -> None:
        with self._lock:
            self._node_positions[node_id] = position

    def get_node_positions(self) -> dict[str, tuple[float, float]]:
        with self._lock:
            return dict(self._node_positions)

    def record_pair_rssi(
        self,
        node_a: str,
        node_b: str,
        rssi: float,
        timestamp: float | None = None,
    ) -> None:
        """Record an RSSI reading between two fixed radio nodes."""
        pair_id = self.make_pair_id(node_a, node_b)
        with self._lock:
            if pair_id not in self._pair_windows:
                self._pair_windows[pair_id] = SlidingRSSIWindow(self._window_seconds)
            self._pair_windows[pair_id].add(rssi, timestamp)

            # Initialize baseline if needed
            if pair_id not in self._baselines:
                sorted_nodes = sorted([node_a, node_b])
                pos_a = self._node_positions.get(sorted_nodes[0], (0.0, 0.0))
                pos_b = self._node_positions.get(sorted_nodes[1], (0.0, 0.0))
                self._baselines[pair_id] = PairBaseline(
                    pair_id=pair_id,
                    node_a=sorted_nodes[0],
                    node_b=sorted_nodes[1],
                    position_a=pos_a,
                    position_b=pos_b,
                )

    def record_device_rssi(
        self,
        observer_id: str,
        device_mac: str,
        rssi: float,
        timestamp: float | None = None,
    ) -> None:
        """Record RSSI from a single observer watching a device."""
        key = f"{observer_id}::{device_mac}"
        with self._lock:
            if key not in self._device_windows:
                self._device_windows[key] = SlidingRSSIWindow(self._window_seconds)
            self._device_windows[key].add(rssi, timestamp)

    def detect(self) -> list[MotionEvent]:
        """Analyze all windows and return new motion events."""
        events: list[MotionEvent] = []
        now = time.time()

        with self._lock:
            # Check pair windows
            for pair_id, window in self._pair_windows.items():
                if window.count < MIN_SAMPLES_FOR_DETECTION:
                    continue

                variance = window.variance
                mean_rssi = window.mean
                baseline = self._baselines.get(pair_id)

                # Update baseline stats
                if baseline is not None:
                    baseline.mean_rssi = mean_rssi
                    baseline.variance = variance
                    baseline.sample_count = window.count
                    # Update positions (may have changed)
                    sorted_nodes = sorted([baseline.node_a, baseline.node_b])
                    baseline.position_a = self._node_positions.get(
                        sorted_nodes[0], baseline.position_a
                    )
                    baseline.position_b = self._node_positions.get(
                        sorted_nodes[1], baseline.position_b
                    )

                if variance >= self._motion_threshold:
                    # Motion detected
                    if baseline is not None:
                        baseline.motion_active = True
                        baseline.last_motion = now

                    confidence = min(1.0, (variance - self._motion_threshold) /
                                     (self._motion_threshold * 2))
                    confidence = max(0.1, confidence)

                    # Direction hint from trend
                    trend = window.trend
                    if trend > 0.5:
                        direction = "approaching"
                    elif trend < -0.5:
                        direction = "departing"
                    elif variance > self._motion_threshold * 2:
                        direction = "crossing"
                    else:
                        direction = "unknown"

                    midpoint = (0.0, 0.0)
                    node_a_id = ""
                    node_b_id = ""
                    if baseline is not None:
                        midpoint = baseline.midpoint
                        node_a_id = baseline.node_a
                        node_b_id = baseline.node_b

                    self._event_counter += 1
                    event = MotionEvent(
                        event_id=f"rfm_{self._event_counter}",
                        pair_id=pair_id,
                        mode="pair",
                        variance=variance,
                        mean_rssi=mean_rssi,
                        confidence=confidence,
                        estimated_position=midpoint,
                        direction_hint=direction,
                        timestamp=now,
                        node_a=node_a_id,
                        node_b=node_b_id,
                        sample_count=window.count,
                    )
                    events.append(event)
                elif variance < self._static_threshold:
                    # Static — clear motion flag
                    if baseline is not None:
                        if baseline.motion_active and (now - baseline.last_motion) > MOTION_HOLD_TIME:
                            baseline.motion_active = False

            # Check device windows (single observer)
            for key, window in self._device_windows.items():
                if window.count < MIN_SAMPLES_FOR_DETECTION:
                    continue

                variance = window.variance
                if variance >= self._motion_threshold:
                    parts = key.split("::", 1)
                    observer_id = parts[0]
                    device_mac = parts[1] if len(parts) > 1 else "unknown"

                    mean_rssi = window.mean
                    confidence = min(1.0, (variance - self._motion_threshold) /
                                     (self._motion_threshold * 2))
                    confidence = max(0.1, confidence)

                    trend = window.trend
                    if trend > 0.5:
                        direction = "approaching"
                    elif trend < -0.5:
                        direction = "departing"
                    else:
                        direction = "unknown"

                    obs_pos = self._node_positions.get(observer_id, (0.0, 0.0))

                    self._event_counter += 1
                    event = MotionEvent(
                        event_id=f"rfm_{self._event_counter}",
                        pair_id=key,
                        mode="device",
                        variance=variance,
                        mean_rssi=mean_rssi,
                        confidence=confidence,
                        estimated_position=obs_pos,
                        direction_hint=direction,
                        timestamp=now,
                        node_a=observer_id,
                        node_b=device_mac,
                        sample_count=window.count,
                    )
                    events.append(event)

            self._recent_events = events

        return events

    def get_baselines(self) -> list[PairBaseline]:
        with self._lock:
            return list(self._baselines.values())

    def get_baseline(self, pair_id: str) -> PairBaseline | None:
        with self._lock:
            return self._baselines.get(pair_id)

    def get_active_motion(self) -> list[PairBaseline]:
        """Return baselines with active motion."""
        with self._lock:
            return [b for b in self._baselines.values() if b.motion_active]

    def get_recent_events(self) -> list[MotionEvent]:
        with self._lock:
            return list(self._recent_events)

    def clear(self) -> None:
        with self._lock:
            self._pair_windows.clear()
            self._device_windows.clear()
            self._baselines.clear()
            self._recent_events.clear()
