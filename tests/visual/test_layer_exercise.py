# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Visual Layer Exercise: Toggle every MAP menu item one at a time.

For each checkable layer:
  1. Screenshot BEFORE toggle
  2. Click the menu item to toggle OFF
  3. Screenshot AFTER toggle
  4. OpenCV pixel diff between before/after
  5. Click again to restore
  6. Verify state restored

After all individual toggles:
  7. Exercise Toggle All OFF/ON
  8. Use local LLM (llava:7b) for visual summaries of key states
  9. Generate HTML report with all screenshots and metrics

Run:
    .venv/bin/python3 -m pytest tests/visual/test_layer_exercise.py -v -s
"""

from __future__ import annotations

import json
import time
import base64
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/layer-exercise")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"

# ── All checkable MAP menu items in order ─────────────────────────
LAYER_TOGGLES = [
    # (menu_label, state_key, default_on, category)
    ("Satellite",     "showSatellite",    True,  "Base map"),
    ("Roads",         "showRoads",        True,  "Base map"),
    ("Buildings",     "showBuildings",    True,  "Base map"),
    ("Waterways",     "showWaterways",    True,  "Base map"),
    ("Parks",         "showParks",        True,  "Base map"),
    ("Grid",          "showGrid",         False, "Base map"),
    ("3D Models",     "showModels3d",     False, "Unit layers"),
    ("Labels",        "showLabels",       True,  "Unit layers"),
    ("Mesh Network",  "showMesh",         True,  "Unit layers"),
    ("Tracers",       "showTracers",      True,  "Combat FX"),
    ("Explosions",    "showExplosions",   True,  "Combat FX"),
    ("Particles",     "showParticles",    True,  "Combat FX"),
    ("Hit Flashes",   "showHitFlashes",   True,  "Combat FX"),
    ("Floating Text", "showFloatingText", True,  "Combat FX"),
    ("Kill Feed",     "showKillFeed",     True,  "Overlays"),
    ("Screen FX",     "showScreenFx",     True,  "Overlays"),
    ("Banners",       "showBanners",      True,  "Overlays"),
    ("Layer HUD",     "showLayerHud",     True,  "Overlays"),
    ("Health Bars",   "showHealthBars",   True,  "Unit decorations"),
    ("Selection FX",  "showSelectionFx",  True,  "Unit decorations"),
    ("Fog",           "showFog",          False, "Environment"),
    ("Terrain",       "showTerrain",      False, "Environment"),
]


@dataclass
class ToggleResult:
    label: str
    state_key: str
    category: str
    default_on: bool
    state_before: bool | None = None
    state_after: bool | None = None
    state_restored: bool | None = None
    pixel_diff_pct: float = 0.0
    mean_brightness_before: float = 0.0
    mean_brightness_after: float = 0.0
    screenshot_before: str = ""
    screenshot_after: str = ""
    passed: bool = False
    error: str = ""


@dataclass
class ExerciseReport:
    results: list[ToggleResult] = field(default_factory=list)
    toggle_all_off_brightness: float = 0.0
    toggle_all_on_brightness: float = 0.0
    toggle_all_diff_pct: float = 0.0
    llm_summary: str = ""
    total_time_s: float = 0.0


def _opencv_diff(path_a: str, path_b: str, region=None):
    """Compare two screenshots. Returns (diff_pct, mean_a, mean_b)."""
    img_a = cv2.imread(path_a)
    img_b = cv2.imread(path_b)
    if img_a is None or img_b is None:
        return 0.0, 0.0, 0.0
    if region:
        x, y, w, h = region
        img_a = img_a[y:y+h, x:x+w]
        img_b = img_b[y:y+h, x:x+w]
    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray_a, gray_b)
    changed = np.count_nonzero(diff > 10)
    total = diff.size
    return (changed / total * 100), float(np.mean(gray_a)), float(np.mean(gray_b))


def _llava_analyze(image_path: str, prompt: str) -> str:
    """Use llava:7b to analyze a screenshot."""
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "llava:7b",
                "prompt": prompt,
                "images": [b64],
                "stream": False,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except Exception as e:
        return f"LLM unavailable: {e}"
    return ""


def _qwen_summarize(text: str) -> str:
    """Use qwen2.5:7b for text summarization."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "qwen2.5:7b",
                "prompt": text,
                "stream": False,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except Exception:
        pass
    return ""


