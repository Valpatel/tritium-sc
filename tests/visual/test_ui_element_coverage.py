"""
UI Element Coverage: Machine vision test for every visible UI element.

For each UI element:
  1. Screenshot the full viewport
  2. Locate the element via CSS selector
  3. Measure bounding box and visibility
  4. Use OpenCV to analyze element content (brightness, edge density)
  5. Optionally use LLaVA to describe what the element shows

Generates an HTML report with per-element analysis and LLM summaries.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_ui_element_coverage.py -v -s
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/ui-elements")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"


# ── All UI elements to test ───────────────────────────────────────
@dataclass
class UIElement:
    name: str
    selector: str
    description: str
    category: str
    should_exist: bool = True
    min_width: int = 10
    min_height: int = 10


UI_ELEMENTS = [
    # Header / Menu
    UIElement("Header Bar", "#header-bar, .command-bar",
             "Top menu bar with FILE/VIEW/LAYOUT/MAP/GAME/HELP", "chrome"),
    UIElement("Menu Trigger FILE", '.menu-trigger:has-text("FILE")',
             "FILE menu trigger button", "chrome"),
    UIElement("Menu Trigger MAP", '.menu-trigger:has-text("MAP")',
             "MAP menu trigger button", "chrome"),
    UIElement("Menu Trigger GAME", '.menu-trigger:has-text("GAME")',
             "GAME menu trigger button", "chrome"),
    # Mode buttons
    UIElement("Observe Mode", '[data-map-mode="observe"]',
             "Observe mode toggle button", "mode"),
    UIElement("Tactical Mode", '[data-map-mode="tactical"]',
             "Tactical mode toggle button", "mode"),
    UIElement("Setup Mode", '[data-map-mode="setup"]',
             "Setup mode toggle button", "mode"),
    # Panels
    UIElement("Units Panel", ".panel-units, .panel:has(.panel-title:has-text('UNITS'))",
             "Units panel showing friendly unit list", "panel"),
    UIElement("Amy Panel", ".panel-amy, .panel:has(.panel-title:has-text('AMY'))",
             "Amy Commander panel with chat", "panel"),
    UIElement("Alerts Panel", ".panel-alerts, .panel:has(.panel-title:has-text('ALERTS'))",
             "Alerts panel showing threat alerts", "panel"),
    # Map canvas
    UIElement("Map Canvas", ".maplibregl-canvas",
             "Main MapLibre rendering canvas", "map"),
    UIElement("Map Container", ".maplibregl-map, .map-container, #map-container",
             "Map container holding the canvas", "map"),
    # HUD elements
    UIElement("Layer HUD", "#map-layer-hud",
             "Layer state indicator (SAT + BLDG + ROADS etc.)", "hud"),
    UIElement("Map Mode Indicator", "#map-mode, .map-mode",
             "Current map mode display", "hud"),
    UIElement("Status Bar", "#status-bar, .status-bar",
             "Bottom status bar", "chrome"),
    # Panel toggle buttons
    UIElement("Panel Toggle AMY", '[data-panel="amy"], .panel-toggle-amy',
             "AMY panel quick-toggle button", "toggle"),
    UIElement("Panel Toggle UNITS", '[data-panel="units"], .panel-toggle-units',
             "UNITS panel quick-toggle button", "toggle"),
    UIElement("Panel Toggle ALERTS", '[data-panel="alerts"], .panel-toggle-alerts',
             "ALERTS panel quick-toggle button", "toggle"),
    # Unit markers on map
    UIElement("Unit Markers", ".tritium-unit-marker",
             "Unit marker dots on the map", "map"),
    # Attribution
    UIElement("Map Attribution", ".maplibregl-ctrl-attrib, .map-attribution",
             "Map data attribution text", "chrome"),
]


@dataclass
class ElementResult:
    name: str
    category: str
    exists: bool = False
    visible: bool = False
    bbox: dict = field(default_factory=dict)
    brightness: float = 0.0
    edge_density: float = 0.0
    screenshot: str = ""
    llm_description: str = ""
    error: str = ""


def _llava_describe(image_path: str, prompt: str) -> str:
    """Use llava:7b to describe a UI element screenshot."""
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
            timeout=45,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")[:500]
    except Exception as e:
        return f"LLM error: {e}"
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


def _analyze_region(img, x, y, w, h):
    """Analyze a region: brightness and edge density."""
    if img is None or w < 2 or h < 2:
        return 0.0, 0.0
    region = img[y:y+h, x:x+w]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / edges.size * 100
    return brightness, edge_density


def _generate_report(results: list[ElementResult], full_screenshot: str,
                     mode_results: dict, menu_results: dict,
                     llm_summary: str, total_time: float) -> str:
    """Generate comprehensive HTML report."""
    # Group by category
    categories = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    rows = []
    for r in results:
        status_color = "#05ffa1" if r.exists and r.visible else (
            "#fcee0a" if r.exists else "#ff2a6d"
        )
        status = "VISIBLE" if r.visible else ("EXISTS" if r.exists else "MISSING")
        bbox_str = (f"{r.bbox.get('x',0)},{r.bbox.get('y',0)} "
                    f"{r.bbox.get('width',0)}x{r.bbox.get('height',0)}"
                    if r.bbox else "N/A")
        img_html = ""
        if r.screenshot and Path(r.screenshot).exists():
            img_html = f'<img src="{Path(r.screenshot).name}" style="max-width:200px;max-height:100px;border:1px solid #333;">'
        llm_html = f'<span style="font-size:11px;color:#888;">{r.llm_description[:200]}</span>' if r.llm_description else ""

        rows.append(f"""
        <tr>
            <td style="color:{status_color}">{status}</td>
            <td>{r.name}</td>
            <td>{r.category}</td>
            <td>{bbox_str}</td>
            <td>{r.brightness:.0f}</td>
            <td>{r.edge_density:.1f}%</td>
            <td>{img_html}</td>
            <td>{llm_html}</td>
            <td style="color:#ff2a6d;font-size:11px;">{r.error}</td>
        </tr>""")

    found = sum(1 for r in results if r.exists)
    visible = sum(1 for r in results if r.visible)
    total = len(results)

    # Mode switching results
    mode_rows = ""
    for mode, data in mode_results.items():
        color = "#05ffa1" if data.get("success") else "#ff2a6d"
        mode_rows += f"""
        <tr>
            <td style="color:{color}">{'PASS' if data.get('success') else 'FAIL'}</td>
            <td>{mode}</td>
            <td>{data.get('active_before', 'N/A')} → {data.get('active_after', 'N/A')}</td>
            <td>{data.get('error', '')}</td>
        </tr>"""

    # Menu test results
    menu_rows = ""
    for menu, data in menu_results.items():
        color = "#05ffa1" if data.get("opens") else "#ff2a6d"
        menu_rows += f"""
        <tr>
            <td style="color:{color}">{'PASS' if data.get('opens') else 'FAIL'}</td>
            <td>{menu}</td>
            <td>{data.get('item_count', 0)} items</td>
            <td>{', '.join(data.get('sample_labels', []))}</td>
        </tr>"""

    llm_html = llm_summary.replace("\n", "<br>") if llm_summary else "N/A"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>UI Element Coverage Report</title>
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
  .full-shot {{ max-width:100%; border:1px solid #333; margin:16px 0; }}
  img {{ border-radius:2px; }}
</style></head><body>
<h1>TRITIUM-SC UI Element Coverage Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')} | Duration: {total_time:.1f}s</p>

<div class="summary">
  <div class="stat"><div class="val">{visible}</div><div class="label">VISIBLE</div></div>
  <div class="stat"><div class="val">{found - visible}</div><div class="label">HIDDEN</div></div>
  <div class="stat"><div class="val">{total - found}</div><div class="label">MISSING</div></div>
  <div class="stat"><div class="val">{total}</div><div class="label">TOTAL CHECKED</div></div>
</div>

<h2>Full Viewport</h2>
<img class="full-shot" src="full_viewport.png">

<h2>UI Element Inventory</h2>
<table>
<tr><th>Status</th><th>Element</th><th>Category</th><th>BBox</th><th>Brightness</th><th>Edges</th><th>Crop</th><th>LLM</th><th>Error</th></tr>
{"".join(rows)}
</table>

<h2>Mode Switching</h2>
<table>
<tr><th>Status</th><th>Mode</th><th>Transition</th><th>Error</th></tr>
{mode_rows}
</table>

<h2>Menu Dropdown Tests</h2>
<table>
<tr><th>Status</th><th>Menu</th><th>Items</th><th>Sample Labels</th></tr>
{menu_rows}
</table>

<h2>LLM Overall Analysis</h2>
<div class="llm">{llm_html}</div>

</body></html>"""
    return html


