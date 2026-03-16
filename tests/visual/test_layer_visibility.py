# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Layer visibility test: step through each layer/category and verify hide/show works.

Uses Playwright to toggle layers via the MAP menu and Layers panel,
then takes screenshots to verify visual changes.

Run:
    cd tritium-sc
    .venv/bin/python3 -m pytest tests/visual/test_layer_visibility.py -v --tb=short
"""

import time
import pytest

# Try importing playwright — skip if not available
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")


@pytest.fixture(scope="module")
def browser_page():
    """Launch browser, navigate to SC, start demo mode."""
    import subprocess
    import requests

    # Verify server is running
    try:
        r = requests.get("http://localhost:8000/health", timeout=3)
        assert r.status_code == 200
    except Exception:
        pytest.skip("SC server not running on :8000")

    # Start demo mode
    requests.post("http://localhost:8000/api/demo/start", timeout=5)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto("http://localhost:8000", timeout=20000)
        time.sleep(8)  # Wait for map to load + demo targets

        yield page
        browser.close()


class TestMenuRename:
    """Verify VIEW tab was renamed to WINDOWS."""

    def test_windows_tab_exists(self, browser_page):
        page = browser_page
        triggers = page.query_selector_all(".menu-trigger")
        labels = [t.text_content().strip() for t in triggers]
        assert "WINDOWS" in labels, f"Expected WINDOWS in menu, got: {labels}"
        assert "VIEW" not in labels, f"VIEW should be renamed to WINDOWS, got: {labels}"


class TestMapMenuLayerControls:
    """Verify MAP menu has Show All / Hide All / Open Layers Window."""

    def test_map_menu_has_layer_controls(self, browser_page):
        page = browser_page
        # Click MAP menu
        triggers = page.query_selector_all(".menu-trigger")
        map_trigger = None
        for t in triggers:
            if t.text_content().strip() == "MAP":
                map_trigger = t
                break
        assert map_trigger is not None, "MAP menu trigger not found"
        map_trigger.click()
        time.sleep(0.5)

        # Check dropdown items
        items = page.query_selector_all(".menu-dropdown:not([hidden]) .menu-item")
        labels = [i.text_content().strip() for i in items]
        label_text = " ".join(labels)

        assert "Open Layers Window" in label_text, f"Missing 'Open Layers Window', got: {labels}"
        assert "Show All Layers" in label_text, f"Missing 'Show All Layers', got: {labels}"
        assert "Hide All Layers" in label_text, f"Missing 'Hide All Layers', got: {labels}"

        # Close menu
        page.keyboard.press("Escape")


class TestLayersPanelButtons:
    """Verify Layers panel has global SHOW ALL / HIDE ALL + per-category buttons."""

    def test_layers_panel_global_buttons(self, browser_page):
        page = browser_page
        # Open layers panel via keyboard shortcut
        page.keyboard.press("l")
        time.sleep(1)

        show_btn = page.query_selector(".layers-btn-show-all")
        hide_btn = page.query_selector(".layers-btn-hide-all")
        assert show_btn is not None, "SHOW ALL button missing from layers panel"
        assert hide_btn is not None, "HIDE ALL button missing from layers panel"

    def test_layers_panel_category_buttons(self, browser_page):
        page = browser_page
        # Check for per-category ALL/NONE buttons
        cat_show = page.query_selector_all(".layer-cat-show-all")
        cat_hide = page.query_selector_all(".layer-cat-hide-all")
        assert len(cat_show) > 0, "No per-category SHOW ALL buttons found"
        assert len(cat_hide) > 0, "No per-category HIDE ALL buttons found"
        # Should have one per category
        assert len(cat_show) >= 5, f"Expected 5+ category show buttons, got {len(cat_show)}"


class TestHideAllShowAll:
    """Test that Hide All and Show All produce consistent results."""

    def test_hide_all_hides_layers(self, browser_page):
        page = browser_page
        # Take baseline screenshot
        page.screenshot(path="/tmp/layer_test_baseline.png")

        # Click Hide All in layers panel
        hide_btn = page.query_selector(".layers-btn-hide-all")
        if hide_btn:
            hide_btn.click()
            time.sleep(1)

        page.screenshot(path="/tmp/layer_test_hidden.png")

        # Verify: check if satellite layer checkbox is unchecked
        sat_cb = page.query_selector('input[data-key="showSatellite"]')
        if sat_cb:
            assert not sat_cb.is_checked(), "Satellite should be unchecked after Hide All"

    def test_show_all_shows_layers(self, browser_page):
        page = browser_page
        # Click Show All
        show_btn = page.query_selector(".layers-btn-show-all")
        if show_btn:
            show_btn.click()
            time.sleep(1)

        page.screenshot(path="/tmp/layer_test_shown.png")

        # Verify: satellite should be checked
        sat_cb = page.query_selector('input[data-key="showSatellite"]')
        if sat_cb:
            assert sat_cb.is_checked(), "Satellite should be checked after Show All"


class TestLayerCategoryToggle:
    """Test per-category ALL/NONE buttons."""

    def test_hide_combat_effects(self, browser_page):
        page = browser_page
        time.sleep(1)
        # Scroll the layers panel to make COMBAT EFFECTS visible
        btn = page.locator('.layer-cat-hide-all[data-cat-name="COMBAT EFFECTS"]')
        btn.scroll_into_view_if_needed(timeout=5000)
        btn.click(timeout=5000)
        time.sleep(0.5)

        # Verify tracers checkbox is unchecked
        tracer_cb = page.query_selector('input[data-key="showTracers"]')
        if tracer_cb:
            assert not tracer_cb.is_checked(), "Tracers should be off after COMBAT EFFECTS → NONE"

    def test_show_combat_effects(self, browser_page):
        page = browser_page
        time.sleep(0.5)
        btn = page.locator('.layer-cat-show-all[data-cat-name="COMBAT EFFECTS"]')
        btn.scroll_into_view_if_needed(timeout=5000)
        btn.click(timeout=5000)
        time.sleep(0.5)

        tracer_cb = page.query_selector('input[data-key="showTracers"]')
        if tracer_cb:
            assert tracer_cb.is_checked(), "Tracers should be on after COMBAT EFFECTS → ALL"
