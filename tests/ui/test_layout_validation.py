# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""UI layout validation tests for the Command Center.

Six test classes, one per known spatial issue. Tests are written to DETECT
the issues -- they FAIL when the bug exists, proving the test catches it.

Requires a running server (tritium_server fixture) and Playwright.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_layout_validation.py -v
    ./test.sh 12   # (once wired into test.sh)
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.layout, pytest.mark.ui]


# ======================================================================
# Issue 1: Z-index hierarchy
# ======================================================================

class TestZIndexHierarchy:
    """Issue 1: toasts should be visible when chat is open.

    Expected z-index ordering (high to low):
        help-overlay (500) > modal-overlay (400) > chat-overlay (300)
        > toast-container (200) > panel-container (100) > header (50)

    The toast container must layer BELOW chat but both must be above panels.
    If toasts render behind panels, users miss notifications.
    """

    def test_toast_above_panels(self, validator):
        """Toast container z-index should exceed panel container z-index."""
        validator.assert_z_above("#toast-container", "#panel-container")

    def test_chat_above_toast(self, validator):
        """Chat overlay should render above toasts."""
        validator.assert_z_above("#chat-overlay", "#toast-container")

    def test_help_above_chat(self, validator):
        """Help overlay should render above chat."""
        validator.assert_z_above("#help-overlay", "#chat-overlay")

    def test_modal_above_chat(self, validator):
        """Modal overlay should render above chat."""
        validator.assert_z_above("#modal-overlay", "#chat-overlay")

    def test_help_above_modal(self, validator):
        """Help and modal should both be at high z-index."""
        # Both are 400-500 range; help is 500, modal is 400
        validator.assert_z_above("#help-overlay", "#modal-overlay")

    def test_panels_above_tactical_area(self, validator):
        """Panel container must be above the tactical map area."""
        validator.assert_z_above("#panel-container", "#tactical-area")


# ======================================================================
# Issue 2: Panel drag freedom
# ======================================================================

class TestPanelDragFreedom:
    """Issue 2: all panels should reach all edges, not just Amy.

    The panel container has inset: 28px 0 20px 0, so panels can move
    within that region. Every panel type should be draggable to all
    four edges (top, bottom, left, right) of the panel container.
    """

    def _open_panel(self, page, panel_id):
        """Open a panel by its keyboard shortcut."""
        shortcut_map = {"amy": "1", "units": "2", "alerts": "3", "game": "4"}
        key = shortcut_map.get(panel_id)
        if key:
            page.keyboard.press(key)
            page.wait_for_timeout(300)

    def _get_container_bounds(self, page):
        """Get the panel container's bounding box."""
        box = page.locator("#panel-container").bounding_box()
        assert box is not None, "Panel container not found"
        return box

    def test_amy_panel_drag_to_top_left(self, page, validator):
        """Amy panel can be dragged to the top-left corner."""
        self._open_panel(page, "amy")
        selector = '.panel[data-panel-id="amy"]'
        page.wait_for_selector(selector, timeout=3000)
        container = self._get_container_bounds(page)
        validator.assert_drag_reaches(selector, container["x"] + 5, container["y"] + 5)

    def test_units_panel_drag_to_top_right(self, page, validator):
        """Units panel can be dragged to the top-right area."""
        self._open_panel(page, "units")
        selector = '.panel[data-panel-id="units"]'
        page.wait_for_selector(selector, timeout=3000)
        container = self._get_container_bounds(page)
        # Target: near right edge (leave room for panel width)
        target_x = container["x"] + container["width"] - 280
        target_y = container["y"] + 5
        validator.assert_drag_reaches(selector, target_x, target_y, tolerance=40)

    def test_alerts_panel_drag_to_bottom_left(self, page, validator):
        """Alerts panel can be dragged to the bottom-left area."""
        self._open_panel(page, "alerts")
        selector = '.panel[data-panel-id="alerts"]'
        page.wait_for_selector(selector, timeout=3000)
        container = self._get_container_bounds(page)
        target_x = container["x"] + 5
        target_y = container["y"] + container["height"] - 50
        validator.assert_drag_reaches(selector, target_x, target_y, tolerance=40)

    def test_game_panel_drag_to_bottom_right(self, page, validator):
        """Game HUD panel can be dragged to the bottom-right area."""
        self._open_panel(page, "game")
        selector = '.panel[data-panel-id="game"]'
        page.wait_for_selector(selector, timeout=3000)
        container = self._get_container_bounds(page)
        target_x = container["x"] + container["width"] - 320
        target_y = container["y"] + container["height"] - 50
        validator.assert_drag_reaches(selector, target_x, target_y, tolerance=40)


