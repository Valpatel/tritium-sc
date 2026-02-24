"""Batch 11 panel feature tests.

Verifies Amy enhanced features (mode, auto-chat, nodes, memory, photos),
System panel tabs and telemetry metrics, Search/Intel panel tabs and detail,
Mesh panel tabs and chat functionality.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch11_panels.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.lib.server_manager import TritiumServer

pytestmark = [pytest.mark.ux, pytest.mark.ui]


@pytest.fixture(scope="module")
def _server():
    """Module-scoped server to avoid per-test restarts."""
    srv = TritiumServer(auto_port=True)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def _browser(_server):
    """Module-scoped browser."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()
    pw.stop()


@pytest.fixture(scope="module")
def _ctx(_browser, _server):
    """Module-scoped browser context — single page for all tests."""
    ctx = _browser.new_context(viewport={"width": 1920, "height": 1080})
    p = ctx.new_page()
    p.goto(f"{_server.url}/", wait_until="domcontentloaded", timeout=60000)
    try:
        p.wait_for_function(
            "() => window.TritiumStore && window.TritiumStore.units.size >= 3",
            timeout=15000,
        )
    except Exception:
        pass
    p.wait_for_timeout(1000)
    yield {"page": p, "url": _server.url}
    ctx.close()


@pytest.fixture
def page(_ctx):
    """Per-test fixture: yields the shared page, closes any open panels after."""
    p = _ctx["page"]
    yield p
    # Clean up: press Escape to close overlays
    p.keyboard.press('Escape')
    p.wait_for_timeout(200)


import os
SCREENSHOT_DIR = os.path.join(
    os.path.dirname(__file__), '..', '.test-results', 'screenshots'
)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


@pytest.fixture
def take_screenshot():
    def _take(page, name):
        path = os.path.join(SCREENSHOT_DIR, f'{name}.png')
        page.screenshot(path=path)
        return path
    return _take


# ── Amy Panel Enhanced Features ──────────────────────────────────────