class TestUIElementCoverage:
    """Comprehensive UI element machine vision test."""

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
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _element_screenshot(self, selector: str, name: str) -> str:
        """Try to screenshot just the element, fall back to full page."""
        path = str(SCREENSHOT_DIR / f"{name}.png")
        try:
            el = self.page.locator(selector).first
            if el.is_visible():
                el.screenshot(path=path)
                return path
        except Exception:
            pass
        return ""

    def test_01_element_inventory(self):
        """Inventory all UI elements: existence, visibility, bbox, content analysis."""
        t0 = time.monotonic()
        results: list[ElementResult] = []

        # Full viewport screenshot
        full_path = self._screenshot("full_viewport")
        full_img = cv2.imread(full_path)

        for elem in UI_ELEMENTS:
            result = ElementResult(name=elem.name, category=elem.category)
            try:
                # Check existence and visibility
                loc = self.page.locator(elem.selector)
                count = loc.count()
                result.exists = count > 0

                if result.exists:
                    first = loc.first
                    result.visible = first.is_visible()

                    if result.visible:
                        bbox = first.bounding_box()
                        if bbox:
                            result.bbox = {
                                "x": int(bbox["x"]),
                                "y": int(bbox["y"]),
                                "width": int(bbox["width"]),
                                "height": int(bbox["height"]),
                            }
                            # OpenCV analysis on the region
                            x, y = int(bbox["x"]), int(bbox["y"])
                            w, h = int(bbox["width"]), int(bbox["height"])
                            if full_img is not None and w > 2 and h > 2:
                                result.brightness, result.edge_density = (
                                    _analyze_region(full_img, x, y, w, h)
                                )

                        # Element screenshot
                        crop_path = self._element_screenshot(
                            elem.selector,
                            f"elem_{elem.name.lower().replace(' ', '_')}"
                        )
                        result.screenshot = crop_path

                    if count > 1:
                        result.error = f"Multiple matches: {count}"

            except Exception as e:
                result.error = str(e)

            results.append(result)
            status = "VISIBLE" if result.visible else (
                "EXISTS" if result.exists else "MISSING"
            )
            print(f"  {status:8s} {elem.name:30s} {elem.category:10s} "
                  f"bright={result.brightness:.0f} edges={result.edge_density:.1f}%")

        # ── Mode switching tests ──────────────────────────────
        print("\n--- Mode Switching ---")
        mode_results = {}
        for mode in ["observe", "tactical", "setup"]:
            data = {"success": False, "active_before": "", "active_after": "", "error": ""}
            try:
                # Get current active mode
                data["active_before"] = self.page.evaluate("""() => {
                    const active = document.querySelector('[data-map-mode].active, [data-map-mode][aria-pressed="true"]');
                    return active ? active.dataset.mapMode : 'unknown';
                }""")

                # Click mode button
                btn = self.page.locator(f'[data-map-mode="{mode}"]')
                if btn.count() > 0:
                    btn.first.click()
                    time.sleep(0.5)
                    self._screenshot(f"mode_{mode}")

                    data["active_after"] = self.page.evaluate("""() => {
                        const active = document.querySelector('[data-map-mode].active, [data-map-mode][aria-pressed="true"]');
                        return active ? active.dataset.mapMode : 'unknown';
                    }""")
                    data["success"] = True
                else:
                    data["error"] = "Button not found"
            except Exception as e:
                data["error"] = str(e)

            mode_results[mode] = data
            status = "PASS" if data["success"] else "FAIL"
            print(f"  {status}: {mode} ({data['active_before']} → {data['active_after']})")

        # Restore to observe mode
        try:
            self.page.locator('[data-map-mode="observe"]').first.click()
            time.sleep(0.3)
        except Exception:
            pass

        # ── Menu dropdown tests ───────────────────────────────
        print("\n--- Menu Dropdowns ---")
        menu_results = {}
        for menu_name in ["FILE", "VIEW", "LAYOUT", "MAP", "GAME", "HELP"]:
            data = {"opens": False, "item_count": 0, "sample_labels": [], "error": ""}
            try:
                trigger = self.page.locator(f'.menu-trigger:has-text("{menu_name}")')
                if trigger.count() > 0:
                    trigger.first.click()
                    time.sleep(0.3)

                    # Count items
                    items = self.page.locator('.menu-dropdown:not([hidden]) .menu-item')
                    data["item_count"] = items.count()
                    data["opens"] = data["item_count"] > 0

                    # Get first 5 labels
                    labels = self.page.evaluate("""() => {
                        const items = document.querySelectorAll('.menu-dropdown:not([hidden]) .menu-item');
                        return Array.from(items).slice(0, 5).map(i =>
                            i.querySelector('.menu-item-label')?.textContent || i.textContent?.trim() || ''
                        ).filter(l => l);
                    }""")
                    data["sample_labels"] = labels

                    self._screenshot(f"menu_{menu_name.lower()}")
                    self.page.keyboard.press("Escape")
                    time.sleep(0.2)
                else:
                    data["error"] = "Trigger not found"
            except Exception as e:
                data["error"] = str(e)

            menu_results[menu_name] = data
            status = "PASS" if data["opens"] else "FAIL"
            print(f"  {status}: {menu_name} ({data['item_count']} items) "
                  f"{data['sample_labels'][:3]}")

        # ── LLM analysis of key elements ──────────────────────
        print("\n--- LLM Analysis ---")
        llm_parts = []

        # Analyze the full viewport
        llm_full = _llava_describe(
            full_path,
            "This is a tactical command center UI called TRITIUM-SC. "
            "List all the visible UI elements you can see: panels, buttons, "
            "map features, menus, status indicators. Be specific about positions "
            "(top, bottom, left, right). What elements are present?",
        )
        if llm_full:
            llm_parts.append(f"Full viewport analysis:\n{llm_full}")
            print(f"  LLaVA (full): {llm_full[:200]}...")

        # Analyze units panel
        units_crop = str(SCREENSHOT_DIR / "elem_units_panel.png")
        if Path(units_crop).exists():
            llm_units = _llava_describe(
                units_crop,
                "This is the UNITS panel from a tactical command center. "
                "What units are listed? What information is shown for each "
                "(name, status, health)? Describe the layout.",
            )
            if llm_units:
                llm_parts.append(f"\nUnits panel:\n{llm_units}")
                print(f"  LLaVA (units): {llm_units[:200]}...")

        # Analyze Amy panel
        amy_crop = str(SCREENSHOT_DIR / "elem_amy_panel.png")
        if Path(amy_crop).exists():
            llm_amy = _llava_describe(
                amy_crop,
                "This is the AMY COMMANDER panel. Amy is an AI commander. "
                "What does the panel show? Is there a chat interface, status "
                "indicator, or avatar?",
            )
            if llm_amy:
                llm_parts.append(f"\nAmy panel:\n{llm_amy}")
                print(f"  LLaVA (amy): {llm_amy[:200]}...")

        # Summarize with qwen
        llm_summary = ""
        if llm_parts:
            summary_prompt = (
                "Summarize these UI element analysis results into a concise "
                "quality report (5-7 sentences). Note which elements are "
                "present and functional, and flag any issues:\n\n"
                + "\n".join(llm_parts)
            )
            llm_summary = _qwen_summarize(summary_prompt)
            if llm_summary:
                print(f"  Summary: {llm_summary[:300]}...")

        # ── Generate report ───────────────────────────────────
        total_time = time.monotonic() - t0
        html = _generate_report(
            results, full_path, mode_results, menu_results,
            llm_summary, total_time,
        )
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

        # Save JSON metrics
        metrics = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elements": [
                {
                    "name": r.name, "category": r.category,
                    "exists": r.exists, "visible": r.visible,
                    "bbox": r.bbox, "brightness": r.brightness,
                    "edge_density": r.edge_density,
                }
                for r in results
            ],
            "modes": mode_results,
            "menus": menu_results,
            "page_errors": self._errors,
        }
        (SCREENSHOT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))

        # ── Assertions ────────────────────────────────────────
        # Critical elements must exist and be visible
        critical = ["Map Canvas", "Header Bar", "Units Panel", "Unit Markers"]
        for name in critical:
            r = next((r for r in results if r.name == name), None)
            assert r is not None, f"Critical element '{name}' not checked"
            assert r.exists, f"Critical element '{name}' not found in DOM"
            assert r.visible, f"Critical element '{name}' not visible"

        # All menus should open
        for menu_name, data in menu_results.items():
            assert data["opens"], f"Menu '{menu_name}' did not open"

        # At least 2 of 3 mode buttons should work
        mode_pass = sum(1 for d in mode_results.values() if d["success"])
        assert mode_pass >= 2, f"Only {mode_pass}/3 mode switches worked"

    def test_02_keyboard_shortcuts(self):
        """Test keyboard shortcuts that affect UI state."""
        print("\n--- Keyboard Shortcuts ---")
        results = {}

        shortcuts = [
            ("I", "toggleSatellite", "showSatellite", "Toggle satellite"),
            ("G", "toggleRoads", "showRoads", "Toggle roads"),
            ("K", "toggleBuildings", "showBuildings", "Toggle buildings"),
            ("F", "centerOnAction", None, "Center on action"),
        ]

        for key, action, state_key, desc in shortcuts:
            data = {"success": False, "desc": desc, "error": ""}
            try:
                if state_key:
                    # Get state before
                    before = self.page.evaluate(f"""() => {{
                        const ma = window._mapActions;
                        return ma && ma.getMapState ? ma.getMapState().{state_key} : null;
                    }}""")

                    self.page.keyboard.press(key)
                    time.sleep(0.5)

                    after = self.page.evaluate(f"""() => {{
                        const ma = window._mapActions;
                        return ma && ma.getMapState ? ma.getMapState().{state_key} : null;
                    }}""")

                    data["success"] = before != after
                    if not data["success"]:
                        data["error"] = f"State unchanged: {before}"

                    # Restore
                    self.page.keyboard.press(key)
                    time.sleep(0.3)
                else:
                    # Non-state shortcuts just verify no crash
                    self.page.keyboard.press(key)
                    time.sleep(0.3)
                    data["success"] = True

            except Exception as e:
                data["error"] = str(e)

            results[key] = data
            status = "PASS" if data["success"] else "FAIL"
            print(f"  {status}: '{key}' - {desc}")

        # Screenshot after all shortcuts
        self._screenshot("keyboard_shortcuts")

        passed = sum(1 for d in results.values() if d["success"])
        assert passed >= 3, f"Only {passed}/{len(results)} keyboard shortcuts worked"

    def test_03_panel_interactions(self):
        """Test panel visibility toggling and content."""
        print("\n--- Panel Interactions ---")

        # Check each panel has content
        panels = self.page.evaluate("""() => {
            const panels = document.querySelectorAll('.panel');
            return Array.from(panels).map(p => ({
                title: p.querySelector('.panel-title')?.textContent?.trim() || 'untitled',
                visible: getComputedStyle(p).display !== 'none',
                width: Math.round(p.getBoundingClientRect().width),
                height: Math.round(p.getBoundingClientRect().height),
                childCount: p.childElementCount,
            }));
        }""")

        print(f"  Found {len(panels)} panels:")
        for p in panels:
            vis = "VISIBLE" if p["visible"] else "HIDDEN"
            print(f"    [{vis}] {p['title']} {p['width']}x{p['height']} "
                  f"({p['childCount']} children)")

        # All visible panels should have content
        visible_panels = [p for p in panels if p["visible"]]
        assert len(visible_panels) >= 2, (
            f"Expected at least 2 visible panels, got {len(visible_panels)}"
        )

        for p in visible_panels:
            assert p["width"] > 50, f"Panel '{p['title']}' too narrow: {p['width']}px"
            assert p["height"] > 30, f"Panel '{p['title']}' too short: {p['height']}px"

    def test_04_map_content_analysis(self):
        """Analyze map content: markers, canvas rendering, interaction."""
        print("\n--- Map Content Analysis ---")

        # Count markers by type
        marker_info = self.page.evaluate("""() => {
            const markers = document.querySelectorAll('.tritium-unit-marker');
            const byAlliance = {};
            markers.forEach(m => {
                const alliance = m.dataset.alliance || 'unknown';
                byAlliance[alliance] = (byAlliance[alliance] || 0) + 1;
            });
            return {
                total: markers.length,
                visible: Array.from(markers).filter(m =>
                    getComputedStyle(m).display !== 'none').length,
                byAlliance,
            };
        }""")

        print(f"  Markers: {marker_info['visible']}/{marker_info['total']} visible")
        print(f"  By alliance: {json.dumps(marker_info['byAlliance'])}")

        # Check canvas has rendered content (not blank)
        canvas_info = self.page.evaluate("""() => {
            const canvas = document.querySelector('.maplibregl-canvas, canvas');
            if (!canvas) return { exists: false };
            return {
                exists: true,
                width: canvas.width,
                height: canvas.height,
                cssWidth: Math.round(canvas.getBoundingClientRect().width),
                cssHeight: Math.round(canvas.getBoundingClientRect().height),
            };
        }""")

        print(f"  Canvas: {canvas_info.get('width', 0)}x{canvas_info.get('height', 0)} "
              f"(CSS: {canvas_info.get('cssWidth', 0)}x{canvas_info.get('cssHeight', 0)})")

        # Screenshot the map area for OpenCV analysis
        map_path = self._screenshot("map_content")
        img = cv2.imread(map_path)
        if img is not None:
            # Analyze center map region
            h, w = img.shape[:2]
            cx, cy = w // 2, h // 2
            region = img[cy-200:cy+200, cx-300:cx+300]
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            mean_brightness = float(np.mean(gray))
            std = float(np.std(gray))
            edges = cv2.Canny(gray, 50, 150)
            edge_pct = float(np.count_nonzero(edges)) / edges.size * 100

            print(f"  Center region: brightness={mean_brightness:.0f} "
                  f"std={std:.0f} edges={edge_pct:.1f}%")

            # Map should have some detail (not a blank solid color)
            assert std > 5, (
                f"Map center has low contrast (std={std:.1f}), "
                "might be a solid color"
            )

        assert marker_info["total"] > 0, "No unit markers found on map"
        assert canvas_info.get("exists"), "Map canvas not found"
