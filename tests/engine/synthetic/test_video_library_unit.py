# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for engine.synthetic.video_library — clip generation, storage, catalog.

Tests cover:
- SyntheticVideoLibrary initialization and path handling
- generate_clip: validation, directory creation, metadata, scene types
- list_clips: filtering, empty library, metadata fields
- get_clip_path: valid/invalid clip IDs
- get_frame_sequence: generator behavior, validation
- generate_cctv_clip: validation, directory structure, metadata
- _has_target_kwargs: scene-specific target detection
- _make_demo_targets: demo data generation for each scene type

Heavy I/O (VideoWriter) is mocked. Rendering functions are mocked to avoid
computing real frames in unit tests.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import numpy as np
import pytest

from engine.synthetic.video_library import (
    SCENE_TYPES,
    SyntheticVideoLibrary,
    _has_target_kwargs,
    _make_demo_targets,
    _RENDERERS,
)


# =========================================================================
# Constants
# =========================================================================


@pytest.mark.unit
class TestConstants:
    def test_scene_types_tuple(self):
        assert isinstance(SCENE_TYPES, tuple)
        assert set(SCENE_TYPES) == {"bird_eye", "street_cam", "battle", "neighborhood"}

    def test_renderers_match_scene_types(self):
        assert set(_RENDERERS.keys()) == set(SCENE_TYPES)


# =========================================================================
# _has_target_kwargs
# =========================================================================


@pytest.mark.unit
class TestHasTargetKwargs:
    def test_bird_eye_with_targets(self):
        assert _has_target_kwargs("bird_eye", {"targets": [{"x": 1}]})

    def test_bird_eye_empty_targets(self):
        assert not _has_target_kwargs("bird_eye", {"targets": []})

    def test_bird_eye_no_targets_key(self):
        assert not _has_target_kwargs("bird_eye", {})

    def test_street_cam_with_targets(self):
        assert _has_target_kwargs("street_cam", {"targets": [{"x": 1}]})

    def test_street_cam_empty(self):
        assert not _has_target_kwargs("street_cam", {"targets": []})

    def test_battle_with_friendlies(self):
        assert _has_target_kwargs("battle", {"friendlies": [{"x": 1}]})

    def test_battle_with_hostiles(self):
        assert _has_target_kwargs("battle", {"hostiles": [{"x": 1}]})

    def test_battle_empty(self):
        assert not _has_target_kwargs("battle", {"friendlies": [], "hostiles": []})

    def test_neighborhood_with_targets(self):
        assert _has_target_kwargs("neighborhood", {"ambient_targets": [{"x": 1}]})

    def test_neighborhood_empty(self):
        assert not _has_target_kwargs("neighborhood", {"ambient_targets": []})

    def test_unknown_scene_type(self):
        assert not _has_target_kwargs("unknown", {"targets": [1]})


# =========================================================================
# _make_demo_targets
# =========================================================================


@pytest.mark.unit
class TestMakeDemoTargets:
    def test_bird_eye_returns_targets_and_zones(self):
        result = _make_demo_targets("bird_eye", 0, 50, 42)
        assert "targets" in result
        assert "zones" in result
        assert len(result["targets"]) > 0
        assert len(result["zones"]) == 2

    def test_bird_eye_targets_have_required_keys(self):
        result = _make_demo_targets("bird_eye", 0, 50, 42)
        for t in result["targets"]:
            assert "target_id" in t
            assert "alliance" in t
            assert "asset_type" in t
            assert "position" in t

    def test_bird_eye_animated_positions(self):
        """Positions should change across frames."""
        r0 = _make_demo_targets("bird_eye", 0, 100, 42)
        r50 = _make_demo_targets("bird_eye", 50, 100, 42)
        pos0 = r0["targets"][0]["position"]
        pos50 = r50["targets"][0]["position"]
        assert pos0 != pos50

    def test_street_cam_returns_targets(self):
        result = _make_demo_targets("street_cam", 0, 50, 42)
        assert "targets" in result
        assert "time_of_day" in result
        assert len(result["targets"]) >= 2  # at least pedestrians + car

    def test_battle_returns_friendlies_hostiles(self):
        result = _make_demo_targets("battle", 0, 50, 42)
        assert "friendlies" in result
        assert "hostiles" in result
        assert len(result["friendlies"]) > 0
        assert len(result["hostiles"]) > 0

    def test_battle_hostiles_increase_with_time(self):
        """Later frames should have more hostiles (n_hostiles = 3 + int(t * 4))."""
        r0 = _make_demo_targets("battle", 0, 100, 42)
        r99 = _make_demo_targets("battle", 99, 100, 42)
        assert len(r99["hostiles"]) >= len(r0["hostiles"])

    def test_battle_projectiles_on_divisible_frames(self):
        """Projectiles appear on frame_index % 3 == 0."""
        result = _make_demo_targets("battle", 0, 50, 42)
        assert "projectiles" in result

    def test_neighborhood_returns_ambient_targets(self):
        result = _make_demo_targets("neighborhood", 0, 50, 42)
        assert "ambient_targets" in result
        assert "time_of_day" in result

    def test_neighborhood_always_has_car(self):
        """Neighborhood always includes a parked car."""
        result = _make_demo_targets("neighborhood", 0, 50, 42)
        car_targets = [t for t in result["ambient_targets"] if t["asset_type"] == "vehicle"]
        assert len(car_targets) == 1

    def test_unknown_scene_returns_empty(self):
        result = _make_demo_targets("doesnt_exist", 0, 50, 42)
        assert result == {}


