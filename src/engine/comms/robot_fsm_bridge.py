"""RobotFSMBridge — bridges real MQTT robots to the FSM system.

When a robot connects via MQTT (or a FakeRobot is used for testing),
this bridge:
  1. Creates a corresponding FSM based on the robot's asset_type.
  2. Maps robot telemetry status strings to FSM state transitions.
  3. When the engine sends commands (dispatch/patrol/recall), transitions
     the FSM and publishes state change events.
  4. Syncs FSM state back via EventBus so the UI and MQTT publisher
     can relay state to the physical robot.

Telemetry status -> FSM state mapping:
  - Rover:  idle->idle, moving->patrolling, patrolling->patrolling,
            returning->rtb
  - Drone:  idle->idle, moving->scouting, patrolling->scouting,
            returning->rtb
  - Turret: idle->idle (turrets have no movement states from telemetry)

The bridge does NOT replace the simulation engine's FSM system. It is a
parallel tracker for *real* robots whose state is reported externally via
telemetry, not computed internally by the engine tick loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from engine.simulation.state_machine import StateMachine
from engine.simulation.unit_states import create_fsm_for_type

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

logger = logging.getLogger("amy.robot_fsm_bridge")


# Maps (asset_type, telemetry_status) -> target FSM state name.
# If telemetry status is not in this map, no transition is forced.
_ROVER_STATUS_MAP: dict[str, str] = {
    "idle": "idle",
    "moving": "patrolling",
    "patrolling": "patrolling",
    "returning": "rtb",
}

_DRONE_STATUS_MAP: dict[str, str] = {
    "idle": "idle",
    "moving": "scouting",
    "patrolling": "scouting",
    "returning": "rtb",
}

_TURRET_STATUS_MAP: dict[str, str] = {
    "idle": "idle",
}

# Rover-like types that share the rover status map
_ROVER_TYPES = {"rover", "tank", "apc"}
_DRONE_TYPES = {"drone", "scout_drone"}
_TURRET_TYPES = {"turret", "heavy_turret", "missile_turret"}

# Command -> target FSM state mapping per type category
_ROVER_COMMAND_MAP: dict[str, str] = {
    "dispatch": "patrolling",
    "patrol": "patrolling",
    "recall": "rtb",
}

_DRONE_COMMAND_MAP: dict[str, str] = {
    "dispatch": "scouting",
    "patrol": "scouting",
    "recall": "rtb",
}


def _get_status_map(asset_type: str) -> dict[str, str]:
    """Return the telemetry status -> FSM state map for an asset type."""
    if asset_type in _ROVER_TYPES:
        return _ROVER_STATUS_MAP
    if asset_type in _DRONE_TYPES:
        return _DRONE_STATUS_MAP
    if asset_type in _TURRET_TYPES:
        return _TURRET_STATUS_MAP
    return {}


def _get_command_map(asset_type: str) -> dict[str, str]:
    """Return the command -> FSM state map for an asset type."""
    if asset_type in _ROVER_TYPES:
        return _ROVER_COMMAND_MAP
    if asset_type in _DRONE_TYPES:
        return _DRONE_COMMAND_MAP
    return {}


class _RobotRecord:
    """Internal record for a registered robot."""

    __slots__ = ("robot_id", "asset_type", "alliance", "fsm", "info")

    def __init__(
        self,
        robot_id: str,
        asset_type: str,
        alliance: str,
        fsm: StateMachine | None,
    ) -> None:
        self.robot_id = robot_id
        self.asset_type = asset_type
        self.alliance = alliance
        self.fsm = fsm
        self.info: dict = {
            "robot_id": robot_id,
            "asset_type": asset_type,
            "alliance": alliance,
            "lat": 0.0,
            "lng": 0.0,
            "heading": 0.0,
            "speed": 0.0,
            "battery": 1.0,
            "status": "idle",
        }


class RobotFSMBridge:
    """Bridges real MQTT robots to the simulation FSM system."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._robots: dict[str, _RobotRecord] = {}

    def register_robot(
        self,
        robot_id: str,
        asset_type: str = "rover",
        alliance: str = "friendly",
    ) -> None:
        """Register a robot and create its FSM.

        If the robot is already registered, this is a no-op (does not
        reset existing FSM state).
        """
        if robot_id in self._robots:
            return

        fsm = create_fsm_for_type(asset_type, alliance=alliance)
        if fsm is not None:
            # Tick once with empty context to trigger on_enter for initial state
            fsm.tick(0.0, {})

        record = _RobotRecord(robot_id, asset_type, alliance, fsm)
        self._robots[robot_id] = record
        logger.debug(f"Registered robot {robot_id} ({asset_type}) with FSM")

    def unregister_robot(self, robot_id: str) -> None:
        """Remove a robot and its FSM."""
        self._robots.pop(robot_id, None)

    def clear_all(self) -> None:
        """Remove all robots and FSMs."""
        self._robots.clear()

    def get_fsm(self, robot_id: str) -> StateMachine | None:
        """Return the FSM for a robot, or None if not registered / no FSM."""
        record = self._robots.get(robot_id)
        if record is None:
            return None
        return record.fsm

    def get_fsm_state(self, robot_id: str) -> str | None:
        """Return current FSM state name for a robot, or None."""
        record = self._robots.get(robot_id)
        if record is None:
            return None
        if record.fsm is None:
            return None
        return record.fsm.current_state

    def get_robot_info(self, robot_id: str) -> dict | None:
        """Return last known telemetry info for a robot."""
        record = self._robots.get(robot_id)
        if record is None:
            return None
        return dict(record.info)

    def get_all_states(self) -> dict[str, str | None]:
        """Return dict of robot_id -> current FSM state for all robots."""
        return {
            rid: (rec.fsm.current_state if rec.fsm else None)
            for rid, rec in self._robots.items()
        }

    @property
    def robot_ids(self) -> list[str]:
        """List of all registered robot IDs."""
        return list(self._robots.keys())

    def on_telemetry(self, robot_id: str, payload: dict) -> None:
        """Process incoming telemetry from a robot.

        Auto-registers the robot if not already known (using asset_type
        from the payload, defaulting to 'rover').

        Maps the telemetry 'status' field to the appropriate FSM state.
        """
        record = self._robots.get(robot_id)
        if record is None:
            asset_type = payload.get("asset_type", "rover")
            alliance = payload.get("alliance", "friendly")
            self.register_robot(robot_id, asset_type=asset_type, alliance=alliance)
            record = self._robots[robot_id]

        # Update stored info
        for key in ("lat", "lng", "heading", "speed", "battery", "status",
                     "alt", "motor_temps", "asset_type", "alliance"):
            if key in payload:
                record.info[key] = payload[key]

        # Map telemetry status to FSM state
        status = payload.get("status", "")
        if status and record.fsm is not None:
            status_map = _get_status_map(record.asset_type)
            target_state = status_map.get(status)
            if target_state is not None:
                self._force_fsm_state(record, target_state)

    def on_command(
        self,
        robot_id: str,
        command: str,
        params: dict | None = None,
    ) -> None:
        """Process a command being sent to a robot.

        Transitions the FSM to the appropriate state and publishes
        events on the EventBus.
        """
        params = params or {}
        record = self._robots.get(robot_id)
        if record is None:
            return

        # Publish command event
        self._event_bus.publish("robot_fsm_command", {
            "robot_id": robot_id,
            "command": command,
            "params": params,
        })

        # Map command to FSM state
        if record.fsm is not None:
            command_map = _get_command_map(record.asset_type)
            target_state = command_map.get(command)
            if target_state is not None:
                self._force_fsm_state(record, target_state)

    def _force_fsm_state(self, record: _RobotRecord, target_state: str) -> None:
        """Force an FSM into a specific state, publishing change events.

        This bypasses normal condition-based transitions because the real
        robot's state is authoritative — we mirror it, not compute it.
        """
        fsm = record.fsm
        if fsm is None:
            return

        old_state = fsm.current_state
        if old_state == target_state:
            return

        # Force transition by calling internal _do_transition
        if target_state in fsm._states:
            fsm._do_transition(target_state, {})
            logger.debug(
                f"Robot {record.robot_id} FSM: {old_state} -> {target_state}"
            )
            self._event_bus.publish("robot_fsm_state_change", {
                "robot_id": record.robot_id,
                "old_state": old_state,
                "new_state": target_state,
                "asset_type": record.asset_type,
            })

    @staticmethod
    def build_command_payload(command: str, params: dict | None = None) -> dict:
        """Build an MQTT-compatible command payload dict.

        Convenience method for constructing command messages that can be
        JSON-serialized and published to the robot's command topic.
        """
        params = params or {}
        payload: dict = {
            "command": command,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if command == "dispatch":
            payload["lat"] = params.get("lat", 0.0)
            payload["lng"] = params.get("lng", 0.0)
        elif command == "patrol":
            waypoints = params.get("waypoints", [])
            payload["waypoints"] = [
                {"lat": wp[0], "lng": wp[1]} if isinstance(wp, (list, tuple)) else wp
                for wp in waypoints
            ]
        elif command == "recall":
            pass  # No extra params needed
        return payload
