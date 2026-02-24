"""Unit tests for TargetTracker."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from engine.tactical.target_tracker import TargetTracker, TrackedTarget

pytestmark = pytest.mark.unit


class TestUpdateFromSimulation:
    def test_update_from_simulation(self):
        tracker = TargetTracker()
        sim_data = {
            "target_id": "r1",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 5.0, "y": 3.0},
            "heading": 1.0,
            "speed": 2.0,
            "battery": 0.9,
            "status": "active",
        }
        tracker.update_from_simulation(sim_data)
        all_targets = tracker.get_all()
        assert len(all_targets) == 1
        t = all_targets[0]
        assert t.target_id == "r1"
        assert t.name == "Rover Alpha"
        assert t.alliance == "friendly"
        assert t.position == (5.0, 3.0)
        assert t.source == "simulation"

    def test_update_from_simulation_updates_existing(self):
        tracker = TargetTracker()
        sim_data = {
            "target_id": "r1",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 0.0, "y": 0.0},
            "heading": 0.0,
            "speed": 2.0,
            "battery": 1.0,
            "status": "active",
        }
        tracker.update_from_simulation(sim_data)

        # Update same target with new position
        sim_data2 = dict(sim_data)
        sim_data2["position"] = {"x": 10.0, "y": 5.0}
        tracker.update_from_simulation(sim_data2)

        all_targets = tracker.get_all()
        assert len(all_targets) == 1
        assert all_targets[0].position == (10.0, 5.0)


class TestUpdateFromDetection:
    def test_update_from_detection_person(self):
        tracker = TargetTracker()
        detection = {
            "class_name": "person",
            "confidence": 0.9,
            "bbox": [100, 100, 200, 300],
            "center_x": 0.5,
            "center_y": 0.6,
        }
        tracker.update_from_detection(detection)
        all_targets = tracker.get_all()
        assert len(all_targets) == 1
        t = all_targets[0]
        assert t.alliance == "hostile"
        assert t.asset_type == "person"
        assert t.source == "yolo"
        assert t.position == (0.5, 0.6)

    def test_update_from_detection_vehicle(self):
        tracker = TargetTracker()
        detection = {
            "class_name": "car",
            "confidence": 0.85,
            "bbox": [50, 50, 150, 200],
            "center_x": 0.3,
            "center_y": 0.4,
        }
        tracker.update_from_detection(detection)
        all_targets = tracker.get_all()
        assert len(all_targets) == 1
        t = all_targets[0]
        assert t.alliance == "unknown"
        assert t.asset_type == "vehicle"

    def test_detection_proximity_matching(self):
        tracker = TargetTracker()
        det1 = {
            "class_name": "person",
            "confidence": 0.9,
            "center_x": 0.5,
            "center_y": 0.5,
        }
        tracker.update_from_detection(det1)

        # Second detection very close — should match existing
        det2 = {
            "class_name": "person",
            "confidence": 0.92,
            "center_x": 0.51,
            "center_y": 0.51,
        }
        tracker.update_from_detection(det2)

        all_targets = tracker.get_all()
        assert len(all_targets) == 1
        # Position should have been updated to the new detection
        assert all_targets[0].position == (0.51, 0.51)

    def test_detection_far_apart_creates_new(self):
        tracker = TargetTracker()
        det1 = {
            "class_name": "person",
            "confidence": 0.9,
            "center_x": 0.1,
            "center_y": 0.1,
        }
        tracker.update_from_detection(det1)

        det2 = {
            "class_name": "person",
            "confidence": 0.9,
            "center_x": 0.9,
            "center_y": 0.9,
        }
        tracker.update_from_detection(det2)

        all_targets = tracker.get_all()
        assert len(all_targets) == 2


class TestGetFiltered:
    def _setup_mixed(self, tracker: TargetTracker) -> None:
        tracker.update_from_simulation({
            "target_id": "r1", "name": "Rover", "alliance": "friendly",
            "asset_type": "rover", "position": {"x": 0, "y": 0},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        tracker.update_from_simulation({
            "target_id": "h1", "name": "Hostile", "alliance": "hostile",
            "asset_type": "person", "position": {"x": 5, "y": 5},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        tracker.update_from_simulation({
            "target_id": "u1", "name": "Unknown", "alliance": "unknown",
            "asset_type": "vehicle", "position": {"x": 10, "y": 10},
            "heading": 0, "speed": 0, "battery": 1, "status": "active",
        })

    def test_get_hostiles(self):
        tracker = TargetTracker()
        self._setup_mixed(tracker)
        hostiles = tracker.get_hostiles()
        assert len(hostiles) == 1
        assert hostiles[0].alliance == "hostile"

    def test_get_friendlies(self):
        tracker = TargetTracker()
        self._setup_mixed(tracker)
        friendlies = tracker.get_friendlies()
        assert len(friendlies) == 1
        assert friendlies[0].alliance == "friendly"


class TestSummary:
    def test_summary_empty(self):
        tracker = TargetTracker()
        assert tracker.summary() == ""

    def test_summary_with_targets(self):
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "r1", "name": "Rover", "alliance": "friendly",
            "asset_type": "rover", "position": {"x": 0, "y": 0},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        tracker.update_from_simulation({
            "target_id": "h1", "name": "Hostile", "alliance": "hostile",
            "asset_type": "person", "position": {"x": 5, "y": 5},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        summary = tracker.summary()
        assert "BATTLESPACE" in summary
        assert "1 friendly" in summary
        assert "1 hostile" in summary


class TestPruneStale:
    def test_prune_stale(self):
        tracker = TargetTracker()
        detection = {
            "class_name": "person",
            "confidence": 0.9,
            "center_x": 0.5,
            "center_y": 0.5,
        }
        tracker.update_from_detection(detection)
        assert len(tracker.get_all()) == 1

        # Mock time.monotonic to jump forward past STALE_TIMEOUT
        real_mono = time.monotonic
        with patch("engine.tactical.target_tracker.time") as mock_time:
            mock_time.monotonic.return_value = real_mono() + tracker.STALE_TIMEOUT + 1.0
            result = tracker.get_all()
        assert len(result) == 0

    def test_simulation_targets_survive_within_timeout(self):
        """Sim targets within SIM_STALE_TIMEOUT should not be pruned."""
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "r1", "name": "Rover", "alliance": "friendly",
            "asset_type": "rover", "position": {"x": 0, "y": 0},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })

        real_mono = time.monotonic
        with patch("engine.tactical.target_tracker.time") as mock_time:
            # Jump to just before sim timeout
            mock_time.monotonic.return_value = real_mono() + tracker.SIM_STALE_TIMEOUT - 1.0
            result = tracker.get_all()
        assert len(result) == 1
        assert result[0].source == "simulation"

    def test_simulation_targets_pruned_after_sim_timeout(self):
        """Sim targets should be pruned after SIM_STALE_TIMEOUT (engine stopped updating)."""
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "r1", "name": "Rover", "alliance": "friendly",
            "asset_type": "rover", "position": {"x": 0, "y": 0},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })

        real_mono = time.monotonic
        with patch("engine.tactical.target_tracker.time") as mock_time:
            mock_time.monotonic.return_value = real_mono() + tracker.SIM_STALE_TIMEOUT + 1.0
            result = tracker.get_all()
        assert len(result) == 0


class TestConfidenceFiltering:
    def test_low_confidence_detection_ignored(self):
        tracker = TargetTracker()
        detection = {
            "class_name": "person",
            "confidence": 0.3,  # Below 0.4 threshold
            "center_x": 0.5,
            "center_y": 0.5,
        }
        tracker.update_from_detection(detection)
        assert len(tracker.get_all()) == 0

    def test_high_confidence_detection_accepted(self):
        tracker = TargetTracker()
        detection = {
            "class_name": "person",
            "confidence": 0.8,
            "center_x": 0.5,
            "center_y": 0.5,
        }
        tracker.update_from_detection(detection)
        assert len(tracker.get_all()) == 1

    def test_borderline_confidence_accepted(self):
        tracker = TargetTracker()
        detection = {
            "class_name": "person",
            "confidence": 0.4,
            "center_x": 0.5,
            "center_y": 0.5,
        }
        tracker.update_from_detection(detection)
        assert len(tracker.get_all()) == 1

    def test_no_confidence_key_ignored(self):
        tracker = TargetTracker()
        detection = {
            "class_name": "person",
            "center_x": 0.5,
            "center_y": 0.5,
        }
        tracker.update_from_detection(detection)
        # No confidence key defaults to 0 which is < 0.4
        assert len(tracker.get_all()) == 0


class TestEnhancedSummary:
    def test_summary_urgency_alert(self):
        tracker = TargetTracker()
        # Friendly at (0, 0)
        tracker.update_from_simulation({
            "target_id": "r1", "name": "Rover", "alliance": "friendly",
            "asset_type": "rover", "position": {"x": 0, "y": 0},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        # Hostile very close at (2, 2)
        tracker.update_from_simulation({
            "target_id": "h1", "name": "Intruder", "alliance": "hostile",
            "asset_type": "person", "position": {"x": 2, "y": 2},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        summary = tracker.summary()
        assert "ALERT" in summary
        assert "Intruder" in summary
        assert "Rover" in summary

    def test_summary_no_alert_when_far(self):
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "r1", "name": "Rover", "alliance": "friendly",
            "asset_type": "rover", "position": {"x": 0, "y": 0},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        tracker.update_from_simulation({
            "target_id": "h1", "name": "Intruder", "alliance": "hostile",
            "asset_type": "person", "position": {"x": 20, "y": 20},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        summary = tracker.summary()
        assert "ALERT" not in summary

    def test_summary_sector_grouping(self):
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "h1", "name": "Alpha", "alliance": "hostile",
            "asset_type": "person", "position": {"x": 10, "y": 10},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        tracker.update_from_simulation({
            "target_id": "h2", "name": "Bravo", "alliance": "hostile",
            "asset_type": "person", "position": {"x": -10, "y": -10},
            "heading": 0, "speed": 1, "battery": 1, "status": "active",
        })
        summary = tracker.summary()
        assert "Hostile sectors" in summary
