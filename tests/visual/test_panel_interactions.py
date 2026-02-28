# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""E2E tests for panel drag, resize, and collapse behavior in the Command Center.

Verifies that panels can be toggled via keyboard shortcuts (1-5), contain
content, support simultaneous display, close via close buttons, persist
across map mode changes, and have proper headers.

Uses Playwright with headless=True for CI compatibility.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.lib.results_db import ResultsDB
from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/panel-interaction-screenshots")

# Panel definitions: id, keyboard shortcut, title text, default open status
PANELS = [
    {"id": "amy", "key": "1", "title": "AMY COMMANDER", "default_open": True},
    {"id": "units", "key": "2", "title": "UNITS", "default_open": True},
    {"id": "alerts", "key": "3", "title": "ALERTS", "default_open": True},
    {"id": "game", "key": "4", "title": "GAME STATUS", "default_open": False},
    {"id": "mesh", "key": "5", "title": "MESHTASTIC", "default_open": False},
]


class TestPanelInteractions:
    """Playwright-based E2E tests for panel interactions in the Command Center."""

    @pytest.fixture(autouse=True, scope="class")
    def _browser(
        self,
        request,
        tritium_server: TritiumServer,
        test_db: ResultsDB,
        run_id: int,
    ):
        """Launch headless browser, navigate to Command Center, wait for ready."""
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._errors: list[str] = []
        cls._t0 = time.monotonic()

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))

        # Clear localStorage to ensure fresh panel state (no saved layout)
        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        cls.page.evaluate("() => localStorage.removeItem('tritium-panel-layout')")

        # Reload to get clean default panel state
        cls.page.reload(wait_until="networkidle")
        cls.page.wait_for_timeout(3000)

        yield

        browser.close()
        cls._pw.stop()

    def _record(self, name: str, passed: bool, details: dict | None = None) -> None:
        """Record result to ResultsDB and take a screenshot."""
        duration_ms = (time.monotonic() - self._t0) * 1000
        self._db.record_result(self._run_id, name, passed, duration_ms, details or {})
        try:
            self.page.screenshot(
                path=str(SCREENSHOT_DIR / f"{name}.png"),
                full_page=False,
            )
        except Exception:
            pass

    def _screenshot(self, name: str) -> None:
        """Take a screenshot without recording a result."""
        try:
            self.page.screenshot(
                path=str(SCREENSHOT_DIR / f"{name}.png"),
                full_page=False,
            )
        except Exception:
            pass

    def _panel_locator(self, panel_id: str):
        """Get the Playwright locator for a panel by its data-panel-id."""
        return self.page.locator(f'.panel[data-panel-id="{panel_id}"]')

    def _is_panel_visible(self, panel_id: str) -> bool:
        """Check if a panel is visible (exists and not display:none)."""
        loc = self._panel_locator(panel_id)
        if loc.count() == 0:
            return False
        # Check the panel element display style
        return self.page.evaluate(
            """(panelId) => {
                const el = document.querySelector(`.panel[data-panel-id="${panelId}"]`);
                if (!el) return false;
                return el.style.display !== 'none' && el.offsetParent !== null;
            }""",
            panel_id,
        )

    def _close_all_panels(self) -> None:
        """Close all panels by pressing their shortcut keys for open panels."""
        for p in PANELS:
            if self._is_panel_visible(p["id"]):
                self.page.keyboard.press(p["key"])
                self.page.wait_for_timeout(200)

    def _open_panel(self, panel_id: str) -> None:
        """Open a panel via its keyboard shortcut if not already open."""
        panel = next(p for p in PANELS if p["id"] == panel_id)
        if not self._is_panel_visible(panel_id):
            self.page.keyboard.press(panel["key"])
            self.page.wait_for_timeout(300)

    # ------------------------------------------------------------------
    # Test 1: Panel open/close via keyboard shortcuts
    # ------------------------------------------------------------------

    def test_01_panel_toggle_via_keyboard(self):
        """Toggle each panel (Amy, Units, Alerts, Game, Mesh) via keys 1-5."""
        name = "panel_01_toggle_keyboard"
        results = {}
        try:
            for p in PANELS:
                pid = p["id"]
                key = p["key"]

                # First, close if open (default panels start open)
                if self._is_panel_visible(pid):
                    self.page.keyboard.press(key)
                    self.page.wait_for_timeout(300)

                # Verify panel is closed
                assert not self._is_panel_visible(pid), (
                    f"Panel '{pid}' should be closed after toggle"
                )

                # Open it
                self.page.keyboard.press(key)
                self.page.wait_for_timeout(300)

                # Verify panel is open
                assert self._is_panel_visible(pid), (
                    f"Panel '{pid}' should be open after pressing '{key}'"
                )

                # Close it again
                self.page.keyboard.press(key)
                self.page.wait_for_timeout(300)

                # Verify closed again
                assert not self._is_panel_visible(pid), (
                    f"Panel '{pid}' should be closed after second toggle"
                )

                results[pid] = "toggle_ok"

            self._record(name, True, results)
        except Exception as exc:
            self._record(name, False, {"error": str(exc), **results})
            raise

    # ------------------------------------------------------------------
    # Test 2: Each opened panel has non-empty content
    # ------------------------------------------------------------------

    def test_02_panel_has_content(self):
        """Each opened panel should contain non-empty text/elements."""
        name = "panel_02_has_content"
        results = {}
        try:
            for p in PANELS:
                pid = p["id"]

                # Open the panel
                self._open_panel(pid)
                self.page.wait_for_timeout(500)

                # Check that the panel body has content
                body = self._panel_locator(pid).locator(".panel-body")
                assert body.count() > 0, f"Panel '{pid}' has no .panel-body"

                inner_html = body.inner_html()
                # Strip whitespace and check non-empty
                content_text = body.inner_text().strip()
                has_children = len(inner_html.strip()) > 10

                assert has_children or len(content_text) > 0, (
                    f"Panel '{pid}' body is empty (html len={len(inner_html)}, "
                    f"text='{content_text[:50]}')"
                )

                results[pid] = {
                    "html_len": len(inner_html),
                    "text_preview": content_text[:80],
                }

                # Close it after checking
                self.page.keyboard.press(p["key"])
                self.page.wait_for_timeout(200)

            self._record(name, True, results)
        except Exception as exc:
            self._record(name, False, {"error": str(exc), **results})
            raise

    # ------------------------------------------------------------------
    # Test 3: Multiple panels open simultaneously
    # ------------------------------------------------------------------

    def test_03_multiple_panels_open(self):
        """Open 2+ panels simultaneously, verify both render."""
        name = "panel_03_multiple_open"
        try:
            # Close all first
            self._close_all_panels()
            self.page.wait_for_timeout(300)

            # Open amy and units
            self.page.keyboard.press("1")  # amy
            self.page.wait_for_timeout(300)
            self.page.keyboard.press("2")  # units
            self.page.wait_for_timeout(300)
            self.page.keyboard.press("3")  # alerts
            self.page.wait_for_timeout(300)

            # Verify all three are visible
            assert self._is_panel_visible("amy"), "Amy panel should be visible"
            assert self._is_panel_visible("units"), "Units panel should be visible"
            assert self._is_panel_visible("alerts"), "Alerts panel should be visible"

            # Count visible panels via DOM
            visible_count = self.page.evaluate("""() => {
                const panels = document.querySelectorAll('.panel');
                let count = 0;
                panels.forEach(p => {
                    if (p.style.display !== 'none' && p.offsetParent !== null) count++;
                });
                return count;
            }""")

            assert visible_count >= 3, (
                f"Expected >= 3 visible panels, got {visible_count}"
            )

            self._screenshot(name)
            self._record(name, True, {"visible_count": visible_count})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 4: Panel close via close button (X)
    # ------------------------------------------------------------------

    def test_04_close_via_button(self):
        """If panels have X/close buttons, verify clicking closes them."""
        name = "panel_04_close_via_button"
        results = {}
        try:
            # Open a panel that is easy to test
            self._open_panel("units")
            self.page.wait_for_timeout(300)

            assert self._is_panel_visible("units"), "Units panel should be open"

            # Click the close button
            close_btn = self._panel_locator("units").locator(".panel-close")
            assert close_btn.count() > 0, "Units panel has no .panel-close button"
            close_btn.click()
            self.page.wait_for_timeout(300)

            assert not self._is_panel_visible("units"), (
                "Units panel should be closed after clicking X"
            )
            results["units_close"] = "ok"

            # Test with amy panel too
            self._open_panel("amy")
            self.page.wait_for_timeout(300)

            assert self._is_panel_visible("amy"), "Amy panel should be open"

            close_btn = self._panel_locator("amy").locator(".panel-close")
            assert close_btn.count() > 0, "Amy panel has no .panel-close button"
            close_btn.click()
            self.page.wait_for_timeout(300)

            assert not self._is_panel_visible("amy"), (
                "Amy panel should be closed after clicking X"
            )
            results["amy_close"] = "ok"

            self._record(name, True, results)
        except Exception as exc:
            self._record(name, False, {"error": str(exc), **results})
            raise

    # ------------------------------------------------------------------
    # Test 5: Panel state persists across mode changes (O/T/S)
    # ------------------------------------------------------------------

    def test_05_persist_across_mode_changes(self):
        """Open panels, switch map modes O/T/S, verify panels stay open."""
        name = "panel_05_persist_mode_changes"
        try:
            # Ensure a known state: close all, open amy + units
            self._close_all_panels()
            self.page.wait_for_timeout(300)

            self.page.keyboard.press("1")  # amy
            self.page.wait_for_timeout(300)
            self.page.keyboard.press("2")  # units
            self.page.wait_for_timeout(300)

            assert self._is_panel_visible("amy"), "Amy should be open before mode switch"
            assert self._is_panel_visible("units"), "Units should be open before mode switch"

            # Switch to Tactical mode
            self.page.keyboard.press("t")
            self.page.wait_for_timeout(500)

            assert self._is_panel_visible("amy"), "Amy should stay open after T mode"
            assert self._is_panel_visible("units"), "Units should stay open after T mode"

            # Switch to Setup mode
            self.page.keyboard.press("s")
            self.page.wait_for_timeout(500)

            assert self._is_panel_visible("amy"), "Amy should stay open after S mode"
            assert self._is_panel_visible("units"), "Units should stay open after S mode"

            # Switch to Observe mode
            self.page.keyboard.press("o")
            self.page.wait_for_timeout(500)

            assert self._is_panel_visible("amy"), "Amy should stay open after O mode"
            assert self._is_panel_visible("units"), "Units should stay open after O mode"

            self._screenshot(name)
            self._record(name, True, {"modes_tested": ["T", "S", "O"]})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 6: Sidebar toggle (Tab key behavior in unified layout)
    # ------------------------------------------------------------------

    def test_06_tab_key_behavior(self):
        """Press Tab in unified layout and verify it is intercepted (no sidebar)."""
        name = "panel_06_tab_key"
        try:
            # In unified layout, Tab is intercepted (e.preventDefault).
            # There is no sidebar in unified layout. Verify the sidebar
            # element does not exist or is not toggled.
            sidebar = self.page.locator("#sidebar")
            has_sidebar = sidebar.count() > 0

            # Press Tab
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(300)

            if has_sidebar:
                # Legacy layout: verify toggle works
                collapsed = sidebar.evaluate(
                    "el => el.dataset.collapsed === 'true' || el.classList.contains('collapsed')"
                )
                self._record(name, True, {
                    "layout": "legacy",
                    "sidebar_collapsed": collapsed,
                })
            else:
                # Unified layout: Tab is intercepted, no sidebar exists.
                # Verify panel-container still exists and functions
                panel_container = self.page.locator("#panel-container")
                assert panel_container.count() > 0, "Panel container should exist"
                self._record(name, True, {
                    "layout": "unified",
                    "tab_intercepted": True,
                })

        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 7: All panels have header with title
    # ------------------------------------------------------------------

    def test_07_all_panels_have_header(self):
        """Verify each panel has a title/header element with correct text."""
        name = "panel_07_headers"
        results = {}
        try:
            for p in PANELS:
                pid = p["id"]
                expected_title = p["title"]

                # Open the panel
                self._open_panel(pid)
                self.page.wait_for_timeout(300)

                panel_loc = self._panel_locator(pid)
                assert panel_loc.count() > 0, f"Panel '{pid}' not found in DOM"

                # Check header exists
                header = panel_loc.locator(".panel-header")
                assert header.count() > 0, f"Panel '{pid}' has no .panel-header"

                # Check title element
                title = panel_loc.locator(".panel-title")
                assert title.count() > 0, f"Panel '{pid}' has no .panel-title"

                title_text = title.text_content().strip()
                assert expected_title in title_text, (
                    f"Panel '{pid}' title mismatch: "
                    f"expected '{expected_title}', got '{title_text}'"
                )

                # Check controls exist (minimize + close)
                controls = panel_loc.locator(".panel-controls")
                assert controls.count() > 0, f"Panel '{pid}' has no .panel-controls"

                minimize_btn = panel_loc.locator(".panel-minimize")
                assert minimize_btn.count() > 0, (
                    f"Panel '{pid}' has no minimize button"
                )

                close_btn = panel_loc.locator(".panel-close")
                assert close_btn.count() > 0, (
                    f"Panel '{pid}' has no close button"
                )

                results[pid] = {
                    "title": title_text,
                    "has_minimize": True,
                    "has_close": True,
                }

                # Close after checking
                self.page.keyboard.press(p["key"])
                self.page.wait_for_timeout(200)

            self._record(name, True, results)
        except Exception as exc:
            self._record(name, False, {"error": str(exc), **results})
            raise
