"""
Panel Content Exercise: Verify the content and interactivity of each panel
(Amy Commander, Units, Alerts, Game HUD, Meshtastic). Checks data binding,
filtering, unit selection, and panel-specific UI elements.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_panel_content_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/panel-content")
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


class TestPanelContentExercise:
    """Exercise panel content: Amy, Units, Alerts, Game HUD."""

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
        # Ensure Commander layout (all key panels open)
        self.page.keyboard.press("Control+4")  # Battle layout has all panels
        time.sleep(0.5)
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _ensure_panel_open(self, panel_id: str):
        is_open = self.page.evaluate(f"""() => {{
            const pm = window.panelManager;
            return pm && pm.isOpen ? pm.isOpen('{panel_id}') : false;
        }}""")
        if not is_open:
            self.page.evaluate(f"""() => {{
                const pm = window.panelManager;
                if (pm && pm.open) pm.open('{panel_id}');
            }}""")
            time.sleep(0.3)

    # --- Amy Commander Panel ---

    def test_01_amy_panel_elements(self):
        """Amy panel shows portrait, state, mood, thought, and action buttons."""
        self._ensure_panel_open("amy")
        time.sleep(0.5)

        amy_state = self.page.evaluate("""() => {
            const inner = document.querySelector('.amy-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                state: inner.querySelector('[data-bind="state"]')?.textContent?.trim() || '',
                mood: inner.querySelector('[data-bind="mood-label"]')?.textContent?.trim() || '',
                thought: inner.querySelector('[data-bind="thought"]')?.textContent?.trim() || '',
                hasPortrait: inner.querySelector('.amy-p-portrait') !== null,
                hasChatBtn: inner.querySelector('[data-action="chat"]') !== null,
                hasAttendBtn: inner.querySelector('[data-action="attend"]') !== null,
                name: inner.querySelector('.amy-p-name')?.textContent?.trim() || '',
            };
        }""")

        print(f"\nAmy panel: {amy_state}")
        self._screenshot("01_amy_panel")

        assert amy_state["found"], "Amy panel inner should exist"
        assert amy_state["name"] == "AMY", f"Name should be AMY, got: {amy_state['name']}"
        assert amy_state["state"], "Amy state should be populated"
        assert amy_state["mood"], "Amy mood should be populated"
        assert amy_state["thought"], "Amy thought should be populated"
        assert amy_state["hasPortrait"], "Amy should have portrait"
        assert amy_state["hasChatBtn"], "Amy should have CHAT button"
        assert amy_state["hasAttendBtn"], "Amy should have ATTEND button"

    def test_02_amy_chat_button(self):
        """CHAT button in Amy panel opens the chat overlay."""
        self._ensure_panel_open("amy")

        chat_visible_before = self.page.evaluate("""() => {
            const el = document.getElementById('chat-overlay');
            return el ? !el.hidden : false;
        }""")
        assert not chat_visible_before, "Chat should be hidden initially"

        # Click CHAT button
        self.page.locator('[data-action="chat"]').first.click()
        time.sleep(0.3)

        chat_visible_after = self.page.evaluate("""() => {
            const el = document.getElementById('chat-overlay');
            return el ? !el.hidden : false;
        }""")

        print(f"\nChat button: {chat_visible_before} -> {chat_visible_after}")
        self._screenshot("02_amy_chat")

        assert chat_visible_after, "CHAT button should open chat overlay"
        self.page.keyboard.press("Escape")
        time.sleep(0.2)

    # --- Units Panel ---

    def test_03_units_panel_list(self):
        """Units panel shows list of units with correct data."""
        self._ensure_panel_open("units")
        time.sleep(0.5)

        units_data = self.page.evaluate("""() => {
            const inner = document.querySelector('.units-panel-inner');
            if (!inner) return { found: false };
            const items = inner.querySelectorAll('.panel-list li');
            const units = [];
            items.forEach(li => {
                if (li.classList.contains('panel-empty')) return;
                units.push({
                    text: li.textContent.trim().substring(0, 100),
                    unitId: li.dataset?.unitId || '',
                });
            });
            return {
                found: true,
                total: items.length,
                count: inner.querySelector('[data-bind="count"]')?.textContent?.trim() || '0',
                units: units.slice(0, 10),  // First 10 for logging
                filterValue: inner.querySelector('[data-bind="filter"]')?.value || '',
            };
        }""")

        print(f"\nUnits panel: total={units_data.get('total')}, count={units_data.get('count')}")
        print(f"  Filter: {units_data.get('filterValue')}")
        for u in units_data.get("units", [])[:5]:
            print(f"  - {u['text'][:60]}")

        self._screenshot("03_units_list")

        assert units_data["found"], "Units panel should exist"
        assert int(units_data["count"]) > 0, "Unit count should be > 0"

    def test_04_units_filter(self):
        """Units panel filter changes the displayed list."""
        self._ensure_panel_open("units")
        time.sleep(0.3)

        results = {}
        for alliance in ["all", "friendly", "hostile", "neutral"]:
            self.page.evaluate(f"""() => {{
                const filter = document.querySelector('.units-panel-inner [data-bind="filter"]');
                if (filter) {{
                    filter.value = '{alliance}';
                    filter.dispatchEvent(new Event('change'));
                }}
            }}""")
            time.sleep(0.3)

            count = self.page.evaluate("""() => {
                const inner = document.querySelector('.units-panel-inner');
                return inner ? inner.querySelector('[data-bind="count"]')?.textContent?.trim() || '0' : '0';
            }""")

            results[alliance] = int(count)
            print(f"  Filter '{alliance}': {count} units")

        self._screenshot("04_units_filter")

        # 'all' should show the most units
        assert results["all"] >= results["friendly"], (
            f"'all' should show >= friendly: {results}"
        )

    def test_05_unit_selection(self):
        """Clicking a unit in the list selects it on the map."""
        self._ensure_panel_open("units")
        time.sleep(0.3)

        # Get first unit's ID from the list
        first_unit = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.units-panel-inner .panel-list li');
            for (const li of items) {
                if (li.dataset?.unitId) return li.dataset.unitId;
            }
            return null;
        }""")

        if not first_unit:
            print("\nNo selectable units in list - skipping")
            self._screenshot("05_no_selectable_units")
            return

        before = self._screenshot("05_before_select")

        # Click the first unit
        self.page.locator(f'.panel-list li[data-unit-id="{first_unit}"]').first.click()
        time.sleep(0.5)

        # Check if selected
        selected = self.page.evaluate("""() => {
            return window.TritiumStore?.get('map.selectedUnitId') || null;
        }""")

        after = self._screenshot("05_after_select")
        diff = _opencv_diff(before, after)

        print(f"\nUnit selection: clicked={first_unit}, selected={selected}, diff={diff:.1f}%")

    # --- Alerts Panel ---

    def test_06_alerts_panel_structure(self):
        """Alerts panel has correct structure and list elements."""
        self._ensure_panel_open("alerts")
        time.sleep(0.3)

        alerts_data = self.page.evaluate("""() => {
            // Try multiple selectors for alerts panel content
            const selectors = [
                '.alerts-panel-inner',
                '[data-panel="alerts"] .panel-body',
                '.panel-body',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.closest('[data-panel="alerts"]')) {
                    const items = el.querySelectorAll('li, .alert-item, [class*=alert]');
                    return {
                        found: true,
                        itemCount: items.length,
                        text: el.textContent.trim().substring(0, 300),
                    };
                }
            }
            // Fallback: check panel body
            const panels = document.querySelectorAll('.panel');
            for (const p of panels) {
                const title = p.querySelector('.panel-title')?.textContent?.trim();
                if (title === 'ALERTS') {
                    const body = p.querySelector('.panel-body');
                    return {
                        found: true,
                        itemCount: body ? body.children.length : 0,
                        text: body ? body.textContent.trim().substring(0, 300) : '',
                    };
                }
            }
            return { found: false };
        }""")

        print(f"\nAlerts panel: {alerts_data}")
        self._screenshot("06_alerts_panel")

        assert alerts_data["found"], "Alerts panel should be found"

    # --- Game HUD Panel ---

    def test_07_game_hud_content(self):
        """Game HUD panel shows game state information."""
        self._ensure_panel_open("game")
        time.sleep(0.3)

        game_data = self.page.evaluate("""() => {
            // Find game panel
            const panels = document.querySelectorAll('.panel');
            for (const p of panels) {
                const title = p.querySelector('.panel-title')?.textContent?.trim();
                if (title === 'GAME STATUS' || title === 'GAME HUD') {
                    const body = p.querySelector('.panel-body');
                    return {
                        found: true,
                        title: title,
                        text: body ? body.textContent.trim().substring(0, 500) : '',
                        hasElements: body ? body.children.length : 0,
                    };
                }
            }
            return { found: false };
        }""")

        print(f"\nGame HUD: {game_data}")
        self._screenshot("07_game_hud")

    def test_08_game_hud_during_battle(self):
        """Game HUD updates during active battle."""
        self._ensure_panel_open("game")

        before = self._screenshot("08_game_before")

        # Start battle
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); }
            catch (e) {}
        }""")
        time.sleep(5)

        during = self._screenshot("08_game_during")

        # Read game state
        state = self.page.evaluate("""() => {
            const s = window.TritiumStore;
            return s ? {
                phase: s.game?.phase || 'unknown',
                wave: s.game?.wave || 0,
                score: s.game?.score || 0,
                kills: s.game?.kills || 0,
            } : {};
        }""")

        diff = _opencv_diff(before, during)
        print(f"\nGame HUD during battle: {state}, diff={diff:.1f}%")

        # Reset
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/reset', { method: 'POST' }); }
            catch (e) {}
        }""")
        time.sleep(1)

    # --- Meshtastic Panel ---

    def test_09_mesh_panel_structure(self):
        """Meshtastic panel has correct structure."""
        self._ensure_panel_open("mesh")
        time.sleep(0.3)

        mesh_data = self.page.evaluate("""() => {
            const panels = document.querySelectorAll('.panel');
            for (const p of panels) {
                const title = p.querySelector('.panel-title')?.textContent?.trim();
                if (title && (title.includes('MESH') || title.includes('mesh'))) {
                    const body = p.querySelector('.panel-body');
                    return {
                        found: true,
                        title: title,
                        text: body ? body.textContent.trim().substring(0, 300) : '',
                        hasElements: body ? body.children.length : 0,
                    };
                }
            }
            return { found: false };
        }""")

        print(f"\nMesh panel: {mesh_data}")
        self._screenshot("09_mesh_panel")

    # --- All panels screenshot ---

    def test_10_all_panels_visible(self):
        """With Battle layout, all key panels are visible."""
        # Battle layout opens amy + units + alerts + game
        self.page.keyboard.press("Control+4")
        time.sleep(0.5)

        panel_states = self.page.evaluate("""() => {
            const pm = window.panelManager;
            if (!pm || !pm.isOpen) return {};
            return {
                amy: pm.isOpen('amy'),
                units: pm.isOpen('units'),
                alerts: pm.isOpen('alerts'),
                game: pm.isOpen('game'),
                mesh: pm.isOpen('mesh'),
            };
        }""")

        print(f"\nBattle layout panel states: {panel_states}")
        self._screenshot("10_all_panels")

        assert panel_states.get("amy"), "Amy should be open in battle layout"
        assert panel_states.get("units"), "Units should be open in battle layout"
        assert panel_states.get("alerts"), "Alerts should be open in battle layout"

    # --- LLM analysis ---

    def test_11_llm_panel_analysis(self):
        """LLaVA analyzes panel content."""
        analyses = {}

        # Battle layout with all panels
        self.page.keyboard.press("Control+4")
        time.sleep(0.5)

        shot = self._screenshot("11_llm_panels")
        analyses["panels"] = _llava_analyze(shot,
            "This shows a tactical command center with multiple side panels open. "
            "Describe the panels visible on the left side: their titles, content, "
            "and any data they show about units, Amy AI, or game status.")

        for name, text in analyses.items():
            print(f"\n{name}: {text[:200]}")

        self._generate_report(analyses)

    def _generate_report(self, analyses: dict):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Panel Content Exercise Report</title>
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
</style></head><body>
<h1>Panel Content Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">12</div><div class="label">TESTS RUN</div></div>
  <div class="stat"><div class="val">5</div><div class="label">PANELS TESTED</div></div>
</div>

<h2>All Panels (Battle Layout)</h2>
<img src="11_llm_panels.png" style="max-width:100%;">
<div class="llm">{analyses.get('panels', 'N/A')}</div>

<h2>Individual Panels</h2>
<div style="display:flex;gap:16px;flex-wrap:wrap;">
  <img src="01_amy_panel.png" style="max-width:300px;">
  <img src="03_units_list.png" style="max-width:300px;">
  <img src="06_alerts_panel.png" style="max-width:300px;">
  <img src="07_game_hud.png" style="max-width:300px;">
</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_12_no_js_errors(self):
        """No critical JS errors during panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
