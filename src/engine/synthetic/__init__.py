# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""engine.synthetic — Procedural synthetic video generation for testing.

Generates tactical surveillance footage using OpenCV + numpy.  No PyTorch,
no YOLO, no GPU dependencies.  Designed to run on any platform including
aarch64 where standard PyTorch does not work.

Scene types:
  - bird_eye: Top-down tactical map view
  - street_cam: Simulated street-level security camera
  - battle: Active combat with projectiles and explosions
  - neighborhood: Quiet ambient neighborhood scene

Usage::

    from engine.synthetic.video_gen import render_bird_eye
    from engine.synthetic.video_library import SyntheticVideoLibrary

    # Single frame
    frame = render_bird_eye(targets)

    # Full clip
    lib = SyntheticVideoLibrary()
    path = lib.generate_clip("bird_eye", duration=5.0, fps=10)
"""

from engine.synthetic.video_gen import (
    render_battle_scene,
    render_bird_eye,
    render_neighborhood,
    render_street_cam,
)
from engine.synthetic.video_library import SyntheticVideoLibrary

__all__ = [
    "render_bird_eye",
    "render_street_cam",
    "render_battle_scene",
    "render_neighborhood",
    "SyntheticVideoLibrary",
]
