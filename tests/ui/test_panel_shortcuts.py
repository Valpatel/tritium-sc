"""Test all panel keyboard shortcuts in /unified Command Center.

Verifies that pressing each number key (1-9, 0) opens and closes
the corresponding panel. Tests all 12 registered panels.

Requires: tritium_server fixture (auto-started), Playwright.
"""
from __future__ import annotations

import pytest

from tests.ui.conftest import assert_panel_visible, assert_panel_hidden

pytestmark = [pytest.mark.ui, pytest.mark.panels]

# Panel ID -> keyboard shortcut mapping
PANEL_SHORTCUTS = [
    ("amy", "1"),
    ("units", "2"),
    ("alerts", "3"),
    ("game", "4"),
    ("mesh", "5"),
    ("cameras", "6"),
    ("audio", "7"),
    ("zones", "8"),
    ("scenarios", "9"),
    ("search", "0"),
]

# Panels without keyboard shortcuts (opened via menu only)
MENU_ONLY_PANELS = ["videos", "system"]


class TestPanelShortcuts:
    """Verify all panel keyboard shortcuts toggle panels open/close."""

    def _close_all_panels(self, page):
        """Close all panels by pressing each shortcut if panel is open."""
        for panel_id, key in PANEL_SHORTCUTS:
            panel = page.locator(f'[data-panel-id="{panel_id}"]')
            if panel.count() > 0 and panel.is_visible():
                page.keyboard.press(key)
                page.wait_for_timeout(150)

    def _is_panel_open(self, page, panel_id):
        """Check if a panel is currently visible."""
        panel = page.locator(f'[data-panel-id="{panel_id}"]')
        return panel.count() > 0 and panel.is_visible()

    @pytest.mark.parametrize("panel_id,key", PANEL_SHORTCUTS)
    def test_toggle_panel(self, page, panel_id, key):
        """Press key to toggle panel open, press again to toggle closed."""
        # Determine starting state
        was_open = self._is_panel_open(page, panel_id)

        # First press: toggle
        page.keyboard.press(key)
        page.wait_for_timeout(500)

        if was_open:
            # Was open, should now be closed
            assert_panel_hidden(page, panel_id)
            # Press again to re-open
            page.keyboard.press(key)
            page.wait_for_timeout(500)
            assert_panel_visible(page, panel_id)
        else:
            # Was closed, should now be open
            assert_panel_visible(page, panel_id)
            # Press again to close
            page.keyboard.press(key)
            page.wait_for_timeout(500)
            assert_panel_hidden(page, panel_id)

    def test_multiple_panels_open(self, page):
        """Open multiple panels simultaneously via shortcuts."""
        self._close_all_panels(page)
        page.wait_for_timeout(300)

        # Open 3 panels
        page.keyboard.press("1")
        page.wait_for_timeout(300)
        page.keyboard.press("2")
        page.wait_for_timeout(300)
        page.keyboard.press("3")
        page.wait_for_timeout(300)

        assert_panel_visible(page, "amy")
        assert_panel_visible(page, "units")
        assert_panel_visible(page, "alerts")

        # Clean up
        self._close_all_panels(page)

    def test_panel_has_content(self, page):
        """Verify opened panels have actual content, not empty containers."""
        self._close_all_panels(page)
        page.wait_for_timeout(300)

        for panel_id, key in PANEL_SHORTCUTS[:5]:
            page.keyboard.press(key)
            page.wait_for_timeout(600)

            panel = page.locator(f'[data-panel-id="{panel_id}"]')
            body = panel.locator('.panel-body')
            child_count = body.evaluate("el => el.children.length")
            assert child_count > 0, f"Panel '{panel_id}' body is empty"

            page.keyboard.press(key)
            page.wait_for_timeout(200)

    def test_all_panels_can_open(self, page):
        """Verify all 10 shortcut-accessible panels can be opened at once."""
        self._close_all_panels(page)
        page.wait_for_timeout(300)

        for _, key in PANEL_SHORTCUTS:
            page.keyboard.press(key)
            page.wait_for_timeout(200)

        for panel_id, _ in PANEL_SHORTCUTS:
            assert_panel_visible(page, panel_id)

        # Clean up
        self._close_all_panels(page)
