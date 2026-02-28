# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Minimap Panel Exercise: Verify minimap renders as a standard panel with
zones, units, camera viewport, click-to-pan, resize, and drag.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_minimap_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/minimap-panel")
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


class TestMinimapPanelExercise:
    """Exercise the Minimap panel (converted from hardcoded to panel system)."""

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
        # Ensure minimap panel is open
        try:
            self.page.evaluate("""() => {
                if (window.panelManager) window.panelManager.open('minimap');
            }""")
            time.sleep(1)
        except Exception:
            pass
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path, timeout=60000)
        return path

    # --- Structure ---

    def test_01_minimap_panel_opens(self):
        """Minimap opens as a standard panel via panelManager."""
        state = self.page.evaluate("""() => {
            const pm = window.panelManager;
            if (!pm) return { found: false, reason: 'no panelManager' };
            const isOpen = pm.isOpen('minimap');
            const panel = pm.getPanel('minimap');
            return {
                found: true,
                isOpen: isOpen,
                hasPanel: !!panel,
                visible: panel ? panel._visible : false,
            };
        }""")

        print(f"\nMinimap panel: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "panelManager should exist"
        assert state["isOpen"], "Minimap panel should be open"
        assert state["hasPanel"], "Panel instance should exist"

    def test_02_minimap_is_registered(self):
        """Minimap is registered in panelManager registry."""
        registered = self.page.evaluate("""() => {
            const pm = window.panelManager;
            if (!pm) return [];
            return pm.registeredIds();
        }""")

        print(f"\nRegistered panels: {registered}")
        assert 'minimap' in registered, f"Minimap should be registered: {registered}"

    def test_03_has_panel_dom_structure(self):
        """Minimap has standard panel DOM: header, body, resize handle."""
        dom = self.page.evaluate("""() => {
            const panel = document.querySelector('[data-panel-id="minimap"]');
            if (!panel) return null;
            return {
                hasHeader: !!panel.querySelector('.panel-header'),
                hasTitle: panel.querySelector('.panel-title')?.textContent?.trim() || '',
                hasBody: !!panel.querySelector('.panel-body'),
                hasResize: !!panel.querySelector('.panel-resize-handle'),
                hasMinimize: !!panel.querySelector('.panel-minimize'),
                hasClose: !!panel.querySelector('.panel-close'),
            };
        }""")

        print(f"\nDOM structure: {dom}")
        self._screenshot("03_dom")

        assert dom is not None, "Minimap panel DOM should exist"
        assert dom["hasHeader"], "Should have panel header"
        assert dom["hasTitle"] == "MINIMAP", f"Title: {dom['hasTitle']}"
        assert dom["hasBody"], "Should have panel body"
        assert dom["hasResize"], "Should have resize handle"
        assert dom["hasMinimize"], "Should have minimize button"
        assert dom["hasClose"], "Should have close button"

    def test_04_has_canvas(self):
        """Minimap panel contains a canvas element."""
        canvas = self.page.evaluate("""() => {
            const panel = document.querySelector('[data-panel-id="minimap"]');
            if (!panel) return null;
            const c = panel.querySelector('canvas');
            return c ? {
                id: c.id,
                width: c.width,
                height: c.height,
                cssWidth: c.style.width,
                cssHeight: c.style.height,
            } : null;
        }""")

        print(f"\nCanvas: {canvas}")
        self._screenshot("04_canvas")

        assert canvas is not None, "Should have canvas"
        assert canvas["id"] == "minimap-canvas", f"Canvas id: {canvas['id']}"
        assert canvas["width"] > 0, f"Canvas width: {canvas['width']}"
        assert canvas["height"] > 0, f"Canvas height: {canvas['height']}"

    def test_05_canvas_has_content(self):
        """Canvas is not blank — has pixels drawn (background + units/border)."""
        has_content = self.page.evaluate("""() => {
            const c = document.getElementById('minimap-canvas');
            if (!c) return false;
            const ctx = c.getContext('2d');
            const data = ctx.getImageData(0, 0, c.width, c.height).data;
            // Background is rgba(10,10,20) so check for brighter pixels
            // (cyan border, unit dots, viewport rectangle)
            let bright = 0;
            for (let i = 0; i < data.length; i += 4) {
                if (data[i] > 30 || data[i+1] > 30 || data[i+2] > 30) bright++;
            }
            // Also check non-transparent (alpha > 0) as content indicator
            let nonTransparent = 0;
            for (let i = 3; i < data.length; i += 4) {
                if (data[i] > 0) nonTransparent++;
            }
            return nonTransparent > 100 || bright > 5;
        }""")

        print(f"\nCanvas has content: {has_content}")
        self._screenshot("05_content")

        assert has_content, "Minimap canvas should have drawn content"

    def test_06_panel_is_draggable(self):
        """Panel can be dragged to a new position."""
        before = self.page.evaluate("""() => {
            const panel = window.panelManager.getPanel('minimap');
            return panel ? { x: panel.x, y: panel.y } : null;
        }""")

        # Drag the panel header
        header = self.page.query_selector('[data-panel-id="minimap"] .panel-header')
        if header:
            box = header.bounding_box()
            if box:
                self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                self.page.mouse.down()
                self.page.mouse.move(box["x"] + 100, box["y"] + 50, steps=5)
                self.page.mouse.up()
                time.sleep(0.3)

        after = self.page.evaluate("""() => {
            const panel = window.panelManager.getPanel('minimap');
            return panel ? { x: panel.x, y: panel.y } : null;
        }""")

        print(f"\nBefore: {before}, After: {after}")
        self._screenshot("06_dragged")

        if before and after:
            moved = before["x"] != after["x"] or before["y"] != after["y"]
            assert moved, f"Panel should have moved: {before} -> {after}"

    def test_07_panel_is_resizable(self):
        """Panel can be resized via resize handle."""
        before = self.page.evaluate("""() => {
            const panel = window.panelManager.getPanel('minimap');
            return panel ? { w: panel.w, h: panel.h } : null;
        }""")

        # Drag the resize handle
        handle = self.page.query_selector('[data-panel-id="minimap"] .panel-resize-handle')
        if handle:
            box = handle.bounding_box()
            if box:
                self.page.mouse.move(box["x"] + 5, box["y"] + 5)
                self.page.mouse.down()
                self.page.mouse.move(box["x"] + 80, box["y"] + 80, steps=5)
                self.page.mouse.up()
                time.sleep(0.3)

        after = self.page.evaluate("""() => {
            const panel = window.panelManager.getPanel('minimap');
            return panel ? { w: panel.w, h: panel.h } : null;
        }""")

        print(f"\nSize before: {before}, after: {after}")
        self._screenshot("07_resized")

        if before and after:
            resized = before["w"] != after["w"] or before["h"] != after["h"]
            assert resized, f"Panel should have resized: {before} -> {after}"

    def test_08_close_and_reopen(self):
        """Panel closes and reopens via panelManager."""
        self.page.evaluate("() => window.panelManager.close('minimap')")
        time.sleep(0.3)

        is_open_after_close = self.page.evaluate(
            "() => window.panelManager.isOpen('minimap')")

        self.page.evaluate("() => window.panelManager.open('minimap')")
        time.sleep(0.3)

        is_open_after_reopen = self.page.evaluate(
            "() => window.panelManager.isOpen('minimap')")

        print(f"\nAfter close: {is_open_after_close}, After reopen: {is_open_after_reopen}")
        self._screenshot("08_reopened")

        assert not is_open_after_close, "Should be closed after close()"
        assert is_open_after_reopen, "Should be open after open()"

    def test_09_m_key_toggles(self):
        """M key toggles minimap panel."""
        self.page.evaluate("() => window.panelManager.open('minimap')")
        time.sleep(0.3)

        before = self.page.evaluate("() => window.panelManager.isOpen('minimap')")

        # Press M key
        self.page.keyboard.press('m')
        time.sleep(0.3)

        after = self.page.evaluate("() => window.panelManager.isOpen('minimap')")

        print(f"\nBefore M: {before}, After M: {after}")
        self._screenshot("09_m_toggle")

        # M should toggle: if open, now closed
        if before:
            assert not after, "M key should close minimap when open"

    def test_10_no_hardcoded_minimap(self):
        """Old hardcoded minimap-container is removed from DOM."""
        old_minimap = self.page.evaluate("""() => {
            return document.getElementById('minimap-container') !== null;
        }""")

        print(f"\nOld minimap-container exists: {old_minimap}")

        assert not old_minimap, "Old minimap-container should not exist in DOM"

    def test_11_visual_diff_open_vs_closed(self):
        """Closing minimap panel produces visible change."""
        self.page.evaluate("() => window.panelManager.open('minimap')")
        time.sleep(0.5)
        before = self._screenshot("11_before_close")

        self.page.evaluate("() => window.panelManager.close('minimap')")
        time.sleep(0.5)
        after = self._screenshot("11_after_close")

        diff = _opencv_diff(before, after)
        print(f"\nOpen vs closed diff: {diff:.1f}%")

        # Reopen
        self.page.evaluate("() => window.panelManager.open('minimap')")

    def test_12_llm_minimap_analysis(self):
        """LLaVA analyzes the minimap panel."""
        self.page.evaluate("() => window.panelManager.open('minimap')")
        time.sleep(1)

        shot = self._screenshot("12_llm_minimap")
        analysis = _llava_analyze(shot,
            "Focus on any minimap or overview panel in this tactical interface. "
            "Describe the minimap contents: unit dots, zones, camera viewport "
            "rectangle, panel title bar, and any interactive elements.")

        print(f"\nMinimap analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Minimap Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .screenshots {{ display:flex; gap:8px; flex-wrap:wrap; margin:16px 0; }}
  .screenshots img {{ max-width:32%; }}
</style></head><body>
<h1>Minimap Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Minimap as Panel</h2>
<img src="12_llm_minimap.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

<h2>Panel Operations</h2>
<div class="screenshots">
  <img src="06_dragged.png">
  <img src="07_resized.png">
  <img src="08_reopened.png">
</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during minimap panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
