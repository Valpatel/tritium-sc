# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo notification generator — produces staggered alerts for an impressive first boot.

Publishes EventBus events that the NotificationManager auto-subscribes to
(ble:suspicious_device, ble:first_seen, geofence:enter, geofence:exit,
automation:alert).  Also generates periodic "intelligence" updates that
make the notification feed feel alive.

The first batch of notifications fires within 3 seconds of demo start,
then continues at randomized intervals (6-12s) to keep the feed active
without being overwhelming.

Usage::

    from engine.synthetic.demo_notifications import DemoNotificationGenerator

    gen = DemoNotificationGenerator(event_bus=bus)
    gen.start()
    gen.stop()
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

logger = logging.getLogger("synthetic.demo_notifications")

# Notification scenarios — each is a tuple of (event_type, data_dict).
# These are designed to trigger the NotificationManager's AUTO_EVENTS
# plus provide enough variety to impress on first boot.

_INITIAL_BURST: list[tuple[str, dict]] = [
    # First-seen devices to populate the feed immediately
    ("ble:first_seen", {
        "title": "New Device First Seen",
        "message": "iPhone-Matt (AA:BB:CC:11:22:01) detected for first time at North Gate",
        "source": "edge_tracker",
        "target_id": "ble_AA:BB:CC:11:22:01",
    }),
    ("ble:first_seen", {
        "title": "New Device First Seen",
        "message": "Unknown device DD:EE:FF:11:22:01 broadcasting — no name, unknown manufacturer",
        "source": "edge_tracker",
        "target_id": "ble_DD:EE:FF:11:22:01",
        "severity": "warning",
    }),
    ("ble:first_seen", {
        "title": "New Device First Seen",
        "message": "Tesla-Key (AA:BB:CC:11:22:10) detected — automotive BLE beacon",
        "source": "edge_tracker",
        "target_id": "ble_AA:BB:CC:11:22:10",
    }),
    ("automation:alert", {
        "title": "Demo Mode Active",
        "message": "Synthetic sensor network online: 12 BLE devices, 5 mesh nodes, 4 cameras, 3 robots patrolling",
        "source": "demo_controller",
        "severity": "info",
    }),
]

_SUSPICIOUS_DEVICE_POOL: list[dict] = [
    {
        "message": "Unknown BLE device DD:EE:FF:11:22:02 lingering near South Lot for 180s — possible surveillance",
        "target_id": "ble_DD:EE:FF:11:22:02",
        "severity": "warning",
    },
    {
        "message": "Randomized MAC detected (locally-administered bit set) — device is spoofing its identity",
        "target_id": "ble_DD:EE:FF:11:22:03",
        "severity": "warning",
    },
    {
        "message": "BLE device DD:EE:FF:11:22:04 disappeared and reappeared with new RSSI — possible relay attack",
        "target_id": "ble_DD:EE:FF:11:22:04",
        "severity": "warning",
    },
    {
        "message": "AirTag (AA:BB:CC:11:22:09) in proximity for 45 min with no paired phone — potential tracker",
        "target_id": "ble_AA:BB:CC:11:22:09",
        "severity": "warning",
    },
]

_GEOFENCE_POOL: list[tuple[str, dict]] = [
    ("geofence:enter", {
        "zone_name": "Restricted Area",
        "zone_type": "restricted",
        "target_id": "ble_DD:EE:FF:11:22:01",
        "source": "geofence_engine",
    }),
    ("geofence:exit", {
        "zone_name": "Patrol Sector",
        "zone_type": "monitored",
        "target_id": "robot_rover_01",
        "source": "geofence_engine",
    }),
    ("geofence:enter", {
        "zone_name": "Patrol Sector",
        "zone_type": "monitored",
        "target_id": "ble_AA:BB:CC:11:22:02",
        "source": "geofence_engine",
    }),
    ("geofence:enter", {
        "zone_name": "Restricted Area",
        "zone_type": "restricted",
        "target_id": "det_person_003",
        "source": "geofence_engine",
    }),
]

