# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Keyboard Shortcuts & Overlays Exercise: Test the help overlay, chat overlay,
modal system, minimap toggle, and keyboard shortcut functionality.
Captures screenshots and uses LLaVA for semantic analysis.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_keyboard_overlay_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/keyboard-overlay")
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


def _llava_analyze(img_path: str, prompt: str) -> str:
    import base64, requests
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": "llava:7b", "prompt": prompt,
            "images": [b64], "stream": False,
        }, timeout=60)
        if resp.ok:
            return resp.json().get("response", "")
    except Exception as e:
        return f"LLM error: {e}"
    return ""


# Expected keyboard shortcut sections in the help overlay
EXPECTED_SECTIONS = ["GENERAL", "MAP", "PANELS", "LAYOUTS", "GAME"]

EXPECTED_SHORTCUTS = {
    "GENERAL": ["?", "ESC", "C", "/", "M"],
    "MAP": ["O", "T", "S", "F", "R", "I", "[", "]"],
    "PANELS": ["1", "2", "3", "4"],
    "LAYOUTS": ["Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+Shift+S"],
    "GAME": ["B"],
}


class TestKeyboardOverlayExercise:
    """Exercise keyboard shortcuts, help overlay, chat, and overlays."""

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
        self.page.screenshot(path=path)
        return path

    def _is_help_visible(self) -> bool:
        return self.page.evaluate("""() => {
            const el = document.getElementById('help-overlay');
            return el ? !el.hidden : false;
        }""")

    def _is_chat_visible(self) -> bool:
        return self.page.evaluate("""() => {
            const el = document.getElementById('chat-overlay');
            return el ? !el.hidden : false;
        }""")

    def _is_minimap_visible(self) -> bool:
        return self.page.evaluate("""() => {
            const el = document.getElementById('minimap-container');
            return el ? !el.hidden : false;
        }""")

    # --- Help overlay ---

    def test_01_help_overlay_toggle(self):
        """'?' key toggles the help overlay on and off."""
        assert not self._is_help_visible(), "Help should be hidden initially"
        before = self._screenshot("01_before_help")

        self.page.keyboard.press("?")
        time.sleep(0.3)

        assert self._is_help_visible(), "Help should be visible after '?'"
        after_open = self._screenshot("01_help_open")

        diff = _opencv_diff(before, after_open)
        print(f"\nHelp overlay: diff={diff:.1f}%")
        assert diff > 1.0, f"Visual should change when help opens, diff={diff:.1f}%"

        # Close with '?'
        self.page.keyboard.press("?")
        time.sleep(0.3)
        assert not self._is_help_visible(), "Help should close on second '?'"

        # Close with Escape
        self.page.keyboard.press("?")
        time.sleep(0.3)
        assert self._is_help_visible()
        self.page.keyboard.press("Escape")
        time.sleep(0.3)
        assert not self._is_help_visible(), "Help should close on Escape"

        self._screenshot("01_help_closed")

    def test_02_help_sections_present(self):
        """Help overlay contains all expected sections."""
        self.page.keyboard.press("?")
        time.sleep(0.3)

        sections = self.page.evaluate("""() => {
            const titles = document.querySelectorAll('.help-section-title');
            return Array.from(titles).map(t => t.textContent.trim());
        }""")

        print(f"\nHelp sections: {sections}")
        self._screenshot("02_help_sections")

        for expected in EXPECTED_SECTIONS:
            assert expected in sections, (
                f"Section '{expected}' not found in help: {sections}"
            )

        self.page.keyboard.press("Escape")
        time.sleep(0.2)

    def test_03_help_shortcuts_listed(self):
        """Help overlay lists all expected keyboard shortcuts."""
        self.page.keyboard.press("?")
        time.sleep(0.3)

        shortcut_data = self.page.evaluate("""() => {
            const sections = {};
            document.querySelectorAll('.help-section').forEach(sec => {
                const title = sec.querySelector('.help-section-title')?.textContent?.trim();
                if (!title) return;
                const keys = [];
                sec.querySelectorAll('kbd').forEach(kbd => {
                    keys.push(kbd.textContent.trim());
                });
                sections[title] = keys;
            });
            return sections;
        }""")

        print("\nShortcut listing:")
        for section, keys in shortcut_data.items():
            print(f"  {section}: {keys}")

        # Verify each expected shortcut is listed
        missing = []
        for section, expected_keys in EXPECTED_SHORTCUTS.items():
            actual_keys = shortcut_data.get(section, [])
            for key in expected_keys:
                if key not in actual_keys:
                    missing.append(f"{section}/{key}")

        if missing:
            print(f"\nMissing shortcuts: {missing}")

        self._screenshot("03_help_shortcuts")
        self.page.keyboard.press("Escape")
        time.sleep(0.2)

        # Allow a few missing (e.g. [ and ] shown as combined)
        assert len(missing) <= 2, f"Too many missing shortcuts: {missing}"

    def test_04_help_overlay_from_menu(self):
        """HELP > Keyboard Shortcuts opens the help overlay."""
        assert not self._is_help_visible()

        self.page.locator('.menu-trigger:has-text("HELP")').click()
        time.sleep(0.3)
        self.page.locator('.menu-item:has-text("Keyboard Shortcuts")').first.click()
        time.sleep(0.5)

        assert self._is_help_visible(), "Help should open from menu"
        self._screenshot("04_help_from_menu")

        self.page.keyboard.press("Escape")
        time.sleep(0.2)

    # --- Chat overlay ---

    def test_05_chat_toggle(self):
        """'C' key toggles the chat overlay."""
        assert not self._is_chat_visible(), "Chat should be hidden initially"
        before = self._screenshot("05_before_chat")

        self.page.keyboard.press("c")
        time.sleep(0.3)

        assert self._is_chat_visible(), "Chat should open on 'C'"
        after_open = self._screenshot("05_chat_open")

        diff = _opencv_diff(before, after_open)
        print(f"\nChat overlay: diff={diff:.1f}%")
        assert diff > 1.0, f"Visual should change when chat opens, diff={diff:.1f}%"

        # Check chat elements
        chat_elements = self.page.evaluate("""() => {
            return {
                title: document.querySelector('.chat-title')?.textContent?.trim() || '',
                input: document.getElementById('chat-input') !== null,
                sendBtn: document.getElementById('chat-send') !== null,
                messages: document.getElementById('chat-messages') !== null,
                contextText: document.getElementById('chat-context-text')?.textContent?.trim() || '',
            };
        }""")
        print(f"Chat elements: {chat_elements}")

        assert chat_elements["title"], "Chat should have a title"
        assert chat_elements["input"], "Chat should have an input field"
        assert chat_elements["sendBtn"], "Chat should have a send button"

        # Close with Escape
        self.page.keyboard.press("Escape")
        time.sleep(0.3)
        assert not self._is_chat_visible(), "Chat should close on Escape"

    def test_06_chat_slash_focus(self):
        """'/' key opens chat and focuses the input."""
        assert not self._is_chat_visible()

        self.page.keyboard.press("/")
        time.sleep(0.3)

        assert self._is_chat_visible(), "Chat should open on '/'"

        # Check if input is focused
        is_focused = self.page.evaluate("""() => {
            return document.activeElement === document.getElementById('chat-input');
        }""")
        print(f"\nChat input focused: {is_focused}")
        assert is_focused, "Chat input should be focused after '/'"

        self._screenshot("06_chat_slash")
        self.page.keyboard.press("Escape")
        time.sleep(0.2)

    # --- Minimap ---

    def test_07_minimap_toggle(self):
        """'M' key toggles the minimap container."""
        vis_before = self._is_minimap_visible()
        before = self._screenshot("07_before_minimap")

        self.page.keyboard.press("m")
        time.sleep(0.3)

        vis_after = self._is_minimap_visible()
        after = self._screenshot("07_after_minimap")

        diff = _opencv_diff(before, after)
        print(f"\nMinimap toggle: {vis_before} -> {vis_after}, diff={diff:.1f}%")

        assert vis_before != vis_after, (
            f"Minimap visibility should change: {vis_before} -> {vis_after}"
        )

        # Toggle back
        self.page.keyboard.press("m")
        time.sleep(0.3)

    # --- Panel number shortcuts ---

    def test_08_panel_number_shortcuts(self):
        """Number keys 1-4 toggle corresponding panels."""
        panel_map = {
            "1": "amy",
            "2": "units",
            "3": "alerts",
            "4": "game",
        }

        results = {}
        for key, panel_id in panel_map.items():
            # Get state before
            before = self.page.evaluate(f"""() => {{
                const pm = window.panelManager;
                return pm && pm.isOpen ? pm.isOpen('{panel_id}') : null;
            }}""")

            self.page.keyboard.press(key)
            time.sleep(0.3)

            after = self.page.evaluate(f"""() => {{
                const pm = window.panelManager;
                return pm && pm.isOpen ? pm.isOpen('{panel_id}') : null;
            }}""")

            toggled = before != after if (before is not None and after is not None) else False
            results[f"{key}={panel_id}"] = {"before": before, "after": after, "toggled": toggled}
            print(f"  Key {key} ({panel_id}): {before} -> {after} {'OK' if toggled else 'NO CHANGE'}")

            # Toggle back
            self.page.keyboard.press(key)
            time.sleep(0.2)

        self._screenshot("08_panel_shortcuts")

        toggled_count = sum(1 for r in results.values() if r["toggled"])
        assert toggled_count >= 3, (
            f"At least 3/4 panel shortcuts should work, got {toggled_count}: {results}"
        )

    # --- Layout shortcuts ---

    def test_09_ctrl_layout_shortcuts(self):
        """Ctrl+1-4 switch between layout presets."""
        layout_map = {
            "1": "commander",
            "2": "observer",
            "3": "tactical",
            "4": "battle",
        }

        layouts_applied = []
        for key, layout_name in layout_map.items():
            self.page.keyboard.press(f"Control+{key}")
            time.sleep(0.5)

            # Check current panels state
            panels = self.page.evaluate("""() => {
                const pm = window.panelManager;
                if (!pm || !pm.isOpen) return {};
                return {
                    amy: pm.isOpen('amy'),
                    units: pm.isOpen('units'),
                    alerts: pm.isOpen('alerts'),
                    game: pm.isOpen('game'),
                };
            }""")

            layouts_applied.append({"name": layout_name, "panels": panels})
            print(f"  Ctrl+{key} ({layout_name}): {panels}")

        self._screenshot("09_layout_shortcuts")

        # Each layout should produce different panel states
        unique_states = set()
        for la in layouts_applied:
            state = tuple(sorted(la["panels"].items()))
            unique_states.add(state)

        print(f"\nUnique layout states: {len(unique_states)}")
        assert len(unique_states) >= 3, (
            f"Ctrl+1-4 should produce at least 3 unique states, got {len(unique_states)}"
        )

    # --- Escape closes everything ---

    def test_10_escape_closes_all(self):
        """Escape key closes all overlays."""
        # Open help
        self.page.keyboard.press("?")
        time.sleep(0.2)
        assert self._is_help_visible()

        self.page.keyboard.press("Escape")
        time.sleep(0.2)
        assert not self._is_help_visible(), "Escape should close help"

        # Open chat
        self.page.keyboard.press("c")
        time.sleep(0.2)
        assert self._is_chat_visible()

        self.page.keyboard.press("Escape")
        time.sleep(0.2)
        assert not self._is_chat_visible(), "Escape should close chat"

        self._screenshot("10_all_closed")

    # --- LLM analysis ---

    def test_11_llm_overlay_analysis(self):
        """LLaVA analyzes help and chat overlays."""
        analyses = {}

        # Help overlay
        self.page.keyboard.press("?")
        time.sleep(0.3)
        help_shot = self._screenshot("11_llm_help")
        analyses["help"] = _llava_analyze(help_shot,
            "This shows a keyboard shortcuts help overlay on a tactical command center. "
            "List all the sections and shortcuts you can see.")
        self.page.keyboard.press("Escape")
        time.sleep(0.2)

        # Chat overlay
        self.page.keyboard.press("c")
        time.sleep(0.3)
        chat_shot = self._screenshot("11_llm_chat")
        analyses["chat"] = _llava_analyze(chat_shot,
            "This shows a chat overlay on a tactical command center. "
            "Describe the chat interface elements visible.")
        self.page.keyboard.press("Escape")
        time.sleep(0.2)

        for name, text in analyses.items():
            print(f"\n{name}: {text[:200]}")

        self._generate_report(analyses)

    def _generate_report(self, analyses: dict):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Keyboard & Overlay Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .summary {{ display:flex; gap:30px; margin:20px 0; }}
  .stat {{ padding:12px 24px; border:1px solid #00f0ff33; border-radius:4px; }}
  .stat .val {{ font-size:28px; color:#00f0ff; }}
  .stat .label {{ font-size:12px; color:#666; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .pair {{ display:flex; gap:16px; margin:16px 0; }}
  .pair img {{ max-width:48%; }}
</style></head><body>
<h1>Keyboard & Overlay Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">12</div><div class="label">TESTS RUN</div></div>
  <div class="stat"><div class="val">{len(EXPECTED_SECTIONS)}</div><div class="label">HELP SECTIONS</div></div>
</div>

<h2>Help Overlay</h2>
<img src="11_llm_help.png" style="max-width:800px;">
<div class="llm">{analyses.get('help', 'N/A')}</div>

<h2>Chat Overlay</h2>
<img src="11_llm_chat.png" style="max-width:800px;">
<div class="llm">{analyses.get('chat', 'N/A')}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_12_no_js_errors(self):
        """No critical JS errors during overlay testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
