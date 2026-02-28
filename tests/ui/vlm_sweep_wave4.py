#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""VLM Comprehensive Sweep - Wave 4
Systematically screenshot every UI state and ask llava:7b to identify defects.
"""
import json, base64, os, time, sys, tempfile
from pathlib import Path
import requests as req

# Use sync playwright
from playwright.sync_api import sync_playwright

OUT = Path("tests/.test-results/vlm-sweep-wave4")
OUT.mkdir(parents=True, exist_ok=True)

def ask_vlm(image_path, prompt):
    """Ask llava:7b about a screenshot using requests library"""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    try:
        resp = req.post("http://localhost:11434/api/generate", json={
            "model": "llava:7b",
            "prompt": prompt,
            "images": [img_b64],
            "stream": False
        }, timeout=120)
        if resp.status_code == 200:
            return resp.json().get("response", "")
        return f"VLM error: HTTP {resp.status_code}"
    except Exception as e:
        return f"VLM error: {e}"

def screenshot(page, name, description=""):
    path = str(OUT / f"{name}.png")
    page.screenshot(path=path)
    print(f"  Screenshot: {name} - {description}")
    return path

results = []
start_time = time.time()

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto("http://localhost:8000", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(3000)  # Let map load

    # --- STATE 1: Default load ---
    print("\n=== STATE 1: Default Load ===")
    path = screenshot(page, "01_default_load", "Initial page load")
    resp = ask_vlm(path, "This is a tactical command center application. Describe what you see. Are there any visual defects, glitches, rendering errors, misaligned elements, or anything that looks broken? Be specific about any issues.")
    results.append(("01_default_load", resp))
    print(f"  VLM: {resp[:200]}")

    # --- STATE 2: All panels hidden ---
    print("\n=== STATE 2: All Panels Hidden ===")
    page.evaluate("window._panelManager?.getRegisteredPanels().forEach(p => window._panelManager.close(p.id))")
    page.wait_for_timeout(500)
    path = screenshot(page, "02_all_panels_hidden", "All panels closed")
    resp = ask_vlm(path, "This is a tactical map view with all side panels hidden. The map should be the only visible element (plus command bar at top). Are there any visual defects, artifacts, overlapping elements, or rendering issues?")
    results.append(("02_all_panels_hidden", resp))
    print(f"  VLM: {resp[:200]}")

    # --- STATE 3: Each panel solo ---
    print("\n=== STATE 3: Each Panel Solo ===")
    panels = ["amy", "units", "alerts", "game"]
    for pid in panels:
        page.evaluate("window._panelManager?.getRegisteredPanels().forEach(p => window._panelManager.close(p.id))")
        page.wait_for_timeout(200)
        page.evaluate(f"window._panelManager?.open('{pid}')")
        page.wait_for_timeout(500)
        path = screenshot(page, f"03_{pid}_panel_solo", f"Only {pid} panel open")
        resp = ask_vlm(path, f"This shows the '{pid}' panel open on a tactical map application. Check for: panel rendering issues, text overflow, color contrast problems, misaligned elements, overlapping content, or any visual defects.")
        results.append((f"03_{pid}_panel_solo", resp))
        print(f"  VLM {pid}: {resp[:200]}")

    # --- STATE 4: All panels open ---
    print("\n=== STATE 4: All Panels Open ===")
    for pid in panels:
        page.evaluate(f"window._panelManager?.open('{pid}')")
    page.wait_for_timeout(500)
    path = screenshot(page, "04_all_panels_open", "All panels open")
    resp = ask_vlm(path, "All side panels are open on this tactical command center. Check for: panel overlap, content clipping, scroll issues, panels pushing off-screen, text readability, any visual defects.")
    results.append(("04_all_panels_open", resp))
    print(f"  VLM: {resp[:200]}")

    # --- STATE 5: Map modes ---
    print("\n=== STATE 5: Map Modes ===")
    for mode in ["observe", "tactical", "setup"]:
        page.evaluate(f"window._mapActions?.setMapMode?.('{mode}')")
        page.wait_for_timeout(1500)
        path = screenshot(page, f"05_mode_{mode}", f"Map mode: {mode}")
        resp = ask_vlm(path, f"This tactical map is in '{mode}' mode. The mode should change the visual appearance (layers shown, pitch angle, etc). Does this look like a properly rendered tactical map? Any visual defects, missing map tiles, broken rendering, or anomalies?")
        results.append((f"05_mode_{mode}", resp))
        print(f"  VLM {mode}: {resp[:200]}")

    # --- STATE 6: Menu dropdowns ---
    print("\n=== STATE 6: Menu Dropdowns ===")
    menus = ["FILE", "VIEW", "LAYOUT", "MAP", "HELP"]
    for menu_name in menus:
        triggers = page.query_selector_all(".menu-trigger")
        for t in triggers:
            if t.text_content().strip() == menu_name:
                t.click()
                page.wait_for_timeout(300)
                path = screenshot(page, f"06_menu_{menu_name.lower()}", f"Menu: {menu_name}")
                resp = ask_vlm(path, f"This shows the '{menu_name}' dropdown menu open on a command bar. Check for: menu positioning, item alignment, text readability, checkmarks visible, shortcut keys shown, any visual issues with the dropdown.")
                results.append((f"06_menu_{menu_name.lower()}", resp))
                print(f"  VLM menu {menu_name}: {resp[:200]}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)
                break

    # --- STATE 7: Help overlay ---
    print("\n=== STATE 7: Help Overlay ===")
    page.keyboard.press("?")
    page.wait_for_timeout(500)
    path = screenshot(page, "07_help_overlay", "Help overlay shown")
    resp = ask_vlm(path, "This shows a keyboard shortcuts help overlay on a tactical application. Check for: overlay positioning, text readability, proper formatting, any visual issues.")
    results.append(("07_help_overlay", resp))
    print(f"  VLM help: {resp[:200]}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # --- STATE 8: All layers off ---
    print("\n=== STATE 8: All Layers Off ===")
    page.evaluate("""
        if (window._mapActions) {
            window._mapActions.setLayers({
                allMapLayers: false
            });
        }
    """)
    page.wait_for_timeout(1000)
    path = screenshot(page, "08_all_layers_off", "All map layers disabled")
    resp = ask_vlm(path, "All map layers have been turned off. The screen should be mostly dark/black with possibly a command bar. Are there any unexpected visible elements, artifacts, or rendering issues?")
    results.append(("08_all_layers_off", resp))
    print(f"  VLM all off: {resp[:200]}")

    # --- STATE 9: Individual layers ---
    print("\n=== STATE 9: Individual Layers ===")
    layers_to_test = [
        ("satellite", "Satellite imagery"),
        ("buildings", "Building outlines (cyan)"),
        ("roads", "Road network"),
        ("waterways", "Waterways/streams"),
        ("parks", "Park areas"),
        ("grid", "Grid overlay"),
        ("models3d", "3D unit models"),
        ("labels", "Unit labels"),
    ]

    for layer_key, layer_desc in layers_to_test:
        page.evaluate("window._mapActions?.setLayers({allMapLayers: false})")
        page.wait_for_timeout(500)
        page.evaluate(f"window._mapActions?.setLayers({{'{layer_key}': true}})")
        page.wait_for_timeout(1000)
        path = screenshot(page, f"09_layer_{layer_key}", f"Only {layer_desc} layer on")
        resp = ask_vlm(path, f"Only the '{layer_desc}' layer is enabled on this tactical map (all others off). The background should be dark/black. Does the {layer_desc} layer render correctly? Any artifacts, wrong colors, misalignment, or visual issues?")
        results.append((f"09_layer_{layer_key}", resp))
        print(f"  VLM layer {layer_key}: {resp[:200]}")

    # --- STATE 10: All layers back on + terrain ---
    print("\n=== STATE 10: Terrain ===")
    page.evaluate("window._mapActions?.setLayers({allMapLayers: true})")
    page.wait_for_timeout(1000)
    page.evaluate("window._mapActions?.toggleTerrain?.()")
    page.wait_for_timeout(2000)
    path = screenshot(page, "10_terrain_enabled", "3D terrain enabled")
    resp = ask_vlm(path, "3D terrain has been enabled on this tactical map. The ground should show elevation/hills/valleys. Does the terrain look correct? Any rendering artifacts, tile gaps, or visual issues?")
    results.append(("10_terrain_enabled", resp))
    print(f"  VLM terrain: {resp[:200]}")

    # --- STATE 11: Battle simulation ---
    print("\n=== STATE 11: Battle Simulation ===")
    try:
        req.post("http://localhost:8000/api/game/reset", timeout=5)
        page.wait_for_timeout(500)
        req.post("http://localhost:8000/api/game/begin", timeout=5)
        page.wait_for_timeout(5000)
        path = screenshot(page, "11_battle_active", "Active battle simulation")
        resp = ask_vlm(path, "An active battle simulation is running on this tactical map. There should be unit markers, possibly combat effects (tracers, explosions). Does everything look correct? Any visual defects, misaligned combat effects, or rendering issues?")
        results.append(("11_battle_active", resp))
        print(f"  VLM battle: {resp[:200]}")

        page.wait_for_timeout(10000)
        path = screenshot(page, "12_battle_mid", "Mid-battle state")
        resp = ask_vlm(path, "This is a mid-battle state of a tactical simulation. There should be active combat, unit markers moving, possibly eliminations. Describe what you see and note any visual defects or rendering issues.")
        results.append(("12_battle_mid", resp))
        print(f"  VLM mid-battle: {resp[:200]}")

    except Exception as e:
        print(f"  Battle test issue: {e}")

    # --- STATE 12: Window resize tests ---
    print("\n=== STATE 12: Window Resize Tests ===")
    for label, w, h in [("narrow", 1024, 768), ("ultrawide", 2560, 1080), ("small", 800, 600)]:
        page.set_viewport_size({"width": w, "height": h})
        page.wait_for_timeout(1000)
        path = screenshot(page, f"13_resize_{label}_{w}x{h}", f"Viewport: {w}x{h}")
        resp = ask_vlm(path, f"This tactical map has been resized to {w}x{h} pixels. Check for: layout breakage, panels overflowing, elements cut off, text truncation, map not filling the viewport, or any responsive design issues.")
        results.append((f"13_resize_{label}_{w}x{h}", resp))
        print(f"  VLM {label}: {resp[:200]}")

    page.set_viewport_size({"width": 1920, "height": 1080})
    page.wait_for_timeout(500)

    # --- STATE 13: Right-click context menu ---
    print("\n=== STATE 13: Right-click Context Menu ===")
    page.mouse.click(960, 540, button="right")
    page.wait_for_timeout(500)
    path = screenshot(page, "14_context_menu", "Right-click context menu")
    resp = ask_vlm(path, "A right-click was performed on the tactical map. If a custom context menu appeared, check its rendering. If no custom menu appeared (just the browser default), note that. Any visual issues?")
    results.append(("14_context_menu", resp))
    print(f"  VLM context menu: {resp[:200]}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)

    # --- STATE 14: Keyboard shortcut modes ---
    print("\n=== STATE 14: Keyboard Shortcut Modes ===")
    for key, mode_name in [("o", "Observe"), ("t", "Tactical"), ("s", "Setup")]:
        page.keyboard.press(key)
        page.wait_for_timeout(1000)
        path = screenshot(page, f"15_key_{key}_{mode_name.lower()}", f"Key '{key}' -> {mode_name} mode")
        resp = ask_vlm(path, f"The '{key}' key was pressed to switch to {mode_name} mode. Does the map appearance change appropriately? Any visual issues?")
        results.append((f"15_key_{key}_{mode_name.lower()}", resp))
        print(f"  VLM key {key}: {resp[:200]}")

    # --- STATE 15: Amy panel interaction ---
    print("\n=== STATE 15: Amy Panel Chat ===")
    page.evaluate("window._panelManager?.getRegisteredPanels().forEach(p => window._panelManager.close(p.id))")
    page.wait_for_timeout(200)
    page.evaluate("window._panelManager?.open('amy')")
    page.wait_for_timeout(500)
    chat_input = page.query_selector("#amy-chat-input, .amy-chat-input, input[placeholder*='chat'], input[placeholder*='Chat'], textarea[placeholder*='Amy']")
    if chat_input:
        chat_input.fill("Status report")
        page.wait_for_timeout(200)
        path = screenshot(page, "16_amy_chat_input", "Amy chat with typed input")
        resp = ask_vlm(path, "The Amy AI panel is open with text typed in the chat input. Check the input field rendering, placeholder text, panel layout, any visual issues.")
        results.append(("16_amy_chat_input", resp))
        print(f"  VLM amy chat: {resp[:200]}")
    else:
        print("  No chat input found, skipping amy chat screenshot")

    # --- STATE 16: Game panel details ---
    print("\n=== STATE 16: Game Panel ===")
    page.evaluate("window._panelManager?.getRegisteredPanels().forEach(p => window._panelManager.close(p.id))")
    page.wait_for_timeout(200)
    page.evaluate("window._panelManager?.open('game')")
    page.wait_for_timeout(500)
    path = screenshot(page, "17_game_panel", "Game panel solo")
    resp = ask_vlm(path, "This shows the 'game' panel on a tactical command center. It should display game/battle status, scores, wave info. Check for: text readability, layout issues, button styling, any visual defects.")
    results.append(("17_game_panel", resp))
    print(f"  VLM game panel: {resp[:200]}")

    # --- STATE 17: Full layout restore ---
    print("\n=== STATE 17: Full Layout Restore ===")
    for pid in panels:
        page.evaluate(f"window._panelManager?.open('{pid}')")
    page.evaluate("window._mapActions?.setMapMode?.('tactical')")
    page.evaluate("window._mapActions?.setLayers({allMapLayers: true})")
    page.wait_for_timeout(1000)
    path = screenshot(page, "18_full_layout_restored", "Full layout restored")
    resp = ask_vlm(path, "All panels are open, all map layers enabled, tactical mode active. This is the full command center view. Give an overall assessment: does this look like a professional tactical command center? Note any visual polish issues, alignment problems, or rendering defects.")
    results.append(("18_full_layout_restored", resp))
    print(f"  VLM full layout: {resp[:200]}")

    browser.close()

elapsed = time.time() - start_time
print(f"\n{'='*60}")
print(f"VLM Sweep completed in {elapsed:.1f}s ({len(results)} screenshots analyzed)")
print(f"{'='*60}")

# Write report
report_path = str(OUT / "vlm_sweep_report.txt")
defect_keywords = ["defect", "broken", "error", "issue", "problem", "artifact",
                   "glitch", "misalign", "overlap", "clip", "missing", "wrong",
                   "incorrect", "bug", "truncat", "overflow", "cut off", "gap",
                   "inconsisten", "blurr", "pixelat", "distort"]

with open(report_path, "w") as f:
    f.write("VLM Comprehensive Sweep - Wave 4\n")
    f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"Duration: {elapsed:.1f}s\n")
    f.write(f"Screenshots: {len(results)}\n")
    f.write("=" * 60 + "\n\n")
    for name, response in results:
        f.write(f"--- {name} ---\n")
        f.write(response + "\n\n")

    # Defect summary
    f.write("\n" + "=" * 60 + "\n")
    f.write("DEFECT SUMMARY\n")
    f.write("=" * 60 + "\n")
    defect_count = 0
    for name, response in results:
        lower = response.lower()
        found = [kw for kw in defect_keywords if kw in lower]
        if found:
            defect_count += 1
            f.write(f"\n[FLAGGED] {name}: Keywords: {', '.join(found)}\n")
            for sentence in response.split('.'):
                if any(kw in sentence.lower() for kw in defect_keywords):
                    f.write(f"  -> {sentence.strip()}\n")

    f.write(f"\n\nTotal flagged: {defect_count}/{len(results)} screenshots\n")

    f.write("\n" + "=" * 60 + "\n")
    f.write("CLEAN SCREENSHOTS (no defect keywords)\n")
    f.write("=" * 60 + "\n")
    for name, response in results:
        lower = response.lower()
        found = [kw for kw in defect_keywords if kw in lower]
        if not found:
            f.write(f"  [OK] {name}\n")

print(f"\nReport: {report_path}")
print(f"Screenshots: {OUT}/")

# Print defect summary to stdout
print("\n" + "=" * 60)
print("DEFECT SUMMARY")
print("=" * 60)
defect_found = False
for name, response in results:
    lower = response.lower()
    found = [kw for kw in defect_keywords if kw in lower]
    if found:
        defect_found = True
        print(f"\n[FLAGGED] {name}: {', '.join(found)}")
        for sentence in response.split('.'):
            if any(kw in sentence.lower() for kw in defect_keywords):
                print(f"  -> {sentence.strip()}")

if not defect_found:
    print("  No defects flagged by VLM!")
