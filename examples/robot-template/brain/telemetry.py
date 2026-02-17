"""Telemetry publisher — sends robot state to TRITIUM-SC via MQTT."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mqtt_client import RobotMQTTClient
    from .navigator import Navigator
    from .turret import TurretController
    from hardware.base import HardwareInterface


class TelemetryPublisher:
    """Publishes robot telemetry at a fixed rate."""

    def __init__(
        self,
        mqtt_client: RobotMQTTClient,
        hardware: HardwareInterface,
        navigator: Navigator,
        turret: TurretController,
        config: dict,
    ) -> None:
        self._mqtt = mqtt_client
        self._hw = hardware
        self._nav = navigator
        self._turret = turret
        self._interval = config.get("telemetry", {}).get("interval", 0.5)
        self._robot_name = config.get("robot_name", config.get("robot_id", "robot"))
        self._asset_type = config.get("asset_type", "rover")
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._publish_loop, daemon=True)
        self._thread.start()
        print(f"  Telemetry publishing every {self._interval}s")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._mqtt.publish_status("offline")

    def _publish_loop(self) -> None:
        while self._running:
            pos = self._hw.get_position()
            self._mqtt.publish_telemetry({
                "name": self._robot_name,
                "asset_type": self._asset_type,
                "position": {"x": pos[0], "y": pos[1]},
                "heading": self._hw.get_heading(),
                "speed": self._hw.get_speed(),
                "battery": self._hw.get_battery(),
                "status": self._nav.status,
                "turret": {
                    "pan": self._turret.pan,
                    "tilt": self._turret.tilt,
                },
            })
            time.sleep(self._interval)