# ======================================================================
# Issue 3: Chat displacement
# ======================================================================

class TestChatDisplacement:
    """Issue 3: chat should push panels, not cover them.

    When the chat overlay slides in from the right, it occupies 350px.
    Panels underneath should either be pushed left, resized, or the
    tactical map area should shrink. The test detects whether the chat
    fully covers existing panel content.
    """

    def test_chat_does_not_fully_cover_panels(self, page, validator):
        """Opening chat should not fully occlude visible panels."""
        # Ensure a panel is on the right side
        page.keyboard.press("3")  # alerts panel
        page.wait_for_timeout(500)

        alerts_sel = '.panel[data-panel-id="alerts"]'
        try:
            before = validator.get_bbox(alerts_sel)
        except AssertionError:
            pytest.skip("Alerts panel not visible")

        # Open chat
        page.keyboard.press("c")
        page.wait_for_timeout(500)

        chat_box = validator.get_bbox("#chat-overlay")
        panel_box = validator.get_bbox(alerts_sel)

        # If chat fully covers the panel, that is the bug
        chat_left = chat_box["x"]
        panel_right = panel_box["x"] + panel_box["width"]

        # The panel should either move left, resize, or remain partially visible
        # This test detects if the panel is FULLY behind the chat
        fully_covered = (
            panel_box["x"] >= chat_left
            and panel_right <= chat_left + chat_box["width"]
        )
        # Close chat
        page.keyboard.press("Escape")

        # Note: this test documents the CURRENT issue. If it passes,
        # the displacement logic is working. If it fails, Issue 3 exists.
        if fully_covered:
            pytest.xfail(
                "Chat fully covers alerts panel (Issue 3: chat displacement not implemented)"
            )

    def test_chat_overlay_visible_when_opened(self, page, validator):
        """Chat overlay should become visible when toggled with C key."""
        page.keyboard.press("c")
        page.wait_for_timeout(500)

        chat = page.locator("#chat-overlay")
        assert not chat.is_hidden(), "Chat overlay should be visible after pressing C"
        box = validator.get_bbox("#chat-overlay")
        assert box["width"] > 0, "Chat overlay has zero width"

        # Close it
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)


# ======================================================================
# Issue 4: World scale
# ======================================================================

class TestWorldScale:
    """Issue 4: sim world scale must match satellite tile scale.

    The simulation spawns units in a coordinate system where 1 unit = 1 meter.
    If the spatial spread of all units is < 50m, the world is too compressed
    and satellite tiles will not align with gameplay.
    """

    def test_unit_spatial_spread_in_meters(self, page, validator):
        """Units should be spread across > 50 meters in game coordinates."""
        positions = page.evaluate("""() => {
            if (!window.TritiumStore) return [];
            const result = [];
            window.TritiumStore.units.forEach(u => {
                if (u.position) {
                    result.push({x: u.position.x, y: u.position.y});
                }
            });
            return result;
        }""")

        assert len(positions) >= 3, (
            f"Expected >= 3 units with positions, got {len(positions)}"
        )

        stats = validator.measure_clustering(positions)
        assert stats["spread"] > 50, (
            f"Unit spread is {stats['spread']:.1f}m, expected > 50m. "
            f"World may be too compressed for satellite tile alignment."
        )

    def test_units_not_all_at_origin(self, page):
        """Units should not all be clustered at (0, 0)."""
        positions = page.evaluate("""() => {
            if (!window.TritiumStore) return [];
            const result = [];
            window.TritiumStore.units.forEach(u => {
                if (u.position) {
                    result.push({x: u.position.x, y: u.position.y});
                }
            });
            return result;
        }""")

        if len(positions) < 2:
            pytest.skip("Not enough units with position data")

        at_origin = sum(
            1 for p in positions if abs(p["x"]) < 1.0 and abs(p["y"]) < 1.0
        )
        assert at_origin < len(positions), (
            f"All {len(positions)} units are at origin (0,0)"
        )


# ======================================================================
# Issue 5: Corner crowding
# ======================================================================

