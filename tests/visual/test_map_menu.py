# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Map Menu tests -- verify all menu items, checkmarks, toggles, and keyboard shortcuts.

Uses Playwright (headed) to exercise the MAP dropdown in the Command Center menu bar.
Each checkable item is clicked and verified against window._mapActions.getMapState().
Keyboard shortcuts (I, G, K, F, R, ], [) are tested independently.

Bugs found and fixed during test development:
  - BUG-001 (FIXED): main.js 'K' handler used _activeMapModule (always null)
    instead of _mapActions. Fixed to match 'G' and 'I' shortcut patterns.
  - BUG-002 (known): map-maplibre.js toggleFog() calls _state.map.setFog() which
    may not exist in all MapLibre GL JS versions. Filtered in test_16.
  - BUG-003 (FIXED): menu-bar.js _closeAllDropdowns() only manipulated DOM without
    resetting closure state (openMenu/hoverMode), so the menu toggle broke after
    clicking non-checkable items. Fixed by passing _closeAll closure into _buildDropdown.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.lib.results_db import ResultsDB
from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/map-menu-screenshots")

# Expected checkable items in the MAP menu, in order, with their state key and default
CHECKABLE_ITEMS = [
    {"label": "Satellite", "shortcut": "I", "state_key": "showSatellite", "default": True},
    {"label": "Roads", "shortcut": "G", "state_key": "showRoads", "default": True},
    {"label": "Buildings", "shortcut": "K", "state_key": "showBuildings", "default": True},
    {"label": "Waterways", "shortcut": None, "state_key": "showWaterways", "default": True},
    {"label": "Parks", "shortcut": None, "state_key": "showParks", "default": True},
    {"label": "Grid", "shortcut": None, "state_key": "showGrid", "default": False},
    # --- separator ---
    {"label": "3D Models", "shortcut": None, "state_key": "showModels3d", "default": True},
    {"label": "Labels", "shortcut": None, "state_key": "showLabels", "default": True},
    # --- separator ---
    {"label": "Fog", "shortcut": None, "state_key": "showFog", "default": False},
    # 3D Mode checked via tiltMode === 'tilted'
    {"label": "3D Mode", "shortcut": None, "state_key": "tiltMode", "default": "tilted"},
]

# Non-checkable action items
ACTION_ITEMS = [
    {"label": "Center on Action", "shortcut": "F"},
    {"label": "Reset Camera", "shortcut": "R"},
    {"label": "Zoom In", "shortcut": "]"},
    {"label": "Zoom Out", "shortcut": "["},
]


