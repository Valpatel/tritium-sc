# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""LPR (License Plate Recognition) Plugin — vehicle plate detection + OCR.

Stub plugin that provides the integration framework for automatic
license plate recognition. Ready to accept a real ALPR model (e.g.,
OpenALPR, Plate Recognizer, or a custom YOLO-based plate detector).

Current capabilities (stub mode):
- Watchlist management (add/remove/search plates)
- Recent detections log
- Plate search API
- Demo mode synthetic plate generation
- EventBus integration for plate alerts

When a real ALPR model is connected:
1. Camera frames arrive via MQTT or camera_feeds plugin
2. Plate detector crops plate regions from frames
3. OCR reads the plate text
4. Watchlist check triggers alerts for known plates
5. All detections feed into TargetTracker as vehicle targets

MQTT topics:
    IN:  tritium/{site}/cameras/{id}/frame    — camera JPEG frames
    OUT: tritium/{site}/lpr/{camera}/detection — plate detection events
    OUT: tritium/{site}/lpr/alert              — watchlist match alerts
"""

from __future__ import annotations

import logging
import random
import string
import time
import threading
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("lpr")

# How often to run the demo plate generator (seconds)
DEMO_INTERVAL_S = 10.0

# Maximum detection history
MAX_DETECTIONS = 1000

# US state abbreviations for synthetic plates
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


def _generate_plate() -> str:
    """Generate a realistic US-style license plate number."""
    formats = [
        lambda: f"{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}-{random.randint(1000, 9999)}",
        lambda: f"{random.randint(100, 999)}-{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}",
        lambda: f"{random.choice(string.ascii_uppercase)}{random.randint(10, 99)}-{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}",
    ]
    return random.choice(formats)()


class LPRPlugin(PluginInterface):
    """License Plate Recognition plugin with watchlist + detection pipeline.

    Stub implementation: provides API routes for watchlist management,
    plate search, and detection history. Can generate synthetic detections
    in demo mode. Ready for a real ALPR model backend.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._logger: logging.Logger = log
        self._running = False
        self._demo_mode = False
        self._demo_thread: Optional[threading.Thread] = None

        # Watchlist: plate_number -> metadata dict
        self._watchlist: dict[str, dict] = {}
        self._watchlist_lock = threading.Lock()

        # Detection history
        self._detections: list[dict] = []
        self._detections_lock = threading.Lock()

        # Stats
        self._stats = {
            "total_detections": 0,
            "watchlist_hits": 0,
            "unique_plates": 0,
            "cameras_active": 0,
        }
        self._seen_plates: set[str] = set()

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.lpr"

    @property
    def name(self) -> str:
        return "License Plate Recognition"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "background"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        settings = ctx.settings or {}
        self._demo_mode = settings.get("demo_mode", False)

        # Seed some watchlist entries for demo
        if self._demo_mode or settings.get("seed_watchlist", False):
            self._seed_watchlist()

        self._register_routes()
        self._logger.info("LPR plugin configured (demo_mode=%s)", self._demo_mode)

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        if self._demo_mode:
            self._demo_thread = threading.Thread(
                target=self._demo_loop,
                daemon=True,
                name="lpr-demo",
            )
            self._demo_thread.start()
            self._logger.info("LPR demo generator started")

        # Subscribe to EventBus for camera frames
        if self._event_bus:
            # In a real implementation, we'd subscribe to camera frame events
            # and run plate detection on each frame
            pass

        self._logger.info("LPR plugin started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._demo_thread and self._demo_thread.is_alive():
            self._demo_thread.join(timeout=3.0)

        self._logger.info("LPR plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Watchlist API -----------------------------------------------------

    def add_to_watchlist(
        self,
        plate_number: str,
        reason: str = "",
        priority: str = "normal",
        owner: str = "",
        vehicle_description: str = "",
        alert_on_match: bool = True,
    ) -> dict:
        """Add a plate to the watchlist."""
        plate = plate_number.upper().strip()
        entry = {
            "plate_number": plate,
            "reason": reason,
            "priority": priority,
            "owner": owner,
            "vehicle_description": vehicle_description,
            "alert_on_match": alert_on_match,
            "added_at": time.time(),
            "last_seen": None,
            "hit_count": 0,
        }
        with self._watchlist_lock:
            self._watchlist[plate] = entry
        self._logger.info("Added plate to watchlist: %s (%s)", plate, reason)
        return entry

    def remove_from_watchlist(self, plate_number: str) -> bool:
        """Remove a plate from the watchlist."""
        plate = plate_number.upper().strip()
        with self._watchlist_lock:
            if plate in self._watchlist:
                del self._watchlist[plate]
                return True
        return False

    def get_watchlist(self) -> list[dict]:
        """Get all watchlist entries."""
        with self._watchlist_lock:
            return list(self._watchlist.values())

    def check_watchlist(self, plate_number: str) -> Optional[dict]:
        """Check if a plate is on the watchlist."""
        plate = plate_number.upper().strip()
        with self._watchlist_lock:
            return self._watchlist.get(plate)

    # -- Detection API -----------------------------------------------------

    def record_detection(
        self,
        plate_number: str,
        camera_id: str = "",
        confidence: float = 0.0,
        bbox: Optional[list[int]] = None,
        vehicle_type: str = "",
        vehicle_color: str = "",
        location: Optional[tuple[float, float]] = None,
    ) -> dict:
        """Record a plate detection."""
        plate = plate_number.upper().strip()
        detection = {
            "plate_number": plate,
            "camera_id": camera_id,
            "confidence": confidence,
            "bbox": bbox,
            "vehicle_type": vehicle_type,
            "vehicle_color": vehicle_color,
            "location": location,
            "timestamp": time.time(),
            "watchlist_match": False,
        }

        # Check watchlist
        watchlist_entry = self.check_watchlist(plate)
        if watchlist_entry:
            detection["watchlist_match"] = True
            detection["watchlist_reason"] = watchlist_entry.get("reason", "")
            detection["watchlist_priority"] = watchlist_entry.get("priority", "normal")
            with self._watchlist_lock:
                watchlist_entry["last_seen"] = time.time()
                watchlist_entry["hit_count"] += 1
            self._stats["watchlist_hits"] += 1

            # Publish alert
            if self._event_bus and watchlist_entry.get("alert_on_match", True):
                self._event_bus.publish("lpr:watchlist_match", data={
                    "detection": detection,
                    "watchlist_entry": watchlist_entry,
                })
                self._logger.warning(
                    "WATCHLIST HIT: plate=%s reason=%s camera=%s",
                    plate, watchlist_entry.get("reason", ""), camera_id,
                )

        # Store detection
        with self._detections_lock:
            self._detections.append(detection)
            if len(self._detections) > MAX_DETECTIONS:
                self._detections = self._detections[-MAX_DETECTIONS:]

        self._stats["total_detections"] += 1
        self._seen_plates.add(plate)
        self._stats["unique_plates"] = len(self._seen_plates)

        # Publish detection event
        if self._event_bus:
            self._event_bus.publish("lpr:detection", data=detection)

        # Create vehicle target in tracker
        self._create_vehicle_target(detection)

        return detection

    def get_recent_detections(self, count: int = 50) -> list[dict]:
        """Get recent plate detections."""
        with self._detections_lock:
            return list(self._detections[-count:])

    def search_plates(self, query: str) -> list[dict]:
        """Search detection history for a plate number (prefix match)."""
        q = query.upper().strip()
        with self._detections_lock:
            matches = [d for d in self._detections if q in d["plate_number"]]
        return matches

    def get_stats(self) -> dict:
        """Get plugin statistics."""
        return {
            **self._stats,
            "watchlist_size": len(self._watchlist),
            "detection_history_size": len(self._detections),
            "demo_mode": self._demo_mode,
        }

    # -- Vehicle target creation -------------------------------------------

    def _create_vehicle_target(self, detection: dict) -> None:
        """Create/update a vehicle target in TargetTracker."""
        if self._tracker is None:
            return

        plate = detection["plate_number"]
        target_id = f"lpr_{plate.replace(' ', '_').replace('-', '_')}"

        try:
            from tritium_lib.tracking.target_tracker import TrackedTarget

            alliance = "unknown"
            if detection.get("watchlist_match"):
                priority = detection.get("watchlist_priority", "normal")
                alliance = "hostile" if priority == "high" else "unknown"

            location = detection.get("location") or (0.0, 0.0)

            with self._tracker._lock:
                if target_id in self._tracker._targets:
                    t = self._tracker._targets[target_id]
                    t.last_seen = time.monotonic()
                    if detection.get("location"):
                        t.position = location
                else:
                    self._tracker._targets[target_id] = TrackedTarget(
                        target_id=target_id,
                        name=f"Vehicle: {plate}",
                        alliance=alliance,
                        asset_type="vehicle_lpr",
                        position=location,
                        last_seen=time.monotonic(),
                        source="lpr",
                        position_source="camera",
                        position_confidence=detection.get("confidence", 0.5),
                        status=f"plate:{plate}",
                    )
        except Exception as exc:
            log.error("Failed to create LPR target: %s", exc)

    # -- Demo mode ---------------------------------------------------------

    def _demo_loop(self) -> None:
        """Generate synthetic plate detections for demo mode."""
        cameras = ["cam_north", "cam_south", "cam_east", "cam_gate"]
        vehicle_types = ["sedan", "suv", "truck", "van", "motorcycle", "pickup"]
        colors = ["black", "white", "silver", "red", "blue", "gray", "green"]

        while self._running:
            plate = _generate_plate()
            # 15% chance of hitting a watchlist plate
            if random.random() < 0.15 and self._watchlist:
                with self._watchlist_lock:
                    if self._watchlist:
                        plate = random.choice(list(self._watchlist.keys()))

            self.record_detection(
                plate_number=plate,
                camera_id=random.choice(cameras),
                confidence=round(random.uniform(0.6, 0.98), 2),
                bbox=[random.randint(100, 500), random.randint(200, 400),
                      random.randint(80, 200), random.randint(30, 60)],
                vehicle_type=random.choice(vehicle_types),
                vehicle_color=random.choice(colors),
                location=(
                    30.2672 + random.uniform(-0.005, 0.005),
                    -97.7431 + random.uniform(-0.005, 0.005),
                ),
            )

            # Sleep in small increments for responsive shutdown
            deadline = time.monotonic() + DEMO_INTERVAL_S
            while self._running and time.monotonic() < deadline:
                time.sleep(0.5)

    def _seed_watchlist(self) -> None:
        """Seed watchlist with example entries for demo."""
        entries = [
            ("ABC-1234", "Stolen vehicle report #2024-1892", "high", "John Doe", "Black Honda Civic 2019"),
            ("XYZ-9876", "Amber alert — suspect vehicle", "high", "Unknown", "White Ford F-150"),
            ("DEF-5678", "Parking violations x12", "normal", "Jane Smith", "Silver Toyota Camry"),
            ("GHI-3456", "Surveillance — known associate", "normal", "Mark Johnson", "Blue Chevrolet Malibu"),
            ("JKL-7890", "Expired registration", "low", "Robert Wilson", "Red Nissan Altima"),
        ]
        for plate, reason, priority, owner, desc in entries:
            self.add_to_watchlist(
                plate_number=plate,
                reason=reason,
                priority=priority,
                owner=owner,
                vehicle_description=desc,
            )

    # -- Routes ------------------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for LPR management."""
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
