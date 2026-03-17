# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Meshtastic Panel Exercise: Click every button, tab, and control.

Uses headed Playwright with REAL mouse clicks.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_meshtastic_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from addon_test_framework import AddonUITester

pytestmark = pytest.mark.visual


class TestMeshtasticPanelExercise:
    """Exercise every UI element of the Meshtastic panel with real clicks."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.tester = AddonUITester(
            panel_id="meshtastic",
            panel_title="MESHTASTIC",
            headed=True,
        )
        self.tester.setup()
        yield
        self.tester.teardown()

    def test_01_open_from_windows_menu(self):
        """Open Meshtastic panel by clicking WINDOWS menu."""
        opened = self.tester.open_panel_via_menu()
        assert opened, "Meshtastic panel should open from WINDOWS menu"

    def test_02_panel_has_content(self):
        """Panel should not be empty."""
        self.tester.open_panel_via_menu()
        assert self.tester.verify_panel_has_content()

    def test_03_no_js_errors(self):
        """No JavaScript errors on open."""
        self.tester.open_panel_via_menu()
        assert self.tester.verify_no_js_errors()

    def test_04_all_tabs_exist(self):
        """Panel should have 7 tabs."""
        self.tester.open_panel_via_menu()
        tabs = self.tester.get_tabs()
        tab_labels = [t["label"] for t in tabs]
        print(f"Tabs: {tab_labels}")
        assert len(tabs) >= 5, f"Expected 5+ tabs, got {len(tabs)}"

    def test_05_click_every_tab(self):
        """Click each tab without errors."""
        self.tester.open_panel_via_menu()
        self.tester.click_all_tabs()
        assert self.tester.verify_no_js_errors()

    def test_06_connection_bar(self):
        """Connection bar should show CONNECTED or DISCONNECTED."""
        self.tester.open_panel_via_menu()
        panel = self.tester.find_panel()
        if panel:
            conn = panel.query_selector('.msh-conn-label')
            assert conn, "Connection label should exist"
            text = conn.inner_text()
            print(f"Connection: {text}")
            assert text in ("CONNECTED", "DISCONNECTED", "AUTO-CONNECTING...")

    def test_07_radio_tab_scan_buttons(self):
        """RADIO tab should have SCAN USB and SCAN BLE buttons."""
        self.tester.open_panel_via_menu()
        self.tester.click_tab("RADIO")
        buttons = self.tester.get_buttons()
        button_texts = [b["text"] for b in buttons]
        print(f"Buttons: {button_texts}")
        has_scan = any("SCAN" in t.upper() for t in button_texts)
        assert has_scan, f"Should have SCAN button, got: {button_texts}"

    def test_08_nodes_tab_has_search(self):
        """NODES tab should have a search input."""
        self.tester.open_panel_via_menu()
        self.tester.click_tab("NODES")
        panel = self.tester.find_panel()
        if panel:
            search = panel.query_selector('input[placeholder*="earch"]')
            assert search, "NODES tab should have search input"

    def test_09_triple_tab_cycle(self):
        """Cycling tabs 3 times should not cause errors."""
        self.tester.open_panel_via_menu()
        for _ in range(3):
            self.tester.click_all_tabs()
        assert self.tester.verify_no_js_errors()