class TestAmyPanelEnhanced:
    """Amy panel: mode indicator, auto-chat, sensor nodes, memory, photos."""

    def _open_amy(self, page):
        panel = page.locator('[data-panel-id="amy"]')
        if panel.count() == 0 or not panel.is_visible():
            page.keyboard.press('1')
            page.wait_for_timeout(500)

    def _close_amy(self, page):
        panel = page.locator('[data-panel-id="amy"]')
        if panel.count() > 0 and panel.is_visible():
            page.keyboard.press('1')
            page.wait_for_timeout(300)

    def test_mode_indicator_exists(self, page, take_screenshot):
        """Amy panel should have a SIM/LIVE mode indicator."""
        self._open_amy(page)
        mode = page.locator('[data-bind="mode-indicator"]')
        assert mode.count() > 0, "Mode indicator element missing"
        label = page.locator('[data-bind="mode-label"]')
        text = label.text_content()
        assert text in ('SIM', 'LIVE'), f"Mode should be SIM or LIVE, got: '{text}'"
        take_screenshot(page, 'amy-mode-indicator')
        self._close_amy(page)

    def test_mode_indicator_has_dot(self, page):
        """Mode indicator should have a colored dot."""
        self._open_amy(page)
        dot = page.locator('[data-bind="mode-indicator"] .panel-dot')
        assert dot.count() > 0, "Mode indicator should have a dot"
        self._close_amy(page)

    def test_mode_label_clickable(self, page):
        """Mode label should have cursor pointer (click toggles mode)."""
        self._open_amy(page)
        label = page.locator('[data-bind="mode-label"]')
        cursor = label.evaluate("el => getComputedStyle(el).cursor")
        assert cursor == 'pointer', f"Mode label cursor should be 'pointer', got: '{cursor}'"
        self._close_amy(page)

    def test_auto_chat_toggle_exists(self, page, take_screenshot):
        """Amy panel should have an AUTO-CHAT checkbox toggle."""
        self._open_amy(page)
        toggle = page.locator('[data-bind="auto-chat-toggle"]')
        assert toggle.count() > 0, "Auto-chat toggle missing"
        assert toggle.get_attribute('type') == 'checkbox', "Toggle should be a checkbox"
        take_screenshot(page, 'amy-auto-chat-toggle')
        self._close_amy(page)

    def test_sensor_nodes_section_exists(self, page, take_screenshot):
        """Amy panel should have a SENSOR NODES section."""
        self._open_amy(page)
        nodes = page.locator('[data-bind="nodes"]')
        assert nodes.count() > 0, "Sensor nodes container missing"
        content = nodes.text_content()
        assert len(content) > 0, "Nodes section should have content"
        take_screenshot(page, 'amy-sensor-nodes')
        self._close_amy(page)

    def test_memory_section_exists(self, page):
        """Amy panel should have a MEMORY section."""
        self._open_amy(page)
        mem = page.locator('[data-bind="memory"]')
        assert mem.count() > 0, "Memory section missing"
        content = mem.text_content()
        assert len(content) > 0, "Memory section should have content"
        self._close_amy(page)

    def test_photos_section_exists(self, page):
        """Amy panel should have a PHOTOS section."""
        self._open_amy(page)
        photos = page.locator('[data-bind="photos"]')
        assert photos.count() > 0, "Photos section missing"
        content = photos.text_content()
        assert len(content) > 0, "Photos section should have content"
        self._close_amy(page)

    def test_speak_bar_hidden_by_default(self, page):
        """Speak bar should be hidden until SPEAK button clicked."""
        self._open_amy(page)
        bar = page.locator('[data-bind="speak-bar"]')
        assert bar.count() > 0, "Speak bar element missing"
        display = bar.evaluate("el => el.style.display")
        assert display == 'none', f"Speak bar should be hidden, display: '{display}'"
        self._close_amy(page)

    def test_speak_button_toggles_bar(self, page, take_screenshot):
        """Clicking SPEAK should show the speak input bar."""
        self._open_amy(page)
        page.evaluate("""
            const btn = document.querySelector('[data-panel-id="amy"] [data-action="speak"]');
            if (btn) btn.click();
        """)
        page.wait_for_timeout(300)
        bar = page.locator('[data-bind="speak-bar"]')
        display = bar.evaluate("el => el.style.display")
        assert display != 'none', "Speak bar should be visible after clicking SPEAK"
        take_screenshot(page, 'amy-speak-bar-open')
        # Close speak bar
        page.evaluate("""
            const btn = document.querySelector('[data-panel-id="amy"] [data-action="speak"]');
            if (btn) btn.click();
        """)
        page.wait_for_timeout(200)
        self._close_amy(page)

    def test_quick_action_buttons_exist(self, page):
        """Amy panel should have SCAN, PATROL, STAND DOWN, REPORT buttons."""
        self._open_amy(page)
        for cmd in ['scan_area', 'patrol_all', 'stand_down', 'report']:
            btn = page.locator(f'[data-panel-id="amy"] [data-cmd="{cmd}"]')
            assert btn.count() > 0, f"Quick action button '{cmd}' missing"
        self._close_amy(page)

    def test_command_input_exists(self, page):
        """Amy panel should have a Lua command input bar."""
        self._open_amy(page)
        cmd_input = page.locator('[data-bind="cmd-input"]')
        assert cmd_input.count() > 0, "Command input missing"
        placeholder = cmd_input.get_attribute('placeholder')
        assert 'Lua' in placeholder or 'command' in placeholder.lower(), \
            f"Command input placeholder should mention Lua/command, got: '{placeholder}'"
        self._close_amy(page)

    def test_command_go_button_exists(self, page):
        """Amy panel should have a GO button for command submission."""
        self._open_amy(page)
        btn = page.locator('[data-panel-id="amy"] [data-action="send-cmd"]')
        assert btn.count() > 0, "GO button missing"
        assert 'GO' in btn.text_content(), "Button should say GO"
        self._close_amy(page)


# ── System Panel Tabs & Metrics ──────────────────────────────────────


