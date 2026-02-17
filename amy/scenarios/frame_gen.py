"""FrameGenerator — produces synthetic BGR frames from world state.

When pre-generated images are available (from ``pregen.py``), renders
realistic CCTV backgrounds with person sprites composited via alpha
blending.  Falls back to geometric silhouettes when cache is empty.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


_CACHE_DIR = Path(__file__).parent / "cache"


class FrameGenerator:
    """Generate synthetic camera frames from world state."""

    def __init__(self, width: int = 320, height: int = 240) -> None:
        self.width = width
        self.height = height
        self._backgrounds: list[np.ndarray] = []
        self._people_sprites: list[np.ndarray] = []
        self._bg_index: int = 0
        self._load_cache()

    # ------------------------------------------------------------------
    # Cache loading
    # ------------------------------------------------------------------

    def _load_cache(self) -> None:
        """Load pre-generated backgrounds and person sprites from cache."""
        bg_dir = _CACHE_DIR / "backgrounds"
        people_dir = _CACHE_DIR / "people"

        if bg_dir.exists():
            for f in sorted(bg_dir.glob("*.jpg")):
                img = cv2.imread(str(f))
                if img is not None:
                    resized = cv2.resize(
                        img, (self.width, self.height),
                        interpolation=cv2.INTER_AREA,
                    )
                    self._backgrounds.append(resized)

        if people_dir.exists():
            for f in sorted(people_dir.glob("*.png")):
                img = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)  # RGBA
                if img is not None and img.shape[2] == 4:
                    self._people_sprites.append(img)

    @property
    def has_cache(self) -> bool:
        return bool(self._backgrounds) and bool(self._people_sprites)

    # ------------------------------------------------------------------
    # Background
    # ------------------------------------------------------------------

    def generate_background(self) -> np.ndarray:
        """Create a background frame with noise and timestamp.

        Uses pre-generated CCTV backgrounds when available, otherwise
        falls back to a simple dark gray rectangle.
        """
        if self._backgrounds:
            bg = self._backgrounds[self._bg_index % len(self._backgrounds)].copy()
            # Add subtle per-frame noise for CCTV realism
            noise = np.random.normal(0, 4, bg.shape).astype(np.int16)
            bg = np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        else:
            # Fallback: geometric dark room
            bg = np.full(
                (self.height, self.width, 3), (30, 30, 35), dtype=np.uint8,
            )
            noise = np.random.normal(0, 3, bg.shape).astype(np.int16)
            bg = np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)

            # Floor line depth cue
            floor_y = int(self.height * 0.75)
            cv2.line(bg, (0, floor_y), (self.width, floor_y), (45, 45, 50), 1)

        # Timestamp overlay (always present, like a real CCTV feed)
        ts_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(
            bg, ts_text, (4, 14),
            cv2.FONT_HERSHEY_PLAIN, 0.8, (200, 200, 200), 1, cv2.LINE_AA,
        )

        return bg

    # ------------------------------------------------------------------
    # Person rendering — sprite compositing
    # ------------------------------------------------------------------

    def _render_sprite(
        self,
        frame: np.ndarray,
        x: float,
        y: float,
        height_ratio: float,
        person_index: int = 0,
    ) -> None:
        """Composite a pre-generated person sprite onto frame (in-place).

        Parameters
        ----------
        frame : BGR image to draw on.
        x, y : Normalised foot position (0.0-1.0).
        height_ratio : Fraction of frame height the person occupies.
        person_index : Which sprite to use (wraps around).
        """
        sprite = self._people_sprites[person_index % len(self._people_sprites)]
        h, w = frame.shape[:2]

        person_h = int(height_ratio * h)
        if person_h < 8:
            return

        # Scale sprite to desired height, preserving aspect ratio
        sprite_h, sprite_w = sprite.shape[:2]
        scale = person_h / sprite_h
        new_w = max(int(sprite_w * scale), 1)
        new_h = person_h
        resized = cv2.resize(sprite, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Foot position in pixels
        px = int(x * w)
        py = int(y * h)

        # Top-left corner of sprite (centered on px, bottom at py)
        x1 = px - new_w // 2
        y1 = py - new_h

        # Clip to frame bounds
        src_x1 = max(0, -x1)
        src_y1 = max(0, -y1)
        dst_x1 = max(0, x1)
        dst_y1 = max(0, y1)
        dst_x2 = min(w, x1 + new_w)
        dst_y2 = min(h, y1 + new_h)

        draw_w = dst_x2 - dst_x1
        draw_h = dst_y2 - dst_y1
        if draw_w <= 0 or draw_h <= 0:
            return

        sprite_region = resized[src_y1:src_y1 + draw_h, src_x1:src_x1 + draw_w]

        # Alpha blend
        alpha = sprite_region[:, :, 3:4].astype(np.float32) / 255.0
        bgr = sprite_region[:, :, :3].astype(np.float32)
        dst = frame[dst_y1:dst_y2, dst_x1:dst_x2].astype(np.float32)
        frame[dst_y1:dst_y2, dst_x1:dst_x2] = (
            bgr * alpha + dst * (1.0 - alpha)
        ).astype(np.uint8)

    # ------------------------------------------------------------------
    # Person rendering — geometric fallback
    # ------------------------------------------------------------------

    def _render_geometric(
        self,
        frame: np.ndarray,
        x: float,
        y: float,
        height_ratio: float,
        color: tuple[int, int, int],
    ) -> None:
        """Draw a geometric person silhouette onto frame (in-place)."""
        h, w = frame.shape[:2]
        px = int(x * w)
        py = int(y * h)

        person_h = int(height_ratio * h)
        if person_h < 4:
            return

        jitter = np.random.randint(-8, 9, size=3)
        col = tuple(int(np.clip(c + j, 0, 255)) for c, j in zip(color, jitter))

        head_h = max(person_h // 6, 4)
        head_w = max(head_h * 3 // 4, 3)
        torso_h = person_h * 2 // 5
        torso_w = max(person_h // 4, 6)
        leg_h = person_h - head_h - torso_h
        leg_w = max(torso_w // 3, 3)
        leg_gap = max(leg_w // 2, 1)

        top_y = py - person_h

        # Head
        head_cx, head_cy = px, top_y + head_h
        cv2.ellipse(
            frame, (head_cx, head_cy), (head_w, head_h),
            0, 0, 360, col, -1, cv2.LINE_AA,
        )

        # Shoulders
        shoulder_y = top_y + head_h * 2
        torso_x1 = px - torso_w // 2
        torso_x2 = px + torso_w // 2
        cv2.line(
            frame, (head_cx - head_w // 2, head_cy + head_h // 2),
            (torso_x1, shoulder_y), col, max(torso_w // 6, 1), cv2.LINE_AA,
        )
        cv2.line(
            frame, (head_cx + head_w // 2, head_cy + head_h // 2),
            (torso_x2, shoulder_y), col, max(torso_w // 6, 1), cv2.LINE_AA,
        )

        # Torso
        torso_y1 = top_y + head_h * 2
        torso_y2 = torso_y1 + torso_h
        cv2.rectangle(frame, (torso_x1, torso_y1), (torso_x2, torso_y2), col, -1)

        # Legs
        legs_y1 = torso_y2
        legs_y2 = legs_y1 + leg_h
        left_cx = px - leg_gap
        right_cx = px + leg_gap
        cv2.rectangle(
            frame, (left_cx - leg_w // 2, legs_y1),
            (left_cx + leg_w // 2, legs_y2), col, -1,
        )
        cv2.rectangle(
            frame, (right_cx - leg_w // 2, legs_y1),
            (right_cx + leg_w // 2, legs_y2), col, -1,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render_person(
        self,
        frame: np.ndarray,
        x: float,
        y: float,
        height_ratio: float,
        color: tuple[int, int, int],
        person_index: int = 0,
    ) -> None:
        """Draw a person onto *frame* (in-place).

        Uses pre-generated sprites when available, otherwise falls back
        to geometric silhouettes.
        """
        if self._people_sprites:
            self._render_sprite(frame, x, y, height_ratio, person_index)
        else:
            self._render_geometric(frame, x, y, height_ratio, color)

    def generate_frame(self, world_state: dict) -> np.ndarray:
        """Render a BGR frame from current world state.

        Parameters
        ----------
        world_state : dict
            Must contain ``"people"`` — a list of dicts each with:

            - ``position``: :class:`Position2D` (x, y in 0-1 range)
            - ``height_ratio``: float (fraction of frame height)
            - ``color``: tuple[int, int, int] (BGR)

        Returns
        -------
        np.ndarray
            BGR uint8 frame of shape ``(height, width, 3)``.
        """
        frame = self.generate_background()

        for i, person in enumerate(world_state.get("people", [])):
            pos = person["position"]
            self.render_person(
                frame,
                x=pos.x,
                y=pos.y,
                height_ratio=person.get("height_ratio", 0.6),
                color=person.get("color", (60, 60, 180)),
                person_index=i,
            )

        return frame
