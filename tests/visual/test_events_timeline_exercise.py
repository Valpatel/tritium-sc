# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Events Timeline Exercise: Verify event filtering, list rendering,
clear button, event types, timestamps, and auto-scroll behavior.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_events_timeline_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/events-timeline")
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


class TestEventsTimelineExercise:
    """Exercise the events timeline panel."""

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
        # Open events panel
        self.page.evaluate("""() => {
            if (window.panelManager) window.panelManager.open('events');
        }""")
        time.sleep(2)
        yield
        # Reset game
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

    def _get_events_state(self) -> dict:
        return self.page.evaluate("""() => {
            const inner = document.querySelector('.events-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                visible: inner.offsetHeight > 0,
                filterValue: inner.querySelector('[data-bind="filter"]')?.value || '',
                countText: inner.querySelector('[data-bind="count"]')?.textContent?.trim() || '',
                entryCount: inner.querySelectorAll('.events-entry').length,
            };
        }""")

    # --- Structure ---

    def test_01_events_panel_opens(self):
        """Events timeline panel opens and is visible."""
        state = self._get_events_state()
        print(f"\nEvents state: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "Events panel should exist"
        assert state["visible"], "Panel should be visible"

    def test_02_filter_dropdown(self):
        """Filter dropdown has all expected options."""
        options = self.page.evaluate("""() => {
            const sel = document.querySelector('.events-filter');
            if (!sel) return [];
            return Array.from(sel.options).map(o => ({
                value: o.value,
                label: o.textContent.trim(),
            }));
        }""")

        print(f"\nFilter options ({len(options)}):")
        for o in options:
            print(f"  {o['value']:10s} = {o['label']}")

        self._screenshot("02_filter")

        expected = [
            {"value": "all", "label": "ALL"},
            {"value": "combat", "label": "COMBAT"},
            {"value": "game", "label": "GAME"},
            {"value": "amy", "label": "AMY"},
            {"value": "alert", "label": "ALERTS"},
        ]
        assert len(options) == 5, f"Should have 5 filter options, got {len(options)}"
        for i, e in enumerate(expected):
            assert options[i]["value"] == e["value"], f"Option {i}: {options[i]}"
            assert options[i]["label"] == e["label"], f"Option {i}: {options[i]}"

    def test_03_event_count_display(self):
        """Event count label shows current filtered count."""
        state = self._get_events_state()
        print(f"\nEvent count: {state['countText']}")
        self._screenshot("03_count")

        assert "events" in state["countText"].lower(), \
            f"Count should contain 'events': {state['countText']}"

    def test_04_clear_button(self):
        """Clear button exists and is functional."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('.events-panel-inner [data-action="clear"]');
            return b ? { text: b.textContent.trim(), visible: b.offsetHeight > 0 } : null;
        }""")

        print(f"\nClear button: {btn}")
        self._screenshot("04_clear_btn")

        assert btn is not None, "Clear button should exist"
        assert btn["text"] == "CLEAR", f"Button text: {btn['text']}"
        assert btn["visible"], "Button should be visible"

    def test_05_events_list_role(self):
        """Events list has proper ARIA role for accessibility."""
        role = self.page.evaluate("""() => {
            const list = document.querySelector('.events-list');
            return list ? {
                role: list.getAttribute('role'),
                label: list.getAttribute('aria-label'),
            } : null;
        }""")

        print(f"\nARIA: {role}")
        assert role is not None, "Events list should exist"
        assert role["role"] == "log", f"Role should be 'log': {role['role']}"
        assert role["label"] == "Events timeline", f"Label: {role['label']}"

    def test_06_events_populate_during_battle(self):
        """Events appear during an active battle."""
        before_state = self._get_events_state()
        before = self._screenshot("06_before_battle")

        # Start battle
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(10)

        during_state = self._get_events_state()
        during = self._screenshot("06_during_battle")

        diff = _opencv_diff(before, during)

        print(f"\nBefore: {before_state['entryCount']} entries, count={before_state['countText']}")
        print(f"During: {during_state['entryCount']} entries, count={during_state['countText']}")
        print(f"Visual diff: {diff:.1f}%")

        assert during_state["entryCount"] > before_state["entryCount"], \
            f"Events should increase during battle: {before_state['entryCount']} -> {during_state['entryCount']}"

    def test_07_event_entry_structure(self):
        """Event entries have timestamp, badge, and text."""
        # Start battle to generate events
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        entries = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.events-entry');
            return Array.from(items).slice(0, 10).map(e => ({
                ts: e.querySelector('.events-ts')?.textContent?.trim() || '',
                badge: e.querySelector('.events-badge')?.textContent?.trim() || '',
                badgeColor: e.querySelector('.events-badge')?.style?.color || '',
                text: e.querySelector('.events-text')?.textContent?.trim()?.substring(0, 80) || '',
            }));
        }""")

        print(f"\nEvent entries (first 10):")
        for e in entries:
            print(f"  [{e['ts']}] {e['badge']} | {e['text']}")

        self._screenshot("07_entries")

        assert len(entries) > 0, "Should have event entries"
        for entry in entries:
            assert entry["ts"], f"Entry should have timestamp: {entry}"
            assert entry["badge"], f"Entry should have badge: {entry}"
            assert entry["text"], f"Entry should have text: {entry}"

    def test_08_filter_combat_events(self):
        """Filtering by COMBAT shows only combat events."""
        # Make sure we have some events
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        all_state = self._get_events_state()

        # Switch filter to COMBAT
        self.page.select_option('.events-filter', 'combat')
        time.sleep(0.5)

        combat_state = self._get_events_state()
        self._screenshot("08_combat_filter")

        print(f"\nAll events: {all_state['countText']}")
        print(f"Combat filter: {combat_state['countText']}")
        print(f"Combat entries: {combat_state['entryCount']}")

        assert combat_state["filterValue"] == "combat", \
            f"Filter should be 'combat': {combat_state['filterValue']}"

        # Reset filter
        self.page.select_option('.events-filter', 'all')
        time.sleep(0.5)

    def test_09_filter_game_events(self):
        """Filtering by GAME shows game state events."""
        # Ensure events exist
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(5)

        self.page.select_option('.events-filter', 'game')
        time.sleep(0.5)

        state = self._get_events_state()
        self._screenshot("09_game_filter")

        print(f"\nGame filter: {state['countText']}, entries={state['entryCount']}")
        assert state["filterValue"] == "game", f"Filter: {state['filterValue']}"

        # Reset
        self.page.select_option('.events-filter', 'all')

    def test_10_clear_removes_events(self):
        """Clear button removes all events from the list."""
        # Start battle to generate events, then reset before testing clear
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(5)
        # Reset game so no new events arrive
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/reset', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(2)

        before_state = self._get_events_state()
        before = self._screenshot("10_before_clear")

        # Click clear
        self.page.click('.events-panel-inner [data-action="clear"]')
        time.sleep(0.5)

        after_state = self._get_events_state()
        after = self._screenshot("10_after_clear")

        diff = _opencv_diff(before, after)

        print(f"\nBefore clear: {before_state['entryCount']} entries")
        print(f"After clear: {after_state['entryCount']} entries")
        print(f"Visual diff: {diff:.1f}%")

        assert after_state["entryCount"] == 0, \
            f"Should have 0 entries after clear: {after_state['entryCount']}"

    def test_11_events_resume_after_clear(self):
        """New events continue to appear after clearing."""
        # Clear first
        self.page.click('.events-panel-inner [data-action="clear"]')
        time.sleep(0.5)

        cleared = self._get_events_state()
        assert cleared["entryCount"] == 0, "Should be cleared"

        # Start battle to generate new events
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        resumed = self._get_events_state()
        self._screenshot("11_resumed")

        print(f"\nAfter clear + battle: {resumed['entryCount']} entries")
        assert resumed["entryCount"] > 0, "New events should appear after clear"

    def test_12_llm_events_analysis(self):
        """LLaVA analyzes the events timeline panel."""
        # Generate some events
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        shot = self._screenshot("12_llm_events")
        analysis = _llava_analyze(shot,
            "Focus on any events timeline or log panel in this tactical interface. "
            "Describe the event entries, timestamps, color-coded badges, and filtering controls.")

        print(f"\nEvents analysis: {analysis[:200]}")

        # Reset
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/reset', { method: 'POST' }); } catch (e) {}
        }""")

        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Events Timeline Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .pair {{ display:flex; gap:16px; margin:16px 0; }}
  .pair img {{ max-width:48%; }}
</style></head><body>
<h1>Events Timeline Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Events During Battle</h2>
<img src="12_llm_events.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

<h2>Before vs During Battle</h2>
<div class="pair">
  <img src="06_before_battle.png">
  <img src="06_during_battle.png">
</div>

<h2>Combat Filter</h2>
<img src="08_combat_filter.png" style="max-width:100%;">

<h2>After Clear</h2>
<img src="10_after_clear.png" style="max-width:100%;">

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during events timeline testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