_AUTOMATION_POOL: list[dict] = [
    {
        "title": "Correlation Match",
        "message": "BLE phone AA:BB:CC:11:22:01 and camera detection person_002 fused — same entity at (37.7750, -122.4188)",
        "source": "correlator",
        "severity": "info",
    },
    {
        "title": "Behavioral Alert",
        "message": "Vehicle detected loitering at South Lot for 12 minutes — unusual pattern",
        "source": "behavioral_intelligence",
        "severity": "warning",
    },
    {
        "title": "Sensor Fusion Update",
        "message": "3 targets now tracked with multi-sensor dossiers (BLE + camera + mesh)",
        "source": "fusion_engine",
        "severity": "info",
    },
    {
        "title": "Patrol Report",
        "message": "Rover-01 completed patrol sector sweep — 4 new detections logged",
        "source": "robot_demo",
        "severity": "info",
    },
    {
        "title": "Network Intel",
        "message": "WiFi probe request from 'FreeWiFi_Guest' SSID — known rogue AP signature",
        "source": "wifi_fingerprint",
        "severity": "warning",
    },
    {
        "title": "Camera Analytics",
        "message": "East Alley camera: 3 persons, 1 dog, 1 bicycle detected in last 30s",
        "source": "yolo_detector",
        "severity": "info",
    },
    {
        "title": "Drone Overwatch",
        "message": "Drone-01 altitude 15m — thermal signature detected near building NE",
        "source": "robot_demo",
        "severity": "info",
    },
    {
        "title": "Acoustic Detection",
        "message": "Vehicle engine sound classified: large truck, heading westbound on main road",
        "source": "acoustic",
        "severity": "info",
    },
    {
        "title": "Mesh Network",
        "message": "Meshtastic node Rover-Alpha reporting 8 hops, 92% battery — relay chain stable",
        "source": "meshtastic",
        "severity": "info",
    },
]


class DemoNotificationGenerator:
    """Generates staggered demo notifications that populate the alert feed.

    Fires an initial burst of 4 notifications within 3 seconds of start,
    then emits one notification every 6-12 seconds from rotating pools of
    suspicious devices, geofence events, and automation alerts.
    """

    def __init__(
        self,
        event_bus: EventBus,
        initial_delay: float = 1.5,
        interval_min: float = 6.0,
        interval_max: float = 12.0,
    ) -> None:
        self._event_bus = event_bus
        self._initial_delay = initial_delay
        self._interval_min = interval_min
        self._interval_max = interval_max
        self._running = False
        self._thread: threading.Thread | None = None
        self._rng = random.Random(7777)

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start the notification generator."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="demo-notif-gen",
        )
        self._thread.start()
        logger.info("Demo notification generator started")

    def stop(self) -> None:
        """Stop the notification generator."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _loop(self) -> None:
        """Main loop: burst then continuous."""
        # Short delay to let other generators initialize
        time.sleep(self._initial_delay)

        # Initial burst — 4 notifications in quick succession
        for event_type, data in _INITIAL_BURST:
            if not self._running:
                return
            self._event_bus.publish(event_type, data)
            time.sleep(0.5)

        # Continuous stream — rotate through pools
        pools = [
            ("ble:suspicious_device", _SUSPICIOUS_DEVICE_POOL),
            ("geofence", _GEOFENCE_POOL),
            ("automation:alert", _AUTOMATION_POOL),
        ]
        pool_idx = 0

        while self._running:
            interval = self._rng.uniform(self._interval_min, self._interval_max)
            # Sleep in small increments so stop() is responsive
            end_time = time.monotonic() + interval
            while self._running and time.monotonic() < end_time:
                time.sleep(0.5)

            if not self._running:
                break

            pool_name, pool_data = pools[pool_idx % len(pools)]
            pool_idx += 1

            if pool_name == "geofence":
                # Geofence pool has (event_type, data) tuples
                event_type, data = self._rng.choice(pool_data)
            elif pool_name == "ble:suspicious_device":
                event_type = pool_name
                data = dict(self._rng.choice(pool_data))
                data["title"] = "Suspicious BLE Device"
                data["source"] = "edge_tracker"
            else:
                event_type = pool_name
                data = dict(self._rng.choice(pool_data))

            self._event_bus.publish(event_type, data)
