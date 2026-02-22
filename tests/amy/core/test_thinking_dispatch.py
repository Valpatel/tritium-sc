"""Integration tests for Amy's thinking dispatch — verify she can command units.

Tests that parse_motor_output correctly handles dispatch/escalate/clear_threat
Lua calls, and that ThinkingThread._dispatch() actually updates simulation
targets and threat classifier state.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from amy.actions.lua_motor import MotorOutput, parse_motor_output
from amy.simulation.target import SimulationTarget
from amy.simulation.engine import SimulationEngine
from amy.brain.thinking import ThinkingThread


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. parse_motor_output — dispatch / escalate / clear_threat / patrol / alert
# ---------------------------------------------------------------------------

class TestParseDispatchActions:
    """Verify parse_motor_output handles all battlespace Lua calls."""

    def test_dispatch_basic(self):
        result = parse_motor_output('dispatch("rover-001", 5.0, 3.0)')
        assert result.valid
        assert result.action == "dispatch"
        assert result.params[0] == "rover-001"
        assert result.params[1] == 5.0
        assert result.params[2] == 3.0

    def test_dispatch_integer_coords(self):
        result = parse_motor_output('dispatch("rover-001", 5, 3)')
        assert result.valid
        assert result.action == "dispatch"
        assert isinstance(result.params[1], (int, float))
        assert isinstance(result.params[2], (int, float))

    def test_dispatch_negative_coords(self):
        result = parse_motor_output('dispatch("drone-002", -10.5, -20.0)')
        assert result.valid
        assert result.params[1] == -10.5
        assert result.params[2] == -20.0

    def test_dispatch_coords_clamped_to_30(self):
        result = parse_motor_output('dispatch("rover-001", 50.0, -50.0)')
        assert result.valid
        assert result.params[1] == 30.0
        assert result.params[2] == -30.0

    def test_dispatch_wrong_param_count(self):
        result = parse_motor_output('dispatch("rover-001", 5.0)')
        assert not result.valid

    def test_dispatch_non_string_target(self):
        result = parse_motor_output('dispatch(42, 5.0, 3.0)')
        assert not result.valid

    def test_escalate_basic(self):
        result = parse_motor_output('escalate("hostile-001", "hostile")')
        assert result.valid
        assert result.action == "escalate"
        assert result.params[0] == "hostile-001"
        assert result.params[1] == "hostile"

    def test_escalate_suspicious(self):
        result = parse_motor_output('escalate("target-x", "suspicious")')
        assert result.valid
        assert result.params[1] == "suspicious"

    def test_escalate_unknown(self):
        result = parse_motor_output('escalate("target-x", "unknown")')
        assert result.valid
        assert result.params[1] == "unknown"

    def test_escalate_invalid_level(self):
        result = parse_motor_output('escalate("target-x", "friendly")')
        assert not result.valid
        assert "level must be" in result.error

    def test_clear_threat_basic(self):
        result = parse_motor_output('clear_threat("hostile-001")')
        assert result.valid
        assert result.action == "clear_threat"
        assert result.params[0] == "hostile-001"

    def test_clear_threat_non_string(self):
        result = parse_motor_output('clear_threat(42)')
        assert not result.valid

    def test_alert_basic(self):
        result = parse_motor_output('alert("target-001", "suspicious movement")')
        assert result.valid
        assert result.action == "alert"
        assert result.params[0] == "target-001"
        assert result.params[1] == "suspicious movement"

    def test_patrol_basic(self):
        result = parse_motor_output('patrol("rover-001", "[[1,2],[3,4],[5,6]]")')
        assert result.valid
        assert result.action == "patrol"
        assert result.params[0] == "rover-001"
        wps = json.loads(result.params[1])
        assert len(wps) == 3

    def test_patrol_invalid_json(self):
        result = parse_motor_output('patrol("rover-001", "not json")')
        assert not result.valid
        assert "JSON" in result.error

    def test_patrol_empty_waypoints(self):
        result = parse_motor_output('patrol("rover-001", "[]")')
        assert not result.valid
        assert "non-empty" in result.error


# ---------------------------------------------------------------------------
# 2. ThinkingThread._dispatch — dispatch action updates sim target waypoints
# ---------------------------------------------------------------------------

class TestDispatchHandler:
    """Verify _dispatch() actually moves simulation units."""

    def _make_thinking(self, sim_engine=None, threat_classifier=None, auto_dispatcher=None):
        commander = MagicMock()
        commander.sensorium = MagicMock()
        commander.event_bus = MagicMock()
        commander.simulation_engine = sim_engine
        commander.threat_classifier = threat_classifier
        commander.auto_dispatcher = auto_dispatcher
        tt = ThinkingThread(commander)
        return tt, commander

    def _make_engine(self):
        bus = MagicMock()
        engine = SimulationEngine(bus)
        return engine

    def test_dispatch_sets_waypoints_on_friendly(self):
        engine = self._make_engine()
        rover = SimulationTarget(
            target_id="rover-001",
            name="Rover Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
        )
        engine.add_target(rover)

        tt, cmd = self._make_thinking(sim_engine=engine)
        result = MotorOutput(
            action="dispatch", params=["rover-001", 5.0, 3.0], valid=True
        )
        tt._dispatch(result)

        # Verify waypoints were set
        target = engine.get_target("rover-001")
        assert target.waypoints == [(5.0, 3.0)]
        assert target._waypoint_index == 0
        # Verify sensorium got a dispatch message
        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("Dispatching" in c for c in push_calls)
        # Verify event bus got a dispatch event
        cmd.event_bus.publish.assert_called_once_with(
            "amy_dispatch",
            {
                "target_id": "rover-001",
                "name": "Rover Alpha",
                "destination": {"x": 5.0, "y": 3.0},
            },
        )

    def test_dispatch_refuses_hostile_unit(self):
        engine = self._make_engine()
        hostile = SimulationTarget(
            target_id="hostile-001",
            name="Intruder Alpha",
            alliance="hostile",
            asset_type="person",
            position=(10.0, 10.0),
        )
        engine.add_target(hostile)

        tt, cmd = self._make_thinking(sim_engine=engine)
        result = MotorOutput(
            action="dispatch", params=["hostile-001", 5.0, 3.0], valid=True
        )
        tt._dispatch(result)

        # Should NOT change hostile waypoints
        target = engine.get_target("hostile-001")
        assert target.waypoints == []
        # Should push "cannot dispatch hostile" thought
        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("Cannot dispatch hostile" in c for c in push_calls)

    def test_dispatch_target_not_found(self):
        engine = self._make_engine()
        tt, cmd = self._make_thinking(sim_engine=engine)
        result = MotorOutput(
            action="dispatch", params=["nonexistent", 5.0, 3.0], valid=True
        )
        tt._dispatch(result)

        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("not found" in c for c in push_calls)

    def test_dispatch_no_simulation_engine(self):
        tt, cmd = self._make_thinking(sim_engine=None)
        result = MotorOutput(
            action="dispatch", params=["rover-001", 5.0, 3.0], valid=True
        )
        tt._dispatch(result)

        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("No simulation engine" in c for c in push_calls)


# ---------------------------------------------------------------------------
# 3. ThinkingThread._dispatch — escalate action changes classifier threat level
# ---------------------------------------------------------------------------

class TestEscalateHandler:
    """Verify _dispatch() updates threat classifier."""

    def _make_thinking(self, threat_classifier=None):
        commander = MagicMock()
        commander.sensorium = MagicMock()
        commander.event_bus = MagicMock()
        commander.simulation_engine = None
        commander.threat_classifier = threat_classifier
        commander.auto_dispatcher = None
        tt = ThinkingThread(commander)
        return tt, commander

    def test_escalate_calls_set_threat_level(self):
        classifier = MagicMock()
        tt, cmd = self._make_thinking(threat_classifier=classifier)
        result = MotorOutput(
            action="escalate", params=["hostile-001", "hostile"], valid=True
        )
        tt._dispatch(result)

        classifier.set_threat_level.assert_called_once_with("hostile-001", "hostile")
        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("Escalated" in c for c in push_calls)

    def test_escalate_suspicious(self):
        classifier = MagicMock()
        tt, cmd = self._make_thinking(threat_classifier=classifier)
        result = MotorOutput(
            action="escalate", params=["target-x", "suspicious"], valid=True
        )
        tt._dispatch(result)
        classifier.set_threat_level.assert_called_once_with("target-x", "suspicious")

    def test_escalate_no_classifier(self):
        tt, cmd = self._make_thinking(threat_classifier=None)
        result = MotorOutput(
            action="escalate", params=["hostile-001", "hostile"], valid=True
        )
        tt._dispatch(result)

        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("No threat classifier" in c for c in push_calls)


# ---------------------------------------------------------------------------
# 4. ThinkingThread._dispatch — clear_threat resets classifier + dispatcher
# ---------------------------------------------------------------------------

class TestClearThreatHandler:
    """Verify _dispatch() clears threat level and active dispatches."""

    def _make_thinking(self, threat_classifier=None, auto_dispatcher=None):
        commander = MagicMock()
        commander.sensorium = MagicMock()
        commander.event_bus = MagicMock()
        commander.simulation_engine = None
        commander.threat_classifier = threat_classifier
        commander.auto_dispatcher = auto_dispatcher
        tt = ThinkingThread(commander)
        return tt, commander

    def test_clear_threat_sets_level_none(self):
        classifier = MagicMock()
        tt, cmd = self._make_thinking(threat_classifier=classifier)
        result = MotorOutput(
            action="clear_threat", params=["hostile-001"], valid=True
        )
        tt._dispatch(result)

        classifier.set_threat_level.assert_called_once_with("hostile-001", "none")
        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("Cleared threat" in c for c in push_calls)

    def test_clear_threat_clears_dispatcher(self):
        classifier = MagicMock()
        dispatcher = MagicMock()
        tt, cmd = self._make_thinking(
            threat_classifier=classifier, auto_dispatcher=dispatcher
        )
        result = MotorOutput(
            action="clear_threat", params=["hostile-001"], valid=True
        )
        tt._dispatch(result)

        dispatcher.clear_dispatch.assert_called_once_with("hostile-001")

    def test_clear_threat_no_classifier(self):
        tt, cmd = self._make_thinking(threat_classifier=None)
        result = MotorOutput(
            action="clear_threat", params=["hostile-001"], valid=True
        )
        tt._dispatch(result)

        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("No threat classifier" in c for c in push_calls)


# ---------------------------------------------------------------------------
# 5. ThinkingThread._dispatch — patrol sets multi-waypoint route
# ---------------------------------------------------------------------------

class TestPatrolHandler:
    """Verify _dispatch() assigns patrol waypoints to simulation target."""

    def _make_thinking(self, sim_engine=None):
        commander = MagicMock()
        commander.sensorium = MagicMock()
        commander.event_bus = MagicMock()
        commander.simulation_engine = sim_engine
        commander.threat_classifier = None
        commander.auto_dispatcher = None
        tt = ThinkingThread(commander)
        return tt, commander

    def _make_engine(self):
        bus = MagicMock()
        return SimulationEngine(bus)

    def test_patrol_sets_waypoints(self):
        engine = self._make_engine()
        rover = SimulationTarget(
            target_id="rover-001",
            name="Rover Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
        )
        engine.add_target(rover)

        tt, cmd = self._make_thinking(sim_engine=engine)
        result = MotorOutput(
            action="patrol",
            params=["rover-001", "[[1,2],[3,4],[5,6]]"],
            valid=True,
        )
        tt._dispatch(result)

        target = engine.get_target("rover-001")
        assert target.waypoints == [(1, 2), (3, 4), (5, 6)]
        assert target._waypoint_index == 0

    def test_patrol_no_engine(self):
        tt, cmd = self._make_thinking(sim_engine=None)
        result = MotorOutput(
            action="patrol", params=["rover-001", "[[1,2]]"], valid=True
        )
        tt._dispatch(result)

        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("No simulation engine" in c for c in push_calls)

    def test_patrol_target_not_found(self):
        engine = self._make_engine()
        tt, cmd = self._make_thinking(sim_engine=engine)
        result = MotorOutput(
            action="patrol", params=["nonexistent", "[[1,2]]"], valid=True
        )
        tt._dispatch(result)

        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("not found" in c for c in push_calls)

    def test_patrol_bad_json(self):
        engine = self._make_engine()
        rover = SimulationTarget(
            target_id="rover-001",
            name="Rover Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
        )
        engine.add_target(rover)

        tt, cmd = self._make_thinking(sim_engine=engine)
        result = MotorOutput(
            action="patrol", params=["rover-001", "not json"], valid=True
        )
        tt._dispatch(result)

        push_calls = [str(c) for c in cmd.sensorium.push.call_args_list]
        assert any("Failed to parse" in c for c in push_calls)


# ---------------------------------------------------------------------------
# 6. ThinkingThread._dispatch — alert publishes event
# ---------------------------------------------------------------------------

class TestAlertHandler:
    """Verify _dispatch() publishes alert events."""

    def test_alert_publishes_event(self):
        commander = MagicMock()
        commander.sensorium = MagicMock()
        commander.event_bus = MagicMock()
        tt = ThinkingThread(commander)

        result = MotorOutput(
            action="alert", params=["target-001", "suspicious movement"], valid=True
        )
        tt._dispatch(result)

        commander.event_bus.publish.assert_called_once_with(
            "amy_alert",
            {"target_id": "target-001", "message": "suspicious movement"},
        )


# ---------------------------------------------------------------------------
# 7. Prompt verification — dispatch actions listed and context provided
# ---------------------------------------------------------------------------

class TestThinkingPrompt:
    """Verify the THINKING_SYSTEM_PROMPT includes dispatch capabilities."""

    def test_dispatch_action_listed(self):
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert 'dispatch("target_id", x, y)' in THINKING_SYSTEM_PROMPT

    def test_escalate_action_listed(self):
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert 'escalate("target_id", "level")' in THINKING_SYSTEM_PROMPT

    def test_clear_threat_action_listed(self):
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert 'clear_threat("target_id")' in THINKING_SYSTEM_PROMPT

    def test_patrol_action_listed(self):
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert 'patrol("target_id"' in THINKING_SYSTEM_PROMPT

    def test_alert_action_listed(self):
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert 'alert("target_id"' in THINKING_SYSTEM_PROMPT

    def test_prompt_mentions_commanding_units(self):
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert "command friendly units" in THINKING_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_hostile_tracking(self):
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert "hostile" in THINKING_SYSTEM_PROMPT.lower()
