# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for CameraTargetLinker — FOV-based camera-to-target auto-linking."""

import pytest

from engine.tactical.camera_target_linker import (
    CameraPlacement,
    CameraTargetLinker,
    DetectionLinkRecord,
    _haversine_m,
    _bearing_deg,
    _angle_diff,
)


class TestGeoHelpers:
    def test_haversine_same_point(self):
        assert _haversine_m(40.0, -74.0, 40.0, -74.0) == 0.0

    def test_haversine_known_distance(self):
        # NYC to nearby point (~111m per 0.001 lat)
        dist = _haversine_m(40.000, -74.0, 40.001, -74.0)
        assert 100 < dist < 120

    def test_bearing_north(self):
        bearing = _bearing_deg(40.0, -74.0, 41.0, -74.0)
        assert abs(bearing - 0.0) < 1.0 or abs(bearing - 360.0) < 1.0

    def test_bearing_east(self):
        bearing = _bearing_deg(40.0, -74.0, 40.0, -73.0)
        assert 89 < bearing < 91

    def test_angle_diff(self):
        assert _angle_diff(0, 90) == 90
        assert _angle_diff(350, 10) == 20
        assert _angle_diff(10, 350) == 20
        assert _angle_diff(180, 0) == 180


class TestCameraTargetLinker:
    def test_register_camera(self):
        linker = CameraTargetLinker()
        cam = CameraPlacement(
            camera_id="cam1",
            lat=40.0,
            lng=-74.0,
            fov_degrees=90.0,
            rotation_degrees=0.0,
            max_range_m=50.0,
        )
        linker.register_camera(cam)
        assert len(linker.get_cameras()) == 1

    def test_detection_within_fov(self):
        linker = CameraTargetLinker()
        # Camera facing north with 90 degree FOV
        cam = CameraPlacement(
            camera_id="cam1",
            lat=40.0,
            lng=-74.0,
            fov_degrees=90.0,
            rotation_degrees=0.0,  # Facing north
            max_range_m=200.0,
        )
        linker.register_camera(cam)

        # Target directly north, within range
        links = linker.process_detection(
            detection_id="det1",
            class_name="person",
            confidence=0.9,
            target_lat=40.001,  # ~111m north
            target_lng=-74.0,
            target_id="t1",
        )
        assert len(links) == 1
        assert links[0].camera_id == "cam1"
        assert links[0].target_id == "t1"
        assert links[0].class_name == "person"

    def test_detection_outside_fov(self):
        linker = CameraTargetLinker()
        # Camera facing north with 90 degree FOV
        cam = CameraPlacement(
            camera_id="cam1",
            lat=40.0,
            lng=-74.0,
            fov_degrees=90.0,
            rotation_degrees=0.0,
            max_range_m=200.0,
        )
        linker.register_camera(cam)

        # Target directly south — outside FOV
        links = linker.process_detection(
            detection_id="det2",
            class_name="vehicle",
            confidence=0.8,
            target_lat=39.999,  # south
            target_lng=-74.0,
            target_id="t2",
        )
        assert len(links) == 0

    def test_detection_out_of_range(self):
        linker = CameraTargetLinker()
        cam = CameraPlacement(
            camera_id="cam1",
            lat=40.0,
            lng=-74.0,
            fov_degrees=360.0,
            rotation_degrees=0.0,
            max_range_m=10.0,  # Very short range
        )
        linker.register_camera(cam)

        # Target 111m away — beyond range
        links = linker.process_detection(
            detection_id="det3",
            class_name="person",
            confidence=0.9,
            target_lat=40.001,
            target_lng=-74.0,
            target_id="t3",
        )
        assert len(links) == 0

    def test_multiple_cameras(self):
        linker = CameraTargetLinker()
        cam1 = CameraPlacement(
            camera_id="cam1", lat=40.0, lng=-74.0,
            fov_degrees=360.0, max_range_m=200.0,
        )
        cam2 = CameraPlacement(
            camera_id="cam2", lat=40.0001, lng=-74.0,
            fov_degrees=360.0, max_range_m=200.0,
        )
        linker.register_camera(cam1)
        linker.register_camera(cam2)

        links = linker.process_detection(
            detection_id="det4",
            class_name="person",
            confidence=0.9,
            target_lat=40.0005,
            target_lng=-74.0,
            target_id="t4",
        )
        assert len(links) == 2

    def test_get_links_for_target(self):
        linker = CameraTargetLinker()
        cam = CameraPlacement(
            camera_id="cam1", lat=40.0, lng=-74.0,
            fov_degrees=360.0, max_range_m=200.0,
        )
        linker.register_camera(cam)

        linker.process_detection(
            detection_id="det5", class_name="person",
            confidence=0.9, target_lat=40.0005,
            target_lng=-74.0, target_id="target_A",
        )
        linker.process_detection(
            detection_id="det6", class_name="vehicle",
            confidence=0.7, target_lat=40.0005,
            target_lng=-74.0, target_id="target_B",
        )

        links_a = linker.get_links_for_target("target_A")
        assert len(links_a) == 1
        assert links_a[0]["target_id"] == "target_A"

    def test_stats(self):
        linker = CameraTargetLinker()
        cam = CameraPlacement(
            camera_id="cam1", lat=40.0, lng=-74.0,
            fov_degrees=360.0, max_range_m=200.0,
        )
        linker.register_camera(cam)

        linker.process_detection(
            detection_id="det7", class_name="person",
            confidence=0.9, target_lat=40.0005,
            target_lng=-74.0, target_id="t7",
        )

        stats = linker.stats
        assert stats["cameras_registered"] == 1
        assert stats["total_checked"] == 1
        assert stats["total_linked"] == 1

    def test_remove_camera(self):
        linker = CameraTargetLinker()
        cam = CameraPlacement(camera_id="cam1", lat=40.0, lng=-74.0)
        linker.register_camera(cam)
        assert len(linker.get_cameras()) == 1
        linker.remove_camera("cam1")
        assert len(linker.get_cameras()) == 0

    def test_link_record_to_dict(self):
        record = DetectionLinkRecord(
            detection_id="d1",
            camera_id="c1",
            target_id="t1",
            class_name="person",
            confidence=0.95,
        )
        d = record.to_dict()
        assert d["detection_id"] == "d1"
        assert d["camera_id"] == "c1"
        assert d["position_in_frame"]["x"] == 0.0

    def test_camera_at_origin_skipped(self):
        linker = CameraTargetLinker()
        cam = CameraPlacement(camera_id="cam_no_pos", lat=0.0, lng=0.0)
        linker.register_camera(cam)

        links = linker.process_detection(
            detection_id="det8", class_name="person",
            confidence=0.9, target_lat=40.0,
            target_lng=-74.0, target_id="t8",
        )
        assert len(links) == 0
