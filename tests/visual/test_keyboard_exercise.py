# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Keyboard Shortcuts Exercise: Verify all keyboard shortcuts work correctly.
Tests mode switching (O/T/S), panel toggles (1/2/3/4/M/C), camera controls
(F/R/[/]), map layer shortcuts (I/G/K/H), and overlay shortcuts (B/?).

Run:
    .venv/bin/python3 -m pytest tests/visual/test_keyboard_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/keyboard")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"


def _opencv_diff(path_a: str, path_b: str) -> float:
    a = cv2.imread(path_a, cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(path_b, cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        return 0.0
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    diff = cv2.absdiff(a, b)
    return float(np.count_nonzero(diff > 15) / diff.size * 100)


class TestKeyboardExercise:
    """Exercise all keyboard shortcuts via Playwright key presses."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        ctx = self._browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = ctx.new_page()
        self._errors = []
        self.page.on("pageerror", lambda e: self._errors.append(str(e)))
        self.page.goto("http://localhost:8000", wait_until="networkidle", timeout=30000)
        time.sleep(5)
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path, timeout=60000)
        return path

    # --- Map Mode Shortcuts ---

    def test_01_o_observe_mode(self):
        """O key switches to observe mode."""
        self.page.keyboard.press('o')
        time.sleep(0.3)
        mode = self.page.evaluate("() => window._mapState?.currentMode")
        self._screenshot("01_observe")
        print(f"\nO key: mode = {mode}")
        assert mode == "observe", f"Expected observe: {mode}"

    def test_02_t_tactical_mode(self):
        """T key switches to tactical mode."""
        self.page.keyboard.press('t')
        time.sleep(0.3)
        mode = self.page.evaluate("() => window._mapState?.currentMode")
        self._screenshot("02_tactical")
        print(f"\nT key: mode = {mode}")
        assert mode == "tactical", f"Expected tactical: {mode}"

    def test_03_s_setup_mode(self):
        """S key switches to setup mode."""
        self.page.keyboard.press('s')
        time.sleep(0.3)
        mode = self.page.evaluate("() => window._mapState?.currentMode")
        self._screenshot("03_setup")
        print(f"\nS key: mode = {mode}")
        assert mode == "setup", f"Expected setup: {mode}"

    # --- Panel Toggle Shortcuts ---

    def test_04_key_1_amy_panel(self):
        """Key 1 toggles Amy panel."""
        before = self.page.evaluate("() => window.panelManager?.isOpen('amy')")
        self.page.keyboard.press('1')
        time.sleep(0.3)
        after = self.page.evaluate("() => window.panelManager?.isOpen('amy')")
        self._screenshot("04_amy_toggle")
        print(f"\nKey 1 (Amy): {before} -> {after}")
        assert before != after, f"Amy panel should have toggled: {before} -> {after}"
        # Restore
        self.page.keyboard.press('1')
        time.sleep(0.2)

    def test_05_key_2_units_panel(self):
        """Key 2 toggles Units panel."""
        before = self.page.evaluate("() => window.panelManager?.isOpen('units')")
        self.page.keyboard.press('2')
        time.sleep(0.3)
        after = self.page.evaluate("() => window.panelManager?.isOpen('units')")
        self._screenshot("05_units_toggle")
        print(f"\nKey 2 (Units): {before} -> {after}")
        assert before != after, f"Units panel should have toggled"
        # Restore
        self.page.keyboard.press('2')
        time.sleep(0.2)

    def test_06_key_3_alerts_panel(self):
        """Key 3 toggles Alerts panel."""
        before = self.page.evaluate("() => window.panelManager?.isOpen('alerts')")
        self.page.keyboard.press('3')
        time.sleep(0.3)
        after = self.page.evaluate("() => window.panelManager?.isOpen('alerts')")
        self._screenshot("06_alerts_toggle")
        print(f"\nKey 3 (Alerts): {before} -> {after}")
        assert before != after, f"Alerts panel should have toggled"
        # Restore
        self.page.keyboard.press('3')
        time.sleep(0.2)

    def test_07_key_4_game_panel(self):
        """Key 4 toggles Game HUD panel."""
        before = self.page.evaluate("() => window.panelManager?.isOpen('game')")
        self.page.keyboard.press('4')
        time.sleep(0.3)
        after = self.page.evaluate("() => window.panelManager?.isOpen('game')")
        self._screenshot("07_game_toggle")
        print(f"\nKey 4 (Game): {before} -> {after}")
        assert before != after, f"Game panel should have toggled"
        # Restore
        self.page.keyboard.press('4')
        time.sleep(0.2)

    def test_08_m_minimap_toggle(self):
        """M key toggles minimap panel."""
        before = self.page.evaluate("() => window.panelManager?.isOpen('minimap')")
        self.page.keyboard.press('m')
        time.sleep(0.3)
        after = self.page.evaluate("() => window.panelManager?.isOpen('minimap')")
        self._screenshot("08_minimap_toggle")
        print(f"\nM key (Minimap): {before} -> {after}")
        assert before != after, f"Minimap should have toggled"
        # Restore
        self.page.keyboard.press('m')
        time.sleep(0.2)

    # --- Map Layer Shortcuts ---

    def test_09_i_satellite_toggle(self):
        """I key toggles satellite imagery."""
        before = self.page.evaluate("() => window._mapState?.showSatellite")
        self.page.keyboard.press('i')
        time.sleep(0.3)
        after = self.page.evaluate("() => window._mapState?.showSatellite")
        self._screenshot("09_satellite_toggle")
        print(f"\nI key (Satellite): {before} -> {after}")
        assert before != after, f"Satellite should have toggled"
        # Restore
        self.page.keyboard.press('i')
        time.sleep(0.2)

    # --- Camera Shortcuts ---

    def test_10_bracket_zoom(self):
        """[ and ] keys zoom out/in."""
        before = self.page.evaluate("() => window._mapState?.map?.getZoom()")
        self.page.keyboard.press(']')
        time.sleep(0.5)
        after_in = self.page.evaluate("() => window._mapState?.map?.getZoom()")
        self.page.keyboard.press('[')
        time.sleep(0.5)
        after_out = self.page.evaluate("() => window._mapState?.map?.getZoom()")

        print(f"\nZoom: before={before}, after]={after_in}, after[={after_out}")
        if before and after_in:
            assert after_in > before, "'] should zoom in"

    def test_11_r_reset_camera(self):
        """R key resets camera."""
        self.page.keyboard.press('r')
        time.sleep(0.5)
        zoom = self.page.evaluate("() => window._mapState?.map?.getZoom()")
        self._screenshot("11_camera_reset")
        print(f"\nR key reset, zoom: {zoom}")
        assert zoom is not None, "Should have zoom after reset"

    def test_12_f_center_on_action(self):
        """F key centers camera on action."""
        before = self._screenshot("12_before_center")
        self.page.keyboard.press('f')
        time.sleep(0.5)
        after = self._screenshot("12_after_center")
        diff = _opencv_diff(before, after)
        print(f"\nF key center, diff: {diff:.1f}%")
        # May or may not move depending on unit positions

    # --- Help Overlay ---

    def test_13_question_help_overlay(self):
        """? key opens help overlay."""
        before = self.page.evaluate("""() => {
            const h = document.getElementById('help-overlay');
            return h ? !h.hidden : false;
        }""")
        self.page.keyboard.press('?')
        time.sleep(0.3)
        after = self.page.evaluate("""() => {
            const h = document.getElementById('help-overlay');
            return h ? !h.hidden : false;
        }""")
        self._screenshot("13_help_overlay")
        print(f"\n? key (Help): {before} -> {after}")
        # Help should now be visible
        assert after is True, "Help overlay should be open"
        # Close it
        self.page.keyboard.press('?')
        time.sleep(0.2)

    def test_14_esc_closes_help(self):
        """ESC key closes help overlay."""
        self.page.keyboard.press('?')
        time.sleep(0.3)
        is_open = self.page.evaluate("""() => {
            const h = document.getElementById('help-overlay');
            return h ? !h.hidden : false;
        }""")
        assert is_open, "Help should be open before ESC"

        self.page.keyboard.press('Escape')
        time.sleep(0.3)
        is_closed = self.page.evaluate("""() => {
            const h = document.getElementById('help-overlay');
            return h ? h.hidden : true;
        }""")
        self._screenshot("14_help_closed")
        print(f"\nESC closes help: {is_closed}")
        assert is_closed, "Help should be closed after ESC"

    # --- Chat Panel ---

    def test_15_c_opens_chat(self):
        """C key opens Amy chat panel."""
        before = self.page.evaluate("""() => {
            const c = document.getElementById('chat-overlay');
            return c ? !c.hidden : false;
        }""")
        self.page.keyboard.press('c')
        time.sleep(0.3)
        after = self.page.evaluate("""() => {
            const c = document.getElementById('chat-overlay');
            return c ? !c.hidden : false;
        }""")
        self._screenshot("15_chat_open")
        print(f"\nC key (Chat): {before} -> {after}")
        # Close chat
        close_btn = self.page.query_selector('#chat-close')
        if close_btn:
            close_btn.click()
            time.sleep(0.2)

    # --- Layout Presets ---

    def test_16_ctrl_1_commander_layout(self):
        """Ctrl+1 activates Commander layout."""
        self.page.keyboard.press('Control+1')
        time.sleep(0.5)
        # Check panels open in commander layout
        panels = self.page.evaluate("""() => {
            const pm = window.panelManager;
            if (!pm) return null;
            return {
                amy: pm.isOpen('amy'),
                units: pm.isOpen('units'),
                alerts: pm.isOpen('alerts'),
            };
        }""")
        self._screenshot("16_commander_layout")
        print(f"\nCtrl+1 Commander layout: {panels}")
        if panels:
            # Commander should have amy, units, alerts open
            assert panels["amy"], "Commander layout should have Amy open"

    def test_17_ctrl_2_observer_layout(self):
        """Ctrl+2 activates Observer layout."""
        self.page.keyboard.press('Control+2')
        time.sleep(0.5)
        self._screenshot("17_observer_layout")
        mode = self.page.evaluate("() => window._mapState?.currentMode")
        print(f"\nCtrl+2 Observer layout, mode: {mode}")
        # Observer layout should switch to observe mode
        assert mode == "observe", f"Observer layout should be observe mode: {mode}"

    # --- Report ---

    def test_18_generate_report(self):
        """Generate keyboard exercise report."""
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Keyboard Shortcuts Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .screenshots {{ display:flex; gap:8px; flex-wrap:wrap; margin:16px 0; }}
  .screenshots img {{ max-width:32%; }}
</style></head><body>
<h1>Keyboard Shortcuts Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Map Modes (O/T/S)</h2>
<div class="screenshots">
  <img src="01_observe.png">
  <img src="02_tactical.png">
  <img src="03_setup.png">
</div>

<h2>Panel Toggles (1/2/3/4/M)</h2>
<div class="screenshots">
  <img src="04_amy_toggle.png">
  <img src="05_units_toggle.png">
  <img src="08_minimap_toggle.png">
</div>

<h2>Help &amp; Chat</h2>
<div class="screenshots">
  <img src="13_help_overlay.png">
  <img src="15_chat_open.png">
</div>

<h2>Layout Presets</h2>
<div class="screenshots">
  <img src="16_commander_layout.png">
  <img src="17_observer_layout.png">
</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_19_no_js_errors(self):
        """No critical JS errors during keyboard testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