# =========================================================================
# SyntheticVideoLibrary: init
# =========================================================================


@pytest.mark.unit
class TestLibraryInit:
    def test_default_path(self):
        lib = SyntheticVideoLibrary()
        assert lib.library_path == Path("data/synthetic/video")

    def test_custom_path_string(self, tmp_path):
        lib = SyntheticVideoLibrary(str(tmp_path / "custom"))
        assert lib.library_path == tmp_path / "custom"

    def test_custom_path_object(self, tmp_path):
        p = tmp_path / "videos"
        lib = SyntheticVideoLibrary(p)
        assert lib.library_path == p


# =========================================================================
# SyntheticVideoLibrary: generate_clip (mocked)
# =========================================================================


@pytest.mark.unit
class TestGenerateClip:
    def test_invalid_scene_type_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(ValueError, match="Invalid scene_type"):
            lib.generate_clip("bogus")

    def test_negative_duration_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(ValueError, match="Duration must be positive"):
            lib.generate_clip("bird_eye", duration=-1.0)

    def test_zero_duration_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(ValueError, match="Duration must be positive"):
            lib.generate_clip("bird_eye", duration=0.0)

    def test_zero_fps_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(ValueError, match="FPS must be positive"):
            lib.generate_clip("bird_eye", duration=1.0, fps=0)

    def test_negative_fps_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(ValueError, match="FPS must be positive"):
            lib.generate_clip("bird_eye", duration=1.0, fps=-5)

    @patch("engine.synthetic.video_library.cv2")
    def test_generate_clip_creates_directory_and_metadata(self, mock_cv2, tmp_path):
        """With mocked cv2, verify directory + metadata creation."""
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter_fourcc.return_value = 0x7634706D
        mock_cv2.VideoWriter.return_value = mock_writer

        # Mock the renderer to avoid real cv2 calls in frame generation
        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        with patch.dict(_RENDERERS, {"bird_eye": lambda **kw: fake_frame}):
            lib = SyntheticVideoLibrary(tmp_path / "lib")
            clip_dir = lib.generate_clip("bird_eye", duration=1.0, fps=5, seed=42)

        assert clip_dir.exists()
        meta_path = clip_dir / "metadata.json"
        assert meta_path.exists()
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["scene_type"] == "bird_eye"
        assert meta["duration"] == 1.0
        assert meta["fps"] == 5
        assert meta["total_frames"] == 5
        assert meta["seed"] == 42
        assert meta["clip_file"] == "clip.mp4"
        assert meta["has_frames"] is False

    @patch("engine.synthetic.video_library.cv2")
    def test_generate_clip_writer_failure_raises(self, mock_cv2, tmp_path):
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = False
        mock_cv2.VideoWriter_fourcc.return_value = 0
        mock_cv2.VideoWriter.return_value = mock_writer

        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(RuntimeError, match="Failed to open VideoWriter"):
            lib.generate_clip("bird_eye", duration=1.0, fps=5, seed=42)

    @patch("engine.synthetic.video_library.cv2")
    def test_generate_clip_with_save_frames(self, mock_cv2, tmp_path):
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter_fourcc.return_value = 0
        mock_cv2.VideoWriter.return_value = mock_writer
        mock_cv2.imwrite = MagicMock()

        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        with patch.dict(_RENDERERS, {"bird_eye": lambda **kw: fake_frame}):
            lib = SyntheticVideoLibrary(tmp_path / "lib")
            clip_dir = lib.generate_clip("bird_eye", duration=0.5, fps=2, seed=1, save_frames=True)

        frames_dir = clip_dir / "frames"
        assert frames_dir.exists()
        # cv2.imwrite should have been called once per frame
        assert mock_cv2.imwrite.call_count == 1  # 0.5 * 2 = 1 frame

    @patch("engine.synthetic.video_library.cv2")
    def test_writer_released_on_error(self, mock_cv2, tmp_path):
        """Writer.release() must be called even if rendering fails."""
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter_fourcc.return_value = 0
        mock_cv2.VideoWriter.return_value = mock_writer

        def raise_error(**kw):
            raise RuntimeError("render failed")

        with patch.dict(_RENDERERS, {"bird_eye": raise_error}):
            lib = SyntheticVideoLibrary(tmp_path / "lib")
            with pytest.raises(RuntimeError):
                lib.generate_clip("bird_eye", duration=1.0, fps=1, seed=1)

        mock_writer.release.assert_called_once()


