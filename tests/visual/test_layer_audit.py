"""Layer-by-layer visual audit using VLM (Vision Language Model).

Hides ALL elements to a pure black screen, then reveals ONE layer at a time
(not additive — each layer is shown alone against black). Each screenshot
is fed to a VLM for structured analysis so we can verify what belongs where.

Usage:
    python tests/visual/test_layer_audit.py                # all layers
    python tests/visual/test_layer_audit.py --battle       # include battle FX layers
    python tests/visual/test_layer_audit.py --no-vlm       # screenshots only, skip VLM

Requires: running server on localhost:8000, Playwright, Ollama fleet
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Layer definitions — each shown ALONE against black (not additive)
# ---------------------------------------------------------------------------

@dataclass
class UILayer:
    """One UI layer. Shown alone against pure black for isolation."""
    name: str
    description: str
    selectors: list[str]           # CSS selectors to reveal (only these, nothing else)
    expected: list[str]            # What the VLM should see
    not_expected: list[str] = field(default_factory=list)


# --- Static HTML layers (always present in DOM) ---
LAYERS: list[UILayer] = [
    # 0: Baseline
    UILayer(
        name="00_black_screen",
        description="Everything hidden. Pure black. If not black, something is leaking.",
        selectors=[],
        expected=["black", "dark", "empty"],
        not_expected=["map", "text", "button", "panel"],
    ),

    # 1: The map itself
    UILayer(
        name="01_map_canvas",
        description="MapLibre GL canvas — satellite imagery of a neighborhood. No UI chrome.",
        selectors=["canvas.maplibregl-canvas", ".maplibregl-canvas-container", ".maplibregl-map"],
        expected=["satellite", "aerial", "houses", "streets", "neighborhood"],
        not_expected=["button", "header", "panel", "text"],
    ),

    # 2: Unit markers (DOM elements positioned by MapLibre)
    UILayer(
        name="02_unit_markers",
        description="Small colored circles with single letters — friendly (cyan/green) and hostile (red/magenta). Positioned where units are on the map. Against black background.",
        selectors=[".unit-marker", ".maplibregl-marker"],
        expected=["circles", "dots", "colored", "letters"],
    ),

    # 3: Map mode buttons (top-left: OBSERVE / TACTICAL / SETUP)
    UILayer(
        name="03_map_mode_buttons",
        description="Three mode buttons: OBSERVE, TACTICAL, SETUP. Small button group, top-left area.",
        selectors=["#map-mode", ".map-mode-indicator"],
        expected=["buttons", "observe", "tactical", "setup"],
    ),

    # 4: Map coordinates display
    UILayer(
        name="04_map_coords",
        description="Coordinate readout showing X/Y position. Small monospace text.",
        selectors=["#map-coords"],
        expected=["coordinates", "numbers", "X", "Y"],
    ),

    # 5: FPS counter
    UILayer(
        name="05_map_fps",
        description="FPS counter. Small monospace text showing frame rate.",
        selectors=["#map-fps"],
        expected=["FPS", "number"],
    ),

    # 6: Center banner (hidden by default, shown during wave announcements)
    UILayer(
        name="06_center_banner",
        description="Center-screen announcement banner. Hidden by default (has 'hidden' attr). May show as empty/black.",
        selectors=["#center-banner"],
        expected=["black", "empty"],  # hidden unless announcement active
    ),

    # 7: War HUD overlays (countdown, wave banner, elimination feed, score, begin button, game over, amy toast)
    UILayer(
        name="07_war_hud_overlays",
        description="War HUD elements: countdown, wave banner, elimination feed, score display, BEGIN WAR button, game-over, Amy toast. Most are display:none unless battle active.",
        selectors=[
            "#war-countdown", "#war-wave-banner", "#war-elimination-feed",
            "#war-score", "#war-begin-btn", "#war-game-over", "#war-amy-toast",
        ],
        expected=["black", "empty"],  # all hidden unless battle running
    ),

    # 8: Header bar
    UILayer(
        name="08_header_bar",
        description="Top header bar (36px). Left: TRITIUM-SC logo + SIM mode badge. Center: clock, unit count, threat count. Right: WAVE/SCORE/ELIMS (hidden outside battle), connection status.",
        selectors=["#header-bar"],
        expected=["TRITIUM", "header", "bar", "top"],
    ),

    # 9: Command bar (toolbar below header)
    UILayer(
        name="09_command_bar",
        description="Toolbar below header (28px). Contains menu buttons. May be empty if not populated by JS.",
        selectors=["#command-bar-container"],
        expected=["toolbar", "bar"],
    ),

    # 10: Floating panels container
    UILayer(
        name="10_floating_panels",
        description="All floating panels (Units, Alerts, Amy, Game HUD, Cameras, etc). Dark semi-transparent panels with headers and content lists.",
        selectors=["#panel-container", ".panel-container"],
        expected=["panels", "list"],
    ),

    # 11: Status bar (bottom)
    UILayer(
        name="11_status_bar",
        description="Bottom status bar (20px). Shows: FPS, alive count, threats, WS status, version, help hint.",
        selectors=["#status-bar"],
        expected=["status", "FPS", "alive", "threats", "bottom"],
    ),

    # 12: Toast container (top-right)
    UILayer(
        name="12_toast_container",
        description="Toast notification area. Top-right. Usually empty unless Amy is sending thoughts or alerts are firing.",
        selectors=["#toast-container"],
        expected=["empty", "black"],  # usually empty
    ),

    # 13: Chat panel (hidden by default)
    UILayer(
        name="13_chat_panel",
        description="Amy chat panel. Slides out from right. Hidden by default (has 'hidden' attr). Should be invisible.",
        selectors=["#chat-overlay"],
        expected=["black", "empty"],
    ),

    # 14: Modal overlay (hidden by default)
    UILayer(
        name="14_modal_overlay",
        description="Modal dialog layer. Hidden by default. Used for mission setup, scenarios.",
        selectors=["#modal-overlay"],
        expected=["black", "empty"],
    ),

    # 15: Help overlay (hidden by default)
    UILayer(
        name="15_help_overlay",
        description="Help panel showing keyboard shortcuts. Hidden by default.",
        selectors=["#help-overlay"],
        expected=["black", "empty"],
    ),

    # 16: Game-over overlay (hidden by default)
    UILayer(
        name="16_game_over_overlay",
        description="Game-over overlay. Shows VICTORY/DEFEAT, score, waves, eliminations, MVP, PLAY AGAIN button. Hidden by default.",
        selectors=["#game-over-overlay"],
        expected=["black", "empty"],  # hidden unless game just ended
    ),

    # 17: Full UI composite (everything visible)
    UILayer(
        name="17_everything",
        description="All layers visible simultaneously — the normal view the user sees.",
        selectors=["*"],
        expected=["map", "header", "panels"],
    ),
]


# --- Dynamic battle FX layers (only exist during active combat) ---
BATTLE_LAYERS: list[UILayer] = [
    UILayer(
        name="B00_full_battle",
        description="Everything visible during active battle.",
        selectors=["*"],
        expected=["map", "markers", "status bar", "combat"],
    ),
    UILayer(
        name="B01_combat_status_bar",
        description="Bottom combat status bar: THREAT count, DEFENDERS count+health%, WAVE n/10, wave progress dots, score, timer. Magenta border.",
        selectors=[".fx-combat-status"],
        expected=["THREAT", "DEFENDERS", "WAVE"],
    ),
    UILayer(
        name="B02_battle_vignette",
        description="Red/magenta border around the entire viewport edge. Indicates active combat.",
        selectors=[".fx-battle-vignette"],
        expected=["red", "border", "edge"],
    ),
    UILayer(
        name="B03_kill_feed",
        description="Kill feed in top-right. Shows 'UnitName [WeaponType] // HostileName'. Entries fade after a few seconds. May be empty between kills.",
        selectors=[".fx-kill-feed"],
        expected=["text"],  # may be empty
    ),
    UILayer(
        name="B04_threat_arrows",
        description="Red pulsing CSS triangle arrows on map edges showing hostile spawn direction (N/S/E/W/pincer/surround). Only for non-random waves.",
        selectors=[".fx-threat-arrow"],
        expected=["arrow", "red"],  # absent for random waves
    ),
    UILayer(
        name="B05_map_banner",
        description="Large centered text on map canvas — wave announcements like 'WAVE 3' or countdown '3...2...1...GO'.",
        selectors=[".fx-map-banner", ".fx-countdown"],
        expected=["text", "center"],  # transient
    ),
    UILayer(
        name="B06_streak_banner",
        description="Kill streak announcement — 'DOUBLE KILL', 'KILLING SPREE', etc. Large centered text.",
        selectors=[".fx-streak-banner"],
        expected=["text"],  # very transient
    ),
    UILayer(
        name="B07_screen_flash",
        description="Brief white flash effect on major events (multi-kill, wave clear).",
        selectors=[".fx-screen-flash"],
        expected=["black"],  # very brief, likely missed
    ),
    UILayer(
        name="B08_damage_pulse",
        description="Red inset flash when a friendly takes 20+ damage. Brief red border pulse.",
        selectors=[".fx-damage-pulse"],
        expected=["red"],  # very brief
    ),
    UILayer(
        name="B09_game_over_map",
        description="Map-level game-over overlay (separate from DOM overlay). Shows VICTORY/DEFEAT with score grid.",
        selectors=[".fx-game-over-overlay"],
        expected=["black"],  # only visible at game end
    ),
]


# ---------------------------------------------------------------------------
# JS helpers: hide everything, show one layer, restore
# ---------------------------------------------------------------------------

HIDE_ALL_JS = """
() => {
    document.body.style.background = '#000';
    // Hide every element under body, and all their descendants
    document.querySelectorAll('body > *').forEach(el => {
        el.style.visibility = 'hidden';
    });
    document.querySelectorAll('body > * *').forEach(el => {
        el.style.visibility = 'hidden';
    });
}
"""

def make_show_js(selectors: list[str]) -> str:
    """JS to reveal ONLY the given selectors (and their ancestors/children)."""
    if selectors == ["*"]:
        return """
        () => {
            document.querySelectorAll('body > *').forEach(el => el.style.visibility = '');
            document.querySelectorAll('body > * *').forEach(el => el.style.visibility = '');
        }
        """
    return f"""
    () => {{
        const selectors = {json.dumps(selectors)};
        for (const sel of selectors) {{
            document.querySelectorAll(sel).forEach(el => {{
                // Show element + ancestors up to body
                let node = el;
                while (node && node !== document.body) {{
                    node.style.visibility = 'visible';
                    node = node.parentElement;
                }}
                // Show all children
                el.querySelectorAll('*').forEach(child => {{
                    child.style.visibility = 'visible';
                }});
            }});
        }}
    }}
    """

# Also force-show hidden elements (remove 'hidden' attr temporarily)
def make_force_show_js(selectors: list[str]) -> str:
    """Like make_show_js but also removes 'hidden' attribute so we can see hidden overlays."""
    return f"""
    () => {{
        const selectors = {json.dumps(selectors)};
        const unhidden = [];
        for (const sel of selectors) {{
            document.querySelectorAll(sel).forEach(el => {{
                if (el.hidden) {{
                    el.hidden = false;
                    unhidden.push(el);
                }}
                if (el.style.display === 'none') {{
                    el.style.display = '';
                    el.dataset._auditRestoreDisplay = 'none';
                }}
                let node = el;
                while (node && node !== document.body) {{
                    node.style.visibility = 'visible';
                    node = node.parentElement;
                }}
                el.querySelectorAll('*').forEach(child => {{
                    child.style.visibility = 'visible';
                }});
            }});
        }}
        window.__auditUnhidden = unhidden;
    }}
    """

RESTORE_ALL_JS = """
() => {
    document.body.style.background = '';
    document.querySelectorAll('body > *').forEach(el => el.style.visibility = '');
    document.querySelectorAll('body > * *').forEach(el => el.style.visibility = '');
    // Re-hide anything we force-showed
    if (window.__auditUnhidden) {
        window.__auditUnhidden.forEach(el => { el.hidden = true; });
        window.__auditUnhidden = [];
    }
    document.querySelectorAll('[data-_audit-restore-display]').forEach(el => {
        el.style.display = el.dataset._auditRestoreDisplay;
        delete el.dataset._auditRestoreDisplay;
    });
}
"""


# ---------------------------------------------------------------------------
# VLM query
# ---------------------------------------------------------------------------

_OLLAMA_HOSTS = [
    "http://gb10-02:11434",
    "http://localhost:11434",
]

VLM_PROMPT = """Analyze this screenshot of an isolated UI layer shown against a pure black background.

