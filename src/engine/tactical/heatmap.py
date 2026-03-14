# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HeatmapEngine — grid-based activity heatmap for the tactical map.

Accumulates position events from all sources (BLE sightings, camera
detections, RF motion, target movements) into a spatial grid.  Each cell
counts events within configurable time windows.  Old data is pruned
automatically.

Layers
------
- ``ble_activity``     — BLE sighting positions
- ``camera_activity``  — Camera/YOLO detection positions
- ``motion_activity``  — RF motion sensor triggers
- ``all``              — Union of all layers

Usage
-----
    engine = HeatmapEngine()
    engine.record_event("ble_activity", x=120.5, y=45.3)
    grid = engine.get_heatmap(time_window_minutes=60, resolution=50)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

VALID_LAYERS = ("ble_activity", "camera_activity", "motion_activity")
DEFAULT_RETENTION_SECONDS = 24 * 3600  # 24 hours


@dataclass
class HeatmapEvent:
    """A single position event recorded into the heatmap."""

    layer: str
    x: float  # local meters (East)
    y: float  # local meters (North)
    timestamp: float = field(default_factory=time.time)
    weight: float = 1.0


class HeatmapEngine:
    """Grid-based spatial activity accumulator.

    Thread-safe.  Events are stored in a flat list per layer and pruned
    on read (lazy) or via explicit ``prune()`` calls.

    Parameters
    ----------
    retention_seconds:
        How long events are kept before pruning.  Default 24 hours.
    """

    def __init__(self, retention_seconds: float = DEFAULT_RETENTION_SECONDS) -> None:
        self._events: dict[str, list[HeatmapEvent]] = {
            layer: [] for layer in VALID_LAYERS
        }
        self._retention = retention_seconds
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_event(
        self,
        layer: str,
        x: float,
        y: float,
        weight: float = 1.0,
        timestamp: float | None = None,
    ) -> None:
        """Record a position event into a layer.

        Args:
            layer:     One of VALID_LAYERS.
            x:         East coordinate in local meters.
            y:         North coordinate in local meters.
            weight:    Event weight (default 1.0).
            timestamp: Unix timestamp (default now).

        Raises:
            ValueError: If *layer* is not in VALID_LAYERS.
        """
        if layer not in VALID_LAYERS:
            raise ValueError(
                f"Invalid layer '{layer}', must be one of {VALID_LAYERS}"
            )
        ts = timestamp if timestamp is not None else time.time()
        evt = HeatmapEvent(layer=layer, x=x, y=y, timestamp=ts, weight=weight)
        with self._lock:
            self._events[layer].append(evt)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get_heatmap(
        self,
        time_window_minutes: float = 60,
        resolution: int = 50,
        layer: str = "all",
    ) -> dict:
        """Build a 2D intensity grid for the given layer and time window.

        Args:
            time_window_minutes: Only include events from the last N minutes.
            resolution:          Number of cells along each axis (NxN grid).
            layer:               ``"all"`` or one of VALID_LAYERS.

        Returns:
            Dict with keys:
                ``grid``       — list[list[float]], row-major intensity grid.
                ``bounds``     — {min_x, max_x, min_y, max_y} of the data.
                ``resolution`` — grid size.
                ``layer``      — which layer was queried.
                ``max_value``  — peak cell intensity (for normalisation).
                ``event_count``— total events in the window.
        """
        cutoff = time.time() - time_window_minutes * 60
        events = self._collect_events(layer, cutoff)

        if not events:
            return {
                "grid": [[0.0] * resolution for _ in range(resolution)],
                "bounds": {"min_x": 0, "max_x": 0, "min_y": 0, "max_y": 0},
                "resolution": resolution,
                "layer": layer,
                "max_value": 0.0,
                "event_count": 0,
            }

        # Determine spatial bounds with a small margin
        xs = [e.x for e in events]
        ys = [e.y for e in events]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        # Avoid zero-size bounds
        if max_x - min_x < 1.0:
            min_x -= 0.5
            max_x += 0.5
        if max_y - min_y < 1.0:
            min_y -= 0.5
            max_y += 0.5

        # Build grid — grid[row][col], row=y, col=x
        grid: list[list[float]] = [
            [0.0] * resolution for _ in range(resolution)
        ]
        range_x = max_x - min_x
        range_y = max_y - min_y

        for evt in events:
            col = int((evt.x - min_x) / range_x * (resolution - 1))
            row = int((evt.y - min_y) / range_y * (resolution - 1))
            col = max(0, min(resolution - 1, col))
            row = max(0, min(resolution - 1, row))
            grid[row][col] += evt.weight

        max_value = max(
            (grid[r][c] for r in range(resolution) for c in range(resolution)),
            default=0.0,
        )

        return {
            "grid": grid,
            "bounds": {
                "min_x": min_x,
                "max_x": max_x,
                "min_y": min_y,
                "max_y": max_y,
            },
            "resolution": resolution,
            "layer": layer,
            "max_value": max_value,
            "event_count": len(events),
        }

    def get_timeline(
        self,
        start: float,
        end: float,
        buckets: int = 48,
        resolution: int = 30,
        layer: str = "all",
    ) -> dict:
        """Build time-bucketed heatmap frames for timeline playback.

        Args:
            start:      Start timestamp (unix seconds).
            end:        End timestamp (unix seconds).
            buckets:    Number of time buckets to divide the range into.
            resolution: Grid resolution (NxN) for each frame.
            layer:      ``"all"`` or one of VALID_LAYERS.

        Returns:
            Dict with keys:
                ``frames``     — list of heatmap dicts (one per bucket).
                ``global_max`` — peak intensity across all frames.
        """
        if buckets < 1:
            buckets = 1
        bucket_size = (end - start) / buckets
        all_events = self._collect_events(layer, start)

        # Filter to only events within [start, end]
        all_events = [e for e in all_events if e.timestamp <= end]

        frames = []
        global_max = 0.0

        for i in range(buckets):
            bucket_start = start + i * bucket_size
            bucket_end = bucket_start + bucket_size
            bucket_events = [
                e for e in all_events
                if bucket_start <= e.timestamp < bucket_end
            ]

            if not bucket_events:
                frames.append({
                    "timestamp": bucket_start,
                    "grid": [[0.0] * resolution for _ in range(resolution)],
                    "resolution": resolution,
                    "max_value": 0.0,
                    "event_count": 0,
                })
                continue

            # Determine spatial bounds from ALL events (consistent across frames)
            xs = [e.x for e in all_events] if all_events else [0]
            ys = [e.y for e in all_events] if all_events else [0]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            if max_x - min_x < 1.0:
                min_x -= 0.5
                max_x += 0.5
            if max_y - min_y < 1.0:
                min_y -= 0.5
                max_y += 0.5

            grid: list[list[float]] = [
                [0.0] * resolution for _ in range(resolution)
            ]
            range_x = max_x - min_x
            range_y = max_y - min_y

            for evt in bucket_events:
                col = int((evt.x - min_x) / range_x * (resolution - 1))
                row = int((evt.y - min_y) / range_y * (resolution - 1))
                col = max(0, min(resolution - 1, col))
                row = max(0, min(resolution - 1, row))
                grid[row][col] += evt.weight

            max_value = max(
                (grid[r][c] for r in range(resolution) for c in range(resolution)),
                default=0.0,
            )
            global_max = max(global_max, max_value)

            frames.append({
                "timestamp": bucket_start,
                "grid": grid,
                "resolution": resolution,
                "max_value": max_value,
                "event_count": len(bucket_events),
            })

        return {
            "frames": frames,
            "global_max": global_max,
        }

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune(self, before: float | None = None) -> int:
        """Remove events older than *before* (unix timestamp).

        If *before* is None, uses ``now - retention_seconds``.

        Returns:
            Number of events removed.
        """
        cutoff = before if before is not None else (time.time() - self._retention)
        removed = 0
        with self._lock:
            for layer in VALID_LAYERS:
                original = len(self._events[layer])
                self._events[layer] = [
                    e for e in self._events[layer] if e.timestamp >= cutoff
                ]
                removed += original - len(self._events[layer])
        if removed:
            logger.debug("Pruned %d heatmap events (cutoff=%.0f)", removed, cutoff)
        return removed

    def clear(self, layer: str | None = None) -> None:
        """Clear all events, or events for a specific layer."""
        with self._lock:
            if layer is None:
                for k in self._events:
                    self._events[k] = []
            elif layer in self._events:
                self._events[layer] = []

    def event_count(self, layer: str = "all") -> int:
        """Return the total number of stored events."""
        with self._lock:
            if layer == "all":
                return sum(len(v) for v in self._events.values())
            return len(self._events.get(layer, []))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _collect_events(
        self, layer: str, cutoff: float
    ) -> list[HeatmapEvent]:
        """Gather events for one or all layers after cutoff."""
        with self._lock:
            if layer == "all":
                events = []
                for evts in self._events.values():
                    events.extend(e for e in evts if e.timestamp >= cutoff)
                return events
            if layer in self._events:
                return [
                    e for e in self._events[layer] if e.timestamp >= cutoff
                ]
            return []
