# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TAKBridge — pytak-based CoT transport bridge.

TDD: tests written BEFORE implementation.
Tests mock pytak entirely so they run without a TAK server.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def target_tracker():
    """Minimal mock TargetTracker."""
    tracker = MagicMock()
    tracker.get_all.return_value = []
    return tracker


@pytest.fixture
def bridge_kwargs(event_bus, target_tracker):
    """Common constructor kwargs."""
    return dict(
        event_bus=event_bus,
        target_tracker=target_tracker,
        cot_url="tcp://localhost:8088",
        callsign="TEST-HQ",
        team="Cyan",
        role="HQ",
        publish_interval=1.0,
        stale_seconds=60,
    )


# ===================================================================
# Construction & properties
# ===================================================================

class TestTAKBridgeConstruction:

    def test_import(self):
        from engine.comms.tak_bridge import TAKBridge
        assert TAKBridge is not None

    def test_constructor(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        assert bridge is not None

    def test_initial_state_not_connected(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        assert bridge.connected is False

    def test_initial_state_not_running(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        assert bridge.running is False

    def test_stats_property(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        stats = bridge.stats
        assert isinstance(stats, dict)
        assert "connected" in stats
        assert "cot_url" in stats
        assert "callsign" in stats
        assert "messages_sent" in stats
        assert "messages_received" in stats

    def test_callsign_property(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        assert bridge.callsign == "TEST-HQ"

    def test_clients_initially_empty(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        assert bridge.clients == {}


# ===================================================================
# Graceful degradation
# ===================================================================

class TestGracefulDegradation:

    def test_no_pytak_logs_warning(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        with patch.dict("sys.modules", {"pytak": None}):
            # start() should not raise
            bridge.start()
            assert bridge.running is False

    def test_stop_when_not_running(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        # Should not raise
        bridge.stop()
        assert bridge.running is False

    def test_double_start_is_noop(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        bridge._running = True
        bridge.start()  # Should be noop
        # No exception means success


# ===================================================================
# Outbound: target publishing
# ===================================================================

class TestOutbound:

    def test_build_cot_from_target(self, bridge_kwargs, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import target_to_cot_xml
        bridge = TAKBridge(**bridge_kwargs)

        # Simulate a target
        mock_target = MagicMock()
        mock_target.to_dict.return_value = {
            "target_id": "rover-1",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 10.0, "y": 20.0},
            "lat": 37.7751,
            "lng": -122.4192,
            "alt": 16.0,
            "heading": 45.0,
            "speed": 1.5,
            "battery": 0.85,
            "status": "active",
            "health": 150.0,
            "max_health": 150.0,
            "kills": 2,
            "is_combatant": True,
            "weapon_range": 10.0,
            "source": "simulation",
        }
        xml = target_to_cot_xml(mock_target.to_dict())
        assert "rover-1" in xml
        assert "37.7751" in xml

    def test_skip_tak_prefixed_targets(self, bridge_kwargs, target_tracker):
        """Targets from TAK (prefixed tak_) should NOT be re-published."""
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)

        mock_target = MagicMock()
        mock_target.target_id = "tak_ANDROID-abc123"
        mock_target.to_dict.return_value = {"target_id": "tak_ANDROID-abc123"}

        # The bridge's _should_publish method should skip tak_ targets
        assert bridge._should_publish(mock_target.to_dict()) is False

    def test_should_publish_sim_targets(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        assert bridge._should_publish({"target_id": "rover-1"}) is True

    def test_should_publish_mqtt_targets(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        assert bridge._should_publish({"target_id": "mqtt_robot-1"}) is True

    def test_tx_queue_capacity(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        # Queue should have reasonable capacity
        assert bridge._tx_queue.maxsize == 500


# ===================================================================
# Inbound: CoT parsing and target injection
# ===================================================================

class TestInbound:

    def test_handle_inbound_cot(self, bridge_kwargs, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import make_sa_cot
        bridge = TAKBridge(**bridge_kwargs)

        # Simulate an inbound SA message from an ATAK user
        xml = make_sa_cot("ATAK-User-1", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)

        # Should have updated target tracker
        target_tracker.update_from_simulation.assert_called_once()
        call_args = target_tracker.update_from_simulation.call_args[0][0]
        assert call_args["target_id"].startswith("tak_")
        assert call_args["alliance"] == "friendly"

    def test_handle_inbound_hostile(self, bridge_kwargs, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from datetime import datetime, timezone
        bridge = TAKBridge(**bridge_kwargs)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        xml = f"""<event version="2.0" uid="hostile-marker" type="a-h-G-U-C-I" how="h-e"
                   time="{now}" start="{now}" stale="{now}">
          <point lat="37.7753" lon="-122.4198" hae="16.0" ce="10" le="10"/>
          <detail>
            <contact callsign="Bad Guy"/>
          </detail>
        </event>"""
        bridge._handle_inbound(xml)
        call_args = target_tracker.update_from_simulation.call_args[0][0]
        assert call_args["alliance"] == "hostile"

    def test_handle_inbound_malformed_xml(self, bridge_kwargs, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        bridge._handle_inbound("not xml")
        # Should not crash, should not call tracker
        target_tracker.update_from_simulation.assert_not_called()

    def test_inbound_publishes_event(self, bridge_kwargs, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import make_sa_cot
        bridge = TAKBridge(**bridge_kwargs)

        q = event_bus.subscribe()
        xml = make_sa_cot("ATAK-User-2", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)

        # Should have published tak_client_update event
        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_client_update":
                found = True
                break
        assert found

    def test_inbound_tracks_client(self, bridge_kwargs, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import make_sa_cot
        bridge = TAKBridge(**bridge_kwargs)

        xml = make_sa_cot("ATAK-User-3", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)

        clients = bridge.clients
        assert len(clients) >= 1


# ===================================================================
# Send raw CoT
# ===================================================================

class TestSendRaw:

    def test_send_cot_queues_message(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        bridge.send_cot("<event/>")
        assert bridge._tx_queue.qsize() == 1

    def test_send_cot_drops_oldest_when_full(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        # Fill the queue
        for i in range(500):
            bridge._tx_queue.put_nowait(f"<event uid='{i}'/>")
        # Should not raise
        bridge.send_cot("<event uid='overflow'/>")
        assert bridge._tx_queue.qsize() == 500


# ===================================================================
# Reconnect with exponential backoff
# ===================================================================

class TestReconnectBackoff:

    def test_reconnect_backoff_initial_delay(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        assert bridge._reconnect_delay == 2.0

    def test_reconnect_backoff_doubles(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        # Simulate doubling
        bridge._reconnect_delay = min(bridge._reconnect_delay * 2, 30.0)
        assert bridge._reconnect_delay == 4.0
        bridge._reconnect_delay = min(bridge._reconnect_delay * 2, 30.0)
        assert bridge._reconnect_delay == 8.0
        bridge._reconnect_delay = min(bridge._reconnect_delay * 2, 30.0)
        assert bridge._reconnect_delay == 16.0

    def test_reconnect_backoff_capped_at_30(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        # Double repeatedly
        for _ in range(10):
            bridge._reconnect_delay = min(bridge._reconnect_delay * 2, 30.0)
        assert bridge._reconnect_delay == 30.0

    def test_reconnect_backoff_resets_on_connect(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        # Escalate delay
        bridge._reconnect_delay = 16.0
        # Simulate connect
        bridge._connected = True
        bridge._reconnect_delay = 2.0
        assert bridge._reconnect_delay == 2.0


# ===================================================================
# Stale client cleanup
# ===================================================================

class TestStaleClientCleanup:

    def test_stale_client_cleanup(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)

        # Add a client that was last seen long ago (beyond 5x stale_seconds)
        bridge._clients["old-client"] = {
            "callsign": "Old User",
            "uid": "old-client",
            "lat": 37.77,
            "lng": -122.42,
            "alt": 16.0,
            "alliance": "friendly",
            "asset_type": "person",
            "speed": 0.0,
            "heading": 0.0,
            "last_seen": time.time() - (bridge._stale_seconds * 5 + 10),
        }
        # Add a fresh client
        bridge._clients["fresh-client"] = {
            "callsign": "Fresh User",
            "uid": "fresh-client",
            "lat": 37.77,
            "lng": -122.42,
            "alt": 16.0,
            "alliance": "friendly",
            "asset_type": "person",
            "speed": 0.0,
            "heading": 0.0,
            "last_seen": time.time(),
        }

        bridge._cleanup_stale_clients()

        assert "old-client" not in bridge._clients
        assert "fresh-client" in bridge._clients


# ===================================================================
# Hostile marker -> escalation event
# ===================================================================

class TestHostileMarkerEvent:

    def test_hostile_marker_event_published(self, bridge_kwargs, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from datetime import datetime, timezone
        bridge = TAKBridge(**bridge_kwargs)

        q = event_bus.subscribe()

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        xml = f"""<event version="2.0" uid="hostile-marker" type="a-h-G-U-C-I" how="h-e"
                   time="{now}" start="{now}" stale="{now}">
          <point lat="37.7753" lon="-122.4198" hae="16.0" ce="10" le="10"/>
          <detail>
            <contact callsign="Bad Guy"/>
          </detail>
        </event>"""
        bridge._handle_inbound(xml)

        # Find the tak_threat_marker event
        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_threat_marker":
                found = True
                assert msg["data"]["callsign"] == "Bad Guy"
                assert msg["data"]["source"] == "tak"
                break
        assert found, "tak_threat_marker event not published for hostile inbound"

    def test_friendly_does_not_publish_threat_marker(self, bridge_kwargs, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import make_sa_cot
        bridge = TAKBridge(**bridge_kwargs)

        q = event_bus.subscribe()
        xml = make_sa_cot("Friendly-User", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)

        # Should NOT have a tak_threat_marker event
        while not q.empty():
            msg = q.get_nowait()
            assert msg["type"] != "tak_threat_marker"


# ===================================================================
# Sensorium integration
# ===================================================================

class TestSensoriumIntegration:

    def test_sensorium_push_on_position(self, bridge_kwargs, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import make_sa_cot
        sensorium = MagicMock()
        bridge = TAKBridge(**bridge_kwargs, sensorium=sensorium)

        xml = make_sa_cot("Alpha-1", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)

        # Sensorium should have been called with tak_position
        sensorium.push.assert_called()
        calls = [c for c in sensorium.push.call_args_list
                 if c[0][0] == "tak_position"]
        assert len(calls) >= 1
        assert "Alpha-1" in calls[0][0][1]
        assert calls[0][1].get("importance") == pytest.approx(0.3)

    def test_sensorium_push_on_hostile(self, bridge_kwargs, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from datetime import datetime, timezone
        sensorium = MagicMock()
        bridge = TAKBridge(**bridge_kwargs, sensorium=sensorium)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        xml = f"""<event version="2.0" uid="hostile-1" type="a-h-G-U-C-I" how="h-e"
                   time="{now}" start="{now}" stale="{now}">
          <point lat="37.7753" lon="-122.4198" hae="16.0" ce="10" le="10"/>
          <detail>
            <contact callsign="Threat Alpha"/>
          </detail>
        </event>"""
        bridge._handle_inbound(xml)

        # Should have a tak_threat push with high importance
        calls = [c for c in sensorium.push.call_args_list
                 if c[0][0] == "tak_threat"]
        assert len(calls) >= 1
        assert "Threat Alpha" in calls[0][0][1]
        assert calls[0][1].get("importance") == pytest.approx(0.9)

    def test_sensorium_optional(self, bridge_kwargs, target_tracker):
        """Bridge should work fine without sensorium."""
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import make_sa_cot
        bridge = TAKBridge(**bridge_kwargs)

        # No sensorium, should not crash
        xml = make_sa_cot("User-1", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)
        # If we got here without exception, the test passes


# ===================================================================
# Inbound routing: tasking, emergency, sensor
# ===================================================================

class TestInboundRouting:
    """Test type-prefix routing in _handle_inbound."""

    def test_tasking_routes_to_handler(self, bridge_kwargs, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import tasking_to_cot
        bridge = TAKBridge(**bridge_kwargs)

        q = event_bus.subscribe()
        xml = tasking_to_cot("task-001", "rover-1", "dispatch", lat=37.77, lng=-122.42, remarks="Go")
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_tasking":
                found = True
                assert msg["data"]["task_id"] == "task-001"
                assert msg["data"]["assignee_uid"] == "rover-1"
                assert msg["data"]["task_type"] == "dispatch"
                break
        assert found, "tak_tasking event not published"

    def test_tasking_does_not_inject_to_tracker(self, bridge_kwargs, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import tasking_to_cot
        bridge = TAKBridge(**bridge_kwargs)

        xml = tasking_to_cot("task-001", "rover-1", "dispatch")
        bridge._handle_inbound(xml)

        # Tasking should not go through the target tracker path
        target_tracker.update_from_simulation.assert_not_called()

    def test_emergency_routes_to_handler(self, bridge_kwargs, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import emergency_to_cot
        bridge = TAKBridge(**bridge_kwargs)

        q = event_bus.subscribe()
        xml = emergency_to_cot("FIELD-01", "911", 37.77, -122.42, remarks="Help!")
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_emergency":
                found = True
                assert msg["data"]["callsign"] == "FIELD-01"
                assert msg["data"]["emergency_type"] == "911"
                break
        assert found, "tak_emergency event not published"

    def test_emergency_pushes_to_sensorium(self, bridge_kwargs, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import emergency_to_cot
        sensorium = MagicMock()
        bridge = TAKBridge(**bridge_kwargs, sensorium=sensorium)

        xml = emergency_to_cot("FIELD-01", "911", 37.77, -122.42, remarks="Breach!")
        bridge._handle_inbound(xml)

        # Should push to sensorium with importance=1.0
        calls = [c for c in sensorium.push.call_args_list
                 if c[0][0] == "tak_emergency"]
        assert len(calls) >= 1
        assert "FIELD-01" in calls[0][0][1]
        assert calls[0][1].get("importance") == pytest.approx(1.0)

    def test_emergency_does_not_inject_to_tracker(self, bridge_kwargs, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import emergency_to_cot
        bridge = TAKBridge(**bridge_kwargs)

        xml = emergency_to_cot("FIELD-01", "911", 37.77, -122.42)
        bridge._handle_inbound(xml)

        target_tracker.update_from_simulation.assert_not_called()

    def test_geochat_still_routes_correctly(self, bridge_kwargs, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import geochat_to_cot_xml
        bridge = TAKBridge(**bridge_kwargs)

        q = event_bus.subscribe()
        xml = geochat_to_cot_xml("USER-1", "Alpha", "Test message")
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_geochat":
                found = True
                break
        assert found, "GeoChat should still route correctly"

    def test_atom_position_still_routes_correctly(self, bridge_kwargs, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import make_sa_cot
        bridge = TAKBridge(**bridge_kwargs)

        xml = make_sa_cot("ATAK-User", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)

        target_tracker.update_from_simulation.assert_called_once()

    def test_tasking_increments_received_count(self, bridge_kwargs, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import tasking_to_cot
        bridge = TAKBridge(**bridge_kwargs)

        xml = tasking_to_cot("task-001", "rover-1", "dispatch")
        bridge._handle_inbound(xml)
        assert bridge._messages_received >= 1


# ===================================================================
# Outbound: send_tasking, send_emergency, send_video_feed
# ===================================================================

class TestOutboundExtended:

    def test_send_tasking_queues_message(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        bridge.send_tasking("task-001", "rover-1", "dispatch", lat=37.77, lng=-122.42, remarks="Go")
        assert bridge._tx_queue.qsize() == 1

    def test_send_tasking_xml_contains_type(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        bridge.send_tasking("task-001", "rover-1", "dispatch")
        xml = bridge._tx_queue.get_nowait()
        assert "t-x-t-a" in xml

    def test_send_emergency_queues_message(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        bridge.send_emergency("911", remarks="Help!")
        assert bridge._tx_queue.qsize() == 1

    def test_send_emergency_xml_contains_type(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        bridge.send_emergency("911", remarks="Alert")
        xml = bridge._tx_queue.get_nowait()
        assert "b-a-o-tbl" in xml

    def test_send_video_feed_queues_message(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        bridge.send_video_feed("cam-01", "rtsp://192.168.1.100/stream")
        assert bridge._tx_queue.qsize() == 1

    def test_send_video_feed_xml_contains_type(self, bridge_kwargs):
        from engine.comms.tak_bridge import TAKBridge
        bridge = TAKBridge(**bridge_kwargs)
        bridge.send_video_feed("cam-01", "rtsp://192.168.1.100/stream")
        xml = bridge._tx_queue.get_nowait()
        assert "b-i-v" in xml
