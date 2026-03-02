# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests that UnitComms publishes signal events on the EventBus.

The UnitComms system should publish a unit_signal event on every broadcast()
call so the frontend receives signals in real time via the WebSocket bridge.
"""

from __future__ import annotations

import queue
import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.comms import UnitComms, SIGNAL_DISTRESS, SIGNAL_CONTACT

pytestmark = pytest.mark.unit


class TestSignalEventPublished:
    """Test that unit_signal events are published on broadcast."""

    def test_broadcast_publishes_event(self):
        """broadcast() should publish a unit_signal event on the EventBus."""
        bus = EventBus()
        sub = bus.subscribe()
        comms = UnitComms(event_bus=bus)

        comms.broadcast(
            SIGNAL_DISTRESS, "rover-1", "friendly", (10.0, 20.0),
        )

        found = None
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "unit_signal":
                found = msg
                break

        assert found is not None, "unit_signal event not published"
        data = found["data"]
        assert data["signal_type"] == "distress"
        assert data["sender_id"] == "rover-1"
        assert data["sender_alliance"] == "friendly"
        assert data["position"] == [10.0, 20.0]

    def test_emit_distress_publishes(self):
        """emit_distress() convenience method publishes unit_signal."""
        bus = EventBus()
        sub = bus.subscribe()
        comms = UnitComms(event_bus=bus)

        comms.emit_distress("turret-2", (30.0, 40.0), "friendly")

        found = None
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "unit_signal":
                found = msg
                break

        assert found is not None
        assert found["data"]["signal_type"] == "distress"
        assert found["data"]["sender_id"] == "turret-2"

    def test_emit_contact_includes_target_position(self):
        """emit_contact() should include target_position in the event."""
        bus = EventBus()
        sub = bus.subscribe()
        comms = UnitComms(event_bus=bus)

        comms.emit_contact("scout-1", (10.0, 10.0), "friendly", enemy_pos=(50.0, 60.0))

        found = None
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "unit_signal":
                found = msg
                break

        assert found is not None
        assert found["data"]["target_position"] == [50.0, 60.0]

    def test_no_event_without_event_bus(self):
        """UnitComms without event_bus should not crash."""
        comms = UnitComms()
        # Should not raise
        comms.broadcast(SIGNAL_CONTACT, "r1", "hostile", (0.0, 0.0))

    def test_multiple_signals_publish_independently(self):
        """Each broadcast should produce its own event."""
        bus = EventBus()
        sub = bus.subscribe()
        comms = UnitComms(event_bus=bus)

        comms.emit_distress("r1", (0, 0), "friendly")
        comms.emit_contact("r2", (10, 10), "hostile", enemy_pos=(20, 20))
        comms.emit_retreat("r3", (30, 30), "hostile")

        events = []
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "unit_signal":
                events.append(msg["data"])

        assert len(events) == 3
        types = [e["signal_type"] for e in events]
        assert "distress" in types
        assert "contact" in types
        assert "retreat" in types
