"""Panel lifecycle tests for the Command Center.

For each of the 5 panels (amy, units, alerts, game, mesh):
open, verify visible, drag, resize, minimize, restore, close.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_panel_lifecycle.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.ui.conftest import assert_panel_visible, assert_panel_hidden, wait_for_panel

pytestmark = [pytest.mark.ux, pytest.mark.ui]


PANELS = [
    ('1', 'amy', 'AMY'),
    ('2', 'units', 'UNITS'),
    ('3', 'alerts', 'ALERTS'),
    ('4', 'game', 'GAME STATUS'),
    ('5', 'mesh', 'MESHTASTIC'),
]


class TestPanelOpen:
    """Opening panels via keyboard shortcut."""

    @pytest.mark.parametrize("key,panel_id,title", PANELS)
    def test_open_panel(self, page, take_screenshot, key, panel_id, title):
        """Pressing {key} should open the {panel_id} panel with title {title}."""
        # Close if already open
        panel_loc = page.locator(f'[data-panel-id="{panel_id}"]')
        if panel_loc.count() > 0 and panel_loc.is_visible():
            page.keyboard.press(key)
            page.wait_for_timeout(500)

        # Open
        page.keyboard.press(key)
        page.wait_for_timeout(500)
        assert_panel_visible(page, panel_id)

        # Verify title text
        panel_title = page.locator(
            f'[data-panel-id="{panel_id}"] .panel-title'
        )
        assert title in panel_title.text_content(), \
            f"Panel title should contain '{title}'"
        take_screenshot(page, f'panel-{panel_id}-open')


class TestPanelDrag:
    """Dragging panels by their header."""

    @pytest.mark.parametrize("key,panel_id,title", PANELS)
    def test_drag_panel(self, page, take_screenshot, key, panel_id, title):
        """Dragging {panel_id} panel header should move the panel."""
        # Close all panels to avoid overlap
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        for k, pid, _ in PANELS:
            p = page.locator(f'[data-panel-id="{pid}"]')
            if p.count() > 0 and p.is_visible():
                page.keyboard.press(k)
                page.wait_for_timeout(200)

        # Open only the target panel
        page.keyboard.press(key)
        page.wait_for_timeout(500)

        panel_loc = page.locator(f'[data-panel-id="{panel_id}"]')
        assert panel_loc.is_visible(), f"Panel '{panel_id}' should be visible"

        # Position panel at a known location via JS for reliable drag testing
        page.evaluate(
            """(panelId) => {
                const panel = window.panelManager && window.panelManager.getPanel(panelId);
                if (panel) {
                    panel.setPosition(200, 200);
                    panel.setSize(300, 250);
                }
            }""",
            panel_id
        )
        page.wait_for_timeout(300)

        # Get initial position
        box_before = panel_loc.bounding_box()
        assert box_before is not None, f"Panel '{panel_id}' should have a bounding box"

        # Drag via header
        header = page.locator(
            f'[data-panel-id="{panel_id}"] [data-drag-handle]'
        )
        header_box = header.bounding_box()
        start_x = header_box['x'] + header_box['width'] / 2
        start_y = header_box['y'] + header_box['height'] / 2

        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x + 200, start_y + 100, steps=10)
        page.mouse.up()
        page.wait_for_timeout(300)

        # Verify position changed
        box_after = panel_loc.bounding_box()
        moved = (
            abs(box_after['x'] - box_before['x']) > 10
            or abs(box_after['y'] - box_before['y']) > 10
        )
        assert moved, \
            f"Panel '{panel_id}' should have moved after drag " \
            f"(before: {box_before['x']:.0f},{box_before['y']:.0f} after: {box_after['x']:.0f},{box_after['y']:.0f})"
        take_screenshot(page, f'panel-{panel_id}-dragged')


class TestPanelResize:
    """Resizing panels via the resize handle."""

    @pytest.mark.parametrize("key,panel_id,title", PANELS)
    def test_resize_panel(self, page, take_screenshot, key, panel_id, title):
        """Dragging {panel_id} resize handle should resize the panel."""
        # Close all panels first to avoid overlap interference
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        for k, pid, _ in PANELS:
            p = page.locator(f'[data-panel-id="{pid}"]')
            if p.count() > 0 and p.is_visible():
                page.keyboard.press(k)
                page.wait_for_timeout(200)

        # Open only the target panel
        page.keyboard.press(key)
        page.wait_for_timeout(500)

        panel_loc = page.locator(f'[data-panel-id="{panel_id}"]')
        assert panel_loc.is_visible(), f"Panel '{panel_id}' should be visible"

        # Move panel to a known position via JS to ensure resize handle is on-screen
        page.evaluate(
            """(panelId) => {
                const panel = window.panelManager && window.panelManager.getPanel(panelId);
                if (panel) {
                    panel.setPosition(50, 50);
                    panel.setSize(300, 250);
                }
            }""",
            panel_id
        )
        page.wait_for_timeout(300)

        box_before = panel_loc.bounding_box()
        assert box_before is not None, f"Panel '{panel_id}' should have a bounding box"

        # Drag resize handle
        handle = page.locator(
            f'[data-panel-id="{panel_id}"] [data-resize-handle]'
        )
        handle_box = handle.bounding_box()
        if handle_box is None:
            pytest.skip(f"No resize handle visible for '{panel_id}'")

        hx = handle_box['x'] + handle_box['width'] / 2
        hy = handle_box['y'] + handle_box['height'] / 2

        page.mouse.move(hx, hy)
        page.mouse.down()
        page.mouse.move(hx + 120, hy + 100, steps=10)
        page.mouse.up()
        page.wait_for_timeout(300)

        box_after = panel_loc.bounding_box()
        width_changed = abs(box_after['width'] - box_before['width']) > 5
        height_changed = abs(box_after['height'] - box_before['height']) > 5
        assert width_changed or height_changed, \
            f"Panel '{panel_id}' should have resized (before: {box_before['width']}x{box_before['height']}, after: {box_after['width']}x{box_after['height']})"
        take_screenshot(page, f'panel-{panel_id}-resized')


class TestPanelMinimize:
    """Minimizing and restoring panels."""

    @pytest.mark.parametrize("key,panel_id,title", PANELS)
    def test_minimize_restore(self, page, take_screenshot, key, panel_id, title):
        """Clicking minimize should collapse {panel_id}, clicking again restores."""
        # Ensure panel is open
        panel_loc = page.locator(f'[data-panel-id="{panel_id}"]')
        if panel_loc.count() == 0 or not panel_loc.is_visible():
            page.keyboard.press(key)
            page.wait_for_timeout(500)

        box_full = panel_loc.bounding_box()

        # Click minimize button
        minimize_btn = page.locator(
            f'[data-panel-id="{panel_id}"] .panel-minimize'
        )
        minimize_btn.click()
        page.wait_for_timeout(300)

        # Verify minimized (height should be small, ~28px)
        box_min = panel_loc.bounding_box()
        assert box_min['height'] < box_full['height'], \
            f"Panel '{panel_id}' height should decrease when minimized"
        assert box_min['height'] < 50, \
            f"Minimized panel should be < 50px tall (got {box_min['height']})"
        take_screenshot(page, f'panel-{panel_id}-minimized')

        # Click minimize again to restore
        minimize_btn.click()
        page.wait_for_timeout(300)

        box_restored = panel_loc.bounding_box()
        assert box_restored['height'] > 50, \
            f"Restored panel should be > 50px tall"
        take_screenshot(page, f'panel-{panel_id}-restored')


class TestPanelClose:
    """Closing panels via the close button."""

    @pytest.mark.parametrize("key,panel_id,title", PANELS)
    def test_close_panel(self, page, take_screenshot, key, panel_id, title):
        """Clicking close button should hide the {panel_id} panel."""
        # Ensure panel is open
        panel_loc = page.locator(f'[data-panel-id="{panel_id}"]')
        if panel_loc.count() == 0 or not panel_loc.is_visible():
            page.keyboard.press(key)
            page.wait_for_timeout(500)

        assert_panel_visible(page, panel_id)

        # Click close button
        close_btn = page.locator(
            f'[data-panel-id="{panel_id}"] .panel-close'
        )
        close_btn.click()
        page.wait_for_timeout(500)

        assert_panel_hidden(page, panel_id)
        take_screenshot(page, f'panel-{panel_id}-closed')
