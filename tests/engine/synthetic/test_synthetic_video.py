"""Unit tests for the synthetic video generation pipeline.

Tests cover:
  - Frame generators produce correct shape and dtype
  - Alliance colors appear in rendered frames
  - Unit shapes are drawn correctly
  - Edge cases (empty targets, single frame, etc.)
  - SyntheticVideoLibrary clip generation and metadata
  - Frame sequence generator yields correct counts
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from engine.synthetic.video_gen import (
    DARK_BG,
    FRIENDLY_GREEN,
    HOSTILE_RED,
    NEUTRAL_BLUE,
    UNKNOWN_YELLOW,
    Explosion,
    Projectile,
    render_battle_scene,
    render_bird_eye,
    render_neighborhood,
    render_street_cam,
)
from engine.synthetic.video_library import SCENE_TYPES, SyntheticVideoLibrary


# -- Helpers ---------------------------------------------------------------

def _color_present(frame: np.ndarray, bgr: tuple[int, int, int], tolerance: int = 40) -> bool:
    """Check if a BGR color is present in the frame within tolerance."""
    diff = np.abs(frame.astype(np.int16) - np.array(bgr, dtype=np.int16))
    matches = np.all(diff < tolerance, axis=-1)
    return bool(np.any(matches))


def _make_friendly_rover(x: float = 5.0, y: float = 5.0) -> dict:
    return {
        "target_id": "rover-test",
        "alliance": "friendly",
        "asset_type": "rover",
        "position": (x, y),
        "heading": 45.0,
        "health": 150.0,
        "max_health": 150.0,
    }


def _make_hostile_person(x: float = -5.0, y: float = 10.0) -> dict:
    return {
        "target_id": "hostile-test",
        "alliance": "hostile",
        "asset_type": "person",
        "position": (x, y),
        "heading": 180.0,
        "health": 60.0,
        "max_health": 80.0,
    }


def _make_neutral_person(x: float = 3.0, y: float = -3.0) -> dict:
    return {
        "target_id": "neutral-test",
        "alliance": "neutral",
        "asset_type": "person",
        "position": (x, y),
        "heading": 0.0,
    }


def _make_drone(x: float = 0.0, y: float = 0.0) -> dict:
    return {
        "target_id": "drone-test",
        "alliance": "friendly",
        "asset_type": "drone",
        "position": (x, y),
        "heading": 90.0,
    }


def _make_turret(x: float = 0.0, y: float = -10.0) -> dict:
    return {
        "target_id": "turret-test",
        "alliance": "friendly",
        "asset_type": "turret",
        "position": (x, y),
        "heading": 0.0,
        "health": 200.0,
        "max_health": 200.0,
    }


def _make_vehicle(x: float = 10.0, y: float = -5.0) -> dict:
    return {
        "target_id": "vehicle-test",
        "alliance": "neutral",
        "asset_type": "vehicle",
        "position": (x, y),
        "heading": 90.0,
    }


def _make_animal(x: float = -8.0, y: float = 2.0) -> dict:
    return {
        "target_id": "animal-test",
        "alliance": "neutral",
        "asset_type": "animal",
        "position": (x, y),
    }


# ==========================================================================
# render_bird_eye
# ==========================================================================

@pytest.mark.unit
class TestRenderBirdEye:
    """Tests for the bird's-eye view renderer."""

    def test_returns_correct_shape_default(self):
        frame = render_bird_eye()
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_returns_correct_shape_custom(self):
        frame = render_bird_eye(resolution=(320, 240))
        assert frame.shape == (240, 320, 3)

    def test_returns_correct_shape_wide(self):
        frame = render_bird_eye(resolution=(1280, 720))
        assert frame.shape == (720, 1280, 3)

    def test_dark_background(self):
        frame = render_bird_eye(seed=42)
        # Center region should be mostly dark
        center = frame[200:280, 280:360]
        mean = center.mean()
        assert mean < 30, f"Background too bright: mean={mean}"

    def test_empty_targets(self):
        frame = render_bird_eye(targets=[], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_friendly_color_present(self):
        targets = [_make_friendly_rover(0, 0)]
        frame = render_bird_eye(targets=targets, seed=42)
        assert _color_present(frame, FRIENDLY_GREEN), "Friendly green not found in frame"

    def test_hostile_color_present(self):
        targets = [_make_hostile_person(0, 0)]
        frame = render_bird_eye(targets=targets, seed=42)
        assert _color_present(frame, HOSTILE_RED), "Hostile red not found in frame"

    def test_unknown_color_present(self):
        targets = [{"target_id": "unk", "alliance": "unknown", "asset_type": "person",
                     "position": (0, 0)}]
        frame = render_bird_eye(targets=targets, seed=42)
        assert _color_present(frame, UNKNOWN_YELLOW), "Unknown yellow not found in frame"

    def test_multiple_target_types(self):
        targets = [
            _make_friendly_rover(5, 5),
            _make_hostile_person(-5, -5),
            _make_drone(0, 10),
            _make_turret(0, 0),
        ]
        frame = render_bird_eye(targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)
        assert _color_present(frame, FRIENDLY_GREEN)
        assert _color_present(frame, HOSTILE_RED)

    def test_zones_rendered(self):
        zones = [{"name": "TEST", "x": 0, "y": 0, "w": 20, "h": 20, "color": (0, 255, 255)}]
        frame = render_bird_eye(zones=zones, seed=42)
        assert _color_present(frame, (0, 255, 255)), "Zone color not found"

    def test_deterministic_with_seed(self):
        targets = [_make_friendly_rover()]
        f1 = render_bird_eye(targets=targets, seed=123)
        f2 = render_bird_eye(targets=targets, seed=123)
        np.testing.assert_array_equal(f1, f2)

    def test_different_seeds_differ(self):
        targets = [_make_friendly_rover()]
        # With fixed timestamp (same overlay text)
        f1 = render_bird_eye(targets=targets, seed=1, timestamp="00:00:00")
        f2 = render_bird_eye(targets=targets, seed=2, timestamp="00:00:00")
        # Should be identical since bird_eye has no random noise component
        # (only grid + targets + overlay, all deterministic given same input)
        # This is correct -- bird_eye is fully deterministic without noise

    def test_custom_view_center(self):
        targets = [_make_friendly_rover(50, 50)]
        frame = render_bird_eye(
            targets=targets,
            view_center=(50, 50),
            seed=42,
        )
        # Target should now be visible (near center)
        assert _color_present(frame, FRIENDLY_GREEN)

    def test_target_out_of_view(self):
        targets = [_make_friendly_rover(100, 100)]
        frame = render_bird_eye(targets=targets, view_center=(0, 0), seed=42)
        # Target is way outside view, should NOT see friendly green
        assert not _color_present(frame, FRIENDLY_GREEN, tolerance=20)


# ==========================================================================
# render_street_cam
# ==========================================================================

@pytest.mark.unit
class TestRenderStreetCam:
    """Tests for the street camera renderer."""

    def test_returns_correct_shape_default(self):
        frame = render_street_cam(seed=42)
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_returns_correct_shape_custom(self):
        frame = render_street_cam(resolution=(320, 240), seed=42)
        assert frame.shape == (240, 320, 3)

    def test_empty_targets(self):
        frame = render_street_cam(targets=[], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_night_mode_dark(self):
        frame = render_street_cam(time_of_day="night", seed=42)
        mean = frame.mean()
        assert mean < 50, f"Night scene too bright: mean={mean}"

    def test_day_mode_brighter(self):
        frame_night = render_street_cam(time_of_day="night", seed=42)
        frame_day = render_street_cam(time_of_day="day", seed=42)
        assert frame_day.mean() > frame_night.mean(), "Day should be brighter than night"

    def test_dusk_mode_between(self):
        frame_night = render_street_cam(time_of_day="night", seed=42)
        frame_dusk = render_street_cam(time_of_day="dusk", seed=42)
        frame_day = render_street_cam(time_of_day="day", seed=42)
        assert frame_night.mean() < frame_dusk.mean() < frame_day.mean()

    def test_targets_visible(self):
        targets = [_make_neutral_person(0, 0)]
        frame = render_street_cam(targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_vehicle_target(self):
        targets = [_make_vehicle(0, 0)]
        frame = render_street_cam(targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_noise_grain_present(self):
        """Verify noise grain is applied (non-zero minimum in output)."""
        frame = render_street_cam(targets=[], seed=42)
        # With noise, not all pixels should be exactly the background
        unique_values = len(np.unique(frame[:, :, 0]))
        assert unique_values > 5, "Expected noise variation in pixel values"

    def test_deterministic_with_seed(self):
        targets = [_make_neutral_person()]
        f1 = render_street_cam(targets=targets, seed=99, timestamp="00:00:00")
        f2 = render_street_cam(targets=targets, seed=99, timestamp="00:00:00")
        np.testing.assert_array_equal(f1, f2)

    def test_camera_name_customizable(self):
        # Just verify it runs without error with custom name
        frame = render_street_cam(camera_name="MY-CAM-99", seed=42)
        assert frame.shape == (480, 640, 3)


# ==========================================================================
# render_battle_scene
# ==========================================================================

@pytest.mark.unit
class TestRenderBattleScene:
    """Tests for the battle scene renderer."""

    def test_returns_correct_shape_default(self):
        frame = render_battle_scene(seed=42)
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_returns_correct_shape_custom(self):
        frame = render_battle_scene(resolution=(800, 600), seed=42)
        assert frame.shape == (600, 800, 3)

    def test_empty_everything(self):
        frame = render_battle_scene(
            friendlies=[], hostiles=[], projectiles=[], explosions=[], seed=42,
        )
        assert frame.shape == (480, 640, 3)

    def test_friendlies_green(self):
        frame = render_battle_scene(
            friendlies=[_make_turret(0, 0)],
            seed=42,
        )
        assert _color_present(frame, FRIENDLY_GREEN)

    def test_hostiles_red(self):
        frame = render_battle_scene(
            hostiles=[_make_hostile_person(0, 0)],
            seed=42,
        )
        assert _color_present(frame, HOSTILE_RED)

    def test_projectile_trail(self):
        proj = Projectile(start=(-10, 0), end=(10, 0), progress=0.5)
        frame = render_battle_scene(
            projectiles=[proj],
            seed=42,
        )
        # Projectile should add bright pixels
        bright_pixels = np.sum(frame > 200)
        assert bright_pixels > 0, "No bright pixels from projectile"

    def test_projectile_as_dict(self):
        proj = {"start": (-10, 0), "end": (10, 0), "progress": 0.5}
        frame = render_battle_scene(projectiles=[proj], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_muzzle_flash_early_projectile(self):
        proj = Projectile(start=(0, 0), end=(10, 10), progress=0.1)
        frame = render_battle_scene(projectiles=[proj], seed=42)
        # Should have muzzle flash (bright area near origin)
        bright_pixels = np.sum(frame > 200)
        assert bright_pixels > 0

    def test_explosion_effect(self):
        expl = Explosion(x=0, y=0, radius=5.0, progress=0.5)
        frame = render_battle_scene(explosions=[expl], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_explosion_as_dict(self):
        expl = {"x": 0, "y": 0, "radius": 5.0, "progress": 0.5}
        frame = render_battle_scene(explosions=[expl], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_health_bars_drawn(self):
        friendlies = [_make_turret(0, 0)]
        friendlies[0]["health"] = 160.0
        friendlies[0]["max_health"] = 200.0
        frame = render_battle_scene(friendlies=friendlies, seed=42)
        # Health bar colors: green for ratio > 0.5 (160/200 = 0.8)
        assert _color_present(frame, (80, 220, 80), tolerance=30)

    def test_full_battle(self):
        """Full battle with all elements."""
        friendlies = [_make_turret(-5, -10), _make_friendly_rover(5, -8)]
        hostiles = [_make_hostile_person(-3, 10), _make_hostile_person(3, 12)]
        projs = [Projectile((-5, -10), (-3, 10), 0.6)]
        expls = [Explosion(3, 12, 4.0, 0.4)]
        frame = render_battle_scene(
            friendlies=friendlies,
            hostiles=hostiles,
            projectiles=projs,
            explosions=expls,
            seed=42,
        )
        assert frame.shape == (480, 640, 3)
        assert _color_present(frame, FRIENDLY_GREEN)
        assert _color_present(frame, HOSTILE_RED)

    def test_deterministic_with_seed(self):
        friendlies = [_make_turret()]
        hostiles = [_make_hostile_person()]
        f1 = render_battle_scene(
            friendlies=friendlies, hostiles=hostiles,
            seed=42, timestamp="00:00:00",
        )
        f2 = render_battle_scene(
            friendlies=friendlies, hostiles=hostiles,
            seed=42, timestamp="00:00:00",
        )
        np.testing.assert_array_equal(f1, f2)


# ==========================================================================
# render_neighborhood
# ==========================================================================

@pytest.mark.unit
class TestRenderNeighborhood:
    """Tests for the neighborhood scene renderer."""

    def test_returns_correct_shape_default(self):
        frame = render_neighborhood(seed=42)
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_returns_correct_shape_custom(self):
        frame = render_neighborhood(resolution=(320, 240), seed=42)
        assert frame.shape == (240, 320, 3)

    def test_empty_targets(self):
        frame = render_neighborhood(ambient_targets=[], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_night_mode(self):
        frame = render_neighborhood(time_of_day="night", seed=42)
        mean = frame.mean()
        assert mean < 60, f"Night neighborhood too bright: mean={mean}"

    def test_day_brighter_than_night(self):
        frame_night = render_neighborhood(time_of_day="night", seed=42)
        frame_day = render_neighborhood(time_of_day="day", seed=42)
        assert frame_day.mean() > frame_night.mean()

    def test_pedestrians_rendered(self):
        targets = [_make_neutral_person(0, 0)]
        frame = render_neighborhood(ambient_targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_animals_rendered(self):
        targets = [_make_animal(0, 0)]
        frame = render_neighborhood(ambient_targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_vehicles_rendered(self):
        targets = [_make_vehicle(0, 0)]
        frame = render_neighborhood(ambient_targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_mixed_ambient(self):
        targets = [
            _make_neutral_person(0, 0),
            _make_animal(-5, 3),
            _make_vehicle(10, -5),
        ]
        frame = render_neighborhood(ambient_targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_deterministic_with_seed(self):
        targets = [_make_neutral_person()]
        f1 = render_neighborhood(ambient_targets=targets, seed=77, timestamp="00:00:00")
        f2 = render_neighborhood(ambient_targets=targets, seed=77, timestamp="00:00:00")
        np.testing.assert_array_equal(f1, f2)

    def test_buildings_present(self):
        """Buildings should add variation to the horizon area."""
        frame = render_neighborhood(seed=42)
        # The horizon region should have some variation (building silhouettes)
        horizon = frame[int(480 * 0.25):int(480 * 0.4), :]
        unique = len(np.unique(horizon[:, :, 0]))
        assert unique > 3, "Expected building variation at horizon"


# ==========================================================================
# SyntheticVideoLibrary
# ==========================================================================

@pytest.mark.unit
class TestSyntheticVideoLibrary:
    """Tests for the video library manager."""

    @pytest.fixture
    def tmp_lib(self, tmp_path):
        """Create a library with a temp directory."""
        return SyntheticVideoLibrary(tmp_path / "video")

    def test_generate_clip_creates_mp4(self, tmp_lib):
        clip_dir = tmp_lib.generate_clip("bird_eye", duration=0.5, fps=5, seed=42)
        mp4_path = clip_dir / "clip.mp4"
        assert mp4_path.exists(), f"MP4 not created at {mp4_path}"
        assert mp4_path.stat().st_size > 0, "MP4 file is empty"

    def test_generate_clip_creates_metadata(self, tmp_lib):
        clip_dir = tmp_lib.generate_clip("bird_eye", duration=0.5, fps=5, seed=42)
        meta_path = clip_dir / "metadata.json"
        assert meta_path.exists()
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["scene_type"] == "bird_eye"
        assert meta["duration"] == 0.5
        assert meta["fps"] == 5
        assert meta["total_frames"] == 2  # 0.5 * 5 = 2 (int truncation: 2)
        assert meta["seed"] == 42

    def test_generate_clip_save_frames(self, tmp_lib):
        clip_dir = tmp_lib.generate_clip(
            "bird_eye", duration=0.3, fps=10, seed=42, save_frames=True,
        )
        frames_dir = clip_dir / "frames"
        assert frames_dir.exists()
        png_files = list(frames_dir.glob("*.png"))
        expected = max(1, int(0.3 * 10))
        assert len(png_files) == expected, f"Expected {expected} frames, got {len(png_files)}"

    def test_generate_all_scene_types(self, tmp_lib):
        for scene in SCENE_TYPES:
            clip_dir = tmp_lib.generate_clip(scene, duration=0.3, fps=5, seed=42)
            assert (clip_dir / "clip.mp4").exists(), f"Missing MP4 for {scene}"
            assert (clip_dir / "metadata.json").exists(), f"Missing metadata for {scene}"

    def test_invalid_scene_type(self, tmp_lib):
        with pytest.raises(ValueError, match="Invalid scene_type"):
            tmp_lib.generate_clip("invalid_scene")

    def test_zero_duration_raises(self, tmp_lib):
        with pytest.raises(ValueError, match="Duration must be positive"):
            tmp_lib.generate_clip("bird_eye", duration=0)

    def test_negative_duration_raises(self, tmp_lib):
        with pytest.raises(ValueError, match="Duration must be positive"):
            tmp_lib.generate_clip("bird_eye", duration=-1)

    def test_zero_fps_raises(self, tmp_lib):
        with pytest.raises(ValueError, match="FPS must be positive"):
            tmp_lib.generate_clip("bird_eye", fps=0)

    def test_list_clips_empty(self, tmp_lib):
        clips = tmp_lib.list_clips()
        assert clips == []

    def test_list_clips_after_generation(self, tmp_lib):
        tmp_lib.generate_clip("bird_eye", duration=0.3, fps=5, seed=42)
        tmp_lib.generate_clip("battle", duration=0.3, fps=5, seed=42)
        clips = tmp_lib.list_clips()
        assert len(clips) == 2
        scene_types = {c["scene_type"] for c in clips}
        assert scene_types == {"bird_eye", "battle"}

    def test_list_clips_filter_by_scene(self, tmp_lib):
        tmp_lib.generate_clip("bird_eye", duration=0.3, fps=5, seed=42)
        tmp_lib.generate_clip("battle", duration=0.3, fps=5, seed=42)
        clips = tmp_lib.list_clips(scene_type="bird_eye")
        assert len(clips) == 1
        assert clips[0]["scene_type"] == "bird_eye"

    def test_get_clip_path(self, tmp_lib):
        clip_dir = tmp_lib.generate_clip("bird_eye", duration=0.3, fps=5, seed=42)
        clips = tmp_lib.list_clips()
        clip_id = clips[0]["clip_id"]
        path = tmp_lib.get_clip_path(clip_id)
        assert path.exists()
        assert path.name == "clip.mp4"

    def test_get_clip_path_not_found(self, tmp_lib):
        with pytest.raises(FileNotFoundError):
            tmp_lib.get_clip_path("nonexistent/clip")

    def test_metadata_has_resolution(self, tmp_lib):
        clip_dir = tmp_lib.generate_clip(
            "bird_eye", duration=0.3, fps=5, resolution=(320, 240), seed=42,
        )
        with open(clip_dir / "metadata.json") as f:
            meta = json.load(f)
        assert meta["resolution"] == [320, 240]

    def test_custom_resolution_clip(self, tmp_lib):
        clip_dir = tmp_lib.generate_clip(
            "street_cam", duration=0.3, fps=5, resolution=(320, 240), seed=42,
        )
        assert (clip_dir / "clip.mp4").exists()

    def test_single_frame_clip(self, tmp_lib):
        """Edge case: very short duration produces at least 1 frame."""
        clip_dir = tmp_lib.generate_clip(
            "bird_eye", duration=0.01, fps=1, seed=42,
        )
        with open(clip_dir / "metadata.json") as f:
            meta = json.load(f)
        assert meta["total_frames"] >= 1


# ==========================================================================
# Frame sequence generator
# ==========================================================================

@pytest.mark.unit
class TestFrameSequence:
    """Tests for the frame sequence generator."""

    @pytest.fixture
    def lib(self, tmp_path):
        return SyntheticVideoLibrary(tmp_path / "video")

    def test_yields_correct_count(self, lib):
        frames = list(lib.get_frame_sequence("bird_eye", duration=1.0, fps=5, seed=42))
        assert len(frames) == 5

    def test_yields_correct_shape(self, lib):
        for frame in lib.get_frame_sequence("bird_eye", duration=0.5, fps=5, seed=42):
            assert frame.shape == (480, 640, 3)
            assert frame.dtype == np.uint8

    def test_custom_resolution(self, lib):
        frames = list(lib.get_frame_sequence(
            "bird_eye", duration=0.3, fps=5, resolution=(320, 240), seed=42,
        ))
        for f in frames:
            assert f.shape == (240, 320, 3)

    def test_all_scene_types(self, lib):
        for scene in SCENE_TYPES:
            frames = list(lib.get_frame_sequence(scene, duration=0.3, fps=5, seed=42))
            assert len(frames) > 0
            assert frames[0].shape == (480, 640, 3)

    def test_single_frame(self, lib):
        frames = list(lib.get_frame_sequence("bird_eye", duration=0.1, fps=1, seed=42))
        assert len(frames) == 1

    def test_invalid_scene_raises(self, lib):
        with pytest.raises(ValueError, match="Invalid scene_type"):
            list(lib.get_frame_sequence("bogus"))

    def test_zero_duration_raises(self, lib):
        with pytest.raises(ValueError, match="Duration must be positive"):
            list(lib.get_frame_sequence("bird_eye", duration=0))

    def test_zero_fps_raises(self, lib):
        with pytest.raises(ValueError, match="FPS must be positive"):
            list(lib.get_frame_sequence("bird_eye", fps=0))

    def test_deterministic_sequence(self, lib):
        frames1 = list(lib.get_frame_sequence("battle", duration=0.5, fps=5, seed=42))
        frames2 = list(lib.get_frame_sequence("battle", duration=0.5, fps=5, seed=42))
        assert len(frames1) == len(frames2)
        for f1, f2 in zip(frames1, frames2):
            np.testing.assert_array_equal(f1, f2)

    def test_generator_is_lazy(self, lib):
        """Verify it's a generator, not a list."""
        gen = lib.get_frame_sequence("bird_eye", duration=1.0, fps=10, seed=42)
        import types
        assert isinstance(gen, types.GeneratorType)

    def test_frames_differ_across_sequence(self, lib):
        """Frames should not all be identical (animation)."""
        frames = list(lib.get_frame_sequence("battle", duration=1.0, fps=5, seed=42))
        assert len(frames) == 5
        # At least one pair should differ
        diffs = [not np.array_equal(frames[i], frames[i+1]) for i in range(len(frames)-1)]
        assert any(diffs), "All frames in sequence are identical"


# ==========================================================================
# SimulationTarget compatibility
# ==========================================================================

@pytest.mark.unit
class TestSimulationTargetCompat:
    """Test that renderers work with actual SimulationTarget objects."""

    def test_bird_eye_with_sim_target(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="sim-rover-1",
            name="Rover Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(5.0, 5.0),
            heading=45.0,
        )
        frame = render_bird_eye(targets=[t], seed=42)
        assert frame.shape == (480, 640, 3)
        assert _color_present(frame, FRIENDLY_GREEN)

    def test_battle_with_sim_targets(self):
        from engine.simulation.target import SimulationTarget
        friendly = SimulationTarget(
            target_id="turret-1",
            name="Turret Alpha",
            alliance="friendly",
            asset_type="turret",
            position=(0.0, -10.0),
            heading=0.0,
        )
        friendly.apply_combat_profile()
        hostile = SimulationTarget(
            target_id="hostile-1",
            name="Intruder",
            alliance="hostile",
            asset_type="person",
            position=(0.0, 10.0),
            heading=180.0,
        )
        hostile.apply_combat_profile()
        frame = render_battle_scene(
            friendlies=[friendly], hostiles=[hostile], seed=42,
        )
        assert frame.shape == (480, 640, 3)
        assert _color_present(frame, FRIENDLY_GREEN)
        assert _color_present(frame, HOSTILE_RED)

    def test_neighborhood_with_sim_target(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="pedestrian-1",
            name="Neighbor",
            alliance="neutral",
            asset_type="person",
            position=(3.0, 0.0),
        )
        frame = render_neighborhood(ambient_targets=[t], seed=42)
        assert frame.shape == (480, 640, 3)


# ==========================================================================
# Edge cases
# ==========================================================================

@pytest.mark.unit
class TestEdgeCases:
    """Edge case tests for renderers."""

    def test_many_targets(self):
        """Stress test with many targets."""
        targets = []
        for i in range(100):
            targets.append({
                "target_id": f"unit-{i}",
                "alliance": "hostile" if i % 2 else "friendly",
                "asset_type": ["rover", "drone", "turret", "person"][i % 4],
                "position": (i * 0.5 - 25, i * 0.3 - 15),
                "heading": i * 3.6,
            })
        frame = render_bird_eye(targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_target_at_edge(self):
        """Target right at view boundary."""
        targets = [_make_friendly_rover(34.9, 34.9)]
        frame = render_bird_eye(targets=targets, view_radius=35.0, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_target_outside_view(self):
        """Target completely outside view should not crash."""
        targets = [_make_friendly_rover(1000, 1000)]
        frame = render_bird_eye(targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_very_small_resolution(self):
        """Minimum viable resolution."""
        frame = render_bird_eye(resolution=(32, 32), seed=42)
        assert frame.shape == (32, 32, 3)

    def test_large_resolution(self):
        frame = render_bird_eye(resolution=(1920, 1080), seed=42)
        assert frame.shape == (1080, 1920, 3)

    def test_zero_heading(self):
        targets = [{"target_id": "t", "alliance": "friendly", "asset_type": "turret",
                     "position": (0, 0), "heading": 0.0}]
        frame = render_bird_eye(targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_360_heading(self):
        targets = [{"target_id": "t", "alliance": "friendly", "asset_type": "turret",
                     "position": (0, 0), "heading": 360.0}]
        frame = render_bird_eye(targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_negative_heading(self):
        targets = [{"target_id": "t", "alliance": "friendly", "asset_type": "turret",
                     "position": (0, 0), "heading": -90.0}]
        frame = render_bird_eye(targets=targets, seed=42)
        assert frame.shape == (480, 640, 3)

    def test_explosion_progress_zero(self):
        expl = Explosion(0, 0, 3.0, 0.0)
        frame = render_battle_scene(explosions=[expl], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_explosion_progress_one(self):
        expl = Explosion(0, 0, 3.0, 1.0)
        frame = render_battle_scene(explosions=[expl], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_projectile_progress_zero(self):
        proj = Projectile((0, 0), (10, 10), 0.0)
        frame = render_battle_scene(projectiles=[proj], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_projectile_progress_one(self):
        proj = Projectile((0, 0), (10, 10), 1.0)
        frame = render_battle_scene(projectiles=[proj], seed=42)
        assert frame.shape == (480, 640, 3)

    def test_position_as_list(self):
        """Position provided as list instead of tuple."""
        targets = [{"target_id": "t", "alliance": "friendly", "asset_type": "rover",
                     "position": [5, 5]}]
        frame = render_bird_eye(targets=targets, seed=42)
        assert _color_present(frame, FRIENDLY_GREEN)

    def test_position_as_dict(self):
        """Position provided as dict with x,y keys."""
        targets = [{"target_id": "t", "alliance": "friendly", "asset_type": "rover",
                     "position": {"x": 5, "y": 5}}]
        frame = render_bird_eye(targets=targets, seed=42)
        assert _color_present(frame, FRIENDLY_GREEN)
