# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for mesh target tracking via TargetTracker.update_from_mesh().

Verifies that Meshtastic LoRa mesh nodes are properly ingested as
TrackedTargets with correct source, alliance, position, and stale pruning.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from engine.tactical.target_tracker import TargetTracker, TrackedTarget

pytestmark = pytest.mark.unit


class TestUpdateFromMesh:
    """Tests for TargetTracker.update_from_mesh()."""

    def test_create_mesh_target_from_latlng(self):
        """Mesh node with GPS lat/lng creates a target with local coords."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_ba33ff38",
            "name": "Meshtastic ff38",
            "lat": 37.749,
            "lng": -122.4194,
            "alt": 16.0,
            "battery": 0.9,
        })
        targets = tracker.get_all()
        assert len(targets) == 1
        t = targets[0]
        assert t.target_id == "mesh_ba33ff38"
        assert t.name == "Meshtastic ff38"
        assert t.source == "mesh"
        assert t.alliance == "friendly"
        assert t.asset_type == "mesh_radio"
        assert t.battery == 0.9
        assert t.position_source == "gps"
        assert t.position_confidence > 0.5
        assert "mesh" in t.confirming_sources

    def test_create_mesh_target_from_local_coords(self):
        """Mesh node with pre-computed local position."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_node1",
            "name": "Node One",
            "position": {"x": 100.0, "y": 200.0},
            "battery": 0.75,
        })
        targets = tracker.get_all()
        assert len(targets) == 1
        t = targets[0]
        assert t.position == (100.0, 200.0)
        assert t.position_source == "gps"

    def test_mesh_target_no_position(self):
        """Mesh node without GPS still creates a target at origin."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_nopos",
            "name": "No GPS Node",
        })
        targets = tracker.get_all()
        assert len(targets) == 1
        t = targets[0]
        assert t.position == (0.0, 0.0)
        assert t.position_source == "unknown"
        assert t.position_confidence == 0.0

    def test_update_existing_mesh_target(self):
        """Second update to same mesh target updates position and battery."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_update",
            "name": "Updater",
            "position": {"x": 10.0, "y": 20.0},
            "battery": 0.5,
        })
        tracker.update_from_mesh({
            "target_id": "mesh_update",
            "name": "Updater v2",
            "position": {"x": 15.0, "y": 25.0},
            "battery": 0.4,
        })
        targets = tracker.get_all()
        assert len(targets) == 1
        t = targets[0]
        assert t.position == (15.0, 25.0)
        assert t.battery == 0.4
        assert t.name == "Updater v2"

    def test_empty_target_id_ignored(self):
        """Mesh update with empty target_id is silently ignored."""
        tracker = TargetTracker()
        tracker.update_from_mesh({"target_id": "", "name": "ghost"})
        assert len(tracker.get_all()) == 0

    def test_mesh_target_default_alliance(self):
        """Mesh nodes default to friendly alliance."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_friend",
            "name": "Friend",
        })
        t = tracker.get_all()[0]
        assert t.alliance == "friendly"

    def test_mesh_target_classification(self):
        """Mesh targets get mesh_radio classification."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_class",
            "name": "Classified",
        })
        t = tracker.get_all()[0]
        assert t.classification == "mesh_radio"

    def test_mesh_stale_pruning(self):
        """Mesh targets are pruned after MESH_STALE_TIMEOUT."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_stale",
            "name": "Stale Node",
        })
        assert len(tracker.get_all()) == 1

        # Fast-forward time past the stale timeout
        with patch("tritium_lib.tracking.target_tracker.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 400.0
            targets = tracker.get_all()
            assert len(targets) == 0

    def test_mesh_not_pruned_before_timeout(self):
        """Mesh targets survive during the stale window."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_fresh",
            "name": "Fresh Node",
        })
        # Within timeout — should still be there
        targets = tracker.get_all()
        assert len(targets) == 1

    def test_many_mesh_nodes(self):
        """250 mesh nodes can be ingested without error."""
        tracker = TargetTracker()
        for i in range(250):
            tracker.update_from_mesh({
                "target_id": f"mesh_node{i:04d}",
                "name": f"Node {i}",
                "position": {"x": float(i), "y": float(i * 2)},
                "battery": 0.8,
            })
        targets = tracker.get_all()
        assert len(targets) == 250
        # All should be friendly mesh
        assert all(t.source == "mesh" for t in targets)
        assert all(t.alliance == "friendly" for t in targets)

    def test_mesh_target_in_get_friendlies(self):
        """Mesh targets appear in get_friendlies()."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_friendly",
            "name": "Friendly Node",
        })
        friendlies = tracker.get_friendlies()
        assert len(friendlies) == 1
        assert friendlies[0].target_id == "mesh_friendly"

    def test_mesh_target_not_in_hostiles(self):
        """Mesh targets do not appear in get_hostiles()."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_not_hostile",
            "name": "Not Hostile",
        })
        assert len(tracker.get_hostiles()) == 0

    def test_mesh_confirming_source(self):
        """Multiple updates accumulate confirming sources."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_multi",
            "name": "Multi",
            "position": {"x": 1.0, "y": 2.0},
        })
        t = tracker.get_target("mesh_multi")
        assert "mesh" in t.confirming_sources

    def test_mesh_half_life_in_decay_table(self):
        """The mesh half-life is defined in the confidence decay table."""
        from engine.tactical.target_tracker import _HALF_LIVES
        assert "mesh" in _HALF_LIVES
        assert _HALF_LIVES["mesh"] == 120.0

    def test_mesh_to_dict_has_geo(self):
        """Mesh target to_dict includes lat/lng from position."""
        tracker = TargetTracker()
        tracker.update_from_mesh({
            "target_id": "mesh_geo",
            "name": "Geo Node",
            "position": {"x": 50.0, "y": 100.0},
            "battery": 0.6,
        })
        t = tracker.get_target("mesh_geo")
        d = t.to_dict()
        assert "lat" in d
        assert "lng" in d
        assert d["source"] == "mesh"
        assert d["asset_type"] == "mesh_radio"
        assert d["battery"] == 0.6


class TestNodeManagerToTracker:
    """Tests that NodeManager correctly feeds targets to TargetTracker."""

    def test_node_manager_feeds_tracker(self):
        """NodeManager.update_nodes feeds targets into TargetTracker."""
        import sys
        # Prefer tritium-addons submodule, fall back to local addons/
        _base = __import__("pathlib").Path(__file__).resolve().parents[3]
        addon_path = str(_base.parent / "tritium-addons" / "meshtastic")
        if not __import__("os").path.isdir(addon_path):
            addon_path = str(_base / "addons" / "meshtastic")
        if addon_path not in sys.path:
            sys.path.insert(0, addon_path)

        from meshtastic_addon.node_manager import NodeManager

        tracker = TargetTracker()
        nm = NodeManager(target_tracker=tracker)

        nm.update_nodes({
            "!node1": {
                "user": {"longName": "Alpha", "shortName": "A1", "hwModel": "T_BEAM"},
                "position": {"latitudeI": 377490000, "longitudeI": -1224194000, "altitude": 16},
                "lastHeard": 2000,
                "deviceMetrics": {"batteryLevel": 90, "voltage": 4.0},
            },
            "!node2": {
                "user": {"longName": "Bravo"},
                "position": {"latitudeI": 377500000, "longitudeI": -1224200000},
                "lastHeard": 1000,
            },
        })

        # Both nodes should be in the tracker
        all_targets = tracker.get_all()
        assert len(all_targets) == 2

        ids = {t.target_id for t in all_targets}
        assert "mesh_node1" in ids
        assert "mesh_node2" in ids

        # Check properties of first node
        t1 = tracker.get_target("mesh_node1")
        assert t1 is not None
        assert t1.name == "Alpha"
        assert t1.source == "mesh"
        assert t1.alliance == "friendly"
        assert t1.asset_type == "mesh_radio"
        assert abs(t1.battery - 0.9) < 0.01  # 90/100 = 0.9