class TestSystemPanelTabs:
    """System panel: tabs, telemetry metrics, perf, AI status."""

    def _open_system(self, page):
        panel = page.locator('[data-panel-id="system"]')
        if panel.count() == 0 or not panel.is_visible():
            page.keyboard.press('u')
            page.wait_for_timeout(500)

    def _close_system(self, page):
        panel = page.locator('[data-panel-id="system"]')
        if panel.count() > 0 and panel.is_visible():
            page.keyboard.press('u')
            page.wait_for_timeout(300)

    def test_system_panel_has_five_tabs(self, page, take_screenshot):
        """System panel should have CAMERAS, DISCOVERY, TELEMETRY, PERF, AI tabs."""
        self._open_system(page)
        tabs = page.locator('[data-panel-id="system"] .sys-tab')
        assert tabs.count() == 5, f"Expected 5 tabs, got {tabs.count()}"
        labels = [tabs.nth(i).text_content() for i in range(5)]
        assert 'CAMERAS' in labels
        assert 'DISCOVERY' in labels
        assert 'TELEMETRY' in labels
        assert 'PERF' in labels
        assert 'AI' in labels
        take_screenshot(page, 'system-panel-tabs')
        self._close_system(page)

    def test_cameras_tab_active_by_default(self, page):
        """CAMERAS tab should be active by default."""
        self._open_system(page)
        active = page.locator('[data-panel-id="system"] .sys-tab.active')
        text = active.text_content()
        assert 'CAMERAS' in text, f"Active tab should be CAMERAS, got: '{text}'"
        self._close_system(page)

    def test_click_telemetry_tab(self, page, take_screenshot):
        """Clicking TELEMETRY tab should show telemetry pane."""
        self._open_system(page)
        page.locator('[data-panel-id="system"] .sys-tab[data-tab="telemetry"]').click()
        page.wait_for_timeout(500)
        pane = page.locator('[data-pane="telemetry"]')
        display = pane.evaluate("el => el.style.display")
        assert display != 'none', "Telemetry pane should be visible"
        take_screenshot(page, 'system-telemetry-tab')
        self._close_system(page)

    def test_click_perf_tab_shows_metrics(self, page, take_screenshot):
        """Clicking PERF tab should show FPS, units, panels metrics."""
        self._open_system(page)
        page.locator('[data-panel-id="system"] .sys-tab[data-tab="perf"]').click()
        page.wait_for_timeout(500)
        fps = page.locator('[data-bind="perf-fps"]')
        assert fps.count() > 0, "FPS metric element missing"
        units = page.locator('[data-bind="perf-units"]')
        assert units.count() > 0, "Units metric element missing"
        panels = page.locator('[data-bind="perf-panels"]')
        assert panels.count() > 0, "Panels metric element missing"
        take_screenshot(page, 'system-perf-tab')
        self._close_system(page)

    def test_perf_fps_sparkline_canvas(self, page):
        """PERF tab should have an FPS sparkline canvas."""
        self._open_system(page)
        page.locator('[data-panel-id="system"] .sys-tab[data-tab="perf"]').click()
        page.wait_for_timeout(300)
        canvas = page.locator('[data-bind="fps-sparkline"]')
        assert canvas.count() > 0, "FPS sparkline canvas missing"
        tag = canvas.evaluate("el => el.tagName.toLowerCase()")
        assert tag == 'canvas', f"Sparkline should be a canvas, got: {tag}"
        self._close_system(page)

    def test_perf_fps_shows_number(self, page):
        """FPS metric should show a number, not '--'."""
        self._open_system(page)
        page.locator('[data-panel-id="system"] .sys-tab[data-tab="perf"]').click()
        page.wait_for_timeout(2500)
        fps = page.locator('[data-bind="perf-fps"]')
        text = fps.text_content()
        assert text != '--', f"FPS should update from '--', got: '{text}'"
        self._close_system(page)

    def test_click_ai_tab(self, page, take_screenshot):
        """Clicking AI tab should show AI status content."""
        self._open_system(page)
        page.locator('[data-panel-id="system"] .sys-tab[data-tab="ai"]').click()
        page.wait_for_timeout(500)
        content = page.locator('[data-bind="ai-content"]')
        assert content.count() > 0, "AI content container missing"
        take_screenshot(page, 'system-ai-tab')
        self._close_system(page)

    def test_discovery_tab_has_scan_button(self, page):
        """DISCOVERY tab should have a SCAN NVR button."""
        self._open_system(page)
        page.locator('[data-panel-id="system"] .sys-tab[data-tab="discovery"]').click()
        page.wait_for_timeout(300)
        btn = page.locator('[data-action="scan-nvr"]')
        assert btn.count() > 0, "SCAN NVR button missing"
        self._close_system(page)


# ── Search/Intel Panel ───────────────────────────────────────────────


