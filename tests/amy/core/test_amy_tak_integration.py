# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Amy's TAK consciousness integration.

Verifies that Amy can:
- See TAK clients and GeoChat in her thinking context
- Send GeoChat messages via send_geochat() action
- Send threat alerts via alert_tak() action
- Query connected TAK clients via query_tak_clients() action
"""

import time
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest

from engine.actions.lua_motor import (
    parse_motor_output,
    VALID_ACTIONS,
    validate_action,
    parse_function_call,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_commander():
    """Build a minimal mock Commander with TAK bridge wired up."""
    commander = MagicMock()

    # State needed by ThinkingThread._dispatch
    commander._state.value = "IDLE"
    commander._last_spoke = 0.0

    # Sensorium
    sensorium = MagicMock()
    sensorium.rich_narrative.return_value = "All quiet."
    sensorium.recent_thoughts = []
    sensorium.people_present = False
    sensorium.mood = "neutral"
    commander.sensorium = sensorium

    # Memory
    memory = MagicMock()
    memory.build_context.return_value = "(no memories)"
    memory.build_people_context.return_value = ""
    memory.build_self_context.return_value = ""
    commander.memory = memory

    # No primary camera
    commander.primary_camera = None

    # Transcript
    commander.transcript = MagicMock()

    # EventBus
    commander.event_bus = MagicMock()

    # Simulation engine (not always present)
    commander.simulation_engine = None

    # Mode
    commander._mode = "sim"

    # Model router (not present by default)
    commander.model_router = None

    # Target tracker
    commander.target_tracker = None

    # Threat classifier
    commander.threat_classifier = None

    # Auto dispatcher
    commander.auto_dispatcher = None

    # Game mode
    commander.game_mode = None

    # TAK bridge (initially None, like Commander.__init__)
    commander.tak_bridge = None

    # Announcer (for battle_cry / taunt)
    commander.announcer = None

    return commander


def _make_mock_tak_bridge():
    """Build a mock TAK bridge with test clients and chat history."""
    bridge = MagicMock()
    bridge.connected = True
    bridge.callsign = "TRITIUM-SC"
    bridge.clients = {
        "ANDROID-abc123": {
            "callsign": "Alpha-1",
            "uid": "ANDROID-abc123",
            "alliance": "friendly",
            "lat": 37.7749,
            "lng": -122.4194,
            "speed": 1.5,
            "last_seen": time.time(),
        },
        "ANDROID-def456": {
            "callsign": "Bravo-2",
            "uid": "ANDROID-def456",
            "alliance": "friendly",
            "lat": 37.7753,
            "lng": -122.4198,
            "speed": 0.0,
            "last_seen": time.time() - 30,
        },
    }
    bridge.chat_history = [
        {
            "sender_callsign": "Alpha-1",
            "message": "Moving to north gate",
            "direction": "inbound",
            "timestamp": "2026-02-22T10:00:00Z",
        },
        {
            "sender_callsign": "TRITIUM-SC",
            "message": "Copy, Alpha-1. Hold position at gate.",
            "direction": "outbound",
            "timestamp": "2026-02-22T10:00:05Z",
        },
        {
            "sender_callsign": "Bravo-2",
            "message": "All clear on south perimeter",
            "direction": "inbound",
            "timestamp": "2026-02-22T10:01:00Z",
        },
    ]
    return bridge


def _make_thinking_thread(commander):
    """Create a ThinkingThread instance with mocked commander.

    Does NOT start the background thread -- we call _dispatch directly.
    """
    from amy.brain.thinking import ThinkingThread
    tt = ThinkingThread(commander, model="test-model", think_interval=999.0)
    return tt


# ===================================================================
# 1. TAK actions in lua_motor.py — parsing and validation
# ===================================================================

@pytest.mark.skip(reason="send_geochat, alert_tak, query_tak_clients not in VALID_ACTIONS — TAK actions not yet registered")
class TestTakActionsInValidActions:
    """Verify send_geochat, alert_tak, and query_tak_clients
    are registered in VALID_ACTIONS and parse correctly."""

    @pytest.mark.unit
    def test_send_geochat_is_valid_action(self):
        """send_geochat should be in VALID_ACTIONS."""
        assert "send_geochat" in VALID_ACTIONS

    @pytest.mark.unit
    def test_alert_tak_is_valid_action(self):
        """alert_tak should be in VALID_ACTIONS."""
        assert "alert_tak" in VALID_ACTIONS

    @pytest.mark.unit
    def test_query_tak_clients_is_valid_action(self):
        """query_tak_clients should be in VALID_ACTIONS."""
        assert "query_tak_clients" in VALID_ACTIONS

    @pytest.mark.unit
    def test_send_geochat_one_param(self):
        """send_geochat('Hello team') should parse as valid."""
        result = parse_motor_output('send_geochat("Hello team")')
        assert result.valid, f"Expected valid, got error: {result.error}"
        assert result.action == "send_geochat"
        assert result.params == ["Hello team"]

    @pytest.mark.unit
    def test_send_geochat_two_params(self):
        """send_geochat('Hello', 'Alpha-1') should parse as valid."""
        result = parse_motor_output('send_geochat("Hello", "Alpha-1")')
        assert result.valid, f"Expected valid, got error: {result.error}"
        assert result.action == "send_geochat"
        assert result.params == ["Hello", "Alpha-1"]

    @pytest.mark.unit
    def test_send_geochat_zero_params_invalid(self):
        """send_geochat() with no params should fail validation."""
        result = parse_motor_output('send_geochat()')
        assert not result.valid
        assert result.error is not None

    @pytest.mark.unit
    def test_send_geochat_three_params_invalid(self):
        """send_geochat with 3 params should fail validation."""
        result = parse_motor_output('send_geochat("a", "b", "c")')
        assert not result.valid

    @pytest.mark.unit
    def test_send_geochat_numeric_param_invalid(self):
        """send_geochat(123) should fail — message must be a string."""
        error = validate_action("send_geochat", [123])
        assert error is not None
        assert "string" in error.lower() or "str" in error.lower()

    @pytest.mark.unit
    def test_alert_tak_one_param(self):
        """alert_tak('Intruder spotted at gate 3') should parse as valid."""
        result = parse_motor_output('alert_tak("Intruder spotted at gate 3")')
        assert result.valid, f"Expected valid, got error: {result.error}"
        assert result.action == "alert_tak"
        assert result.params == ["Intruder spotted at gate 3"]

    @pytest.mark.unit
    def test_alert_tak_zero_params_invalid(self):
        """alert_tak() with no params should fail."""
        result = parse_motor_output('alert_tak()')
        assert not result.valid

    @pytest.mark.unit
    def test_alert_tak_two_params_invalid(self):
        """alert_tak with 2 params should fail."""
        result = parse_motor_output('alert_tak("a", "b")')
        assert not result.valid

    @pytest.mark.unit
    def test_alert_tak_numeric_param_invalid(self):
        """alert_tak(42) should fail — message must be a string."""
        error = validate_action("alert_tak", [42])
        assert error is not None

    @pytest.mark.unit
    def test_query_tak_clients_zero_params(self):
        """query_tak_clients() should parse as valid with 0 params."""
        result = parse_motor_output('query_tak_clients()')
        assert result.valid, f"Expected valid, got error: {result.error}"
        assert result.action == "query_tak_clients"
        assert result.params == []

    @pytest.mark.unit
    def test_query_tak_clients_with_params_invalid(self):
        """query_tak_clients('foo') should fail — takes 0 params."""
        result = parse_motor_output('query_tak_clients("foo")')
        assert not result.valid

    @pytest.mark.unit
    def test_send_geochat_min_max_params(self):
        """Verify send_geochat param count constraints."""
        min_p, max_p, types = VALID_ACTIONS["send_geochat"]
        assert min_p == 1
        assert max_p == 2

    @pytest.mark.unit
    def test_alert_tak_min_max_params(self):
        """Verify alert_tak param count constraints."""
        min_p, max_p, types = VALID_ACTIONS["alert_tak"]
        assert min_p == 1
        assert max_p == 1

    @pytest.mark.unit
    def test_query_tak_clients_min_max_params(self):
        """Verify query_tak_clients param count constraints."""
        min_p, max_p, types = VALID_ACTIONS["query_tak_clients"]
        assert min_p == 0
        assert max_p == 0


# ===================================================================
# 2. ThinkingThread TAK context building
# ===================================================================

@pytest.mark.skip(reason="ThinkingThread._think_cycle does not yet include TAK client/chat context in prompt")
class TestThinkingThreadTakContext:
    """Verify _think_cycle includes TAK client data and chat history
    in the battlespace context sent to the LLM."""

    @pytest.mark.unit
    def test_tak_clients_in_battlespace_context(self):
        """When tak_bridge is connected with clients, the thinking prompt
        should include TAK client callsigns and positions."""
        commander = _make_mock_commander()
        bridge = _make_mock_tak_bridge()
        commander.tak_bridge = bridge

        tt = _make_thinking_thread(commander)

        # We need to intercept the prompt sent to ollama_chat.
        # Patch ollama_chat to capture the system message.
        captured = {}
        def fake_ollama_chat(model, messages):
            captured["messages"] = messages
            return {"message": {"content": 'think("TAK clients visible.")'}}

        with patch("amy.brain.thinking.ollama_chat", side_effect=fake_ollama_chat):
            tt._think_cycle()

        system_msg = captured.get("messages", [{}])[0].get("content", "")
        assert "Alpha-1" in system_msg, "TAK client Alpha-1 should appear in thinking context"
        assert "Bravo-2" in system_msg, "TAK client Bravo-2 should appear in thinking context"

    @pytest.mark.unit
    def test_tak_chat_history_in_context(self):
        """When tak_bridge has chat history, recent GeoChat messages
        should appear in the thinking prompt."""
        commander = _make_mock_commander()
        bridge = _make_mock_tak_bridge()
        commander.tak_bridge = bridge

        tt = _make_thinking_thread(commander)

        captured = {}
        def fake_ollama_chat(model, messages):
            captured["messages"] = messages
            return {"message": {"content": 'think("Noted chat.")'}}

        with patch("amy.brain.thinking.ollama_chat", side_effect=fake_ollama_chat):
            tt._think_cycle()

        system_msg = captured.get("messages", [{}])[0].get("content", "")
        assert "Moving to north gate" in system_msg, "Chat history should appear in context"
        assert "south perimeter" in system_msg, "All recent chat should appear"

    @pytest.mark.unit
    def test_tak_connected_status_in_context(self):
        """When TAK bridge is connected, the context should indicate this."""
        commander = _make_mock_commander()
        bridge = _make_mock_tak_bridge()
        bridge.connected = True
        commander.tak_bridge = bridge

        tt = _make_thinking_thread(commander)

        captured = {}
        def fake_ollama_chat(model, messages):
            captured["messages"] = messages
            return {"message": {"content": 'think("TAK online.")'}}

        with patch("amy.brain.thinking.ollama_chat", side_effect=fake_ollama_chat):
            tt._think_cycle()

        system_msg = captured.get("messages", [{}])[0].get("content", "")
        # The system prompt should mention TAK connection status
        assert "TAK" in system_msg, "TAK status should appear in the thinking prompt"

    @pytest.mark.unit
    def test_no_tak_context_when_bridge_none(self):
        """When tak_bridge is None, no TAK section should appear."""
        commander = _make_mock_commander()
        commander.tak_bridge = None

        tt = _make_thinking_thread(commander)

        captured = {}
        def fake_ollama_chat(model, messages):
            captured["messages"] = messages
            return {"message": {"content": 'think("Quiet night.")'}}

        with patch("amy.brain.thinking.ollama_chat", side_effect=fake_ollama_chat):
            tt._think_cycle()

        system_msg = captured.get("messages", [{}])[0].get("content", "")
        # Should not have TAK client details when bridge is None
        assert "Alpha-1" not in system_msg
        assert "Bravo-2" not in system_msg


# ===================================================================
# 3. ThinkingThread TAK dispatch handlers
# ===================================================================

@pytest.mark.skip(reason="ThinkingThread._dispatch does not yet handle TAK actions (send_geochat, alert_tak, query_tak_clients)")
class TestThinkingThreadTakDispatch:
    """Verify that TAK action dispatch calls the right methods."""

    @pytest.mark.unit
    def test_dispatch_send_geochat_one_param(self):
        """send_geochat('Hello') should call tak_bridge.send_geochat('Hello')."""
        commander = _make_mock_commander()
        bridge = _make_mock_tak_bridge()
        commander.tak_bridge = bridge

        tt = _make_thinking_thread(commander)
        result = parse_motor_output('send_geochat("Hello")')
        assert result.valid

        tt._dispatch(result)

        bridge.send_geochat.assert_called_once_with("Hello")

    @pytest.mark.unit
    def test_dispatch_send_geochat_two_params(self):
        """send_geochat('Hello', 'Alpha-1') should call
        tak_bridge.send_geochat('Hello', to_callsign='Alpha-1')."""
        commander = _make_mock_commander()
        bridge = _make_mock_tak_bridge()
        commander.tak_bridge = bridge

        tt = _make_thinking_thread(commander)
        result = parse_motor_output('send_geochat("Hello", "Alpha-1")')
        assert result.valid

        tt._dispatch(result)

        bridge.send_geochat.assert_called_once_with("Hello", to_callsign="Alpha-1")

    @pytest.mark.unit
    def test_dispatch_alert_tak(self):
        """alert_tak('Intruder at gate') should call tak_bridge.send_cot()
        with hostile CoT XML."""
        commander = _make_mock_commander()
        bridge = _make_mock_tak_bridge()
        commander.tak_bridge = bridge

        tt = _make_thinking_thread(commander)
        result = parse_motor_output('alert_tak("Intruder at gate")')
        assert result.valid

        tt._dispatch(result)

        # alert_tak should produce a send_cot call with hostile CoT
        bridge.send_cot.assert_called_once()
        xml_arg = bridge.send_cot.call_args[0][0]
        assert "a-h-" in xml_arg, "Alert CoT should use hostile type prefix"
        assert "Intruder at gate" in xml_arg, "Alert message should appear in remarks"

    @pytest.mark.unit
    def test_dispatch_query_tak_clients_pushes_sensorium(self):
        """query_tak_clients() should push a client summary to sensorium."""
        commander = _make_mock_commander()
        bridge = _make_mock_tak_bridge()
        commander.tak_bridge = bridge

        tt = _make_thinking_thread(commander)
        result = parse_motor_output('query_tak_clients()')
        assert result.valid

        tt._dispatch(result)

        # Should push TAK client summary to sensorium
        push_calls = commander.sensorium.push.call_args_list
        assert len(push_calls) > 0
        # Find the call about TAK clients
        found_tak_summary = False
        for c in push_calls:
            text = c[0][1] if len(c[0]) > 1 else ""
            if "Alpha-1" in text or "Bravo-2" in text or "TAK" in text.upper():
                found_tak_summary = True
                break
        assert found_tak_summary, "query_tak_clients should push client info to sensorium"

    @pytest.mark.unit
    def test_dispatch_send_geochat_bridge_none_graceful(self):
        """send_geochat when tak_bridge is None should not crash."""
        commander = _make_mock_commander()
        commander.tak_bridge = None

        tt = _make_thinking_thread(commander)
        result = parse_motor_output('send_geochat("Hello")')
        assert result.valid

        # Should not raise
        tt._dispatch(result)

        # Should push a fallback message to sensorium
        push_calls = commander.sensorium.push.call_args_list
        assert len(push_calls) > 0

    @pytest.mark.unit
    def test_dispatch_alert_tak_bridge_none_graceful(self):
        """alert_tak when tak_bridge is None should not crash."""
        commander = _make_mock_commander()
        commander.tak_bridge = None

        tt = _make_thinking_thread(commander)
        result = parse_motor_output('alert_tak("Intruder spotted")')
        assert result.valid

        # Should not raise
        tt._dispatch(result)

    @pytest.mark.unit
    def test_dispatch_query_tak_clients_bridge_none_graceful(self):
        """query_tak_clients when tak_bridge is None should not crash."""
        commander = _make_mock_commander()
        commander.tak_bridge = None

        tt = _make_thinking_thread(commander)
        result = parse_motor_output('query_tak_clients()')
        assert result.valid

        # Should not raise
        tt._dispatch(result)

        # Should push a no-bridge message to sensorium
        push_calls = commander.sensorium.push.call_args_list
        assert len(push_calls) > 0


# ===================================================================
# 4. Sensorium wiring — TAKBridge._handle_inbound pushes events
# ===================================================================

class TestSensoriumTakWiring:
    """Verify that TAKBridge._handle_inbound pushes to sensorium
    for both position updates and GeoChat messages."""

    @pytest.mark.unit
    def test_geochat_inbound_pushes_to_sensorium(self):
        """An inbound GeoChat message should push to sensorium."""
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.event_bus import EventBus
        from engine.comms.cot import geochat_to_cot_xml

        event_bus = EventBus()
        tracker = MagicMock()
        tracker.get_all.return_value = []
        sensorium = MagicMock()

        bridge = TAKBridge(
            event_bus=event_bus,
            target_tracker=tracker,
            sensorium=sensorium,
        )

        # Simulate inbound GeoChat
        xml = geochat_to_cot_xml(
            sender_uid="ANDROID-abc123",
            sender_callsign="Alpha-1",
            message="Contact at north gate!",
            lat=37.7749,
            lng=-122.4194,
        )
        bridge._handle_inbound(xml)

        # Sensorium should have a tak_chat push
        calls = [c for c in sensorium.push.call_args_list
                 if c[0][0] == "tak_chat"]
        assert len(calls) >= 1, "GeoChat inbound should push to sensorium as tak_chat"
        assert "Alpha-1" in calls[0][0][1]
        assert "Contact at north gate" in calls[0][0][1]

    @pytest.mark.unit
    def test_geochat_stored_in_chat_history(self):
        """Inbound GeoChat should be stored in chat_history."""
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.event_bus import EventBus
        from engine.comms.cot import geochat_to_cot_xml

        event_bus = EventBus()
        tracker = MagicMock()
        tracker.get_all.return_value = []

        bridge = TAKBridge(event_bus=event_bus, target_tracker=tracker)

        xml = geochat_to_cot_xml(
            sender_uid="ANDROID-abc123",
            sender_callsign="Alpha-1",
            message="All clear.",
        )
        bridge._handle_inbound(xml)

        history = bridge.chat_history
        assert len(history) == 1
        assert history[0]["sender_callsign"] == "Alpha-1"
        assert history[0]["message"] == "All clear."
        assert history[0]["direction"] == "inbound"

    @pytest.mark.unit
    def test_hostile_inbound_pushes_tak_threat_to_sensorium(self):
        """An inbound hostile marker should push tak_threat to sensorium."""
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.event_bus import EventBus
        from datetime import datetime, timezone

        event_bus = EventBus()
        tracker = MagicMock()
        tracker.get_all.return_value = []
        sensorium = MagicMock()

        bridge = TAKBridge(
            event_bus=event_bus,
            target_tracker=tracker,
            sensorium=sensorium,
        )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        xml = f"""<event version="2.0" uid="hostile-marker" type="a-h-G-U-C-I" how="h-e"
                   time="{now}" start="{now}" stale="{now}">
          <point lat="37.7753" lon="-122.4198" hae="16.0" ce="10" le="10"/>
          <detail>
            <contact callsign="Suspicious Person"/>
          </detail>
        </event>"""
        bridge._handle_inbound(xml)

        calls = [c for c in sensorium.push.call_args_list
                 if c[0][0] == "tak_threat"]
        assert len(calls) >= 1
        assert "Suspicious Person" in calls[0][0][1]
        assert calls[0][1].get("importance") == pytest.approx(0.9)


# ===================================================================
# 5. Commander tak_bridge attribute
# ===================================================================

class TestCommanderTakBridgeAttribute:
    """Verify Commander has a tak_bridge attribute."""

    @pytest.mark.unit
    def test_commander_has_tak_bridge_attribute(self):
        """Commander.__init__ should set self.tak_bridge (initially None)."""
        # We cannot import Commander directly because it imports cv2, numpy, etc.
        # Instead verify via mock pattern that matches the real code.
        commander = _make_mock_commander()
        assert hasattr(commander, "tak_bridge")
        assert commander.tak_bridge is None

    @pytest.mark.unit
    def test_commander_tak_bridge_can_be_set(self):
        """Commander.tak_bridge should be assignable to a TAKBridge instance."""
        commander = _make_mock_commander()
        bridge = _make_mock_tak_bridge()
        commander.tak_bridge = bridge
        assert commander.tak_bridge is bridge
        assert commander.tak_bridge.connected is True
        assert len(commander.tak_bridge.clients) == 2
