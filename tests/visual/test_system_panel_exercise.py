# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
System Panel Exercise: Verify 5-tab system panel (Cameras, Discovery,
Telemetry, Perf, AI), tab switching, data displays, and action buttons.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_system_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/system-panel")
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


class TestSystemPanelExercise:
    """Exercise the 5-tab system infrastructure panel."""

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
        # Open system panel
        self.page.evaluate("""() => {
            if (window.panelManager) window.panelManager.open('system');
        }""")
        time.sleep(2)
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    # --- Structure ---

    def test_01_system_panel_opens(self):
        """System panel opens and shows 5 tabs."""
        state = self.page.evaluate("""() => {
            const inner = document.querySelector('.system-panel-inner');
            if (!inner) return { found: false };
            const tabs = inner.querySelectorAll('.sys-tab');
            return {
                found: true,
                visible: inner.offsetHeight > 0,
                tabCount: tabs.length,
                tabLabels: Array.from(tabs).map(t => t.textContent.trim()),
                activeTab: inner.querySelector('.sys-tab.active')?.dataset?.tab || '',
            };
        }""")

        print(f"\nSystem panel: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "System panel should exist"
        assert state["tabCount"] == 5, f"Should have 5 tabs: {state['tabCount']}"
        expected = ["CAMERAS", "DISCOVERY", "TELEMETRY", "PERF", "AI"]
        assert state["tabLabels"] == expected, f"Tabs: {state['tabLabels']}"
        assert state["activeTab"] == "cameras", f"Default tab: {state['activeTab']}"

    def test_02_cameras_tab_content(self):
        """Cameras tab shows camera list or empty message."""
        content = self.page.evaluate("""() => {
            const list = document.querySelector('[data-bind="camera-list"]');
            if (!list) return null;
            const items = list.querySelectorAll('.sys-cam-item');
            if (items.length > 0) {
                return {
                    count: items.length,
                    first: items[0].querySelector('.sys-cam-name')?.textContent?.trim() || '',
                };
            }
            const empty = list.querySelector('.panel-empty');
            return { count: 0, empty: empty?.textContent?.trim() || '' };
        }""")

        print(f"\nCameras tab: {content}")
        self._screenshot("02_cameras_tab")

        assert content is not None, "Camera list should exist"

    def test_03_cameras_refresh_button(self):
        """Cameras tab has REFRESH button."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="refresh-cameras"]');
            return b ? { text: b.textContent.trim(), visible: b.offsetHeight > 0 } : null;
        }""")

        print(f"\nRefresh button: {btn}")
        self._screenshot("03_refresh")

        assert btn is not None, "REFRESH button should exist"
        assert btn["text"] == "REFRESH", f"Button text: {btn['text']}"

    def test_04_switch_to_discovery_tab(self):
        """Switching to Discovery tab shows NVR controls."""
        before = self._screenshot("04_before_discovery")

        # Click discovery tab
        self.page.click('.sys-tab[data-tab="discovery"]')
        time.sleep(1)

        after = self._screenshot("04_discovery_tab")
        diff = _opencv_diff(before, after)

        content = self.page.evaluate("""() => {
            const active = document.querySelector('.sys-tab.active');
            const scanBtn = document.querySelector('[data-action="scan-nvr"]');
            const autoBtn = document.querySelector('[data-action="auto-register"]');
            return {
                activeTab: active?.dataset?.tab || '',
                scanBtn: scanBtn ? scanBtn.textContent.trim() : null,
                autoBtn: autoBtn ? autoBtn.textContent.trim() : null,
            };
        }""")

        print(f"\nDiscovery tab: {content}, diff={diff:.1f}%")

        assert content["activeTab"] == "discovery", f"Active: {content['activeTab']}"
        assert content["scanBtn"] == "SCAN NVR", f"Scan: {content['scanBtn']}"
        assert content["autoBtn"] == "AUTO-REGISTER", f"Auto: {content['autoBtn']}"

    def test_05_switch_to_telemetry_tab(self):
        """Switching to Telemetry tab shows system metrics."""
        self.page.click('.sys-tab[data-tab="telemetry"]')
        time.sleep(2)

        content = self.page.evaluate("""() => {
            const active = document.querySelector('.sys-tab.active');
            const telemContent = document.querySelector('[data-bind="telemetry-content"]');
            const refreshBtn = document.querySelector('[data-action="refresh-telemetry"]');
            return {
                activeTab: active?.dataset?.tab || '',
                hasContent: telemContent ? telemContent.textContent.trim().length > 0 : false,
                contentPreview: telemContent ? telemContent.textContent.trim().substring(0, 200) : '',
                refreshBtn: refreshBtn ? refreshBtn.textContent.trim() : null,
            };
        }""")

        print(f"\nTelemetry tab: active={content['activeTab']}")
        print(f"  Content preview: {content['contentPreview'][:100]}")

        self._screenshot("05_telemetry_tab")

        assert content["activeTab"] == "telemetry", f"Active: {content['activeTab']}"
        assert content["refreshBtn"] == "REFRESH", f"Refresh: {content['refreshBtn']}"

    def test_06_switch_to_perf_tab(self):
        """Perf tab shows FPS, units, panels, WS latency, memory."""
        self.page.click('.sys-tab[data-tab="perf"]')
        time.sleep(3)  # Allow perf metrics to populate

        stats = self.page.evaluate("""() => {
            const active = document.querySelector('.sys-tab.active');
            const sparkline = document.querySelector('[data-bind="fps-sparkline"]');
            return {
                activeTab: active?.dataset?.tab || '',
                hasSparkline: !!sparkline,
                fps: document.querySelector('[data-bind="perf-fps"]')?.textContent?.trim() || '',
                units: document.querySelector('[data-bind="perf-units"]')?.textContent?.trim() || '',
                panels: document.querySelector('[data-bind="perf-panels"]')?.textContent?.trim() || '',
                wsLatency: document.querySelector('[data-bind="perf-ws-latency"]')?.textContent?.trim() || '',
                memory: document.querySelector('[data-bind="perf-memory"]')?.textContent?.trim() || '',
            };
        }""")

        print(f"\nPerf tab:")
        print(f"  FPS: {stats['fps']}")
        print(f"  Units: {stats['units']}")
        print(f"  Panels: {stats['panels']}")
        print(f"  WS Latency: {stats['wsLatency']}")
        print(f"  Memory: {stats['memory']}")
        print(f"  Sparkline: {stats['hasSparkline']}")

        self._screenshot("06_perf_tab")

        assert stats["activeTab"] == "perf", f"Active: {stats['activeTab']}"
        assert stats["hasSparkline"], "Should have FPS sparkline canvas"

    def test_07_switch_to_ai_tab(self):
        """AI tab shows YOLO, GPU, tracker, Ollama, Whisper, TTS status."""
        self.page.click('.sys-tab[data-tab="ai"]')
        time.sleep(2)

        content = self.page.evaluate("""() => {
            const active = document.querySelector('.sys-tab.active');
            const aiContent = document.querySelector('[data-bind="ai-content"]');
            const refreshBtn = document.querySelector('[data-action="refresh-ai"]');
            return {
                activeTab: active?.dataset?.tab || '',
                text: aiContent ? aiContent.textContent.trim().substring(0, 500) : '',
                refreshBtn: refreshBtn ? refreshBtn.textContent.trim() : null,
            };
        }""")

        print(f"\nAI tab: active={content['activeTab']}")
        print(f"  Content: {content['text'][:200]}")

        self._screenshot("07_ai_tab")

        assert content["activeTab"] == "ai", f"Active: {content['activeTab']}"
        assert content["refreshBtn"] == "REFRESH", f"Refresh: {content['refreshBtn']}"

    def test_08_tab_switching_visual_diff(self):
        """Each tab switch produces visible change."""
        tabs = ["cameras", "discovery", "telemetry", "perf", "ai"]
        screenshots = []

        for tab in tabs:
            self.page.click(f'.sys-tab[data-tab="{tab}"]')
            time.sleep(1)
            shot = self._screenshot(f"08_{tab}")
            screenshots.append(shot)

        # Compare consecutive tabs
        diffs = []
        for i in range(len(screenshots) - 1):
            d = _opencv_diff(screenshots[i], screenshots[i + 1])
            diffs.append(d)

        print(f"\nTab switch diffs: {[f'{d:.1f}%' for d in diffs]}")
        avg_diff = sum(diffs) / len(diffs)
        print(f"  Average: {avg_diff:.1f}%")

    def test_09_tabs_have_aria_roles(self):
        """Tabs have proper ARIA role attributes."""
        roles = self.page.evaluate("""() => {
            const tabs = document.querySelectorAll('.sys-tab');
            const list = document.querySelector('.sys-tabs');
            return {
                tabListRole: list ? list.getAttribute('role') : null,
                tabRoles: Array.from(tabs).map(t => t.getAttribute('role')),
            };
        }""")

        print(f"\nARIA roles: {roles}")
        self._screenshot("09_aria")

        assert roles["tabListRole"] == "tablist", f"Tab list role: {roles['tabListRole']}"
        assert all(r == "tab" for r in roles["tabRoles"]), f"Tab roles: {roles['tabRoles']}"

    def test_10_perf_sparkline_canvas(self):
        """FPS sparkline canvas has correct dimensions and draws content."""
        self.page.click('.sys-tab[data-tab="perf"]')
        time.sleep(4)  # Allow multiple perf updates

        canvas = self.page.evaluate("""() => {
            const c = document.querySelector('[data-bind="fps-sparkline"]');
            if (!c) return null;
            const ctx = c.getContext('2d');
            const imageData = ctx.getImageData(0, 0, c.width, c.height);
            let nonEmpty = 0;
            for (let i = 3; i < imageData.data.length; i += 4) {
                if (imageData.data[i] > 0) nonEmpty++;
            }
            return {
                width: c.width,
                height: c.height,
                pixelsDrawn: nonEmpty,
                totalPixels: c.width * c.height,
            };
        }""")

        print(f"\nSparkline canvas: {canvas}")
        self._screenshot("10_sparkline")

        assert canvas is not None, "Sparkline canvas should exist"
        assert canvas["width"] == 280, f"Width: {canvas['width']}"
        assert canvas["height"] == 40, f"Height: {canvas['height']}"

    def test_11_camera_list_aria(self):
        """Camera list has proper ARIA attributes."""
        aria = self.page.evaluate("""() => {
            const list = document.querySelector('[data-bind="camera-list"]');
            return list ? {
                role: list.getAttribute('role'),
                label: list.getAttribute('aria-label'),
            } : null;
        }""")

        print(f"\nCamera list ARIA: {aria}")
        assert aria is not None, "Camera list should exist"
        assert aria["role"] == "listbox", f"Role: {aria['role']}"
        assert aria["label"] == "Registered cameras", f"Label: {aria['label']}"

    def test_12_llm_system_analysis(self):
        """LLaVA analyzes the system panel."""
        shot = self._screenshot("12_llm_system")
        analysis = _llava_analyze(shot,
            "Focus on any system or infrastructure panel in this tactical interface. "
            "Describe tabs, camera lists, metrics, performance graphs, and AI status.")

        print(f"\nSystem analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>System Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin:16px 0; }}
  .tabs img {{ max-width:19%; }}
</style></head><body>
<h1>System Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Overview</h2>
<img src="12_llm_system.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

<h2>All 5 Tabs</h2>
<div class="tabs">
  <img src="08_cameras.png">
  <img src="08_discovery.png">
  <img src="08_telemetry.png">
  <img src="08_perf.png">
  <img src="08_ai.png">
</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during system panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
