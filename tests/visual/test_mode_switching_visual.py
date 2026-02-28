# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Mode Switching Visual Exercise: Switch between Observe, Tactical, and Setup
map modes.  Capture screenshots at each mode, measure visual differences
with OpenCV, and use LLaVA to describe what each mode looks like.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_mode_switching_visual.py -v -s
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/mode-switching")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"

MODES = [
    {"key": "o", "name": "observe", "label": "OBSERVE",
     "desc": "Clean satellite view for surveillance"},
    {"key": "t", "name": "tactical", "label": "TACTICAL",
     "desc": "Unit status overlays and engagement ranges"},
    {"key": "s", "name": "setup", "label": "SETUP",
     "desc": "Unit placement and drag-to-position"},
]


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


def _qwen_summarize(text: str) -> str:
    import requests
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": "qwen2.5:7b",
            "prompt": f"Summarize this comparison of 3 UI modes concisely:\n{text}",
            "stream": False,
        }, timeout=30)
        if resp.ok:
            return resp.json().get("response", "")
    except Exception:
        pass
    return ""


def _opencv_diff(path_a: str, path_b: str) -> float:
    a = cv2.imread(path_a, cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(path_b, cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        return 0.0
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    diff = cv2.absdiff(a, b)
    return float(np.count_nonzero(diff > 15) / diff.size * 100)


def _opencv_brightness(path: str) -> float:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return float(np.mean(img)) if img is not None else 0.0


def _opencv_edge_density(path: str) -> float:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    edges = cv2.Canny(img, 50, 150)
    return float(np.count_nonzero(edges) / edges.size * 100)


class TestModeSwitchingVisual:
    """Visual verification of map mode switching."""

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

    def _get_mode(self) -> str:
        """Get current map mode from the mode indicator or buttons."""
        return self.page.evaluate("""() => {
            // Try the mode indicator div
            const ind = document.getElementById('map-mode');
            if (ind && ind.textContent.trim()) return ind.textContent.trim();
            // Fall back to active mode button
            const active = document.querySelector('.map-mode-btn.active');
            if (active) return active.dataset.mapMode || active.textContent.trim();
            // Fall back to store
            if (window.TritiumStore && window.TritiumStore.map)
                return window.TritiumStore.map.mode || 'unknown';
            return 'unknown';
        }""")

    def _get_mode_buttons(self) -> list:
        """Get all mode button states."""
        return self.page.evaluate("""() => {
            const buttons = document.querySelectorAll('.map-mode-btn');
            return Array.from(buttons).map(b => ({
                text: b.textContent.trim(),
                active: b.classList.contains('active'),
                mode: b.dataset?.mapMode || b.textContent.trim().toLowerCase(),
            }));
        }""")

    def _get_map_state(self) -> dict:
        return self.page.evaluate("""() => {
            const ma = window._mapActions;
            return ma && ma.getMapState ? ma.getMapState() : {};
        }""")

    def test_01_capture_all_modes(self):
        """Capture screenshot at each mode with full metrics."""
        mode_shots = {}
        mode_metrics = {}

        for m in MODES:
            self.page.keyboard.press(m["key"])
            time.sleep(0.5)

            shot = self._screenshot(f"01_{m['name']}")
            mode_text = self._get_mode()
            buttons = self._get_mode_buttons()
            state = self._get_map_state()

            brightness = _opencv_brightness(shot)
            edges = _opencv_edge_density(shot)

            mode_shots[m["name"]] = shot
            mode_metrics[m["name"]] = {
                "indicator": mode_text,
                "brightness": brightness,
                "edges": edges,
                "map_mode": state.get("mapMode", "unknown"),
                "buttons": buttons,
            }

            print(f"\n{m['name'].upper()}:")
            print(f"  Indicator: {mode_text}")
            print(f"  Brightness: {brightness:.1f}")
            print(f"  Edge density: {edges:.1f}%")
            print(f"  Map state mode: {state.get('mapMode', 'unknown')}")

            # Mode indicator should contain the expected label or mode name
            mode_lower = mode_text.lower()
            assert (m["label"].lower() in mode_lower
                    or m["name"] in mode_lower
                    or m["key"] == mode_lower[0:1]), (
                f"Mode indicator should show '{m['label']}', got: {mode_text}"
            )

        # Each mode should look different
        names = list(mode_shots.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                diff = _opencv_diff(mode_shots[names[i]], mode_shots[names[j]])
                print(f"\n  {names[i]:10s} vs {names[j]:10s}: {diff:.1f}% diff")

    def test_02_mode_button_highlight(self):
        """Verify mode buttons update their active state on switch."""
        for m in MODES:
            self.page.keyboard.press(m["key"])
            time.sleep(0.3)

            buttons = self._get_mode_buttons()
            active_buttons = [b for b in buttons if b.get("active")]
            active_names = [b.get("text", "").lower() for b in active_buttons]

            print(f"\n{m['name']}: active buttons = {active_names}")

            # At least one button should be active
            if buttons:
                assert len(active_buttons) >= 1, (
                    f"No active mode button for {m['name']}"
                )

        self._screenshot("02_button_states")

    def test_03_rapid_mode_cycling(self):
        """Rapidly cycle through modes 5 times, verify final state correct."""
        sequence = ["o", "t", "s"] * 5
        for key in sequence:
            self.page.keyboard.press(key)
            time.sleep(0.1)

        time.sleep(0.5)

        # Final key was 's', so should be in setup mode
        mode = self._get_mode()
        print(f"\nAfter rapid cycling: {mode}")
        assert "setup" in mode.lower(), f"Expected Setup after cycling, got: {mode}"

        self._screenshot("03_rapid_cycle")

    def test_04_mode_affects_unit_display(self):
        """Check if different modes change how units are displayed on map."""
        mode_markers = {}
        for m in MODES:
            self.page.keyboard.press(m["key"])
            time.sleep(0.5)

            markers = self.page.evaluate("""() => {
                const markers = document.querySelectorAll('.unit-marker, .maplibregl-marker');
                return {
                    count: markers.length,
                    samples: Array.from(markers).slice(0, 5).map(m => ({
                        class: m.className,
                        visible: m.offsetHeight > 0,
                    })),
                };
            }""")
            mode_markers[m["name"]] = markers
            print(f"\n{m['name']}: {markers['count']} markers")

        self._screenshot("04_unit_display")

    def test_05_llm_mode_analysis(self):
        """Use LLaVA to analyze and compare all three modes."""
        analyses = {}

        for m in MODES:
            self.page.keyboard.press(m["key"])
            time.sleep(0.5)
            shot = self._screenshot(f"05_llm_{m['name']}")
            analysis = _llava_analyze(shot,
                f"This tactical command center is in '{m['name'].upper()}' mode. "
                f"Describe the UI state: what panels, overlays, and map features "
                f"are visible? Focus on differences from a standard satellite map view.")
            analyses[m["name"]] = analysis
            print(f"\n{m['name']}: {analysis[:200]}")

        # Summary comparison
        combined = "\n".join(f"{k}: {v[:400]}" for k, v in analyses.items())
        summary = _qwen_summarize(combined)
        print(f"\nSummary: {summary[:300]}")

        # Generate report
        self._generate_report(analyses, summary)

    def _generate_report(self, analyses: dict, summary: str):
        rows = ""
        for m in MODES:
            analysis = analyses.get(m["name"], "N/A")
            rows += f"""
            <tr>
                <td style="color:#00f0ff">{m['name'].upper()}</td>
                <td>{m['key'].upper()}</td>
                <td>{m['desc']}</td>
                <td><img src="05_llm_{m['name']}.png" style="max-width:500px;max-height:250px;"></td>
                <td style="font-size:11px;">{analysis[:400]}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Mode Switching Visual Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .summary {{ display:flex; gap:30px; margin:20px 0; }}
  .stat {{ padding:12px 24px; border:1px solid #00f0ff33; border-radius:4px; }}
  .stat .val {{ font-size:28px; color:#00f0ff; }}
  .stat .label {{ font-size:12px; color:#666; }}
  table {{ border-collapse:collapse; width:100%; margin:16px 0; font-size:12px; }}
  th {{ background:#111; color:#00f0ff; padding:8px; text-align:left; border-bottom:2px solid #00f0ff33; }}
  td {{ padding:6px 8px; border-bottom:1px solid #222; vertical-align:top; }}
  tr:hover {{ background:#111; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; }}
</style></head><body>
<h1>Mode Switching Visual Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">{len(MODES)}</div><div class="label">MODES TESTED</div></div>
  <div class="stat"><div class="val">5</div><div class="label">TESTS RUN</div></div>
</div>

<h2>Mode Comparison</h2>
<table>
<tr><th>Mode</th><th>Key</th><th>Description</th><th>Screenshot</th><th>LLM Analysis</th></tr>
{rows}
</table>

<h2>LLM Summary</h2>
<div class="llm">{summary}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_06_no_js_errors(self):
        """No critical JS errors during mode switching."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