class TestSearchPanelFeatures:
    """Search/Intel panel: tabs, search bar, detail structure."""

    def _open_search(self, page):
        panel = page.locator('[data-panel-id="search"]')
        if panel.count() == 0 or not panel.is_visible():
            page.keyboard.press('0')
            page.wait_for_timeout(500)

    def _close_search(self, page):
        panel = page.locator('[data-panel-id="search"]')
        if panel.count() > 0 and panel.is_visible():
            page.keyboard.press('0')
            page.wait_for_timeout(300)

    def test_search_panel_has_four_tabs(self, page, take_screenshot):
        """Search panel should have PEOPLE, VEHICLES, FLAGGED, TRENDS tabs."""
        self._open_search(page)
        tabs = page.locator('[data-panel-id="search"] .search-tab')
        assert tabs.count() == 4, f"Expected 4 tabs, got {tabs.count()}"
        labels = [tabs.nth(i).text_content() for i in range(4)]
        assert 'PEOPLE' in labels
        assert 'VEHICLES' in labels
        assert 'FLAGGED' in labels
        assert 'TRENDS' in labels
        take_screenshot(page, 'search-panel-tabs')
        self._close_search(page)

    def test_people_tab_active_by_default(self, page):
        """PEOPLE tab should be active by default."""
        self._open_search(page)
        active = page.locator('[data-panel-id="search"] .search-tab.active')
        assert active.text_content() == 'PEOPLE', "PEOPLE tab should be active by default"
        self._close_search(page)

    def test_search_input_exists(self, page):
        """Search panel should have a text search input."""
        self._open_search(page)
        inp = page.locator('[data-bind="search-input"]')
        assert inp.count() > 0, "Search input missing"
        self._close_search(page)

    def test_search_button_exists(self, page):
        """Search panel should have a SEARCH button."""
        self._open_search(page)
        btn = page.locator('[data-action="text-search"]')
        assert btn.count() > 0, "SEARCH button missing"
        assert 'SEARCH' in btn.text_content(), "Button should say SEARCH"
        self._close_search(page)

    def test_click_vehicles_tab(self, page, take_screenshot):
        """Clicking VEHICLES tab should show vehicles pane."""
        self._open_search(page)
        page.locator('[data-panel-id="search"] .search-tab[data-tab="vehicles"]').click()
        page.wait_for_timeout(300)
        pane = page.locator('[data-pane="vehicles"]')
        display = pane.evaluate("el => el.style.display")
        assert display != 'none', "Vehicles pane should be visible"
        take_screenshot(page, 'search-vehicles-tab')
        self._close_search(page)

    def test_click_trends_tab(self, page, take_screenshot):
        """Clicking TRENDS tab should show trends pane."""
        self._open_search(page)
        page.locator('[data-panel-id="search"] .search-tab[data-tab="trends"]').click()
        page.wait_for_timeout(300)
        pane = page.locator('[data-pane="trends"]')
        display = pane.evaluate("el => el.style.display")
        assert display != 'none', "Trends pane should be visible"
        take_screenshot(page, 'search-trends-tab')
        self._close_search(page)

    def test_detail_hidden_by_default(self, page):
        """Detail view should be hidden by default."""
        self._open_search(page)
        detail = page.locator('[data-panel-id="search"] [data-bind="detail"]')
        assert detail.count() > 0, "Detail container missing"
        display = detail.evaluate("el => el.style.display")
        assert display == 'none', f"Detail should be hidden by default, display: '{display}'"
        self._close_search(page)

    def test_people_list_exists(self, page):
        """People list should exist and have content or empty message."""
        self._open_search(page)
        plist = page.locator('[data-bind="people-list"]')
        assert plist.count() > 0, "People list missing"
        content = plist.text_content()
        assert len(content) > 0, "People list should have content"
        self._close_search(page)


# ── Mesh Panel ───────────────────────────────────────────────────────