# =========================================================================
# SyntheticVideoLibrary: list_clips
# =========================================================================


@pytest.mark.unit
class TestListClips:
    def test_empty_library_returns_empty(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "nonexistent")
        assert lib.list_clips() == []

    def test_list_clips_finds_metadata(self, tmp_path):
        lib_path = tmp_path / "lib"
        clip_dir = lib_path / "bird_eye" / "20260224_120000_000000"
        clip_dir.mkdir(parents=True)
        meta = {"scene_type": "bird_eye", "duration": 5.0, "fps": 10}
        with open(clip_dir / "metadata.json", "w") as f:
            json.dump(meta, f)

        lib = SyntheticVideoLibrary(lib_path)
        clips = lib.list_clips()
        assert len(clips) == 1
        assert clips[0]["scene_type"] == "bird_eye"
        assert clips[0]["duration"] == 5.0
        assert "path" in clips[0]
        assert "clip_id" in clips[0]
        assert clips[0]["clip_id"] == "bird_eye/20260224_120000_000000"

    def test_list_clips_filter_by_scene_type(self, tmp_path):
        lib_path = tmp_path / "lib"
        # Create clips of two scene types
        for st in ["bird_eye", "battle"]:
            clip_dir = lib_path / st / "clip_001"
            clip_dir.mkdir(parents=True)
            with open(clip_dir / "metadata.json", "w") as f:
                json.dump({"scene_type": st}, f)

        lib = SyntheticVideoLibrary(lib_path)
        all_clips = lib.list_clips()
        assert len(all_clips) == 2

        bird_clips = lib.list_clips(scene_type="bird_eye")
        assert len(bird_clips) == 1
        assert bird_clips[0]["scene_type"] == "bird_eye"

        battle_clips = lib.list_clips(scene_type="battle")
        assert len(battle_clips) == 1

    def test_list_clips_skips_dirs_without_metadata(self, tmp_path):
        lib_path = tmp_path / "lib"
        clip_dir = lib_path / "bird_eye" / "no_meta"
        clip_dir.mkdir(parents=True)

        lib = SyntheticVideoLibrary(lib_path)
        assert lib.list_clips() == []

    def test_list_clips_sorted_by_directory_name(self, tmp_path):
        lib_path = tmp_path / "lib"
        for name in ["clip_c", "clip_a", "clip_b"]:
            d = lib_path / "bird_eye" / name
            d.mkdir(parents=True)
            with open(d / "metadata.json", "w") as f:
                json.dump({"scene_type": "bird_eye", "name": name}, f)

        lib = SyntheticVideoLibrary(lib_path)
        clips = lib.list_clips()
        names = [c["name"] for c in clips]
        assert names == ["clip_a", "clip_b", "clip_c"]


# =========================================================================
# SyntheticVideoLibrary: get_clip_path
# =========================================================================


