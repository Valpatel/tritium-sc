# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
DOM Inventory Exercise: Audit all interactive UI elements in the Command
Center. Inventories buttons, inputs, overlays, panels, menus, indicators,
and verifies they're properly structured and accessible.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_dom_inventory.py -v -s
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/dom-inventory")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"


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


class TestDOMInventory:
    """Audit all UI elements in the Command Center."""

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
        self._inventory = {}
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    # --- Overlays ---

    def test_01_overlay_inventory(self):
        """Audit all overlay elements (hidden by default)."""
        overlays = self.page.evaluate("""() => {
            const ids = [
                'chat-overlay', 'help-overlay', 'modal-overlay',
                'game-over-overlay',
            ];
            return ids.map(id => {
                const el = document.getElementById(id);
                return {
                    id: id,
                    exists: el !== null,
                    hidden: el ? el.hidden : null,
                    classList: el ? Array.from(el.classList) : [],
                    childCount: el ? el.children.length : 0,
                };
            });
        }""")

        print("\nOverlay inventory:")
        for o in overlays:
            status = "EXISTS" if o["exists"] else "MISSING"
            hidden = "hidden" if o.get("hidden") else "visible"
            print(f"  {o['id']:22s} {status:7s} {hidden:7s} children={o['childCount']}")

        self._inventory["overlays"] = overlays
        self._screenshot("01_overlays")

        for o in overlays:
            assert o["exists"], f"Overlay '{o['id']}' should exist"
            assert o["hidden"], f"Overlay '{o['id']}' should be hidden by default"

    # --- Containers ---

    def test_02_container_inventory(self):
        """Audit main container elements."""
        containers = self.page.evaluate("""() => {
            const selectors = {
                'map-container': '.maplibregl-map, #map-container, #map, .map-container',
                'toast-container': '#toast-container',
                'minimap-container': '#minimap-container',
                'center-banner': '#center-banner',
                'command-bar': '.command-bar',
                'status-bar': '.status-bar, #status-bar',
                'panel-container': '.panel-container',
            };

            return Object.entries(selectors).map(([name, sel]) => {
                const el = document.querySelector(sel);
                return {
                    name: name,
                    exists: el !== null,
                    visible: el ? el.offsetHeight > 0 : false,
                    dimensions: el ? {
                        w: el.offsetWidth,
                        h: el.offsetHeight,
                    } : null,
                };
            });
        }""")

        print("\nContainer inventory:")
        for c in containers:
            dim = f"{c['dimensions']['w']}x{c['dimensions']['h']}" if c["dimensions"] else "N/A"
            vis = "visible" if c.get("visible") else "hidden"
            print(f"  {c['name']:20s} {'EXISTS' if c['exists'] else 'MISSING':7s} {vis:7s} {dim}")

        self._inventory["containers"] = containers
        self._screenshot("02_containers")

        critical = ["map-container", "toast-container", "command-bar", "status-bar"]
        for c in containers:
            if c["name"] in critical:
                assert c["exists"], f"Container '{c['name']}' should exist"

    # --- Buttons ---

    def test_03_button_inventory(self):
        """Audit all buttons in the UI."""
        buttons = self.page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            return Array.from(btns).map(b => ({
                text: b.textContent.trim().substring(0, 50),
                class: b.className.substring(0, 60),
                ariaLabel: b.getAttribute('aria-label') || '',
                dataAction: b.dataset?.action || '',
                visible: b.offsetHeight > 0,
                disabled: b.disabled,
            }));
        }""")

        visible_btns = [b for b in buttons if b.get("visible")]
        hidden_btns = [b for b in buttons if not b.get("visible")]

        print(f"\nButton inventory: {len(buttons)} total ({len(visible_btns)} visible, {len(hidden_btns)} hidden)")
        print("\nVisible buttons:")
        for b in visible_btns[:15]:
            label = b["text"] or b["ariaLabel"] or b["dataAction"] or "(unlabeled)"
            print(f"  {label[:30]:30s} class={b['class'][:40]}")

        self._inventory["buttons"] = {"total": len(buttons), "visible": len(visible_btns)}
        self._screenshot("03_buttons")

        assert len(visible_btns) >= 5, f"Should have at least 5 visible buttons, got {len(visible_btns)}"

    # --- Inputs ---

    def test_04_input_inventory(self):
        """Audit all input/select elements."""
        inputs = self.page.evaluate("""() => {
            const inputs = document.querySelectorAll('input, select, textarea');
            return Array.from(inputs).map(inp => ({
                tag: inp.tagName.toLowerCase(),
                type: inp.type || '',
                id: inp.id || '',
                placeholder: inp.placeholder || '',
                ariaLabel: inp.getAttribute('aria-label') || '',
                visible: inp.offsetHeight > 0,
            }));
        }""")

        print(f"\nInput inventory: {len(inputs)} total")
        for inp in inputs:
            label = inp["placeholder"] or inp["ariaLabel"] or inp["id"] or "(unlabeled)"
            vis = "visible" if inp.get("visible") else "hidden"
            print(f"  <{inp['tag']}> type={inp['type']:10s} {vis:7s} {label}")

        self._inventory["inputs"] = inputs
        self._screenshot("04_inputs")

    # --- Data elements ---

    def test_05_data_binding_inventory(self):
        """Audit elements with data-bind attributes (reactive UI)."""
        bindings = self.page.evaluate("""() => {
            const els = document.querySelectorAll('[data-bind]');
            return Array.from(els).map(el => ({
                bind: el.dataset.bind,
                tag: el.tagName.toLowerCase(),
                text: el.textContent.trim().substring(0, 60),
                visible: el.offsetHeight > 0,
            }));
        }""")

        print(f"\nData binding inventory: {len(bindings)} elements")
        for b in bindings[:20]:
            vis = "visible" if b.get("visible") else "hidden"
            print(f"  data-bind=\"{b['bind']}\" <{b['tag']}> {vis} text=\"{b['text'][:40]}\"")

        self._inventory["bindings"] = bindings
        self._screenshot("05_bindings")

        assert len(bindings) >= 5, f"Should have at least 5 data-bound elements, got {len(bindings)}"

    # --- ARIA/accessibility ---

    def test_06_aria_inventory(self):
        """Audit ARIA attributes for accessibility."""
        aria = self.page.evaluate("""() => {
            const labelledEls = document.querySelectorAll('[aria-label]');
            const roleEls = document.querySelectorAll('[role]');
            const liveEls = document.querySelectorAll('[aria-live]');

            return {
                ariaLabels: Array.from(labelledEls).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    label: el.getAttribute('aria-label'),
                    visible: el.offsetHeight > 0,
                })),
                roles: Array.from(roleEls).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role'),
                })),
                liveRegions: Array.from(liveEls).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    live: el.getAttribute('aria-live'),
                    text: el.textContent.trim().substring(0, 60),
                })),
            };
        }""")

        print(f"\nARIA inventory:")
        print(f"  aria-label elements: {len(aria['ariaLabels'])}")
        print(f"  role elements: {len(aria['roles'])}")
        print(f"  aria-live regions: {len(aria['liveRegions'])}")

        for a in aria["ariaLabels"][:10]:
            print(f"    <{a['tag']}> aria-label=\"{a['label']}\"")

        self._inventory["aria"] = aria
        self._screenshot("06_aria")

    # --- Map markers ---

    def test_07_map_marker_inventory(self):
        """Audit all map markers and their types."""
        markers = self.page.evaluate("""() => {
            const markers = document.querySelectorAll('.maplibregl-marker');
            const types = {};
            markers.forEach(m => {
                const cls = m.className || '';
                const key = cls.includes('hostile') ? 'hostile' :
                            cls.includes('neutral') ? 'neutral' : 'friendly';
                types[key] = (types[key] || 0) + 1;
            });
            return {
                total: markers.length,
                types: types,
                // Sample a few marker positions
                samples: Array.from(markers).slice(0, 5).map(m => ({
                    x: Math.round(parseFloat(m.style.left) || 0),
                    y: Math.round(parseFloat(m.style.top) || 0),
                    class: m.className.substring(0, 60),
                })),
            };
        }""")

        print(f"\nMap marker inventory: {markers['total']} total")
        print(f"  Types: {markers['types']}")

        self._inventory["markers"] = markers
        self._screenshot("07_markers")

        assert markers["total"] > 0, "Should have map markers"

    # --- Panel system ---

    def test_08_panel_system_inventory(self):
        """Audit all panels registered in the panel manager."""
        panels = self.page.evaluate("""() => {
            const pm = window.panelManager;
            if (!pm) return { found: false };

            // Try to get all panels
            const panelIds = pm._panelDefs ? Object.keys(pm._panelDefs) :
                             pm.panels ? Array.from(pm.panels.keys()) : [];
            const states = {};
            panelIds.forEach(id => {
                states[id] = pm.isOpen ? pm.isOpen(id) : null;
            });

            return {
                found: true,
                panelIds: panelIds,
                states: states,
                count: panelIds.length,
            };
        }""")

        print(f"\nPanel system inventory:")
        if panels.get("found"):
            print(f"  Registered panels: {panels['count']}")
            for pid, state in panels.get("states", {}).items():
                status = "OPEN" if state else "CLOSED"
                print(f"    {pid:20s} {status}")
        else:
            print("  Panel manager not found")

        self._inventory["panels"] = panels
        self._screenshot("08_panels")

    # --- Store data ---

    def test_09_store_inventory(self):
        """Audit TritiumStore data structure."""
        store = self.page.evaluate("""() => {
            const s = window.TritiumStore;
            if (!s) return { found: false };

            return {
                found: true,
                game: {
                    phase: s.game?.phase || 'unknown',
                    wave: s.game?.wave || 0,
                    score: s.game?.score || 0,
                    kills: s.game?.kills || 0,
                },
                unitCount: s.units ? s.units.size || Object.keys(s.units).length : 0,
                mapMode: s.map?.mode || 'unknown',
                selectedUnit: s.get ? s.get('map.selectedUnitId') : null,
            };
        }""")

        print(f"\nStore inventory:")
        print(f"  Game: {store.get('game', {})}")
        print(f"  Units: {store.get('unitCount', 0)}")
        print(f"  Map mode: {store.get('mapMode', 'unknown')}")
        print(f"  Selected unit: {store.get('selectedUnit', 'none')}")

        self._inventory["store"] = store
        self._screenshot("09_store")

    # --- EventBus ---

    def test_10_eventbus_inventory(self):
        """Audit EventBus registered event types."""
        events = self.page.evaluate("""() => {
            const eb = window.EventBus;
            if (!eb) return { found: false };

            // Try to get listener map
            const listeners = eb._listeners || eb.listeners || eb._events || {};
            const types = Object.keys(listeners);

            return {
                found: true,
                eventTypes: types.slice(0, 30),
                totalTypes: types.length,
                totalListeners: types.reduce((sum, t) => {
                    const l = listeners[t];
                    return sum + (Array.isArray(l) ? l.length : l instanceof Set ? l.size : 1);
                }, 0),
            };
        }""")

        print(f"\nEventBus inventory:")
        if events.get("found"):
            print(f"  Event types: {events.get('totalTypes', 0)}")
            print(f"  Total listeners: {events.get('totalListeners', 0)}")
            for t in events.get("eventTypes", [])[:15]:
                print(f"    - {t}")
        else:
            print("  EventBus not found")

        self._inventory["events"] = events
        self._screenshot("10_eventbus")

    # --- CSS custom properties ---

    def test_11_css_theme_inventory(self):
        """Audit CSS custom properties (theme colors)."""
        css_vars = self.page.evaluate("""() => {
            const style = getComputedStyle(document.documentElement);
            const vars = {};
            const expected = [
                '--cyan', '--magenta', '--green', '--amber', '--yellow',
                '--bg', '--bg-dark', '--text', '--text-dim',
                '--panel-bg', '--border',
            ];
            expected.forEach(v => {
                vars[v] = style.getPropertyValue(v).trim();
            });
            return vars;
        }""")

        print(f"\nCSS theme variables:")
        for name, value in css_vars.items():
            print(f"  {name:20s} = {value}")

        self._inventory["css_vars"] = css_vars
        self._screenshot("11_css_vars")

    # --- Generate comprehensive report ---

    def test_12_generate_report(self):
        """Generate comprehensive DOM inventory report."""
        shot = self._screenshot("12_full_page")

        analysis = _llava_analyze(shot,
            "This shows a tactical command center application. List all visible "
            "UI elements: panels, buttons, menus, status indicators, map elements, "
            "and any text or data displayed.")

        print(f"\nLLM overview: {analysis[:200]}")

        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        inv = self._inventory

        # Build overlay rows
        overlay_rows = ""
        for o in inv.get("overlays", []):
            status = "EXISTS" if o["exists"] else "MISSING"
            hidden = "hidden" if o.get("hidden") else "visible"
            overlay_rows += f"<tr><td>{o['id']}</td><td>{status}</td><td>{hidden}</td><td>{o['childCount']}</td></tr>"

        # Build container rows
        container_rows = ""
        for c in inv.get("containers", []):
            dim = f"{c['dimensions']['w']}x{c['dimensions']['h']}" if c.get("dimensions") else "N/A"
            vis = "visible" if c.get("visible") else "hidden"
            container_rows += f"<tr><td>{c['name']}</td><td>{'YES' if c['exists'] else 'NO'}</td><td>{vis}</td><td>{dim}</td></tr>"

        # Panel rows
        panel_rows = ""
        panels = inv.get("panels", {})
        for pid, state in panels.get("states", {}).items():
            status = "OPEN" if state else "CLOSED"
            panel_rows += f"<tr><td>{pid}</td><td>{status}</td></tr>"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>DOM Inventory Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .summary {{ display:flex; gap:20px; margin:20px 0; flex-wrap:wrap; }}
  .stat {{ padding:12px 24px; border:1px solid #00f0ff33; border-radius:4px; }}
  .stat .val {{ font-size:28px; color:#00f0ff; }}
  .stat .label {{ font-size:12px; color:#666; }}
  table {{ border-collapse:collapse; width:100%; margin:16px 0; font-size:12px; }}
  th {{ background:#111; color:#00f0ff; padding:8px; text-align:left; border-bottom:2px solid #00f0ff33; }}
  td {{ padding:6px 8px; border-bottom:1px solid #222; vertical-align:top; }}
  tr:hover {{ background:#111; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
</style></head><body>
<h1>DOM Inventory Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">{inv.get('buttons', {}).get('total', 0)}</div><div class="label">BUTTONS</div></div>
  <div class="stat"><div class="val">{len(inv.get('inputs', []))}</div><div class="label">INPUTS</div></div>
  <div class="stat"><div class="val">{len(inv.get('bindings', []))}</div><div class="label">DATA BINDINGS</div></div>
  <div class="stat"><div class="val">{inv.get('markers', {}).get('total', 0)}</div><div class="label">MAP MARKERS</div></div>
  <div class="stat"><div class="val">{panels.get('count', 0)}</div><div class="label">PANELS</div></div>
  <div class="stat"><div class="val">{inv.get('events', {}).get('totalTypes', 0)}</div><div class="label">EVENT TYPES</div></div>
</div>

<h2>Full Page</h2>
<img src="12_full_page.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

<h2>Overlays</h2>
<table>
<tr><th>ID</th><th>Status</th><th>Visibility</th><th>Children</th></tr>
{overlay_rows}
</table>

<h2>Containers</h2>
<table>
<tr><th>Name</th><th>Exists</th><th>Visibility</th><th>Dimensions</th></tr>
{container_rows}
</table>

<h2>Panel System</h2>
<table>
<tr><th>Panel ID</th><th>State</th></tr>
{panel_rows}
</table>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during DOM inventory."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
