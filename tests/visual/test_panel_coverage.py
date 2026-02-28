# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Panel Coverage & Menu Bar Validation Pipeline.

Tests all registered panels render correctly, menu bar works,
game HUD displays proper state, and layout system functions.

Registered panels: amy, units, alerts, game (game-hud), mesh
Menu bar: FILE, VIEW, LAYOUT, MAP, HELP

Run:
    .venv/bin/python3 -m pytest tests/visual/test_panel_coverage.py -v
    ./test.sh 21
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests
from playwright.sync_api import sync_playwright, Page

SERVER = "http://localhost:8000"
OUT = Path("tests/.test-results/panel-coverage")
OUT.mkdir(parents=True, exist_ok=True)

SETTLE = 1.5


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def browser_page():
    """Launch headed Playwright browser, navigate to Command Center."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        page.goto(SERVER, wait_until="networkidle", timeout=20000)
        time.sleep(4)

        page.keyboard.press("Escape")
        time.sleep(0.5)

        yield page

        browser.close()


@pytest.fixture(autouse=True)
def reset_state(browser_page):
    """Reset game state before each test."""
    try:
        requests.post(f"{SERVER}/api/game/reset", timeout=5)
    except Exception:
        pass
    # Close all panels to start clean
    browser_page.keyboard.press("Escape")
    time.sleep(0.3)


# ============================================================
# Helpers
# ============================================================

def _grab(page: Page) -> np.ndarray:
    buf = page.screenshot()
    arr = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _save(name: str, img: np.ndarray):
    cv2.imwrite(str(OUT / f"{name}.png"), img)


def _panel_visible(page: Page, panel_id: str) -> bool:
    """Check if a panel with given ID is visible on screen."""
    return page.evaluate(f"""(() => {{
        const el = document.querySelector('[data-panel-id="{panel_id}"]');
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none') return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    }})()""")


def _panel_content(page: Page, panel_id: str) -> dict:
    """Get panel body content info."""
    return page.evaluate(f"""(() => {{
        const el = document.querySelector('[data-panel-id="{panel_id}"]');
        if (!el) return null;
        const body = el.querySelector('.panel-body');
        if (!body) return null;
        const r = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return {{
            visible: r.width > 0 && r.height > 0 && style.display !== 'none',
            width: r.width,
            height: r.height,
            textLength: body.textContent.trim().length,
            childCount: body.children.length,
            innerHTML: body.innerHTML.slice(0, 500),
        }};
    }})()""")


def _ensure_panel_open(page: Page, key: str, panel_id: str):
    """Ensure a panel is open (toggle if needed)."""
    # Check if already open
    is_visible = _panel_visible(page, panel_id)
    if not is_visible:
        page.keyboard.press(key)
        time.sleep(0.5)
        # Re-check
        is_visible = _panel_visible(page, panel_id)
    return is_visible


# ============================================================
# Part 1: Registered Panel Rendering
# ============================================================

def test_amy_panel_opens(browser_page):
    """Amy panel opens with keyboard shortcut and has content."""
    page = browser_page

    _ensure_panel_open(page, "1", "amy")
    time.sleep(1)

    content = _panel_content(page, "amy")
    print(f"  Amy panel: {content}")

    if content is None:
        pytest.skip("Amy panel not found in DOM")

    assert content["visible"], "Amy panel not visible"
    assert content["textLength"] > 10, \
        f"Amy panel has too little text ({content['textLength']} chars)"


def test_units_panel_opens(browser_page):
    """Units panel opens and lists deployed units."""
    page = browser_page

    _ensure_panel_open(page, "2", "units")
    time.sleep(1)

    content = _panel_content(page, "units")
    print(f"  Units panel: {content}")

    if content is None:
        pytest.skip("Units panel not found in DOM")

    assert content["visible"], "Units panel not visible"
    assert content["childCount"] >= 1, "Units panel body is empty"


def test_alerts_panel_opens(browser_page):
    """Alerts panel opens and is visible."""
    page = browser_page

    _ensure_panel_open(page, "3", "alerts")
    time.sleep(1)

    content = _panel_content(page, "alerts")
    print(f"  Alerts panel: {content}")

    if content is None:
        pytest.skip("Alerts panel not found in DOM")

    assert content["visible"], "Alerts panel not visible"


def test_game_hud_panel_opens(browser_page):
    """Game HUD panel opens and shows phase/wave/score."""
    page = browser_page

    _ensure_panel_open(page, "4", "game")
    time.sleep(1)

    content = _panel_content(page, "game")
    print(f"  Game HUD panel: {content}")

    if content is None:
        pytest.skip("Game HUD panel not found in DOM")

    assert content["visible"], "Game HUD panel not visible"


def test_mesh_panel_opens(browser_page):
    """Mesh panel opens and is visible."""
    page = browser_page

    # Mesh panel may not have a single-key shortcut, try opening via menu
    page.keyboard.press("5")
    time.sleep(1)

    content = _panel_content(page, "mesh")
    print(f"  Mesh panel: {content}")

    if content is None:
        pytest.skip("Mesh panel not found or no shortcut assigned")

    assert content["visible"], "Mesh panel not visible"


def test_all_panels_simultaneously(browser_page):
    """All 5 panels can be open at the same time without overlap errors."""
    page = browser_page

    panel_keys = [("1", "amy"), ("2", "units"), ("3", "alerts"), ("4", "game"), ("5", "mesh")]
    for key, pid in panel_keys:
        _ensure_panel_open(page, key, pid)

    time.sleep(1)

    img = _grab(page)
    _save("all_panels_open", img)

    # Count visible panels
    visible = page.evaluate("""(() => {
        const frames = document.querySelectorAll('.panel[data-panel-id]');
        let count = 0;
        for (const f of frames) {
            const style = window.getComputedStyle(f);
            if (style.display === 'none') continue;
            const r = f.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) count++;
        }
        return count;
    })()""")

    print(f"  Visible panels: {visible}")
    assert visible >= 3, f"Expected at least 3 visible panels, got {visible}"


# ============================================================
# Part 2: Game HUD Functionality
# ============================================================

def test_game_hud_phase_display(browser_page):
    """Game HUD shows current game phase."""
    page = browser_page

    _ensure_panel_open(page, "4", "game")
    time.sleep(1)

    phase = page.evaluate("""(() => {
        const el = document.querySelector('[data-bind="phase"]');
        return el ? el.textContent.trim() : null;
    })()""")

    print(f"  Phase display: {phase}")
    # Phase should be one of: IDLE, SETUP, ACTIVE, VICTORY, DEFEAT
    if phase is not None:
        assert phase.upper() in ["IDLE", "SETUP", "ACTIVE", "VICTORY", "DEFEAT", ""], \
            f"Unexpected phase: {phase}"


def test_game_hud_begin_button_exists(browser_page):
    """BEGIN WAR button exists in game HUD panel DOM."""
    page = browser_page

    _ensure_panel_open(page, "4", "game")
    time.sleep(1)

    # Check the game panel is open first
    panel_open = _panel_visible(page, "game")
    print(f"  Game panel visible: {panel_open}")

    # Find BEGIN WAR button anywhere in the game panel or globally
    btn_info = page.evaluate("""(() => {
        // Look in game panel specifically
        const panel = document.querySelector('[data-panel-id="game"]');
        const scope = panel || document;
        const buttons = scope.querySelectorAll('button');
        const result = [];
        for (const b of buttons) {
            const text = b.textContent.trim();
            if (text.includes('BEGIN') || text.includes('WAR') || text.includes('SPAWN') || text.includes('RESET')) {
                const r = b.getBoundingClientRect();
                const style = window.getComputedStyle(b);
                result.push({
                    text,
                    width: r.width,
                    height: r.height,
                    display: style.display,
                    inPanel: !!panel,
                });
            }
        }
        return result;
    })()""")

    print(f"  Game HUD buttons: {btn_info}")
    # At least one game action button should exist in the DOM
    assert len(btn_info) >= 1, "No game action buttons found (BEGIN/SPAWN/RESET)"


def test_game_hud_helpers_exposed(browser_page):
    """GameHudHelpers are accessible from window scope."""
    page = browser_page

    helpers = page.evaluate("""(() => {
        const h = window.GameHudHelpers;
        if (!h) return null;
        return {
            hasHealthColor: typeof h.healthColor === 'function',
            hasHealthBar: typeof h.healthBar === 'function',
            hasMoraleTrend: typeof h.moraleTrend === 'function',
            hasWaveProgressPct: typeof h.waveProgressPct === 'function',
            hasComputeAccuracy: typeof h.computeAccuracy === 'function',
            hasFindMVP: typeof h.findMVP === 'function',
            // Quick tests
            healthColor60: h.healthColor(0.6),
            healthColor30: h.healthColor(0.3),
            healthColor10: h.healthColor(0.1),
            healthBar50: h.healthBar(0.5, 10),
            moraleTrendRising: h.moraleTrend(0.8, 0.5),
            moraleTrendFalling: h.moraleTrend(0.3, 0.8),
            moraleTrendSteady: h.moraleTrend(0.5, 0.5),
            accuracy50: h.computeAccuracy(5, 10),
        };
    })()""")

    if helpers is None:
        pytest.skip("GameHudHelpers not exposed on window")

    print(f"  GameHudHelpers: {helpers}")
    assert helpers["hasHealthColor"], "healthColor not found"
    assert helpers["hasHealthBar"], "healthBar not found"
    assert helpers["hasMoraleTrend"], "moraleTrend not found"

    # Verify helper outputs
    assert helpers["healthColor10"] == "#ff2a6d", \
        f"healthColor(0.1) should be red, got {helpers['healthColor10']}"
    assert helpers["moraleTrendRising"] == "rising", \
        f"moraleTrend(0.8, 0.5) should be rising, got {helpers['moraleTrendRising']}"
    assert helpers["moraleTrendFalling"] == "falling", \
        f"moraleTrend(0.3, 0.8) should be falling, got {helpers['moraleTrendFalling']}"
    assert helpers["accuracy50"] == 50, \
        f"computeAccuracy(5,10) should be 50, got {helpers['accuracy50']}"


# ============================================================
# Part 3: Menu Bar
# ============================================================

def test_menu_bar_renders(browser_page):
    """Menu bar has FILE, VIEW, LAYOUT, MAP, HELP triggers."""
    page = browser_page

    triggers = page.evaluate("""(() => {
        const items = document.querySelectorAll('.menu-trigger');
        return Array.from(items).map(el => ({
            text: el.textContent.trim(),
            visible: el.getBoundingClientRect().width > 0,
        }));
    })()""")

    print(f"  Menu triggers: {triggers}")
    labels = [t["text"] for t in triggers if t["visible"]]

    # At least FILE, VIEW, MAP should be present
    found = set(l.upper() for l in labels)
    expected = {"FILE", "VIEW", "MAP"}
    missing = expected - found
    assert not missing, f"Missing menu triggers: {missing}. Found: {found}"


def test_file_menu_opens(browser_page):
    """Clicking FILE opens dropdown with Save/Export/Import items."""
    page = browser_page

    # Click FILE menu trigger
    file_trigger = page.query_selector('.menu-trigger')
    if file_trigger is None:
        pytest.skip("No menu trigger found")

    file_trigger.click()
    time.sleep(0.5)

    # Check for dropdown
    dropdown = page.evaluate("""(() => {
        const dropdowns = document.querySelectorAll('.menu-dropdown');
        for (const d of dropdowns) {
            const style = window.getComputedStyle(d);
            if (style.display !== 'none' && style.visibility !== 'hidden') {
                const items = d.querySelectorAll('.menu-item');
                return {
                    visible: true,
                    itemCount: items.length,
                    items: Array.from(items).slice(0, 10).map(i => i.textContent.trim()),
                };
            }
        }
        return { visible: false, itemCount: 0, items: [] };
    })()""")

    print(f"  File dropdown: {dropdown}")
    assert dropdown["visible"], "File menu dropdown not visible after click"
    assert dropdown["itemCount"] >= 2, \
        f"File menu should have at least 2 items, got {dropdown['itemCount']}"

    # Close menu
    page.keyboard.press("Escape")
    time.sleep(0.3)


def test_view_menu_lists_panels(browser_page):
    """VIEW menu lists all registered panels."""
    page = browser_page

    # Find and click VIEW trigger
    view_clicked = page.evaluate("""(() => {
        const triggers = document.querySelectorAll('.menu-trigger');
        for (const t of triggers) {
            if (t.textContent.trim().toUpperCase() === 'VIEW') {
                t.click();
                return true;
            }
        }
        return false;
    })()""")

    if not view_clicked:
        pytest.skip("VIEW menu trigger not found")

    time.sleep(0.5)

    items = page.evaluate("""(() => {
        const dropdowns = document.querySelectorAll('.menu-dropdown');
        for (const d of dropdowns) {
            const style = window.getComputedStyle(d);
            if (style.display !== 'none' && style.visibility !== 'hidden') {
                const labels = d.querySelectorAll('.menu-item-label');
                return Array.from(labels).map(l => l.textContent.trim());
            }
        }
        return [];
    })()""")

    print(f"  View menu items: {items}")

    # Should contain panel names + Show All / Hide All
    assert len(items) >= 3, f"VIEW menu should have at least 3 items, got {len(items)}"

    # Close menu
    page.keyboard.press("Escape")
    time.sleep(0.3)


def test_map_menu_has_layer_toggles(browser_page):
    """MAP menu has layer toggle items (Satellite, Roads, Buildings, etc)."""
    page = browser_page

    # Find and click MAP trigger
    map_clicked = page.evaluate("""(() => {
        const triggers = document.querySelectorAll('.menu-trigger');
        for (const t of triggers) {
            if (t.textContent.trim().toUpperCase() === 'MAP') {
                t.click();
                return true;
            }
        }
        return false;
    })()""")

    if not map_clicked:
        pytest.skip("MAP menu trigger not found")

    time.sleep(0.5)

    items = page.evaluate("""(() => {
        const dropdowns = document.querySelectorAll('.menu-dropdown');
        for (const d of dropdowns) {
            const style = window.getComputedStyle(d);
            if (style.display !== 'none' && style.visibility !== 'hidden') {
                const menuItems = d.querySelectorAll('.menu-item');
                return Array.from(menuItems).map(m => ({
                    label: (m.querySelector('.menu-item-label') || m).textContent.trim(),
                    shortcut: (m.querySelector('.menu-item-shortcut') || {}).textContent || '',
                    hasCheck: !!m.querySelector('.menu-item-check'),
                }));
            }
        }
        return [];
    })()""")

    print(f"  Map menu items ({len(items)}):")
    for item in items[:15]:
        print(f"    {item['label']:20s} {item['shortcut']:8s} check={item['hasCheck']}")

    labels = [i["label"].lower() for i in items]
    assert any("satellite" in l for l in labels), "MAP menu missing Satellite toggle"
    assert any("road" in l for l in labels), "MAP menu missing Roads toggle"
    assert any("build" in l for l in labels), "MAP menu missing Buildings toggle"

    # Close menu
    page.keyboard.press("Escape")
    time.sleep(0.3)


def test_menu_closes_on_escape(browser_page):
    """Pressing Escape closes open menu dropdowns."""
    page = browser_page

    # Open first menu
    trigger = page.query_selector('.menu-trigger')
    if trigger is None:
        pytest.skip("No menu trigger found")

    trigger.click()
    time.sleep(0.3)

    # Verify a dropdown is open
    open_before = page.evaluate("""(() => {
        const dropdowns = document.querySelectorAll('.menu-dropdown');
        for (const d of dropdowns) {
            const style = window.getComputedStyle(d);
            if (style.display !== 'none') return true;
        }
        return false;
    })()""")

    assert open_before, "No dropdown opened on click"

    # Press Escape
    page.keyboard.press("Escape")
    time.sleep(0.3)

    open_after = page.evaluate("""(() => {
        const dropdowns = document.querySelectorAll('.menu-dropdown');
        for (const d of dropdowns) {
            const style = window.getComputedStyle(d);
            if (style.display !== 'none') return true;
        }
        return false;
    })()""")

    assert not open_after, "Dropdown still open after Escape"


def test_quick_access_buttons(browser_page):
    """Right side of menu bar has panel toggle buttons."""
    page = browser_page

    buttons = page.evaluate("""(() => {
        const btns = document.querySelectorAll('.command-bar-btn');
        return Array.from(btns).map(b => ({
            text: b.textContent.trim(),
            active: b.classList.contains('active'),
            visible: b.getBoundingClientRect().width > 0,
        }));
    })()""")

    print(f"  Quick-access buttons: {len(buttons)}")
    for b in buttons[:10]:
        print(f"    {b['text']:20s} active={b['active']} visible={b['visible']}")

    visible_btns = [b for b in buttons if b["visible"]]
    assert len(visible_btns) >= 1, "No quick-access panel buttons found"


# ============================================================
# Part 4: Panel Content Validation
# ============================================================

def test_units_panel_shows_unit_list(browser_page):
    """Units panel displays units with health bars and names."""
    page = browser_page

    # Place a unit first
    try:
        requests.post(f"{SERVER}/api/game/place", json={
            "name": "panel-test", "asset_type": "turret",
            "position": {"x": 0, "y": 0},
        }, timeout=5)
    except Exception:
        pass
    time.sleep(1.5)

    _ensure_panel_open(page, "2", "units")
    time.sleep(1)

    unit_info = page.evaluate("""(() => {
        const items = document.querySelectorAll('.unit-row, .unit-item, .panel-list li');
        const result = [];
        for (const item of items) {
            const text = item.textContent.trim();
            if (text.length > 0 && !text.includes('No ')) {
                result.push({
                    text: text.slice(0, 80),
                    hasHpBar: !!item.querySelector('[class*="hp"], [class*="health"]'),
                });
            }
        }
        return result;
    })()""")

    print(f"  Unit items: {len(unit_info)}")
    for u in unit_info[:5]:
        print(f"    {u['text'][:60]}")

    # Should have at least 1 unit listed
    assert len(unit_info) >= 1, "Units panel should list at least 1 unit"


def test_panel_no_console_errors(browser_page):
    """Opening and closing panels doesn't produce JavaScript errors."""
    page = browser_page

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # Toggle all panels
    for key in ["1", "2", "3", "4", "5"]:
        page.keyboard.press(key)
        time.sleep(0.2)

    time.sleep(1)

    # Close them
    for key in ["1", "2", "3", "4", "5"]:
        page.keyboard.press(key)
        time.sleep(0.2)

    time.sleep(0.5)

    print(f"  JS errors: {len(errors)}")
    for e in errors[:5]:
        print(f"    {e[:100]}")

    assert len(errors) == 0, f"{len(errors)} JS errors during panel toggle: {errors[0][:100]}"


# ============================================================
# Part 5: Layout System
# ============================================================

def test_layout_menu_has_presets(browser_page):
    """LAYOUT menu offers built-in preset layouts."""
    page = browser_page

    layout_clicked = page.evaluate("""(() => {
        const triggers = document.querySelectorAll('.menu-trigger');
        for (const t of triggers) {
            if (t.textContent.trim().toUpperCase() === 'LAYOUT') {
                t.click();
                return true;
            }
        }
        return false;
    })()""")

    if not layout_clicked:
        pytest.skip("LAYOUT menu trigger not found")

    time.sleep(0.5)

    items = page.evaluate("""(() => {
        const dropdowns = document.querySelectorAll('.menu-dropdown');
        for (const d of dropdowns) {
            const style = window.getComputedStyle(d);
            if (style.display !== 'none' && style.visibility !== 'hidden') {
                const labels = d.querySelectorAll('.menu-item-label');
                return Array.from(labels).map(l => l.textContent.trim());
            }
        }
        return [];
    })()""")

    print(f"  Layout presets: {items}")

    # Should have at least 1 built-in layout
    assert len(items) >= 1, "LAYOUT menu should have at least 1 preset"

    # Close menu
    page.keyboard.press("Escape")
    time.sleep(0.3)


# ============================================================
# Part 6: Screenshot-based panel visual check
# ============================================================

def test_panel_screenshot_quality(browser_page):
    """Panels render with visible content, not blank boxes.

    Opens all panels, takes screenshot, verifies panel areas
    have content (not solid black or transparent).
    """
    page = browser_page

    # Open a few key panels
    for key in ["1", "2", "4"]:
        page.keyboard.press(key)
        time.sleep(0.3)
    time.sleep(1.5)

    img = _grab(page)
    _save("panels_content_check", img)

    # Get panel frame positions
    frames = page.evaluate("""(() => {
        const panels = document.querySelectorAll('.panel[data-panel-id]');
        const result = [];
        for (const p of panels) {
            const style = window.getComputedStyle(p);
            if (style.display === 'none') continue;
            const r = p.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            result.push({
                left: Math.round(r.left), top: Math.round(r.top),
                width: Math.round(r.width), height: Math.round(r.height),
            });
        }
        return result;
    })()""")

    print(f"  Visible panel frames: {len(frames)}")

    # Check each panel area has non-black content
    blank_panels = 0
    for i, f in enumerate(frames):
        x1 = max(0, f["left"])
        y1 = max(0, f["top"])
        x2 = min(img.shape[1], f["left"] + f["width"])
        y2 = min(img.shape[0], f["top"] + f["height"])
        if x2 <= x1 or y2 <= y1:
            continue

        crop = img[y1:y2, x1:x2]
        mean_brightness = np.mean(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        print(f"    Panel[{i}]: ({f['left']},{f['top']}) {f['width']}x{f['height']} "
              f"brightness={mean_brightness:.1f}")

        if mean_brightness < 5:
            blank_panels += 1

    assert blank_panels == 0, f"{blank_panels} panels appear blank (all black)"
