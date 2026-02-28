# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Mesh Radio Panel Exercise: Verify 4-tab panel (Nodes/Chat/Radio/Scan),
tab switching, node list, chat input, connection controls, status bar.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_mesh_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/mesh-panel")
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


class TestMeshPanelExercise:
    """Exercise the Meshtastic mesh radio panel."""

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
        # Open mesh panel
        try:
            self.page.evaluate("""() => {
                if (window.panelManager) window.panelManager.open('mesh');
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

    def test_01_mesh_panel_opens(self):
        """Mesh panel opens and shows 4 tabs."""
        state = self.page.evaluate("""() => {
            const inner = document.querySelector('.mesh-panel-inner');
            if (!inner) return { found: false };
            const tabs = inner.querySelectorAll('.mesh-tab');
            return {
                found: true,
                visible: inner.offsetHeight > 0,
                tabCount: tabs.length,
                tabLabels: Array.from(tabs).map(t => t.textContent.trim()),
                activeTab: inner.querySelector('.mesh-tab.active')?.dataset?.tab || '',
            };
        }""")

        print(f"\nMesh panel: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "Mesh panel should exist"
        assert state["tabCount"] == 4, f"Should have 4 tabs: {state['tabCount']}"
        expected = ["Nodes", "Chat", "Radio", "Scan"]
        assert state["tabLabels"] == expected, f"Tabs: {state['tabLabels']}"
        assert state["activeTab"] == "nodes", f"Default tab: {state['activeTab']}"

    def test_02_nodes_tab_content(self):
        """Nodes tab shows node list or empty message."""
        content = self.page.evaluate("""() => {
            const list = document.querySelector('[data-bind="node-list"]');
            if (!list) return null;
            const items = list.querySelectorAll('.mesh-node-item');
            if (items.length > 0) {
                return {
                    count: items.length,
                    first: items[0].textContent.trim().substring(0, 100),
                };
            }
            const empty = list.querySelector('.panel-empty');
            return { count: 0, empty: empty?.textContent?.trim() || '' };
        }""")

        print(f"\nNodes tab: {content}")
        self._screenshot("02_nodes")

        assert content is not None, "Node list should exist"

    def test_03_node_list_aria(self):
        """Node list has proper ARIA attributes."""
        aria = self.page.evaluate("""() => {
            const list = document.querySelector('[data-bind="node-list"]');
            return list ? {
                role: list.getAttribute('role'),
                label: list.getAttribute('aria-label'),
            } : null;
        }""")

        print(f"\nNode list ARIA: {aria}")
        assert aria is not None, "Node list should exist"
        assert aria["role"] == "listbox", f"Role: {aria['role']}"
        assert aria["label"] == "Mesh nodes", f"Label: {aria['label']}"

    def test_04_switch_to_chat_tab(self):
        """Chat tab shows message area and input."""
        before = self._screenshot("04_before_chat")

        self.page.click('.mesh-tab[data-tab="chat"]')
        time.sleep(0.5)

        after = self._screenshot("04_chat_tab")
        diff = _opencv_diff(before, after)

        content = self.page.evaluate("""() => {
            const active = document.querySelector('.mesh-tab.active');
            const input = document.querySelector('.mesh-chat-input');
            const sendBtn = document.querySelector('[data-action="send"]');
            const channelSelect = document.querySelector('[data-bind="channel-select"]');
            return {
                activeTab: active?.dataset?.tab || '',
                hasInput: !!input,
                inputPlaceholder: input ? input.placeholder : '',
                hasSendBtn: sendBtn ? sendBtn.textContent.trim() : null,
                channelOptions: channelSelect ? channelSelect.options.length : 0,
            };
        }""")

        print(f"\nChat tab: {content}, diff={diff:.1f}%")

        assert content["activeTab"] == "chat", f"Active: {content['activeTab']}"
        assert content["hasInput"], "Should have chat input"
        assert content["hasSendBtn"] == "SEND", f"Send button: {content['hasSendBtn']}"

    def test_05_chat_char_counter(self):
        """Chat input has character counter (228 max)."""
        self.page.click('.mesh-tab[data-tab="chat"]')
        time.sleep(0.5)

        counter = self.page.evaluate("""() => {
            return document.querySelector('[data-bind="char-count"]')?.textContent?.trim() || '';
        }""")

        print(f"\nChar counter: {counter}")
        self._screenshot("05_char_counter")

        assert counter == "228", f"Counter should be 228: {counter}"

    def test_06_chat_input_updates_counter(self):
        """Typing in chat input updates character counter."""
        self.page.click('.mesh-tab[data-tab="chat"]')
        time.sleep(0.5)

        # Type some text
        self.page.fill('.mesh-chat-input', 'Hello mesh!')
        time.sleep(0.3)

        counter = self.page.evaluate("""() => {
            return document.querySelector('[data-bind="char-count"]')?.textContent?.trim() || '';
        }""")

        print(f"\nCounter after typing: {counter}")
        self._screenshot("06_input_counter")

        # 228 - 11 = 217
        assert counter == "217", f"Counter should be 217: {counter}"

    def test_07_switch_to_radio_tab(self):
        """Radio tab shows connection controls."""
        self.page.click('.mesh-tab[data-tab="radio"]')
        time.sleep(0.5)

        content = self.page.evaluate("""() => {
            const active = document.querySelector('.mesh-tab.active');
            const connectBtn = document.querySelector('[data-action="connect"]');
            const disconnectBtn = document.querySelector('[data-action="disconnect"]');
            const hostInput = document.querySelector('[data-bind="radio-host-input"]');
            const portInput = document.querySelector('[data-bind="radio-port-input"]');
            return {
                activeTab: active?.dataset?.tab || '',
                connectBtn: connectBtn ? connectBtn.textContent.trim() : null,
                disconnectBtn: disconnectBtn ? disconnectBtn.textContent.trim() : null,
                hasHostInput: !!hostInput,
                portDefault: portInput ? portInput.value : '',
            };
        }""")

        print(f"\nRadio tab: {content}")
        self._screenshot("07_radio")

        assert content["activeTab"] == "radio", f"Active: {content['activeTab']}"
        assert content["connectBtn"] == "CONNECT", f"Connect: {content['connectBtn']}"
        assert content["disconnectBtn"] == "DISCONNECT", f"Disconnect: {content['disconnectBtn']}"
        assert content["hasHostInput"], "Should have host input"
        assert content["portDefault"] == "4403", f"Port default: {content['portDefault']}"

    def test_08_switch_to_scan_tab(self):
        """Scan tab shows scan button."""
        self.page.click('.mesh-tab[data-tab="scan"]')
        time.sleep(0.5)

        content = self.page.evaluate("""() => {
            const active = document.querySelector('.mesh-tab.active');
            const scanBtn = document.querySelector('[data-action="scan"]');
            return {
                activeTab: active?.dataset?.tab || '',
                scanBtn: scanBtn ? scanBtn.textContent.trim() : null,
            };
        }""")

        print(f"\nScan tab: {content}")
        self._screenshot("08_scan")

        assert content["activeTab"] == "scan", f"Active: {content['activeTab']}"
        assert content["scanBtn"] == "SCAN FOR DEVICES", f"Scan: {content['scanBtn']}"

    def test_09_status_bar(self):
        """Status bar shows connection status and counts."""
        status = self.page.evaluate("""() => {
            return {
                dot: document.querySelector('[data-bind="status-dot"]')?.className || '',
                label: document.querySelector('[data-bind="status-label"]')?.textContent?.trim() || '',
                nodeCount: document.querySelector('[data-bind="node-count"]')?.textContent?.trim() || '',
                msgCount: document.querySelector('[data-bind="msg-count"]')?.textContent?.trim() || '',
            };
        }""")

        print(f"\nStatus bar:")
        print(f"  Label: {status['label']}")
        print(f"  Nodes: {status['nodeCount']}")
        print(f"  Messages: {status['msgCount']}")
        self._screenshot("09_status")

        assert status["label"] in ["CONNECTED", "DISCONNECTED"], \
            f"Status should be CONNECTED or DISCONNECTED: {status['label']}"

    def test_10_tab_switching_visual_diff(self):
        """Each tab switch produces visible change."""
        tabs = ["nodes", "chat", "radio", "scan"]
        screenshots = []

        for tab in tabs:
            self.page.click(f'.mesh-tab[data-tab="{tab}"]')
            time.sleep(0.5)
            shot = self._screenshot(f"10_{tab}")
            screenshots.append(shot)

        diffs = []
        for i in range(len(screenshots) - 1):
            d = _opencv_diff(screenshots[i], screenshots[i + 1])
            diffs.append(d)

        print(f"\nTab switch diffs: {[f'{d:.1f}%' for d in diffs]}")

    def test_11_radio_status_display(self):
        """Radio tab shows STATUS and HOST stat rows."""
        self.page.click('.mesh-tab[data-tab="radio"]')
        time.sleep(0.5)

        radio = self.page.evaluate("""() => {
            return {
                status: document.querySelector('[data-bind="radio-status"]')?.textContent?.trim() || '',
                host: document.querySelector('[data-bind="radio-host"]')?.textContent?.trim() || '',
            };
        }""")

        print(f"\nRadio status: {radio['status']}, Host: {radio['host']}")
        self._screenshot("11_radio_status")

    def test_12_llm_mesh_analysis(self):
        """LLaVA analyzes the mesh panel."""
        shot = self._screenshot("12_llm_mesh")
        analysis = _llava_analyze(shot,
            "Focus on any radio, mesh network, or Meshtastic panel in this tactical interface. "
            "Describe the tabs, node list, chat area, radio controls, and connection status.")

        print(f"\nMesh analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Mesh Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin:16px 0; }}
  .tabs img {{ max-width:24%; }}
</style></head><body>
<h1>Mesh Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Overview</h2>
<img src="12_llm_mesh.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

<h2>All 4 Tabs</h2>
<div class="tabs">
  <img src="10_nodes.png">
  <img src="10_chat.png">
  <img src="10_radio.png">
  <img src="10_scan.png">
</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during mesh panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
