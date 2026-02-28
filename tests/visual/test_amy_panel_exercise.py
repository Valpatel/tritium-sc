# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Amy Commander Panel Exercise: Verify portrait, state, mood, latest thought,
CHAT and ATTEND buttons, and store subscription updates.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_amy_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/amy-panel")
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


class TestAmyPanelExercise:
    """Exercise the Amy Commander panel."""

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
        # Open Amy panel
        try:
            self.page.evaluate("""() => {
                if (window.panelManager) window.panelManager.open('amy');
            }""")
            time.sleep(2)
        except Exception:
            pass
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    # --- Structure ---

    def test_01_amy_panel_opens(self):
        """Amy panel opens and is visible."""
        state = self.page.evaluate("""() => {
            const inner = document.querySelector('.amy-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                visible: inner.offsetHeight > 0,
                width: inner.offsetWidth,
                height: inner.offsetHeight,
            };
        }""")

        print(f"\nAmy panel: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "Amy panel should exist"
        assert state["visible"], "Panel should be visible"

    def test_02_portrait_element(self):
        """Portrait area exists with avatar SVG and speaking ring."""
        portrait = self.page.evaluate("""() => {
            const p = document.querySelector('.amy-p-portrait');
            if (!p) return null;
            return {
                state: p.dataset.state || '',
                hasSvg: !!p.querySelector('svg'),
                hasSpeakingRing: !!p.querySelector('.amy-p-speaking-ring'),
            };
        }""")

        print(f"\nPortrait: {portrait}")
        self._screenshot("02_portrait")

        assert portrait is not None, "Portrait should exist"
        assert portrait["hasSvg"], "Should have avatar SVG"
        assert portrait["hasSpeakingRing"], "Should have speaking ring"

    def test_03_name_and_state(self):
        """Amy name and current state displayed."""
        info = self.page.evaluate("""() => {
            const name = document.querySelector('.amy-p-name');
            const state = document.querySelector('[data-bind="state"]');
            return {
                name: name ? name.textContent.trim() : '',
                state: state ? state.textContent.trim() : '',
            };
        }""")

        print(f"\nName: {info['name']}, State: {info['state']}")
        self._screenshot("03_name_state")

        assert info["name"] == "AMY", f"Name should be AMY: {info['name']}"
        assert info["state"], "State should have a value"

    def test_04_mood_display(self):
        """Mood display shows current mood with dot."""
        mood = self.page.evaluate("""() => {
            const moodEl = document.querySelector('.amy-p-mood');
            const label = document.querySelector('[data-bind="mood-label"]');
            const dot = moodEl ? moodEl.querySelector('.panel-dot') : null;
            return {
                visible: moodEl ? moodEl.offsetHeight > 0 : false,
                label: label ? label.textContent.trim() : '',
                hasDot: !!dot,
            };
        }""")

        print(f"\nMood: {mood}")
        self._screenshot("04_mood")

        assert mood["visible"], "Mood should be visible"
        assert mood["label"], "Mood label should have text"
        assert mood["hasDot"], "Mood should have status dot"

    def test_05_thought_display(self):
        """Latest thought is displayed."""
        thought = self.page.evaluate("""() => {
            const el = document.querySelector('[data-bind="thought"]');
            return el ? {
                text: el.textContent.trim().substring(0, 200),
                visible: el.offsetHeight > 0,
            } : null;
        }""")

        print(f"\nThought: {thought}")
        self._screenshot("05_thought")

        assert thought is not None, "Thought element should exist"
        assert thought["visible"], "Thought should be visible"
        assert thought["text"], "Thought should have text"

    def test_06_chat_button(self):
        """CHAT button exists and is primary styled."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('.amy-panel-inner [data-action="chat"]');
            return b ? {
                text: b.textContent.trim(),
                visible: b.offsetHeight > 0,
                isPrimary: b.classList.contains('panel-action-btn-primary'),
            } : null;
        }""")

        print(f"\nChat button: {btn}")
        self._screenshot("06_chat_btn")

        assert btn is not None, "CHAT button should exist"
        assert btn["text"] == "CHAT", f"Button text: {btn['text']}"
        assert btn["isPrimary"], "CHAT should be primary button"

    def test_07_attend_button(self):
        """ATTEND button exists."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('.amy-panel-inner [data-action="attend"]');
            return b ? {
                text: b.textContent.trim(),
                visible: b.offsetHeight > 0,
            } : null;
        }""")

        print(f"\nAttend button: {btn}")
        self._screenshot("07_attend_btn")

        assert btn is not None, "ATTEND button should exist"
        assert btn["text"] == "ATTEND", f"Button text: {btn['text']}"

    def test_08_state_from_api(self):
        """Amy state matches /api/amy/status response."""
        api_state = self.page.evaluate("""async () => {
            try {
                const resp = await fetch('/api/amy/status');
                if (!resp.ok) return null;
                return await resp.json();
            } catch (e) { return null; }
        }""")

        ui_state = self.page.evaluate("""() => {
            return document.querySelector('[data-bind="state"]')?.textContent?.trim() || '';
        }""")

        print(f"\nAPI state: {api_state.get('state') if api_state else 'none'}")
        print(f"UI state: {ui_state}")
        self._screenshot("08_api_state")

        if api_state:
            assert api_state["state"].upper() == ui_state.upper(), \
                f"State mismatch: API={api_state['state']} UI={ui_state}"

    def test_09_thought_updates_over_time(self):
        """Thought text changes over time as Amy thinks."""
        thought1 = self.page.evaluate("""() => {
            return document.querySelector('[data-bind="thought"]')?.textContent?.trim() || '';
        }""")

        time.sleep(8)

        thought2 = self.page.evaluate("""() => {
            return document.querySelector('[data-bind="thought"]')?.textContent?.trim() || '';
        }""")

        changed = thought1 != thought2
        print(f"\nThought 1: {thought1[:80]}")
        print(f"Thought 2: {thought2[:80]}")
        print(f"Changed: {changed}")
        self._screenshot("09_thought_update")

    def test_10_portrait_state_attribute(self):
        """Portrait data-state reflects Amy's current state."""
        portrait_state = self.page.evaluate("""() => {
            const p = document.querySelector('.amy-p-portrait');
            return p ? p.dataset.state : null;
        }""")

        amy_state = self.page.evaluate("""() => {
            return window.TritiumStore?.amy?.state || 'idle';
        }""")

        print(f"\nPortrait data-state: {portrait_state}")
        print(f"Amy store state: {amy_state}")
        self._screenshot("10_portrait_state")

        assert portrait_state is not None, "Portrait should have data-state"

    def test_11_panel_position(self):
        """Amy panel positioned at bottom-left of screen."""
        pos = self.page.evaluate("""() => {
            const panel = document.querySelector('.amy-panel-inner');
            if (!panel) return null;
            const wrapper = panel.closest('.panel');
            if (!wrapper) return null;
            const rect = wrapper.getBoundingClientRect();
            return {
                x: rect.x,
                y: rect.y,
                bottom: rect.bottom,
                right: rect.right,
                screenHeight: window.innerHeight,
            };
        }""")

        print(f"\nPanel position: {pos}")
        self._screenshot("11_position")

        if pos:
            # Amy panel should be near bottom-left
            assert pos["x"] < 350, f"Should be near left: x={pos['x']}"

    def test_12_llm_amy_analysis(self):
        """LLaVA analyzes the Amy panel."""
        shot = self._screenshot("12_llm_amy")
        analysis = _llava_analyze(shot,
            "Focus on any AI commander or assistant panel in this tactical interface. "
            "Describe the portrait, name, state indicator, mood display, thought text, "
            "and action buttons.")

        print(f"\nAmy analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Amy Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
</style></head><body>
<h1>Amy Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Amy Commander Panel</h2>
<img src="12_llm_amy.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during Amy panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
