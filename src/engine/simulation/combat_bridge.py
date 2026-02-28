# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CombatBridge — routes simulation combat actions to physical hardware via MQTT.

Dual-Authority Model
--------------------
The simulation engine remains the authoritative source for game state (score,
hit detection, damage, eliminations).  When the sim fires a projectile or
dispatches a unit, the CombatBridge sends the corresponding MQTT command to
the bound physical robot IN PARALLEL.  Hardware feedback (telemetry, ACKs) is
recorded alongside sim state for correlation, but does NOT override simulation
results.

This gives the operator two views:
  - "Simulation says hit" (deterministic, repeatable)
  - "Hardware says fired and turret confirmed aim" (real, noisy)

Over time, correlation between the two builds confidence in the simulation
model's accuracy against real-world physics.

Binding API
-----------
  bridge.bind_unit("turret-1", "real-turret-01")   # sim ID -> MQTT robot ID
  bridge.unbind_unit("turret-1")                     # remove binding
  bridge.get_mqtt_id("turret-1") -> "real-turret-01" # lookup
  bridge.get_sim_id("real-turret-01") -> "turret-1"  # reverse lookup

Event Handlers
--------------
  bridge.on_fire(event)      # sim fired -> MQTT aim + fire
  bridge.on_dispatch(event)  # sim dispatch -> MQTT dispatch
  bridge.on_patrol(event)    # sim patrol -> MQTT patrol
  bridge.on_recall(event)    # sim recall -> MQTT recall
  bridge.on_telemetry(mqtt_id, data)  # inbound HW telemetry

The bridge subscribes to EventBus events when start() is called.  It listens
for projectile_fired, unit_dispatched, unit_patrol, unit_recall and routes them
to the appropriate MQTT topic via the MQTTBridge.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.comms.mqtt_bridge import MQTTBridge
    from engine.simulation.engine import SimulationEngine

logger = logging.getLogger("engine.combat_bridge")


