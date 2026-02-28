# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Meshtastic panel tests for the Command Center.

Exercises the Meshtastic (mesh) radio panel: open, verify structure,
switch tabs (Nodes, Chat, Radio, Scan), interact with chat input.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_meshtastic_panel.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.ui.conftest import assert_panel_visible, assert_panel_hidden

pytestmark = [pytest.mark.ux, pytest.mark.ui]


def _open_mesh(page):
    """Ensure the mesh panel is open."""
    panel = page.locator('[data-panel-id="mesh"]')
    if panel.count() == 0 or not panel.is_visible():
        page.keyboard.press('5')
        page.wait_for_timeout(500)


def _switch_tab(page, tab_name):
    """Click a tab button inside the mesh panel."""
    tab = page.locator(f'[data-panel-id="mesh"] .mesh-tab[data-tab="{tab_name}"]')
    if tab.count() > 0:
        tab.click()
        page.wait_for_timeout(300)


class TestMeshPanelOpen:
    """Opening and verifying the Meshtastic panel."""

    def test_open_mesh_panel(self, page, take_screenshot):
        """Pressing 5 should open the Meshtastic panel."""
        panel = page.locator('[data-panel-id="mesh"]')
        if panel.count() > 0 and panel.is_visible():
            page.keyboard.press('5')
            page.wait_for_timeout(500)

        page.keyboard.press('5')
        page.wait_for_timeout(500)
        assert_panel_visible(page, 'mesh')
        take_screenshot(page, 'mesh-panel-open')

    def test_mesh_panel_title(self, page, take_screenshot):
        """Meshtastic panel should have title MESHTASTIC."""
        _open_mesh(page)

        title = page.locator('[data-panel-id="mesh"] .panel-title')
        assert 'MESHTASTIC' in title.text_content(), \
            "Panel title should contain MESHTASTIC"
        take_screenshot(page, 'mesh-panel-title')


class TestMeshTabs:
    """Tab navigation within the Meshtastic panel."""

    def test_tabs_exist(self, page, take_screenshot):
        """Panel should have Nodes, Chat, Radio, Scan tabs."""
        _open_mesh(page)

        for tab_name in ['nodes', 'chat', 'radio', 'scan']:
            tab = page.locator(
                f'[data-panel-id="mesh"] .mesh-tab[data-tab="{tab_name}"]'
            )
            assert tab.count() > 0, f"Tab '{tab_name}' should exist"
        take_screenshot(page, 'mesh-tabs')

    def test_switch_to_chat_tab(self, page, take_screenshot):
        """Clicking Chat tab should show the chat pane."""
        _open_mesh(page)
        _switch_tab(page, 'chat')

        chat_pane = page.locator('[data-panel-id="mesh"] [data-pane="chat"]')
        assert chat_pane.is_visible(), "Chat pane should be visible"
        take_screenshot(page, 'mesh-tab-chat')

    def test_switch_to_radio_tab(self, page, take_screenshot):
        """Clicking Radio tab should show the radio pane."""
        _open_mesh(page)
        _switch_tab(page, 'radio')

        radio_pane = page.locator('[data-panel-id="mesh"] [data-pane="radio"]')
        assert radio_pane.is_visible(), "Radio pane should be visible"
        take_screenshot(page, 'mesh-tab-radio')

    def test_switch_to_scan_tab(self, page, take_screenshot):
        """Clicking Scan tab should show the scan pane."""
        _open_mesh(page)
        _switch_tab(page, 'scan')

        scan_pane = page.locator('[data-panel-id="mesh"] [data-pane="scan"]')
        assert scan_pane.is_visible(), "Scan pane should be visible"

        # Verify SCAN button exists
        scan_btn = page.locator('[data-panel-id="mesh"] [data-action="scan"]')
        assert scan_btn.count() > 0, "SCAN button should exist"
        take_screenshot(page, 'mesh-tab-scan')

    def test_switch_back_to_nodes(self, page, take_screenshot):
        """Switching to Chat then back to Nodes should work."""
        _open_mesh(page)
        _switch_tab(page, 'chat')
        _switch_tab(page, 'nodes')

        nodes_pane = page.locator('[data-panel-id="mesh"] [data-pane="nodes"]')
        assert nodes_pane.is_visible(), "Nodes pane should be visible"
        take_screenshot(page, 'mesh-tab-nodes-back')


