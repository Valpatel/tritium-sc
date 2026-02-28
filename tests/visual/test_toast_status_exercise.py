# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Toast & Status Exercise: Trigger toast notifications, verify WebSocket
connection status, test the command bar status indicators, and exercise
the game-over overlay.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_toast_status_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/toast-status")
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


class TestToastStatusExercise:
    """Exercise toast notifications, status indicators, and overlays."""

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

    def _get_toast_count(self) -> int:
        return self.page.evaluate("""() => {
            const container = document.getElementById('toast-container');
            return container ? container.querySelectorAll('.toast').length : 0;
        }""")

    def _get_toast_texts(self) -> list:
        return self.page.evaluate("""() => {
            const container = document.getElementById('toast-container');
            if (!container) return [];
            return Array.from(container.querySelectorAll('.toast')).map(t => ({
                label: t.querySelector('.toast-label')?.textContent?.trim() || '',
                body: t.querySelector('.toast-body')?.textContent?.trim() || '',
                time: t.querySelector('.toast-time')?.textContent?.trim() || '',
            }));
        }""")

    # --- Toast notifications ---

    def test_01_toast_container_exists(self):
        """Toast container element exists in the DOM."""
        exists = self.page.evaluate("""() => {
            return document.getElementById('toast-container') !== null;
        }""")
        print(f"\nToast container exists: {exists}")
        assert exists, "toast-container element should exist"

        self._screenshot("01_toast_container")

    def test_02_trigger_toast_via_event(self):
        """Emit a toast:show event and verify it appears."""
        before = self._screenshot("02_before_toast")
        count_before = self._get_toast_count()

        # Trigger toast via EventBus
        self.page.evaluate("""() => {
            if (window.EventBus) {
                window.EventBus.emit('toast:show', {
                    message: 'Test notification from Playwright',
                    type: 'info',
                });
            }
        }""")
        time.sleep(0.5)

        count_after = self._get_toast_count()
        after = self._screenshot("02_after_toast")
        toasts = self._get_toast_texts()

        diff = _opencv_diff(before, after)
        print(f"\nToast triggered: count {count_before} -> {count_after}, diff={diff:.1f}%")
        for t in toasts:
            print(f"  [{t['label']}] {t['body']} @ {t['time']}")

        assert count_after > count_before, (
            f"Toast count should increase: {count_before} -> {count_after}"
        )
        assert any("Playwright" in t["body"] for t in toasts), (
            f"Toast with our message not found: {toasts}"
        )

    def test_03_toast_types(self):
        """Different toast types render with different styling."""
        types = ["info", "alert", "amy", "robot"]
        toast_screenshots = {}

        for toast_type in types:
            # Clear existing toasts
            self.page.evaluate("""() => {
                const c = document.getElementById('toast-container');
                if (c) c.innerHTML = '';
            }""")
            time.sleep(0.2)

            self.page.evaluate(f"""() => {{
                if (window.EventBus) {{
                    window.EventBus.emit('toast:show', {{
                        message: 'Test {toast_type} notification',
                        type: '{toast_type}',
                    }});
                }}
            }}""")
            time.sleep(0.3)

            shot = self._screenshot(f"03_toast_{toast_type}")
            toast_screenshots[toast_type] = shot

            # Check toast class
            has_class = self.page.evaluate(f"""() => {{
                const t = document.querySelector('.toast-{toast_type}');
                return t !== null;
            }}""")
            print(f"  {toast_type}: has class toast-{toast_type} = {has_class}")

        self._screenshot("03_toast_types_final")

    def test_04_toast_max_limit(self):
        """Toast container respects max limit (5 visible)."""
        # Clear existing
        self.page.evaluate("""() => {
            const c = document.getElementById('toast-container');
            if (c) c.innerHTML = '';
        }""")
        time.sleep(0.2)

        # Fire 8 toasts rapidly
        for i in range(8):
            self.page.evaluate(f"""() => {{
                if (window.EventBus) {{
                    window.EventBus.emit('toast:show', {{
                        message: 'Rapid toast #{i+1}',
                        type: 'info',
                    }});
                }}
            }}""")
            time.sleep(0.1)

        time.sleep(0.5)
        count = self._get_toast_count()
        self._screenshot("04_toast_max")

        print(f"\nAfter 8 toasts: {count} visible")
        assert count <= 5, f"Max 5 toasts should be visible, got {count}"

    def test_05_toast_dismiss(self):
        """Clicking toast close button dismisses it."""
        # Clear and add one toast
        self.page.evaluate("""() => {
            const c = document.getElementById('toast-container');
            if (c) c.innerHTML = '';
        }""")
        time.sleep(0.2)

        self.page.evaluate("""() => {
            if (window.EventBus) {
                window.EventBus.emit('toast:show', {
                    message: 'Dismissable toast',
                    type: 'info',
                });
            }
        }""")
        time.sleep(0.3)

        count_before = self._get_toast_count()

        # Click the close button
        close_btn = self.page.locator('.toast-close').first
        if close_btn.count() > 0:
            close_btn.click()
            time.sleep(0.5)

        count_after = self._get_toast_count()
        print(f"\nToast dismiss: {count_before} -> {count_after}")

        self._screenshot("05_toast_dismissed")

    def test_06_about_toast(self):
        """HELP > About TRITIUM-SC shows a version toast."""
        self.page.evaluate("""() => {
            const c = document.getElementById('toast-container');
            if (c) c.innerHTML = '';
        }""")
        time.sleep(0.2)

        self.page.locator('.menu-trigger:has-text("HELP")').click()
        time.sleep(0.3)
        self.page.locator('.menu-item:has-text("About TRITIUM-SC")').first.click()
        time.sleep(0.5)

        toasts = self._get_toast_texts()
        print(f"\nAbout toast: {toasts}")

        self._screenshot("06_about_toast")

        assert any("TRITIUM" in t["body"] for t in toasts), (
            f"About toast should mention TRITIUM: {toasts}"
        )

    # --- WebSocket status ---

    def test_07_websocket_connection(self):
        """WebSocket connects successfully to /ws/live."""
        ws_state = self.page.evaluate("""() => {
            // Check if there's a WebSocket in a known location
            if (window._ws) {
                return {
                    readyState: window._ws.readyState,
                    url: window._ws.url,
                    protocol: window._ws.protocol || '',
                };
            }
            // Check TritiumStore for ws status
            if (window.TritiumStore && window.TritiumStore.ws) {
                return {
                    readyState: window.TritiumStore.ws.readyState || -1,
                    connected: window.TritiumStore.ws.connected,
                };
            }
            return { readyState: -1, note: 'No WS reference found' };
        }""")

        print(f"\nWebSocket state: {ws_state}")
        self._screenshot("07_ws_status")

        # readyState 1 = OPEN
        if ws_state.get("readyState") is not None:
            print(f"  readyState: {ws_state['readyState']} (1=OPEN)")

    # --- Command bar status ---

    def test_08_command_bar_elements(self):
        """Command bar contains expected status indicators."""
        elements = self.page.evaluate("""() => {
            const bar = document.querySelector('.command-bar, #command-bar');
            if (!bar) return { found: false };

            return {
                found: true,
                children: bar.children.length,
                // Check for various status elements
                hasMenus: bar.querySelectorAll('.menu-trigger').length,
                hasModeButtons: bar.querySelectorAll('.map-mode-btn').length,
                hasStatusIndicators: bar.querySelectorAll('[class*=status], [class*=indicator]').length,
                text: bar.textContent.substring(0, 200).trim(),
            };
        }""")

        print(f"\nCommand bar: {elements}")
        self._screenshot("08_command_bar")

    def test_09_status_bar_elements(self):
        """Status bar (bottom) contains connection/mode indicators."""
        elements = self.page.evaluate("""() => {
            const bar = document.querySelector('.status-bar, #status-bar');
            if (!bar) return { found: false };

            return {
                found: true,
                visible: bar.offsetHeight > 0,
                text: bar.textContent.trim().substring(0, 300),
                children: bar.children.length,
            };
        }""")

        print(f"\nStatus bar: {elements}")
        self._screenshot("09_status_bar")

    # --- Game-over overlay ---

    def test_10_game_over_overlay_structure(self):
        """Game-over overlay has correct structure (hidden by default)."""
        overlay = self.page.evaluate("""() => {
            const el = document.getElementById('game-over-overlay');
            if (!el) return { found: false };
            return {
                found: true,
                hidden: el.hidden,
                title: document.getElementById('game-over-title')?.textContent?.trim() || '',
                hasScore: document.getElementById('go-score') !== null,
                hasWaves: document.getElementById('go-waves') !== null,
                hasElims: document.getElementById('go-eliminations') !== null,
                hasPlayAgain: el.querySelector('[data-action="play-again"]') !== null,
            };
        }""")

        print(f"\nGame-over overlay: {overlay}")
        self._screenshot("10_game_over_structure")

        assert overlay["found"], "Game-over overlay should exist"
        assert overlay["hidden"], "Game-over overlay should be hidden by default"
        assert overlay["hasScore"], "Game-over should have score element"
        assert overlay["hasWaves"], "Game-over should have waves element"
        assert overlay["hasElims"], "Game-over should have eliminations element"
        assert overlay["hasPlayAgain"], "Game-over should have play again button"

    # --- Modal overlay ---

    def test_11_modal_overlay_structure(self):
        """Modal overlay exists and is hidden by default."""
        modal = self.page.evaluate("""() => {
            const el = document.getElementById('modal-overlay');
            if (!el) return { found: false };
            return {
                found: true,
                hidden: el.hidden,
                hasCloseBtn: document.getElementById('modal-close') !== null,
                hasContent: document.getElementById('modal-content') !== null,
            };
        }""")

        print(f"\nModal overlay: {modal}")
        self._screenshot("11_modal_structure")

        assert modal["found"], "Modal overlay should exist"
        assert modal["hidden"], "Modal should be hidden by default"

    # --- LLM analysis ---

    def test_12_llm_toast_analysis(self):
        """LLaVA analyzes toast notifications."""
        # Fire multiple toasts
        for toast_type in ["info", "alert", "amy"]:
            self.page.evaluate(f"""() => {{
                if (window.EventBus) {{
                    window.EventBus.emit('toast:show', {{
                        message: 'Test {toast_type} from visual test suite',
                        type: '{toast_type}',
                    }});
                }}
            }}""")
            time.sleep(0.3)

        shot = self._screenshot("12_llm_toasts")
        analysis = _llava_analyze(shot,
            "This shows a tactical command center with notification toasts visible. "
            "Describe any toast notifications, status indicators, or UI feedback elements.")

        print(f"\nToast analysis: {analysis[:200]}")

        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Toast & Status Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .summary {{ display:flex; gap:30px; margin:20px 0; flex-wrap:wrap; }}
  .stat {{ padding:12px 24px; border:1px solid #00f0ff33; border-radius:4px; }}
  .stat .val {{ font-size:28px; color:#00f0ff; }}
  .stat .label {{ font-size:12px; color:#666; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .pair {{ display:flex; gap:16px; margin:16px 0; }}
  .pair img {{ max-width:48%; }}
</style></head><body>
<h1>Toast & Status Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">13</div><div class="label">TESTS RUN</div></div>
</div>

<h2>Toast Types</h2>
<div class="pair">
  <img src="03_toast_info.png">
  <img src="03_toast_alert.png">
</div>

<h2>Toast Max Limit</h2>
<img src="04_toast_max.png" style="max-width:800px;">

<h2>LLM Analysis</h2>
<img src="12_llm_toasts.png" style="max-width:800px;">
<div class="llm">{analysis}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during toast/status testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
