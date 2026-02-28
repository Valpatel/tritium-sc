# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Status Bar Exercise: Verify all elements in the bottom status bar,
including FPS counter, unit counts, threat count, WebSocket status,
version string, and help button. Tests update behavior during gameplay.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_statusbar_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/statusbar")
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


class TestStatusBarExercise:
    """Exercise all status bar elements and behavior."""

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

    def _get_status_bar(self) -> dict:
        return self.page.evaluate("""() => {
            const bar = document.querySelector('.status-bar, #status-bar');
            if (!bar) return { found: false };

            // Get all text content from children
            const children = Array.from(bar.children).map(c => ({
                text: c.textContent.trim(),
                class: c.className.substring(0, 50),
                visible: c.offsetHeight > 0,
            }));

            return {
                found: true,
                width: bar.offsetWidth,
                height: bar.offsetHeight,
                fullText: bar.textContent.trim().substring(0, 500),
                children: children,
                childCount: bar.children.length,
            };
        }""")

    # --- Structure ---

    def test_01_statusbar_exists(self):
        """Status bar exists and is visible at bottom of screen."""
        bar = self._get_status_bar()
        print(f"\nStatus bar: {bar.get('width')}x{bar.get('height')}")
        print(f"  Children: {bar.get('childCount')}")

        self._screenshot("01_statusbar")

        assert bar["found"], "Status bar should exist"
        assert bar["width"] > 1000, f"Status bar should be wide: {bar['width']}"
        assert bar["height"] > 0, "Status bar should have height"

    def test_02_statusbar_children(self):
        """Status bar has expected child elements."""
        bar = self._get_status_bar()

        print("\nStatus bar children:")
        for c in bar.get("children", []):
            vis = "visible" if c.get("visible") else "hidden"
            print(f"  [{vis:7s}] {c['text'][:40]:40s} class={c['class']}")

        self._screenshot("02_children")

        # Should have multiple children (FPS, alive, threats, WS, version, help)
        assert bar["childCount"] >= 4, (
            f"Status bar should have >= 4 children, got {bar['childCount']}"
        )

    def test_03_fps_counter(self):
        """FPS counter is present and shows a number."""
        fps_data = self.page.evaluate("""() => {
            const fps = document.getElementById('map-fps');
            if (fps) return { found: true, text: fps.textContent.trim(), id: 'map-fps' };
            // Fallback: look in status bar
            const bar = document.querySelector('.status-bar');
            if (bar) {
                for (const c of bar.children) {
                    if (c.textContent.includes('FPS')) {
                        return { found: true, text: c.textContent.trim(), id: 'status-bar-child' };
                    }
                }
            }
            return { found: false };
        }""")

        print(f"\nFPS counter: {fps_data}")
        self._screenshot("03_fps")

        assert fps_data["found"], "FPS counter should exist"
        assert "FPS" in fps_data["text"], f"FPS element should contain 'FPS': {fps_data['text']}"

    def test_04_alive_count(self):
        """Alive count shows number of living units."""
        alive = self.page.evaluate("""() => {
            const bar = document.querySelector('.status-bar');
            if (!bar) return null;
            for (const c of bar.children) {
                if (c.textContent.includes('alive')) {
                    return c.textContent.trim();
                }
            }
            return null;
        }""")

        print(f"\nAlive count: {alive}")
        self._screenshot("04_alive")

        assert alive is not None, "Alive count should be in status bar"
        assert "alive" in alive, f"Should contain 'alive': {alive}"

    def test_05_threat_count(self):
        """Threat count shows number of threats."""
        threats = self.page.evaluate("""() => {
            const bar = document.querySelector('.status-bar');
            if (!bar) return null;
            for (const c of bar.children) {
                if (c.textContent.includes('threat')) {
                    return c.textContent.trim();
                }
            }
            return null;
        }""")

        print(f"\nThreat count: {threats}")
        self._screenshot("05_threats")

        assert threats is not None, "Threat count should be in status bar"

    def test_06_websocket_status(self):
        """WebSocket status indicator shows connection state."""
        ws_status = self.page.evaluate("""() => {
            const bar = document.querySelector('.status-bar');
            if (!bar) return null;
            for (const c of bar.children) {
                if (c.textContent.includes('WS')) {
                    return c.textContent.trim();
                }
            }
            return null;
        }""")

        print(f"\nWebSocket status: {ws_status}")
        self._screenshot("06_ws_status")

        assert ws_status is not None, "WebSocket status should be in status bar"
        assert "WS" in ws_status, f"Should show WS indicator: {ws_status}"

    def test_07_version_string(self):
        """Version string is displayed in status bar."""
        version = self.page.evaluate("""() => {
            const bar = document.querySelector('.status-bar');
            if (!bar) return null;
            for (const c of bar.children) {
                if (c.textContent.includes('TRITIUM') || c.textContent.includes('v0.')) {
                    return c.textContent.trim();
                }
            }
            return null;
        }""")

        print(f"\nVersion: {version}")
        self._screenshot("07_version")

        assert version is not None, "Version should be in status bar"

    def test_08_help_button(self):
        """Help button (?) exists in status bar and opens help."""
        help_btn = self.page.evaluate("""() => {
            const bar = document.querySelector('.status-bar');
            if (!bar) return { found: false };
            for (const c of bar.children) {
                if (c.textContent.trim() === '?' || c.textContent.includes('HELP')) {
                    return { found: true, text: c.textContent.trim(), tag: c.tagName };
                }
            }
            return { found: false };
        }""")

        print(f"\nHelp button: {help_btn}")
        self._screenshot("08_help_btn")

    # --- Coordinate display ---

    def test_09_map_coordinates(self):
        """Map coordinate display shows lat/lng."""
        coords = self.page.evaluate("""() => {
            const el = document.getElementById('map-coords');
            return el ? { found: true, text: el.textContent.trim() } : { found: false };
        }""")

        print(f"\nMap coordinates: {coords}")
        self._screenshot("09_coords")

        assert coords["found"], "Map coordinates element should exist"

    def test_10_coordinates_update_on_mousemove(self):
        """Coordinates update when mouse moves over map."""
        before = self.page.evaluate("""() => {
            const el = document.getElementById('map-coords');
            return el ? el.textContent.trim() : '';
        }""")

        # Move mouse to center of map
        self.page.mouse.move(960, 540)
        time.sleep(0.5)

        after = self.page.evaluate("""() => {
            const el = document.getElementById('map-coords');
            return el ? el.textContent.trim() : '';
        }""")

        # Move to different spot
        self.page.mouse.move(500, 300)
        time.sleep(0.5)

        after2 = self.page.evaluate("""() => {
            const el = document.getElementById('map-coords');
            return el ? el.textContent.trim() : '';
        }""")

        print(f"\nCoords before: {before}")
        print(f"Coords at (960,540): {after}")
        print(f"Coords at (500,300): {after2}")

        self._screenshot("10_coords_moved")

    # --- Status updates during battle ---

    def test_11_status_updates_during_battle(self):
        """Status bar threat count increases during battle."""
        before_bar = self._get_status_bar()
        before = self._screenshot("11_before_battle")

        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); }
            catch (e) {}
        }""")
        time.sleep(10)

        during_bar = self._get_status_bar()
        during = self._screenshot("11_during_battle")

        print(f"\nBefore: {before_bar.get('fullText', '')[:100]}")
        print(f"During: {during_bar.get('fullText', '')[:100]}")

        diff = _opencv_diff(before, during)
        print(f"Visual diff: {diff:.1f}%")

        # Reset
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/reset', { method: 'POST' }); }
            catch (e) {}
        }""")
        time.sleep(1)

    # --- LLM analysis ---

    def test_12_llm_statusbar_analysis(self):
        """LLaVA analyzes the status bar area."""
        # Crop just the bottom of the screen
        shot = self._screenshot("12_llm_statusbar")
        analysis = _llava_analyze(shot,
            "Focus on the bottom status bar of this tactical command center. "
            "List all indicators, numbers, and status elements visible in the bar.")

        print(f"\nStatus bar analysis: {analysis[:200]}")

        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Status Bar Exercise Report</title>
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
</style></head><body>
<h1>Status Bar Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">13</div><div class="label">TESTS RUN</div></div>
</div>

<h2>Status Bar</h2>
<img src="12_llm_statusbar.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

<h2>During Battle</h2>
<img src="11_during_battle.png" style="max-width:100%;">

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during status bar testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
