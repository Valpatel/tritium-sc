# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Map interaction tests for the Command Center.

Exercises pan, zoom, satellite toggle, roads toggle, minimap toggle,
and map mode switching.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_map_interactions.py -v -m ux
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.ux, pytest.mark.ui]


class TestMapPan:
    """Mouse drag on the tactical canvas to pan the map."""

    def test_pan_map(self, page, take_screenshot):
        """Dragging on the canvas should pan the map."""
        canvas = page.locator('#tactical-canvas')
        box = canvas.bounding_box()
        assert box is not None, "Tactical canvas should exist"

        cx = box['x'] + box['width'] / 2
        cy = box['y'] + box['height'] / 2

        take_screenshot(page, 'map-pan-before')

        # Drag from center to the left
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx - 200, cy - 100, steps=5)
        page.mouse.up()
        page.wait_for_timeout(500)

        take_screenshot(page, 'map-pan-after')


class TestMapZoom:
    """Zoom via keyboard [ and ] keys."""

    def test_zoom_out_bracket(self, page, take_screenshot):
        """Pressing [ should zoom out."""
        take_screenshot(page, 'map-zoom-before')
        for _ in range(3):
            page.keyboard.press('[')
            page.wait_for_timeout(200)
        page.wait_for_timeout(500)
        take_screenshot(page, 'map-zoom-out')

    def test_zoom_in_bracket(self, page, take_screenshot):
        """Pressing ] should zoom in."""
        for _ in range(3):
            page.keyboard.press(']')
            page.wait_for_timeout(200)
        page.wait_for_timeout(500)
        take_screenshot(page, 'map-zoom-in')


class TestSatelliteToggle:
    """Pressing I toggles satellite imagery."""

    def test_satellite_toggle(self, page, take_screenshot):
        """Pressing I should toggle satellite (visual change on canvas)."""
        take_screenshot(page, 'map-satellite-before')
        page.keyboard.press('i')
        page.wait_for_timeout(1000)
        take_screenshot(page, 'map-satellite-toggled')
        # Toggle back
        page.keyboard.press('i')
        page.wait_for_timeout(1000)
        take_screenshot(page, 'map-satellite-restored')


class TestRoadsToggle:
    """Pressing G toggles roads overlay."""

    def test_roads_toggle(self, page, take_screenshot):
        """Pressing G should toggle roads overlay."""
        take_screenshot(page, 'map-roads-before')
        page.keyboard.press('g')
        page.wait_for_timeout(1000)
        take_screenshot(page, 'map-roads-toggled')
        # Toggle back
        page.keyboard.press('g')
        page.wait_for_timeout(1000)
        take_screenshot(page, 'map-roads-restored')


class TestMinimapToggle:
    """Pressing M toggles the minimap."""

    def test_minimap_toggle(self, page, take_screenshot):
        """Pressing M should show/hide the minimap container."""
        minimap = page.locator('#minimap-container')

        # Ensure visible first
        if minimap.is_hidden():
            page.keyboard.press('m')
            page.wait_for_timeout(500)

        assert not minimap.is_hidden(), "Minimap should start visible"
        take_screenshot(page, 'map-minimap-visible')

        page.keyboard.press('m')
        page.wait_for_timeout(500)
        assert minimap.is_hidden(), "Minimap should hide after M"
        take_screenshot(page, 'map-minimap-hidden')

        page.keyboard.press('m')
        page.wait_for_timeout(500)
        assert not minimap.is_hidden(), "Minimap should show again after M"
        take_screenshot(page, 'map-minimap-restored')


class TestMapModes:
    """Map mode switching via O, T, S keys."""

    def test_observe_mode(self, page, take_screenshot):
        """Pressing O should set observe mode as active."""
        page.keyboard.press('o')
        page.wait_for_timeout(500)
        btn = page.locator('[data-map-mode="observe"]')
        assert 'active' in (btn.get_attribute('class') or ''), \
            "Observe button should be active"
        take_screenshot(page, 'map-mode-observe')

    def test_tactical_mode(self, page, take_screenshot):
        """Pressing T should set tactical mode as active."""
        page.keyboard.press('t')
        page.wait_for_timeout(500)
        btn = page.locator('[data-map-mode="tactical"]')
        assert 'active' in (btn.get_attribute('class') or ''), \
            "Tactical button should be active"
        # Observe should not be active
        obs_btn = page.locator('[data-map-mode="observe"]')
        assert 'active' not in (obs_btn.get_attribute('class') or ''), \
            "Observe button should NOT be active when tactical is selected"
        take_screenshot(page, 'map-mode-tactical')

    def test_setup_mode(self, page, take_screenshot):
        """Pressing S should set setup mode as active."""
        page.keyboard.press('s')
        page.wait_for_timeout(500)
        btn = page.locator('[data-map-mode="setup"]')
        assert 'active' in (btn.get_attribute('class') or ''), \
            "Setup button should be active"
        take_screenshot(page, 'map-mode-setup')

    def test_mode_switching_removes_previous(self, page, take_screenshot):
        """Switching modes should deactivate the previous mode button."""
        page.keyboard.press('o')
        page.wait_for_timeout(300)
        page.keyboard.press('t')
        page.wait_for_timeout(300)
        page.keyboard.press('s')
        page.wait_for_timeout(300)

        # Only setup should be active
        for mode in ['observe', 'tactical']:
            btn = page.locator(f'[data-map-mode="{mode}"]')
            assert 'active' not in (btn.get_attribute('class') or ''), \
                f"{mode} should NOT be active"

        setup_btn = page.locator('[data-map-mode="setup"]')
        assert 'active' in (setup_btn.get_attribute('class') or ''), \
            "Setup should be the only active mode"
        take_screenshot(page, 'map-mode-switching')
