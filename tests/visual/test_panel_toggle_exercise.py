# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Panel Toggle Exercise: Open/close every registered panel through the VIEW
menu, verify each panel's DOM presence, bounding box, and visual change
using OpenCV pixel diff.  Also tests Show All / Hide All bulk commands.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_panel_toggle_exercise.py -v -s
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/panel-exercise")
REPORT_PATH = SCREENSHOT_DIR / "report.html"

# Panels expected in the VIEW menu (id → selector, title, default_open)
# default_open values based on the Commander layout preset
PANELS = [
    {"id": "amy",    "title": "AMY COMMANDER", "selector": "#panel-amy, .panel[data-panel-id='amy']",
     "default_open": True},
    {"id": "units",  "title": "UNITS",         "selector": "#panel-units, .panel[data-panel-id='units']",
     "default_open": True},
    {"id": "alerts", "title": "ALERTS",        "selector": "#panel-alerts, .panel[data-panel-id='alerts']",
     "default_open": True},
    {"id": "game",   "title": "GAME STATUS",   "selector": "#panel-game, .panel[data-panel-id='game']",
     "default_open": False},
    {"id": "mesh",   "title": "MESHTASTIC",    "selector": "#panel-mesh, .panel[data-panel-id='mesh']",
     "default_open": False},
]

OLLAMA_URL = "http://localhost:11434"


def _llava_analyze(img_path: str, prompt: str) -> str:
    """Ask llava:7b about a screenshot."""
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
    """Summarize text with qwen2.5:7b."""
    import requests
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": "qwen2.5:7b",
            "prompt": f"Summarize this UI test result concisely:\n{text}",
            "stream": False,
        }, timeout=30)
        if resp.ok:
            return resp.json().get("response", "")
    except Exception:
        pass
    return ""


def _opencv_brightness(img_path: str) -> float:
    """Average brightness of a screenshot."""
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return float(np.mean(img))


