"""Keyboard shortcut tests for the Command Center.

Exercises every keyboard shortcut: panel toggles, chat, help,
map modes, zoom, satellite, roads, minimap, layouts, save.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_keyboard_shortcuts.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.ui.conftest import assert_panel_visible, assert_panel_hidden, wait_for_panel

pytestmark = [pytest.mark.ux, pytest.mark.ui]


class TestPanelToggleKeys:
    """Keys 1-5 toggle floating panels."""

    @pytest.mark.parametrize("key,panel_id", [
        ('1', 'amy'),
        ('2', 'units'),
        ('3', 'alerts'),
        ('4', 'game'),
        ('5', 'mesh'),
    ])
    def test_panel_toggle(self, page, take_screenshot, key, panel_id):
        """Pressing {key} should toggle the {panel_id} panel."""
        # Close all panels first
        for k in ['1', '2', '3', '4', '5']:
            panel = page.locator(f'[data-panel-id]')
            # Close via hide all: use keyboard to close individually
        # Ensure panel is closed by toggling if open
        p = page.locator(f'[data-panel-id="{panel_id}"]')
        if p.count() > 0 and p.is_visible():
            page.keyboard.press(key)
            page.wait_for_timeout(500)

        # Now it should be hidden
        assert_panel_hidden(page, panel_id)
        take_screenshot(page, f'key-{key}-{panel_id}-before')

        # Press key to open
        page.keyboard.press(key)
        page.wait_for_timeout(500)
        assert_panel_visible(page, panel_id)
        take_screenshot(page, f'key-{key}-{panel_id}-open')

        # Press again to close
        page.keyboard.press(key)
        page.wait_for_timeout(500)
        assert_panel_hidden(page, panel_id)
        take_screenshot(page, f'key-{key}-{panel_id}-closed')


class TestChatShortcuts:
    """C and / open chat, Escape closes it."""

    def test_c_opens_chat(self, page, take_screenshot):
        """Pressing C should open the chat overlay."""
        page.keyboard.press('Escape')  # close anything open
        page.wait_for_timeout(300)
        chat = page.locator('#chat-overlay')
        assert chat.is_hidden(), "Chat should start hidden"

        page.keyboard.press('c')
        page.wait_for_timeout(500)
        assert not chat.is_hidden(), "Chat should open on C"
        take_screenshot(page, 'key-c-chat-open')

        # Verify input is focused
        focused = page.evaluate("document.activeElement.id")
        assert focused == 'chat-input', "Chat input should be focused"

    def test_slash_opens_chat(self, page, take_screenshot):
        """Pressing / should open chat and focus input."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

        page.keyboard.press('/')
        page.wait_for_timeout(500)
        chat = page.locator('#chat-overlay')
        assert not chat.is_hidden(), "Chat should open on /"
        take_screenshot(page, 'key-slash-chat-open')

        focused = page.evaluate("document.activeElement.id")
        assert focused == 'chat-input', "Chat input should be focused"

    def test_escape_closes_chat(self, page, take_screenshot):
        """Pressing Escape should close an open chat overlay."""
        page.keyboard.press('c')
        page.wait_for_timeout(300)
        # Click outside chat-input to unfocus it (so Escape goes to keydown handler)
        page.locator('#tactical-canvas').click()
        page.wait_for_timeout(200)

        page.keyboard.press('Escape')
        page.wait_for_timeout(500)
        chat = page.locator('#chat-overlay')
        assert chat.is_hidden(), "Chat should close on Escape"
        take_screenshot(page, 'key-escape-chat-closed')


class TestHelpShortcut:
    """? toggles help overlay."""

    def test_question_mark_opens_help(self, page, take_screenshot):
        """Pressing ? should open the help overlay."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        help_el = page.locator('#help-overlay')
        assert help_el.is_hidden(), "Help should start hidden"

        page.keyboard.press('?')
        page.wait_for_timeout(500)
        assert not help_el.is_hidden(), "Help should open on ?"
        take_screenshot(page, 'key-help-open')

    def test_question_mark_toggles_help(self, page, take_screenshot):
        """Pressing ? twice should open then close help."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

        page.keyboard.press('?')
        page.wait_for_timeout(300)
        help_el = page.locator('#help-overlay')
        assert not help_el.is_hidden()

        page.keyboard.press('?')
        page.wait_for_timeout(300)
        assert help_el.is_hidden(), "Help should close on second ?"
        take_screenshot(page, 'key-help-toggle-closed')

    def test_escape_closes_help(self, page, take_screenshot):
        """Pressing Escape should close the help overlay."""
        page.keyboard.press('?')
        page.wait_for_timeout(300)
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        help_el = page.locator('#help-overlay')
        assert help_el.is_hidden(), "Help should close on Escape"
        take_screenshot(page, 'key-escape-closes-help')


