# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""E2E tests for TAK bridge with real EventBus + TargetTracker.

These tests verify the full pipeline without a real TAK server:
EventBus -> TargetTracker -> TAKBridge -> CoT XML -> parse -> TargetTracker
"""

import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

from engine.comms.event_bus import EventBus
from engine.comms.cot import target_to_cot_xml, cot_xml_to_target, make_sa_cot
from engine.comms.tak_bridge import TAKBridge
from engine.tactical.target_tracker import TargetTracker


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def tracker():
    return TargetTracker()


@pytest.fixture
def bridge(event_bus, tracker):
    return TAKBridge(
        event_bus=event_bus,
        target_tracker=tracker,
        cot_url="tcp://localhost:8088",
        callsign="TEST-HQ",
        publish_interval=1.0,
    )


class TestRoundTrip:
    """Verify CoT XML round-trip: target -> XML -> parse -> target."""

    def test_friendly_rover_round_trip(self):
        target = {
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
        }
        xml = target_to_cot_xml(target)
        parsed = cot_xml_to_target(xml)

        assert parsed is not None
        assert parsed["target_id"] == "rover-1"
        assert parsed["name"] == "Rover Alpha"
        assert parsed["alliance"] == "friendly"
        assert parsed["asset_type"] == "rover"
        assert parsed["speed"] == pytest.approx(1.5, abs=0.1)
        assert parsed["heading"] == pytest.approx(45.0, abs=0.1)

    def test_hostile_person_round_trip(self):
        target = {
            "target_id": "hostile-5",
            "name": "Hostile 5",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": -10.0, "y": 30.0},
            "lat": 37.7752,
            "lng": -122.4195,
            "alt": 16.0,
            "heading": 180.0,
            "speed": 2.0,
            "battery": 1.0,
            "status": "active",
            "health": 80.0,
            "max_health": 80.0,
            "kills": 0,
            "is_combatant": True,
            "weapon_range": 8.0,
        }
        xml = target_to_cot_xml(target)
        parsed = cot_xml_to_target(xml)
        assert parsed["alliance"] == "hostile"
        # Both hostile_person and hostile_leader share CoT code a-h-G-U-C-I,
        # so reverse lookup may resolve to either
        assert parsed["asset_type"] in ("person", "hostile_person", "hostile_leader")


class TestBridgeInboundWithRealTracker:
    """Test inbound CoT injection into real TargetTracker."""

    def test_atak_user_appears_in_tracker(self, bridge, tracker):
        xml = make_sa_cot("ATAK-User-1", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)

        targets = tracker.get_all()
        tak_targets = [t for t in targets if t.target_id.startswith("tak_")]
        assert len(tak_targets) == 1
        assert tak_targets[0].alliance == "friendly"

    def test_multiple_atak_users(self, bridge, tracker):
        for i in range(3):
            xml = make_sa_cot(f"User-{i}", 37.7749 + i * 0.001, -122.4194, 16.0, "Green", "Team Member")
            bridge._handle_inbound(xml)

        targets = tracker.get_all()
        tak_targets = [t for t in targets if t.target_id.startswith("tak_")]
        assert len(tak_targets) == 3

    def test_event_bus_receives_tak_events(self, bridge, event_bus):
        q = event_bus.subscribe()
        xml = make_sa_cot("ATAK-Phone", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)

        events = []
        while not q.empty():
            events.append(q.get_nowait())
        tak_events = [e for e in events if e["type"] == "tak_client_update"]
        assert len(tak_events) == 1
        assert "ATAK-Phone" in tak_events[0]["data"]["callsign"]

    def test_bridge_tracks_clients(self, bridge):
        for name in ["Alpha", "Bravo", "Charlie"]:
            xml = make_sa_cot(name, 37.7749, -122.4194, 16.0, "Green", "Team Member")
            bridge._handle_inbound(xml)

        clients = bridge.clients
        assert len(clients) == 3
        callsigns = {c["callsign"] for c in clients.values()}
        assert callsigns == {"Alpha", "Bravo", "Charlie"}


class TestBridgeOutboundFiltering:
    """Verify that TAK-originated targets aren't echo'd back."""

    def test_tak_targets_filtered(self, bridge, tracker):
        # Simulate an ATAK user being injected
        xml = make_sa_cot("ATAK-User", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)

        # Now check which targets would be published
        targets = tracker.get_all()
        for t in targets:
            d = t.to_dict()
            if d["target_id"].startswith("tak_"):
                assert bridge._should_publish(d) is False
            else:
                assert bridge._should_publish(d) is True
