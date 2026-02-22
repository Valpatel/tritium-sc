"""Menu bar interaction tests for the Command Center.

Exercises every dropdown menu: FILE, VIEW, LAYOUT, MAP, HELP.
Verifies items appear, checkable items toggle, and actions fire.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_menu_bar.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.ui.conftest import click_menu_item, assert_panel_visible, assert_panel_hidden

pytestmark = [pytest.mark.ux, pytest.mark.ui]


class TestFileMenu:
    """FILE menu items."""

    def test_file_menu_opens(self, page, take_screenshot):
        """Clicking FILE trigger should reveal the dropdown."""
        trigger = page.locator('.menu-trigger:has-text("FILE")')
        trigger.click()
        page.wait_for_timeout(300)
        dropdown = trigger.locator('..').locator('.menu-dropdown')
        assert not dropdown.is_hidden(), "FILE dropdown should be visible"
        take_screenshot(page, 'menu-file-open')
        # Close
        page.keyboard.press('Escape')

    def test_file_save_layout_item(self, page, take_screenshot):
        """FILE > Save Layout... should show the save input."""
        click_menu_item(page, 'FILE', 'Save Layout...')
        page.wait_for_timeout(300)
        save_input = page.locator('.command-bar-save-input')
        assert save_input.is_visible(), "Save input should appear"
        take_screenshot(page, 'menu-file-save-layout')
        page.keyboard.press('Escape')

    def test_file_export_layout(self, page, take_screenshot):
        """FILE > Export Layout JSON should trigger download."""
        click_menu_item(page, 'FILE', 'Export Layout JSON')
        page.wait_for_timeout(500)
        take_screenshot(page, 'menu-file-export')

    def test_file_import_layout(self, page, take_screenshot):
        """FILE > Import Layout JSON should trigger file picker."""
        # We can only verify the click fires without error
        trigger = page.locator('.menu-trigger:has-text("FILE")')
        trigger.click()
        page.wait_for_timeout(300)
        item = page.locator(
            '.menu-item:has(.menu-item-label:has-text("Import Layout JSON"))'
        ).first
        assert item.is_visible(), "Import Layout JSON item should be visible"
        take_screenshot(page, 'menu-file-import-visible')
        page.keyboard.press('Escape')


class TestViewMenu:
    """VIEW menu: panel toggles, Show All, Hide All, Fullscreen."""

    def test_view_menu_opens(self, page, take_screenshot):
        """Clicking VIEW trigger should reveal the dropdown."""
        trigger = page.locator('.menu-trigger:has-text("VIEW")')
        trigger.click()
        page.wait_for_timeout(300)
        dropdown = trigger.locator('..').locator('.menu-dropdown')
        assert not dropdown.is_hidden(), "VIEW dropdown should be visible"
        take_screenshot(page, 'menu-view-open')
        page.keyboard.press('Escape')

    def test_view_toggle_amy_panel(self, page, take_screenshot):
        """VIEW > AMY COMMANDER should toggle the Amy panel visibility."""
        # Start from a known state: close amy via keyboard
        amy = page.locator('[data-panel-id="amy"]')
        if amy.count() > 0 and amy.is_visible():
            page.keyboard.press('1')
            page.wait_for_timeout(500)

        assert_panel_hidden(page, 'amy')

        # Open via VIEW menu (label is 'AMY COMMANDER' per panel definition)
        click_menu_item(page, 'VIEW', 'AMY COMMANDER')
        page.wait_for_timeout(500)
        assert_panel_visible(page, 'amy')
        take_screenshot(page, 'menu-view-toggle-amy-open')

        # Close via VIEW menu
        click_menu_item(page, 'VIEW', 'AMY COMMANDER')
        page.wait_for_timeout(500)
        assert_panel_hidden(page, 'amy')
        take_screenshot(page, 'menu-view-toggle-amy-closed')

    def test_view_toggle_units_panel(self, page, take_screenshot):
        """VIEW > UNITS should toggle the Units panel visibility."""
        # Start from known state: close units via keyboard
        units = page.locator('[data-panel-id="units"]')
        if units.count() > 0 and units.is_visible():
            page.keyboard.press('2')
            page.wait_for_timeout(500)

        assert_panel_hidden(page, 'units')

        # Open via VIEW menu
        click_menu_item(page, 'VIEW', 'UNITS')
        page.wait_for_timeout(500)
        assert_panel_visible(page, 'units')
        take_screenshot(page, 'menu-view-toggle-units-open')

        # Close via VIEW menu
        click_menu_item(page, 'VIEW', 'UNITS')
        page.wait_for_timeout(500)
        assert_panel_hidden(page, 'units')
        take_screenshot(page, 'menu-view-toggle-units-closed')

    def test_view_show_all(self, page, take_screenshot):
        """VIEW > Show All should open all panels."""
        click_menu_item(page, 'VIEW', 'Show All')
        page.wait_for_timeout(500)
        for pid in ['amy', 'units', 'alerts', 'game', 'mesh']:
            assert_panel_visible(page, pid)
        take_screenshot(page, 'menu-view-show-all')

    def test_view_hide_all(self, page, take_screenshot):
        """VIEW > Hide All should close all panels."""
        # Ensure some are open first
        click_menu_item(page, 'VIEW', 'Show All')
        page.wait_for_timeout(500)
        click_menu_item(page, 'VIEW', 'Hide All')
        page.wait_for_timeout(500)
        for pid in ['amy', 'units', 'alerts', 'game', 'mesh']:
            assert_panel_hidden(page, pid)
        take_screenshot(page, 'menu-view-hide-all')


class TestLayoutMenu:
    """LAYOUT menu: built-in presets."""

    def test_layout_menu_opens(self, page, take_screenshot):
        """Clicking LAYOUT trigger should reveal the dropdown."""
        trigger = page.locator('.menu-trigger:has-text("LAYOUT")')
        trigger.click()
        page.wait_for_timeout(300)
        dropdown = trigger.locator('..').locator('.menu-dropdown')
        assert not dropdown.is_hidden(), "LAYOUT dropdown should be visible"
        take_screenshot(page, 'menu-layout-open')
        page.keyboard.press('Escape')

    def test_layout_commander(self, page, take_screenshot):
        """LAYOUT > Commander should apply the commander layout."""
        click_menu_item(page, 'LAYOUT', 'Commander')
        page.wait_for_timeout(500)
        take_screenshot(page, 'menu-layout-commander')
        # Commander layout opens amy, units, alerts
        assert_panel_visible(page, 'amy')
        assert_panel_visible(page, 'units')
        assert_panel_visible(page, 'alerts')

    def test_layout_observer(self, page, take_screenshot):
        """LAYOUT > Observer should apply the observer layout."""
        click_menu_item(page, 'LAYOUT', 'Observer')
        page.wait_for_timeout(500)
        take_screenshot(page, 'menu-layout-observer')
        assert_panel_visible(page, 'alerts')

    def test_layout_tactical(self, page, take_screenshot):
        """LAYOUT > Tactical should apply the tactical layout."""
        click_menu_item(page, 'LAYOUT', 'Tactical')
        page.wait_for_timeout(500)
        take_screenshot(page, 'menu-layout-tactical')
        assert_panel_visible(page, 'units')
        assert_panel_visible(page, 'alerts')

    def test_layout_battle(self, page, take_screenshot):
        """LAYOUT > Battle should apply the battle layout."""
        click_menu_item(page, 'LAYOUT', 'Battle')
        page.wait_for_timeout(500)
        take_screenshot(page, 'menu-layout-battle')
        assert_panel_visible(page, 'amy')
        assert_panel_visible(page, 'units')
        assert_panel_visible(page, 'alerts')
        assert_panel_visible(page, 'game')


class TestMapMenu:
    """MAP menu: satellite, roads, grid, 3D mode, navigation."""

    def test_map_menu_opens(self, page, take_screenshot):
        """Clicking MAP trigger should reveal the dropdown."""
        trigger = page.locator('.menu-trigger:has-text("MAP")')
        trigger.click()
        page.wait_for_timeout(300)
        dropdown = trigger.locator('..').locator('.menu-dropdown')
        assert not dropdown.is_hidden(), "MAP dropdown should be visible"
        take_screenshot(page, 'menu-map-open')
        page.keyboard.press('Escape')

    def test_map_satellite_toggle(self, page, take_screenshot):
        """MAP > Satellite should toggle and show a check indicator."""
        trigger = page.locator('.menu-trigger:has-text("MAP")')
        trigger.click()
        page.wait_for_timeout(300)
        sat_item = page.locator(
            '.menu-item:has(.menu-item-label:has-text("Satellite"))'
        ).first
        # Get the check element
        check = sat_item.locator('.menu-item-check')
        before = check.text_content()
        sat_item.click()
        page.wait_for_timeout(300)
        # Reopen to check toggled state
        trigger.click()
        page.wait_for_timeout(300)
        sat_item = page.locator(
            '.menu-item:has(.menu-item-label:has-text("Satellite"))'
        ).first
        after = sat_item.locator('.menu-item-check').text_content()
        take_screenshot(page, 'menu-map-satellite-toggled')
        # The check should have changed
        assert before != after, "Satellite check indicator should toggle"
        page.keyboard.press('Escape')

    def test_map_roads_toggle(self, page, take_screenshot):
        """MAP > Roads should toggle and show a check indicator."""
        trigger = page.locator('.menu-trigger:has-text("MAP")')
        trigger.click()
        page.wait_for_timeout(300)
        roads_item = page.locator(
            '.menu-item:has(.menu-item-label:has-text("Roads"))'
        ).first
        check = roads_item.locator('.menu-item-check')
        before = check.text_content()
        roads_item.click()
        page.wait_for_timeout(300)
        trigger.click()
        page.wait_for_timeout(300)
        roads_item = page.locator(
            '.menu-item:has(.menu-item-label:has-text("Roads"))'
        ).first
        after = roads_item.locator('.menu-item-check').text_content()
        take_screenshot(page, 'menu-map-roads-toggled')
        assert before != after, "Roads check indicator should toggle"
        page.keyboard.press('Escape')

    def test_map_grid_toggle(self, page, take_screenshot):
        """MAP > Grid should toggle and show a check indicator."""
        trigger = page.locator('.menu-trigger:has-text("MAP")')
        trigger.click()
        page.wait_for_timeout(300)
        grid_item = page.locator(
            '.menu-item:has(.menu-item-label:has-text("Grid"))'
        ).first
        check = grid_item.locator('.menu-item-check')
        before = check.text_content()
        grid_item.click()
        page.wait_for_timeout(300)
        trigger.click()
        page.wait_for_timeout(300)
        grid_item = page.locator(
            '.menu-item:has(.menu-item-label:has-text("Grid"))'
        ).first
        after = grid_item.locator('.menu-item-check').text_content()
        take_screenshot(page, 'menu-map-grid-toggled')
        assert before != after, "Grid check indicator should toggle"
        page.keyboard.press('Escape')


class TestHelpMenu:
    """HELP menu items."""

    def test_help_menu_opens(self, page, take_screenshot):
        """Clicking HELP trigger should reveal the dropdown."""
        trigger = page.locator('.menu-trigger:has-text("HELP")')
        trigger.click()
        page.wait_for_timeout(300)
        dropdown = trigger.locator('..').locator('.menu-dropdown')
        assert not dropdown.is_hidden(), "HELP dropdown should be visible"
        take_screenshot(page, 'menu-help-open')
        page.keyboard.press('Escape')

    def test_help_keyboard_shortcuts(self, page, take_screenshot):
        """HELP > Keyboard Shortcuts should open the help overlay."""
        click_menu_item(page, 'HELP', 'Keyboard Shortcuts')
        page.wait_for_timeout(500)
        help_overlay = page.locator('#help-overlay')
        assert not help_overlay.is_hidden(), "Help overlay should be visible"
        take_screenshot(page, 'menu-help-shortcuts')
        page.keyboard.press('Escape')

    def test_help_about(self, page, take_screenshot):
        """HELP > About TRITIUM-SC should show a toast."""
        click_menu_item(page, 'HELP', 'About TRITIUM-SC')
        page.wait_for_timeout(500)
        take_screenshot(page, 'menu-help-about')
        # Verify toast appeared
        toast = page.locator('.toast').first
        assert toast.is_visible(), "About toast should appear"
