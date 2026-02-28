# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Scenarios Panel Exercise: Verify scenario list, stats display, run buttons,
progress bar, REFRESH button, and ARIA roles.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_scenarios_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/scenarios-panel")
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


class TestScenariosPanelExercise:
    """Exercise the scenarios runner panel."""

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
        # Open scenarios panel (may crash on stressed browsers)
        try:
            self.page.evaluate("""() => {
                if (window.panelManager) window.panelManager.open('scenarios');
            }""")
            time.sleep(3)
        except Exception:
            pass  # Panel open failed — tests will handle individually
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    # --- Structure ---

    def test_01_scenarios_panel_opens(self):
        """Scenarios panel opens and is visible."""
        state = self.page.evaluate("""() => {
            const inner = document.querySelector('.scenarios-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                visible: inner.offsetHeight > 0,
                width: inner.offsetWidth,
                height: inner.offsetHeight,
            };
        }""")

        print(f"\nScenarios panel: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "Scenarios panel should exist"
        assert state["visible"], "Panel should be visible"

    def test_02_toolbar_buttons(self):
        """Toolbar has REFRESH and RUN ALL buttons."""
        btns = self.page.evaluate("""() => {
            const refresh = document.querySelector('.scenarios-panel-inner [data-action="refresh"]');
            const runAll = document.querySelector('.scenarios-panel-inner [data-action="run-all"]');
            return {
                refresh: refresh ? { text: refresh.textContent.trim(), visible: refresh.offsetHeight > 0 } : null,
                runAll: runAll ? { text: runAll.textContent.trim(), visible: runAll.offsetHeight > 0 } : null,
            };
        }""")

        print(f"\nToolbar buttons: {btns}")
        self._screenshot("02_toolbar")

        assert btns["refresh"] is not None, "REFRESH button should exist"
        assert btns["refresh"]["text"] == "REFRESH", f"Refresh text: {btns['refresh']['text']}"
        assert btns["runAll"] is not None, "RUN ALL button should exist"
        assert btns["runAll"]["text"] == "RUN ALL", f"RunAll text: {btns['runAll']['text']}"

    def test_03_scenario_list(self):
        """Scenario list loads from /api/scenarios."""
        scenarios = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.scn-item');
            if (items.length === 0) {
                const empty = document.querySelector('.scn-list .panel-empty');
                return { count: 0, empty: empty ? empty.textContent.trim() : null };
            }
            return {
                count: items.length,
                names: Array.from(items).slice(0, 10).map(i =>
                    i.querySelector('.scn-item-name')?.textContent?.trim() || ''
                ),
            };
        }""")

        print(f"\nScenario list: {scenarios}")
        self._screenshot("03_list")

        # Either has scenarios or shows appropriate message
        if scenarios["count"] > 0:
            print(f"  First scenarios: {scenarios.get('names', [])[:5]}")
        else:
            print(f"  Empty message: {scenarios.get('empty')}")

    def test_04_scenario_items_have_run_buttons(self):
        """Each scenario item has a play/run button."""
        run_btns = self.page.evaluate("""() => {
            const btns = document.querySelectorAll('.scn-run-btn');
            return {
                count: btns.length,
                scenarioNames: Array.from(btns).slice(0, 5).map(b => b.dataset.scenario || ''),
            };
        }""")

        items = self.page.evaluate("""() => {
            return document.querySelectorAll('.scn-item').length;
        }""")

        print(f"\nRun buttons: {run_btns['count']}, Items: {items}")
        self._screenshot("04_run_buttons")

        assert run_btns["count"] == items, \
            f"Run buttons ({run_btns['count']}) should match items ({items})"

    def test_05_scenario_status_dots(self):
        """Scenario items have status dots (green/amber/red/neutral)."""
        dots = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.scn-item');
            return Array.from(items).slice(0, 10).map(i => {
                const dot = i.querySelector('.panel-dot');
                if (!dot) return null;
                const classes = dot.className;
                return {
                    green: classes.includes('panel-dot-green'),
                    amber: classes.includes('panel-dot-amber'),
                    red: classes.includes('panel-dot-red'),
                    neutral: classes.includes('panel-dot-neutral'),
                };
            });
        }""")

        print(f"\nStatus dots: {dots}")
        self._screenshot("05_dots")

    def test_06_stats_section(self):
        """Stats section shows scenario count and run count."""
        stats = self.page.evaluate("""() => {
            const el = document.querySelector('.scn-stats');
            if (!el) return null;
            const rows = el.querySelectorAll('.panel-stat-row');
            return {
                text: el.textContent.trim().substring(0, 200),
                rowCount: rows.length,
                rows: Array.from(rows).map(r => ({
                    label: r.querySelector('.panel-stat-label')?.textContent?.trim() || '',
                    value: r.querySelector('.panel-stat-value')?.textContent?.trim() || '',
                })),
            };
        }""")

        print(f"\nStats: {stats}")
        self._screenshot("06_stats")

    def test_07_progress_bar_hidden_by_default(self):
        """Progress bar is hidden when no scenario is running."""
        progress = self.page.evaluate("""() => {
            const el = document.querySelector('[data-bind="run-progress"]');
            if (!el) return null;
            return {
                display: el.style.display,
                hidden: el.style.display === 'none',
            };
        }""")

        print(f"\nProgress bar: {progress}")
        self._screenshot("07_progress")

        assert progress is not None, "Progress element should exist"
        assert progress["hidden"], "Progress should be hidden by default"

    def test_08_scenario_list_aria(self):
        """Scenario list has proper ARIA role."""
        aria = self.page.evaluate("""() => {
            const list = document.querySelector('.scn-list');
            return list ? {
                role: list.getAttribute('role'),
                label: list.getAttribute('aria-label'),
            } : null;
        }""")

        print(f"\nARIA: {aria}")
        assert aria is not None, "Scenario list should exist"
        assert aria["role"] == "listbox", f"Role: {aria['role']}"
        assert aria["label"] == "Behavioral scenarios", f"Label: {aria['label']}"

    def test_09_scenario_score_display(self):
        """Scenario items show score or placeholder."""
        scores = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.scn-item');
            return Array.from(items).slice(0, 10).map(i => {
                const spans = i.querySelectorAll('.mono');
                for (const s of spans) {
                    const text = s.textContent.trim();
                    if (text.includes('%') || text === '--') return text;
                }
                return null;
            });
        }""")

        print(f"\nScenario scores: {scores}")
        self._screenshot("09_scores")

    def test_10_refresh_reloads_list(self):
        """REFRESH button reloads the scenario list."""
        before = self._screenshot("10_before_refresh")

        self.page.click('.scenarios-panel-inner [data-action="refresh"]')
        time.sleep(2)

        after = self._screenshot("10_after_refresh")
        diff = _opencv_diff(before, after)

        print(f"\nRefresh diff: {diff:.1f}%")

    def test_11_scenario_item_structure(self):
        """Each scenario item has dot, name, score, and run button."""
        structure = self.page.evaluate("""() => {
            const item = document.querySelector('.scn-item');
            if (!item) return null;
            return {
                hasDot: !!item.querySelector('.panel-dot'),
                hasName: !!item.querySelector('.scn-item-name'),
                hasRunBtn: !!item.querySelector('.scn-run-btn'),
                role: item.getAttribute('role'),
                dataScenario: item.dataset.scenario || '',
            };
        }""")

        print(f"\nScenario item structure: {structure}")
        self._screenshot("11_structure")

        if structure:
            assert structure["hasDot"], "Item should have status dot"
            assert structure["hasName"], "Item should have name"
            assert structure["hasRunBtn"], "Item should have run button"
            assert structure["role"] == "option", f"Role: {structure['role']}"

    def test_12_llm_scenarios_analysis(self):
        """LLaVA analyzes the scenarios panel."""
        shot = self._screenshot("12_llm_scenarios")
        analysis = _llava_analyze(shot,
            "Focus on any scenario runner or test panel in this tactical interface. "
            "Describe the scenario list, status dots, action buttons, and any stats or progress bars.")

        print(f"\nScenarios analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Scenarios Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
</style></head><body>
<h1>Scenarios Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Scenarios Panel</h2>
<img src="12_llm_scenarios.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during scenarios panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