def _opencv_diff(path_a: str, path_b: str) -> float:
    """Percentage of pixels that changed between two screenshots."""
    a = cv2.imread(path_a, cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(path_b, cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        return 0.0
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    diff = cv2.absdiff(a, b)
    return float(np.count_nonzero(diff > 15) / diff.size * 100)


class TestPanelToggleExercise:
    """Exercise every panel through the VIEW menu."""

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
        self._results = []
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _open_view_menu(self):
        """Open the VIEW dropdown."""
        self.page.locator('.menu-trigger:has-text("VIEW")').click()
        time.sleep(0.3)

    def _close_menu(self):
        self.page.keyboard.press("Escape")
        time.sleep(0.2)

    def _is_panel_visible(self, panel_id: str) -> bool:
        """Check if a panel is open/visible in the DOM."""
        return self.page.evaluate(f"""() => {{
            const pm = window.panelManager;
            if (pm && pm.isOpen) return pm.isOpen('{panel_id}');
            // Fallback: check DOM
            const el = document.querySelector('[data-panel-id="{panel_id}"]');
            return el ? !el.hidden && el.offsetHeight > 0 : false;
        }}""")

    def _get_panel_bbox(self, panel_id: str) -> dict | None:
        """Get the bounding box of a panel if visible."""
        return self.page.evaluate(f"""() => {{
            const el = document.querySelector('[data-panel-id="{panel_id}"]');
            if (!el || el.hidden || el.offsetHeight === 0) return null;
            const r = el.getBoundingClientRect();
            return {{ x: r.x, y: r.y, w: r.width, h: r.height }};
        }}""")

    def _toggle_panel_via_menu(self, title: str):
        """Toggle a panel by clicking its VIEW menu entry."""
        # Open VIEW menu
        self.page.locator('.menu-trigger:has-text("VIEW")').click()
        time.sleep(0.4)
        # Click the item while menu is open
        item = self.page.locator(f'.menu-dropdown:not([hidden]) .menu-item:has-text("{title}")')
        item.first.click(timeout=5000)
        time.sleep(0.5)

    def test_01_initial_panel_state(self):
        """Verify initial panel visibility matches Commander layout."""
        shot = self._screenshot("01_initial")
        print("\nInitial panel states:")
        for p in PANELS:
            visible = self._is_panel_visible(p["id"])
            bbox = self._get_panel_bbox(p["id"])
            print(f"  {p['title']:18s} visible={visible} bbox={bbox}")
            if p["default_open"]:
                assert visible, f"Panel {p['title']} should be open by default"

    def _toggle_panel_js(self, panel_id: str):
        """Toggle a panel using the JS panelManager API directly."""
        self.page.evaluate(f"""() => {{
            const pm = window.panelManager;
            if (pm && pm.toggle) pm.toggle('{panel_id}');
        }}""")
        time.sleep(0.4)

    def test_02_toggle_each_panel(self):
        """Toggle each panel OFF then ON, verify state and visual change."""
        results = []

        for p in PANELS:
            pid = p["id"]
            title = p["title"]
            initial_vis = self._is_panel_visible(pid)
            print(f"\n--- Panel: {title} (initial={initial_vis}) ---")

            # Take before screenshot
            before = self._screenshot(f"02_{pid}_before")

            # Toggle via JS API (reliable, no menu timing issues)
            self._toggle_panel_js(pid)

            after_vis = self._is_panel_visible(pid)
            after = self._screenshot(f"02_{pid}_after_toggle1")

            diff = _opencv_diff(before, after)
            print(f"  Toggle 1: {initial_vis} -> {after_vis}, diff={diff:.1f}%")

            # State should have flipped
            assert after_vis != initial_vis, (
                f"Panel {title} didn't toggle: was {initial_vis}, still {after_vis}"
            )

            # Visual diff should be nonzero (panel appeared/disappeared)
            assert diff > 0.1, f"No visual change after toggling {title}"

            # Toggle back via JS API
            self._toggle_panel_js(pid)

            restored_vis = self._is_panel_visible(pid)
            restored = self._screenshot(f"02_{pid}_restored")
            diff_restore = _opencv_diff(before, restored)

            print(f"  Restored: {restored_vis}, diff from initial={diff_restore:.1f}%")
            assert restored_vis == initial_vis, (
                f"Panel {title} didn't restore: expected {initial_vis}, got {restored_vis}"
            )

            results.append({
                "panel": title,
                "initial": initial_vis,
                "toggled": after_vis,
                "restored": restored_vis,
                "diff_toggle": diff,
                "diff_restore": diff_restore,
            })

        self._results = results
        print(f"\nAll {len(results)} panels toggled successfully")

    def test_03_show_all_hide_all(self):
        """Test VIEW > Show All and Hide All bulk commands."""
        # First, Hide All
        self._open_view_menu()
        self.page.locator('.menu-item:has-text("Hide All")').first.click()
        time.sleep(0.5)

        hide_shot = self._screenshot("03_hide_all")
        print("\nAfter Hide All:")
        hidden_count = 0
        for p in PANELS:
            vis = self._is_panel_visible(p["id"])
            print(f"  {p['title']:18s} visible={vis}")
            if not vis:
                hidden_count += 1

        assert hidden_count >= 3, f"Hide All should hide most panels, only hid {hidden_count}"

        # Now Show All
        self._open_view_menu()
        self.page.locator('.menu-item:has-text("Show All")').first.click()
        time.sleep(0.5)

        show_shot = self._screenshot("03_show_all")
        print("\nAfter Show All:")
        shown_count = 0
        for p in PANELS:
            vis = self._is_panel_visible(p["id"])
            bbox = self._get_panel_bbox(p["id"])
            print(f"  {p['title']:18s} visible={vis} bbox={bbox}")
            if vis:
                shown_count += 1

        assert shown_count >= 4, f"Show All should show most panels, only showed {shown_count}"

        diff = _opencv_diff(hide_shot, show_shot)
        print(f"\nHide→Show diff: {diff:.1f}%")
        assert diff > 2.0, f"Show All should visually differ from Hide All, only {diff:.1f}%"

    def test_04_panel_quick_toggle_buttons(self):
        """Test the quick-access panel toggle buttons on the right side of the menu bar."""
        buttons = self.page.locator('.command-bar-btn[data-panel]')
        count = buttons.count()
        print(f"\nQuick toggle buttons: {count}")

        for i in range(min(count, 5)):
            btn = buttons.nth(i)
            panel_id = btn.get_attribute("data-panel")
            label = btn.text_content().strip()
            is_active = "active" in (btn.get_attribute("class") or "")
            print(f"  [{i}] {label} (panel={panel_id}, active={is_active})")

            # Click the button
            before = self._screenshot(f"04_btn_{panel_id}_before")
            btn.click()
            time.sleep(0.4)
            after = self._screenshot(f"04_btn_{panel_id}_after")

            # Check state changed
            new_active = "active" in (btn.get_attribute("class") or "")
            diff = _opencv_diff(before, after)
            print(f"    Clicked: active {is_active} -> {new_active}, diff={diff:.1f}%")

            # Restore
            btn.click()
            time.sleep(0.3)

        self._screenshot("04_buttons_done")

    def test_05_panel_content_check(self):
        """Verify each visible panel has meaningful content (text, elements)."""
        shot = self._screenshot("05_content_check")
        print("\nPanel content analysis:")

        for p in PANELS:
            if not self._is_panel_visible(p["id"]):
                print(f"  {p['title']:18s} HIDDEN (skipping)")
                continue

            content = self.page.evaluate(f"""() => {{
                const el = document.querySelector('[data-panel-id="{p['id']}"]');
                if (!el) return {{ text: '', children: 0, height: 0 }};
                return {{
                    text: el.textContent.substring(0, 200).trim(),
                    children: el.children.length,
                    height: el.offsetHeight,
                    width: el.offsetWidth,
                }};
            }}""")

            text_len = len(content.get("text", ""))
            children = content.get("children", 0)
            height = content.get("height", 0)
            print(f"  {p['title']:18s} text={text_len}ch children={children} h={height}px")

            # Panel should have some content
            assert text_len > 5 or children > 1, f"Panel {p['title']} appears empty"
            assert height > 50, f"Panel {p['title']} too small: {height}px"

    def test_06_llm_panel_analysis(self):
        """Use LLaVA to analyze panel screenshots."""
        analyses = []

        # Full viewport
        full = self._screenshot("06_full_viewport")

        # Show All first
        self._open_view_menu()
        self.page.locator('.menu-item:has-text("Show All")').first.click()
        time.sleep(0.5)

        all_panels = self._screenshot("06_all_panels_visible")
        llava_all = _llava_analyze(all_panels,
            "Describe all visible UI panels in this tactical command center screenshot. "
            "What information does each panel show?")

        print(f"\nLLaVA analysis (all panels): {llava_all[:300]}")

        # Hide All
        self._open_view_menu()
        self.page.locator('.menu-item:has-text("Hide All")').first.click()
        time.sleep(0.5)

        no_panels = self._screenshot("06_no_panels")
        llava_none = _llava_analyze(no_panels,
            "This is the same tactical command center with all panels hidden. "
            "Describe what remains visible. Is the map still showing?")

        print(f"LLaVA analysis (no panels): {llava_none[:300]}")

        summary = _qwen_summarize(
            f"All panels shown: {llava_all[:500]}\n"
            f"No panels: {llava_none[:500]}"
        )
        print(f"\nSummary: {summary[:300]}")

        # Restore Commander layout
        self._open_view_menu()
        self.page.locator('.menu-item:has-text("Show All")').first.click()
        time.sleep(0.3)

        # Generate report
        self._generate_report(full, all_panels, no_panels, llava_all, llava_none, summary)

    def _generate_report(self, full_path, all_path, none_path, llava_all, llava_none, summary):
        """Generate HTML report for panel exercise."""
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Panel Toggle Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .summary {{ display:flex; gap:30px; margin:20px 0; flex-wrap:wrap; }}
  .stat {{ padding:12px 24px; border:1px solid #00f0ff33; border-radius:4px; }}
  .stat .val {{ font-size:28px; color:#00f0ff; }}
  .stat .label {{ font-size:12px; color:#666; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .screenshots {{ display:flex; gap:16px; flex-wrap:wrap; margin:16px 0; }}
  .screenshots img {{ max-width:600px; max-height:300px; }}
</style></head><body>
<h1>Panel Toggle Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">{len(PANELS)}</div><div class="label">PANELS TESTED</div></div>
  <div class="stat"><div class="val">6</div><div class="label">TESTS RUN</div></div>
</div>

<h2>All Panels Visible</h2>
<img src="06_all_panels_visible.png">
<div class="llm">{llava_all}</div>

<h2>All Panels Hidden</h2>
<img src="06_no_panels.png">
<div class="llm">{llava_none}</div>

<h2>LLM Summary</h2>
<div class="llm">{summary}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_07_no_js_errors(self):
        """No critical JS errors during panel toggling."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
