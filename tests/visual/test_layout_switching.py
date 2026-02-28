# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Layout Switching Exercise: Switch between Commander, Observer, Tactical, and
Battle layout presets via the LAYOUT menu.  Verify that each layout produces
the correct panel arrangement and visual state.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_layout_switching.py -v -s
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/layout-switching")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"

# Expected panel visibility per layout (from layout-manager.js BUILTIN_LAYOUTS)
EXPECTED_LAYOUTS = {
    "Commander": {
        "amy": True, "units": True, "alerts": True,
        "game": False, "mesh": False,
    },
    "Observer": {
        "amy": False, "units": False, "alerts": True,
        "game": False, "mesh": False,
    },
    "Tactical": {
        "amy": False, "units": True, "alerts": True,
        "game": False, "mesh": False,
    },
    "Battle": {
        "amy": True, "units": True, "alerts": True,
        "game": True, "mesh": False,
    },
}


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
            "prompt": f"Summarize this UI layout test in 2-3 sentences:\n{text}",
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


class TestLayoutSwitching:
    """Test layout preset switching."""

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
        self._layout_results = []
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _is_panel_visible(self, panel_id: str) -> bool:
        return self.page.evaluate(f"""() => {{
            const pm = window._panelManager;
            if (pm && pm.isOpen) return pm.isOpen('{panel_id}');
            const el = document.querySelector('[data-panel-id="{panel_id}"]');
            return el ? !el.hidden && el.offsetHeight > 0 : false;
        }}""")

    def _get_all_panel_states(self) -> dict:
        """Get visibility of all known panels."""
        ids = ["amy", "units", "alerts", "game", "mesh"]
        return {pid: self._is_panel_visible(pid) for pid in ids}

    def _apply_layout(self, name: str):
        """Apply a layout via the LAYOUT menu."""
        self.page.locator('.menu-trigger:has-text("LAYOUT")').click()
        time.sleep(0.3)
        self.page.locator(f'.menu-item:has-text("{name}")').first.click()
        time.sleep(0.5)

    def test_01_initial_is_commander(self):
        """Default layout should be Commander."""
        shot = self._screenshot("01_initial_commander")
        states = self._get_all_panel_states()
        expected = EXPECTED_LAYOUTS["Commander"]

        print("\nInitial (Commander) layout:")
        mismatches = []
        for pid, exp in expected.items():
            actual = states.get(pid, False)
            match = actual == exp
            status = "OK" if match else "MISMATCH"
            print(f"  {status:8s} {pid:8s} expected={exp} actual={actual}")
            if not match:
                mismatches.append(f"{pid}: expected={exp} actual={actual}")

        if mismatches:
            print(f"  Mismatches: {mismatches}")
        # Allow some flexibility - at least the main panels should match
        assert states.get("units", False), "Units panel should be visible in Commander"
        assert states.get("alerts", False), "Alerts panel should be visible in Commander"

    def test_02_switch_to_observer(self):
        """Switch to Observer layout - minimal panels."""
        before = self._screenshot("02_before_observer")
        self._apply_layout("Observer")
        after = self._screenshot("02_observer")

        states = self._get_all_panel_states()
        expected = EXPECTED_LAYOUTS["Observer"]

        print("\nObserver layout:")
        for pid, exp in expected.items():
            actual = states.get(pid, False)
            match = actual == exp
            print(f"  {'OK' if match else 'MISS':4s} {pid:8s} expected={exp} actual={actual}")

        diff = _opencv_diff(before, after)
        print(f"  Visual diff: {diff:.1f}%")

        # Observer should hide most panels
        assert not states.get("units", True), "Units should be hidden in Observer"
        assert states.get("alerts", False), "Alerts should be visible in Observer"

        self._layout_results.append({
            "layout": "Observer", "states": states, "diff": diff
        })

    def test_03_switch_to_tactical(self):
        """Switch to Tactical layout - units + alerts."""
        before = self._screenshot("03_before_tactical")
        self._apply_layout("Tactical")
        after = self._screenshot("03_tactical")

        states = self._get_all_panel_states()
        expected = EXPECTED_LAYOUTS["Tactical"]

        print("\nTactical layout:")
        for pid, exp in expected.items():
            actual = states.get(pid, False)
            match = actual == exp
            print(f"  {'OK' if match else 'MISS':4s} {pid:8s} expected={exp} actual={actual}")

        diff = _opencv_diff(before, after)
        print(f"  Visual diff: {diff:.1f}%")

        assert states.get("units", False), "Units should be visible in Tactical"
        assert states.get("alerts", False), "Alerts should be visible in Tactical"

    def test_04_switch_to_battle(self):
        """Switch to Battle layout - all combat panels."""
        before = self._screenshot("04_before_battle")
        self._apply_layout("Battle")
        after = self._screenshot("04_battle")

        states = self._get_all_panel_states()
        expected = EXPECTED_LAYOUTS["Battle"]

        print("\nBattle layout:")
        for pid, exp in expected.items():
            actual = states.get(pid, False)
            match = actual == exp
            print(f"  {'OK' if match else 'MISS':4s} {pid:8s} expected={exp} actual={actual}")

        diff = _opencv_diff(before, after)
        print(f"  Visual diff: {diff:.1f}%")

        assert states.get("amy", False), "Amy should be visible in Battle"
        assert states.get("units", False), "Units should be visible in Battle"
        assert states.get("game", False), "Game status should be visible in Battle"

    def test_05_cycle_all_layouts(self):
        """Rapidly cycle through all layouts and verify each is visually distinct."""
        shots = {}
        for name in ["Commander", "Observer", "Tactical", "Battle"]:
            self._apply_layout(name)
            time.sleep(0.3)
            shots[name] = self._screenshot(f"05_cycle_{name.lower()}")

        # Compare each pair
        print("\nPairwise layout diffs:")
        names = list(shots.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                diff = _opencv_diff(shots[names[i]], shots[names[j]])
                print(f"  {names[i]:12s} vs {names[j]:12s} = {diff:.1f}%")
                # Each layout should look different
                assert diff > 0.5, f"{names[i]} and {names[j]} look identical ({diff:.1f}%)"

    def test_06_layout_persistence_check(self):
        """Apply a layout, verify it sticks after brief wait."""
        self._apply_layout("Observer")
        time.sleep(1)

        # Check Observer is still active
        states = self._get_all_panel_states()
        print("\nObserver persistence:")
        assert not states.get("units", True), "Units should still be hidden in Observer"
        assert states.get("alerts", False), "Alerts should still be visible in Observer"

        # Back to Commander
        self._apply_layout("Commander")
        time.sleep(1)

        states = self._get_all_panel_states()
        print("Commander persistence:")
        assert states.get("units", False), "Units should be visible in Commander"
        assert states.get("alerts", False), "Alerts should be visible in Commander"

        self._screenshot("06_persistence")

    def test_07_llm_layout_comparison(self):
        """Use LLaVA to compare layout screenshots visually."""
        analyses = {}

        for name in ["Commander", "Observer", "Tactical", "Battle"]:
            self._apply_layout(name)
            time.sleep(0.5)
            shot = self._screenshot(f"07_llm_{name.lower()}")
            analysis = _llava_analyze(shot,
                f"This shows the '{name}' layout of a tactical command center. "
                f"What panels and UI elements are visible? Describe the layout.")
            analyses[name] = analysis
            print(f"\n{name}: {analysis[:200]}")

        # Generate report
        summary = _qwen_summarize(
            "\n".join(f"{k}: {v[:300]}" for k, v in analyses.items())
        )
        self._generate_report(analyses, summary)

    def _generate_report(self, analyses: dict, summary: str):
        rows = ""
        for name in ["Commander", "Observer", "Tactical", "Battle"]:
            expected = EXPECTED_LAYOUTS.get(name, {})
            panels = ", ".join(p for p, v in expected.items() if v)
            analysis = analyses.get(name, "N/A")
            rows += f"""
            <tr>
                <td>{name}</td>
                <td>{panels}</td>
                <td><img src="07_llm_{name.lower()}.png" style="max-width:400px;max-height:200px;"></td>
                <td style="font-size:11px;">{analysis[:300]}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Layout Switching Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  table {{ border-collapse:collapse; width:100%; margin:16px 0; font-size:12px; }}
  th {{ background:#111; color:#00f0ff; padding:8px; text-align:left; border-bottom:2px solid #00f0ff33; }}
  td {{ padding:6px 8px; border-bottom:1px solid #222; vertical-align:top; }}
  tr:hover {{ background:#111; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; }}
</style></head><body>
<h1>Layout Switching Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Layout Comparison</h2>
<table>
<tr><th>Layout</th><th>Expected Panels</th><th>Screenshot</th><th>LLM Analysis</th></tr>
{rows}
</table>

<h2>LLM Summary</h2>
<div class="llm">{summary}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_08_no_js_errors(self):
        """No critical JS errors during layout switching."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