Answer these questions in order:
1. EMPTY OR CONTENT? Is this screenshot entirely black/empty, or does it contain visible elements?
2. ELEMENTS: List every distinct UI element you can see. For each one, state:
   - What it is (button, text, bar, icon, panel, image, etc.)
   - Its position (top/bottom/left/right/center, approximate pixel region)
   - Its color(s)
   - Any readable text
3. BACKGROUND: What percentage of the screen is black/empty vs occupied by UI elements?
4. UNEXPECTED: Is there anything that seems out of place or surprising?

Layer name: {name}
Expected content: {description}

Be precise and factual. If the screen is entirely black, just say "EMPTY: Entirely black screen, no visible elements." and stop."""


def query_vlm(image_path: str, prompt: str, model: str = "llama3.2-vision:11b") -> str:
    """Send image to VLM via Ollama fleet. Tries gb10-02 first, then localhost."""
    import base64
    import requests

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    for host in _OLLAMA_HOSTS:
        try:
            resp = requests.post(
                f"{host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [img_b64],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 500},
                },
                timeout=120,
            )
            if resp.ok:
                return resp.json().get("response", "")
        except Exception:
            continue
    return "[VLM unavailable on all hosts]"


# ---------------------------------------------------------------------------
# Test class (for pytest)
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("tests/.test-results/layer-audit")


@pytest.fixture(scope="module")
def browser_page():
    """Launch headed Playwright browser, navigate to Command Center."""
    from playwright.sync_api import sync_playwright

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto("http://localhost:8000", wait_until="networkidle", timeout=15000)
        time.sleep(3)
        yield page
        browser.close()


class TestLayerAudit:
    """Visual layer-by-layer audit with VLM verification."""

    @pytest.fixture(autouse=True)
    def _setup(self, browser_page):
        self.page = browser_page

    @pytest.mark.parametrize("layer", LAYERS, ids=[l.name for l in LAYERS])
    def test_layer(self, layer: UILayer):
        """Hide all, reveal ONE layer alone, screenshot, VLM describe."""
        self.page.evaluate(HIDE_ALL_JS)
        time.sleep(0.3)

        if layer.selectors:
            self.page.evaluate(make_show_js(layer.selectors))
        time.sleep(0.5)

        screenshot_path = str(OUTPUT_DIR / f"{layer.name}.png")
        self.page.screenshot(path=screenshot_path)
        print(f"\n  Screenshot: {screenshot_path}")

        self.page.evaluate(RESTORE_ALL_JS)
        time.sleep(0.3)

        prompt = VLM_PROMPT.format(name=layer.name, description=layer.description)
        vlm_response = query_vlm(screenshot_path, prompt)
        print(f"  VLM: {vlm_response[:300]}")

        result = {
            "layer": layer.name,
            "description": layer.description,
            "selectors": layer.selectors,
            "vlm_response": vlm_response,
            "expected": layer.expected,
            "not_expected": layer.not_expected,
            "screenshot": screenshot_path,
        }
        (OUTPUT_DIR / f"{layer.name}.json").write_text(json.dumps(result, indent=2))

        if layer.name == "00_black_screen":
            vlm_lower = vlm_response.lower()
            assert any(w in vlm_lower for w in ["black", "dark", "empty", "nothing", "blank"]), \
                f"Black screen not described as empty: {vlm_response[:100]}"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def _audit_one_layer(page, layer: UILayer, results: list[dict], *,
                     skip_vlm: bool = False, force_show: bool = False):
    """Audit a single layer: hide all -> show just this layer -> screenshot -> VLM."""
    print(f"\n{'─' * 60}")
    print(f"  {layer.name}")
    print(f"  {layer.description}")
    print(f"{'─' * 60}")

    # Hide everything
    page.evaluate(HIDE_ALL_JS)
    time.sleep(0.3)

    # Reveal ONLY this layer
    if layer.selectors:
        if force_show:
            page.evaluate(make_force_show_js(layer.selectors))
        else:
            page.evaluate(make_show_js(layer.selectors))
    time.sleep(0.5)

    # Screenshot
    screenshot_path = str(OUTPUT_DIR / f"{layer.name}.png")
    page.screenshot(path=screenshot_path)

    # Restore
    page.evaluate(RESTORE_ALL_JS)
    time.sleep(0.3)

    # VLM analysis
    vlm_response = ""
    if not skip_vlm:
        prompt = VLM_PROMPT.format(name=layer.name, description=layer.description)
        vlm_response = query_vlm(screenshot_path, prompt)
        # Print first meaningful line
        first_line = vlm_response.strip().split("\n")[0][:120] if vlm_response else ""
        print(f"  VLM: {first_line}")
    else:
        print(f"  [screenshot saved, VLM skipped]")

    result = {
        "layer": layer.name,
        "description": layer.description,
        "selectors": layer.selectors,
        "vlm_response": vlm_response,
        "expected": layer.expected,
        "not_expected": layer.not_expected,
        "screenshot": screenshot_path,
    }
    results.append(result)
    (OUTPUT_DIR / f"{layer.name}.json").write_text(json.dumps(result, indent=2))


def _start_battle(page) -> bool:
    """Start a battle via API and wait for active combat."""
    import requests

    print("\n" + "=" * 60)
    print("  STARTING BATTLE for battle-layer audit")
    print("=" * 60)

    try:
        requests.post("http://localhost:8000/api/game/reset", timeout=5)
        time.sleep(1)
    except Exception:
        pass

    try:
        resp = requests.post(
            "http://localhost:8000/api/game/begin",
            json={"auto_load_layout": True},
            timeout=10,
        )
        if not resp.ok:
            print(f"  Failed: {resp.status_code} {resp.text[:200]}")
            return False
        print(f"  {resp.json()}")
    except Exception as e:
        print(f"  Failed: {e}")
        return False

    for i in range(30):
        time.sleep(0.5)
        try:
            sr = requests.get("http://localhost:8000/api/game/state", timeout=5)
            if sr.ok and sr.json().get("state") == "active":
                print(f"  Battle active after {(i+1)*0.5:.1f}s")
                time.sleep(5)  # let combat effects appear
                return True
        except Exception:
            pass

    print("  Battle did not reach active state")
    return False


def generate_html_report(results: list[dict], output_path: Path | None = None):
    """Generate visual HTML report with embedded screenshots."""
    import base64

    if output_path is None:
        output_path = OUTPUT_DIR / "layer_audit_report.html"

    rows = []
    for r in results:
        img_path = r.get("screenshot", "")
        if img_path and os.path.exists(img_path):
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            img_tag = f'<img src="data:image/png;base64,{img_b64}" style="max-width:100%;border:1px solid #333;border-radius:4px">'
        else:
            img_tag = '<div style="background:#111;height:200px;display:flex;align-items:center;justify-content:center;color:#666">No screenshot</div>'

        vlm = r.get("vlm_response", "").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        name = r.get("layer", "?")
        desc = r.get("description", "")
        sels = r.get("selectors", [])
        sel_str = ", ".join(f"<code>{s}</code>" for s in sels) if sels else "<em>none (black screen)</em>"
        color = "#fcee0a" if name.startswith("B") else "#00f0ff"

        rows.append(f"""
        <div class="layer-card">
            <div class="layer-info">
                <h3 style="color:{color}">{name}</h3>
                <p class="desc">{desc}</p>
                <div class="selectors">Selectors: {sel_str}</div>
                <div class="vlm-box">
                    <div class="vlm-label">VLM Analysis</div>
                    {vlm if vlm else '<em style="color:#666">No VLM analysis</em>'}
                </div>
            </div>
            <div class="layer-img">{img_tag}</div>
        </div>
        """)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>TRITIUM-SC Layer Audit</title>
<style>
    * {{ box-sizing: border-box; }}
    body {{ background: #050510; color: #ccc; font-family: 'JetBrains Mono', 'Fira Code', monospace;
           margin: 0; padding: 20px 40px; }}
    h1 {{ color: #00f0ff; text-align: center; font-size: 22px; margin-bottom: 4px; }}
    h2 {{ color: #ff2a6d; font-size: 13px; text-align: center; margin-top: 0; font-weight: normal; }}
    .summary {{ text-align: center; color: #555; font-size: 11px; margin-bottom: 30px; }}
    .layer-card {{
        display: grid; grid-template-columns: 1fr 1fr; gap: 20px;
        margin-bottom: 24px; padding: 16px; background: #0a0a14;
        border: 1px solid #1a1a2e; border-radius: 6px;
    }}
    .layer-info h3 {{ margin: 0 0 6px; font-size: 15px; }}
    .desc {{ color: #999; margin: 0 0 8px; font-size: 12px; line-height: 1.4; }}
    .selectors {{ font-size: 11px; color: #555; margin-bottom: 12px; }}
    code {{ background: #111; padding: 1px 4px; border-radius: 2px; font-size: 10px; color: #05ffa1; }}
    .vlm-box {{
        padding: 10px; background: #060610; border: 1px solid #1a1a2e;
        border-radius: 4px; font-size: 12px; color: #bbb; line-height: 1.5;
        max-height: 400px; overflow-y: auto;
    }}
    .vlm-label {{ color: #05ffa1; font-size: 11px; font-weight: bold; margin-bottom: 6px; }}
    .layer-img img {{ width: 100%; border: 1px solid #222; border-radius: 4px; }}
</style>
</head>
<body>
<h1>TRITIUM-SC LAYER AUDIT</h1>
<h2>Each layer shown ALONE against black -- not additive</h2>
<div class="summary">{len(results)} layers | VLM: llama3.2-vision:11b | {time.strftime('%Y-%m-%d %H:%M')}</div>
{"".join(rows)}
</body>
</html>"""

    output_path.write_text(html)
    return output_path


