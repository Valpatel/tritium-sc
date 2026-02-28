#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CLI tool for generating synthetic video clips.

Usage:
    python scripts/gen_synthetic_video.py --scene bird_eye --count 5 --duration 5 --fps 10
    python scripts/gen_synthetic_video.py --scene battle --count 3
    python scripts/gen_synthetic_video.py --all --count 2
    python scripts/gen_synthetic_video.py --list
    python scripts/gen_synthetic_video.py --scene bird_eye --save-frames
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

from engine.synthetic.video_library import SCENE_TYPES, SyntheticVideoLibrary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic surveillance video clips for TRITIUM-SC",
    )
    parser.add_argument(
        "--scene",
        choices=SCENE_TYPES,
        help="Scene type to generate",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate clips for all scene types",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of clips to generate per scene type (default: 1)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="Clip duration in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=10,
        help="Frames per second (default: 10)",
    )
    parser.add_argument(
        "--resolution",
        type=str,
        default="640x480",
        help="Resolution as WxH (default: 640x480)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for deterministic generation",
    )
    parser.add_argument(
        "--save-frames",
        action="store_true",
        help="Also save individual PNG frames",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/synthetic/video",
        help="Output library path (default: data/synthetic/video)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_clips",
        help="List existing clips in the library",
    )

    args = parser.parse_args()

    lib = SyntheticVideoLibrary(args.output)

    if args.list_clips:
        _list_clips(lib)
        return

    if not args.scene and not args.all:
        parser.error("Either --scene or --all is required (or use --list)")

    # Parse resolution
    try:
        w, h = args.resolution.split("x")
        resolution = (int(w), int(h))
    except ValueError:
        parser.error(f"Invalid resolution format: {args.resolution}. Use WxH (e.g. 640x480)")
        return

    scenes = list(SCENE_TYPES) if args.all else [args.scene]

    total = len(scenes) * args.count
    generated = 0
    print(f"Generating {total} clip(s)...")
    print(f"  Scenes: {', '.join(scenes)}")
    print(f"  Duration: {args.duration}s @ {args.fps} FPS")
    print(f"  Resolution: {resolution[0]}x{resolution[1]}")
    print(f"  Output: {args.output}")
    print()

    for scene in scenes:
        for i in range(args.count):
            seed = args.seed
            if seed is not None and args.count > 1:
                seed = seed + i * 1000

            t0 = time.time()
            try:
                clip_dir = lib.generate_clip(
                    scene_type=scene,
                    duration=args.duration,
                    fps=args.fps,
                    resolution=resolution,
                    seed=seed,
                    save_frames=args.save_frames,
                )
                elapsed = time.time() - t0
                generated += 1
                print(f"  [{generated}/{total}] {scene} clip {i+1}/{args.count} "
                      f"-> {clip_dir} ({elapsed:.1f}s)")
            except Exception as e:
                print(f"  ERROR generating {scene} clip {i+1}: {e}", file=sys.stderr)

    print(f"\nDone. Generated {generated}/{total} clips.")


def _list_clips(lib: SyntheticVideoLibrary) -> None:
    """Print library contents."""
    clips = lib.list_clips()
    if not clips:
        print("No clips in library.")
        print(f"Library path: {lib.library_path}")
        return

    print(f"Synthetic Video Library: {lib.library_path}")
    print(f"Total clips: {len(clips)}")
    print()

    by_scene: dict[str, list[dict]] = {}
    for c in clips:
        st = c.get("scene_type", "unknown")
        by_scene.setdefault(st, []).append(c)

    for scene, scene_clips in sorted(by_scene.items()):
        print(f"  {scene}: {len(scene_clips)} clip(s)")
        for c in scene_clips:
            dur = c.get("duration", "?")
            fps = c.get("fps", "?")
            res = c.get("resolution", [0, 0])
            created = c.get("created", "?")
            frames = c.get("total_frames", "?")
            print(f"    - {c.get('clip_id', '?')}: "
                  f"{dur}s @ {fps}fps, {res[0]}x{res[1]}, "
                  f"{frames} frames, created {created}")


if __name__ == "__main__":
    main()
