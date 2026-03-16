# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RadarTrackerPlugin — radar track ingestion and map integration.

Subscribes to MQTT radar track topics, converts range/azimuth to lat/lng,
and creates TrackedTarget entries for display on the tactical map.
Supports multiple radar units (Aeris-10, SDR-based passive radar, etc.).

MQTT topics:
    IN:  tritium/{site}/radar/{radar_id}/tracks  — JSON array of tracks
    IN:  tritium/{site}/radar/{radar_id}/status   — radar unit status
    IN:  tritium/{site}/radar/{radar_id}/config   — radar configuration
    OUT: radar:tracks_updated                     — EventBus notification
"""

from __future__ import annotations

import json
import logging
import queue as queue_mod
import threading
import time
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface
from .tracker import RadarTracker

log = logging.getLogger("radar-tracker")


class RadarTrackerPlugin(PluginInterface):
    """Radar track ingestion and unified target creation.

    Processes radar tracks from MQTT (or direct API ingestion),
    converts range/azimuth polar coordinates to lat/lng using each
    radar's configured position, and pushes TrackedTarget entries
    into the TargetTracker for map display and sensor fusion.

    Includes a demo data generator for synthetic radar tracks.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker_service: Optional[RadarTracker] = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None

        self._running = False
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None
        self._cleanup_thread: Optional[threading.Thread] = None
        self._demo_generator: Any = None

        # Cleanup interval
        self._cleanup_interval = 5.0

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.radar-tracker"

    @property
    def name(self) -> str:
        return "Radar Tracker"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"bridge", "data_source", "routes", "ui"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Store references and initialize RadarTracker + routes."""
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._logger = ctx.logger or log

        # Initialize RadarTracker
        self._tracker_service = RadarTracker(
            target_tracker=ctx.target_tracker,
            event_bus=ctx.event_bus,
        )

        # Register FastAPI routes
        self._register_routes()

        self._logger.info("Radar Tracker plugin configured")

    def start(self) -> None:
        """Start event listener and cleanup threads."""
        if self._running:
            return
        self._running = True

        # Subscribe to EventBus for MQTT-bridged radar events
        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="radar-tracker-events",
            )
            self._event_thread.start()

        # Cleanup thread for pruning stale tracks
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="radar-tracker-cleanup",
        )
        self._cleanup_thread.start()

        self._logger.info("Radar Tracker plugin started")

    def stop(self) -> None:
        """Stop event listener, cleanup, and demo generator."""
        if not self._running:
            return
        self._running = False

        # Stop demo generator if running
        if self._demo_generator is not None:
            self._demo_generator.stop()
            self._demo_generator = None

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=3.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._logger.info("Radar Tracker plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Public accessors --------------------------------------------------

    @property
    def tracker(self) -> Optional[RadarTracker]:
        """Access the underlying RadarTracker for direct API use."""
        return self._tracker_service

    def start_demo(self) -> dict:
        """Start the demo data generator."""
        from .demo import RadarDemoGenerator

        if self._demo_generator is not None and self._demo_generator.running:
            return {"status": "already_running"}

        if self._tracker_service is None:
            return {"status": "error", "message": "Tracker not initialized"}

        self._demo_generator = RadarDemoGenerator(
            tracker=self._tracker_service,
        )
        self._demo_generator.start()
        return {"status": "started"}

    def stop_demo(self) -> dict:
        """Stop the demo data generator."""
        if self._demo_generator is None or not self._demo_generator.running:
            return {"status": "not_running"}

        self._demo_generator.stop()
        self._demo_generator = None
        return {"status": "stopped"}

    # -- Event handling ----------------------------------------------------

    def _event_drain_loop(self) -> None:
        """Background loop: drain EventBus for radar MQTT events."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._handle_event(event)
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("Radar tracker event error: %s", exc)

    def _handle_event(self, event: dict) -> None:
        """Process a single EventBus event."""
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        # MQTT-bridged radar track data
        if event_type in ("radar:tracks", "mqtt:radar_tracks"):
            radar_id = data.get("radar_id", data.get("source_id", "unknown"))
            tracks = data.get("tracks", [])
            if tracks and self._tracker_service:
                self._tracker_service.ingest_tracks(radar_id, tracks)

        # MQTT-bridged radar status
        elif event_type in ("radar:status", "mqtt:radar_status"):
            radar_id = data.get("radar_id", "")
            if radar_id and self._tracker_service:
                radar = self._tracker_service.get_radar(radar_id)
                if radar:
                    radar.online = data.get("online", True)
                    radar.last_seen = time.time()

        # MQTT-bridged radar config
        elif event_type in ("radar:config", "mqtt:radar_config"):
            self._handle_config_event(data)

        # Demo mode start — auto-start radar demo
        elif event_type == "demo:started":
            self.start_demo()

        # Demo mode stop — auto-stop radar demo
        elif event_type == "demo:stopped":
            self.stop_demo()

    def _handle_config_event(self, data: dict) -> None:
        """Handle incoming radar configuration from MQTT."""
        if self._tracker_service is None:
            return

        radar_id = data.get("radar_id", "")
        if not radar_id:
            return

        self._tracker_service.configure_radar(
            radar_id=radar_id,
            lat=data.get("latitude", data.get("lat", 0.0)),
            lng=data.get("longitude", data.get("lng", 0.0)),
            altitude_m=data.get("altitude_m", data.get("alt_m", 0.0)),
            orientation_deg=data.get("orientation_deg", 0.0),
            max_range_m=data.get("max_range_m", 20000.0),
            min_range_m=data.get("min_range_m", 50.0),
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
        )

    # -- Cleanup loop ------------------------------------------------------

    def _cleanup_loop(self) -> None:
        """Background: prune stale radar tracks periodically."""
        while self._running:
            try:
                if self._tracker_service:
                    pruned = self._tracker_service.prune_stale()
                    if pruned > 0:
                        log.debug("Pruned %d stale radar tracks", pruned)
            except Exception as exc:
                log.error("Radar cleanup error: %s", exc)

            deadline = time.monotonic() + self._cleanup_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    # -- Route registration ------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for the radar tracker API."""
        if not self._app or not self._tracker_service:
            return

        from .routes import create_router

        router = create_router(self._tracker_service)
        self._app.include_router(router)
