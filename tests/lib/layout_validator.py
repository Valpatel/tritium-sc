# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BoundingBoxValidator -- reusable spatial validation for Playwright pages.

Wraps a Playwright sync_api page object and provides:
  - bounding box queries (position, z-index)
  - spatial assertions (no-overlap, z-ordering, viewport containment)
  - drag/resize verification
  - clustering measurement for crowding detection

Usage:
    from tests.lib.layout_validator import BoundingBoxValidator
    v = BoundingBoxValidator(page)
    v.assert_no_overlap('#panel-a', '#panel-b')
"""

from __future__ import annotations

import math
from typing import Any

import pytest


class BoundingBoxValidator:
    """Spatial validation helper wrapping a Playwright page object."""

    def __init__(self, page: Any):
        self.page = page

    # ------------------------------------------------------------------
    # Core spatial queries
    # ------------------------------------------------------------------

    def get_bbox(self, selector: str) -> dict:
        """Return {x, y, width, height} for the first matching element.

        Raises AssertionError if the element is not found or not visible.
        """
        loc = self.page.locator(selector).first
        box = loc.bounding_box()
        assert box is not None, f"Element '{selector}' has no bounding box (not visible?)"
        return box

    def get_computed_z_index(self, selector: str) -> int:
        """Read getComputedStyle(el).zIndex for the first matching element.

        Returns 0 when the computed value is 'auto'.
        """
        raw = self.page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                const z = window.getComputedStyle(el).zIndex;
                return z === 'auto' ? 0 : parseInt(z, 10);
            }""",
            selector,
        )
        assert raw is not None, f"Element '{selector}' not found in DOM"
        return int(raw)

    # ------------------------------------------------------------------
    # Overlap detection
    # ------------------------------------------------------------------

    @staticmethod
    def boxes_overlap(a: dict, b: dict) -> bool:
        """Return True if two {x, y, width, height} rects intersect."""
        a_right = a["x"] + a["width"]
        a_bottom = a["y"] + a["height"]
        b_right = b["x"] + b["width"]
        b_bottom = b["y"] + b["height"]
        if a["x"] >= b_right or b["x"] >= a_right:
            return False
        if a["y"] >= b_bottom or b["y"] >= a_bottom:
            return False
        return True

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    def assert_no_overlap(self, sel_a: str, sel_b: str) -> None:
        """Fail if the bounding boxes of two elements intersect."""
        a = self.get_bbox(sel_a)
        b = self.get_bbox(sel_b)
        assert not self.boxes_overlap(a, b), (
            f"Elements overlap: '{sel_a}' {a} and '{sel_b}' {b}"
        )

    def assert_z_above(self, higher: str, lower: str) -> None:
        """Fail if *higher* does not have a strictly greater z-index than *lower*."""
        z_hi = self.get_computed_z_index(higher)
        z_lo = self.get_computed_z_index(lower)
        assert z_hi > z_lo, (
            f"Expected '{higher}' z-index ({z_hi}) > "
            f"'{lower}' z-index ({z_lo})"
        )

    def assert_within_viewport(self, selector: str) -> None:
        """Fail if the element extends outside the visible viewport."""
        box = self.get_bbox(selector)
        vw, vh = self.page.evaluate("[window.innerWidth, window.innerHeight]")
        assert box["x"] >= 0, (
            f"'{selector}' left edge ({box['x']}) is off-screen"
        )
        assert box["y"] >= 0, (
            f"'{selector}' top edge ({box['y']}) is off-screen"
        )
        assert box["x"] + box["width"] <= vw + 1, (
            f"'{selector}' right edge ({box['x'] + box['width']}) exceeds viewport width ({vw})"
        )
        assert box["y"] + box["height"] <= vh + 1, (
            f"'{selector}' bottom edge ({box['y'] + box['height']}) exceeds viewport height ({vh})"
        )

    def assert_drag_reaches(
        self, selector: str, target_x: float, target_y: float, tolerance: float = 30.0
    ) -> None:
        """Drag an element to (target_x, target_y) and verify it arrived.

        Uses the element's drag handle (or center) as the grab point.
        Tolerance is in pixels.
        """
        box = self.get_bbox(selector)
        # Grab from the center of the panel header (drag handle)
        handle = self.page.locator(f"{selector} [data-drag-handle]")
        if handle.count() > 0:
            hbox = handle.first.bounding_box()
            start_x = hbox["x"] + hbox["width"] / 2
            start_y = hbox["y"] + hbox["height"] / 2
        else:
            start_x = box["x"] + box["width"] / 2
            start_y = box["y"] + box["height"] / 2

        # Calculate delta
        dx = target_x - box["x"]
        dy = target_y - box["y"]

        self.page.mouse.move(start_x, start_y)
        self.page.mouse.down()
        # Move in steps to trigger mousemove handlers
        steps = max(5, int(max(abs(dx), abs(dy)) / 50))
        self.page.mouse.move(start_x + dx, start_y + dy, steps=steps)
        self.page.mouse.up()
        self.page.wait_for_timeout(200)

        after = self.get_bbox(selector)
        dist = math.sqrt((after["x"] - target_x) ** 2 + (after["y"] - target_y) ** 2)
        assert dist <= tolerance, (
            f"Drag '{selector}' to ({target_x}, {target_y}) failed: "
            f"ended at ({after['x']}, {after['y']}), distance {dist:.1f}px > {tolerance}px"
        )

    def assert_resize_independent(
        self, resize_sel: str, observer_sels: list[str], tolerance: float = 3.0
    ) -> None:
        """Resize *resize_sel* and verify *observer_sels* don't move.

        Captures bounding boxes of observers before and after resizing
        the target element by dragging its resize handle 50px.
        """
        # Record observer positions before
        before = {}
        for sel in observer_sels:
            try:
                before[sel] = self.get_bbox(sel)
            except AssertionError:
                continue  # element not visible, skip

        # Find and drag the resize handle
        handle = self.page.locator(f"{resize_sel} [data-resize-handle]")
        if handle.count() == 0:
            pytest.skip(f"No resize handle found for '{resize_sel}'")

        hbox = handle.first.bounding_box()
        cx = hbox["x"] + hbox["width"] / 2
        cy = hbox["y"] + hbox["height"] / 2

        self.page.mouse.move(cx, cy)
        self.page.mouse.down()
        self.page.mouse.move(cx + 50, cy + 50, steps=5)
        self.page.mouse.up()
        self.page.wait_for_timeout(200)

        # Check observer positions after
        moved = []
        for sel, old in before.items():
            try:
                cur = self.get_bbox(sel)
            except AssertionError:
                continue
            dx = abs(cur["x"] - old["x"])
            dy = abs(cur["y"] - old["y"])
            if dx > tolerance or dy > tolerance:
                moved.append(f"'{sel}' shifted by ({dx:.1f}, {dy:.1f})")

        assert len(moved) == 0, (
            f"Resizing '{resize_sel}' moved other elements: {'; '.join(moved)}"
        )

    # ------------------------------------------------------------------
    # Measurement
    # ------------------------------------------------------------------

    @staticmethod
    def measure_clustering(positions: list[dict]) -> dict:
        """Compute spatial statistics for a list of {x, y} positions.

        Returns {centroid_x, centroid_y, std_dev, spread, count}.
        spread = max distance between any two points.
        """
        n = len(positions)
        if n == 0:
            return {"centroid_x": 0, "centroid_y": 0, "std_dev": 0, "spread": 0, "count": 0}

        cx = sum(p["x"] for p in positions) / n
        cy = sum(p["y"] for p in positions) / n

        variance = sum((p["x"] - cx) ** 2 + (p["y"] - cy) ** 2 for p in positions) / n
        std_dev = math.sqrt(variance)

        spread = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                d = math.sqrt(
                    (positions[i]["x"] - positions[j]["x"]) ** 2
                    + (positions[i]["y"] - positions[j]["y"]) ** 2
                )
                spread = max(spread, d)

        return {
            "centroid_x": cx,
            "centroid_y": cy,
            "std_dev": std_dev,
            "spread": spread,
            "count": n,
        }

    def count_elements_in_region(
        self, x: float, y: float, w: float, h: float, selector: str = "*"
    ) -> int:
        """Count visible elements matching *selector* that overlap the given region."""
        region = {"x": x, "y": y, "width": w, "height": h}
        count = 0
        elements = self.page.locator(selector)
        total = elements.count()
        for i in range(total):
            el = elements.nth(i)
            if not el.is_visible():
                continue
            box = el.bounding_box()
            if box and self.boxes_overlap(box, region):
                count += 1
        return count

    def get_visible_element_positions(self, selector: str) -> list[dict]:
        """Return list of {x, y, width, height} for all visible elements matching selector."""
        result = []
        elements = self.page.locator(selector)
        total = elements.count()
        for i in range(total):
            el = elements.nth(i)
            if not el.is_visible():
                continue
            box = el.bounding_box()
            if box:
                result.append(box)
        return result
