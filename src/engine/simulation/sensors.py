"""SensorSimulator -- virtual sensor network that reacts to nearby targets.

Sensors (motion detectors, door sensors, tripwires) are placed in the scenario
and check each tick whether any target is within their detection radius.
Activations are published to the EventBus and optionally to MQTT.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus


@dataclass
class SensorDevice:
    sensor_id: str
    name: str
    sensor_type: str  # "motion", "door", "tripwire"
    position: tuple[float, float]  # (x, z) in local meters
    radius: float
    active: bool = False
    last_triggered: float = 0.0
    triggered_by: str = ""


class SensorSimulator:
    """Tick-driven sensor network.  Call ``tick(dt, targets)`` from the engine."""

    DEBOUNCE_S = 3.0  # Don't re-trigger within 3s

    def __init__(self, event_bus: EventBus, mqtt_bridge=None, site_id: str = "home"):
        self._sensors: list[SensorDevice] = []
        self._event_bus = event_bus
        self._mqtt = mqtt_bridge
        self._site_id = site_id

    def set_event_bus(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def add_sensor(
        self,
        sensor_id: str,
        name: str,
        sensor_type: str,
        position: tuple[float, float],
        radius: float,
    ) -> None:
        self._sensors.append(SensorDevice(
            sensor_id=sensor_id,
            name=name,
            sensor_type=sensor_type,
            position=position,
            radius=radius,
        ))

    @property
    def sensors(self) -> list[SensorDevice]:
        return list(self._sensors)

    # ------------------------------------------------------------------

    def tick(self, dt: float, targets) -> None:
        """Check all sensors against target positions.  Called from engine tick."""
        import math

        now = time.monotonic()

        for sensor in self._sensors:
            nearby = []
            for t in targets:
                if t.status in ("destroyed", "eliminated", "despawned", "escaped"):
                    continue
                dx = t.position[0] - sensor.position[0]
                dy = t.position[1] - sensor.position[1]
                dist = math.hypot(dx, dy)
                if dist <= sensor.radius:
                    nearby.append(t)

            if nearby and not sensor.active:
                if now - sensor.last_triggered >= self.DEBOUNCE_S:
                    sensor.active = True
                    sensor.last_triggered = now
                    sensor.triggered_by = nearby[0].name
                    self._publish_activation(sensor, nearby[0])
            elif not nearby and sensor.active:
                sensor.active = False
                self._publish_deactivation(sensor)

    # ------------------------------------------------------------------

    def _publish_activation(self, sensor: SensorDevice, trigger_target) -> None:
        event = {
            "sensor_id": sensor.sensor_id,
            "name": sensor.name,
            "type": sensor.sensor_type,
            "triggered_by": trigger_target.name,
            "target_id": trigger_target.target_id,
            "position": {"x": sensor.position[0], "z": sensor.position[1]},
        }
        self._event_bus.publish("sensor_triggered", event)
        if self._mqtt:
            try:
                import json
                self._mqtt.publish(
                    f"tritium/{self._site_id}/sensors/{sensor.sensor_id}/events",
                    json.dumps(event),
                )
            except Exception:
                pass
        # Also publish CoT XML event for TAK interop
        try:
            from engine.comms.mqtt_cot import sensor_event_to_cot
            cot_event = {
                "sensor_type": sensor.sensor_type,
                "lat": sensor.position[0],
                "lng": sensor.position[1],
                "triggered_by": trigger_target.name,
                "timestamp": "",
            }
            cot_xml = sensor_event_to_cot(sensor.sensor_id, cot_event)
            self._event_bus.publish("sensor_triggered_cot", {
                "sensor_id": sensor.sensor_id,
                "cot_xml": cot_xml,
            })
        except Exception:
            pass

    def _publish_deactivation(self, sensor: SensorDevice) -> None:
        event = {
            "sensor_id": sensor.sensor_id,
            "name": sensor.name,
            "type": sensor.sensor_type,
            "position": {"x": sensor.position[0], "z": sensor.position[1]},
        }
        self._event_bus.publish("sensor_cleared", event)