class TestMapModeKeys:
    """O, T, S switch map modes."""

    @pytest.mark.parametrize("key,mode", [
        ('o', 'observe'),
        ('t', 'tactical'),
        ('s', 'setup'),
    ])
    def test_map_mode_key(self, page, take_screenshot, key, mode):
        """Pressing {key} should activate {mode} map mode button."""
        page.keyboard.press(key)
        page.wait_for_timeout(500)
        btn = page.locator(f'[data-map-mode="{mode}"]')
        assert 'active' in (btn.get_attribute('class') or ''), \
            f"Map mode button '{mode}' should have 'active' class"
        take_screenshot(page, f'key-{key}-mapmode-{mode}')


class TestMapKeys:
    """Map navigation keys: I (satellite), G (roads), M (minimap), [/] (zoom)."""

    def test_i_toggles_satellite(self, page, take_screenshot):
        """Pressing I should toggle satellite imagery."""
        page.keyboard.press('i')
        page.wait_for_timeout(500)
        take_screenshot(page, 'key-i-satellite')

    def test_g_toggles_roads(self, page, take_screenshot):
        """Pressing G should toggle roads overlay."""
        page.keyboard.press('g')
        page.wait_for_timeout(500)
        take_screenshot(page, 'key-g-roads')

    def test_m_toggles_minimap(self, page, take_screenshot):
        """Pressing M should toggle the minimap container."""
        minimap = page.locator('#minimap-container')
        was_hidden = minimap.is_hidden()

        page.keyboard.press('m')
        page.wait_for_timeout(500)

        if was_hidden:
            assert not minimap.is_hidden(), "Minimap should be visible after M"
        else:
            assert minimap.is_hidden(), "Minimap should be hidden after M"
        take_screenshot(page, 'key-m-minimap-toggle')

    def test_bracket_zoom(self, page, take_screenshot):
        """Pressing [ and ] should zoom out and in without error."""
        page.keyboard.press('[')
        page.wait_for_timeout(300)
        take_screenshot(page, 'key-bracket-zoom-out')
        page.keyboard.press(']')
        page.wait_for_timeout(300)
        take_screenshot(page, 'key-bracket-zoom-in')


class TestLayoutKeys:
    """Ctrl+1..4 apply layout presets, Ctrl+Shift+S opens save."""

    def test_ctrl_1_commander_layout(self, page, take_screenshot):
        """Ctrl+1 should apply the commander layout."""
        page.keyboard.press('Control+1')
        page.wait_for_timeout(500)
        assert_panel_visible(page, 'amy')
        assert_panel_visible(page, 'units')
        assert_panel_visible(page, 'alerts')
        take_screenshot(page, 'key-ctrl1-commander')

    def test_ctrl_2_observer_layout(self, page, take_screenshot):
        """Ctrl+2 should apply the observer layout."""
        page.keyboard.press('Control+2')
        page.wait_for_timeout(500)
        assert_panel_visible(page, 'alerts')
        take_screenshot(page, 'key-ctrl2-observer')

    def test_ctrl_3_tactical_layout(self, page, take_screenshot):
        """Ctrl+3 should apply the tactical layout."""
        page.keyboard.press('Control+3')
        page.wait_for_timeout(500)
        assert_panel_visible(page, 'units')
        assert_panel_visible(page, 'alerts')
        take_screenshot(page, 'key-ctrl3-tactical')

    def test_ctrl_4_battle_layout(self, page, take_screenshot):
        """Ctrl+4 should apply the battle layout."""
        page.keyboard.press('Control+4')
        page.wait_for_timeout(500)
        assert_panel_visible(page, 'amy')
        assert_panel_visible(page, 'units')
        assert_panel_visible(page, 'alerts')
        assert_panel_visible(page, 'game')
        take_screenshot(page, 'key-ctrl4-battle')

    def test_ctrl_shift_s_save_input(self, page, take_screenshot):
        """Ctrl+Shift+S should reveal the save layout input."""
        page.keyboard.press('Control+Shift+s')
        page.wait_for_timeout(500)
        save_input = page.locator('.command-bar-save-input')
        assert save_input.is_visible(), "Save input should appear"
        take_screenshot(page, 'key-ctrl-shift-s-save')
        page.keyboard.press('Escape')
