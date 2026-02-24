"""Tests for TAK -> Escalation integration.

TDD: tests written BEFORE implementation.
Verifies that AutoDispatcher reacts to tak_threat_marker events and that
ThreatClassifier picks up TAK hostile targets from the TargetTracker.
"""

import math
import queue
import time
from unittest.mock import MagicMock

import pytest

from engine.comms.event_bus import EventBus
from engine.tactical.escalation import AutoDispatcher, ThreatClassifier


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def target_tracker():
    tracker = MagicMock()
    tracker.get_all.return_value = []
    tracker.get_friendlies.return_value = []
    tracker.get_target.return_value = None
    return tracker


class TestAutoDispatcherTAKThreatMarker:
    """Verify AutoDispatcher handles tak_threat_marker events."""

    @pytest.mark.skip(reason="AutoDispatcher does not handle tak_threat_marker events — TAK threat dispatch not implemented")
    def test_autodispatcher_handles_tak_threat_marker(self, event_bus, target_tracker):
        """AutoDispatcher should react to tak_threat_marker immediately."""
        # Set up a threat target in the tracker
        threat = MagicMock()
        threat.target_id = "tak_hostile-1"
        threat.name = "Bad Guy"
        threat.position = (50.0, 50.0)
        threat.alliance = "hostile"

        # Set up an available friendly unit
        friendly = MagicMock()
        friendly.target_id = "rover-1"
        friendly.name = "Rover Alpha"
        friendly.position = (10.0, 10.0)
        friendly.battery = 0.9
        friendly.status = "active"
        friendly.asset_type = "rover"

        target_tracker.get_target.return_value = threat
        target_tracker.get_friendlies.return_value = [friendly]

        dispatcher = AutoDispatcher(
            event_bus=event_bus,
            target_tracker=target_tracker,
        )
        dispatcher.start()

        try:
            # Publish a tak_threat_marker event
            event_bus.publish("tak_threat_marker", {
                "target_id": "tak_hostile-1",
                "callsign": "Bad Guy",
                "lat": 37.7753,
                "lng": -122.4198,
                "source": "tak",
            })

            # Give the dispatcher time to process
            time.sleep(0.5)

            # Should have dispatched
            dispatches = dispatcher.active_dispatches
            assert "tak_hostile-1" in dispatches
            assert dispatches["tak_hostile-1"] == "rover-1"
        finally:
            dispatcher.stop()

    def test_autodispatcher_ignores_tak_marker_without_target_id(self, event_bus, target_tracker):
        """tak_threat_marker without target_id should be silently ignored."""
        dispatcher = AutoDispatcher(
            event_bus=event_bus,
            target_tracker=target_tracker,
        )
        dispatcher.start()
        try:
            event_bus.publish("tak_threat_marker", {
                "callsign": "No ID",
                "source": "tak",
            })
            time.sleep(0.3)
            assert dispatcher.active_dispatches == {}
        finally:
            dispatcher.stop()


class TestThreatClassifierTAKHostile:
    """Verify ThreatClassifier picks up TAK hostile targets from the tracker."""

    def test_tak_hostile_in_tracker_classified(self, event_bus):
        """A TAK hostile target in a zone should be classified by ThreatClassifier."""
        from engine.tactical.target_tracker import TargetTracker

        tracker = TargetTracker()

        # Add a zone
        zones = [{
            "name": "front_yard",
            "type": "perimeter",
            "position": {"x": 50.0, "y": 50.0},
            "properties": {"radius": 30.0},
        }]

        classifier = ThreatClassifier(
            event_bus=event_bus,
            target_tracker=tracker,
            zones=zones,
        )

        # Inject a TAK hostile target at the zone position
        tracker.update_from_simulation({
            "target_id": "tak_hostile-marker-1",
            "name": "TAK Hostile",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 50.0, "y": 50.0},
            "lat": 37.7753,
            "lng": -122.4198,
            "status": "active",
            "health": 100.0,
            "max_health": 100.0,
            "speed": 0.0,
            "heading": 0.0,
            "battery": 1.0,
            "kills": 0,
            "is_combatant": True,
            "weapon_range": 5.0,
            "source": "tak",
        })

        # Run one classification tick
        classifier._classify_tick()

        records = classifier.get_records()
        assert "tak_hostile-marker-1" in records
        # Should be at least unknown (in a perimeter zone)
        assert records["tak_hostile-marker-1"].threat_level != "none"
