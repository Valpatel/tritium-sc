# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for training data wiring in correlator and BLE classifier.

Wave 110 — verifies that the correlator and BLE classifier actually
log decisions to the TrainingStore when they run.
"""
from __future__ import annotations

import os
import tempfile
import time
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def temp_store():
    """Create a temporary TrainingStore."""
    from engine.intelligence.training_store import TrainingStore
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_training.db")
        store = TrainingStore(db_path=db_path)
        yield store


def _make_tracker_with(*targets):
    """Create a TargetTracker pre-loaded with given targets."""
    from tritium_lib.tracking.target_tracker import TargetTracker
    tracker = TargetTracker()
    with tracker._lock:
        for t in targets:
            tracker._targets[t.target_id] = t
    return tracker


class TestCorrelatorTrainingWiring:
    """Verify the correlator logs decisions to TrainingStore."""

    @pytest.mark.unit
    def test_correlator_logs_positive_correlation(self, temp_store):
        """Correlator should log merge decisions to training store."""
        from tritium_lib.tracking.target_tracker import TrackedTarget
        from tritium_lib.tracking.correlator import TargetCorrelator

        now = time.monotonic()

        t1 = TrackedTarget(
            target_id="ble_aa:bb:cc:dd:ee:01",
            name="iPhone",
            source="ble",
            asset_type="phone",
            position=(0.0, 0.0),
            position_confidence=0.8,
            last_seen=now,
            alliance="unknown",
        )
        t2 = TrackedTarget(
            target_id="det_person_1",
            name="Person",
            source="yolo",
            asset_type="person",
            position=(0.5, 0.5),
            position_confidence=0.9,
            last_seen=now,
            alliance="unknown",
        )
        tracker = _make_tracker_with(t1, t2)

        correlator = TargetCorrelator(
            tracker,
            radius=10.0,
            confidence_threshold=0.01,  # Very low so correlation fires
        )

        with patch(
            "tritium_lib.tracking.correlator.TargetCorrelator._get_training_store",
            return_value=temp_store,
        ):
            records = correlator.correlate()

        data = temp_store.get_correlation_data()
        assert len(data) >= 1, "Correlator should log at least 1 decision"

        logged = data[0]
        assert logged["score"] > 0
        assert logged["decision"] in ("merge", "unrelated")

    @pytest.mark.unit
    def test_correlator_logs_negative_decision(self, temp_store):
        """Correlator should log unrelated decisions too."""
        from tritium_lib.tracking.target_tracker import TrackedTarget
        from tritium_lib.tracking.correlator import TargetCorrelator

        now = time.monotonic()

        t1 = TrackedTarget(
            target_id="ble_far_01",
            name="Far BLE",
            source="ble",
            asset_type="phone",
            position=(0.0, 0.0),
            position_confidence=0.5,
            last_seen=now,
            alliance="unknown",
        )
        t2 = TrackedTarget(
            target_id="det_far_person",
            name="Far Person",
            source="yolo",
            asset_type="person",
            position=(100.0, 100.0),
            position_confidence=0.5,
            last_seen=now,
            alliance="unknown",
        )
        tracker = _make_tracker_with(t1, t2)

        correlator = TargetCorrelator(
            tracker,
            radius=5.0,
            confidence_threshold=0.9,  # High threshold so nothing correlates
        )

        with patch(
            "tritium_lib.tracking.correlator.TargetCorrelator._get_training_store",
            return_value=temp_store,
        ):
            records = correlator.correlate()

        data = temp_store.get_correlation_data()
        assert len(data) >= 1, "Correlator should log negative decisions too"

        logged = data[0]
        assert logged["decision"] == "unrelated"


class TestBLEClassifierTrainingWiring:
    """Verify the BLE classifier logs decisions to TrainingStore."""

    @pytest.mark.unit
    def test_ble_classifier_logs_classification(self, temp_store):
        """BLE classifier should log each classification to training store."""
        from tritium_lib.tracking.ble_classifier import BLEClassifier
        from engine.comms.event_bus import EventBus

        bus = EventBus()
        classifier = BLEClassifier(
            event_bus=bus,
            known_macs={"AA:BB:CC:DD:EE:FF"},
            training_store_fn=lambda: temp_store,
        )

        # Classify a known device
        result = classifier.classify("AA:BB:CC:DD:EE:FF", "Known Phone", -50)
        assert result.level == "known"

        # Classify an unknown device
        result = classifier.classify("11:22:33:44:55:66", "Unknown", -80)
        assert result.level == "new"

        # Classify a suspicious device (strong signal, unknown)
        result = classifier.classify("99:88:77:66:55:44", "Strong", -30)
        assert result.level == "suspicious"

        # Check training store
        data = temp_store.get_classification_data()
        assert len(data) == 3, f"Expected 3 classifications, got {len(data)}"

        # Verify feature structure
        for record in data:
            assert "rssi" in record["features"]
            assert record["predicted_type"] == "ble_device"
            assert record["source"] == "ble_classifier"

    @pytest.mark.unit
    def test_ble_classifier_continues_if_store_unavailable(self):
        """BLE classifier should not crash if training store is unavailable."""
        from tritium_lib.tracking.ble_classifier import BLEClassifier
        from engine.comms.event_bus import EventBus

        bus = EventBus()
        classifier = BLEClassifier(
            event_bus=bus,
            training_store_fn=lambda: None,
        )

        # Should not raise
        result = classifier.classify("AA:BB:CC:DD:EE:FF", "Test", -60)
        assert result.level in ("known", "unknown", "new", "suspicious")


class TestHealthRLMetrics:
    """Verify RL training metrics appear in health endpoint."""

    @pytest.mark.unit
    def test_rl_metrics_structure(self, temp_store):
        """Health endpoint RL metrics should have expected keys."""
        with patch(
            "app.routers.health.get_training_store",
            return_value=temp_store,
            create=True,
        ):
            from app.routers.health import _rl_training_metrics
            metrics = _rl_training_metrics()

        assert "correlation_decisions" in metrics
        assert "classification_decisions" in metrics
        assert "feedback_entries" in metrics
        assert "feedback_accuracy" in metrics

    @pytest.mark.unit
    def test_rl_metrics_reflect_data(self, temp_store):
        """RL metrics should reflect actual training store data."""
        temp_store.log_correlation("a", "b", {}, 0.5, "merge")
        temp_store.log_classification("t1", {}, "phone", 0.9)
        temp_store.log_feedback("t1", "classification", True)

        with patch(
            "app.routers.health._rl_training_metrics",
        ) as mock_metrics:
            # Just test the function directly
            pass

        from app.routers.health import _rl_training_metrics

        # Patch the import inside the function
        import engine.intelligence.training_store as ts_mod
        original = ts_mod.get_training_store

        try:
            ts_mod.get_training_store = lambda: temp_store
            metrics = _rl_training_metrics()
            assert metrics["correlation_decisions"] == 1
            assert metrics["classification_decisions"] == 1
            assert metrics["feedback_entries"] == 1
        finally:
            ts_mod.get_training_store = original