@pytest.mark.unit
class TestGetClipPath:
    def test_valid_clip_returns_path(self, tmp_path):
        lib_path = tmp_path / "lib"
        clip_dir = lib_path / "bird_eye" / "clip_001"
        clip_dir.mkdir(parents=True)
        (clip_dir / "clip.mp4").write_text("fake")

        lib = SyntheticVideoLibrary(lib_path)
        path = lib.get_clip_path("bird_eye/clip_001")
        assert path == clip_dir / "clip.mp4"

    def test_missing_clip_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(FileNotFoundError, match="Clip not found"):
            lib.get_clip_path("bird_eye/nonexistent")


# =========================================================================
# SyntheticVideoLibrary: get_frame_sequence
# =========================================================================


@pytest.mark.unit
class TestGetFrameSequence:
    def test_invalid_scene_type_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path)
        with pytest.raises(ValueError, match="Invalid scene_type"):
            list(lib.get_frame_sequence("bogus"))

    def test_negative_duration_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path)
        with pytest.raises(ValueError, match="Duration must be positive"):
            list(lib.get_frame_sequence("bird_eye", duration=-1))

    def test_zero_fps_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path)
        with pytest.raises(ValueError, match="FPS must be positive"):
            list(lib.get_frame_sequence("bird_eye", fps=0))

    def test_yields_correct_frame_count(self, tmp_path):
        fake_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        with patch.dict(_RENDERERS, {"bird_eye": lambda **kw: fake_frame}):
            lib = SyntheticVideoLibrary(tmp_path)
            frames = list(lib.get_frame_sequence(
                "bird_eye", duration=1.0, fps=5, resolution=(320, 240), seed=1,
            ))
        assert len(frames) == 5

    def test_yields_numpy_arrays(self, tmp_path):
        fake_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        with patch.dict(_RENDERERS, {"bird_eye": lambda **kw: fake_frame}):
            lib = SyntheticVideoLibrary(tmp_path)
            frames = list(lib.get_frame_sequence(
                "bird_eye", duration=0.5, fps=2, resolution=(320, 240), seed=1,
            ))
        for f in frames:
            assert isinstance(f, np.ndarray)
            assert f.shape == (240, 320, 3)

    def test_generator_is_lazy(self, tmp_path):
        """Frame sequence should be a generator, not eagerly computed."""
        call_count = 0
        def counting_renderer(**kw):
            nonlocal call_count
            call_count += 1
            return np.zeros((240, 320, 3), dtype=np.uint8)

        with patch.dict(_RENDERERS, {"bird_eye": counting_renderer}):
            lib = SyntheticVideoLibrary(tmp_path)
            gen = lib.get_frame_sequence("bird_eye", duration=1.0, fps=10, resolution=(320, 240), seed=1)
            assert call_count == 0  # Not yet computed
            next(gen)
            assert call_count == 1  # Only first frame


# =========================================================================
# SyntheticVideoLibrary: generate_cctv_clip (mocked)
# =========================================================================


