# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Telemetry publisher — sends rich robot state to TRITIUM-SC via MQTT.

Publishes position, heading, speed, battery (with voltage/current/temp),
IMU, odometry, motor temps, and elevation. All data flows through MQTT
to Amy's target tracker for unified situational awareness.
"""

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

            # Core telemetry (compatible with existing bridge)
            data = {
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
            }

            # Extended telemetry (simulation or real sensors)
            try:
                bat_state = self._hw.get_battery_state()
                data["battery_state"] = {
                    "charge_pct": bat_state.charge_pct,
                    "voltage": bat_state.voltage,
                    "current_draw": bat_state.current_draw,
                    "temperature_c": bat_state.temperature_c,
                }
            except (NotImplementedError, AttributeError):
                pass

            try:
                data["elevation"] = self._hw.get_elevation()
            except (NotImplementedError, AttributeError):
                pass

            try:
                imu = self._hw.get_imu()
                data["imu"] = {
                    "roll": imu.roll,
                    "pitch": imu.pitch,
                    "yaw": imu.yaw,
                    "accel_x": imu.accel_x,
                    "accel_y": imu.accel_y,
                    "accel_z": imu.accel_z,
                }
            except (NotImplementedError, AttributeError):
                pass

            try:
                data["odometry"] = self._hw.get_odometry()
            except (NotImplementedError, AttributeError):
                pass

            try:
                left_t, right_t = self._hw.get_motor_temps()
                data["motor_temps"] = {"left": left_t, "right": right_t}
            except (NotImplementedError, AttributeError):
                pass

            try:
                gps = self._hw.get_gps()
                if gps is not None:
                    data["gps"] = {
                        "lat": gps[0],
                        "lng": gps[1],
                        "altitude": gps[2],
                    }
            except (NotImplementedError, AttributeError):
                pass

            self._mqtt.publish_telemetry(data)
            time.sleep(self._interval)