class TestMeshPanelFeatures:
    """Mesh panel: tabs, chat, radio, scan, status bar."""

    def _open_mesh(self, page):
        panel = page.locator('[data-panel-id="mesh"]')
        if panel.count() == 0 or not panel.is_visible():
            page.keyboard.press('5')
            page.wait_for_timeout(500)

    def _close_mesh(self, page):
        panel = page.locator('[data-panel-id="mesh"]')
        if panel.count() > 0 and panel.is_visible():
            page.keyboard.press('5')
            page.wait_for_timeout(300)

    def test_mesh_panel_has_four_tabs(self, page, take_screenshot):
        """Mesh panel should have Nodes, Chat, Radio, Scan tabs."""
        self._open_mesh(page)
        tabs = page.locator('[data-panel-id="mesh"] .mesh-tab')
        assert tabs.count() == 4, f"Expected 4 tabs, got {tabs.count()}"
        labels = [tabs.nth(i).text_content() for i in range(4)]
        assert 'Nodes' in labels
        assert 'Chat' in labels
        assert 'Radio' in labels
        assert 'Scan' in labels
        take_screenshot(page, 'mesh-panel-tabs')
        self._close_mesh(page)

    def test_nodes_tab_active_by_default(self, page):
        """Nodes tab should be active by default."""
        self._open_mesh(page)
        active = page.locator('[data-panel-id="mesh"] .mesh-tab.active')
        assert active.text_content() == 'Nodes', "Nodes tab should be active by default"
        self._close_mesh(page)

    def test_status_bar_exists(self, page):
        """Mesh panel should have a status bar with node/msg counts."""
        self._open_mesh(page)
        status = page.locator('[data-bind="status-label"]')
        assert status.count() > 0, "Status label missing"
        node_count = page.locator('[data-bind="node-count"]')
        assert node_count.count() > 0, "Node count element missing"
        msg_count = page.locator('[data-bind="msg-count"]')
        assert msg_count.count() > 0, "Message count element missing"
        self._close_mesh(page)

    def test_click_chat_tab_shows_input(self, page, take_screenshot):
        """Clicking Chat tab should show chat input."""
        self._open_mesh(page)
        page.locator('[data-panel-id="mesh"] .mesh-tab[data-tab="chat"]').click()
        page.wait_for_timeout(300)
        inp = page.locator('[data-panel-id="mesh"] [data-bind="input"]')
        assert inp.is_visible(), "Chat input should be visible"
        take_screenshot(page, 'mesh-chat-tab')
        self._close_mesh(page)

    def test_chat_input_has_char_counter(self, page):
        """Chat input should have a character counter showing 228."""
        self._open_mesh(page)
        page.locator('[data-panel-id="mesh"] .mesh-tab[data-tab="chat"]').click()
        page.wait_for_timeout(300)
        counter = page.locator('[data-bind="char-count"]')
        assert counter.count() > 0, "Char counter missing"
        text = counter.text_content()
        assert text == '228', f"Char counter should show 228, got: '{text}'"
        self._close_mesh(page)

    def test_chat_send_button_exists(self, page):
        """Chat tab should have a SEND button."""
        self._open_mesh(page)
        page.locator('[data-panel-id="mesh"] .mesh-tab[data-tab="chat"]').click()
        page.wait_for_timeout(300)
        btn = page.locator('[data-panel-id="mesh"] [data-action="send"]')
        assert btn.count() > 0, "SEND button missing"
        assert 'SEND' in btn.text_content(), "Button should say SEND"
        self._close_mesh(page)

    def test_chat_channel_select_exists(self, page):
        """Chat tab should have a channel selector."""
        self._open_mesh(page)
        page.locator('[data-panel-id="mesh"] .mesh-tab[data-tab="chat"]').click()
        page.wait_for_timeout(300)
        sel = page.locator('[data-bind="channel-select"]')
        assert sel.count() > 0, "Channel selector missing"
        tag = sel.evaluate("el => el.tagName.toLowerCase()")
        assert tag == 'select', f"Channel selector should be a <select>, got: {tag}"
        self._close_mesh(page)

    def test_click_radio_tab(self, page, take_screenshot):
        """Clicking Radio tab should show connect/disconnect controls."""
        self._open_mesh(page)
        page.locator('[data-panel-id="mesh"] .mesh-tab[data-tab="radio"]').click()
        page.wait_for_timeout(300)
        connect_btn = page.locator('[data-action="connect"]')
        assert connect_btn.is_visible(), "CONNECT button should be visible"
        disconnect_btn = page.locator('[data-action="disconnect"]')
        assert disconnect_btn.is_visible(), "DISCONNECT button should be visible"
        take_screenshot(page, 'mesh-radio-tab')
        self._close_mesh(page)

    def test_radio_host_input_exists(self, page):
        """Radio tab should have a host input field."""
        self._open_mesh(page)
        page.locator('[data-panel-id="mesh"] .mesh-tab[data-tab="radio"]').click()
        page.wait_for_timeout(300)
        host = page.locator('[data-bind="radio-host-input"]')
        assert host.count() > 0, "Radio host input missing"
        self._close_mesh(page)

    def test_click_scan_tab(self, page, take_screenshot):
        """Clicking Scan tab should show SCAN FOR DEVICES button."""
        self._open_mesh(page)
        page.locator('[data-panel-id="mesh"] .mesh-tab[data-tab="scan"]').click()
        page.wait_for_timeout(300)
        btn = page.locator('[data-action="scan"]')
        assert btn.is_visible(), "SCAN button should be visible"
        assert 'SCAN' in btn.text_content(), "Button should say SCAN"
        take_screenshot(page, 'mesh-scan-tab')
        self._close_mesh(page)

    def test_node_detail_hidden_by_default(self, page):
        """Node detail should be hidden until a node is clicked."""
        self._open_mesh(page)
        detail = page.locator('[data-bind="node-detail"]')
        assert detail.count() > 0, "Node detail container missing"
        display = detail.evaluate("el => el.style.display")
        assert display == 'none', f"Node detail should be hidden, display: '{display}'"
        self._close_mesh(page)