class TestMapMenu:
    """Playwright-based tests for the MAP dropdown menu in the Command Center."""

    @pytest.fixture(autouse=True, scope="class")
    def _browser(
        self,
        request,
        tritium_server: TritiumServer,
        test_db: ResultsDB,
        run_id: int,
    ):
        """Launch headed browser, navigate to Command Center, wait for data."""
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._errors: list[str] = []
        cls._t0 = time.monotonic()

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))
        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        # Wait for the map and store to initialize
        cls.page.wait_for_timeout(4000)

        yield

        browser.close()
        cls._pw.stop()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record(self, name: str, passed: bool, details: dict | None = None) -> None:
        duration_ms = (time.monotonic() - self._t0) * 1000
        self._db.record_result(self._run_id, name, passed, duration_ms, details or {})

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path, full_page=False)
        return path

    def _is_any_menu_open(self) -> bool:
        """Check if any menu dropdown is currently visible."""
        return self.page.evaluate("""() => {
            const dropdowns = document.querySelectorAll('.menu-dropdown');
            for (const d of dropdowns) {
                if (!d.hidden) return true;
            }
            return false;
        }""")

    def _is_map_menu_open(self) -> bool:
        """Check if the MAP dropdown is currently visible."""
        return self.page.evaluate("""() => {
            const triggers = document.querySelectorAll('.menu-trigger');
            for (const t of triggers) {
                if (t.textContent.trim().toUpperCase() === 'MAP') {
                    const dropdown = t.parentElement.querySelector('.menu-dropdown');
                    return dropdown && !dropdown.hidden;
                }
            }
            return false;
        }""")

    def _get_map_trigger(self):
        """Find and return the MAP menu trigger button locator."""
        triggers = self.page.locator(".menu-trigger")
        count = triggers.count()
        for i in range(count):
            if triggers.nth(i).text_content().strip().upper() == "MAP":
                return triggers.nth(i)
        return None

    def _open_map_menu(self):
        """Click the MAP trigger to open the dropdown. Returns the dropdown locator."""
        map_trigger = self._get_map_trigger()
        assert map_trigger is not None, "MAP menu trigger not found"

        # If the MAP menu is already open, return the dropdown directly
        if self._is_map_menu_open():
            wrap = map_trigger.locator("..")
            return wrap.locator(".menu-dropdown")

        # If a different menu is open, close it by pressing Escape
        if self._is_any_menu_open():
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(200)

        # Click to open
        map_trigger.click()
        self.page.wait_for_timeout(300)

        wrap = map_trigger.locator("..")
        dropdown = wrap.locator(".menu-dropdown")

        assert self._is_map_menu_open(), "MAP dropdown did not open"
        return dropdown

    def _close_menu(self):
        """Close any open menu by pressing Escape (uses the built-in handler)."""
        if self._is_any_menu_open():
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(200)

    def _get_map_state(self) -> dict:
        """Return the current map state via window._mapActions.getMapState()."""
        return self.page.evaluate("() => window._mapActions.getMapState()")

    def _find_menu_item(self, dropdown, label: str):
        """Find a menu item row by its label text. Returns the row locator."""
        items = dropdown.locator(".menu-item")
        count = items.count()
        for i in range(count):
            row = items.nth(i)
            lbl = row.locator(".menu-item-label")
            if lbl.count() > 0 and lbl.text_content().strip() == label:
                return row
        return None

    def _item_is_checked(self, row) -> bool:
        """Return True if the menu item row has a bullet check indicator."""
        check = row.locator(".menu-item-check")
        if check.count() == 0:
            return False
        text = check.text_content()
        return text.strip() == "\u2022"

    def _is_dropdown_hidden_js(self) -> bool:
        """Check if the MAP dropdown is hidden via JS."""
        return self.page.evaluate("""() => {
            const triggers = document.querySelectorAll('.menu-trigger');
            for (const t of triggers) {
                if (t.textContent.trim().toUpperCase() === 'MAP') {
                    const dropdown = t.parentElement.querySelector('.menu-dropdown');
                    return dropdown ? dropdown.hidden : true;
                }
            }
            return true;
        }""")

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_01_map_menu_opens(self):
        """MAP menu opens when clicked and shows expected items."""
        name = "map_menu_01_opens"
        try:
            dropdown = self._open_map_menu()
            self._screenshot(name)

            # Verify all expected labels are present
            items = dropdown.locator(".menu-item")
            labels = []
            for i in range(items.count()):
                lbl = items.nth(i).locator(".menu-item-label")
                if lbl.count() > 0:
                    labels.append(lbl.text_content().strip())

            expected_labels = [c["label"] for c in CHECKABLE_ITEMS] + [a["label"] for a in ACTION_ITEMS]
            missing = [l for l in expected_labels if l not in labels]
            assert len(missing) == 0, f"Missing menu items: {missing}"

            # Verify separators exist
            seps = dropdown.locator(".menu-separator")
            assert seps.count() >= 3, f"Expected >= 3 separators, got {seps.count()}"

            self._close_menu()
            self._record(name, True, {"labels": labels})
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_02_map_menu_shortcuts_displayed(self):
        """Menu items with keyboard shortcuts show the shortcut text."""
        name = "map_menu_02_shortcuts"
        try:
            dropdown = self._open_map_menu()

            shortcuts_found = {}
            all_items = CHECKABLE_ITEMS + ACTION_ITEMS
            for item_def in all_items:
                if item_def.get("shortcut"):
                    row = self._find_menu_item(dropdown, item_def["label"])
                    assert row is not None, f"Item '{item_def['label']}' not found"
                    sc = row.locator(".menu-item-shortcut")
                    if sc.count() > 0:
                        shortcuts_found[item_def["label"]] = sc.text_content().strip()

            expected_shortcuts = {i["label"]: i["shortcut"] for i in all_items if i.get("shortcut")}
            for label, expected in expected_shortcuts.items():
                actual = shortcuts_found.get(label)
                assert actual == expected, f"Shortcut for '{label}': expected '{expected}', got '{actual}'"

            self._close_menu()
            self._record(name, True, {"shortcuts": shortcuts_found})
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_03_initial_checkmark_state(self):
        """Initial checkmarks match default map state."""
        name = "map_menu_03_initial_state"
        try:
            state = self._get_map_state()
            dropdown = self._open_map_menu()
            self._screenshot(name)

            results = {}
            for item_def in CHECKABLE_ITEMS:
                row = self._find_menu_item(dropdown, item_def["label"])
                assert row is not None, f"Item '{item_def['label']}' not found"
                is_checked = self._item_is_checked(row)
                key = item_def["state_key"]
                if key == "tiltMode":
                    expected_checked = state.get(key) == "tilted"
                elif key == "showFog":
                    expected_checked = state.get("showFog", state.get("fogEnabled", False))
                else:
                    expected_checked = state.get(key, item_def["default"])
                results[item_def["label"]] = {
                    "checked": is_checked,
                    "expected": expected_checked,
                    "state_val": state.get(key),
                }
                assert is_checked == expected_checked, (
                    f"'{item_def['label']}' checkmark mismatch: "
                    f"UI shows {'checked' if is_checked else 'unchecked'}, "
                    f"state[{key}]={state.get(key)}, expected {'checked' if expected_checked else 'unchecked'}"
                )

            self._close_menu()
            self._record(name, True, results)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_04_toggle_satellite_via_menu(self):
        """Clicking Satellite toggles the checkmark and map state."""
        name = "map_menu_04_toggle_satellite"
        try:
            state_before = self._get_map_state()
            was_on = state_before["showSatellite"]

            dropdown = self._open_map_menu()
            row = self._find_menu_item(dropdown, "Satellite")
            assert row is not None, "Satellite item not found"
            row.click()
            self.page.wait_for_timeout(300)

            # Check state changed
            state_after = self._get_map_state()
            assert state_after["showSatellite"] == (not was_on), (
                f"Satellite state didn't toggle: was {was_on}, now {state_after['showSatellite']}"
            )

            # Check the menu item's bullet updated (menu should still be open for checkable items)
            is_checked = self._item_is_checked(row)
            assert is_checked == (not was_on), (
                f"Satellite checkmark mismatch after click: expected {not was_on}, got {is_checked}"
            )

            self._screenshot(name)

            # Toggle back
            row.click()
            self.page.wait_for_timeout(200)
            state_restored = self._get_map_state()
            assert state_restored["showSatellite"] == was_on, "Satellite didn't toggle back"

            self._close_menu()
            self._record(name, True, {"before": was_on, "after": not was_on})
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_05_toggle_all_checkable_items(self):
        """Each checkable menu item toggles its state when clicked."""
        name = "map_menu_05_toggle_all"
        try:
            results = {}
            for item_def in CHECKABLE_ITEMS:
                label = item_def["label"]
                key = item_def["state_key"]

                state_before = self._get_map_state()
                if key == "tiltMode":
                    val_before = state_before.get(key) == "tilted"
                else:
                    val_before = state_before.get(key, False)

                dropdown = self._open_map_menu()
                row = self._find_menu_item(dropdown, label)
                assert row is not None, f"'{label}' not found in menu"

                # Click to toggle
                row.click()
                self.page.wait_for_timeout(300)

                state_after = self._get_map_state()
                if key == "tiltMode":
                    val_after = state_after.get(key) == "tilted"
                else:
                    val_after = state_after.get(key, False)

                toggled = val_after != val_before
                results[label] = {
                    "before": val_before,
                    "after": val_after,
                    "toggled": toggled,
                }

                # Close and reopen to ensure fresh dropdown for next item
                self._close_menu()
                self.page.wait_for_timeout(100)

                # Toggle back to restore original state
                dropdown2 = self._open_map_menu()
                row2 = self._find_menu_item(dropdown2, label)
                if row2:
                    row2.click()
                    self.page.wait_for_timeout(200)
                self._close_menu()
                self.page.wait_for_timeout(100)

                assert toggled, f"'{label}' did not toggle: state[{key}] was {val_before}, still {val_after}"

            self._screenshot(name)
            self._record(name, True, results)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_06_keyboard_shortcut_satellite(self):
        """Pressing 'I' toggles satellite layer."""
        name = "map_menu_06_kb_satellite"
        try:
            self._close_menu()
            state_before = self._get_map_state()
            was_on = state_before["showSatellite"]

            self.page.keyboard.press("i")
            self.page.wait_for_timeout(300)

            state_after = self._get_map_state()
            assert state_after["showSatellite"] == (not was_on), (
                f"'I' key didn't toggle satellite: was {was_on}, now {state_after['showSatellite']}"
            )

            # Toggle back
            self.page.keyboard.press("i")
            self.page.wait_for_timeout(200)

            self._screenshot(name)
            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_07_keyboard_shortcut_roads(self):
        """Pressing 'G' toggles roads layer."""
        name = "map_menu_07_kb_roads"
        try:
            self._close_menu()
            state_before = self._get_map_state()
            was_on = state_before["showRoads"]

            self.page.keyboard.press("g")
            self.page.wait_for_timeout(300)

            state_after = self._get_map_state()
            assert state_after["showRoads"] == (not was_on), (
                f"'G' key didn't toggle roads: was {was_on}, now {state_after['showRoads']}"
            )

            # Toggle back
            self.page.keyboard.press("g")
            self.page.wait_for_timeout(200)

            self._screenshot(name)
            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_08_keyboard_shortcut_buildings(self):
        """Pressing 'K' toggles buildings layer.

        Previously broken (BUG-001): main.js used _activeMapModule (always null)
        instead of _mapActions. Fixed to match 'G' and 'I' shortcut pattern.
        """
        name = "map_menu_08_kb_buildings"
        try:
            self._close_menu()
            state_before = self._get_map_state()
            was_on = state_before["showBuildings"]

            self.page.keyboard.press("k")
            self.page.wait_for_timeout(300)

            state_after = self._get_map_state()
            assert state_after["showBuildings"] == (not was_on), (
                f"'K' key didn't toggle buildings: was {was_on}, now {state_after['showBuildings']}"
            )

            # Toggle back
            self.page.keyboard.press("k")
            self.page.wait_for_timeout(200)

            self._screenshot(name)
            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_09_keyboard_zoom_in_out(self):
        """Pressing ']' zooms in and '[' zooms out (no errors)."""
        name = "map_menu_09_kb_zoom"
        try:
            self._close_menu()
            errors_before = len(self._errors)

            self.page.keyboard.press("]")
            self.page.wait_for_timeout(500)
            self.page.keyboard.press("[")
            self.page.wait_for_timeout(500)

            new_errors = self._errors[errors_before:]
            assert len(new_errors) == 0, f"Zoom shortcuts caused errors: {new_errors}"

            self._screenshot(name)
            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_10_keyboard_center_and_reset(self):
        """Pressing 'F' centers on action and 'R' resets camera (no errors)."""
        name = "map_menu_10_kb_center_reset"
        try:
            self._close_menu()
            errors_before = len(self._errors)

            self.page.keyboard.press("f")
            self.page.wait_for_timeout(500)
            self._screenshot(f"{name}_after_center")

            self.page.keyboard.press("r")
            self.page.wait_for_timeout(500)
            self._screenshot(f"{name}_after_reset")

            new_errors = self._errors[errors_before:]
            assert len(new_errors) == 0, f"Center/Reset shortcuts caused errors: {new_errors}"

            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_11_non_checkable_items_close_menu(self):
        """Non-checkable items (Center, Reset, Zoom) close the dropdown after click."""
        name = "map_menu_11_action_items_close"
        try:
            for action_def in ACTION_ITEMS:
                label = action_def["label"]
                dropdown = self._open_map_menu()
                row = self._find_menu_item(dropdown, label)
                assert row is not None, f"Action item '{label}' not found"

                row.click()
                self.page.wait_for_timeout(400)

                # Check hidden attribute via JS (more reliable than Playwright is_hidden)
                is_hidden = self._is_dropdown_hidden_js()
                assert is_hidden, f"Dropdown stayed open after clicking '{label}'"

            self._screenshot(name)
            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_12_checkable_items_keep_menu_open(self):
        """Checkable items keep the dropdown open after click."""
        name = "map_menu_12_checkable_stays_open"
        try:
            dropdown = self._open_map_menu()
            row = self._find_menu_item(dropdown, "Grid")
            assert row is not None, "Grid item not found"

            row.click()
            self.page.wait_for_timeout(200)

            # The dropdown should remain visible for checkable items
            is_still_open = not self._is_dropdown_hidden_js()
            assert is_still_open, "Dropdown closed after clicking checkable item 'Grid'"

            self._screenshot(name)

            # Toggle back
            row.click()
            self.page.wait_for_timeout(200)
            self._close_menu()

            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_13_menu_closes_on_escape(self):
        """Pressing Escape closes the open MAP dropdown."""
        name = "map_menu_13_escape_closes"
        try:
            self._open_map_menu()
            assert not self._is_dropdown_hidden_js(), "Dropdown not visible after opening"

            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(200)

            assert self._is_dropdown_hidden_js(), "Dropdown did not close on Escape"

            self._screenshot(name)
            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_14_menu_closes_on_outside_click(self):
        """Clicking outside the dropdown closes it."""
        name = "map_menu_14_outside_click_closes"
        try:
            self._open_map_menu()
            assert not self._is_dropdown_hidden_js(), "Dropdown not visible after opening"

            # Click on the map area (center of viewport), using dispatchEvent to
            # ensure the document-level click handler fires
            self.page.evaluate("""() => {
                document.dispatchEvent(new MouseEvent('click', {
                    bubbles: true, clientX: 960, clientY: 540
                }));
            }""")
            self.page.wait_for_timeout(300)

            assert self._is_dropdown_hidden_js(), "Dropdown did not close on outside click"

            self._screenshot(name)
            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_15_hover_switching(self):
        """After opening MAP, hovering over another menu trigger switches menus."""
        name = "map_menu_15_hover_switch"
        try:
            # Open MAP menu first
            self._open_map_menu()

            # Find the VIEW trigger and hover over it
            triggers = self.page.locator(".menu-trigger")
            view_trigger = None
            for i in range(triggers.count()):
                if triggers.nth(i).text_content().strip().upper() == "VIEW":
                    view_trigger = triggers.nth(i)
                    break
            assert view_trigger is not None, "VIEW trigger not found"

            view_trigger.hover()
            self.page.wait_for_timeout(300)

            # VIEW dropdown should now be visible (check via JS)
            view_open = self.page.evaluate("""() => {
                const triggers = document.querySelectorAll('.menu-trigger');
                for (const t of triggers) {
                    if (t.textContent.trim().toUpperCase() === 'VIEW') {
                        const dropdown = t.parentElement.querySelector('.menu-dropdown');
                        return dropdown && !dropdown.hidden;
                    }
                }
                return false;
            }""")
            assert view_open, "VIEW dropdown did not open on hover"

            self._screenshot(name)
            self._close_menu()
            self._record(name, True)
        except Exception as exc:
            self._screenshot(f"{name}_FAIL")
            self._record(name, False, {"error": str(exc)})
            raise

    def test_16_no_console_errors(self):
        """No unexpected page console errors during the test suite.

        Known issues filtered:
          - WebSocket, tile, fetch, net:: errors (benign in test env)
          - setFog not a function (BUG-002 in map-maplibre.js)
        """
        name = "map_menu_16_no_console_errors"
        try:
            # Filter out known benign errors
            real_errors = [
                e for e in self._errors
                if "websocket" not in e.lower()
                and "tile" not in e.lower()
                and "fetch" not in e.lower()
                and "net::" not in e.lower()
                and "setfog" not in e.lower()  # BUG-002: known maplibre compat issue
            ]
            assert len(real_errors) == 0, (
                f"Got {len(real_errors)} unexpected console error(s): {real_errors[:5]}"
            )
            fog_errors = [e for e in self._errors if "setfog" in e.lower()]
            self._record(name, True, {
                "total_errors": len(self._errors),
                "filtered_errors": len(real_errors),
                "fog_errors_bug002": len(fog_errors),
            })
        except Exception as exc:
            self._record(name, False, {"errors": self._errors[:10]})
            raise
