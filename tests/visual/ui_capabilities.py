# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Modular UI testing capabilities.

Each capability is a small, independent function that does ONE thing.
Compose them to build complex test sequences.

Capabilities don't process data — they interact with the UI and return raw results.
The test functions decide what to assert.

Usage:
    from tests.visual.ui_capabilities import (
        launch_browser, ensure_server, open_menu, click_menu_item,
        discover_menu_items, open_layers_panel, discover_layers,
        toggle_layer, screenshot, check_js_errors,
    )
"""

import time
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Output directory for all test screenshots
SCREENSHOT_DIR = Path(os.environ.get("TRITIUM_TEST_SCREENSHOTS", "/tmp/tritium_test"))
SCREENSHOT_DIR.mkdir(exist_ok=True)


@dataclass
class UIResult:
    """Result from any UI capability."""
    success: bool
    message: str = ""
    data: dict = field(default_factory=dict)
    screenshot: Optional[str] = None


# ---------------------------------------------------------------------------
# Browser lifecycle
# ---------------------------------------------------------------------------

def launch_browser(playwright, headless=True, width=1920, height=1080):
    """Launch a Chromium browser and return (browser, page)."""
    browser = playwright.chromium.launch(headless=headless, args=["--disable-gpu"])
    page = browser.new_page(viewport={"width": width, "height": height})
    return browser, page


def navigate(page, url="http://localhost:8000", wait=5):
    """Navigate to URL and wait for load."""
    page.goto(url, timeout=20000)
    time.sleep(wait)
    return UIResult(success=True, message=f"Navigated to {url}")


def ensure_server(url="http://localhost:8000/health"):
    """Check if the server is running. Returns UIResult."""
    import requests
    try:
        r = requests.get(url, timeout=3)
        return UIResult(success=r.status_code == 200, message=f"Server status: {r.status_code}")
    except Exception as e:
        return UIResult(success=False, message=f"Server unreachable: {e}")


def start_demo(url="http://localhost:8000/api/demo/start"):
    """Start demo mode via API."""
    import requests
    try:
        r = requests.post(url, timeout=5)
        return UIResult(success=r.ok, data=r.json() if r.ok else {})
    except Exception as e:
        return UIResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------

def screenshot(page, name, subdir=""):
    """Take a screenshot with a descriptive name."""
    d = SCREENSHOT_DIR / subdir if subdir else SCREENSHOT_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = str(d / f"{name}.png")
    page.screenshot(path=path)
    return UIResult(success=True, screenshot=path, message=f"Screenshot: {path}")


# ---------------------------------------------------------------------------
# Error checking
# ---------------------------------------------------------------------------

def collect_js_errors(page, duration=0):
    """Collect JS errors over a time period. Returns list of error strings."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if duration > 0:
        time.sleep(duration)
    return errors


# ---------------------------------------------------------------------------
# Menu interaction
# ---------------------------------------------------------------------------

def open_menu(page, menu_label):
    """Click a menu trigger by its label text. Returns UIResult."""
    triggers = page.query_selector_all(".menu-trigger")
    for t in triggers:
        if t.text_content().strip() == menu_label:
            t.click()
            time.sleep(0.3)
            return UIResult(success=True, message=f"Opened {menu_label} menu")
    return UIResult(success=False, message=f"Menu '{menu_label}' not found")


def close_menu(page):
    """Close any open menu dropdown."""
    page.keyboard.press("Escape")
    time.sleep(0.2)
    return UIResult(success=True)


def discover_menu_items(page, menu_label):
    """Open a menu and return all item labels. Closes menu after."""
    result = open_menu(page, menu_label)
    if not result.success:
        return []

    items = page.query_selector_all(".menu-dropdown:not([hidden]) .menu-item")
    labels = []
    for item in items:
        text = item.text_content().strip()
        if text and text not in ("", "Show All", "Hide All", "Fullscreen"):
            # Check if it's a checkable item (has a bullet/check indicator)
            check = item.query_selector(".menu-check")
            labels.append({
                "label": text,
                "checkable": check is not None,
                "checked": check.text_content().strip() == "\u2022" if check else False,
            })

    close_menu(page)
    return labels


def click_menu_item(page, menu_label, item_label):
    """Open a menu and click a specific item by label."""
    result = open_menu(page, menu_label)
    if not result.success:
        return result

    items = page.query_selector_all(".menu-dropdown:not([hidden]) .menu-item")
    for item in items:
        if item.text_content().strip() == item_label:
            item.click()
            time.sleep(0.3)
            return UIResult(success=True, message=f"Clicked '{item_label}' in {menu_label}")

    close_menu(page)
    return UIResult(success=False, message=f"Item '{item_label}' not found in {menu_label}")


# ---------------------------------------------------------------------------
# Layers panel
# ---------------------------------------------------------------------------

def open_layers_panel(page):
    """Open the Layers panel via L key."""
    page.keyboard.press("l")
    time.sleep(0.5)
    panel = page.query_selector(".layers-panel-inner")
    return UIResult(success=panel is not None, message="Layers panel opened" if panel else "Layers panel not found")