class CombatBridge:
    """Routes simulation combat actions to physical hardware via MQTT.

    Attributes:
        bindings: Dict mapping sim target ID -> MQTT robot ID.
        active: Whether the bridge is currently listening for events.
        command_log: List of command records for sim-vs-hardware correlation.
        MAX_LOG_ENTRIES: Maximum number of entries kept in command_log.
    """

    MAX_LOG_ENTRIES: int = 500

    def __init__(
        self,
        mqtt_bridge: MQTTBridge,
        event_bus: EventBus,
        sim_engine: SimulationEngine | None = None,
    ) -> None:
        self._mqtt = mqtt_bridge
        self._event_bus = event_bus
        self._sim_engine = sim_engine

        # sim_target_id -> mqtt_robot_id
        self._bindings: dict[str, str] = {}
        # mqtt_robot_id -> sim_target_id (reverse lookup)
        self._reverse: dict[str, str] = {}

        # Hardware state cache: sim_target_id -> latest telemetry dict
        self._hw_state: dict[str, dict] = {}

        # Command log for correlation
        self._command_log: list[dict] = []
        self._log_lock = threading.Lock()

        # Lifecycle
        self._active = False
        self._sub_thread: threading.Thread | None = None
        self._sub_queue = None

    # -- Properties ----------------------------------------------------------

    @property
    def bindings(self) -> dict[str, str]:
        """Return a copy of the sim_id -> mqtt_id bindings."""
        return dict(self._bindings)

    @property
    def active(self) -> bool:
        """Whether the bridge is actively listening for events."""
        return self._active

    @property
    def site_id(self) -> str:
        """Return the MQTT site ID from the underlying bridge."""
        return getattr(self._mqtt, "_site", "home")

    @property
    def command_log(self) -> list[dict]:
        """Return a copy of the command correlation log."""
        with self._log_lock:
            return list(self._command_log)

    # -- Binding API ---------------------------------------------------------

    def bind_unit(self, sim_target_id: str, mqtt_robot_id: str) -> None:
        """Bind a simulation target to a physical robot.

        Args:
            sim_target_id: The target_id from SimulationTarget.
            mqtt_robot_id: The MQTT robot ID (used in topic path).
        """
        # Clean up old reverse mapping if rebinding
        old_mqtt = self._bindings.get(sim_target_id)
        if old_mqtt is not None:
            self._reverse.pop(old_mqtt, None)

        self._bindings[sim_target_id] = mqtt_robot_id
        self._reverse[mqtt_robot_id] = sim_target_id
        logger.info(f"Bound sim:{sim_target_id} -> mqtt:{mqtt_robot_id}")

    def unbind_unit(self, sim_target_id: str) -> None:
        """Remove the binding for a simulation target.

        Does nothing if the sim_target_id is not bound.
        """
        mqtt_id = self._bindings.pop(sim_target_id, None)
        if mqtt_id is not None:
            self._reverse.pop(mqtt_id, None)
            self._hw_state.pop(sim_target_id, None)
            logger.info(f"Unbound sim:{sim_target_id}")

    def get_mqtt_id(self, sim_target_id: str) -> str | None:
        """Look up the MQTT robot ID for a simulation target."""
        return self._bindings.get(sim_target_id)

    def get_sim_id(self, mqtt_robot_id: str) -> str | None:
        """Reverse lookup: MQTT robot ID -> simulation target ID."""
        return self._reverse.get(mqtt_robot_id)

    # -- Hardware state ------------------------------------------------------

    def get_hardware_state(self, sim_target_id: str) -> dict | None:
        """Return the latest hardware telemetry for a bound sim target."""
        return self._hw_state.get(sim_target_id)

    def get_binding_status(self, sim_target_id: str) -> dict | None:
        """Return combined sim + hardware status for a binding.

        Returns None if the sim_target_id is not bound.
        """
        mqtt_id = self._bindings.get(sim_target_id)
        if mqtt_id is None:
            return None

        hw = self._hw_state.get(sim_target_id, {})

        # Get sim target position from engine if available
        sim_pos = {"x": 0.0, "y": 0.0}
        if self._sim_engine is not None:
            target = self._sim_engine.get_target(sim_target_id)
            if target is not None:
                sim_pos = {"x": target.position[0], "y": target.position[1]}

        return {
            "sim_id": sim_target_id,
            "mqtt_id": mqtt_id,
            "sim_position": sim_pos,
            "hw_position": hw.get("position", {"x": 0.0, "y": 0.0}),
            "hw_heading": hw.get("heading", 0.0),
            "hw_battery": hw.get("battery", 0.0),
            "hw_status": hw.get("status", "unknown"),
            "last_hw_update": hw.get("_timestamp", 0.0),
        }

    # -- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Start listening for simulation events on the EventBus.

        Subscribes to the EventBus and processes events in a background
        thread, routing relevant events to MQTT commands.
        """
        if self._active:
            return

        self._active = True
        self._sub_queue = self._event_bus.subscribe()
        self._sub_thread = threading.Thread(
            target=self._event_loop, name="combat-bridge", daemon=True
        )
        self._sub_thread.start()
        logger.info("CombatBridge started")

    def stop(self) -> None:
        """Stop listening for events and clean up."""
        if not self._active:
            return

        self._active = False
        if self._sub_queue is not None:
            self._event_bus.unsubscribe(self._sub_queue)
            self._sub_queue = None
        if self._sub_thread is not None:
            self._sub_thread.join(timeout=2.0)
            self._sub_thread = None
        logger.info("CombatBridge stopped")

    def _event_loop(self) -> None:
        """Background thread: read EventBus messages and route to MQTT."""
        while self._active and self._sub_queue is not None:
            try:
                msg = self._sub_queue.get(timeout=0.5)
                event_type = msg.get("type", "")
                data = msg.get("data", {})

                if event_type == "projectile_fired":
                    self.on_fire(data)
                elif event_type == "unit_dispatched":
                    self.on_dispatch(data)
                elif event_type == "unit_patrol":
                    self.on_patrol(data)
                elif event_type == "unit_recall":
                    self.on_recall(data)
            except Exception:
                pass  # queue.Empty or shutdown

    # -- Command handlers ----------------------------------------------------

    def on_dispatch(self, event: dict) -> None:
        """Called when a simulation unit is dispatched to a destination.

        Sends a dispatch command to the bound hardware unit via MQTT.

        Event keys:
            unit_id: str — simulation target ID
            destination: dict — {"x": float, "y": float}
        """
        sim_id = event.get("unit_id", "")
        mqtt_id = self._bindings.get(sim_id)
        if mqtt_id is None:
            return

        dest = event.get("destination", {})
        x = dest.get("x", 0.0)
        y = dest.get("y", 0.0)

        payload = {
            "command": "dispatch",
            "x": x,
            "y": y,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        delivered = self._publish_command(mqtt_id, payload)
        self._log_command("dispatch", sim_id, mqtt_id, payload, delivered)

    def on_recall(self, event: dict) -> None:
        """Called when a simulation unit is recalled.

        Sends a recall command to the bound hardware unit via MQTT.

        Event keys:
            unit_id: str — simulation target ID
        """
        sim_id = event.get("unit_id", "")
        mqtt_id = self._bindings.get(sim_id)
        if mqtt_id is None:
            return

        payload = {
            "command": "recall",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        delivered = self._publish_command(mqtt_id, payload)
        self._log_command("recall", sim_id, mqtt_id, payload, delivered)

    def on_patrol(self, event: dict) -> None:
        """Called when a simulation unit is set to patrol.

        Sends a patrol command with waypoints to the bound hardware unit.

        Event keys:
            unit_id: str — simulation target ID
            waypoints: list[dict] — [{"x": float, "y": float}, ...]
        """
        sim_id = event.get("unit_id", "")
        mqtt_id = self._bindings.get(sim_id)
        if mqtt_id is None:
            return

        waypoints = event.get("waypoints", [])
        payload = {
            "command": "patrol",
            "waypoints": waypoints,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        delivered = self._publish_command(mqtt_id, payload)
        self._log_command("patrol", sim_id, mqtt_id, payload, delivered)

    def on_fire(self, event: dict) -> None:
        """Called when a simulation unit fires a projectile.

        Sends fire command (and optionally aim) to the bound hardware unit.
        The bearing and elevation from shooter to target are computed and
        sent as part of the fire command.

        Event keys:
            shooter_id: str — simulation target ID of the firer
            target_id: str — simulation target ID of what was fired at
            target_position: dict — {"x": float, "y": float}
            shooter_position: dict — {"x": float, "y": float}
        """
        sim_id = event.get("shooter_id", "")
        mqtt_id = self._bindings.get(sim_id)
        if mqtt_id is None:
            return

        target_pos = event.get("target_position", {})
        shooter_pos = event.get("shooter_position", {})

        tx = target_pos.get("x", 0.0)
        ty = target_pos.get("y", 0.0)
        sx = shooter_pos.get("x", 0.0)
        sy = shooter_pos.get("y", 0.0)

        # Compute bearing from shooter to target (degrees, 0=north, clockwise)
        dx = tx - sx
        dy = ty - sy
        bearing = math.degrees(math.atan2(dx, dy)) % 360.0

        now = datetime.now(timezone.utc).isoformat()

        fire_payload = {
            "command": "fire",
            "target_x": tx,
            "target_y": ty,
            "bearing": round(bearing, 1),
            "timestamp": now,
        }

        delivered = self._publish_command(mqtt_id, fire_payload)
        self._log_command("fire", sim_id, mqtt_id, fire_payload, delivered,
                          extra={"target_id": event.get("target_id", "")})

    # -- Inbound telemetry ---------------------------------------------------

    def on_telemetry(self, mqtt_robot_id: str, telemetry: dict) -> None:
        """Handle inbound hardware telemetry from a bound robot.

        Records the hardware state for correlation with simulation state.
        Does NOT modify the simulation target (dual-authority: sim wins).

        Args:
            mqtt_robot_id: The MQTT robot ID.
            telemetry: Telemetry payload from the robot.
        """
        sim_id = self._reverse.get(mqtt_robot_id)
        if sim_id is None:
            return

        # Record hardware state (with timestamp)
        self._hw_state[sim_id] = {
            **telemetry,
            "_timestamp": time.time(),
        }

        # Publish correlation event on EventBus
        self._event_bus.publish("combat_bridge_telemetry", {
            "sim_id": sim_id,
            "mqtt_id": mqtt_robot_id,
            "telemetry": telemetry,
        })

    # -- Internal helpers ----------------------------------------------------

    def _publish_command(self, mqtt_robot_id: str, payload: dict) -> bool:
        """Publish a command to a robot's MQTT command topic.

        Returns True if the message was sent (MQTT connected), False otherwise.
        """
        if not getattr(self._mqtt, "connected", False):
            logger.debug(f"MQTT disconnected, dropping command to {mqtt_robot_id}")
            return False

        site = self.site_id
        topic = f"tritium/{site}/robots/{mqtt_robot_id}/command"

        try:
            self._mqtt.publish(topic, json.dumps(payload), qos=1)
            return True
        except Exception as e:
            logger.debug(f"MQTT publish failed for {mqtt_robot_id}: {e}")
            return False

    def _log_command(
        self,
        command: str,
        sim_id: str,
        mqtt_id: str,
        payload: dict,
        delivered: bool,
        extra: dict | None = None,
    ) -> None:
        """Record a command in the correlation log."""
        entry = {
            "command": command,
            "sim_id": sim_id,
            "mqtt_id": mqtt_id,
            "payload": payload,
            "mqtt_delivered": delivered,
            "timestamp": time.time(),
            "source": "simulation",
        }
        if extra:
            entry.update(extra)

        with self._log_lock:
            self._command_log.append(entry)
            # Prune to MAX_LOG_ENTRIES
            if len(self._command_log) > self.MAX_LOG_ENTRIES:
                self._command_log = self._command_log[-self.MAX_LOG_ENTRIES:]
