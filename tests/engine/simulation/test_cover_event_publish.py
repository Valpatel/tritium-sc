# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests that the CoverSystem publishes cover_points events on the EventBus.

The engine should periodically publish cover object positions so the
frontend can render cover indicators on the tactical map.
"""

from __future__ import annotations

import queue
import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.cover import CoverSystem, CoverObject

pytestmark = pytest.mark.unit


class TestCoverEventPublish:
    """Test that cover_points events are published."""

    def test_publish_cover_points(self):
        """publish_cover_state() should emit a cover_points event."""
        bus = EventBus()
        sub = bus.subscribe()
        cs = CoverSystem(event_bus=bus)

        cs.add_cover(CoverObject(position=(10.0, 20.0), radius=3.0, cover_value=0.6))
        cs.add_cover(CoverObject(position=(30.0, 40.0), radius=5.0, cover_value=0.4))
        cs.publish_cover_state()

        found = None
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "cover_points":
                found = msg
                break

        assert found is not None, "cover_points event not published"
        points = found["data"]["points"]
        assert len(points) == 2
        assert points[0]["position"] == [10.0, 20.0]
        assert points[0]["radius"] == 3.0
        assert points[0]["cover_value"] == 0.6
        assert points[1]["position"] == [30.0, 40.0]

    def test_empty_cover_publishes_empty_list(self):
        """No cover objects should publish an empty points list."""
        bus = EventBus()
        sub = bus.subscribe()
        cs = CoverSystem(event_bus=bus)

        cs.publish_cover_state()

        found = None
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "cover_points":
                found = msg
                break

        assert found is not None
        assert found["data"]["points"] == []

    def test_no_event_without_event_bus(self):
        """CoverSystem without event_bus should not crash."""
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(10.0, 20.0)))
        # Should not raise
        cs.publish_cover_state()

    def test_cover_reset_clears_published_state(self):
        """After reset(), publish_cover_state() should emit empty list."""
        bus = EventBus()
        sub = bus.subscribe()
        cs = CoverSystem(event_bus=bus)

        cs.add_cover(CoverObject(position=(10.0, 20.0)))
        cs.reset()
        cs.publish_cover_state()

        events = []
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "cover_points":
                events.append(msg)

        assert len(events) >= 1
        assert events[-1]["data"]["points"] == []

    def test_cover_point_includes_all_fields(self):
        """Each cover point should include position, radius, cover_value."""
        bus = EventBus()
        sub = bus.subscribe()
        cs = CoverSystem(event_bus=bus)

        cs.add_cover(CoverObject(position=(5.0, 15.0), radius=4.0, cover_value=0.7))
        cs.publish_cover_state()

        found = None
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "cover_points":
                found = msg
                break

        point = found["data"]["points"][0]
        assert "position" in point
        assert "radius" in point
        assert "cover_value" in point
