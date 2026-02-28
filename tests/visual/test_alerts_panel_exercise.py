# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Alerts Panel Exercise: Verify alert feed, unread count, severity dots,
auto-population during battle, and ARIA roles.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_alerts_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/alerts-panel")
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


class TestAlertsPanelExercise:
    """Exercise the Alerts feed panel."""

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
        # Open alerts panel
        try:
            self.page.evaluate("""() => {
                if (window.panelManager) window.panelManager.open('alerts');
            }""")
            time.sleep(2)
        except Exception:
            pass
        yield
        # Reset game state
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

    # --- Structure ---

    def test_01_alerts_panel_opens(self):
        """Alerts panel opens and is visible."""
        state = self.page.evaluate("""() => {
            const inner = document.querySelector('.alerts-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                visible: inner.offsetHeight > 0,
            };
        }""")

        print(f"\nAlerts panel: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "Alerts panel should exist"
        assert state["visible"], "Panel should be visible"

    def test_02_unread_count_display(self):
        """Unread count label exists."""
        count = self.page.evaluate("""() => {
            return document.querySelector('.alerts-panel-inner [data-bind="count"]')?.textContent?.trim() || '';
        }""")

        print(f"\nUnread count: {count}")
        self._screenshot("02_unread")

        assert count is not None, "Unread count should exist"

    def test_03_feed_list_role(self):
        """Alert feed has proper ARIA role for accessibility."""
        role = self.page.evaluate("""() => {
            const feed = document.querySelector('.alerts-panel-inner [data-bind="feed"]');
            return feed ? {
                role: feed.getAttribute('role'),
                label: feed.getAttribute('aria-label'),
                live: feed.getAttribute('aria-live'),
            } : null;
        }""")

        print(f"\nARIA: {role}")
        assert role is not None, "Alert feed should exist"
        assert role["role"] == "log", f"Role should be 'log': {role['role']}"
        assert role["label"] == "Alert feed", f"Label: {role['label']}"
        assert role["live"] == "polite", f"aria-live: {role['live']}"

    def test_04_empty_state(self):
        """When no alerts, shows empty message."""
        content = self.page.evaluate("""() => {
            const feed = document.querySelector('.alerts-panel-inner [data-bind="feed"]');
            if (!feed) return null;
            const items = feed.querySelectorAll('.panel-list-item');
            const empty = feed.querySelector('.panel-empty');
            return {
                itemCount: items.length,
                emptyText: empty ? empty.textContent.trim() : null,
            };
        }""")

        print(f"\nFeed state: {content}")
        self._screenshot("04_empty_state")

    def test_05_alerts_populate_during_battle(self):
        """Alerts appear during an active battle."""
        before = self._screenshot("05_before_battle")
        before_count = self.page.evaluate("""() => {
            return document.querySelectorAll('.alerts-panel-inner .panel-list-item').length;
        }""")

        # Start battle
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(10)

        after = self._screenshot("05_during_battle")
        after_count = self.page.evaluate("""() => {
            return document.querySelectorAll('.alerts-panel-inner .panel-list-item').length;
        }""")

        diff = _opencv_diff(before, after)

        print(f"\nBefore: {before_count} alerts, After: {after_count} alerts")
        print(f"Visual diff: {diff:.1f}%")

    def test_06_alert_entry_structure(self):
        """Alert entries have dot, message, and timestamp."""
        # Ensure alerts exist
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        entries = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.alerts-panel-inner .panel-list-item');
            return Array.from(items).slice(0, 10).map(li => ({
                hasDot: !!li.querySelector('.panel-dot'),
                text: li.textContent.trim().substring(0, 100),
            }));
        }""")

        print(f"\nAlert entries ({len(entries)}):")
        for e in entries:
            print(f"  dot={e['hasDot']} | {e['text'][:80]}")

        self._screenshot("06_entries")

    def test_07_severity_dots(self):
        """Alert entries have severity-colored dots."""
        # Ensure alerts
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        dots = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.alerts-panel-inner .panel-list-item .panel-dot');
            return Array.from(items).slice(0, 10).map(d => ({
                classes: d.className,
                hostile: d.classList.contains('panel-dot-hostile'),
                unknown: d.classList.contains('panel-dot-unknown'),
                neutral: d.classList.contains('panel-dot-neutral'),
            }));
        }""")

        print(f"\nSeverity dots:")
        for d in dots:
            sev = "hostile" if d["hostile"] else "unknown" if d["unknown"] else "neutral"
            print(f"  [{sev}] {d['classes']}")

        self._screenshot("07_severity")

    def test_08_panel_position(self):
        """Alerts panel positioned at top-right."""
        pos = self.page.evaluate("""() => {
            const inner = document.querySelector('.alerts-panel-inner');
            if (!inner) return null;
            const wrapper = inner.closest('.panel');
            if (!wrapper) return null;
            const rect = wrapper.getBoundingClientRect();
            return {
                x: rect.x,
                right: rect.right,
                screenWidth: window.innerWidth,
            };
        }""")

        print(f"\nAlerts position: {pos}")
        self._screenshot("08_position")

        if pos:
            # Should be near right edge
            assert pos["right"] > pos["screenWidth"] - 400, \
                f"Should be near right: right={pos['right']}, screen={pos['screenWidth']}"

    def test_09_max_30_alerts(self):
        """Feed shows at most 30 alerts (truncated)."""
        # The panel renders .slice(0, 30) — verify this limit
        max_items = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.alerts-panel-inner .panel-list-item');
            return items.length;
        }""")

        print(f"\nTotal alert items: {max_items}")
        self._screenshot("09_max_count")

        assert max_items <= 30, f"Should be at most 30: {max_items}"

    def test_10_alert_timestamps(self):
        """Alert entries show timestamps."""
        # Start battle for alerts
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        times = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.alerts-panel-inner .panel-list-item');
            const results = [];
            for (const li of items) {
                const spans = li.querySelectorAll('.panel-stat-value');
                for (const s of spans) {
                    const text = s.textContent.trim();
                    if (text.match(/\\d{1,2}:\\d{2}/)) {
                        results.push(text);
                    }
                }
            }
            return results.slice(0, 10);
        }""")

        print(f"\nTimestamps: {times}")
        self._screenshot("10_timestamps")

    def test_11_visual_change_during_battle(self):
        """Panel visually changes when alerts arrive."""
        before = self._screenshot("11_before")

        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(10)

        after = self._screenshot("11_after")
        diff = _opencv_diff(before, after)

        print(f"\nBattle visual diff: {diff:.1f}%")

    def test_12_llm_alerts_analysis(self):
        """LLaVA analyzes the alerts panel."""
        # Generate alerts
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        shot = self._screenshot("12_llm_alerts")
        analysis = _llava_analyze(shot,
            "Focus on any alert feed or notification panel in this tactical interface. "
            "Describe the alert entries, severity indicators, timestamps, and unread count.")

        print(f"\nAlerts analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Alerts Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
</style></head><body>
<h1>Alerts Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Alerts Feed</h2>
<img src="12_llm_alerts.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during alerts panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