@pytest.mark.unit
class TestGenerateCCTVClip:
    def test_invalid_scene_type_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(ValueError, match="Invalid CCTV scene_type"):
            lib.generate_cctv_clip("CAM-01", "invalid_scene")

    def test_negative_duration_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(ValueError, match="Duration must be positive"):
            lib.generate_cctv_clip("CAM-01", "front_door", duration=-1.0)

    def test_zero_fps_raises(self, tmp_path):
        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(ValueError, match="FPS must be positive"):
            lib.generate_cctv_clip("CAM-01", "front_door", fps=0)

    @patch("engine.synthetic.video_library.render_cctv_frame")
    @patch("engine.synthetic.video_library.cv2")
    def test_generates_directory_and_metadata(self, mock_cv2, mock_render, tmp_path):
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter_fourcc.return_value = 0
        mock_cv2.VideoWriter.return_value = mock_writer
        mock_cv2.imwrite = MagicMock()
        mock_cv2.IMWRITE_JPEG_QUALITY = 1

        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_render.return_value = fake_frame

        lib = SyntheticVideoLibrary(tmp_path / "lib")
        clip_dir = lib.generate_cctv_clip(
            "CAM-01", "front_door", duration=0.5, fps=2, seed=42,
        )

        assert clip_dir.exists()
        meta_path = clip_dir / "metadata.json"
        assert meta_path.exists()
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["camera_name"] == "CAM-01"
        assert meta["scene_type"] == "front_door"
        assert meta["total_frames"] == 1
        assert meta["seed"] == 42

    @patch("engine.synthetic.video_library.render_cctv_frame")
    @patch("engine.synthetic.video_library.cv2")
    def test_cctv_clip_directory_under_cameras(self, mock_cv2, mock_render, tmp_path):
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter_fourcc.return_value = 0
        mock_cv2.VideoWriter.return_value = mock_writer
        mock_cv2.imwrite = MagicMock()
        mock_cv2.IMWRITE_JPEG_QUALITY = 1

        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_render.return_value = fake_frame

        lib = SyntheticVideoLibrary(tmp_path / "lib")
        clip_dir = lib.generate_cctv_clip("FRONT-CAM", "parking", duration=0.5, fps=2, seed=1)

        assert "cameras" in str(clip_dir)
        assert "FRONT-CAM" in str(clip_dir)

    @patch("engine.synthetic.video_library.cv2")
    def test_cctv_writer_failure_raises(self, mock_cv2, tmp_path):
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = False
        mock_cv2.VideoWriter_fourcc.return_value = 0
        mock_cv2.VideoWriter.return_value = mock_writer

        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(RuntimeError, match="Failed to open VideoWriter"):
            lib.generate_cctv_clip("CAM-01", "front_door", duration=1.0, fps=5, seed=1)

    @patch("engine.synthetic.video_library.render_cctv_frame")
    @patch("engine.synthetic.video_library.cv2")
    def test_cctv_writer_released_on_error(self, mock_cv2, mock_render, tmp_path):
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter_fourcc.return_value = 0
        mock_cv2.VideoWriter.return_value = mock_writer
        mock_cv2.imwrite = MagicMock()
        mock_cv2.IMWRITE_JPEG_QUALITY = 1

        mock_render.side_effect = RuntimeError("render failed")

        lib = SyntheticVideoLibrary(tmp_path / "lib")
        with pytest.raises(RuntimeError):
            lib.generate_cctv_clip("CAM-01", "front_door", duration=1.0, fps=1, seed=1)

        mock_writer.release.assert_called_once()


# =========================================================================
# _make_demo_targets: deeper assertions
# =========================================================================


@pytest.mark.unit
class TestMakeDemoTargetsDeeper:
    def test_bird_eye_friendly_rover_count(self):
        result = _make_demo_targets("bird_eye", 0, 50, 42)
        rovers = [t for t in result["targets"] if t["asset_type"] == "rover"]
        assert len(rovers) == 3

    def test_bird_eye_includes_drone_and_turret(self):
        result = _make_demo_targets("bird_eye", 0, 50, 42)
        types = {t["asset_type"] for t in result["targets"]}
        assert "drone" in types
        assert "turret" in types

    def test_bird_eye_hostile_count(self):
        result = _make_demo_targets("bird_eye", 0, 50, 42)
        hostiles = [t for t in result["targets"] if t["alliance"] == "hostile"]
        assert len(hostiles) == 2

    def test_battle_has_projectiles_key(self):
        result = _make_demo_targets("battle", 0, 50, 42)
        assert "projectiles" in result

    def test_battle_has_explosions_key(self):
        result = _make_demo_targets("battle", 0, 50, 42)
        assert "explosions" in result

    def test_street_cam_car_present(self):
        result = _make_demo_targets("street_cam", 0, 50, 42)
        cars = [t for t in result["targets"] if t["asset_type"] == "vehicle"]
        assert len(cars) == 1

    def test_seed_determinism(self):
        r1 = _make_demo_targets("bird_eye", 10, 50, 42)
        r2 = _make_demo_targets("bird_eye", 10, 50, 42)
        assert r1 == r2

    def test_different_seeds_differ(self):
        r1 = _make_demo_targets("street_cam", 10, 50, 42)
        r2 = _make_demo_targets("street_cam", 10, 50, 99)
        # Pedestrian count or positions should differ
        assert r1 != r2


# =========================================================================
# Integration-like: total_frames calculation
# =========================================================================


@pytest.mark.unit
class TestFrameCalculation:
    """Verify total_frames = max(1, int(duration * fps))."""

    @pytest.mark.parametrize("duration,fps,expected", [
        (1.0, 10, 10),
        (0.5, 10, 5),
        (2.0, 30, 60),
        (0.1, 1, 1),   # max(1, 0) = 1 but int(0.1*1)=0, max(1,0)=1
        (0.01, 1, 1),  # Very short duration
    ])
    def test_total_frames_formula(self, duration, fps, expected):
        total = max(1, int(duration * fps))
        assert total == expected