class TestMeshPanelStructure:
    """Meshtastic panel internal structure."""

    def test_mesh_status_bar(self, page, take_screenshot):
        """Panel should have a status bar showing connection state."""
        _open_mesh(page)

        status_label = page.locator(
            '[data-panel-id="mesh"] [data-bind="status-label"]'
        )
        assert status_label.is_visible(), "Status label should be visible"
        status_text = status_label.text_content()
        assert status_text in ('DISCONNECTED', 'CONNECTED'), \
            f"Status should be DISCONNECTED or CONNECTED, got: {status_text}"
        take_screenshot(page, 'mesh-status-bar')

    def test_mesh_node_list(self, page, take_screenshot):
        """Panel should have a node list in the Nodes tab."""
        _open_mesh(page)
        _switch_tab(page, 'nodes')

        node_list = page.locator('[data-panel-id="mesh"] [data-bind="node-list"]')
        assert node_list.count() > 0, "Node list should exist in DOM"
        take_screenshot(page, 'mesh-node-list')

    def test_mesh_chat_area(self, page, take_screenshot):
        """Chat tab should have a messages area."""
        _open_mesh(page)
        _switch_tab(page, 'chat')

        messages = page.locator('[data-panel-id="mesh"] [data-bind="messages"]')
        assert messages.count() > 0, "Chat messages area should exist in DOM"
        take_screenshot(page, 'mesh-chat-area')

    def test_mesh_chat_input(self, page, take_screenshot):
        """Chat tab should have an input with char counter and send button."""
        _open_mesh(page)
        _switch_tab(page, 'chat')

        chat_input = page.locator('[data-panel-id="mesh"] [data-bind="input"]')
        assert chat_input.is_visible(), "Chat input should be visible"

        char_count = page.locator('[data-panel-id="mesh"] [data-bind="char-count"]')
        assert char_count.is_visible(), "Char counter should be visible"
        assert char_count.text_content().strip() == '228', \
            "Char counter should show 228"

        send_btn = page.locator('[data-panel-id="mesh"] [data-action="send"]')
        assert send_btn.is_visible(), "SEND button should be visible"
        take_screenshot(page, 'mesh-chat-input')


class TestMeshChatInteraction:
    """Interacting with the Meshtastic chat input."""

    def test_char_counter_updates(self, page, take_screenshot):
        """Typing in the input should update the char counter."""
        _open_mesh(page)
        _switch_tab(page, 'chat')

        chat_input = page.locator('[data-panel-id="mesh"] [data-bind="input"]')
        char_count = page.locator('[data-panel-id="mesh"] [data-bind="char-count"]')

        chat_input.click()
        page.wait_for_timeout(200)

        chat_input.fill('Hello mesh')
        page.wait_for_timeout(300)

        remaining = int(char_count.text_content().strip())
        assert remaining == 228 - len('Hello mesh'), \
            f"Char counter should show {228 - len('Hello mesh')}, got {remaining}"
        take_screenshot(page, 'mesh-char-counter-update')

    def test_mesh_node_count(self, page, take_screenshot):
        """Node count indicator should show a number."""
        _open_mesh(page)

        node_count = page.locator('[data-panel-id="mesh"] [data-bind="node-count"]')
        assert node_count.is_visible(), "Node count should be visible"
        text = node_count.text_content().strip()
        assert 'nodes' in text, f"Node count should contain 'nodes', got: {text}"
        take_screenshot(page, 'mesh-node-count')

    def test_mesh_msg_count(self, page, take_screenshot):
        """Message count indicator should show a number."""
        _open_mesh(page)

        msg_count = page.locator('[data-panel-id="mesh"] [data-bind="msg-count"]')
        assert msg_count.is_visible(), "Message count should be visible"
        text = msg_count.text_content().strip()
        assert 'msgs' in text, f"Message count should contain 'msgs', got: {text}"
        take_screenshot(page, 'mesh-msg-count')


class TestMeshPanelClose:
    """Closing the Meshtastic panel."""

    def test_close_mesh_panel(self, page, take_screenshot):
        """Pressing 5 should toggle the mesh panel closed."""
        _open_mesh(page)
        assert_panel_visible(page, 'mesh')
        page.keyboard.press('5')
        page.wait_for_timeout(500)
        assert_panel_hidden(page, 'mesh')
        take_screenshot(page, 'mesh-panel-closed')