def main():
    """Run the layer audit standalone."""
    from playwright.sync_api import sync_playwright

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    do_battle = "--battle" in sys.argv
    skip_vlm = "--no-vlm" in sys.argv
    force_show_hidden = "--force-show" in sys.argv

    print("=" * 60)
    print("  TRITIUM-SC Layer-by-Layer Visual Audit")
    print(f"  Each layer shown ALONE against black")
    print(f"  VLM: {'SKIP' if skip_vlm else 'llama3.2-vision:11b'}")
    print(f"  Battle layers: {'YES' if do_battle else 'NO'}")
    print(f"  Force-show hidden: {'YES' if force_show_hidden else 'NO'}")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto("http://localhost:8000", wait_until="networkidle", timeout=15000)
        time.sleep(3)

        # Base layers
        for layer in LAYERS:
            _audit_one_layer(page, layer, results,
                             skip_vlm=skip_vlm,
                             force_show=force_show_hidden)

        # Battle layers
        if do_battle:
            if _start_battle(page):
                for layer in BATTLE_LAYERS:
                    _audit_one_layer(page, layer, results, skip_vlm=skip_vlm)
            else:
                print("\n  SKIPPING battle layers -- could not start battle")

        browser.close()

    # Reports
    report_json = OUTPUT_DIR / "layer_audit_report.json"
    report_json.write_text(json.dumps(results, indent=2))
    report_html = generate_html_report(results)

    print(f"\n{'=' * 60}")
    print(f"  HTML:  {report_html}")
    print(f"  JSON:  {report_json}")
    print(f"  PNGs:  {OUTPUT_DIR}/")
    print(f"  Total: {len(results)} layers")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
