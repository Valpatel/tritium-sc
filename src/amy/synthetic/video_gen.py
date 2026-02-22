"""Synthetic video frame generators for tactical surveillance footage.

Each function takes target data (SimulationTarget-like dicts or objects) and
returns a single BGR uint8 numpy frame.  All generators are deterministic
given the same random seed.

Color conventions (BGR):
  - FRIENDLY_GREEN: (161, 255, 5)
  - HOSTILE_RED: (109, 42, 255)
  - UNKNOWN_YELLOW: (10, 238, 252)
  - NEUTRAL_BLUE: (255, 160, 0)
  - CYAN: (255, 240, 0)
  - DARK_BG: (15, 10, 10)  -- #0a0a0f

Shape conventions (unit types):
  - rover: square
  - drone: diamond
  - turret: triangle
  - hostile person: circle
  - friendly/neutral person: small circle
  - vehicle: rectangle (wider than square)
  - animal: small diamond
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

# -- BGR color constants ---------------------------------------------------

FRIENDLY_GREEN = (161, 255, 5)
HOSTILE_RED = (109, 42, 255)
UNKNOWN_YELLOW = (10, 238, 252)
NEUTRAL_BLUE = (255, 160, 0)
CYAN = (255, 240, 0)
DARK_BG = (15, 10, 10)  # #0a0a0f

_ALLIANCE_COLORS: dict[str, tuple[int, int, int]] = {
    "friendly": FRIENDLY_GREEN,
    "hostile": HOSTILE_RED,
    "neutral": NEUTRAL_BLUE,
    "unknown": UNKNOWN_YELLOW,
}

# Projectile/explosion colors (BGR)
MUZZLE_FLASH = (130, 245, 255)  # bright yellow-white
PROJECTILE_COLOR = (100, 220, 255)  # orange-yellow
EXPLOSION_ORANGE = (50, 130, 255)
EXPLOSION_YELLOW = (70, 230, 255)


# -- Helper: extract position from target ----------------------------------

def _get_pos(target: Any) -> tuple[float, float]:
    """Extract (x, y) from a target dict or object."""
    if isinstance(target, dict):
        pos = target.get("position", target)
        if isinstance(pos, dict):
            return (float(pos.get("x", 0)), float(pos.get("y", 0)))
        if isinstance(pos, (list, tuple)) and len(pos) >= 2:
            return (float(pos[0]), float(pos[1]))
        return (float(target.get("x", 0)), float(target.get("y", 0)))
    # Object with .position attribute (SimulationTarget)
    if hasattr(target, "position"):
        pos = target.position
        if isinstance(pos, (list, tuple)):
            return (float(pos[0]), float(pos[1]))
        if isinstance(pos, dict):
            return (float(pos.get("x", 0)), float(pos.get("y", 0)))
    return (0.0, 0.0)


def _get_attr(target: Any, key: str, default: Any = None) -> Any:
    """Get attribute from dict or object."""
    if isinstance(target, dict):
        return target.get(key, default)
    return getattr(target, key, default)


# -- World-to-pixel transform ---------------------------------------------

def _world_to_pixel(
    wx: float,
    wy: float,
    width: int,
    height: int,
    view_center: tuple[float, float] = (0.0, 0.0),
    view_radius: float = 35.0,
) -> tuple[int, int]:
    """Convert world coordinates to pixel coordinates."""
    cx, cy = view_center
    scale = min(width, height) / (2.0 * view_radius)
    px = int(width / 2 + (wx - cx) * scale)
    py = int(height / 2 - (wy - cy) * scale)  # Y inverted
    return px, py


# -- Shape drawing ---------------------------------------------------------

def _draw_unit(
    frame: np.ndarray,
    px: int,
    py: int,
    asset_type: str,
    color: tuple[int, int, int],
    size: int = 8,
    heading: float = 0.0,
) -> None:
    """Draw a unit shape at pixel coordinates based on asset_type."""
    if asset_type == "rover":
        # Square
        cv2.rectangle(
            frame, (px - size, py - size), (px + size, py + size), color, -1,
        )
        cv2.rectangle(
            frame, (px - size, py - size), (px + size, py + size), (255, 255, 255), 1,
        )
    elif asset_type == "drone":
        # Diamond
        pts = np.array([
            [px, py - size],
            [px + size, py],
            [px, py + size],
            [px - size, py],
        ], dtype=np.int32)
        cv2.fillPoly(frame, [pts], color)
        cv2.polylines(frame, [pts], True, (255, 255, 255), 1)
    elif asset_type == "turret":
        # Triangle pointing in heading direction
        rad = math.radians(heading)
        tip_x = int(px + size * math.sin(rad))
        tip_y = int(py - size * math.cos(rad))
        left_x = int(px - size * math.cos(rad) * 0.7 - size * math.sin(rad) * 0.3)
        left_y = int(py - size * math.sin(rad) * 0.7 + size * math.cos(rad) * 0.3)
        right_x = int(px + size * math.cos(rad) * 0.7 - size * math.sin(rad) * 0.3)
        right_y = int(py + size * math.sin(rad) * 0.7 + size * math.cos(rad) * 0.3)
        pts = np.array([[tip_x, tip_y], [left_x, left_y], [right_x, right_y]], dtype=np.int32)
        cv2.fillPoly(frame, [pts], color)
        cv2.polylines(frame, [pts], True, (255, 255, 255), 1)
    elif asset_type == "vehicle":
        # Wide rectangle
        cv2.rectangle(
            frame, (px - size - 4, py - size + 2), (px + size + 4, py + size - 2), color, -1,
        )
        cv2.rectangle(
            frame, (px - size - 4, py - size + 2), (px + size + 4, py + size - 2), (255, 255, 255), 1,
        )
    elif asset_type == "animal":
        # Small diamond
        s = max(3, size // 2)
        pts = np.array([
            [px, py - s],
            [px + s, py],
            [px, py + s],
            [px - s, py],
        ], dtype=np.int32)
        cv2.fillPoly(frame, [pts], color)
    else:
        # Person / default: circle
        # Hostiles get bigger circle
        radius = size if _get_attr(None, "alliance", "") == "hostile" else max(4, size - 2)
        cv2.circle(frame, (px, py), radius, color, -1)
        cv2.circle(frame, (px, py), radius, (255, 255, 255), 1)


def _draw_heading_indicator(
    frame: np.ndarray,
    px: int,
    py: int,
    heading: float,
    color: tuple[int, int, int],
    length: int = 12,
) -> None:
    """Draw a heading line from unit center."""
    rad = math.radians(heading)
    ex = int(px + length * math.sin(rad))
    ey = int(py - length * math.cos(rad))
    cv2.line(frame, (px, py), (ex, ey), color, 1, cv2.LINE_AA)


def _draw_health_bar(
    frame: np.ndarray,
    px: int,
    py: int,
    health: float,
    max_health: float,
    size: int = 8,
) -> None:
    """Draw a small health bar above a unit."""
    if max_health <= 0:
        return
    ratio = max(0.0, min(1.0, health / max_health))
    bar_w = size * 2 + 4
    bar_h = 3
    bar_x = px - bar_w // 2
    bar_y = py - size - 8

    # Background
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (40, 40, 40), -1)
    # Fill
    fill_w = int(bar_w * ratio)
    if fill_w > 0:
        if ratio > 0.5:
            bar_color = (80, 220, 80)
        elif ratio > 0.25:
            bar_color = (40, 200, 230)
        else:
            bar_color = (60, 60, 230)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), bar_color, -1)


# -- Grid overlay ----------------------------------------------------------

def _draw_grid(
    frame: np.ndarray,
    width: int,
    height: int,
    view_center: tuple[float, float] = (0.0, 0.0),
    view_radius: float = 35.0,
    spacing: int = 5,
    color: tuple[int, int, int] = (20, 20, 20),
) -> None:
    """Draw grid lines at world-unit intervals."""
    for g in range(-50, 51, spacing):
        px, _ = _world_to_pixel(g, 0, width, height, view_center, view_radius)
        if 0 <= px < width:
            cv2.line(frame, (px, 0), (px, height), color, 1)
        _, py = _world_to_pixel(0, g, width, height, view_center, view_radius)
        if 0 <= py < height:
            cv2.line(frame, (0, py), (width, py), color, 1)


# -- Zone drawing ----------------------------------------------------------

@dataclass
class ZoneRect:
    """A zone boundary for rendering."""
    name: str
    x: float
    y: float
    w: float
    h: float
    color: tuple[int, int, int] = (80, 80, 40)


def _draw_zones(
    frame: np.ndarray,
    zones: list[ZoneRect | dict],
    width: int,
    height: int,
    view_center: tuple[float, float] = (0.0, 0.0),
    view_radius: float = 35.0,
) -> None:
    """Draw zone boundaries."""
    for z in zones:
        if isinstance(z, dict):
            zx = z.get("x", 0)
            zy = z.get("y", 0)
            zw = z.get("w", 10)
            zh = z.get("h", 10)
            name = z.get("name", "")
            color = z.get("color", (80, 80, 40))
        else:
            zx, zy, zw, zh = z.x, z.y, z.w, z.h
            name = z.name
            color = z.color

        p1 = _world_to_pixel(zx - zw / 2, zy + zh / 2, width, height, view_center, view_radius)
        p2 = _world_to_pixel(zx + zw / 2, zy - zh / 2, width, height, view_center, view_radius)
        cv2.rectangle(frame, p1, p2, color, 1)
        if name:
            cv2.putText(
                frame, name, (p1[0] + 2, p1[1] + 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1,
            )


# ==========================================================================
# Scene generators
# ==========================================================================

def render_bird_eye(
    targets: list[Any] | None = None,
    zones: list[Any] | None = None,
    resolution: tuple[int, int] = (640, 480),
    view_center: tuple[float, float] = (0.0, 0.0),
    view_radius: float = 35.0,
    timestamp: str | None = None,
    seed: int | None = None,
) -> np.ndarray:
    """Render a top-down tactical map view.

    Args:
        targets: List of SimulationTarget objects or dicts with position,
                 alliance, asset_type, heading, etc.
        zones: List of ZoneRect or dicts with zone boundaries.
        resolution: (width, height) of output frame.
        view_center: World coordinates of view center.
        view_radius: World units visible from center to edge.
        timestamp: Override timestamp text. None = current time.
        seed: Random seed for deterministic noise. None = no noise.

    Returns:
        BGR uint8 numpy array of shape (height, width, 3).
    """
    if targets is None:
        targets = []
    if zones is None:
        zones = []

    width, height = resolution
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = DARK_BG

    # Grid
    _draw_grid(frame, width, height, view_center, view_radius)

    # Zones
    if zones:
        _draw_zones(frame, zones, width, height, view_center, view_radius)

    # Targets
    for t in targets:
        x, y = _get_pos(t)
        px, py = _world_to_pixel(x, y, width, height, view_center, view_radius)
        if not (0 <= px < width and 0 <= py < height):
            continue

        alliance = _get_attr(t, "alliance", "unknown")
        asset_type = _get_attr(t, "asset_type", "person")
        heading = float(_get_attr(t, "heading", 0.0))
        color = _ALLIANCE_COLORS.get(alliance, UNKNOWN_YELLOW)

        _draw_unit(frame, px, py, asset_type, color, size=8, heading=heading)
        _draw_heading_indicator(frame, px, py, heading, color, length=12)

        # Label
        label = _get_attr(t, "target_id", "")
        if label:
            label = str(label)[:12]
            cv2.putText(
                frame, label, (px - 8, py - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1,
            )

    # Timestamp overlay
    ts = timestamp or time.strftime("%H:%M:%S")
    count = len(targets)
    cv2.putText(
        frame, f"BIRD-EYE | {ts} | {count} targets",
        (10, height - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1,
    )

    return frame


def render_street_cam(
    targets: list[Any] | None = None,
    time_of_day: str = "night",
    resolution: tuple[int, int] = (640, 480),
    camera_name: str = "CAM-01",
    timestamp: str | None = None,
    seed: int | None = None,
) -> np.ndarray:
    """Render a simulated street-level security camera view.

    Draws a perspective ground plane with distant targets as silhouettes,
    timestamp + camera name overlay, and slight noise grain.

    Args:
        targets: List of target dicts/objects. Position y maps to depth,
                 x maps to horizontal position.
        time_of_day: "night" (dark), "day" (lighter), "dusk" (medium).
        resolution: (width, height) of output frame.
        camera_name: Camera identifier shown in overlay.
        timestamp: Override timestamp. None = current time.
        seed: Random seed for deterministic noise.

    Returns:
        BGR uint8 numpy array.
    """
    if targets is None:
        targets = []

    rng = random.Random(seed) if seed is not None else random.Random()
    width, height = resolution
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # Sky/background based on time of day
    bg_colors = {
        "night": (15, 10, 10),
        "day": (160, 140, 120),
        "dusk": (60, 40, 35),
    }
    bg = bg_colors.get(time_of_day, bg_colors["night"])
    frame[:] = bg

    # Horizon line at 40% from top
    horizon_y = int(height * 0.4)

    # Ground plane (perspective grid)
    ground_color = tuple(min(255, c + 15) for c in bg)
    frame[horizon_y:] = ground_color

    # Perspective grid lines on ground
    vanishing_x = width // 2
    vanishing_y = horizon_y
    line_color = tuple(min(255, c + 10) for c in ground_color)
    for i in range(8):
        frac = (i + 1) / 9.0
        lx = int(vanishing_x - width * frac)
        rx = int(vanishing_x + width * frac)
        cv2.line(frame, (vanishing_x, vanishing_y), (lx, height), line_color, 1)
        cv2.line(frame, (vanishing_x, vanishing_y), (rx, height), line_color, 1)

    # Horizontal depth lines
    for i in range(1, 6):
        y = horizon_y + int((height - horizon_y) * (i / 6.0))
        cv2.line(frame, (0, y), (width, y), line_color, 1)

    # Streetlight glow (one or two)
    if time_of_day in ("night", "dusk"):
        for sx in [width // 4, 3 * width // 4]:
            sy = horizon_y + 20
            # Glow circle
            overlay = frame.copy()
            cv2.circle(overlay, (sx, sy), 40, (60, 70, 80), -1)
            cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
            # Light source
            cv2.circle(frame, (sx, sy - 30), 3, (200, 220, 240), -1)
            # Pole
            cv2.line(frame, (sx, sy - 30), (sx, horizon_y - 5), (80, 80, 80), 2)

    # Draw targets as silhouettes on ground plane
    for t in targets:
        x, y = _get_pos(t)
        alliance = _get_attr(t, "alliance", "unknown")
        asset_type = _get_attr(t, "asset_type", "person")
        color = _ALLIANCE_COLORS.get(alliance, UNKNOWN_YELLOW)

        # Map world Y to depth (further = closer to horizon, smaller)
        # Assume y range roughly -30 to 30
        depth = max(0.0, min(1.0, (y + 30) / 60.0))
        screen_y = int(horizon_y + (1.0 - depth) * (height - horizon_y) * 0.9)
        # Map world X to screen X with perspective compression
        perspective_scale = 0.3 + 0.7 * (1.0 - depth)
        screen_x = int(width / 2 + x * (width / 80.0) * perspective_scale)

        # Size decreases with depth
        size = max(3, int(12 * (1.0 - depth * 0.7)))

        if 0 <= screen_x < width and horizon_y <= screen_y < height:
            # Silhouette: darker version of alliance color
            sil_color = tuple(max(0, c // 2) for c in color)
            _draw_unit(frame, screen_x, screen_y, asset_type, sil_color, size=size)
            # Outline glow in alliance color
            if asset_type in ("rover", "vehicle"):
                cv2.rectangle(
                    frame,
                    (screen_x - size - 1, screen_y - size - 1),
                    (screen_x + size + 1, screen_y + size + 1),
                    color, 1,
                )
            else:
                cv2.circle(frame, (screen_x, screen_y), size + 1, color, 1)

    # Camera noise grain
    if seed is not None:
        np_rng = np.random.RandomState(seed)
    else:
        np_rng = np.random.RandomState()
    noise = np_rng.randint(0, 8, (height, width), dtype=np.uint8)
    noise_3ch = np.stack([noise, noise, noise], axis=-1)
    frame = cv2.add(frame, noise_3ch)

    # Timestamp + camera name overlay
    ts = timestamp or time.strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(
        frame, camera_name, (10, 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1,
    )
    cv2.putText(
        frame, ts, (width - 180, 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1,
    )
    # REC indicator
    cv2.circle(frame, (width - 200, 17), 5, (60, 60, 220), -1)
    cv2.putText(
        frame, "REC", (width - 192, 22),
        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (60, 60, 220), 1,
    )

    return frame


@dataclass
class Projectile:
    """A projectile for battle scene rendering."""
    start: tuple[float, float]
    end: tuple[float, float]
    progress: float = 0.5  # 0.0 = at start, 1.0 = at end
    color: tuple[int, int, int] = PROJECTILE_COLOR


@dataclass
class Explosion:
    """An explosion effect for battle scene rendering."""
    x: float
    y: float
    radius: float = 3.0  # world units
    progress: float = 0.5  # 0.0 = just started, 1.0 = fading


def render_battle_scene(
    friendlies: list[Any] | None = None,
    hostiles: list[Any] | None = None,
    projectiles: list[Any] | None = None,
    explosions: list[Any] | None = None,
    resolution: tuple[int, int] = (640, 480),
    view_center: tuple[float, float] = (0.0, 0.0),
    view_radius: float = 35.0,
    timestamp: str | None = None,
    seed: int | None = None,
) -> np.ndarray:
    """Render an active combat scene with muzzle flashes, projectiles, explosions.

    Args:
        friendlies: Friendly unit targets.
        hostiles: Hostile unit targets.
        projectiles: List of Projectile or dicts with start, end, progress.
        explosions: List of Explosion or dicts with x, y, radius, progress.
        resolution: (width, height) of output frame.
        view_center: World coordinates of view center.
        view_radius: World units visible from center to edge.
        timestamp: Override timestamp. None = current time.
        seed: Random seed for deterministic particles.

    Returns:
        BGR uint8 numpy array.
    """
    if friendlies is None:
        friendlies = []
    if hostiles is None:
        hostiles = []
    if projectiles is None:
        projectiles = []
    if explosions is None:
        explosions = []

    rng = random.Random(seed) if seed is not None else random.Random()

    width, height = resolution
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = DARK_BG

    # Grid (dimmer for battle)
    _draw_grid(frame, width, height, view_center, view_radius, color=(15, 15, 15))

    # Draw friendlies
    for t in friendlies:
        x, y = _get_pos(t)
        px, py = _world_to_pixel(x, y, width, height, view_center, view_radius)
        if not (0 <= px < width and 0 <= py < height):
            continue
        asset_type = _get_attr(t, "asset_type", "rover")
        heading = float(_get_attr(t, "heading", 0.0))
        health = float(_get_attr(t, "health", 100.0))
        max_health = float(_get_attr(t, "max_health", 100.0))

        _draw_unit(frame, px, py, asset_type, FRIENDLY_GREEN, size=8, heading=heading)
        _draw_heading_indicator(frame, px, py, heading, FRIENDLY_GREEN)
        _draw_health_bar(frame, px, py, health, max_health)

    # Draw hostiles
    for t in hostiles:
        x, y = _get_pos(t)
        px, py = _world_to_pixel(x, y, width, height, view_center, view_radius)
        if not (0 <= px < width and 0 <= py < height):
            continue
        asset_type = _get_attr(t, "asset_type", "person")
        heading = float(_get_attr(t, "heading", 0.0))
        health = float(_get_attr(t, "health", 80.0))
        max_health = float(_get_attr(t, "max_health", 80.0))

        _draw_unit(frame, px, py, asset_type, HOSTILE_RED, size=8, heading=heading)
        _draw_heading_indicator(frame, px, py, heading, HOSTILE_RED)
        _draw_health_bar(frame, px, py, health, max_health)

    # Draw projectiles as bright lines with glow
    for p in projectiles:
        if isinstance(p, dict):
            sx, sy = p.get("start", (0, 0))
            ex, ey = p.get("end", (0, 0))
            prog = p.get("progress", 0.5)
            p_color = tuple(p.get("color", PROJECTILE_COLOR))
        else:
            sx, sy = p.start
            ex, ey = p.end
            prog = p.progress
            p_color = p.color

        # Current position along trajectory
        cx = sx + (ex - sx) * prog
        cy = sy + (ey - sy) * prog
        # Trail: from slightly behind to current position
        trail_start = max(0.0, prog - 0.3)
        tsx = sx + (ex - sx) * trail_start
        tsy = sy + (ey - sy) * trail_start

        p1 = _world_to_pixel(tsx, tsy, width, height, view_center, view_radius)
        p2 = _world_to_pixel(cx, cy, width, height, view_center, view_radius)

        # Glow line (wider, dimmer)
        glow_color = tuple(max(0, c // 2) for c in p_color)
        cv2.line(frame, p1, p2, glow_color, 3, cv2.LINE_AA)
        # Bright core
        cv2.line(frame, p1, p2, p_color, 1, cv2.LINE_AA)
        # Bright tip
        cv2.circle(frame, p2, 2, (255, 255, 255), -1)

        # Muzzle flash at source (if projectile just fired)
        if prog < 0.2:
            sp = _world_to_pixel(sx, sy, width, height, view_center, view_radius)
            cv2.circle(frame, sp, 6, MUZZLE_FLASH, -1)

    # Draw explosions
    for e in explosions:
        if isinstance(e, dict):
            ex_x, ex_y = e.get("x", 0), e.get("y", 0)
            radius = e.get("radius", 3.0)
            prog = e.get("progress", 0.5)
        else:
            ex_x, ex_y = e.x, e.y
            radius = e.radius
            prog = e.progress

        ep = _world_to_pixel(ex_x, ex_y, width, height, view_center, view_radius)
        scale = min(width, height) / (2.0 * view_radius)
        pixel_radius = int(radius * scale * prog)

        if pixel_radius > 0:
            # Expanding ring
            alpha = max(0.0, 1.0 - prog)
            ring_color = tuple(int(c * alpha) for c in EXPLOSION_ORANGE)
            cv2.circle(frame, ep, pixel_radius, ring_color, 2)

            # Inner fill (fading)
            fill_color = tuple(int(c * alpha * 0.5) for c in EXPLOSION_YELLOW)
            if alpha > 0.3:
                overlay = frame.copy()
                cv2.circle(overlay, ep, max(1, pixel_radius // 2), fill_color, -1)
                cv2.addWeighted(overlay, alpha * 0.4, frame, 1.0 - alpha * 0.4, 0, frame)

            # Particles
            n_particles = max(1, int(8 * (1.0 - prog)))
            for _ in range(n_particles):
                angle = rng.uniform(0, 2 * math.pi)
                dist = rng.uniform(0.5, 1.0) * pixel_radius
                ppx = int(ep[0] + dist * math.cos(angle))
                ppy = int(ep[1] + dist * math.sin(angle))
                if 0 <= ppx < width and 0 <= ppy < height:
                    pc = EXPLOSION_ORANGE if rng.random() > 0.5 else EXPLOSION_YELLOW
                    cv2.circle(frame, (ppx, ppy), rng.randint(1, 2), pc, -1)

    # HUD overlay
    ts = timestamp or time.strftime("%H:%M:%S")
    cv2.putText(
        frame, f"BATTLE | {ts} | F:{len(friendlies)} H:{len(hostiles)}",
        (10, height - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1,
    )

    return frame


def render_neighborhood(
    ambient_targets: list[Any] | None = None,
    resolution: tuple[int, int] = (640, 480),
    time_of_day: str = "night",
    camera_name: str = "NBHD-01",
    timestamp: str | None = None,
    seed: int | None = None,
) -> np.ndarray:
    """Render a quiet neighborhood scene with ambient activity.

    Night scene with streetlight glow circles, ambient pedestrians, cars,
    dogs/cats. Low activity, calm atmosphere.

    Args:
        ambient_targets: List of neutral/ambient target dicts/objects
                        (pedestrians, cars, animals).
        resolution: (width, height) of output frame.
        time_of_day: "night", "day", "dusk".
        camera_name: Camera name for overlay.
        timestamp: Override timestamp. None = current time.
        seed: Random seed for deterministic scene elements.

    Returns:
        BGR uint8 numpy array.
    """
    if ambient_targets is None:
        ambient_targets = []

    rng = random.Random(seed) if seed is not None else random.Random()
    width, height = resolution
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # Background
    bg_colors = {
        "night": (15, 12, 10),
        "day": (150, 135, 115),
        "dusk": (55, 38, 30),
    }
    bg = bg_colors.get(time_of_day, bg_colors["night"])
    frame[:] = bg

    # Horizon
    horizon_y = int(height * 0.35)

    # Sky gradient (slightly lighter at horizon)
    for y in range(horizon_y):
        t = y / max(1, horizon_y)
        sky_color = tuple(int(bg[i] * (0.6 + 0.4 * t)) for i in range(3))
        frame[y, :] = sky_color

    # Ground
    ground_base = tuple(min(255, c + 10) for c in bg)
    frame[horizon_y:] = ground_base

    # Road (darker stripe)
    road_y1 = int(height * 0.7)
    road_y2 = int(height * 0.85)
    road_color = tuple(max(0, c - 5) for c in bg)
    frame[road_y1:road_y2] = road_color
    # Road lines (dashed)
    road_mid = (road_y1 + road_y2) // 2
    for dx in range(0, width, 30):
        cv2.line(frame, (dx, road_mid), (dx + 15, road_mid), (50, 50, 50), 1)

    # Buildings silhouette on horizon
    bx = 0
    while bx < width:
        bw = rng.randint(30, 80)
        bh = rng.randint(20, 60)
        by = horizon_y - bh
        building_color = tuple(max(0, c - 3) for c in bg)
        cv2.rectangle(frame, (bx, by), (bx + bw, horizon_y), building_color, -1)
        # Windows (random lit squares)
        for wy in range(by + 5, horizon_y - 5, 8):
            for wx in range(bx + 5, bx + bw - 5, 8):
                if rng.random() < 0.3:
                    window_color = (60, 80, 100) if time_of_day == "night" else (120, 140, 160)
                    cv2.rectangle(frame, (wx, wy), (wx + 4, wy + 4), window_color, -1)
        bx += bw + rng.randint(5, 20)

    # Streetlights
    if time_of_day in ("night", "dusk"):
        for sx in range(width // 6, width, width // 3):
            sy = road_y1 - 5
            # Glow
            overlay = frame.copy()
            glow_radius = 50 if time_of_day == "night" else 30
            cv2.circle(overlay, (sx, sy), glow_radius, (50, 60, 70), -1)
            cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)
            # Lamp
            cv2.circle(frame, (sx, sy - 40), 3, (180, 200, 220), -1)
            # Pole
            cv2.line(frame, (sx, sy - 40), (sx, road_y1), (70, 70, 70), 2)

    # Draw ambient targets
    for t in ambient_targets:
        x, y_pos = _get_pos(t)
        asset_type = _get_attr(t, "asset_type", "person")
        alliance = _get_attr(t, "alliance", "neutral")
        color = _ALLIANCE_COLORS.get(alliance, NEUTRAL_BLUE)

        # Map to screen: x -> horizontal, y -> depth on ground
        depth = max(0.0, min(1.0, (y_pos + 30) / 60.0))
        screen_y = int(horizon_y + (1.0 - depth) * (height - horizon_y) * 0.85)
        perspective_scale = 0.3 + 0.7 * (1.0 - depth)
        screen_x = int(width / 2 + x * (width / 80.0) * perspective_scale)

        size = max(3, int(10 * (1.0 - depth * 0.6)))

        if 0 <= screen_x < width and horizon_y <= screen_y < height:
            # Muted colors for ambient scene
            muted = tuple(max(0, c // 3 + 30) for c in color)
            _draw_unit(frame, screen_x, screen_y, asset_type, muted, size=size)

    # Noise grain
    if seed is not None:
        np_rng = np.random.RandomState(seed)
    else:
        np_rng = np.random.RandomState()
    noise = np_rng.randint(0, 5, (height, width), dtype=np.uint8)
    noise_3ch = np.stack([noise, noise, noise], axis=-1)
    frame = cv2.add(frame, noise_3ch)

    # Overlay
    ts = timestamp or time.strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(
        frame, camera_name, (10, 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1,
    )
    cv2.putText(
        frame, ts, (width - 180, 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1,
    )
    # Ambient count
    cv2.putText(
        frame, f"{len(ambient_targets)} ambient",
        (10, height - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (120, 120, 120), 1,
    )

    return frame
