# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo mode controller — exercises the full pipeline with synthetic data.

Activates synthetic BLE, Meshtastic, and camera generators that publish
events through the real EventBus, proving end-to-end data flow without
any hardware.

Usage::

    from engine.synthetic.demo_mode import DemoController

    controller = DemoController(event_bus=bus, target_tracker=tracker)
    controller.start()
    print(controller.status())
    controller.stop()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.synthetic.data_generators import (
    BLEScanGenerator,
    CameraDetectionGenerator,
    MeshtasticNodeGenerator,
)

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.tactical.target_tracker import TargetTracker

logger = logging.getLogger("synthetic.demo_mode")


@dataclass
class GeneratorStats:
    """Snapshot of a running generator's state."""
    name: str
    running: bool
    started_at: float | None = None


class DemoController:
    """Orchestrates synthetic data generators for demo mode.

    Creates BLE, Meshtastic, and camera generators and wires them
    to the EventBus so data flows through the real pipeline.
    """

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker | None = None,
        ble_device_count: int = 5,
        mesh_node_count: int = 3,
        camera_count: int = 2,
    ) -> None:
        self._event_bus = event_bus
        self._target_tracker = target_tracker
        self._ble_device_count = ble_device_count
        self._mesh_node_count = mesh_node_count
        self._camera_count = camera_count

        self._active = False
        self._started_at: float | None = None

        self._ble_gen: BLEScanGenerator | None = None
        self._mesh_gen: MeshtasticNodeGenerator | None = None
        self._camera_gens: list[CameraDetectionGenerator] = []

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        """Start all synthetic generators."""
        if self._active:
            logger.warning("Demo mode already active")
            return

        logger.info("Starting demo mode...")
        self._started_at = time.monotonic()

        # BLE scanner
        self._ble_gen = BLEScanGenerator(
            interval=5.0,
            max_devices=self._ble_device_count,
            node_id="demo-scanner-01",
        )
        self._ble_gen.start(self._event_bus)

        # Meshtastic nodes
        self._mesh_gen = MeshtasticNodeGenerator(
            interval=10.0,
            node_count=self._mesh_node_count,
        )
        self._mesh_gen.start(self._event_bus)

        # Camera detections
        self._camera_gens = []
        for i in range(self._camera_count):
            cam = CameraDetectionGenerator(
                interval=1.0,
                camera_id=f"demo-cam-{i + 1:02d}",
                max_objects=4,
            )
            cam.start(self._event_bus)
            self._camera_gens.append(cam)

        self._active = True
        self._event_bus.publish("demo:started", {
            "ble_devices": self._ble_device_count,
            "mesh_nodes": self._mesh_node_count,
            "cameras": self._camera_count,
        })
        logger.info(
            f"Demo mode active: {self._ble_device_count} BLE devices, "
            f"{self._mesh_node_count} mesh nodes, {self._camera_count} cameras"
        )

    def stop(self) -> None:
        """Stop all synthetic generators."""
        if not self._active:
            logger.warning("Demo mode not active")
            return

        logger.info("Stopping demo mode...")

        if self._ble_gen is not None:
            self._ble_gen.stop()
            self._ble_gen = None

        if self._mesh_gen is not None:
            self._mesh_gen.stop()
            self._mesh_gen = None

        for cam in self._camera_gens:
            cam.stop()
        self._camera_gens = []

        self._active = False
        self._event_bus.publish("demo:stopped", {})
        logger.info("Demo mode stopped")

    def status(self) -> dict:
        """Return current demo mode status."""
        generators = []

        if self._ble_gen is not None:
            generators.append({
                "name": "BLEScanGenerator",
                "running": self._ble_gen.running,
                "config": {
                    "max_devices": self._ble_device_count,
                    "interval": 5.0,
                },
            })

        if self._mesh_gen is not None:
            generators.append({
                "name": "MeshtasticNodeGenerator",
                "running": self._mesh_gen.running,
                "config": {
                    "node_count": self._mesh_node_count,
                    "interval": 10.0,
                },
            })

        for i, cam in enumerate(self._camera_gens):
            generators.append({
                "name": f"CameraDetectionGenerator",
                "camera_id": f"demo-cam-{i + 1:02d}",
                "running": cam.running,
                "config": {
                    "max_objects": 4,
                    "interval": 1.0,
                },
            })

        uptime = None
        if self._started_at is not None and self._active:
            uptime = round(time.monotonic() - self._started_at, 1)

        return {
            "active": self._active,
            "uptime_s": uptime,
            "generators": generators,
            "generator_count": len(generators),
        }
