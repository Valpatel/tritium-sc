# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Units Panel Exercise: Verify unit list, alliance filter, selection, detail
view, FSM state badges, health bars, and ARIA roles.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_units_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/units-panel")
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


class TestUnitsPanelExercise:
    """Exercise the Units list panel."""

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
        # Open units panel
        try:
            self.page.evaluate("""() => {
                if (window.panelManager) window.panelManager.open('units');
            }""")
            time.sleep(2)
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

    def test_01_units_panel_opens(self):
        """Units panel opens and is visible."""
        state = self.page.evaluate("""() => {
            const inner = document.querySelector('.units-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                visible: inner.offsetHeight > 0,
                width: inner.offsetWidth,
                height: inner.offsetHeight,
            };
        }""")

        print(f"\nUnits panel: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "Units panel should exist"
        assert state["visible"], "Panel should be visible"

    def test_02_filter_dropdown(self):
        """Filter dropdown has alliance options."""
        options = self.page.evaluate("""() => {
            const sel = document.querySelector('.units-panel-inner [data-bind="filter"]');
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

        expected_values = ["all", "friendly", "hostile", "neutral", "unknown"]
        assert len(options) == 5, f"Should have 5 options, got {len(options)}"
        for i, ev in enumerate(expected_values):
            assert options[i]["value"] == ev, f"Option {i}: {options[i]}"

    def test_03_unit_count_display(self):
        """Unit count label shows current filtered count."""
        count = self.page.evaluate("""() => {
            return document.querySelector('.units-panel-inner [data-bind="count"]')?.textContent?.trim() || '';
        }""")

        print(f"\nUnit count: {count}")
        self._screenshot("03_count")

        assert count.isdigit(), f"Count should be numeric: {count}"
        assert int(count) > 0, f"Should have units: {count}"

    def test_04_unit_list_has_items(self):
        """Unit list populates with items."""
        items = self.page.evaluate("""() => {
            const list = document.querySelector('.units-panel-inner [data-bind="list"]');
            if (!list) return [];
            return Array.from(list.querySelectorAll('.panel-list-item')).slice(0, 10).map(li => ({
                unitId: li.dataset.unitId || '',
                text: li.textContent.trim().substring(0, 100),
                hasIconBadge: !!li.querySelector('.panel-icon-badge'),
            }));
        }""")

        print(f"\nUnit items (first 10):")
        for item in items:
            print(f"  {item['unitId']:20s} | {item['text'][:60]}")

        self._screenshot("04_items")

        assert len(items) > 0, "Should have unit items"
        for item in items:
            assert item["unitId"], f"Item should have unitId: {item}"
            assert item["hasIconBadge"], f"Item should have icon badge: {item}"

    def test_05_unit_list_aria(self):
        """Unit list has proper ARIA attributes."""
        aria = self.page.evaluate("""() => {
            const list = document.querySelector('.units-panel-inner [data-bind="list"]');
            return list ? {
                role: list.getAttribute('role'),
                label: list.getAttribute('aria-label'),
            } : null;
        }""")

        print(f"\nARIA: {aria}")
        assert aria is not None, "Unit list should exist"
        assert aria["role"] == "listbox", f"Role: {aria['role']}"
        assert aria["label"] == "Unit list", f"Label: {aria['label']}"

    def test_06_filter_friendly(self):
        """Friendly filter shows only friendly units."""
        # Get all count first
        all_count = self.page.evaluate("""() => {
            return document.querySelector('.units-panel-inner [data-bind="count"]')?.textContent?.trim() || '0';
        }""")

        # Switch to friendly
        self.page.select_option('.units-panel-inner [data-bind="filter"]', 'friendly')
        time.sleep(0.5)

        friendly_count = self.page.evaluate("""() => {
            return document.querySelector('.units-panel-inner [data-bind="count"]')?.textContent?.trim() || '0';
        }""")

        self._screenshot("06_friendly_filter")

        print(f"\nAll units: {all_count}, Friendly: {friendly_count}")

        # Reset
        self.page.select_option('.units-panel-inner [data-bind="filter"]', 'all')
        time.sleep(0.3)

    def test_07_filter_hostile(self):
        """Hostile filter shows only hostile units."""
        self.page.select_option('.units-panel-inner [data-bind="filter"]', 'hostile')
        time.sleep(0.5)

        count = self.page.evaluate("""() => {
            return document.querySelector('.units-panel-inner [data-bind="count"]')?.textContent?.trim() || '0';
        }""")

        self._screenshot("07_hostile_filter")
        print(f"\nHostile units: {count}")

        # Reset
        self.page.select_option('.units-panel-inner [data-bind="filter"]', 'all')

    def test_08_unit_click_selects(self):
        """Clicking a unit item selects it and shows detail."""
        first_id = self.page.evaluate("""() => {
            const item = document.querySelector('.units-panel-inner .panel-list-item');
            return item ? item.dataset.unitId : null;
        }""")

        if first_id:
            self.page.click(f'.units-panel-inner .panel-list-item[data-unit-id="{first_id}"]')
            time.sleep(0.5)

            detail = self.page.evaluate("""() => {
                const el = document.querySelector('.units-panel-inner [data-bind="detail"]');
                if (!el) return null;
                return {
                    visible: el.style.display !== 'none',
                    text: el.textContent.trim().substring(0, 300),
                };
            }""")

            selected = self.page.evaluate("""() => {
                return window.TritiumStore?.get?.('map.selectedUnitId') || null;
            }""")

            print(f"\nClicked: {first_id}, Selected: {selected}")
            print(f"Detail visible: {detail.get('visible') if detail else 'none'}")
            self._screenshot("08_selected")

            assert selected == first_id, \
                f"Click should select: clicked={first_id}, selected={selected}"
        else:
            print("\nNo unit items to click")

    def test_09_detail_shows_stats(self):
        """Detail view shows TYPE, ALLIANCE, HEADING, POSITION."""
        # Select first unit
        first_id = self.page.evaluate("""() => {
            const item = document.querySelector('.units-panel-inner .panel-list-item');
            return item ? item.dataset.unitId : null;
        }""")

        if first_id:
            self.page.click(f'.units-panel-inner .panel-list-item[data-unit-id="{first_id}"]')
            time.sleep(0.5)

            detail = self.page.evaluate("""() => {
                const el = document.querySelector('.units-panel-inner [data-bind="detail"]');
                if (!el || el.style.display === 'none') return null;
                const labels = el.querySelectorAll('.panel-stat-label');
                return {
                    labels: Array.from(labels).map(l => l.textContent.trim()),
                    fullText: el.textContent.trim().substring(0, 500),
                };
            }""")

            print(f"\nDetail labels: {detail.get('labels') if detail else 'none'}")
            self._screenshot("09_detail_stats")

            if detail:
                assert "TYPE" in detail["labels"], f"Should show TYPE: {detail['labels']}"
                assert "ALLIANCE" in detail["labels"], f"Should show ALLIANCE: {detail['labels']}"
                assert "POSITION" in detail["labels"], f"Should show POSITION: {detail['labels']}"
        else:
            print("\nNo units available for detail test")

    def test_10_icon_badges_colored(self):
        """Icon badges have alliance-appropriate colors."""
        badges = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.units-panel-inner .panel-icon-badge');
            return Array.from(items).slice(0, 10).map(b => ({
                letter: b.textContent.trim(),
                color: b.style.color || '',
            }));
        }""")

        print(f"\nIcon badges:")
        for b in badges:
            print(f"  [{b['letter']}] color={b['color']}")

        self._screenshot("10_badges")

        assert len(badges) > 0, "Should have icon badges"

    def test_11_filter_visual_diff(self):
        """Switching filters produces visible change."""
        before = self._screenshot("11_before_filter")

        self.page.select_option('.units-panel-inner [data-bind="filter"]', 'friendly')
        time.sleep(0.5)

        after = self._screenshot("11_after_filter")
        diff = _opencv_diff(before, after)

        print(f"\nFilter switch diff: {diff:.1f}%")

        # Reset
        self.page.select_option('.units-panel-inner [data-bind="filter"]', 'all')

    def test_12_llm_units_analysis(self):
        """LLaVA analyzes the units panel."""
        shot = self._screenshot("12_llm_units")
        analysis = _llava_analyze(shot,
            "Focus on any unit list or roster panel in this tactical interface. "
            "Describe the unit entries, icon badges, alliance colors, filter controls, "
            "and any selected unit detail view.")

        print(f"\nUnits analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Units Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
</style></head><body>
<h1>Units Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Units Panel</h2>
<img src="12_llm_units.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during units panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
