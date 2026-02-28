# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SyntheticVideoLibrary — generate, store, and retrieve synthetic video clips.

Each clip is stored as a directory under ``{library_path}/{scene_type}/{timestamp}/``
containing:
  - ``clip.mp4`` — the video file (mp4v codec)
  - ``metadata.json`` — scene parameters, frame count, duration, resolution
  - ``frames/`` — individual PNG frames (optional, for debugging)

Uses OpenCV VideoWriter with mp4v codec.  No ffmpeg dependency.
"""

from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

import cv2
import numpy as np

from engine.synthetic.video_gen import (
    CCTV_SCENE_TYPES,
    Explosion,
    Projectile,
    render_battle_scene,
    render_bird_eye,
    render_cctv_frame,
    render_neighborhood,
    render_street_cam,
)

# Valid scene types
SCENE_TYPES = ("bird_eye", "street_cam", "battle", "neighborhood")


def _make_demo_targets(
    scene_type: str,
    frame_index: int,
    total_frames: int,
    seed: int,
) -> dict[str, Any]:
    """Generate demo targets for a given frame in a sequence.

    Returns kwargs suitable for the corresponding render_* function.
    Creates animated targets that move across frames for realistic clips.
    """
    rng = random.Random(seed + frame_index)
    t = frame_index / max(1, total_frames - 1)  # normalized time 0..1

    if scene_type == "bird_eye":
        targets = []
        # Friendly patrol rovers
        for i in range(3):
            angle = t * 2 * math.pi + i * (2 * math.pi / 3)
            r = 12.0 + i * 3
            targets.append({
                "target_id": f"rover-{i}",
                "alliance": "friendly",
                "asset_type": "rover",
                "position": (r * math.cos(angle), r * math.sin(angle)),
                "heading": math.degrees(angle) + 90,
            })
        # Friendly drone
        targets.append({
            "target_id": "drone-0",
            "alliance": "friendly",
            "asset_type": "drone",
            "position": (5 * math.cos(t * 4), 5 * math.sin(t * 4)),
            "heading": t * 360,
        })
        # Turret
        targets.append({
            "target_id": "turret-0",
            "alliance": "friendly",
            "asset_type": "turret",
            "position": (0.0, 0.0),
            "heading": t * 180,
        })
        # Hostiles approaching
        for i in range(2):
            hx = -25.0 + t * 20.0 + i * 5
            hy = 15.0 - i * 10
            targets.append({
                "target_id": f"hostile-{i}",
                "alliance": "hostile",
                "asset_type": "person",
                "position": (hx, hy),
                "heading": 90.0,
            })
        # Zone
        zones = [
            {"name": "YARD", "x": 0, "y": 0, "w": 30, "h": 30, "color": (80, 80, 40)},
            {"name": "STREET", "x": 0, "y": -20, "w": 40, "h": 8, "color": (60, 60, 80)},
        ]
        return {"targets": targets, "zones": zones}

    elif scene_type == "street_cam":
        targets = []
        # Pedestrians walking
        for i in range(rng.randint(1, 4)):
            targets.append({
                "target_id": f"ped-{i}",
                "alliance": "neutral",
                "asset_type": "person",
                "position": (-15 + t * 30 + i * 5, rng.uniform(-10, 10)),
                "heading": 90.0,
            })
        # Car
        targets.append({
            "target_id": "car-0",
            "alliance": "neutral",
            "asset_type": "vehicle",
            "position": (20 - t * 40, -5.0),
            "heading": 270.0,
        })
        return {"targets": targets, "time_of_day": "night"}

    elif scene_type == "battle":
        friendlies = []
        hostiles = []
        projectiles = []
        explosions_list = []

        # Friendly turrets
        for i in range(2):
            friendlies.append({
                "target_id": f"turret-{i}",
                "alliance": "friendly",
                "asset_type": "turret",
                "position": (-5.0 + i * 10, -10.0),
                "heading": t * 60 + i * 30,
                "health": 180.0 - t * 40,
                "max_health": 200.0,
            })
        # Friendly rover
        friendlies.append({
            "target_id": "rover-0",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": (8 * math.cos(t * 3), -5 + 3 * math.sin(t * 2)),
            "heading": t * 120,
            "health": 120.0,
            "max_health": 150.0,
        })

        # Hostile wave
        n_hostiles = 3 + int(t * 4)
        for i in range(n_hostiles):
            hx = -20 + rng.uniform(-5, 5) + t * 15
            hy = 10 + rng.uniform(-8, 8)
            hostiles.append({
                "target_id": f"hostile-{i}",
                "alliance": "hostile",
                "asset_type": "person",
                "position": (hx, hy),
                "heading": 180.0 + rng.uniform(-30, 30),
                "health": rng.uniform(30, 80),
                "max_health": 80.0,
            })

        # Projectiles from turrets to hostiles
        if hostiles and frame_index % 3 == 0:
            src = friendlies[0]
            tgt = rng.choice(hostiles)
            projectiles.append(Projectile(
                start=src["position"],
                end=tgt["position"],
                progress=rng.uniform(0.1, 0.9),
            ))

        # Random explosions
        if rng.random() < 0.3:
            explosions_list.append(Explosion(
                x=rng.uniform(-15, 15),
                y=rng.uniform(-5, 15),
                radius=rng.uniform(2, 5),
                progress=rng.uniform(0.2, 0.8),
            ))

        return {
            "friendlies": friendlies,
            "hostiles": hostiles,
            "projectiles": projectiles,
            "explosions": explosions_list,
        }

    elif scene_type == "neighborhood":
        targets = []
        # Pedestrians
        for i in range(rng.randint(0, 3)):
            targets.append({
                "target_id": f"ped-{i}",
                "alliance": "neutral",
                "asset_type": "person",
                "position": (-10 + t * 20 + i * 5, rng.uniform(-5, 5)),
            })
        # Dog or cat
        if rng.random() < 0.5:
            targets.append({
                "target_id": "animal-0",
                "alliance": "neutral",
                "asset_type": "animal",
                "position": (rng.uniform(-10, 10), rng.uniform(-3, 3)),
            })
        # Parked car
        targets.append({
            "target_id": "car-0",
            "alliance": "neutral",
            "asset_type": "vehicle",
            "position": (15.0, -8.0),
            "heading": 0.0,
        })
        return {"ambient_targets": targets, "time_of_day": "night"}

    return {}


# Map scene_type -> renderer function name
_RENDERERS = {
    "bird_eye": render_bird_eye,
    "street_cam": render_street_cam,
    "battle": render_battle_scene,
    "neighborhood": render_neighborhood,
}


class SyntheticVideoLibrary:
    """Generate, store, and manage synthetic video clips."""

    def __init__(self, library_path: str | Path = "data/synthetic/video") -> None:
        self._library_path = Path(library_path)

    @property
    def library_path(self) -> Path:
        return self._library_path

    def generate_clip(
        self,
        scene_type: str,
        duration: float = 5.0,
        fps: int = 10,
        resolution: tuple[int, int] = (640, 480),
        seed: int | None = None,
        save_frames: bool = False,
        **kwargs: Any,
    ) -> Path:
        """Generate a video clip and save it to the library.

        Args:
            scene_type: One of "bird_eye", "street_cam", "battle", "neighborhood".
            duration: Clip duration in seconds.
            fps: Frames per second.
            resolution: (width, height).
            seed: Random seed for deterministic generation.
            save_frames: Also save individual PNG frames.
            **kwargs: Additional arguments passed to the renderer.

        Returns:
            Path to the clip directory.

        Raises:
            ValueError: If scene_type is invalid or duration/fps invalid.
        """
        if scene_type not in SCENE_TYPES:
            raise ValueError(
                f"Invalid scene_type '{scene_type}'. Must be one of {SCENE_TYPES}"
            )
        if duration <= 0:
            raise ValueError(f"Duration must be positive, got {duration}")
        if fps <= 0:
            raise ValueError(f"FPS must be positive, got {fps}")

        total_frames = max(1, int(duration * fps))
        if seed is None:
            seed = int(time.time() * 1000) % (2**31)

        # Create clip directory
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        clip_dir = self._library_path / scene_type / ts
        clip_dir.mkdir(parents=True, exist_ok=True)

        if save_frames:
            frames_dir = clip_dir / "frames"
            frames_dir.mkdir(exist_ok=True)

        # Set up video writer
        width, height = resolution
        clip_path = clip_dir / "clip.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(clip_path), fourcc, fps, (width, height))

        if not writer.isOpened():
            raise RuntimeError(f"Failed to open VideoWriter at {clip_path}")

        renderer = _RENDERERS[scene_type]

        try:
            for i in range(total_frames):
                # Build kwargs for this frame
                frame_kwargs = dict(kwargs)
                frame_kwargs["resolution"] = resolution
                frame_kwargs["seed"] = seed + i
                frame_kwargs["timestamp"] = f"2026-02-20 00:00:{i:02d}"

                # If no targets provided, generate demo data
                if not _has_target_kwargs(scene_type, frame_kwargs):
                    demo = _make_demo_targets(scene_type, i, total_frames, seed)
                    frame_kwargs.update(demo)

                frame = renderer(**frame_kwargs)
                writer.write(frame)

                if save_frames:
                    cv2.imwrite(str(frames_dir / f"frame_{i:04d}.png"), frame)
        finally:
            writer.release()

        # Write metadata
        metadata = {
            "scene_type": scene_type,
            "duration": duration,
            "fps": fps,
            "resolution": list(resolution),
            "total_frames": total_frames,
            "seed": seed,
            "created": datetime.now().isoformat(),
            "clip_file": "clip.mp4",
            "has_frames": save_frames,
        }
        with open(clip_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        return clip_dir

    def list_clips(self, scene_type: str | None = None) -> list[dict]:
        """List available clips with metadata.

        Args:
            scene_type: Filter by scene type. None = all.

        Returns:
            List of metadata dicts, each with an added "path" field.
        """
        results = []
        if not self._library_path.exists():
            return results

        scene_dirs = [scene_type] if scene_type else SCENE_TYPES
        for st in scene_dirs:
            st_dir = self._library_path / st
            if not st_dir.exists():
                continue
            for clip_dir in sorted(st_dir.iterdir()):
                meta_path = clip_dir / "metadata.json"
                if meta_path.exists():
                    with open(meta_path) as f:
                        meta = json.load(f)
                    meta["path"] = str(clip_dir)
                    meta["clip_id"] = f"{st}/{clip_dir.name}"
                    results.append(meta)

        return results

    def get_clip_path(self, clip_id: str) -> Path:
        """Get path to a specific clip's MP4 file.

        Args:
            clip_id: Clip identifier in format "scene_type/timestamp".

        Returns:
            Path to the clip.mp4 file.

        Raises:
            FileNotFoundError: If clip does not exist.
        """
        clip_dir = self._library_path / clip_id
        clip_file = clip_dir / "clip.mp4"
        if not clip_file.exists():
            raise FileNotFoundError(f"Clip not found: {clip_file}")
        return clip_file

    def get_frame_sequence(
        self,
        scene_type: str,
        duration: float = 5.0,
        fps: int = 10,
        resolution: tuple[int, int] = (640, 480),
        seed: int | None = None,
        **kwargs: Any,
    ) -> Generator[np.ndarray, None, None]:
        """Yield frames as numpy arrays (for MJPEG streaming).

        Does not write to disk. Generates frames on-the-fly.

        Args:
            scene_type: Scene type to render.
            duration: Total duration in seconds.
            fps: Frames per second (determines total frame count).
            resolution: (width, height).
            seed: Random seed.
            **kwargs: Additional renderer arguments.

        Yields:
            BGR uint8 numpy arrays of shape (height, width, 3).
        """
        if scene_type not in SCENE_TYPES:
            raise ValueError(
                f"Invalid scene_type '{scene_type}'. Must be one of {SCENE_TYPES}"
            )
        if duration <= 0:
            raise ValueError(f"Duration must be positive, got {duration}")
        if fps <= 0:
            raise ValueError(f"FPS must be positive, got {fps}")

        total_frames = max(1, int(duration * fps))
        if seed is None:
            seed = int(time.time() * 1000) % (2**31)

        renderer = _RENDERERS[scene_type]

        for i in range(total_frames):
            frame_kwargs = dict(kwargs)
            frame_kwargs["resolution"] = resolution
            frame_kwargs["seed"] = seed + i
            frame_kwargs["timestamp"] = f"2026-02-20 00:00:{i % 60:02d}"

            if not _has_target_kwargs(scene_type, frame_kwargs):
                demo = _make_demo_targets(scene_type, i, total_frames, seed)
                frame_kwargs.update(demo)

            yield renderer(**frame_kwargs)


    def generate_cctv_clip(
        self,
        camera_name: str,
        scene_type: str,
        duration: float = 5.0,
        fps: int = 10,
        resolution: tuple[int, int] = (640, 480),
        seed: int = 42,
        time_of_day: str = "night",
    ) -> Path:
        """Generate a CCTV video clip with individual JPEG frames.

        Creates an MP4 clip and individual JPEG frames in a camera-named
        directory. Includes subtle motion (camera vibration, moving figures).

        Args:
            camera_name: Camera identifier (e.g. "CAM-01").
            scene_type: CCTV scene type (front_door, back_yard, street_view, parking, driveway).
            duration: Clip duration in seconds.
            fps: Frames per second.
            resolution: (width, height).
            seed: Random seed for deterministic output.
            time_of_day: "day", "dusk", or "night".

        Returns:
            Path to the clip directory containing clip.mp4, frame_*.jpg, metadata.json.

        Raises:
            ValueError: If scene_type is invalid.
        """
        if scene_type not in CCTV_SCENE_TYPES:
            raise ValueError(
                f"Invalid CCTV scene_type '{scene_type}'. Must be one of {CCTV_SCENE_TYPES}"
            )
        if duration <= 0:
            raise ValueError(f"Duration must be positive, got {duration}")
        if fps <= 0:
            raise ValueError(f"FPS must be positive, got {fps}")

        total_frames = max(1, int(duration * fps))

        # Create clip directory under cameras/{camera_name}
        clip_dir = self._library_path / "cameras" / camera_name
        clip_dir.mkdir(parents=True, exist_ok=True)

        width, height = resolution
        clip_path = clip_dir / "clip.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(clip_path), fourcc, fps, (width, height))

        if not writer.isOpened():
            raise RuntimeError(f"Failed to open VideoWriter at {clip_path}")

        try:
            for i in range(total_frames):
                ts = f"2026-02-22 03:{(i // 60) % 60:02d}:{i % 60:02d}"
                frame = render_cctv_frame(
                    camera_name=camera_name,
                    scene_type=scene_type,
                    time_of_day=time_of_day,
                    resolution=resolution,
                    timestamp=ts,
                    seed=seed + i,
                    frame_number=i,
                )
                writer.write(frame)
                # Save individual JPEG frames
                cv2.imwrite(
                    str(clip_dir / f"frame_{i:03d}.jpg"),
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 80],
                )
        finally:
            writer.release()

        # Write metadata
        metadata = {
            "camera_name": camera_name,
            "scene_type": scene_type,
            "time_of_day": time_of_day,
            "duration": duration,
            "fps": fps,
            "resolution": list(resolution),
            "total_frames": total_frames,
            "seed": seed,
            "created": datetime.now().isoformat(),
            "clip_file": "clip.mp4",
        }
        with open(clip_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        return clip_dir


def _has_target_kwargs(scene_type: str, kwargs: dict) -> bool:
    """Check if the kwargs contain target data for the given scene type."""
    if scene_type == "bird_eye":
        return "targets" in kwargs and kwargs["targets"]
    elif scene_type == "street_cam":
        return "targets" in kwargs and kwargs["targets"]
    elif scene_type == "battle":
        return ("friendlies" in kwargs and kwargs["friendlies"]) or \
               ("hostiles" in kwargs and kwargs["hostiles"])
    elif scene_type == "neighborhood":
        return "ambient_targets" in kwargs and kwargs["ambient_targets"]
    return False