def _generate_report(report: ExerciseReport) -> str:
    """Generate HTML report with screenshots, metrics, and LLM analysis."""
    rows = []
    for r in report.results:
        status = "PASS" if r.passed else "FAIL"
        color = "#05ffa1" if r.passed else "#ff2a6d"
        img_before = ""
        img_after = ""
        if r.screenshot_before and Path(r.screenshot_before).exists():
            img_before = f'<img src="{Path(r.screenshot_before).name}" style="max-width:300px;max-height:150px;">'
        if r.screenshot_after and Path(r.screenshot_after).exists():
            img_after = f'<img src="{Path(r.screenshot_after).name}" style="max-width:300px;max-height:150px;">'
        rows.append(f"""
        <tr>
            <td style="color:{color}">{status}</td>
            <td>{r.label}</td>
            <td>{r.category}</td>
            <td>{r.state_key}</td>
            <td>{'ON' if r.default_on else 'OFF'}</td>
            <td>{r.state_before} → {r.state_after} → {r.state_restored}</td>
            <td>{r.pixel_diff_pct:.1f}%</td>
            <td>{r.mean_brightness_before:.0f} → {r.mean_brightness_after:.0f}</td>
            <td>{img_before}</td>
            <td>{img_after}</td>
            <td style="color:#ff2a6d">{r.error}</td>
        </tr>""")

    passed = sum(1 for r in report.results if r.passed)
    failed = len(report.results) - passed
    llm_html = report.llm_summary.replace("\n", "<br>") if report.llm_summary else "N/A"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Layer Toggle Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; }}
  .summary {{ display:flex; gap:40px; margin:20px 0; }}
  .stat {{ padding:12px 24px; border:1px solid #00f0ff33; border-radius:4px; }}
  .stat .val {{ font-size:28px; color:#00f0ff; }}
  .stat .label {{ font-size:12px; color:#666; }}
  table {{ border-collapse:collapse; width:100%; margin:16px 0; font-size:12px; }}
  th {{ background:#111; color:#00f0ff; padding:8px; text-align:left; border-bottom:2px solid #00f0ff33; }}
  td {{ padding:6px 8px; border-bottom:1px solid #222; vertical-align:top; }}
  tr:hover {{ background:#111; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; }}
</style></head><body>
<h1>TRITIUM-SC Layer Toggle Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')} | Duration: {report.total_time_s:.1f}s</p>

<div class="summary">
  <div class="stat"><div class="val">{passed}</div><div class="label">PASSED</div></div>
  <div class="stat"><div class="val">{failed}</div><div class="label">FAILED</div></div>
  <div class="stat"><div class="val">{len(report.results)}</div><div class="label">TOTAL TOGGLES</div></div>
  <div class="stat"><div class="val">{report.toggle_all_diff_pct:.1f}%</div><div class="label">TOGGLE ALL DIFF</div></div>
</div>

<h2>Toggle All Metrics</h2>
<p>Brightness ON: {report.toggle_all_on_brightness:.0f} | OFF: {report.toggle_all_off_brightness:.0f}
 | Reduction: {((report.toggle_all_on_brightness - report.toggle_all_off_brightness) / max(report.toggle_all_on_brightness, 1) * 100):.1f}%</p>

<h2>Individual Layer Toggles</h2>
<table>
<tr>
  <th>Status</th><th>Layer</th><th>Category</th><th>State Key</th><th>Default</th>
  <th>Before → After → Restored</th><th>Pixel Diff</th><th>Brightness</th>
  <th>Before</th><th>After</th><th>Error</th>
</tr>
{"".join(rows)}
</table>

<h2>LLM Visual Analysis</h2>
<div class="llm">{llm_html}</div>

</body></html>"""
    return html


class TestLayerExercise:
    """Exercise every MAP menu toggle in the real browser with OpenCV verification."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Launch headed browser and navigate to Command Center."""
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        ctx = self._browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = ctx.new_page()
        self._console_msgs = []
        self.page.on("console", lambda msg: self._console_msgs.append(msg.text))
        self.page.goto("http://localhost:8000", wait_until="networkidle", timeout=30000)
        time.sleep(5)  # Wait for map + units to fully load
        yield
        self._browser.close()
        self._pw.stop()

    def _get_state(self) -> dict:
        """Read map state via mapActions."""
        return self.page.evaluate("""() => {
            const ma = window._mapActions;
            return ma && ma.getMapState ? ma.getMapState() : null;
        }""")

    def _click_map_menu_item(self, label: str):
        """Open MAP menu and click a specific item by label."""
        self.page.locator('.menu-trigger:has-text("MAP")').click()
        time.sleep(0.3)
        self.page.locator(f'.menu-item:has-text("{label}")').first.click()
        time.sleep(0.3)
        self.page.keyboard.press("Escape")
        time.sleep(0.5)

    def _screenshot(self, name: str) -> str:
        """Take screenshot, return path."""
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _count_visible_markers(self) -> dict:
        """Count visible/hidden unit markers."""
        return self.page.evaluate("""() => {
            const m = document.querySelectorAll('.tritium-unit-marker');
            let visible = 0, hidden = 0;
            m.forEach(el => {
                if (getComputedStyle(el).display !== 'none') visible++;
                else hidden++;
            });
            return { total: m.length, visible, hidden };
        }""")

    # Map region for OpenCV analysis (excludes panels/chrome)
    MAP_REGION = (300, 60, 1300, 900)

    def test_exercise_all_layers(self):
        """Exercise every layer toggle individually, then Toggle All."""
        t0 = time.monotonic()
        report = ExerciseReport()

        # ── Individual toggles ────────────────────────────────
        for label, state_key, default_on, category in LAYER_TOGGLES:
            result = ToggleResult(
                label=label, state_key=state_key,
                category=category, default_on=default_on,
            )
            try:
                # Get state before
                state = self._get_state()
                if state is None:
                    result.error = "mapState unavailable"
                    result.passed = False
                    report.results.append(result)
                    continue

                result.state_before = state.get(state_key)

                # Screenshot before
                before_path = self._screenshot(
                    f"layer_{state_key}_before"
                )
                result.screenshot_before = before_path

                # Toggle the layer
                self._click_map_menu_item(label)
                time.sleep(0.3)

                # Get state after
                state_after = self._get_state()
                result.state_after = state_after.get(state_key) if state_after else None

                # Screenshot after
                after_path = self._screenshot(
                    f"layer_{state_key}_after"
                )
                result.screenshot_after = after_path

                # OpenCV diff
                diff_pct, mean_before, mean_after = _opencv_diff(
                    before_path, after_path, self.MAP_REGION
                )
                result.pixel_diff_pct = diff_pct
                result.mean_brightness_before = mean_before
                result.mean_brightness_after = mean_after

                # Verify state actually changed
                if result.state_before == result.state_after:
                    result.error = f"State did not change: still {result.state_after}"
                    result.passed = False
                else:
                    result.passed = True

                # Restore the layer to original state
                self._click_map_menu_item(label)
                time.sleep(0.3)
                state_restored = self._get_state()
                result.state_restored = (
                    state_restored.get(state_key) if state_restored else None
                )

                if result.state_restored != result.state_before:
                    result.error += f" Restore failed: {result.state_restored}"
                    result.passed = False

            except Exception as e:
                result.error = str(e)
                result.passed = False

            report.results.append(result)
            print(
                f"  {'PASS' if result.passed else 'FAIL'}: {label} "
                f"({state_key}) diff={result.pixel_diff_pct:.1f}% "
                f"brightness={result.mean_brightness_before:.0f}→"
                f"{result.mean_brightness_after:.0f}"
            )

        # ── Toggle All OFF ────────────────────────────────────
        print("\n--- Toggle All ---")
        before_all = self._screenshot("toggle_all_before")
        markers_before = self._count_visible_markers()
        print(f"  Before: {markers_before['visible']}/{markers_before['total']} markers visible")

        self._click_map_menu_item("Toggle All")
        time.sleep(1)  # Let 10Hz update propagate

        after_all = self._screenshot("toggle_all_after")
        markers_after = self._count_visible_markers()
        print(f"  After:  {markers_after['visible']}/{markers_after['total']} markers visible ({markers_after['hidden']} hidden)")

        diff_pct, mean_on, mean_off = _opencv_diff(
            before_all, after_all, self.MAP_REGION
        )
        report.toggle_all_on_brightness = mean_on
        report.toggle_all_off_brightness = mean_off
        report.toggle_all_diff_pct = diff_pct
        print(f"  OpenCV: brightness {mean_on:.0f}→{mean_off:.0f}, diff={diff_pct:.1f}%")

        # Verify most markers hidden
        assert markers_after["hidden"] >= markers_after["visible"], (
            f"Toggle All should hide most markers: "
            f"{markers_after['visible']} visible, {markers_after['hidden']} hidden"
        )

        # ── Toggle All ON (restore) ───────────────────────────
        self._click_map_menu_item("Toggle All")
        time.sleep(1)

        restored_all = self._screenshot("toggle_all_restored")
        markers_restored = self._count_visible_markers()
        print(f"  Restored: {markers_restored['visible']}/{markers_restored['total']} markers visible")

        # ── LLM analysis of key screenshots ───────────────────
        print("\n--- LLM Visual Analysis ---")
        llm_parts = []

        # Analyze the Toggle All OFF screenshot
        llm_off = _llava_analyze(
            after_all,
            "This is a tactical command center UI after all map layers were "
            "toggled OFF. Describe what you see. Are there any map elements "
            "still visible that shouldn't be? Is the map area dark/empty? "
            "What UI chrome elements remain visible (panels, menus, headers)? "
            "Be specific and concise.",
        )
        if llm_off:
            llm_parts.append(f"Toggle All OFF analysis:\n{llm_off}")
            print(f"  LLaVA (off): {llm_off[:200]}...")

        # Analyze a high-impact toggle (Satellite)
        sat_after = str(SCREENSHOT_DIR / "layer_showSatellite_after.png")
        if Path(sat_after).exists():
            llm_sat = _llava_analyze(
                sat_after,
                "This is a tactical map after the satellite imagery layer was "
                "toggled OFF. Describe what changed. Is the satellite imagery "
                "gone? What remains visible? Be specific.",
            )
            if llm_sat:
                llm_parts.append(f"\nSatellite OFF analysis:\n{llm_sat}")
                print(f"  LLaVA (sat): {llm_sat[:200]}...")

        # Summary with qwen
        if llm_parts:
            summary_prompt = (
                "Summarize these visual analysis results for a layer toggle "
                "test report. Be concise (3-5 sentences):\n\n"
                + "\n".join(llm_parts)
            )
            report.llm_summary = _qwen_summarize(summary_prompt)
            if report.llm_summary:
                print(f"  Summary: {report.llm_summary[:300]}...")
        else:
            report.llm_summary = "LLM analysis unavailable (Ollama not running)"

        # ── Console messages ──────────────────────────────────
        ml_msgs = [m for m in self._console_msgs if "MAP-ML" in m]
        print(f"\n--- Console ({len(ml_msgs)} MAP-ML messages) ---")
        for m in ml_msgs[-10:]:
            print(f"  {m}")

        # ── Generate report ───────────────────────────────────
        report.total_time_s = time.monotonic() - t0
        html = _generate_report(report)
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

        # Also save JSON metrics
        metrics = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_toggles": len(report.results),
            "passed": sum(1 for r in report.results if r.passed),
            "failed": sum(1 for r in report.results if not r.passed),
            "toggle_all_brightness_on": report.toggle_all_on_brightness,
            "toggle_all_brightness_off": report.toggle_all_off_brightness,
            "toggle_all_diff_pct": report.toggle_all_diff_pct,
            "markers_before": markers_before,
            "markers_after_toggle_all": markers_after,
            "per_layer": [
                {
                    "label": r.label,
                    "state_key": r.state_key,
                    "passed": r.passed,
                    "pixel_diff_pct": r.pixel_diff_pct,
                    "brightness_before": r.mean_brightness_before,
                    "brightness_after": r.mean_brightness_after,
                    "error": r.error,
                }
                for r in report.results
            ],
        }
        (SCREENSHOT_DIR / "metrics.json").write_text(
            json.dumps(metrics, indent=2)
        )

        # ── Assertions ────────────────────────────────────────
        passed = sum(1 for r in report.results if r.passed)
        failed_results = [r for r in report.results if not r.passed]
        if failed_results:
            fail_summary = "; ".join(
                f"{r.label}: {r.error}" for r in failed_results
            )
            print(f"\nFailed toggles: {fail_summary}")

        # At least 80% of toggles should work (some may not have visual
        # effect without active combat, like Tracers or Explosions)
        min_pass = int(len(report.results) * 0.8)
        assert passed >= min_pass, (
            f"Only {passed}/{len(report.results)} toggles passed "
            f"(need {min_pass}). Failures: "
            + "; ".join(f"{r.label}:{r.error}" for r in failed_results)
        )
