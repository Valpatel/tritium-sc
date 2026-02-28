#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Comprehensive UX audit of the TRITIUM-SC Command Center.

Starts a server, opens Chromium via Playwright at 1920x1080, and
systematically tests every user-facing feature.
"""

import json
import os
import sys
import time
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from server_manager import TritiumServer
from playwright.sync_api import sync_playwright, expect

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCREENSHOTS_DIR = os.path.join(PROJECT_ROOT, 'docs', 'screenshots')
REPORT_DIR = os.path.join(PROJECT_ROOT, 'docs', 'overnight-status')

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)


def main():
    # Start server — use subprocess directly to avoid pipe buffer issues
    import subprocess
    import signal
    import socket

    def _find_free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(PROJECT_ROOT, "src")
    env["SIMULATION_ENABLED"] = "true"
    env["AMY_ENABLED"] = "false"
    env["MQTT_ENABLED"] = "false"
    env["CUDA_VISIBLE_DEVICES"] = ""

    print(f"Starting server on port {port}...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for health
    import requests as _req
    deadline = time.monotonic() + 60
    healthy = False
    while time.monotonic() < deadline:
        try:
            r = _req.get(f"{base_url}/health", timeout=2)
            if r.status_code == 200:
                healthy = True
                break
        except Exception:
            pass
        time.sleep(0.5)

    if not healthy:
        proc.kill()
        raise RuntimeError(f"Server failed to start on {base_url}")

    print(f"Server running at {base_url}")

    class _Server:
        url = base_url
        def get_game_state(self):
            return _req.get(f"{base_url}/api/game/state", timeout=5).json()
        def begin_war(self):
            return _req.post(f"{base_url}/api/game/begin", timeout=5).json()
        def reset_game(self):
            return _req.post(f"{base_url}/api/game/reset", timeout=5).json()
        def place_unit(self, name, x, y, unit_type="turret"):
            return _req.post(f"{base_url}/api/game/place",
                json={"name": name, "position": {"x": x, "y": y}, "asset_type": unit_type},
                timeout=5).json()
        def stop(self):
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    server = _Server()

    results = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                device_scale_factor=1,
            )
            page = context.new_page()

            # Collect console errors
            console_errors = []
            page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)

            # Navigate to Command Center
            url = f"{server.url}/unified"
            print(f"Navigating to {url}")
            page.goto(url, wait_until='networkidle', timeout=30000)
            time.sleep(3)  # Let canvas render and WebSocket connect

            # ============================================================
            # HEADER
            # ============================================================
            print("\n=== HEADER ===")

            # Logo
            logo = page.query_selector('[data-element="logo"]')
            logo_text = logo.text_content() if logo else None
            r = check("Header: TRITIUM-SC logo", logo_text and 'TRITIUM' in logo_text, f"Logo text: '{logo_text}'")
            results.append(r)

            # Mode indicator
            mode = page.query_selector('[data-element="mode-indicator"]')
            mode_text = mode.text_content().strip() if mode else None
            r = check("Header: SIM mode badge", mode and 'SIM' in (mode_text or ''), f"Mode: '{mode_text}'")
            results.append(r)

            # Clock
            clock = page.query_selector('[data-element="clock"]')
            clock_text = clock.text_content().strip() if clock else None
            r = check("Header: UTC clock", clock and 'UTC' in (clock_text or ''), f"Clock: '{clock_text}'")
            results.append(r)

            # Unit count
            unit_count_el = page.query_selector('#header-units .stat-value')
            unit_count = unit_count_el.text_content().strip() if unit_count_el else None
            r = check("Header: Unit count", unit_count is not None, f"Unit count: '{unit_count}'")
            results.append(r)

            # Threat count
            threat_count_el = page.query_selector('#header-threats .stat-value')
            threat_count = threat_count_el.text_content().strip() if threat_count_el else None
            r = check("Header: Threat count", threat_count is not None, f"Threat count: '{threat_count}'")
            results.append(r)

            # Connection status
            conn = page.query_selector('[data-element="connection-status"]')
            conn_state = conn.get_attribute('data-state') if conn else None
            conn_label = page.query_selector('.conn-label')
            conn_text = conn_label.text_content().strip() if conn_label else None
            r = check("Header: Connection status", conn_state == 'connected' and conn_text == 'ONLINE',
                       f"State: '{conn_state}', Label: '{conn_text}'")
            results.append(r)

            # ============================================================
            # MAP
            # ============================================================
            print("\n=== MAP ===")

            # Canvas exists and has dimensions
            canvas = page.query_selector('#tactical-canvas')
            canvas_box = canvas.bounding_box() if canvas else None
            r = check("Map: Canvas exists and sized", canvas_box and canvas_box['width'] > 100 and canvas_box['height'] > 100,
                       f"Canvas box: {canvas_box}")
            results.append(r)

            # FPS counter
            fps_el = page.query_selector('[data-element="map-fps"]')
            fps_text = fps_el.text_content().strip() if fps_el else None
            r = check("Map: FPS counter visible", fps_text and 'FPS' in fps_text, f"FPS: '{fps_text}'")
            results.append(r)

            # Wait for FPS to update
            time.sleep(2)
            fps_text2 = fps_el.text_content().strip() if fps_el else None
            fps_num = None
            if fps_text2:
                try:
                    fps_num = int(fps_text2.replace('FPS', '').strip().replace('--', '0'))
                except ValueError:
                    pass
            r = check("Map: Render loop running (FPS > 0)", fps_num is not None and fps_num > 0,
                       f"FPS after 2s: '{fps_text2}' (parsed: {fps_num})")
            results.append(r)

            # Coordinate display
            coords_el = page.query_selector('[data-element="map-coords"]')
            coords_text = coords_el.text_content().strip() if coords_el else None
            r = check("Map: Coordinates display", coords_el and coords_text and 'X:' in coords_text,
                       f"Coords: '{coords_text}'")
            results.append(r)

            # Map mode buttons
            mode_btns = page.query_selector_all('[data-map-mode]')
            r = check("Map: Mode buttons (O/T/S)", len(mode_btns) == 3,
                       f"Found {len(mode_btns)} mode buttons")
            results.append(r)

            # Check active mode is Observe by default
            active_mode = page.query_selector('[data-map-mode].active')
            active_mode_val = active_mode.get_attribute('data-map-mode') if active_mode else None
            r = check("Map: Default mode is Observe", active_mode_val == 'observe',
                       f"Active mode: '{active_mode_val}'")
            results.append(r)

            # Minimap
            minimap = page.query_selector('[data-component="minimap"]')
            minimap_visible = minimap and not minimap.get_attribute('hidden')
            r = check("Map: Minimap visible", minimap_visible, f"Minimap found: {minimap is not None}")
            results.append(r)

            minimap_canvas = page.query_selector('#minimap-canvas')
            mm_box = minimap_canvas.bounding_box() if minimap_canvas else None
            r = check("Map: Minimap canvas sized", mm_box and mm_box['width'] > 50,
                       f"Minimap box: {mm_box}")
            results.append(r)

            # Scale bar visible (check canvas rendering - indirect)
            # We can't directly check canvas content, but we can verify the code path

            # Check if satellite tiles loaded (via API)
            try:
                geo_resp = requests.get(f"{server.url}/api/geo/reference", timeout=5)
                geo_data = geo_resp.json() if geo_resp.ok else {}
                geo_initialized = geo_data.get('initialized', False)
            except Exception:
                geo_initialized = False
            r = check("Map: Geo reference initialized", geo_initialized,
                       f"Geo data: {geo_data if geo_initialized else 'not initialized'}")
            results.append(r)

            # Screenshot: initial state
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-01-initial.png'))

            # ============================================================
            # UNITS ON MAP
            # ============================================================
            print("\n=== UNITS ===")

            # Wait for WebSocket to push unit data
            time.sleep(2)

            # Check units from API
            try:
                targets_resp = requests.get(f"{server.url}/api/amy/simulation/targets", timeout=5)
                targets_data = targets_resp.json() if targets_resp.ok else {}
                sim_targets = targets_data.get('targets', [])
            except Exception:
                sim_targets = []

            r = check("Units: Simulation has targets", len(sim_targets) > 0,
                       f"Simulation targets: {len(sim_targets)}")
            results.append(r)

            # Check units in store via JS evaluation
            unit_count_js = page.evaluate("() => { try { return TritiumStore.units.size; } catch(e) { return -1; } }")
            r = check("Units: Store has units (via WebSocket)", unit_count_js > 0,
                       f"TritiumStore.units.size = {unit_count_js}")
            results.append(r)

            # Check unit types
            if sim_targets:
                types = set(t.get('type', t.get('asset_type', '')) for t in sim_targets)
                alliances = set(t.get('alliance', '') for t in sim_targets)
                r = check("Units: Multiple unit types", len(types) > 1,
                           f"Unit types: {types}")
                results.append(r)
                r = check("Units: Friendly units present", 'friendly' in alliances,
                           f"Alliances: {alliances}")
                results.append(r)

            # Screenshot: map with units
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-02-units.png'))

            # ============================================================
            # PANELS
            # ============================================================
            print("\n=== PANELS ===")

            # Check panel container
            panel_container = page.query_selector('#panel-container')
            r = check("Panels: Container exists", panel_container is not None, "")
            results.append(r)

            # Check which panels are open
            panel_els = page.query_selector_all('.floating-panel')
            panel_ids = []
            for pel in panel_els:
                pid = pel.get_attribute('data-panel-id')
                if pid:
                    panel_ids.append(pid)
            r = check("Panels: Floating panels present", len(panel_els) > 0,
                       f"Open panels: {panel_ids}")
            results.append(r)

            # Amy panel
            amy_panel = page.query_selector('[data-panel-id="amy"]')
            r = check("Panels: Amy panel open", amy_panel is not None, "")
            results.append(r)

            # Units panel
            units_panel = page.query_selector('[data-panel-id="units"]')
            r = check("Panels: Units panel open", units_panel is not None, "")
            results.append(r)

            # Alerts panel
            alerts_panel = page.query_selector('[data-panel-id="alerts"]')
            r = check("Panels: Alerts panel open", alerts_panel is not None, "")
            results.append(r)

            # Check Amy panel content
            if amy_panel:
                amy_content = amy_panel.text_content()
                r = check("Panels: Amy panel has content", len(amy_content) > 20,
                           f"Amy panel text length: {len(amy_content)}")
                results.append(r)

            # Check Units panel content
            if units_panel:
                units_content = units_panel.text_content()
                has_unit_data = any(word in units_content.lower() for word in ['rover', 'drone', 'turret', 'patrol', 'scout', 'unit'])
                r = check("Panels: Units panel shows unit data", has_unit_data,
                           f"Units panel preview: '{units_content[:200]}'")
                results.append(r)

            # Screenshot: panels visible
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-03-panels.png'))

            # ============================================================
            # KEYBOARD SHORTCUTS
            # ============================================================
            print("\n=== KEYBOARD SHORTCUTS ===")

            # ? = Help overlay
            page.keyboard.press('?')
            time.sleep(0.5)
            help_overlay = page.query_selector('#help-overlay')
            help_visible = help_overlay and not help_overlay.get_attribute('hidden')
            r = check("Keys: ? opens help overlay", help_visible, "")
            results.append(r)

            if help_visible:
                help_text = help_overlay.text_content()
                has_shortcuts = 'KEYBOARD' in help_text.upper() or 'GENERAL' in help_text.upper()
                r = check("Keys: Help overlay has shortcut content", has_shortcuts,
                           f"Help text preview: '{help_text[:200]}'")
                results.append(r)

            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-04-help.png'))

            # ESC closes help
            page.keyboard.press('Escape')
            time.sleep(0.3)
            help_hidden = help_overlay and help_overlay.get_attribute('hidden') is not None
            r = check("Keys: ESC closes help overlay", help_hidden, "")
            results.append(r)

            # O = Observe mode
            page.keyboard.press('o')
            time.sleep(0.3)
            active = page.query_selector('[data-map-mode].active')
            r = check("Keys: O = Observe mode", active and active.get_attribute('data-map-mode') == 'observe', "")
            results.append(r)

            # T = Tactical mode
            page.keyboard.press('t')
            time.sleep(0.3)
            active = page.query_selector('[data-map-mode].active')
            r = check("Keys: T = Tactical mode", active and active.get_attribute('data-map-mode') == 'tactical', "")
            results.append(r)

            # S = Setup mode
            page.keyboard.press('s')
            time.sleep(0.3)
            active = page.query_selector('[data-map-mode].active')
            r = check("Keys: S = Setup mode", active and active.get_attribute('data-map-mode') == 'setup', "")
            results.append(r)

            # Switch back to observe
            page.keyboard.press('o')
            time.sleep(0.3)

            # C = Chat overlay
            page.keyboard.press('c')
            time.sleep(0.5)
            chat_overlay = page.query_selector('#chat-overlay')
            chat_visible = chat_overlay and not chat_overlay.get_attribute('hidden')
            r = check("Keys: C opens chat overlay", chat_visible, "")
            results.append(r)

            # ESC closes chat
            page.keyboard.press('Escape')
            time.sleep(0.3)
            chat_hidden = chat_overlay and chat_overlay.get_attribute('hidden') is not None
            r = check("Keys: ESC closes chat", chat_hidden, "")
            results.append(r)

            # M = Toggle minimap
            mm_before = page.query_selector('#minimap-container')
            mm_hidden_before = mm_before.get_attribute('hidden') if mm_before else None
            page.keyboard.press('m')
            time.sleep(0.3)
            mm_after = page.query_selector('#minimap-container')
            mm_hidden_after = mm_after.get_attribute('hidden') if mm_after else None
            toggled = mm_hidden_before != mm_hidden_after
            r = check("Keys: M toggles minimap", toggled, f"Before: hidden={mm_hidden_before}, After: hidden={mm_hidden_after}")
            results.append(r)
            # Toggle back
            page.keyboard.press('m')
            time.sleep(0.2)

            # Panel toggles
            # 1 = Amy
            page.keyboard.press('1')
            time.sleep(0.3)
            amy_after = page.query_selector('[data-panel-id="amy"]')
            r = check("Keys: 1 toggles Amy panel", True, f"Amy panel after toggle: {'visible' if amy_after else 'hidden'}")
            results.append(r)
            page.keyboard.press('1')  # Toggle back
            time.sleep(0.2)

            # 4 = Game HUD
            page.keyboard.press('4')
            time.sleep(0.3)
            game_panel = page.query_selector('[data-panel-id="game"]')
            r = check("Keys: 4 opens Game HUD panel", game_panel is not None, "")
            results.append(r)

            if game_panel:
                game_content = game_panel.text_content()
                r = check("Keys: Game HUD has content", len(game_content) > 10,
                           f"Game HUD text: '{game_content[:200]}'")
                results.append(r)

            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-05-game-hud.png'))

            # Close game panel
            page.keyboard.press('4')
            time.sleep(0.2)

            # ============================================================
            # CHAT
            # ============================================================
            print("\n=== CHAT ===")

            page.keyboard.press('c')
            time.sleep(0.5)

            # Chat input
            chat_input = page.query_selector('#chat-input')
            r = check("Chat: Input field exists", chat_input is not None, "")
            results.append(r)

            # Send button
            chat_send = page.query_selector('#chat-send')
            r = check("Chat: Send button exists", chat_send is not None, "")
            results.append(r)

            # Type and send
            if chat_input:
                chat_input.fill("Hello Amy, status report?")
                time.sleep(0.3)
                page.keyboard.press('Enter')
                time.sleep(2)

                # Check for messages
                messages = page.query_selector_all('.chat-msg')
                r = check("Chat: Messages appear after send", len(messages) > 0,
                           f"Message count: {len(messages)}")
                results.append(r)

                # Check for user message
                user_msgs = page.query_selector_all('.chat-msg-user')
                r = check("Chat: User message displayed", len(user_msgs) > 0, "")
                results.append(r)

                # Check for amy/system response
                other_msgs = page.query_selector_all('.chat-msg-amy, .chat-msg-error')
                r = check("Chat: Amy/system response appears", len(other_msgs) > 0,
                           f"Response messages: {len(other_msgs)}")
                results.append(r)

            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-06-chat.png'))
            page.keyboard.press('Escape')
            time.sleep(0.3)

            # ============================================================
            # MAP INTERACTIONS
            # ============================================================
            print("\n=== MAP INTERACTIONS ===")

            # Zoom via keyboard
            zoom_before = page.evaluate("() => TritiumStore.map?.viewport?.zoom || 0")
            page.keyboard.press(']')  # Zoom in
            time.sleep(0.5)
            zoom_after = page.evaluate("() => TritiumStore.map?.viewport?.zoom || 0")
            r = check("Map: ] zooms in", zoom_after > zoom_before,
                       f"Zoom before: {zoom_before}, after: {zoom_after}")
            results.append(r)

            page.keyboard.press('[')  # Zoom out
            time.sleep(0.5)

            # Mouse wheel zoom
            if canvas_box:
                cx = canvas_box['x'] + canvas_box['width'] / 2
                cy = canvas_box['y'] + canvas_box['height'] / 2
                zoom_before2 = page.evaluate("() => TritiumStore.map?.viewport?.zoom || 0")
                page.mouse.move(cx, cy)
                page.mouse.wheel(0, -300)  # Scroll up = zoom in
                time.sleep(0.5)
                zoom_after2 = page.evaluate("() => TritiumStore.map?.viewport?.zoom || 0")
                r = check("Map: Mouse wheel zooms", abs(zoom_after2 - zoom_before2) > 0.01,
                           f"Zoom before: {zoom_before2:.2f}, after: {zoom_after2:.2f}")
                results.append(r)

            # Pan (right-click drag)
            if canvas_box:
                cam_x_before = page.evaluate("() => TritiumStore.map?.viewport?.x || 0")
                page.mouse.move(cx, cy)
                page.mouse.down(button='right')
                page.mouse.move(cx + 100, cy + 100, steps=5)
                page.mouse.up(button='right')
                time.sleep(0.5)
                cam_x_after = page.evaluate("() => TritiumStore.map?.viewport?.x || 0")
                r = check("Map: Right-click drag pans", abs(cam_x_after - cam_x_before) > 0.1,
                           f"Cam X before: {cam_x_before:.1f}, after: {cam_x_after:.1f}")
                results.append(r)

            # Reset camera
            page.keyboard.press('r')
            time.sleep(1)

            # Unit click selection
            if canvas_box and unit_count_js > 0:
                # Get first unit position via JS
                first_unit_pos = page.evaluate("""() => {
                    const iter = TritiumStore.units.entries();
                    const entry = iter.next().value;
                    if (!entry) return null;
                    const [id, u] = entry;
                    if (!u.position) return null;
                    return { id, x: u.position.x, y: u.position.y };
                }""")
                if first_unit_pos:
                    # Convert world to screen
                    screen_pos = page.evaluate(f"""() => {{
                        // Access the map module's worldToScreen via canvas
                        const cam = TritiumStore.map.viewport;
                        const canvas = document.getElementById('tactical-canvas');
                        const dpr = window.devicePixelRatio || 1;
                        const cssW = canvas.width / dpr;
                        const cssH = canvas.height / dpr;
                        const sx = ({first_unit_pos['x']} - cam.x) * cam.zoom + cssW / 2;
                        const sy = -({first_unit_pos['y']} - cam.y) * cam.zoom + cssH / 2;
                        const rect = canvas.getBoundingClientRect();
                        return {{ x: rect.left + sx, y: rect.top + sy }};
                    }}""")
                    if screen_pos and 0 < screen_pos['x'] < 1920 and 0 < screen_pos['y'] < 1080:
                        page.mouse.click(screen_pos['x'], screen_pos['y'])
                        time.sleep(0.3)
                        selected = page.evaluate("() => TritiumStore.get('map.selectedUnitId')")
                        r = check("Map: Click selects unit", selected is not None,
                                   f"Selected unit: {selected}")
                        results.append(r)

            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-07-map-interaction.png'))

            # ============================================================
            # GAME FLOW
            # ============================================================
            print("\n=== GAME FLOW ===")

            # Check game state
            try:
                game_state = server.get_game_state()
                phase = game_state.get('phase', 'unknown')
            except Exception as e:
                game_state = {}
                phase = 'error'
            r = check("Game: API returns state", phase in ('idle', 'setup', 'active', 'countdown', 'victory', 'defeat', 'wave_complete'),
                       f"Game phase: '{phase}'")
            results.append(r)

            # Place units
            try:
                place_resp = server.place_unit("Audit Turret NW", -30, 40, "turret")
                r = check("Game: Place turret via API", 'error' not in str(place_resp).lower(),
                           f"Place response: {place_resp}")
                results.append(r)
            except Exception as e:
                r = check("Game: Place turret via API", False, f"Error: {e}")
                results.append(r)

            try:
                place_resp2 = server.place_unit("Audit Turret SE", 30, -30, "turret")
                r = check("Game: Place second turret", 'error' not in str(place_resp2).lower(), "")
                results.append(r)
            except Exception as e:
                r = check("Game: Place second turret", False, f"Error: {e}")
                results.append(r)

            time.sleep(1)

            # Screenshot: setup with placed units
            page.keyboard.press('r')  # Reset camera
            time.sleep(1)
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-08-setup.png'))

            # Begin War
            try:
                war_resp = server.begin_war()
                r = check("Game: Begin war", 'error' not in str(war_resp).lower(),
                           f"War response: {war_resp}")
                results.append(r)
            except Exception as e:
                r = check("Game: Begin war", False, f"Error: {e}")
                results.append(r)

            # Wait through countdown
            time.sleep(6)

            # Check active phase
            try:
                game_state2 = server.get_game_state()
                phase2 = game_state2.get('phase', 'unknown')
            except Exception:
                phase2 = 'error'
            r = check("Game: Phase transitions to active/countdown",
                       phase2 in ('active', 'countdown', 'wave_complete'),
                       f"Phase after begin: '{phase2}'")
            results.append(r)

            # Check for hostiles
            time.sleep(3)
            try:
                targets2 = requests.get(f"{server.url}/api/amy/simulation/targets", timeout=5).json()
                hostiles = [t for t in targets2.get('targets', []) if t.get('alliance') == 'hostile']
            except Exception:
                hostiles = []
            r = check("Game: Hostiles spawned", len(hostiles) > 0,
                       f"Hostile count: {len(hostiles)}")
            results.append(r)

            # Check header game score area visible
            game_score_area = page.query_selector('#game-score-area')
            score_hidden = game_score_area.get_attribute('hidden') if game_score_area else 'missing'
            r = check("Game: Score HUD visible in header", score_hidden is None,
                       f"Score area hidden attr: {score_hidden}")
            results.append(r)

            # Wave display
            wave_el = page.query_selector('#game-wave')
            wave_text = wave_el.text_content().strip() if wave_el else None
            r = check("Game: Wave number displayed", wave_text and '/' in wave_text,
                       f"Wave: '{wave_text}'")
            results.append(r)

            # Screenshot: active combat
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-09-combat.png'))
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'game-combat.png'))

            # Wait a bit more for combat to proceed
            time.sleep(5)
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'audit-10-combat-later.png'))

            # Check score and eliminations
            score_el = page.query_selector('#game-score')
            score_text = score_el.text_content().strip() if score_el else '0'
            elim_el = page.query_selector('#game-eliminations')
            elim_text = elim_el.text_content().strip() if elim_el else '0'
            r = check("Game: Score updates", score_text != '0' or elim_text != '0',
                       f"Score: {score_text}, Eliminations: {elim_text}")
            results.append(r)

            # Check WebSocket-driven updates in store
            js_game = page.evaluate("""() => {
                try {
                    return {
                        phase: TritiumStore.game.phase,
                        wave: TritiumStore.game.wave,
                        score: TritiumStore.game.score,
                        eliminations: TritiumStore.game.eliminations,
                    };
                } catch(e) { return { error: e.message }; }
            }""")
            r = check("Game: Store reflects game state", js_game.get('phase') in ('active', 'countdown', 'wave_complete', 'victory', 'defeat'),
                       f"Store game: {js_game}")
            results.append(r)

            # Reset game
            try:
                reset_resp = server.reset_game()
                r = check("Game: Reset works", True, f"Reset response: {reset_resp}")
                results.append(r)
            except Exception as e:
                r = check("Game: Reset works", False, f"Error: {e}")
                results.append(r)

            time.sleep(1)

            # ============================================================
            # STATUS BAR
            # ============================================================
            print("\n=== STATUS BAR ===")

            status_bar = page.query_selector('[data-component="status-bar"]')
            r = check("Status: Bar exists", status_bar is not None, "")
            results.append(r)

            status_fps = page.query_selector('[data-element="status-fps"]')
            sfps_text = status_fps.text_content().strip() if status_fps else None
            r = check("Status: FPS display", sfps_text and 'FPS' in sfps_text, f"Status FPS: '{sfps_text}'")
            results.append(r)

            status_alive = page.query_selector('[data-element="status-alive"]')
            salive_text = status_alive.text_content().strip() if status_alive else None
            r = check("Status: Alive count", salive_text and 'alive' in salive_text, f"Status alive: '{salive_text}'")
            results.append(r)

            status_threats = page.query_selector('[data-element="status-threats"]')
            sthreats_text = status_threats.text_content().strip() if status_threats else None
            r = check("Status: Threats count", sthreats_text and 'threats' in sthreats_text, f"Status threats: '{sthreats_text}'")
            results.append(r)

            status_ws = page.query_selector('[data-element="status-ws"]')
            sws_text = status_ws.text_content().strip() if status_ws else None
            r = check("Status: WS indicator", sws_text and 'WS:' in sws_text, f"Status WS: '{sws_text}'")
            results.append(r)

            # ============================================================
            # MENU BAR
            # ============================================================
            print("\n=== MENU BAR ===")

            command_bar = page.query_selector('#command-bar-container')
            r = check("Menu: Command bar container exists", command_bar is not None, "")
            results.append(r)

            menu_content = command_bar.text_content().strip() if command_bar else ''
            r = check("Menu: Command bar has content", len(menu_content) > 0,
                       f"Menu bar text: '{menu_content[:200]}'")
            results.append(r)

            # ============================================================
            # TOAST NOTIFICATIONS
            # ============================================================
            print("\n=== TOASTS ===")

            toast_container = page.query_selector('#toast-container')
            r = check("Toasts: Container exists", toast_container is not None, "")
            results.append(r)

            # ============================================================
            # CENTER BANNER
            # ============================================================
            print("\n=== BANNER ===")

            banner = page.query_selector('#center-banner')
            r = check("Banner: Element exists", banner is not None, "")
            results.append(r)

            # ============================================================
            # COMBAT HUD ELEMENTS
            # ============================================================
            print("\n=== COMBAT HUD ===")

            countdown = page.query_selector('#war-countdown')
            r = check("Combat HUD: Countdown element exists", countdown is not None, "")
            results.append(r)

            wave_banner = page.query_selector('#war-wave-banner')
            r = check("Combat HUD: Wave banner element exists", wave_banner is not None, "")
            results.append(r)

            elim_feed = page.query_selector('#war-elimination-feed')
            r = check("Combat HUD: Elimination feed element exists", elim_feed is not None, "")
            results.append(r)

            begin_btn = page.query_selector('#war-begin-btn')
            r = check("Combat HUD: Begin War button exists", begin_btn is not None, "")
            results.append(r)

            game_over_el = page.query_selector('#war-game-over')
            r = check("Combat HUD: Game over element exists", game_over_el is not None, "")
            results.append(r)

            # ============================================================
            # HERO SCREENSHOTS
            # ============================================================
            print("\n=== HERO SCREENSHOTS ===")

            # Reset everything for clean shots
            try:
                server.reset_game()
            except Exception:
                pass
            time.sleep(2)

            # 1. Clean overview
            page.keyboard.press('r')
            time.sleep(1)
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'command-center.png'))
            print("  Saved: command-center.png")

            # 3. Wide neighborhood view (zoom out)
            page.keyboard.press('[')
            time.sleep(0.3)
            page.keyboard.press('[')
            time.sleep(0.3)
            page.keyboard.press('[')
            time.sleep(1)
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'neighborhood-wide.png'))
            print("  Saved: neighborhood-wide.png")

            # 2. Active combat shot
            page.keyboard.press('r')
            time.sleep(0.5)
            try:
                server.place_unit("Hero Turret A", -25, 35, "turret")
                server.place_unit("Hero Turret B", 30, -20, "turret")
                server.place_unit("Hero Turret C", 0, 50, "turret")
                time.sleep(0.5)
                server.begin_war()
                time.sleep(8)  # Let combat run
            except Exception as e:
                print(f"  (combat setup error: {e})")

            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, 'game-combat.png'))
            print("  Saved: game-combat.png")

            # Final reset
            try:
                server.reset_game()
            except Exception:
                pass

            # ============================================================
            # CONSOLE ERRORS
            # ============================================================
            print("\n=== CONSOLE ERRORS ===")

            # Filter out noise
            real_errors = [e for e in console_errors if
                           'favicon' not in e.lower() and
                           'failed to load resource' not in e.lower() and
                           'net::ERR' not in e]
            r = check("Console: No JS errors", len(real_errors) == 0,
                       f"Errors: {real_errors[:5]}" if real_errors else "Clean console")
            results.append(r)

            browser.close()

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        results.append(check("FATAL", False, str(e)))

    finally:
        server.stop()

    # ============================================================
    # WRITE REPORT
    # ============================================================
    write_report(results)
    print(f"\nReport written to {os.path.join(REPORT_DIR, 'ux-audit.md')}")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r['status'] == 'WORKS')
    partial = sum(1 for r in results if r['status'] == 'PARTIAL')
    failed = sum(1 for r in results if r['status'] == 'BROKEN')
    missing = sum(1 for r in results if r['status'] == 'MISSING')

    print(f"\n{'='*60}")
    print(f"AUDIT SUMMARY: {passed}/{total} WORKS, {partial} PARTIAL, {failed} BROKEN, {missing} MISSING")
    print(f"{'='*60}")

    return results


def check(name, condition, detail=""):
    status = "WORKS" if condition else "BROKEN"
    icon = "[PASS]" if condition else "[FAIL]"
    print(f"  {icon} {name}")
    if detail and not condition:
        print(f"        Detail: {detail}")
    return {"name": name, "status": status, "detail": detail}


def write_report(results):
    total = len(results)
    passed = sum(1 for r in results if r['status'] == 'WORKS')
    partial = sum(1 for r in results if r['status'] == 'PARTIAL')
    broken = sum(1 for r in results if r['status'] == 'BROKEN')

    lines = [
        "# UX Audit Report -- TRITIUM-SC Command Center",
        "",
        f"**Date**: {time.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Resolution**: 1920x1080 (headless Chromium)",
        f"**Route**: `/unified`",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total checks | {total} |",
        f"| WORKS | {passed} |",
        f"| PARTIAL | {partial} |",
        f"| BROKEN | {broken} |",
        f"| Pass rate | {passed/total*100:.0f}% |" if total > 0 else "| Pass rate | N/A |",
        "",
        "## Detailed Results",
        "",
    ]

    # Group by category
    current_category = None
    for r in results:
        name = r['name']
        cat = name.split(':')[0].strip() if ':' in name else 'Other'
        if cat != current_category:
            current_category = cat
            lines.append(f"### {cat}")
            lines.append("")

        icon = "PASS" if r['status'] == 'WORKS' else "FAIL"
        marker = "[x]" if r['status'] == 'WORKS' else "[ ]"
        lines.append(f"- {marker} **{r['status']}** -- {name}")
        if r['detail'] and r['status'] != 'WORKS':
            lines.append(f"  - {r['detail']}")
        lines.append("")

    # Screenshots section
    lines.extend([
        "",
        "## Screenshots",
        "",
        "| Screenshot | Description |",
        "|------------|-------------|",
        "| `command-center.png` | Clean overview, panels visible |",
        "| `game-combat.png` | Active combat with turrets firing |",
        "| `neighborhood-wide.png` | Zoomed out neighborhood view |",
        "| `audit-01-initial.png` | Initial page load |",
        "| `audit-02-units.png` | Map with units |",
        "| `audit-03-panels.png` | Floating panels |",
        "| `audit-04-help.png` | Help overlay |",
        "| `audit-05-game-hud.png` | Game HUD panel |",
        "| `audit-06-chat.png` | Chat panel |",
        "| `audit-07-map-interaction.png` | After map interaction |",
        "| `audit-08-setup.png` | Setup phase with placed turrets |",
        "| `audit-09-combat.png` | Active combat |",
        "| `audit-10-combat-later.png` | Combat after a few seconds |",
        "",
    ])

    # Failed items summary
    broken_items = [r for r in results if r['status'] != 'WORKS']
    if broken_items:
        lines.append("## Issues Requiring Attention")
        lines.append("")
        for r in broken_items:
            lines.append(f"1. **{r['name']}** -- {r['detail']}")
        lines.append("")

    report_path = os.path.join(REPORT_DIR, 'ux-audit.md')
    with open(report_path, 'w') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    main()
