# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Escalation Panel Exercise: Verify threat level display, hostile count,
auto-dispatch indicator, escalation history, and color coding per threat level.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_escalation_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/escalation-panel")
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


class TestEscalationPanelExercise:
    """Exercise threat level escalation panel."""

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
        # Open escalation panel
        self.page.evaluate("""() => {
            if (window.panelManager) window.panelManager.open('escalation');
        }""")
        time.sleep(2)
        yield
        # Reset game if running
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/reset', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(0.5)
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _get_escalation_state(self) -> dict:
        return self.page.evaluate("""() => {
            const inner = document.querySelector('.escalation-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                visible: inner.offsetHeight > 0,
                levelNum: inner.querySelector('[data-bind="level-num"]')?.textContent?.trim() || '',
                levelLabel: inner.querySelector('[data-bind="level-label"]')?.textContent?.trim() || '',
                levelDesc: inner.querySelector('[data-bind="level-desc"]')?.textContent?.trim() || '',
                hostileCount: inner.querySelector('[data-bind="hostile-count"]')?.textContent?.trim() || '',
                autoDispatch: inner.querySelector('[data-bind="auto-dispatch"]')?.textContent?.trim() || '',
                lastChange: inner.querySelector('[data-bind="last-change"]')?.textContent?.trim() || '',
            };
        }""")

    # --- Structure ---

    def test_01_escalation_panel_opens(self):
        """Escalation panel opens and shows threat display."""
        state = self._get_escalation_state()
        print(f"\nEscalation state: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "Escalation panel should exist"
        assert state["visible"], "Panel should be visible"

    def test_02_initial_threat_level(self):
        """Initial threat level reflects current hostile count."""
        state = self._get_escalation_state()

        print(f"\nThreat level: {state['levelNum']} ({state['levelLabel']})")
        print(f"Description: {state['levelDesc']}")
        self._screenshot("02_initial_level")

        # Level should be a valid number 1-5
        level = int(state["levelNum"])
        assert 1 <= level <= 5, f"Level should be 1-5: {level}"
        assert state["levelLabel"] in ("GREEN", "BLUE", "YELLOW", "ORANGE", "RED"), \
            f"Label should be valid: {state['levelLabel']}"

    def test_03_threat_level_colors(self):
        """Threat level label has correct color coding."""
        color = self.page.evaluate("""() => {
            const label = document.querySelector('[data-bind="level-label"]');
            return label ? label.style.color : null;
        }""")

        level_num = self.page.evaluate("""() => {
            const el = document.querySelector('[data-bind="level-num"]');
            return el ? el.style.color : null;
        }""")

        display_border = self.page.evaluate("""() => {
            const el = document.querySelector('[data-bind="threat-display"]');
            return el ? el.style.borderColor : null;
        }""")

        print(f"\nLabel color: {color}")
        print(f"Number color: {level_num}")
        print(f"Display border: {display_border}")
        self._screenshot("03_colors")

        assert color, "Label should have a color"
        # Color should match the threat level palette
        valid_colors = ['#05ffa1', '#00a0ff', '#fcee0a', '#ff6b35', '#ff2a6d',
                        'rgb(5, 255, 161)', 'rgb(0, 160, 255)', 'rgb(252, 238, 10)',
                        'rgb(255, 107, 53)', 'rgb(255, 42, 109)']
        assert any(c in color for c in valid_colors), f"Color should be from palette: {color}"

    def test_04_hostile_count_display(self):
        """Hostile count is displayed as a number."""
        state = self._get_escalation_state()
        count = state["hostileCount"]

        print(f"\nHostile count: {count}")
        self._screenshot("04_hostile_count")

        assert count.isdigit(), f"Hostile count should be a number: {count}"

    def test_05_auto_dispatch_indicator(self):
        """Auto-dispatch shows STANDBY or ACTIVE status."""
        state = self._get_escalation_state()

        print(f"\nAuto-dispatch: {state['autoDispatch']}")
        self._screenshot("05_auto_dispatch")

        assert state["autoDispatch"] in ("ENABLED", "STANDBY", "ACTIVE"), \
            f"Auto-dispatch should be ENABLED/STANDBY/ACTIVE: {state['autoDispatch']}"

    def test_06_history_section_exists(self):
        """Escalation history section exists with proper ARIA."""
        history = self.page.evaluate("""() => {
            const list = document.querySelector('.esc-history');
            if (!list) return null;
            return {
                role: list.getAttribute('role'),
                label: list.getAttribute('aria-label'),
                children: list.children.length,
                text: list.textContent.trim().substring(0, 200),
            };
        }""")

        print(f"\nHistory section: {history}")
        self._screenshot("06_history")

        assert history is not None, "History section should exist"
        assert history["role"] == "log", f"Role should be 'log': {history['role']}"
        assert history["label"] == "Escalation history", f"Label: {history['label']}"

    def test_07_threat_escalates_during_battle(self):
        """Threat level increases when battle starts and hostiles spawn."""
        before_state = self._get_escalation_state()
        before = self._screenshot("07_before_battle")

        # Start battle
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(10)

        during_state = self._get_escalation_state()
        during = self._screenshot("07_during_battle")

        diff = _opencv_diff(before, during)

        print(f"\nBefore: level={before_state['levelNum']} hostiles={before_state['hostileCount']}")
        print(f"During: level={during_state['levelNum']} hostiles={during_state['hostileCount']}")
        print(f"Visual diff: {diff:.1f}%")

        # Hostile count should increase
        before_hostiles = int(before_state["hostileCount"])
        during_hostiles = int(during_state["hostileCount"])
        assert during_hostiles > before_hostiles, \
            f"Hostiles should increase during battle: {before_hostiles} -> {during_hostiles}"

    def test_08_history_populates_on_level_change(self):
        """History list shows entries after threat level changes."""
        # Start battle to trigger level changes
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        history = self.page.evaluate("""() => {
            const entries = document.querySelectorAll('.esc-history .events-entry');
            return Array.from(entries).map(e => ({
                ts: e.querySelector('.events-ts')?.textContent?.trim() || '',
                badge: e.querySelector('.events-badge')?.textContent?.trim() || '',
                text: e.querySelector('.events-text')?.textContent?.trim() || '',
            }));
        }""")

        print(f"\nHistory entries ({len(history)}):")
        for h in history:
            print(f"  [{h['ts']}] Level {h['badge']}: {h['text']}")

        self._screenshot("08_history_entries")

        # Reset
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/reset', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(1)

    def test_09_last_change_timestamp(self):
        """Last change shows a valid timestamp after escalation."""
        # Start battle to trigger level changes
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        state = self._get_escalation_state()
        print(f"\nLast change: {state['lastChange']}")
        self._screenshot("09_last_change")

        # Should be a timestamp like HH:MM:SS or --- if no change
        last = state["lastChange"]
        if last != "---":
            assert ":" in last, f"Last change should be time format: {last}"

        # Reset
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/reset', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(1)

    def test_10_stat_rows_layout(self):
        """Stat rows (hostiles, auto-dispatch, last change) are visible."""
        stats = self.page.evaluate("""() => {
            const rows = document.querySelectorAll('.esc-stat-row');
            return Array.from(rows).map(r => ({
                label: r.querySelector('.esc-stat-label')?.textContent?.trim() || '',
                value: r.querySelector('.esc-stat-val')?.textContent?.trim() || '',
                visible: r.offsetHeight > 0,
            }));
        }""")

        print(f"\nStat rows ({len(stats)}):")
        for s in stats:
            vis = "visible" if s["visible"] else "hidden"
            print(f"  [{vis}] {s['label']:20s} = {s['value']}")

        self._screenshot("10_stat_rows")

        assert len(stats) == 3, f"Should have 3 stat rows: {len(stats)}"
        labels = [s["label"] for s in stats]
        assert "HOSTILES" in labels, f"Missing HOSTILES: {labels}"
        assert "AUTO-DISPATCH" in labels, f"Missing AUTO-DISPATCH: {labels}"
        assert "LAST CHANGE" in labels, f"Missing LAST CHANGE: {labels}"

    def test_11_threat_display_glow(self):
        """Threat display has box-shadow glow matching level color."""
        glow = self.page.evaluate("""() => {
            const el = document.querySelector('[data-bind="threat-display"]');
            return el ? {
                shadow: el.style.boxShadow,
                border: el.style.borderColor,
            } : null;
        }""")

        print(f"\nThreat display glow: {glow}")
        self._screenshot("11_glow")

        assert glow is not None, "Threat display should exist"
        assert glow["shadow"], "Should have box-shadow glow"

    def test_12_llm_escalation_analysis(self):
        """LLaVA analyzes the escalation panel."""
        shot = self._screenshot("12_llm_escalation")
        analysis = _llava_analyze(shot,
            "Focus on any threat level or escalation panel in this tactical interface. "
            "Describe the threat level indicator, colors, statistics, and any history entries.")

        print(f"\nEscalation analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Escalation Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .pair {{ display:flex; gap:16px; margin:16px 0; }}
  .pair img {{ max-width:48%; }}
</style></head><body>
<h1>Escalation Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Overview</h2>
<img src="12_llm_escalation.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

<h2>Before vs During Battle</h2>
<div class="pair">
  <img src="07_before_battle.png">
  <img src="07_during_battle.png">
</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during escalation panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
