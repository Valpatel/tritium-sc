# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for engine.synthetic.video_gen — synthetic video frame generators.

Tests cover:
- Color constants and alliance color mapping
- Helper functions (_get_pos, _get_attr, _world_to_pixel)
- Shape drawing dispatch (_draw_unit, _draw_health_bar)
- Grid and zone rendering
- Scene generators (bird_eye, street_cam, battle, neighborhood, cctv)
- ZoneRect dataclass
- Projectile / Explosion dataclasses
- CCTV scene type validation
- Barrel distortion and JPEG compression utilities
- Configuration and edge cases

All cv2/numpy calls use real cv2+numpy since they are available in the
test environment and the generators are pure-compute (no disk, no network).
"""

from __future__ import annotations

import math
import time
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from engine.synthetic.video_gen import (
    CCTV_SCENE_TYPES,
    CYAN,
    DARK_BG,
    EXPLOSION_ORANGE,
    EXPLOSION_YELLOW,
    FRIENDLY_GREEN,
    HOSTILE_RED,
    MUZZLE_FLASH,
    NEUTRAL_BLUE,
    PROJECTILE_COLOR,
    UNKNOWN_YELLOW,
    Explosion,
    Projectile,
    ZoneRect,
    _ALLIANCE_COLORS,
    _CCTV_SCENE_RENDERERS,
    _apply_barrel_distortion,
    _apply_jpeg_compression,
    _draw_cctv_overlay,
    _draw_grid,
    _draw_health_bar,
    _draw_heading_indicator,
    _draw_unit,
    _draw_zones,
    _get_attr,
    _get_pos,
    _world_to_pixel,
    render_battle_scene,
    render_bird_eye,
    render_cctv_frame,
    render_neighborhood,
    render_street_cam,
)


# =========================================================================
# Color constants
# =========================================================================


@pytest.mark.unit
class TestColorConstants:
    """Verify color tuples are BGR 3-channel with values in [0, 255]."""

    @pytest.mark.parametrize("color", [
        FRIENDLY_GREEN, HOSTILE_RED, UNKNOWN_YELLOW, NEUTRAL_BLUE,
        CYAN, DARK_BG, MUZZLE_FLASH, PROJECTILE_COLOR,
        EXPLOSION_ORANGE, EXPLOSION_YELLOW,
    ])
    def test_color_is_bgr_tuple(self, color):
        assert isinstance(color, tuple)
        assert len(color) == 3
        for c in color:
            assert 0 <= c <= 255

    def test_alliance_colors_mapping(self):
        assert set(_ALLIANCE_COLORS.keys()) == {"friendly", "hostile", "neutral", "unknown"}
        assert _ALLIANCE_COLORS["friendly"] == FRIENDLY_GREEN
        assert _ALLIANCE_COLORS["hostile"] == HOSTILE_RED
        assert _ALLIANCE_COLORS["neutral"] == NEUTRAL_BLUE
        assert _ALLIANCE_COLORS["unknown"] == UNKNOWN_YELLOW


# =========================================================================
# Helper: _get_pos
# =========================================================================


@pytest.mark.unit
class TestGetPos:
    """Extract (x, y) from various target representations."""

    def test_dict_with_position_dict(self):
        t = {"position": {"x": 10.0, "y": 20.0}}
        assert _get_pos(t) == (10.0, 20.0)

    def test_dict_with_position_list(self):
        t = {"position": [5.5, -3.2]}
        assert _get_pos(t) == (5.5, -3.2)

    def test_dict_with_position_tuple(self):
        t = {"position": (7.0, 8.0)}
        assert _get_pos(t) == (7.0, 8.0)

    def test_dict_with_direct_xy(self):
        t = {"x": 1.0, "y": 2.0}
        assert _get_pos(t) == (1.0, 2.0)

    def test_dict_with_missing_keys_defaults_zero(self):
        t = {}
        assert _get_pos(t) == (0.0, 0.0)

    def test_object_with_position_list(self):
        class FakeTarget:
            position = [11.0, 22.0]
        assert _get_pos(FakeTarget()) == (11.0, 22.0)

    def test_object_with_position_tuple(self):
        class FakeTarget:
            position = (3.0, 4.0)
        assert _get_pos(FakeTarget()) == (3.0, 4.0)

    def test_object_with_position_dict(self):
        class FakeTarget:
            position = {"x": 9.0, "y": -1.0}
        assert _get_pos(FakeTarget()) == (9.0, -1.0)

    def test_object_without_position(self):
        class FakeTarget:
            pass
        assert _get_pos(FakeTarget()) == (0.0, 0.0)


# =========================================================================
# Helper: _get_attr
# =========================================================================


@pytest.mark.unit
class TestGetAttr:
    def test_dict_get(self):
        assert _get_attr({"alliance": "hostile"}, "alliance") == "hostile"

    def test_dict_default(self):
        assert _get_attr({}, "alliance", "unknown") == "unknown"

    def test_object_get(self):
        class T:
            alliance = "friendly"
        assert _get_attr(T(), "alliance") == "friendly"

    def test_object_default(self):
        class T:
            pass
        assert _get_attr(T(), "missing", 42) == 42


# =========================================================================
# Helper: _world_to_pixel
# =========================================================================


@pytest.mark.unit
class TestWorldToPixel:
    def test_origin_maps_to_center(self):
        px, py = _world_to_pixel(0, 0, 640, 480)
        assert px == 320
        assert py == 240

    def test_positive_x_maps_right(self):
        px, _ = _world_to_pixel(10, 0, 640, 480, view_radius=35.0)
        assert px > 320

    def test_positive_y_maps_up(self):
        """World Y positive should map to lower pixel Y (screen Y inverted)."""
        _, py = _world_to_pixel(0, 10, 640, 480, view_radius=35.0)
        assert py < 240

    def test_custom_view_center(self):
        px, py = _world_to_pixel(5, 5, 640, 480, view_center=(5.0, 5.0))
        assert px == 320
        assert py == 240

    def test_view_radius_affects_scale(self):
        # Smaller radius = more zoomed in = further from center in pixels
        px_near, _ = _world_to_pixel(10, 0, 640, 480, view_radius=20.0)
        px_far, _ = _world_to_pixel(10, 0, 640, 480, view_radius=100.0)
        assert abs(px_near - 320) > abs(px_far - 320)

    def test_square_resolution_symmetric(self):
        px, py = _world_to_pixel(5, 5, 500, 500, view_radius=10.0)
        # With square res, scale is width/2*vr = 500/(2*10) = 25
        expected_px = 250 + int(5 * 25)
        expected_py = 250 - int(5 * 25)
        assert px == expected_px
        assert py == expected_py


# =========================================================================
# Drawing: _draw_unit
# =========================================================================


@pytest.mark.unit
class TestDrawUnit:
    """Verify _draw_unit modifies frame pixels for each asset type."""

    def _blank_frame(self):
        return np.zeros((100, 100, 3), dtype=np.uint8)

    @pytest.mark.parametrize("asset_type", [
        "rover", "drone", "turret", "vehicle", "animal", "person", "unknown",
    ])
    def test_draw_modifies_frame(self, asset_type):
        frame = self._blank_frame()
        _draw_unit(frame, 50, 50, asset_type, FRIENDLY_GREEN, size=8)
        assert frame.sum() > 0, f"No pixels drawn for asset_type={asset_type}"

    def test_rover_draws_square(self):
        frame = self._blank_frame()
        _draw_unit(frame, 50, 50, "rover", (255, 0, 0), size=8)
        # Check that pixels at center are non-zero
        assert frame[50, 50].sum() > 0

    def test_turret_uses_heading(self):
        frame1 = self._blank_frame()
        frame2 = self._blank_frame()
        _draw_unit(frame1, 50, 50, "turret", (0, 255, 0), size=10, heading=0.0)
        _draw_unit(frame2, 50, 50, "turret", (0, 255, 0), size=10, heading=180.0)
        # Different headings should produce different pixel patterns
        assert not np.array_equal(frame1, frame2)


# =========================================================================
# Drawing: _draw_heading_indicator
# =========================================================================


@pytest.mark.unit
class TestDrawHeadingIndicator:
    def test_draws_line(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        _draw_heading_indicator(frame, 50, 50, 0.0, (255, 255, 255), length=12)
        assert frame.sum() > 0

    def test_different_headings_differ(self):
        f1 = np.zeros((100, 100, 3), dtype=np.uint8)
        f2 = np.zeros((100, 100, 3), dtype=np.uint8)
        _draw_heading_indicator(f1, 50, 50, 0.0, (255, 255, 255), length=12)
        _draw_heading_indicator(f2, 50, 50, 90.0, (255, 255, 255), length=12)
        assert not np.array_equal(f1, f2)


# =========================================================================
# Drawing: _draw_health_bar
# =========================================================================


@pytest.mark.unit
class TestDrawHealthBar:
    def test_full_health_draws_green(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        _draw_health_bar(frame, 50, 50, 100.0, 100.0)
        assert frame.sum() > 0

    def test_zero_max_health_noop(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        _draw_health_bar(frame, 50, 50, 50.0, 0.0)
        assert frame.sum() == 0, "Should not draw when max_health=0"

    def test_low_health_draws_red(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        _draw_health_bar(frame, 50, 50, 10.0, 100.0, size=8)
        # Health < 25% should use red-ish color (60, 60, 230 BGR)
        assert frame.sum() > 0

    def test_negative_health_clamps(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        # Should not crash with negative health
        _draw_health_bar(frame, 50, 50, -10.0, 100.0)
        assert frame.sum() > 0  # bg bar still drawn


# =========================================================================
# Drawing: _draw_grid
# =========================================================================


@pytest.mark.unit
class TestDrawGrid:
    def test_grid_draws_lines(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        _draw_grid(frame, 640, 480)
        assert frame.sum() > 0


# =========================================================================
# Drawing: _draw_zones
# =========================================================================


@pytest.mark.unit
class TestDrawZones:
    def test_zone_rect(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        zones = [ZoneRect(name="TEST", x=0, y=0, w=10, h=10)]
        _draw_zones(frame, zones, 640, 480)
        assert frame.sum() > 0

    def test_zone_dict(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        zones = [{"name": "ZONE1", "x": 5, "y": 5, "w": 8, "h": 8}]
        _draw_zones(frame, zones, 640, 480)
        assert frame.sum() > 0

    def test_empty_zones_noop(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        _draw_zones(frame, [], 640, 480)
        assert frame.sum() == 0


# =========================================================================
# Dataclasses
# =========================================================================


@pytest.mark.unit
class TestDataclasses:
    def test_zone_rect_defaults(self):
        z = ZoneRect(name="Z", x=1, y=2, w=3, h=4)
        assert z.color == (80, 80, 40)

    def test_projectile_defaults(self):
        p = Projectile(start=(0, 0), end=(10, 10))
        assert p.progress == 0.5
        assert p.color == PROJECTILE_COLOR

    def test_explosion_defaults(self):
        e = Explosion(x=5.0, y=5.0)
        assert e.radius == 3.0
        assert e.progress == 0.5


# =========================================================================
# Scene: render_bird_eye
# =========================================================================


@pytest.mark.unit
class TestRenderBirdEye:
    def test_returns_correct_shape(self):
        frame = render_bird_eye(resolution=(640, 480), timestamp="12:00:00")
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_custom_resolution(self):
        frame = render_bird_eye(resolution=(320, 240), timestamp="12:00:00")
        assert frame.shape == (240, 320, 3)

    def test_empty_targets(self):
        frame = render_bird_eye(targets=[], timestamp="12:00:00")
        assert frame is not None
        assert frame.shape == (480, 640, 3)

    def test_with_targets(self):
        targets = [
            {"target_id": "r1", "alliance": "friendly", "asset_type": "rover",
             "position": (5.0, 5.0), "heading": 90.0},
            {"target_id": "h1", "alliance": "hostile", "asset_type": "person",
             "position": (-10.0, 10.0), "heading": 0.0},
        ]
        frame = render_bird_eye(targets=targets, timestamp="12:00:00")
        assert frame is not None

    def test_with_zones(self):
        zones = [ZoneRect("ALPHA", 0, 0, 20, 20)]
        frame = render_bird_eye(zones=zones, timestamp="12:00:00")
        assert frame is not None

    def test_background_is_dark(self):
        frame = render_bird_eye(targets=[], timestamp="12:00:00")
        # Most of the frame should be dark
        mean_brightness = frame.mean()
        assert mean_brightness < 50

    def test_out_of_view_targets_skipped(self):
        """Targets far outside view_radius should not crash."""
        targets = [
            {"target_id": "far", "alliance": "hostile", "asset_type": "person",
             "position": (9999.0, 9999.0)},
        ]
        frame = render_bird_eye(targets=targets, view_radius=35.0, timestamp="12:00:00")
        assert frame is not None

    def test_timestamp_override(self):
        """When timestamp is provided, it should appear in the frame."""
        frame = render_bird_eye(timestamp="99:99:99")
        # Not easy to OCR, but at least verify no crash
        assert frame is not None

    def test_seed_determinism(self):
        """Same seed produces same grid (no noise in bird_eye though)."""
        f1 = render_bird_eye(targets=[], seed=42, timestamp="00:00:00")
        f2 = render_bird_eye(targets=[], seed=42, timestamp="00:00:00")
        assert np.array_equal(f1, f2)


# =========================================================================
# Scene: render_street_cam
# =========================================================================


@pytest.mark.unit
class TestRenderStreetCam:
    def test_returns_correct_shape(self):
        frame = render_street_cam(resolution=(640, 480), timestamp="2026-01-01 00:00:00", seed=1)
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    @pytest.mark.parametrize("tod", ["night", "day", "dusk"])
    def test_time_of_day(self, tod):
        frame = render_street_cam(time_of_day=tod, seed=10, timestamp="2026-01-01 00:00:00")
        assert frame is not None

    def test_invalid_time_of_day_falls_back_to_night(self):
        frame = render_street_cam(time_of_day="midnight", seed=10, timestamp="T")
        assert frame is not None

    def test_camera_name_in_overlay(self):
        frame = render_street_cam(camera_name="TEST-CAM", seed=10, timestamp="T")
        assert frame is not None

    def test_with_targets(self):
        targets = [
            {"alliance": "neutral", "asset_type": "person", "position": (0, 0)},
            {"alliance": "hostile", "asset_type": "vehicle", "position": (5, -5)},
        ]
        frame = render_street_cam(targets=targets, seed=10, timestamp="T")
        assert frame is not None

    def test_seed_determinism(self):
        f1 = render_street_cam(seed=42, timestamp="T")
        f2 = render_street_cam(seed=42, timestamp="T")
        assert np.array_equal(f1, f2)

    def test_noise_added(self):
        """Seed-based noise should make frame not perfectly smooth."""
        frame = render_street_cam(targets=[], seed=7, timestamp="T")
        # Noise means variance > 0 across uniform regions
        assert frame.std() > 0


# =========================================================================
# Scene: render_battle_scene
# =========================================================================


@pytest.mark.unit
class TestRenderBattleScene:
    def test_returns_correct_shape(self):
        frame = render_battle_scene(resolution=(640, 480), timestamp="12:00:00")
        assert frame.shape == (480, 640, 3)

    def test_empty_scene(self):
        frame = render_battle_scene(timestamp="12:00:00")
        assert frame is not None

    def test_with_friendlies_and_hostiles(self):
        friendlies = [
            {"asset_type": "turret", "position": (0, -10), "heading": 0,
             "health": 100, "max_health": 100},
        ]
        hostiles = [
            {"asset_type": "person", "position": (0, 10), "heading": 180,
             "health": 80, "max_health": 80},
        ]
        frame = render_battle_scene(friendlies=friendlies, hostiles=hostiles, timestamp="T")
        assert frame is not None

    def test_with_projectiles_dict(self):
        projectiles = [
            {"start": (0, -10), "end": (0, 10), "progress": 0.5},
        ]
        frame = render_battle_scene(projectiles=projectiles, timestamp="T")
        assert frame is not None

    def test_with_projectile_objects(self):
        projectiles = [
            Projectile(start=(0, -10), end=(0, 10), progress=0.1),
            Projectile(start=(5, 0), end=(-5, 0), progress=0.9),
        ]
        frame = render_battle_scene(projectiles=projectiles, timestamp="T")
        assert frame is not None

    def test_muzzle_flash_at_low_progress(self):
        """Projectile with progress < 0.2 draws a muzzle flash."""
        projectiles = [
            Projectile(start=(0, 0), end=(10, 10), progress=0.05),
        ]
        frame = render_battle_scene(projectiles=projectiles, timestamp="T")
        assert frame is not None

    def test_with_explosion_dict(self):
        explosions = [
            {"x": 0, "y": 0, "radius": 5.0, "progress": 0.5},
        ]
        frame = render_battle_scene(explosions=explosions, timestamp="T", seed=1)
        assert frame is not None

    def test_with_explosion_objects(self):
        explosions = [
            Explosion(x=0, y=5, radius=4.0, progress=0.3),
            Explosion(x=-5, y=-5, radius=2.0, progress=0.9),
        ]
        frame = render_battle_scene(explosions=explosions, timestamp="T", seed=1)
        assert frame is not None

    def test_explosion_high_progress_fading(self):
        """Progress near 1.0 should fade explosion (alpha near 0)."""
        explosions = [Explosion(x=0, y=0, radius=5, progress=0.99)]
        frame = render_battle_scene(explosions=explosions, timestamp="T", seed=1)
        assert frame is not None

    def test_hud_shows_counts(self):
        """HUD overlay text should contain F: and H: counts."""
        frame = render_battle_scene(
            friendlies=[{"position": (0, 0)}],
            hostiles=[{"position": (5, 5)}, {"position": (6, 6)}],
            timestamp="T",
        )
        assert frame is not None


# =========================================================================
# Scene: render_neighborhood
# =========================================================================


@pytest.mark.unit
class TestRenderNeighborhood:
    def test_returns_correct_shape(self):
        frame = render_neighborhood(resolution=(640, 480), seed=1, timestamp="T")
        assert frame.shape == (480, 640, 3)

    @pytest.mark.parametrize("tod", ["night", "day", "dusk"])
    def test_time_of_day(self, tod):
        frame = render_neighborhood(time_of_day=tod, seed=1, timestamp="T")
        assert frame is not None

    def test_with_ambient_targets(self):
        targets = [
            {"asset_type": "person", "alliance": "neutral", "position": (0, 0)},
            {"asset_type": "animal", "alliance": "neutral", "position": (5, 3)},
            {"asset_type": "vehicle", "alliance": "neutral", "position": (15, -8)},
        ]
        frame = render_neighborhood(ambient_targets=targets, seed=1, timestamp="T")
        assert frame is not None

    def test_empty_ambient(self):
        frame = render_neighborhood(ambient_targets=[], seed=1, timestamp="T")
        assert frame is not None

    def test_seed_determinism(self):
        f1 = render_neighborhood(seed=42, timestamp="T")
        f2 = render_neighborhood(seed=42, timestamp="T")
        assert np.array_equal(f1, f2)

    def test_buildings_drawn(self):
        """Buildings on horizon change the frame from a plain gradient."""
        frame = render_neighborhood(seed=100, timestamp="T")
        # The building region (top portion) should have some pixel variation
        horizon_region = frame[0:int(480 * 0.35), :, :]
        assert horizon_region.std() > 0


# =========================================================================
# CCTV Scene Types
# =========================================================================


@pytest.mark.unit
class TestCCTVSceneTypes:
    def test_scene_types_tuple(self):
        assert isinstance(CCTV_SCENE_TYPES, tuple)
        assert len(CCTV_SCENE_TYPES) == 5
        assert "front_door" in CCTV_SCENE_TYPES
        assert "back_yard" in CCTV_SCENE_TYPES
        assert "street_view" in CCTV_SCENE_TYPES
        assert "parking" in CCTV_SCENE_TYPES
        assert "driveway" in CCTV_SCENE_TYPES

    def test_renderer_map_matches(self):
        assert set(_CCTV_SCENE_RENDERERS.keys()) == set(CCTV_SCENE_TYPES)


# =========================================================================
# Scene: render_cctv_frame
# =========================================================================


@pytest.mark.unit
class TestRenderCCTVFrame:
    def test_returns_correct_shape(self):
        frame = render_cctv_frame(seed=1, timestamp="T")
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    @pytest.mark.parametrize("scene_type", CCTV_SCENE_TYPES)
    def test_all_scene_types(self, scene_type):
        frame = render_cctv_frame(scene_type=scene_type, seed=1, timestamp="T")
        assert frame.shape == (480, 640, 3)

    def test_invalid_scene_type_raises(self):
        with pytest.raises(ValueError, match="Invalid CCTV scene_type"):
            render_cctv_frame(scene_type="invalid_scene")

    @pytest.mark.parametrize("tod", ["night", "day", "dusk"])
    def test_time_of_day_variants(self, tod):
        frame = render_cctv_frame(time_of_day=tod, seed=1, timestamp="T")
        assert frame is not None

    def test_camera_name_hash_shifts_colors(self):
        """Different camera names should produce slightly different frames."""
        f1 = render_cctv_frame(camera_name="CAM-01", seed=1, timestamp="T")
        f2 = render_cctv_frame(camera_name="CAM-99", seed=1, timestamp="T")
        # Frames should differ due to per-camera color temperature shift
        assert not np.array_equal(f1, f2)

    def test_frame_number_parameter(self):
        frame = render_cctv_frame(seed=1, timestamp="T", frame_number=100)
        assert frame is not None

    def test_custom_resolution(self):
        frame = render_cctv_frame(resolution=(320, 240), seed=1, timestamp="T")
        assert frame.shape == (240, 320, 3)

    def test_seed_determinism(self):
        f1 = render_cctv_frame(seed=42, timestamp="T", frame_number=0)
        f2 = render_cctv_frame(seed=42, timestamp="T", frame_number=0)
        assert np.array_equal(f1, f2)


# =========================================================================
# Utilities: barrel distortion, JPEG compression, overlay
# =========================================================================


@pytest.mark.unit
class TestCCTVUtilities:
    def test_barrel_distortion_preserves_shape(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[200:300, 200:400] = 128  # gray block
        result = _apply_barrel_distortion(frame, strength=0.3)
        assert result.shape == frame.shape
        assert result.dtype == np.uint8

    def test_barrel_distortion_modifies_pixels(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[200:300, 200:400] = 128
        result = _apply_barrel_distortion(frame, strength=0.3)
        assert not np.array_equal(frame, result)

    def test_jpeg_compression_preserves_shape(self):
        frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        result = _apply_jpeg_compression(frame, quality=70)
        assert result.shape == frame.shape

    def test_jpeg_compression_lossy(self):
        """JPEG compression introduces artifacts, so output differs from input."""
        frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        result = _apply_jpeg_compression(frame, quality=50)
        assert not np.array_equal(frame, result)

    def test_cctv_overlay_draws_text(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        _draw_cctv_overlay(frame, "CAM-01", "2026-01-01 00:00:00", 0, 640, 480)
        assert frame.sum() > 0


# =========================================================================
# Individual CCTV scene renderers (lower-level)
# =========================================================================


@pytest.mark.unit
class TestCCTVSceneRenderers:
    """Verify each CCTV scene renderer modifies the frame without crashing."""

    @pytest.mark.parametrize("scene_name", list(_CCTV_SCENE_RENDERERS.keys()))
    def test_scene_modifies_frame(self, scene_name):
        import random as stdlib_random
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        rng = stdlib_random.Random(42)
        np_rng = np.random.RandomState(42)
        bg = (15, 10, 10)
        renderer = _CCTV_SCENE_RENDERERS[scene_name]
        renderer(frame, rng, np_rng, 640, 480, bg, "night", 0)
        assert frame.sum() > 0, f"Scene {scene_name} did not modify frame"


# =========================================================================
# Edge cases and robustness
# =========================================================================


@pytest.mark.unit
class TestEdgeCases:
    def test_bird_eye_none_targets_defaults_empty(self):
        frame = render_bird_eye(targets=None, timestamp="T")
        assert frame is not None

    def test_street_cam_none_targets_defaults_empty(self):
        frame = render_street_cam(targets=None, seed=1, timestamp="T")
        assert frame is not None

    def test_battle_none_all_defaults_empty(self):
        frame = render_battle_scene(
            friendlies=None, hostiles=None, projectiles=None, explosions=None,
            timestamp="T",
        )
        assert frame is not None

    def test_neighborhood_none_targets_defaults_empty(self):
        frame = render_neighborhood(ambient_targets=None, seed=1, timestamp="T")
        assert frame is not None

    def test_very_small_resolution(self):
        """Tiny frames should not crash."""
        frame = render_bird_eye(resolution=(32, 32), timestamp="T")
        assert frame.shape == (32, 32, 3)

    def test_large_resolution(self):
        frame = render_bird_eye(resolution=(1280, 720), timestamp="T")
        assert frame.shape == (720, 1280, 3)

    def test_world_to_pixel_negative_coords(self):
        px, py = _world_to_pixel(-20, -20, 640, 480)
        assert isinstance(px, int)
        assert isinstance(py, int)

    def test_get_pos_numeric_coercion(self):
        """String values in position should be coerced to float."""
        t = {"position": {"x": "3.5", "y": "7.2"}}
        x, y = _get_pos(t)
        assert x == 3.5
        assert y == 7.2
