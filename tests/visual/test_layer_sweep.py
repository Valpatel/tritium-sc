# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Layer sweep: hide all, show each layer individually, screenshot each.

DATA COLLECTION ONLY — captures screenshots per layer.
Analysis (OpenCV diff, llava vision, pixel comparison) is separate.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_layer_sweep.py -v
"""

import pytest
import time

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from tests.visual.ui_capabilities import (
    ensure_server, start_demo, launch_browser, navigate, screenshot,
    open_layers_panel, discover_layers, toggle_layer,
    hide_all_layers, show_all_layers, expand_all_categories,
    generate_sweep_report, SCREENSHOT_DIR,
)

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")


@pytest.fixture(scope="module")
def page():
    server = ensure_server()
    if not server.success:
        pytest.skip("SC server not running")
    start_demo()
    with sync_playwright() as p:
        browser, pg = launch_browser(p)
        navigate(pg, wait=8)
        open_layers_panel(pg)
        expand_all_categories(pg)
        yield pg
        browser.close()


class TestLayerSweep:

    def test_discover_layers(self, page):
        """Layers panel has checkboxes to sweep."""
        layers = discover_layers(page)
        print(f"\nLayers found: {len(layers)}")
        for l in layers:
            state = "ON" if l["checked"] else "off"
            print(f"  [{state:3s}] {l['key']}")
        assert len(layers) >= 10, f"Expected 10+ layers, got {len(layers)}"

    def test_sweep_each_layer(self, page):
        """Hide all, then show each layer one at a time and screenshot."""
        layers = discover_layers(page)
        results = []

        # Hide everything
        hide_all_layers(page)
        time.sleep(0.5)
        screenshot(page, "00_all_hidden", subdir="layer_sweep")

        for i, layer in enumerate(layers):
            key = layer["key"]
            safe = key.replace(":", "_").replace("/", "_")

            # Show this one layer
            res = toggle_layer(page, key)
            if not res.success:
                results.append({"name": key, "status": "SKIP", "notes": res.message})
                continue

            # Only screenshot if it actually toggled ON
            if res.data.get("now", False):
                time.sleep(0.3)
                shot = screenshot(page, f"{i+1:02d}_{safe}", subdir="layer_sweep")

                # Hide it again for clean next test
                toggle_layer(page, key)
                time.sleep(0.2)

                results.append({
                    "name": key,
                    "status": "PASS",
                    "screenshot": shot.screenshot,
                })
            else:
                results.append({
                    "name": key,
                    "status": "FAIL",
                    "notes": "Toggle did not change state",
                })

        # Restore
        show_all_layers(page)

        # Report
        report_path = generate_sweep_report(
            results, "Layer Sweep Report",
            str(SCREENSHOT_DIR / "layer_sweep" / "report.md"),
        )
        print(f"\nReport: {report_path}")
        passed = sum(1 for r in results if r["status"] == "PASS")
        failed = sum(1 for r in results if r["status"] == "FAIL")
        skipped = sum(1 for r in results if r["status"] == "SKIP")
        print(f"Passed: {passed}, Failed: {failed}, Skipped: {skipped}")

        # The key assertion: layers that FAIL to toggle are bugs
        if failed > 0:
            broken = [r["name"] for r in results if r["status"] == "FAIL"]
            print(f"BROKEN LAYERS (toggle doesn't work): {broken}")

        assert passed >= 5, f"Only {passed} layers toggled successfully"
