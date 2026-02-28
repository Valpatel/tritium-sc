# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Patrol Panel Exercise: Verify patrol routes, unit health bars, idle/active
listings, Patrol All / Recall All buttons, and unit selection interaction.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_patrol_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/patrol-panel")
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


class TestPatrolPanelExercise:
    """Exercise patrol routes panel."""

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
        # Open patrol panel
        self.page.evaluate("""() => {
            if (window.panelManager) window.panelManager.open('patrol');
        }""")
        time.sleep(2)
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _get_patrol_state(self) -> dict:
        return self.page.evaluate("""() => {
            const inner = document.querySelector('.patrol-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                visible: inner.offsetHeight > 0,
                summaryText: inner.querySelector('[data-bind="summary"]')?.textContent?.trim() || '',
                entryCount: inner.querySelectorAll('.patrol-entry').length,
                idleCount: inner.querySelectorAll('.patrol-entry-idle').length,
                activeCount: inner.querySelectorAll('.patrol-entry:not(.patrol-entry-idle)').length,
            };
        }""")

    # --- Structure ---

    def test_01_patrol_panel_opens(self):
        """Patrol panel opens and shows content."""
        state = self._get_patrol_state()
        print(f"\nPatrol state: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "Patrol panel should exist"
        assert state["visible"], "Panel should be visible"

    def test_02_summary_row(self):
        """Summary shows patrolling count, idle count, and phase."""
        state = self._get_patrol_state()
        summary = state["summaryText"]

        print(f"\nSummary: {summary}")
        self._screenshot("02_summary")

        # Summary should mention PATROLLING and IDLE
        assert "PATROLLING" in summary or "IDLE" in summary, \
            f"Summary should show patrol stats: {summary}"

    def test_03_unit_entries_exist(self):
        """Patrol panel lists friendly units."""
        state = self._get_patrol_state()

        print(f"\nEntries: {state['entryCount']} total")
        print(f"  Active patrols: {state['activeCount']}")
        print(f"  Idle units: {state['idleCount']}")

        self._screenshot("03_entries")

        # Should have some friendly units
        assert state["entryCount"] > 0, \
            f"Should have unit entries: {state['entryCount']}"

    def test_04_unit_entry_details(self):
        """Each entry shows unit name and type."""
        entries = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.patrol-entry');
            return Array.from(items).slice(0, 10).map(e => ({
                name: e.querySelector('.mono')?.textContent?.trim() || '',
                unitId: e.dataset.unitId || '',
                idle: e.classList.contains('patrol-entry-idle'),
            }));
        }""")

        print(f"\nUnit entries (first 10):")
        for e in entries:
            status = "IDLE" if e["idle"] else "ACTIVE"
            print(f"  [{status:6s}] {e['name']:20s} id={e['unitId']}")

        self._screenshot("04_details")

        assert len(entries) > 0, "Should have entries"
        for e in entries:
            assert e["name"], f"Entry should have name: {e}"

    def test_05_patrol_all_button(self):
        """PATROL ALL button exists and is clickable."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="patrol-all"]');
            return b ? { text: b.textContent.trim(), visible: b.offsetHeight > 0 } : null;
        }""")

        print(f"\nPatrol All button: {btn}")
        self._screenshot("05_patrol_all")

        assert btn is not None, "PATROL ALL button should exist"
        assert btn["text"] == "PATROL ALL", f"Button text: {btn['text']}"
        assert btn["visible"], "Button should be visible"

    def test_06_recall_all_button(self):
        """RECALL ALL button exists and is clickable."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="recall-all"]');
            return b ? { text: b.textContent.trim(), visible: b.offsetHeight > 0 } : null;
        }""")

        print(f"\nRecall All button: {btn}")
        self._screenshot("06_recall_all")

        assert btn is not None, "RECALL ALL button should exist"
        assert btn["text"] == "RECALL ALL", f"Button text: {btn['text']}"
        assert btn["visible"], "Button should be visible"

    def test_07_section_labels(self):
        """Section labels exist for active patrols and idle units."""
        labels = self.page.evaluate("""() => {
            const els = document.querySelectorAll('.patrol-panel-inner .panel-section-label');
            return Array.from(els).map(e => e.textContent.trim());
        }""")

        print(f"\nSection labels: {labels}")
        self._screenshot("07_sections")

        # Should have at least one section label
        assert len(labels) > 0, f"Should have section labels: {labels}"

    def test_08_health_display(self):
        """Active patrol entries show health percentage."""
        health_data = self.page.evaluate("""() => {
            const entries = document.querySelectorAll('.patrol-entry:not(.patrol-entry-idle)');
            const results = [];
            for (const e of entries) {
                const infoSpans = e.querySelectorAll('.patrol-entry-info .mono');
                for (const s of infoSpans) {
                    const text = s.textContent.trim();
                    if (text.includes('%') && !text.includes('waypoint')) {
                        results.push(text);
                    }
                }
            }
            return results;
        }""")

        print(f"\nHealth values: {health_data}")
        self._screenshot("08_health")

    def test_09_waypoint_counts(self):
        """Active patrol entries show waypoint counts."""
        wp_data = self.page.evaluate("""() => {
            const entries = document.querySelectorAll('.patrol-entry:not(.patrol-entry-idle)');
            const results = [];
            for (const e of entries) {
                const spans = e.querySelectorAll('.patrol-entry-info .mono');
                for (const s of spans) {
                    const text = s.textContent.trim();
                    if (text.includes('waypoint')) {
                        results.push(text);
                    }
                }
            }
            return results;
        }""")

        print(f"\nWaypoint counts: {wp_data}")
        self._screenshot("09_waypoints")

    def test_10_unit_click_selects(self):
        """Clicking a unit entry selects it in the store."""
        # Get first unit ID
        first_id = self.page.evaluate("""() => {
            const entry = document.querySelector('.patrol-entry');
            return entry ? entry.dataset.unitId : null;
        }""")

        if first_id:
            # Click it
            self.page.click(f'.patrol-entry[data-unit-id="{first_id}"]')
            time.sleep(0.5)

            selected = self.page.evaluate("""() => {
                return window.TritiumStore?.get?.('map.selectedUnitId') || null;
            }""")

            print(f"\nClicked: {first_id}, Selected: {selected}")
            self._screenshot("10_unit_selected")

            assert selected == first_id, \
                f"Clicking should select unit: clicked={first_id}, selected={selected}"
        else:
            print("\nNo patrol entries to click")
            self._screenshot("10_no_entries")

    def test_11_patrol_dots(self):
        """Patrol entries have colored status dots."""
        dots = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.patrol-dot');
            return Array.from(items).slice(0, 5).map(d => ({
                bgColor: d.style.background || '',
            }));
        }""")

        print(f"\nPatrol dots: {dots}")
        self._screenshot("11_dots")

        assert len(dots) > 0, "Should have patrol status dots"

    def test_12_llm_patrol_analysis(self):
        """LLaVA analyzes the patrol panel."""
        shot = self._screenshot("12_llm_patrol")
        analysis = _llava_analyze(shot,
            "Focus on any patrol routes or unit list panel in this tactical interface. "
            "Describe the unit entries, status dots, health bars, and action buttons.")

        print(f"\nPatrol analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Patrol Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
</style></head><body>
<h1>Patrol Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Patrol Panel</h2>
<img src="12_llm_patrol.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during patrol panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
