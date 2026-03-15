# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MissionTargetBinder."""

import pytest

from engine.tactical.mission_target_binder import (
    MissionTargetBinder,
    _point_in_circle,
    _point_in_polygon,
)


class TestPointInCircle:
    def test_inside(self):
        assert _point_in_circle(37.716, -121.896, 37.716, -121.896, 100)

    def test_outside(self):
        assert not _point_in_circle(38.0, -121.0, 37.716, -121.896, 100)

    def test_edge(self):
        # ~111m per degree at equator, so 0.001 deg ~ 111m
        assert _point_in_circle(0.0, 0.001, 0.0, 0.0, 200)


class TestPointInPolygon:
    def test_inside_square(self):
        verts = [(0, 0), (0, 1), (1, 1), (1, 0)]
        assert _point_in_polygon(0.5, 0.5, verts)

    def test_outside_square(self):
        verts = [(0, 0), (0, 1), (1, 1), (1, 0)]
        assert not _point_in_polygon(2.0, 2.0, verts)

    def test_too_few_vertices(self):
        assert not _point_in_polygon(0.5, 0.5, [(0, 0), (1, 1)])


class MockGeofence:
    def __init__(self, center_lat=None, center_lng=None, radius_m=None, vertices=None):
        self.center_lat = center_lat
        self.center_lng = center_lng
        self.radius_m = radius_m
        self.vertices = vertices or []

    @property
    def is_circle(self):
        return self.center_lat is not None and self.center_lng is not None and self.radius_m is not None


class MockMission:
    def __init__(self, mission_id, status="active", geofence=None, title="test"):
        self.mission_id = mission_id
        self.status = status
        self.geofence_zone = geofence
        self.title = title


class TestMissionTargetBinder:
    def test_get_mission_targets_empty(self):
        binder = MissionTargetBinder(missions_store={})
        assert binder.get_mission_targets("m1") == []

    def test_manual_bind(self):
        binder = MissionTargetBinder(missions_store={})
        assert binder.bind_target_manually("m1", "t1") is True
        assert binder.bind_target_manually("m1", "t1") is False  # already bound
        assert binder.get_mission_targets("m1") == ["t1"]

    def test_unbind(self):
        binder = MissionTargetBinder(missions_store={})
        binder.bind_target_manually("m1", "t1")
        assert binder.unbind_target("m1", "t1") is True
        assert binder.unbind_target("m1", "t1") is False  # already removed
        assert binder.get_mission_targets("m1") == []

    def test_get_all_bindings(self):
        binder = MissionTargetBinder(missions_store={})
        binder.bind_target_manually("m1", "t1")
        binder.bind_target_manually("m1", "t2")
        binder.bind_target_manually("m2", "t3")
        bindings = binder.get_all_bindings()
        assert len(bindings) == 2
        assert "t1" in bindings["m1"]
        assert "t3" in bindings["m2"]
