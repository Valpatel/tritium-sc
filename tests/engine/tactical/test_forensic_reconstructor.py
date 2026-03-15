# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for ForensicReconstructor."""

import time

import pytest

from engine.tactical.forensic_reconstructor import ForensicReconstructor


class MockEventStore:
    """Minimal event store mock for testing."""

    def __init__(self, events=None):
        self._events = events or []

    def query_time_range(self, start=0, end=0, limit=10000):
        return [
            e for e in self._events
            if start <= e.get("timestamp", 0) <= end
        ][:limit]


class MockPlayback:
    """Minimal playback mock for testing."""

    def __init__(self, snapshots=None):
        self._snapshots = snapshots or []

    def get_snapshots_between(self, start, end, max_count=100):
        return [
            s for s in self._snapshots
            if start <= s.get("timestamp", 0) <= end
        ][:max_count]


@pytest.fixture
def sample_events():
    now = time.time()
    return [
        {
            "timestamp": now - 300,
            "event_type": "target_sighting",
            "target_id": "ble_aa:bb:cc",
            "target_type": "phone",
            "sensor_id": "node_01",
            "sensor_type": "ble",
            "lat": 39.5,
            "lng": -74.5,
            "confidence": 0.9,
            "alliance": "unknown",
        },
        {
            "timestamp": now - 200,
            "event_type": "target_sighting",
            "target_id": "ble_dd:ee:ff",
            "target_type": "watch",
            "sensor_id": "node_02",
            "sensor_type": "ble",
            "lat": 39.51,
            "lng": -74.51,
            "confidence": 0.85,
            "alliance": "hostile",
        },
        {
            "timestamp": now - 100,
            "event_type": "alert",
            "target_id": "ble_dd:ee:ff",
            "sensor_id": "node_02",
            "sensor_type": "ble",
            "lat": 39.51,
            "lng": -74.51,
            "confidence": 0.95,
            "alliance": "hostile",
            "summary": "Hostile device detected",
        },
        {
            "timestamp": now - 50,
            "event_type": "target_sighting",
            "target_id": "ble_aa:bb:cc",
            "target_type": "phone",
            "sensor_id": "node_01",
            "sensor_type": "ble",
            "lat": 39.52,
            "lng": -74.52,
            "confidence": 0.9,
            "alliance": "unknown",
        },
    ]


class TestForensicReconstructor:
    def test_reconstruct_empty(self):
        """Reconstruction with no event store returns empty."""
        r = ForensicReconstructor()
        result = r.reconstruct(start=0, end=100)
        assert result["status"] == "complete"
        assert result["total_events"] == 0
        assert result["total_targets"] == 0

    def test_reconstruct_with_events(self, sample_events):
        """Reconstruction extracts targets and events."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        result = r.reconstruct(start=now - 400, end=now)

        assert result["status"] == "complete"
        assert result["total_events"] == 4
        assert result["total_targets"] == 2

        # Check target timelines
        targets = result["targets"]
        target_ids = {t["target_id"] for t in targets}
        assert "ble_aa:bb:cc" in target_ids
        assert "ble_dd:ee:ff" in target_ids

    def test_reconstruct_with_bounds(self, sample_events):
        """Bounds filtering works."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        bounds = {"north": 39.505, "south": 39.49, "east": -74.49, "west": -74.52}
        result = r.reconstruct(start=now - 400, end=now, bounds=bounds)

        assert result["status"] == "complete"
        # Only events within bounds should be included
        assert result["total_events"] >= 1

    def test_evidence_chain(self, sample_events):
        """Evidence chain is built from events."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        result = r.reconstruct(start=now - 400, end=now)

        evidence = result["evidence_chain"]
        assert len(evidence) == 4
        assert evidence[0]["evidence_id"] == "ev_0000"
        assert evidence[0]["sensor_type"] == "ble"

    def test_sensor_coverage(self, sample_events):
        """Sensor coverage is computed."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        result = r.reconstruct(start=now - 400, end=now)

        coverage = result["sensor_coverage"]
        assert "node_01" in coverage
        assert "node_02" in coverage
        assert coverage["node_01"]["count"] == 2
        assert coverage["node_02"]["count"] == 2

    def test_cached_reconstruction(self, sample_events):
        """Reconstructions are cached and retrievable."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        result = r.reconstruct(start=now - 400, end=now)
        recon_id = result["reconstruction_id"]

        cached = r.get_reconstruction(recon_id)
        assert cached is not None
        assert cached["reconstruction_id"] == recon_id

    def test_list_reconstructions(self, sample_events):
        """Listing reconstructions returns summaries."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        r.reconstruct(start=now - 400, end=now)
        r.reconstruct(start=now - 200, end=now)

        items = r.list_reconstructions()
        assert len(items) == 2

    def test_generate_incident_report(self, sample_events):
        """Incident report is generated from reconstruction."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        result = r.reconstruct(start=now - 400, end=now)

        report = r.generate_incident_report(result, title="Test Incident")
        assert report["title"] == "Test Incident"
        assert report["reconstruction_id"] == result["reconstruction_id"]
        assert report["status"] == "draft"
        assert len(report["entities"]) == 2
        assert len(report["findings"]) >= 1

        # Should detect hostile target
        hostile_finding = next(
            (f for f in report["findings"] if "hostile" in f.get("tags", [])),
            None,
        )
        assert hostile_finding is not None

    def test_incident_classification(self, sample_events):
        """Incident is auto-classified based on content."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        result = r.reconstruct(start=now - 400, end=now)

        report = r.generate_incident_report(result)
        # Has hostile target + alert event = should be significant or critical
        assert report["classification"] in ("significant", "critical")

    def test_recommendations_generated(self, sample_events):
        """Recommendations are generated for hostile findings."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        result = r.reconstruct(start=now - 400, end=now)

        report = r.generate_incident_report(result)
        assert len(report["recommendations"]) >= 1
        # Should recommend response to hostile
        hostile_rec = next(
            (rec for rec in report["recommendations"] if rec["priority"] <= 2),
            None,
        )
        assert hostile_rec is not None

    def test_timeline_summary(self, sample_events):
        """Timeline summary includes key events."""
        store = MockEventStore(sample_events)
        r = ForensicReconstructor(event_store=store)

        now = time.time()
        result = r.reconstruct(start=now - 400, end=now)

        report = r.generate_incident_report(result)
        assert len(report["timeline_summary"]) >= 1

    def test_with_playback_augmentation(self, sample_events):
        """Playback snapshots augment target positions."""
        store = MockEventStore(sample_events)
        now = time.time()
        snapshots = [
            {
                "timestamp": now - 250,
                "targets": [
                    {"target_id": "ble_aa:bb:cc", "position": {"lat": 39.505, "lng": -74.505}},
                ],
            },
        ]
        playback = MockPlayback(snapshots)
        r = ForensicReconstructor(event_store=store, playback=playback)

        result = r.reconstruct(start=now - 400, end=now)

        # Target ble_aa:bb:cc should have positions from both events and snapshots
        target_aa = next(
            (t for t in result["targets"] if t["target_id"] == "ble_aa:bb:cc"),
            None,
        )
        assert target_aa is not None
        assert len(target_aa["positions"]) >= 3  # 2 from events + 1 from snapshot