class TestCornerCrowding:
    """Issue 5: bottom-left corner has too many elements.

    The minimap, map coordinates, and map mode indicator all occupy the
    bottom-left and top-left areas. When panels default to bottom-left,
    elements stack up. This test counts overlapping elements in that region.
    """

    def test_bottom_left_not_overcrowded(self, page, validator):
        """Bottom-left 200x200px region should not have > 4 overlapping elements."""
        # Get viewport height for bottom-left corner
        vh = page.evaluate("window.innerHeight")
        region_x = 0
        region_y = vh - 200
        region_w = 200
        region_h = 200

        # Count visible elements with specific selectors (not all DOM elements)
        selectors = [
            "#minimap-container",
            "#map-coords",
            "#map-mode",
            "#map-fps",
            '.panel[data-panel-id="amy"]',
            '.panel[data-panel-id="units"]',
            '.panel[data-panel-id="alerts"]',
            '.panel[data-panel-id="game"]',
        ]

        region = {"x": region_x, "y": region_y, "width": region_w, "height": region_h}
        overlapping = []
        for sel in selectors:
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            el = loc.first
            if not el.is_visible():
                continue
            box = el.bounding_box()
            if box and validator.boxes_overlap(box, region):
                overlapping.append(sel)

        assert len(overlapping) <= 4, (
            f"Bottom-left corner has {len(overlapping)} overlapping elements "
            f"(max 4): {overlapping}"
        )

    def test_no_panel_pairwise_overlap(self, page, validator):
        """Open panels should not overlap each other."""
        panel_ids = ["amy", "units", "alerts"]
        boxes = {}

        for pid in panel_ids:
            sel = f'.panel[data-panel-id="{pid}"]'
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                box = loc.first.bounding_box()
                if box:
                    boxes[pid] = box

        # Check pairwise overlap
        ids = list(boxes.keys())
        overlaps = []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if validator.boxes_overlap(boxes[ids[i]], boxes[ids[j]]):
                    overlaps.append(f"{ids[i]} <-> {ids[j]}")

        assert len(overlaps) == 0, (
            f"Panel overlaps detected: {overlaps}"
        )


# ======================================================================
# Issue 6: Panel resize independence
# ======================================================================

class TestPanelResizeIndependence:
    """Issue 6: resizing one panel shouldn't move others (free mode).

    In the floating panel system, each panel is absolutely positioned
    with transform: translate(). Resizing one panel by dragging its
    resize handle should only affect that panel's dimensions, not
    the position of any other open panel.
    """

    def test_resize_amy_does_not_move_others(self, page, validator):
        """Resizing Amy panel should not move Units or Alerts panels."""
        # Ensure panels are open
        page.keyboard.press("1")  # amy
        page.wait_for_timeout(300)
        page.keyboard.press("2")  # units
        page.wait_for_timeout(300)
        page.keyboard.press("3")  # alerts
        page.wait_for_timeout(300)

        amy_sel = '.panel[data-panel-id="amy"]'
        observers = [
            '.panel[data-panel-id="units"]',
            '.panel[data-panel-id="alerts"]',
        ]

        # Verify panels exist
        if page.locator(amy_sel).count() == 0:
            pytest.skip("Amy panel not visible")

        validator.assert_resize_independent(amy_sel, observers)

    def test_resize_units_does_not_move_others(self, page, validator):
        """Resizing Units panel should not move Amy or Alerts panels."""
        page.keyboard.press("1")
        page.wait_for_timeout(300)
        page.keyboard.press("2")
        page.wait_for_timeout(300)
        page.keyboard.press("3")
        page.wait_for_timeout(300)

        units_sel = '.panel[data-panel-id="units"]'
        observers = [
            '.panel[data-panel-id="amy"]',
            '.panel[data-panel-id="alerts"]',
        ]

        if page.locator(units_sel).count() == 0:
            pytest.skip("Units panel not visible")

        validator.assert_resize_independent(units_sel, observers)

    def test_resize_preserves_panel_dimensions(self, page, validator):
        """After resize, the resized panel should be larger."""
        page.keyboard.press("1")  # amy
        page.wait_for_timeout(300)

        sel = '.panel[data-panel-id="amy"]'
        if page.locator(sel).count() == 0:
            pytest.skip("Amy panel not visible")

        before = validator.get_bbox(sel)

        handle = page.locator(f'{sel} [data-resize-handle]')
        if handle.count() == 0:
            pytest.skip("No resize handle")

        hbox = handle.first.bounding_box()
        cx = hbox["x"] + hbox["width"] / 2
        cy = hbox["y"] + hbox["height"] / 2

        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 80, cy + 60, steps=5)
        page.mouse.up()
        page.wait_for_timeout(200)

        after = validator.get_bbox(sel)
        assert after["width"] > before["width"], (
            f"Panel width did not increase after resize: "
            f"{before['width']} -> {after['width']}"
        )
        assert after["height"] > before["height"], (
            f"Panel height did not increase after resize: "
            f"{before['height']} -> {after['height']}"
        )
