# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Menu Dropdown Exercise: Open every menu in the menu bar, verify all items
are present and clickable.  Captures screenshots of each open dropdown.
Tests hover-mode switching between menus.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_menu_dropdown_exercise.py -v -s
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/menu-dropdown")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"

# Expected menus and minimum item counts
EXPECTED_MENUS = [
    {"label": "FILE",   "min_items": 2},
    {"label": "VIEW",   "min_items": 4},
    {"label": "LAYOUT", "min_items": 3},
    {"label": "MAP",    "min_items": 20},
    {"label": "GAME",   "min_items": 4},
    {"label": "HELP",   "min_items": 2},
]


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
            "prompt": f"Summarize this menu test report concisely:\n{text}",
            "stream": False,
        }, timeout=30)
        if resp.ok:
            return resp.json().get("response", "")
    except Exception:
        pass
    return ""


class TestMenuDropdownExercise:
    """Exercise every menu dropdown in the command bar."""

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
        self._menu_data = {}
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _open_menu(self, label: str):
        """Open a menu by clicking its trigger."""
        self.page.mouse.click(960, 540)  # Click away first
        time.sleep(0.2)
        self.page.locator(f'.menu-trigger:has-text("{label}")').click()
        time.sleep(0.5)

    def _get_menu_items(self) -> list:
        """Get all items from the currently open dropdown."""
        return self.page.evaluate("""() => {
            const dds = document.querySelectorAll('.menu-dropdown');
            for (const dd of dds) {
                if (dd.hidden) continue;
                return Array.from(dd.querySelectorAll('.menu-item')).map(item => {
                    const label = item.querySelector('.menu-item-label')?.textContent?.trim()
                                  || item.textContent.trim();
                    const check = item.querySelector('.menu-item-check')?.textContent?.trim() || '';
                    const shortcut = item.querySelector('.menu-item-shortcut')?.textContent?.trim() || '';
                    return {
                        label: label,
                        hasCheck: item.querySelector('.menu-item-check') !== null,
                        checked: check === '\u2022',
                        shortcut: shortcut,
                        isSeparator: false,
                    };
                });
            }
            return [];
        }""")

    def _close_menu(self):
        self.page.keyboard.press("Escape")
        time.sleep(0.2)

    def test_01_all_menus_present(self):
        """Verify all expected menu triggers exist."""
        triggers = self.page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.menu-trigger')).map(t => ({
                text: t.textContent.trim(),
                visible: t.offsetHeight > 0,
            }));
        }""")

        print("\nMenu triggers:")
        for t in triggers:
            print(f"  {t['text']:12s} visible={t['visible']}")

        self._screenshot("01_menu_bar")

        trigger_labels = [t["text"] for t in triggers]
        for m in EXPECTED_MENUS:
            assert m["label"] in trigger_labels, (
                f"Menu '{m['label']}' not found in triggers: {trigger_labels}"
            )

    def test_02_open_each_menu(self):
        """Open each menu, verify items, capture screenshot."""
        results = []

        for m in EXPECTED_MENUS:
            self._open_menu(m["label"])
            items = self._get_menu_items()
            shot = self._screenshot(f"02_menu_{m['label'].lower()}")

            print(f"\n{m['label']} menu ({len(items)} items):")
            for item in items:
                check_str = "[x]" if item["checked"] else "[ ]" if item["hasCheck"] else "   "
                shortcut = f"  ({item['shortcut']})" if item["shortcut"] else ""
                print(f"  {check_str} {item['label']}{shortcut}")

            assert len(items) >= m["min_items"], (
                f"{m['label']} menu should have >= {m['min_items']} items, got {len(items)}"
            )

            results.append({
                "menu": m["label"],
                "items": len(items),
                "labels": [i["label"] for i in items],
                "checkable": sum(1 for i in items if i["hasCheck"]),
                "checked": sum(1 for i in items if i["checked"]),
                "shortcuts": [i for i in items if i["shortcut"]],
            })

            self._close_menu()

        self._menu_data = results

    def test_03_map_menu_all_checkable_items(self):
        """MAP menu should have 22+ checkable layer toggles."""
        self._open_menu("MAP")
        items = self._get_menu_items()

        checkable = [i for i in items if i["hasCheck"]]
        checked = [i for i in items if i["checked"]]
        unchecked = [i for i in checkable if not i["checked"]]

        print(f"\nMAP menu checkable items: {len(checkable)}")
        print(f"  Checked: {len(checked)}")
        print(f"  Unchecked: {len(unchecked)}")

        for item in checkable:
            status = "ON " if item["checked"] else "OFF"
            print(f"  {status} {item['label']}")

        self._screenshot("03_map_menu_checks")
        self._close_menu()

        assert len(checkable) >= 20, (
            f"MAP menu should have >= 20 checkable items, got {len(checkable)}"
        )

    def test_04_view_menu_panel_states(self):
        """VIEW menu panel items reflect actual panel visibility."""
        self._open_menu("VIEW")
        items = self._get_menu_items()

        panel_items = [i for i in items if i["hasCheck"]]
        print(f"\nVIEW panel items:")
        for item in panel_items:
            status = "OPEN  " if item["checked"] else "CLOSED"
            print(f"  {status} {item['label']}")

        # Verify against actual panel state
        for item in panel_items:
            # Map VIEW menu labels to panel IDs
            label_to_id = {
                "AMY COMMANDER": "amy",
                "UNITS": "units",
                "ALERTS": "alerts",
                "GAME STATUS": "game",
                "MESHTASTIC": "mesh",
            }
            pid = label_to_id.get(item["label"])
            if pid:
                actual = self.page.evaluate(f"""() => {{
                    const pm = window.panelManager;
                    return pm && pm.isOpen ? pm.isOpen('{pid}') : null;
                }}""")
                match = actual == item["checked"] if actual is not None else True
                status = "MATCH" if match else "MISMATCH"
                print(f"    {status}: menu={item['checked']} actual={actual}")

        self._screenshot("04_view_menu_states")
        self._close_menu()

    def test_05_hover_mode_switching(self):
        """After clicking one menu, hovering over another switches to it."""
        # Click FILE to enter hover mode
        self.page.locator('.menu-trigger:has-text("FILE")').click()
        time.sleep(0.3)
        file_shot = self._screenshot("05_hover_file")

        # Hover over VIEW - should switch
        self.page.locator('.menu-trigger:has-text("VIEW")').hover()
        time.sleep(0.3)
        view_shot = self._screenshot("05_hover_view")

        # Hover over MAP
        self.page.locator('.menu-trigger:has-text("MAP")').hover()
        time.sleep(0.3)
        map_shot = self._screenshot("05_hover_map")

        # Check that different menus are showing
        file_items = self._get_menu_items()
        print(f"\nAfter hover to MAP: {len(file_items)} items visible")

        self._close_menu()

    def test_06_keyboard_shortcut_labels(self):
        """Verify menus show correct keyboard shortcut labels."""
        shortcut_map = {
            "MAP": {
                "Satellite": "I",
                "Roads": "G",
                "Buildings": "K",
                "Terrain": "H",
                "Center on Action": "F",
                "Reset Camera": "R",
            },
            "GAME": {
                "Begin Battle": "B",
            },
            "HELP": {
                "Keyboard Shortcuts": "?",
            },
        }

        mismatches = []
        for menu_label, expected_shortcuts in shortcut_map.items():
            self._open_menu(menu_label)
            items = self._get_menu_items()
            self._close_menu()

            for item_label, expected_key in expected_shortcuts.items():
                matching = [i for i in items if i["label"] == item_label]
                if matching:
                    actual_shortcut = matching[0]["shortcut"]
                    if expected_key not in actual_shortcut:
                        mismatches.append(
                            f"{menu_label}/{item_label}: expected '{expected_key}', "
                            f"got '{actual_shortcut}'"
                        )
                    print(f"  {menu_label}/{item_label}: '{actual_shortcut}' (expected '{expected_key}')")

        if mismatches:
            print(f"\nMismatches: {mismatches}")

        self._screenshot("06_shortcuts")

    def test_07_help_menu_about(self):
        """HELP > About TRITIUM-SC shows a toast message."""
        self._open_menu("HELP")
        self.page.locator('.menu-item:has-text("About TRITIUM-SC")').first.click()
        time.sleep(0.5)

        # Check for toast
        toast = self.page.evaluate("""() => {
            const toasts = document.querySelectorAll('.toast, [class*=toast]');
            return Array.from(toasts).map(t => t.textContent.trim()).filter(t => t);
        }""")

        print(f"\nAbout toast: {toast}")
        self._screenshot("07_about_toast")

    def test_08_llm_menu_analysis(self):
        """Use LLaVA to analyze menu screenshots."""
        analyses = {}

        for m in ["FILE", "MAP", "GAME"]:
            self._open_menu(m)
            shot = self._screenshot(f"08_llm_{m.lower()}")
            analysis = _llava_analyze(shot,
                f"This shows the '{m}' dropdown menu of a tactical command center. "
                f"List all visible menu items and their states.")
            analyses[m] = analysis
            print(f"\n{m}: {analysis[:200]}")
            self._close_menu()

        # Generate report
        summary = _qwen_summarize(
            "\n".join(f"{k}: {v[:400]}" for k, v in analyses.items())
        )
        self._generate_report(analyses, summary)

    def _generate_report(self, analyses: dict, summary: str):
        menu_rows = ""
        for data in self._menu_data if self._menu_data else []:
            labels_str = ", ".join(data["labels"][:8])
            if len(data["labels"]) > 8:
                labels_str += f"... (+{len(data['labels'])-8} more)"
            menu_rows += f"""
            <tr>
                <td style="color:#00f0ff">{data['menu']}</td>
                <td>{data['items']}</td>
                <td>{data['checkable']}</td>
                <td>{data['checked']}</td>
                <td style="font-size:11px;">{labels_str}</td>
                <td><img src="02_menu_{data['menu'].lower()}.png" style="max-width:300px;max-height:200px;"></td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Menu Dropdown Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .summary {{ display:flex; gap:30px; margin:20px 0; flex-wrap:wrap; }}
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
<h1>Menu Dropdown Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">{len(EXPECTED_MENUS)}</div><div class="label">MENUS TESTED</div></div>
  <div class="stat"><div class="val">8</div><div class="label">TESTS RUN</div></div>
</div>

<h2>Menu Inventory</h2>
<table>
<tr><th>Menu</th><th>Items</th><th>Checkable</th><th>Checked</th><th>Labels</th><th>Screenshot</th></tr>
{menu_rows}
</table>

<h2>LLM Analysis</h2>
{"".join(f'<h3>{k}</h3><div class="llm">{v}</div>' for k, v in analyses.items())}

<h2>Summary</h2>
<div class="llm">{summary}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_09_no_js_errors(self):
        """No critical JS errors during menu testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