def discover_layers(page):
    """Find all layer checkboxes in the open Layers panel. Returns list of dicts."""
    checkboxes = page.query_selector_all('.layers-panel-inner input[type="checkbox"]')
    layers = []
    for cb in checkboxes:
        key = cb.get_attribute("data-key") or cb.get_attribute("data-event-toggle") or ""
        if not key:
            continue
        checked = cb.is_checked()

        # Get label from parent
        parent = cb.evaluate_handle("el => el.closest('.layer-item')")
        label_el = parent.query_selector(".layer-label") if parent else None
        label = label_el.text_content().strip() if label_el else key

        # Get category from grandparent
        cat_el = parent.query_selector("xpath=ancestor::div[contains(@class,'layer-category')]//span[contains(@class,'layer-cat-name')]") if parent else None
        category = cat_el.text_content().strip() if cat_el else "Unknown"

        layers.append({
            "key": key,
            "label": label,
            "category": category,
            "checked": checked,
        })
    return layers


def toggle_layer(page, key):
    """Toggle a layer checkbox by its data-key. Returns UIResult."""
    cb = page.query_selector(f'input[data-key="{key}"]')
    if not cb:
        cb = page.query_selector(f'input[data-event-toggle="{key}"]')
    if not cb:
        return UIResult(success=False, message=f"Checkbox '{key}' not found")

    try:
        cb.scroll_into_view_if_needed(timeout=2000)
        was_checked = cb.is_checked()
        cb.click(timeout=2000)
        time.sleep(0.3)
        now_checked = cb.is_checked()
        return UIResult(
            success=was_checked != now_checked,
            message=f"{key}: {'ON' if now_checked else 'OFF'}",
            data={"key": key, "was": was_checked, "now": now_checked},
        )
    except Exception as e:
        return UIResult(success=False, message=f"Toggle failed: {e}")


def hide_all_layers(page):
    """Click HIDE button in layers panel."""
    btn = page.query_selector(".layers-btn-hide-all")
    if btn:
        btn.click()
        time.sleep(0.5)
        return UIResult(success=True, message="All layers hidden")
    return UIResult(success=False, message="HIDE button not found")


def show_all_layers(page):
    """Click SHOW button in layers panel."""
    btn = page.query_selector(".layers-btn-show-all")
    if btn:
        btn.click()
        time.sleep(0.5)
        return UIResult(success=True, message="All layers shown")
    return UIResult(success=False, message="SHOW button not found")


def expand_all_categories(page):
    """Click EXPAND button in layers panel."""
    btn = page.query_selector(".layers-btn-expand-all")
    if btn:
        btn.click()
        time.sleep(0.2)
        return UIResult(success=True)
    return UIResult(success=False, message="EXPAND button not found")


def collapse_all_categories(page):
    """Click COLLAPSE button in layers panel."""
    btn = page.query_selector(".layers-btn-collapse-all")
    if btn:
        btn.click()
        time.sleep(0.2)
        return UIResult(success=True)
    return UIResult(success=False, message="COLLAPSE button not found")


# ---------------------------------------------------------------------------
# Keyboard shortcuts
# ---------------------------------------------------------------------------

def press_key(page, key, wait=0.5):
    """Press a keyboard key and wait."""
    page.keyboard.press(key)
    time.sleep(wait)
    return UIResult(success=True, message=f"Pressed {key}")


# ---------------------------------------------------------------------------
# Element queries
# ---------------------------------------------------------------------------

def count_visible(page, selector):
    """Count visible elements matching a CSS selector."""
    elements = page.query_selector_all(selector)
    visible = [e for e in elements if e.is_visible()]
    return len(visible)


def read_text(page, selector):
    """Read text content of first element matching selector."""
    el = page.query_selector(selector)
    if el:
        return el.text_content().strip()
    return None


def element_exists(page, selector):
    """Check if an element exists in the DOM."""
    return page.query_selector(selector) is not None


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_sweep_report(results, title, output_path):
    """Generate a markdown report from sweep results."""
    md = f"# {title}\n\n"
    md += f"**Total items:** {len(results)}\n"
    md += f"**Passed:** {sum(1 for r in results if r.get('status') == 'PASS')}\n"
    md += f"**Failed:** {sum(1 for r in results if r.get('status') == 'FAIL')}\n"
    md += f"**Skipped:** {sum(1 for r in results if r.get('status') == 'SKIP')}\n\n"

    md += "| # | Name | Status | Screenshot | Notes |\n"
    md += "|---|------|--------|------------|-------|\n"
    for i, r in enumerate(results):
        name = r.get("name", "?")
        status = r.get("status", "?")
        shot = r.get("screenshot", "")
        notes = r.get("notes", "")
        md += f"| {i+1} | {name} | {status} | {shot} | {notes} |\n"

    with open(output_path, "w") as f:
        f.write(md)
    return output_path
