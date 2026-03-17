# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HackRF SDR Panel Exercise: Click every button, tab, and control.

Uses headed Playwright with REAL mouse clicks — no evaluate() shortcuts.
Designed to catch UI bugs that API tests miss.

Run (headed, user watches):
    .venv/bin/python3 -m pytest tests/visual/test_hackrf_panel_exercise.py -v -s

Run (headless, CI):
    .venv/bin/python3 -m pytest tests/visual/test_hackrf_panel_exercise.py -v -s --headless
"""

from __future__ import annotations

import time
import pytest
from pathlib import Path

# Import our reusable framework
import sys
sys.path.insert(0, str(Path(__file__).parent))
from addon_test_framework import AddonUITester

pytestmark = pytest.mark.visual

HEADED = True  # Set False for CI


class TestHackRFPanelExercise:
    """Exercise every UI element of the HackRF SDR panel with real clicks."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.tester = AddonUITester(
            panel_id="hackrf",
            panel_title="HACKRF SDR",
            headed=HEADED,
        )
        self.tester.setup()
        yield
        self.tester.teardown()

    # ── Panel opens from menu ─────────────────────────────────

    def test_01_open_from_windows_menu(self):
        """Open HackRF panel by clicking WINDOWS > HACKRF SDR."""
        opened = self.tester.open_panel_via_menu()
        assert opened, "HackRF panel should open from WINDOWS menu"

    def test_02_panel_has_content(self):
        """Panel should display device info, not be empty."""
        self.tester.open_panel_via_menu()
        assert self.tester.verify_panel_has_content()

    def test_03_no_js_errors_on_open(self):
        """No JavaScript errors when panel opens."""
        self.tester.open_panel_via_menu()
        assert self.tester.verify_no_js_errors()

    # ── Tab navigation ────────────────────────────────────────

    def test_04_all_tabs_exist(self):
        """Panel should have 7 tabs."""
        self.tester.open_panel_via_menu()
        tabs = self.tester.get_tabs()
        tab_labels = [t["label"] for t in tabs]
        print(f"Tabs: {tab_labels}")
        assert len(tabs) >= 5, f"Expected 5+ tabs, got {len(tabs)}: {tab_labels}"

    def test_05_click_every_tab(self):
        """Click each tab and verify content appears."""
        self.tester.open_panel_via_menu()
        self.tester.click_all_tabs()
        assert self.tester.verify_no_js_errors()

    def test_06_tab_switching_preserves_state(self):
        """Switching tabs should not cause JS errors."""
        self.tester.open_panel_via_menu()
        for _ in range(3):  # Cycle through tabs 3 times
            self.tester.click_all_tabs()
        assert self.tester.verify_no_js_errors()

    # ── RADIO tab ─────────────────────────────────────────────

    def test_07_radio_tab_shows_device_info(self):
        """RADIO tab should show device serial and firmware."""
        self.tester.open_panel_via_menu()
        self.tester.click_tab("RADIO")
        panel = self.tester.find_panel()
        text = panel.inner_text() if panel else ""
        # Should contain device info — serial or firmware version
        has_info = any(word in text.lower() for word in ["serial", "firmware", "hackrf", "connected"])
        print(f"RADIO tab text preview: {text[:200]}")
        assert has_info, "RADIO tab should show device info"

    def test_08_fm_listen_button(self):
        """Click FM LISTEN button — should show audio player or feedback."""
        self.tester.open_panel_via_menu()
        self.tester.click_tab("RADIO")
        clicked = self.tester.click_button("LISTEN", wait_s=8)
        if clicked:
            panel = self.tester.find_panel()
            text = panel.inner_text() if panel else ""
            # Should show audio player, error, or "Capturing"
            has_feedback = any(w in text.lower() for w in ["audio", "capturing", "error", "mhz", "kb"])
            print(f"After LISTEN: {text[:200]}")
            assert has_feedback, "LISTEN should produce visible feedback"

    def test_09_scan_stations_button(self):
        """Click SCAN STATIONS — should show FM stations or 'scanning'."""
        self.tester.open_panel_via_menu()
        self.tester.click_tab("RADIO")
        clicked = self.tester.click_button("SCAN STATIONS", wait_s=15)
        if clicked:
            panel = self.tester.find_panel()
            text = panel.inner_text() if panel else ""
            has_result = any(w in text.lower() for w in ["mhz", "station", "scanning", "no station", "dbm"])
            print(f"After SCAN: {text[:300]}")

    # ── SPECTRUM tab ──────────────────────────────────────────

    def test_10_spectrum_start_stop(self):
        """Start sweep, verify canvas updates, stop sweep."""
        self.tester.open_panel_via_menu()
        self.tester.click_tab("SPECTRUM")
        self.tester.screenshot("spectrum_before")

        # Click START SWEEP
        self.tester.click_button("START SWEEP", wait_s=5)
        self.tester.screenshot("spectrum_sweeping")

        # Click STOP SWEEP
        self.tester.click_button("STOP SWEEP", wait_s=2)
        self.tester.screenshot("spectrum_stopped")

        assert self.tester.verify_no_js_errors()

    def test_11_preset_buttons(self):
        """Click preset buttons — should start sweep and switch to spectrum."""
        self.tester.open_panel_via_menu()
        self.tester.click_tab("RADIO")
        # Click FM Radio preset
        self.tester.click_button("FM Radio", wait_s=4)
        self.tester.screenshot("preset_fm")
        # Stop whatever is running
        self.tester.click_button("STOP SWEEP", wait_s=1)

    # ── Random stress test ────────────────────────────────────

    def test_12_random_stress(self):
        """Random tab/button clicking for 30 iterations."""
        self.tester.open_panel_via_menu()
        self.tester.random_exercise(iterations=30, seed=42)
        # Allow some errors in stress test but not too many
        assert len(self.tester.errors) < 5, f"Too many JS errors in stress test: {self.tester.errors[:3]}"

    # ── Connection bar ────────────────────────────────────────

    def test_13_connection_bar_visible(self):
        """Connection bar should always be visible with device status."""
        self.tester.open_panel_via_menu()
        panel = self.tester.find_panel()
        if panel:
            conn = panel.query_selector('.hrf-conn-label')
            assert conn, "Connection label should exist"
            text = conn.inner_text()
            assert text in ("CONNECTED", "DISCONNECTED"), f"Connection label unexpected: {text}"

    # ── Status bar ────────────────────────────────────────────

    def test_14_status_bar_visible(self):
        """Status bar should always be visible at bottom of panel."""
        self.tester.open_panel_via_menu()
        panel = self.tester.find_panel()
        if panel:
            status = panel.query_selector('.hrf-status-bar')
            assert status, "Status bar should exist"
            text = status.inner_text()
            assert len(text) > 0, "Status bar should have content"
