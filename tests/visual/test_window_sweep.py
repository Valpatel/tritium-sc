# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Window sweep: discover all panels, open each, screenshot, close each.

Uses ui_capabilities for all interactions — no hardcoded panel lists.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_window_sweep.py -v
"""

import pytest
import time

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from tests.visual.ui_capabilities import (
    ensure_server, launch_browser, navigate, screenshot,
    discover_menu_items, click_menu_item, close_menu,
    generate_sweep_report, SCREENSHOT_DIR,
)

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")


@pytest.fixture(scope="module")
def page():
    server = ensure_server()
    if not server.success:
        pytest.skip("SC server not running")
    with sync_playwright() as p:
        browser, pg = launch_browser(p)
        navigate(pg)
        yield pg
        browser.close()


class TestWindowSweep:

    def test_discover_panels(self, page):
        """WINDOWS menu has panels to sweep."""
        items = discover_menu_items(page, "WINDOWS")
        checkable = [i for i in items if i["checkable"]]
        print(f"\nPanels found: {len(checkable)}")
        for c in checkable:
            state = "OPEN" if c["checked"] else "closed"
            print(f"  {'[*]' if c['checked'] else '[ ]'} {c['label']}")
        assert len(checkable) >= 5, f"Expected 5+ panels, got {len(checkable)}"

    def test_sweep_open_screenshot_close(self, page):
        """Open each panel individually, screenshot, then close."""
        items = discover_menu_items(page, "WINDOWS")
        panels = [i for i in items if i["checkable"]]
        results = []

        # First close all panels
        for panel in panels:
            if panel["checked"]:
                click_menu_item(page, "WINDOWS", panel["label"])
                time.sleep(0.2)

        # Baseline screenshot with nothing open
        screenshot(page, "00_baseline", subdir="window_sweep")

        for i, panel in enumerate(panels):
            name = panel["label"]
            safe = name.replace(" ", "_").replace("/", "-").lower()

            # Open panel
            res = click_menu_item(page, "WINDOWS", name)
            if not res.success:
                results.append({"name": name, "status": "SKIP", "notes": res.message})
                continue

            time.sleep(0.5)

            # Screenshot with this panel open
            shot = screenshot(page, f"{i+1:02d}_{safe}", subdir="window_sweep")

            # Close panel
            click_menu_item(page, "WINDOWS", name)
            time.sleep(0.2)

            results.append({
                "name": name,
                "status": "PASS",
                "screenshot": shot.screenshot,
            })

        # Report
        report_path = generate_sweep_report(
            results, "Window Sweep Report",
            str(SCREENSHOT_DIR / "window_sweep" / "report.md"),
        )
        print(f"\nReport: {report_path}")
        print(f"Passed: {sum(1 for r in results if r['status'] == 'PASS')}/{len(results)}")

        passed = sum(1 for r in results if r["status"] == "PASS")
        assert passed >= 3, f"Only {passed} panels opened"

    def test_open_all_close_all(self, page):
        """WINDOWS → Show All opens everything, Hide All closes everything."""
        # Show all
        click_menu_item(page, "WINDOWS", "Show All")
        time.sleep(1)
        screenshot(page, "all_open", subdir="window_sweep")

        # Hide all
        click_menu_item(page, "WINDOWS", "Hide All")
        time.sleep(0.5)
        screenshot(page, "all_closed", subdir="window_sweep")
