# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo data generator for radar tracker plugin.

Generates synthetic radar tracks simulating vehicles on roads,
aircraft in flight, and boats on water. Publishes track data
through the RadarTracker so it flows through the real pipeline.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import Any, Optional

log = logging.getLogger("radar-demo")

# Demo radar position (San Francisco — matches demo mode center)
DEMO_RADAR_LAT = 37.7749
DEMO_RADAR_LNG = -122.4194

# Synthetic track templates
DEMO_TRACKS = [
    # Vehicles on roads (1-3 km, moderate speed)
    {
        "base_range": 1200.0, "base_azimuth": 45.0,
        "speed": 15.0, "rcs": 8.0, "class": "vehicle",
        "range_drift": 200.0, "azimuth_drift": 10.0,
    },
    {
        "base_range": 2500.0, "base_azimuth": 120.0,
        "speed": 22.0, "rcs": 12.0, "class": "vehicle",
        "range_drift": 400.0, "azimuth_drift": 15.0,
    },
    {
        "base_range": 800.0, "base_azimuth": 210.0,
        "speed": 8.0, "rcs": 5.0, "class": "vehicle",
        "range_drift": 150.0, "azimuth_drift": 8.0,
    },
    # Aircraft (5-15 km, fast)
    {
        "base_range": 8000.0, "base_azimuth": 90.0,
        "speed": 120.0, "rcs": 25.0, "class": "aircraft",
        "range_drift": 3000.0, "azimuth_drift": 30.0,
    },
    {
        "base_range": 12000.0, "base_azimuth": 270.0,
        "speed": 85.0, "rcs": -5.0, "class": "uav",
        "range_drift": 2000.0, "azimuth_drift": 20.0,
    },
    # People walking (close range)
    {
        "base_range": 300.0, "base_azimuth": 160.0,
        "speed": 1.5, "rcs": -5.0, "class": "person",
        "range_drift": 50.0, "azimuth_drift": 5.0,
    },
    # Boat (moderate range, slow)
    {
        "base_range": 4000.0, "base_azimuth": 320.0,
        "speed": 5.0, "rcs": 30.0, "class": "ship",
        "range_drift": 500.0, "azimuth_drift": 8.0,
    },
]


class RadarDemoGenerator:
    """Generates synthetic radar tracks for demo mode.

    Creates realistic-looking radar track data at ~1Hz update rate.
    Tracks move smoothly with slight randomness to simulate real
    radar track jitter.
    """

    def __init__(
        self,
        tracker: Any,
        radar_id: str = "demo-radar-01",
        update_interval: float = 1.0,
    ) -> None:
        self._tracker = tracker
        self._radar_id = radar_id
        self._update_interval = update_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Track state: track_id -> current state dict
        self._track_state: dict[str, dict] = {}
        self._next_track_id = 1

        # Initialize track states from templates
        for template in DEMO_TRACKS:
            tid = f"T{self._next_track_id:04d}"
            self._next_track_id += 1
            self._track_state[tid] = {
                "track_id": tid,
                "range_m": template["base_range"],
                "azimuth_deg": template["base_azimuth"],
                "velocity_mps": template["speed"],
                "rcs_dbsm": template["rcs"],
                "classification": template["class"],
                "range_drift": template["range_drift"],
                "azimuth_drift": template["azimuth_drift"],
                "phase": random.uniform(0, 2 * math.pi),
            }

    def start(self) -> None:
        """Start generating demo tracks."""
        if self._running:
            return

        # Configure the demo radar position
        self._tracker.configure_radar(
            radar_id=self._radar_id,
            lat=DEMO_RADAR_LAT,
            lng=DEMO_RADAR_LNG,
            altitude_m=50.0,
            orientation_deg=0.0,
            max_range_m=20000.0,
            min_range_m=10.0,
            name="Demo Radar (SF)",
            enabled=True,
        )

        self._running = True
        self._thread = threading.Thread(
            target=self._generate_loop,
            daemon=True,
            name="radar-demo-gen",
        )
        self._thread.start()
        log.info("Radar demo generator started (radar=%s)", self._radar_id)

    def stop(self) -> None:
        """Stop generating demo tracks."""
        if not self._running:
            return
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        log.info("Radar demo generator stopped")

    @property
    def running(self) -> bool:
        return self._running

    def _generate_loop(self) -> None:
        """Background loop: generate and ingest synthetic tracks."""
        while self._running:
            try:
                tracks = self._generate_tracks()
                self._tracker.ingest_tracks(self._radar_id, tracks)
                self._tracker.prune_stale()
            except Exception as exc:
                log.error("Radar demo generation error: %s", exc)

            # Sleep with early exit check
            deadline = time.monotonic() + self._update_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.1)

    def _generate_tracks(self) -> list[dict]:
        """Generate one sweep of synthetic tracks."""
        now = time.time()
        tracks = []

        for tid, state in self._track_state.items():
            # Sinusoidal movement pattern with noise
            phase = state["phase"]
            t = now * 0.1  # slow time scale

            range_offset = state["range_drift"] * math.sin(t + phase)
            azimuth_offset = state["azimuth_drift"] * math.sin(t * 0.7 + phase + 1.0)

            # Add some random jitter (radar measurement noise)
            range_jitter = random.gauss(0, state["range_drift"] * 0.05)
            azimuth_jitter = random.gauss(0, 0.5)

            current_range = max(50.0, state["range_m"] + range_offset + range_jitter)
            current_azimuth = (state["azimuth_deg"] + azimuth_offset + azimuth_jitter) % 360.0

            # Velocity with small variation
            velocity = state["velocity_mps"] + random.gauss(0, state["velocity_mps"] * 0.1)

            tracks.append({
                "track_id": tid,
                "range_m": current_range,
                "azimuth_deg": current_azimuth,
                "elevation_deg": random.gauss(0, 0.5),
                "velocity_mps": velocity,
                "rcs_dbsm": state["rcs_dbsm"] + random.gauss(0, 1.0),
                "classification": state["classification"],
                "confidence": min(1.0, 0.7 + random.random() * 0.3),
                "timestamp": now,
            })

        return tracks
