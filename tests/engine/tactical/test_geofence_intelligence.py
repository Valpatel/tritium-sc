# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GeofenceIntelligence — auto-investigate on geofence enter."""

import tempfile
import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def event_bus():
    """Simple event bus mock that stores subscribers."""

    class MockEventBus:
        def __init__(self):
            self._subs = {}
            self._published = []

        def subscribe(self, topic, callback):
            self._subs.setdefault(topic, []).append(callback)

        def unsubscribe(self, topic, callback):
            if topic in self._subs:
                self._subs[topic] = [c for c in self._subs[topic] if c != callback]

        def publish(self, topic, data):
            self._published.append((topic, data))
            for cb in self._subs.get(topic, []):
                cb(data)

    return MockEventBus()


@pytest.fixture
def investigation_engine():
    from engine.tactical.investigation import InvestigationEngine
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        engine = InvestigationEngine(db_path=f.name)
    yield engine
    engine.close_db()


@pytest.fixture
def threat_scorer():
    """Mock threat scorer."""
    scorer = MagicMock()
    scorer.get_score = MagicMock(return_value=0.0)
    return scorer


@pytest.fixture
def target_tracker():
    """Mock target tracker with get_all()."""

    class MockTarget:
        def __init__(self, target_id, position, source="ble"):
            self.target_id = target_id
            self.position = position
            self.source = source

    tracker = MagicMock()
    tracker.get_all = MagicMock(return_value=[
        MockTarget("nearby_1", (10.0, 10.0), "ble"),
        MockTarget("nearby_2", (12.0, 12.0), "camera"),
        MockTarget("far_away", (500.0, 500.0), "wifi"),
    ])
    return tracker


@pytest.fixture
def geofence_intel(event_bus, investigation_engine, threat_scorer, target_tracker):
    from engine.tactical.geofence_intelligence import GeofenceIntelligence
    gi = GeofenceIntelligence(
        event_bus=event_bus,
        investigation_engine=investigation_engine,
        threat_scorer=threat_scorer,
        target_tracker=target_tracker,
        threat_threshold=0.5,
        nearby_radius=25.0,
    )
    gi.start()
    yield gi
    gi.stop()


@pytest.mark.unit
class TestGeofenceIntelligence:

    def test_start_subscribes(self, geofence_intel, event_bus):
        assert "geofence:enter" in event_bus._subs
        assert len(event_bus._subs["geofence:enter"]) == 1

    def test_low_threat_no_investigation(
        self, geofence_intel, event_bus, threat_scorer, investigation_engine,
    ):
        threat_scorer.get_score.return_value = 0.3  # below threshold

        event_bus.publish("geofence:enter", {
            "target_id": "ble_abc123",
            "zone_name": "TestZone",
            "zone_type": "restricted",
            "position": [10.0, 10.0],
        })

        investigations = investigation_engine.list_investigations()
        assert len(investigations) == 0

    def test_high_threat_creates_investigation(
        self, geofence_intel, event_bus, threat_scorer, investigation_engine,
    ):
        threat_scorer.get_score.return_value = 0.7

        event_bus.publish("geofence:enter", {
            "target_id": "ble_abc123",
            "zone_name": "TestZone",
            "zone_type": "restricted",
            "position": [10.0, 10.0],
        })

        investigations = investigation_engine.list_investigations()
        assert len(investigations) == 1
        inv = investigations[0]
        assert "ble_abc123" in inv.seed_entities
        assert "Geofence alert" in inv.title

    def test_nearby_targets_added(
        self, geofence_intel, event_bus, threat_scorer, investigation_engine,
    ):
        threat_scorer.get_score.return_value = 0.8

        event_bus.publish("geofence:enter", {
            "target_id": "trigger_target",
            "zone_name": "TestZone",
            "zone_type": "monitored",
            "position": [10.0, 10.0],
        })

        investigations = investigation_engine.list_investigations()
        assert len(investigations) == 1
        inv = investigations[0]
        # nearby_1 at (10,10) and nearby_2 at (12,12) should be added
        # far_away at (500,500) should NOT be added
        assert "nearby_1" in inv.discovered_entities
        assert "nearby_2" in inv.discovered_entities
        assert "far_away" not in inv.discovered_entities

    def test_no_duplicate_investigation(
        self, geofence_intel, event_bus, threat_scorer, investigation_engine,
    ):
        threat_scorer.get_score.return_value = 0.7

        # Trigger twice for same target
        event_bus.publish("geofence:enter", {
            "target_id": "ble_abc123",
            "zone_name": "Zone1",
            "zone_type": "restricted",
            "position": [10.0, 10.0],
        })
        event_bus.publish("geofence:enter", {
            "target_id": "ble_abc123",
            "zone_name": "Zone2",
            "zone_type": "restricted",
            "position": [15.0, 15.0],
        })

        investigations = investigation_engine.list_investigations()
        # Should only create one investigation
        assert len(investigations) == 1

    def test_publishes_event(
        self, geofence_intel, event_bus, threat_scorer,
    ):
        threat_scorer.get_score.return_value = 0.6

        event_bus.publish("geofence:enter", {
            "target_id": "ble_xyz",
            "zone_name": "Perimeter",
            "zone_type": "restricted",
            "position": [10.0, 10.0],
        })

        inv_events = [
            (t, d) for t, d in event_bus._published
            if t == "investigation:auto_created"
        ]
        assert len(inv_events) == 1
        _, data = inv_events[0]
        assert data["target_id"] == "ble_xyz"
        assert data["trigger"] == "geofence_enter"

    def test_get_status(self, geofence_intel, event_bus, threat_scorer):
        threat_scorer.get_score.return_value = 0.7
        event_bus.publish("geofence:enter", {
            "target_id": "test_1",
            "zone_name": "Z1",
            "zone_type": "restricted",
            "position": [10.0, 10.0],
        })

        status = geofence_intel.get_status()
        assert status["active"] is True
        assert status["investigations_created"] == 1
        assert status["events_processed"] >= 1

    def test_annotations_created(
        self, geofence_intel, event_bus, threat_scorer, investigation_engine,
    ):
        threat_scorer.get_score.return_value = 0.75

        event_bus.publish("geofence:enter", {
            "target_id": "annotated_target",
            "zone_name": "SensitiveArea",
            "zone_type": "restricted",
            "position": [10.0, 10.0],
        })

        invs = investigation_engine.list_investigations()
        assert len(invs) == 1
        inv = invs[0]
        # Should have annotations for the trigger target and nearby targets
        assert len(inv.annotations) >= 1
        trigger_ann = [a for a in inv.annotations if a.entity_id == "annotated_target"]
        assert len(trigger_ann) >= 1
        assert "threat_score" in trigger_ann[0].note
