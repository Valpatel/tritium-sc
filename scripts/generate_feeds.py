#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Generate synthetic CCTV camera feeds — frames and video clips.

Generates 50 still frames and 1 five-second clip per camera for 6 cameras:
  CAM-01 Front Door (front_door, day)
  CAM-02 Back Yard  (back_yard, day)
  CAM-03 Street East (street_view, dusk)
  CAM-04 Street West (street_view, night)
  CAM-05 Driveway   (driveway, day)
  CAM-06 Parking    (parking, night)

Total: ~300 frames + 6 clips.

Usage:
    python scripts/generate_feeds.py [--output DIR] [--parallel]

Options:
    --output DIR   Output directory (default: data/synthetic/cameras)
    --parallel     Attempt to split across GB10 fleet (SSH to gb10-02)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure src/ is on the path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import cv2
from engine.synthetic.video_gen import render_cctv_frame
from engine.synthetic.video_library import SyntheticVideoLibrary

# Camera definitions: (name, scene_type, time_of_day)
CAMERAS = [
    ("CAM-01", "front_door", "day"),
    ("CAM-02", "back_yard", "day"),
    ("CAM-03", "street_view", "dusk"),
    ("CAM-04", "street_view", "night"),
    ("CAM-05", "driveway", "day"),
    ("CAM-06", "parking", "night"),
]

FRAMES_PER_CAMERA = 50
CLIP_DURATION = 5.0
CLIP_FPS = 10
SEED_BASE = 20260222


def generate_camera(
    camera_name: str,
    scene_type: str,
    time_of_day: str,
    output_dir: Path,
    n_frames: int = FRAMES_PER_CAMERA,
) -> dict:
    """Generate frames and clip for a single camera.

    Returns metadata dict.
    """
    cam_dir = output_dir / camera_name
    cam_dir.mkdir(parents=True, exist_ok=True)

    seed = SEED_BASE + hash(camera_name) % 10000

    # Generate still frames
    t0 = time.time()
    for i in range(n_frames):
        frame = render_cctv_frame(
            camera_name=camera_name,
            scene_type=scene_type,
            time_of_day=time_of_day,
            seed=seed + i,
            frame_number=i,
        )
        cv2.imwrite(
            str(cam_dir / f"frame_{i:03d}.jpg"),
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, 80],
        )
    frame_time = time.time() - t0

    # Generate video clip
    t1 = time.time()
    lib = SyntheticVideoLibrary(output_dir)
    lib.generate_cctv_clip(
        camera_name=camera_name,
        scene_type=scene_type,
        time_of_day=time_of_day,
        duration=CLIP_DURATION,
        fps=CLIP_FPS,
        seed=seed,
    )
    clip_time = time.time() - t1

    meta = {
        "camera_name": camera_name,
        "scene_type": scene_type,
        "time_of_day": time_of_day,
        "n_frames": n_frames,
        "clip_duration": CLIP_DURATION,
        "clip_fps": CLIP_FPS,
        "seed": seed,
        "frame_gen_time_s": round(frame_time, 2),
        "clip_gen_time_s": round(clip_time, 2),
    }
    return meta


def check_gb10_02() -> bool:
    """Check if GB10-02 is reachable via SSH."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
             "gb10-02", "echo", "ok"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def run_remote_cameras(
    cameras: list[tuple[str, str, str]],
    output_dir: Path,
) -> bool:
    """Run camera generation on GB10-02 via SSH."""
    cam_args = json.dumps(cameras)
    remote_cmd = (
        f"cd ~/Code/tritium-sc && "
        f".venv/bin/python3 -c \""
        f"import sys; sys.path.insert(0, 'src'); "
        f"from scripts.generate_feeds import generate_camera; "
        f"from pathlib import Path; "
        f"import json; "
        f"cams = json.loads('{cam_args}'); "
        f"[generate_camera(c[0], c[1], c[2], Path('{output_dir}')) for c in cams]; "
        f"print('REMOTE_DONE')"
        f"\""
    )
    try:
        result = subprocess.run(
            ["ssh", "gb10-02", remote_cmd],
            capture_output=True, text=True, timeout=300,
        )
        return "REMOTE_DONE" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic CCTV feeds")
    parser.add_argument(
        "--output", type=str, default="data/synthetic/cameras",
        help="Output directory",
    )
    parser.add_argument(
        "--parallel", action="store_true",
        help="Split across GB10 fleet",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_cameras = len(CAMERAS)
    total_frames = total_cameras * FRAMES_PER_CAMERA
    print(f"Generating {total_cameras} cameras x {FRAMES_PER_CAMERA} frames + {total_cameras} clips")
    print(f"Total: {total_frames} frames + {total_cameras} clips")
    print(f"Output: {output_dir.resolve()}")
    print()

    use_remote = False
    if args.parallel:
        print("Checking GB10-02 availability...")
        if check_gb10_02():
            print("  GB10-02 is reachable -- splitting work")
            use_remote = True
        else:
            print("  GB10-02 is not reachable -- running locally")

    if use_remote:
        local_cams = CAMERAS[:3]
        remote_cams = CAMERAS[3:]
        print(f"Local: {[c[0] for c in local_cams]}")
        print(f"Remote: {[c[0] for c in remote_cams]}")
        # Start remote generation
        # (In practice this would use threading; for now sequential)
        for cam_name, scene, tod in local_cams:
            print(f"  [{cam_name}] {scene} ({tod})...", end=" ", flush=True)
            meta = generate_camera(cam_name, scene, tod, output_dir)
            print(f"done ({meta['frame_gen_time_s']}s frames, {meta['clip_gen_time_s']}s clip)")

        ok = run_remote_cameras(remote_cams, output_dir)
        if not ok:
            print("  Remote generation failed -- running remaining locally")
            for cam_name, scene, tod in remote_cams:
                print(f"  [{cam_name}] {scene} ({tod})...", end=" ", flush=True)
                meta = generate_camera(cam_name, scene, tod, output_dir)
                print(f"done ({meta['frame_gen_time_s']}s frames, {meta['clip_gen_time_s']}s clip)")
    else:
        all_meta = []
        for idx, (cam_name, scene, tod) in enumerate(CAMERAS, 1):
            print(f"  [{idx}/{total_cameras}] {cam_name} ({scene}, {tod})...", end=" ", flush=True)
            meta = generate_camera(cam_name, scene, tod, output_dir)
            all_meta.append(meta)
            done_frames = idx * FRAMES_PER_CAMERA
            print(f"done ({meta['frame_gen_time_s']}s frames, {meta['clip_gen_time_s']}s clip) "
                  f"[{done_frames}/{total_frames}]")

        # Write summary
        summary = {
            "cameras": all_meta,
            "total_frames": total_frames,
            "total_clips": total_cameras,
        }
        with open(output_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        print()
        print(f"Summary written to {output_dir / 'summary.json'}")

    print()
    print("Done!")


if __name__ == "__main__":
    main()
