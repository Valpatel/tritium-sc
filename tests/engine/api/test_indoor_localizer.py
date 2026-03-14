# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for indoor target localizer."""

import sys
from pathlib import Path

import pytest

_plugins_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

from floorplan.store import FloorPlanStore
from floorplan.localizer import IndoorLocalizer, _point_in_polygon


class TestPointInPolygon:
    """Test ray-casting polygon containment."""

    def test_inside_square(self):
        poly = [
            {"lat": 0, "lon": 0},
            {"lat": 0, "lon": 1},
            {"lat": 1, "lon": 1},
            {"lat": 1, "lon": 0},
        ]
        assert _point_in_polygon(0.5, 0.5, poly) is True

    def test_outside_square(self):
        poly = [
            {"lat": 0, "lon": 0},
            {"lat": 0, "lon": 1},
            {"lat": 1, "lon": 1},
            {"lat": 1, "lon": 0},
        ]
        assert _point_in_polygon(2.0, 2.0, poly) is False

    def test_inside_triangle(self):
        poly = [
            {"lat": 0, "lon": 0},
            {"lat": 0, "lon": 2},
            {"lat": 2, "lon": 1},
        ]
        assert _point_in_polygon(0.5, 1.0, poly) is True

    def test_empty_polygon(self):
        assert _point_in_polygon(0.5, 0.5, []) is False


class TestIndoorLocalizer:
    """Test indoor target localization."""

    @pytest.fixture
    def setup(self, tmp_path):
        store = FloorPlanStore(data_dir=tmp_path / "fp")
        plan = store.create_plan("Test", building="HQ")
        plan_id = plan["plan_id"]

        # Update to active with bounds
        store.update_plan(plan_id, {
            "status": "active",
            "bounds": {"north": 1.5, "south": -0.5, "east": 1.5, "west": -0.5},
        })

        store.add_room(plan_id, {
            "room_id": "conf_a",
            "name": "Conference A",
            "polygon": [
                {"lat": 0.0, "lon": 0.0},
                {"lat": 0.0, "lon": 1.0},
                {"lat": 1.0, "lon": 1.0},
                {"lat": 1.0, "lon": 0.0},
            ],
        })

        localizer = IndoorLocalizer(store)
        return store, localizer, plan_id

    def test_localize_to_room(self, setup):
        store, localizer, plan_id = setup
        result = localizer.localize_target("ble_test", 0.5, 0.5, confidence=0.8)
        assert result is not None
        assert result["room_id"] == "conf_a"
        assert result["plan_id"] == plan_id
        assert result["confidence"] == 0.8

    def test_localize_outside_rooms_inside_bounds(self, setup):
        store, localizer, plan_id = setup
        # Point inside bounds but outside any room
        result = localizer.localize_target("ble_test", -0.2, -0.2)
        assert result is not None
        assert result["plan_id"] == plan_id
        assert result["room_id"] is None

    def test_localize_outside_bounds(self, setup):
        _, localizer, _ = setup
        result = localizer.localize_target("ble_test", 50.0, 50.0)
        assert result is None

    def test_fingerprint_localization(self, setup):
        store, localizer, plan_id = setup

        # Add fingerprints
        store.add_fingerprint({
            "plan_id": plan_id,
            "room_id": "conf_a",
            "lat": 0.5,
            "lon": 0.5,
            "rssi_map": {"AP1": -45.0, "AP2": -60.0, "AP3": -70.0},
        })

        # Query with similar RSSI
        result = localizer.localize_from_fingerprint(
            "device_1",
            {"AP1": -47.0, "AP2": -62.0, "AP3": -71.0},
            plan_id=plan_id,
        )
        assert result is not None
        assert result["room_id"] == "conf_a"
        assert result["method"] == "fingerprint"
        assert result["confidence"] > 0.5

    def test_fingerprint_no_match(self, setup):
        _, localizer, _ = setup
        # No fingerprints in database
        result = localizer.localize_from_fingerprint(
            "device_1",
            {"AP1": -50.0},
        )
        assert result is None

    def test_position_stored(self, setup):
        store, localizer, plan_id = setup
        localizer.localize_target("ble_test", 0.5, 0.5)
        pos = store.get_position("ble_test")
        assert pos is not None
        assert pos["room_id"] == "conf_a"
