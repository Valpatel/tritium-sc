"""Shared Playwright fixtures for UI layout and UX tests.

Provides session-scoped server, browser, page, BoundingBoxValidator,
screenshot helpers, and interaction utilities for UX tests.
Uses playwright.sync_api to match existing test patterns.
"""

from __future__ import annotations

import os

import pytest

from tests.lib.server_manager import TritiumServer
from tests.lib.layout_validator import BoundingBoxValidator

SCREENSHOT_DIR = os.path.join(
    os.path.dirname(__file__), '..', '.test-results', 'screenshots'
)


@pytest.fixture(scope="session", autouse=True)
def screenshot_dir():
    """Ensure screenshot output directory exists."""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


@pytest.fixture(scope="session")
def tritium_server():
    """Session-scoped auto-port server."""
    server = TritiumServer(auto_port=True)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def browser(tritium_server):
    """Session-scoped headless Chromium browser."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def page(browser, tritium_server):
    """Fresh page at 1920x1080, navigated to Command Center with data loaded."""
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    p = ctx.new_page()
    p.goto(f"{tritium_server.url}/", wait_until="domcontentloaded",
           timeout=60000)
    # Wait for store to initialize and have units (simulation data)
    try:
        p.wait_for_function(
            "() => window.TritiumStore && window.TritiumStore.units.size >= 3",
            timeout=15000,
        )
    except Exception:
        pass  # Tests will detect missing data themselves
    p.wait_for_timeout(1000)
    yield p
    ctx.close()


@pytest.fixture
def validator(page):
    """BoundingBoxValidator wrapping the current page."""
    return BoundingBoxValidator(page)


@pytest.fixture
def take_screenshot():
    """Returns a callable that takes a screenshot and saves it."""
    def _take(page, name):
        path = os.path.join(SCREENSHOT_DIR, f'{name}.png')
        page.screenshot(path=path)
        return path
    return _take


# ---------------------------------------------------------------------------
# Interaction helpers (module-level functions, importable by tests)
# ---------------------------------------------------------------------------

def click_menu_item(page, menu_label, item_label):
    """Click a menu trigger by label, then click a menu item by label.

    Args:
        page: Playwright page
        menu_label: Text of the menu trigger (e.g. "FILE", "VIEW")
        item_label: Text of the menu item label (e.g. "Save Layout...")
    """
    # Close any open dropdown first by pressing Escape
    page.keyboard.press('Escape')
    page.wait_for_timeout(200)

    # Click the menu trigger to open the dropdown
    trigger = page.locator('.menu-trigger').filter(has_text=menu_label).first
    trigger.click()
    page.wait_for_timeout(400)

    # Find the menu item label within the sibling dropdown
    wrap = trigger.locator('..')
    dropdown = wrap.locator('.menu-dropdown')
    # Use evaluate to click the correct item via JS for reliability
    page.evaluate(
        """([dropdownSel, label]) => {
            const items = document.querySelectorAll('.menu-dropdown:not([hidden]) .menu-item');
            for (const item of items) {
                const lbl = item.querySelector('.menu-item-label');
                if (lbl && lbl.textContent.trim() === label) {
                    item.click();
                    return;
                }
            }
        }""",
        ['.menu-dropdown', item_label]
    )
    page.wait_for_timeout(400)


def assert_panel_visible(page, panel_id):
    """Assert that a panel with the given data-panel-id is visible."""
    panel = page.locator(f'[data-panel-id="{panel_id}"]')
    assert panel.count() > 0, f"Panel '{panel_id}' not found in DOM"
    assert panel.is_visible(), f"Panel '{panel_id}' exists but is not visible"


def assert_panel_hidden(page, panel_id):
    """Assert that a panel with the given data-panel-id is NOT visible."""
    panel = page.locator(f'[data-panel-id="{panel_id}"]')
    if panel.count() == 0:
        return  # Not in DOM = hidden
    assert not panel.is_visible(), f"Panel '{panel_id}' is visible but should be hidden"


def wait_for_panel(page, panel_id, timeout=5000):
    """Wait for a panel element to appear and be visible."""
    page.locator(f'[data-panel-id="{panel_id}"]').wait_for(
        state="visible", timeout=timeout
    )
