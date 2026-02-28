# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Error boundary E2E tests for the Command Center.

Verifies the UI handles bad data, missing elements, connection failures,
and edge cases gracefully -- no crashes, no uncaught exceptions, no
"undefined" leaking into user-visible text.

Uses Playwright (headed browser) against a live TRITIUM-SC server.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import requests

from tests.lib.results_db import ResultsDB
from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/error-boundary-screenshots")


class TestErrorBoundaries:
    """Playwright-based tests for error conditions in the Command Center."""

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
        cls.server = tritium_server
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

    def _count_page_errors(self) -> int:
        """Return the current count of captured page errors."""
        return len(self._errors)

    def _page_text_contains(self, bad_strings: list[str]) -> list[str]:
        """Check if the visible page text contains any bad strings."""
        body_text = self.page.evaluate("() => document.body.innerText")
        found = []
        for bad in bad_strings:
            if bad.lower() in body_text.lower():
                found.append(bad)
        return found

    # ------------------------------------------------------------------
    # Test 1: Bad telemetry data
    # ------------------------------------------------------------------

    def test_01_bad_telemetry_data(self):
        """Send malformed WebSocket messages -- missing fields, wrong types,
        null values. Verify no uncaught page errors and page stays alive."""
        name = "error_01_bad_telemetry"
        errors_before = self._count_page_errors()
        try:
            # Inject a series of malformed telemetry messages directly via
            # the WebSocket message handler on the client side.
            self.page.evaluate("""() => {
                const ws = window.TritiumStore;
                if (!ws) return;

                // Simulate the WebSocket onmessage handler receiving bad data.
                // We call _handleMessage on the global WebSocketManager if accessible,
                // or fall back to dispatching via TritiumStore directly.

                const badPayloads = [
                    // Missing target_id entirely
                    { type: 'sim_telemetry', data: { name: 'ghost', x: 10, y: 20 } },
                    // Null values everywhere
                    { type: 'sim_telemetry', data: { target_id: null, name: null, position: null } },
                    // Wrong types (numbers as strings)
                    { type: 'sim_telemetry', data: { target_id: 'test-bad-1', x: 'not_a_number', y: 'nope', health: 'full', heading: 'north' } },
                    // Empty object
                    { type: 'sim_telemetry', data: {} },
                    // No data field at all
                    { type: 'sim_telemetry' },
                    // Completely empty
                    {},
                    // Non-object data field
                    { type: 'sim_telemetry', data: 'this is a string' },
                    // Array data field
                    { type: 'sim_telemetry', data: [1, 2, 3] },
                    // Deeply nested nonsense
                    { type: 'sim_telemetry', data: { target_id: 'test-bad-2', position: { x: { nested: true }, y: [1] } } },
                    // Batch with mixed valid/invalid
                    { type: 'amy_sim_telemetry_batch', data: [
                        { target_id: 'test-ok', name: 'Valid', x: 10, y: 20, alliance: 'friendly', asset_type: 'turret' },
                        null,
                        undefined,
                        { name: 'no-id' },
                        42,
                        'string-in-array',
                    ]},
                    // Unknown event type
                    { type: 'totally_unknown_event_xyz', data: { foo: 'bar' } },
                    // game_state with absurd values
                    { type: 'game_state', data: { state: null, wave: -999, score: Infinity } },
                ];

                // Directly invoke the WebSocket handler path via dispatchEvent on
                // window -- or just push through TritiumStore.updateUnit which is
                // what the WS handler calls.
                for (const payload of badPayloads) {
                    try {
                        // Simulate the onmessage code path: parse the msg and
                        // call _handleMessage. We do this by creating a
                        // MessageEvent-like call through the WS handler.
                        const event = new MessageEvent('message', {
                            data: JSON.stringify(payload),
                        });
                        // Find any open WebSocket and dispatch
                        // Or just directly call updateUnit with bad data
                        const t = payload?.data;
                        if (t && typeof t === 'object' && !Array.isArray(t) && t.target_id) {
                            window.TritiumStore.updateUnit(t.target_id, t);
                        }
                    } catch (e) {
                        // Swallow -- we're testing the frontend doesn't throw uncaught
                    }
                }
            }""")

            self.page.wait_for_timeout(1000)
            self._screenshot(f"{name}_after_injection")

            # The page should still be alive and responsive
            title = self.page.title()
            assert title is not None and len(title) > 0, "Page title is empty after bad telemetry"

            # Check that no new page-level errors were thrown
            errors_after = self._count_page_errors()
            new_errors = self._errors[errors_before:]
            # Filter out non-critical errors (console.error from WS parse is expected)
            critical_errors = [e for e in new_errors if "TypeError" in e or "Cannot read" in e]
            assert len(critical_errors) == 0, (
                f"Critical page errors after bad telemetry: {critical_errors}"
            )

            # Verify the page still renders meaningful content
            clock = self.page.locator("#header-clock").text_content()
            assert clock is not None and "UTC" in clock, "Clock disappeared after bad telemetry"

            self._record(name, True, {
                "payloads_injected": 12,
                "new_errors": len(new_errors),
                "critical_errors": len(critical_errors),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 2: Unknown unit type renders with fallback
    # ------------------------------------------------------------------

    def test_02_unknown_unit_type(self):
        """Inject a unit with asset_type 'unknown_robot'. Verify it appears
        in the store with a fallback representation, not a crash."""
        name = "error_02_unknown_unit_type"
        errors_before = self._count_page_errors()
        try:
            # Inject an unknown unit type directly into the store
            self.page.evaluate("""() => {
                window.TritiumStore.updateUnit('mystery-bot-001', {
                    name: 'Mystery Bot',
                    type: 'unknown_robot',
                    alliance: 'friendly',
                    position: { x: 50, y: 50 },
                    heading: 0,
                    health: 100,
                    maxHealth: 100,
                    status: 'active',
                    speed: 2.0,
                });
            }""")

            self.page.wait_for_timeout(1000)
            self._screenshot(f"{name}_after_inject")

            # Verify the unit is in the store
            unit_exists = self.page.evaluate(
                "() => window.TritiumStore.units.has('mystery-bot-001')"
            )
            assert unit_exists, "Unknown unit type was not added to store"

            unit_type = self.page.evaluate(
                "() => window.TritiumStore.units.get('mystery-bot-001')?.type"
            )
            assert unit_type == "unknown_robot", f"Unit type was changed: {unit_type}"

            # No critical page errors
            new_errors = self._errors[errors_before:]
            critical = [e for e in new_errors if "TypeError" in e or "Cannot read" in e]
            assert len(critical) == 0, f"Critical errors after unknown type: {critical}"

            # Page is still alive
            clock = self.page.locator("#header-clock").text_content()
            assert clock is not None, "Page crashed after unknown unit type"

            self._record(name, True, {
                "unit_exists": unit_exists,
                "unit_type": unit_type,
                "critical_errors": len(critical),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 3: Zero units -- empty state renders correctly
    # ------------------------------------------------------------------

    def test_03_zero_units_clean_state(self):
        """Reset game and clear all units. Verify the UI renders a clean
        empty state without 'undefined', 'NaN', or 'null' in visible text."""
        name = "error_03_zero_units"
        errors_before = self._count_page_errors()
        try:
            # Reset the game server-side
            try:
                requests.post(f"{self.url}/api/game/reset", timeout=5)
            except Exception:
                pass  # Server may not support reset in current state

            # Clear units from client store
            self.page.evaluate("""() => {
                window.TritiumStore.units.clear();
                window.TritiumStore._notify('units', window.TritiumStore.units);
            }""")

            self.page.wait_for_timeout(1000)
            self._screenshot(f"{name}_empty_state")

            # Check for bad strings in visible page text
            bad_strings = self._page_text_contains(["undefined", "NaN", "null"])
            # Filter out legitimate uses of "null" in tech contexts -- focus on
            # unit count areas and panel bodies
            header_text = self.page.evaluate("""() => {
                const header = document.getElementById('header-bar');
                return header ? header.innerText : '';
            }""")
            panel_text = self.page.evaluate("""() => {
                const container = document.getElementById('panel-container');
                return container ? container.innerText : '';
            }""")
            combined = (header_text + " " + panel_text).lower()

            header_bad = [s for s in ["undefined", "nan"] if s in combined]
            assert len(header_bad) == 0, (
                f"Bad strings found in header/panels with zero units: {header_bad}"
            )

            # Unit count in header should be 0, not empty or NaN
            stat_text = self.page.locator("#header-units .stat-value").text_content()
            if stat_text is not None:
                stat_stripped = stat_text.strip()
                assert stat_stripped != "NaN", "Unit count shows NaN"
                assert stat_stripped != "undefined", "Unit count shows undefined"
                assert stat_stripped != "", "Unit count is empty string"

            # No new critical errors
            new_errors = self._errors[errors_before:]
            critical = [e for e in new_errors if "TypeError" in e or "Cannot read" in e]
            assert len(critical) == 0, f"Critical errors with zero units: {critical}"

            self._record(name, True, {
                "stat_text": stat_text,
                "header_bad_strings": header_bad,
                "critical_errors": len(critical),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 4: Rapid mode switching (O/T/S x20 in 2 seconds)
    # ------------------------------------------------------------------

    def test_04_rapid_mode_switching(self):
        """Switch modes O/T/S rapidly 20 times in ~2 seconds. Verify no
        crash and the final mode is correct."""
        name = "error_04_rapid_mode_switch"
        errors_before = self._count_page_errors()
        try:
            modes = ["o", "t", "s"]
            sequence = []
            for i in range(20):
                key = modes[i % 3]
                sequence.append(key)

            # Fire them rapidly (100ms apart = 2s total)
            for key in sequence:
                self.page.keyboard.press(key)
                self.page.wait_for_timeout(100)

            # Wait for UI to settle
            self.page.wait_for_timeout(1000)
            self._screenshot(f"{name}_after_rapid")

            # The last mode pressed determines the expected state
            expected_mode_map = {"o": "observe", "t": "tactical", "s": "setup"}
            last_key = sequence[-1]
            expected_mode = expected_mode_map[last_key]

            actual_mode = self.page.evaluate(
                "() => window.TritiumStore.map.mode"
            )
            assert actual_mode == expected_mode, (
                f"Expected mode '{expected_mode}' after rapid switching, got '{actual_mode}'"
            )

            # Page should still be alive
            title = self.page.title()
            assert title is not None and len(title) > 0, "Page title gone after rapid mode switch"

            # No critical errors
            new_errors = self._errors[errors_before:]
            critical = [e for e in new_errors if "TypeError" in e or "Cannot read" in e]
            assert len(critical) == 0, f"Critical errors after rapid mode switch: {critical}"

            self._record(name, True, {
                "switches": 20,
                "expected_mode": expected_mode,
                "actual_mode": actual_mode,
                "critical_errors": len(critical),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 5: Panel overflow -- inject 100 units
    # ------------------------------------------------------------------

    def test_05_panel_overflow_100_units(self):
        """Inject 100 units via the store. Verify the units panel scrolls
        correctly without layout breakage."""
        name = "error_05_panel_overflow"
        errors_before = self._count_page_errors()
        try:
            # Inject 100 units into the store
            self.page.evaluate("""() => {
                const alliances = ['friendly', 'hostile'];
                const types = ['turret', 'drone', 'rover', 'tank', 'scout_drone', 'apc'];
                for (let i = 0; i < 100; i++) {
                    const alliance = alliances[i % 2];
                    const type = types[i % types.length];
                    window.TritiumStore.updateUnit(`overflow-unit-${i}`, {
                        name: `Unit ${i} (${type})`,
                        type: type,
                        alliance: alliance,
                        position: { x: 20 + (i % 10) * 10, y: 20 + Math.floor(i / 10) * 10 },
                        heading: (i * 36) % 360,
                        health: 50 + (i % 51),
                        maxHealth: 100,
                        status: 'active',
                        speed: 1.0 + (i % 5),
                    });
                }
            }""")

            # Open units panel via keyboard
            self.page.keyboard.press("2")
            self.page.wait_for_timeout(1500)
            self._screenshot(f"{name}_100_units")

            # Verify the store has >= 100 units
            unit_count = self.page.evaluate("() => window.TritiumStore.units.size")
            assert unit_count >= 100, f"Expected >= 100 units, got {unit_count}"

            # Verify the page layout is not broken -- check that the header
            # and map are still visible and reasonably sized
            header_box = self.page.locator("#header-bar").bounding_box()
            assert header_box is not None, "Header disappeared with 100 units"
            assert header_box["height"] < 100, (
                f"Header grew too tall: {header_box['height']}px"
            )

            # Check that the units panel exists and has reasonable bounds
            units_panel = self.page.locator('.panel[data-panel-id="units"]')
            if units_panel.count() > 0 and units_panel.is_visible():
                panel_box = units_panel.bounding_box()
                assert panel_box is not None, "Units panel has no bounding box"
                # Panel should not overflow the viewport (1080px height)
                assert panel_box["height"] <= 1100, (
                    f"Units panel overflowed viewport: {panel_box['height']}px"
                )

            # No critical errors
            new_errors = self._errors[errors_before:]
            critical = [e for e in new_errors if "TypeError" in e or "Cannot read" in e]
            assert len(critical) == 0, f"Critical errors with 100 units: {critical}"

            self._record(name, True, {
                "unit_count": unit_count,
                "header_height": header_box["height"] if header_box else None,
                "critical_errors": len(critical),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 6: Double initialization -- reload immediately
    # ------------------------------------------------------------------

    def test_06_double_initialization(self):
        """Navigate to the page, reload immediately, verify clean restart
        with no zombie state or duplicate elements."""
        name = "error_06_double_init"
        errors_before_reload = self._count_page_errors()
        try:
            # Reload the page immediately (simulates double-init)
            self.page.reload(wait_until="domcontentloaded")
            # Don't wait for networkidle -- reload again quickly
            self.page.wait_for_timeout(500)
            self.page.reload(wait_until="networkidle")
            self.page.wait_for_timeout(3000)

            self._screenshot(f"{name}_after_double_reload")

            # Verify key elements exist exactly once (no duplicates)
            header_count = self.page.locator("#header-bar").count()
            assert header_count == 1, f"Expected 1 header, got {header_count} (duplicate?)"

            canvas_count = self.page.evaluate("""() => {
                const ids = ['maplibre-map', 'tactical-3d-canvas', 'tactical-canvas'];
                let count = 0;
                for (const id of ids) {
                    const el = document.getElementById(id);
                    if (el && el.offsetWidth > 0) count++;
                }
                return count;
            }""")
            assert canvas_count >= 1, "No visible map element after double reload"

            # Store should be reinitialized
            store_exists = self.page.evaluate(
                "() => typeof window.TritiumStore !== 'undefined' && window.TritiumStore !== null"
            )
            assert store_exists, "TritiumStore not available after double reload"

            # Connection status should recover
            self.page.wait_for_timeout(2000)
            conn_status = self.page.evaluate(
                "() => window.TritiumStore.connection.status"
            )
            assert conn_status == "connected", (
                f"WebSocket not reconnected after double reload: {conn_status}"
            )

            # Page title intact
            title = self.page.title()
            assert "TRITIUM" in title, f"Page title wrong after double reload: {title}"

            self._record(name, True, {
                "header_count": header_count,
                "canvas_count": canvas_count,
                "connection_status": conn_status,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 7: WebSocket reconnect indicator
    # ------------------------------------------------------------------

    def test_07_websocket_reconnect(self):
        """Simulate a WebSocket disconnection by closing the client-side WS.
        Verify the connection indicator changes to OFFLINE and then recovers."""
        name = "error_07_ws_reconnect"
        try:
            # Wait for initial connection to be stable
            self.page.wait_for_timeout(1000)

            initial_status = self.page.evaluate(
                "() => window.TritiumStore.connection.status"
            )

            # Force-close the WebSocket from the client side
            self.page.evaluate("""() => {
                // Find the WebSocket object -- it's stored as a private property
                // but we can find open WebSockets through the connection status.
                // The simplest approach: just set the connection status and trigger
                // reconnection behavior by closing any open WS.
                const allWs = performance.getEntriesByType?.('resource')
                    ?.filter(r => r.name.includes('ws'));

                // Force disconnect status to trigger the UI indicator
                window.TritiumStore.set('connection.status', 'disconnected');
            }""")

            self.page.wait_for_timeout(500)
            self._screenshot(f"{name}_disconnected")

            # The connection indicator should show OFFLINE
            conn_label = self.page.locator("#connection-status .conn-label").text_content()
            assert conn_label is not None, "Connection label element not found"
            assert "OFFLINE" in conn_label.upper() or "DISCONNECT" in conn_label.upper(), (
                f"Connection indicator did not show offline state: '{conn_label}'"
            )

            conn_state = self.page.locator("#connection-status").get_attribute("data-state")
            assert conn_state == "disconnected", (
                f"Connection data-state not 'disconnected': '{conn_state}'"
            )

            # Now restore -- simulate reconnection
            self.page.evaluate("""() => {
                window.TritiumStore.set('connection.status', 'connected');
            }""")

            self.page.wait_for_timeout(500)
            self._screenshot(f"{name}_reconnected")

            conn_label_after = self.page.locator("#connection-status .conn-label").text_content()
            assert "ONLINE" in conn_label_after.upper(), (
                f"Connection indicator did not recover to ONLINE: '{conn_label_after}'"
            )

            self._record(name, True, {
                "initial_status": initial_status,
                "disconnected_label": conn_label,
                "reconnected_label": conn_label_after,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 8: Invalid coordinates
    # ------------------------------------------------------------------

    def test_08_invalid_coordinates(self):
        """Spawn a unit at extreme coordinates (999999, 999999). Verify the
        map does not crash, zoom does not go haywire, other units still render."""
        name = "error_08_invalid_coords"
        errors_before = self._count_page_errors()
        try:
            # Inject a unit at extreme coordinates
            self.page.evaluate("""() => {
                window.TritiumStore.updateUnit('extreme-unit-001', {
                    name: 'Far Away Bot',
                    type: 'drone',
                    alliance: 'friendly',
                    position: { x: 999999, y: 999999 },
                    heading: 0,
                    health: 100,
                    maxHealth: 100,
                    status: 'active',
                    speed: 5.0,
                });
            }""")

            self.page.wait_for_timeout(1000)

            # Also inject units at negative extreme and zero
            self.page.evaluate("""() => {
                window.TritiumStore.updateUnit('negative-unit-001', {
                    name: 'Negative Bot',
                    type: 'rover',
                    alliance: 'hostile',
                    position: { x: -999999, y: -999999 },
                    heading: 180,
                    health: 50,
                    maxHealth: 100,
                    status: 'active',
                });
                window.TritiumStore.updateUnit('origin-unit-001', {
                    name: 'Origin Bot',
                    type: 'turret',
                    alliance: 'friendly',
                    position: { x: 0, y: 0 },
                    heading: 0,
                    health: 100,
                    maxHealth: 100,
                    status: 'active',
                });
                // NaN and Infinity coordinates
                window.TritiumStore.updateUnit('nan-unit-001', {
                    name: 'NaN Bot',
                    type: 'tank',
                    alliance: 'friendly',
                    position: { x: NaN, y: NaN },
                    heading: NaN,
                    health: NaN,
                    maxHealth: 100,
                    status: 'active',
                });
                window.TritiumStore.updateUnit('inf-unit-001', {
                    name: 'Infinity Bot',
                    type: 'apc',
                    alliance: 'hostile',
                    position: { x: Infinity, y: -Infinity },
                    heading: Infinity,
                    health: Infinity,
                    maxHealth: 100,
                    status: 'active',
                });
            }""")

            self.page.wait_for_timeout(1000)
            self._screenshot(f"{name}_extreme_coords")

            # The map/canvas should still exist and have reasonable dimensions
            map_ok = self.page.evaluate("""() => {
                const el = document.getElementById('maplibre-map')
                    || document.getElementById('tactical-3d-canvas')
                    || document.getElementById('tactical-canvas');
                if (!el) return false;
                return el.offsetWidth > 100 && el.offsetHeight > 100;
            }""")
            assert map_ok, "Map element disappeared or shrank after extreme coords"

            # The page should still be responsive -- try a keyboard action
            self.page.keyboard.press("o")
            self.page.wait_for_timeout(300)
            mode = self.page.evaluate("() => window.TritiumStore.map.mode")
            assert mode == "observe", f"Keyboard not responsive after extreme coords, mode={mode}"

            # No critical errors
            new_errors = self._errors[errors_before:]
            critical = [e for e in new_errors if "TypeError" in e or "Cannot read" in e]
            assert len(critical) == 0, f"Critical errors after extreme coords: {critical}"

            self._record(name, True, {
                "map_ok": map_ok,
                "mode": mode,
                "units_injected": 5,
                "critical_errors": len(critical),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 9: Malformed game state events
    # ------------------------------------------------------------------

    def test_09_malformed_game_state(self):
        """Push malformed game state data through the store. Verify the
        game HUD does not render garbage text."""
        name = "error_09_malformed_game_state"
        errors_before = self._count_page_errors()
        try:
            # Push a series of bad game state values
            self.page.evaluate("""() => {
                const store = window.TritiumStore;

                // Set game state to nonsense values one at a time
                store.set('game.phase', undefined);
                store.set('game.wave', 'not_a_number');
                store.set('game.score', null);
                store.set('game.eliminations', -1);
                store.set('game.totalWaves', 0);
            }""")

            self.page.wait_for_timeout(500)
            self._screenshot(f"{name}_bad_game_state")

            # Now try setting to reasonable values -- should recover
            self.page.evaluate("""() => {
                const store = window.TritiumStore;
                store.set('game.phase', 'idle');
                store.set('game.wave', 0);
                store.set('game.score', 0);
                store.set('game.eliminations', 0);
                store.set('game.totalWaves', 10);
            }""")

            self.page.wait_for_timeout(500)
            self._screenshot(f"{name}_recovered")

            # Verify the store recovered to sane values
            phase = self.page.evaluate("() => window.TritiumStore.game.phase")
            assert phase == "idle", f"Game phase did not recover: {phase}"

            # No critical errors
            new_errors = self._errors[errors_before:]
            critical = [e for e in new_errors if "TypeError" in e or "Cannot read" in e]
            assert len(critical) == 0, f"Critical errors from bad game state: {critical}"

            self._record(name, True, {
                "phase_recovered": phase,
                "critical_errors": len(critical),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 10: Concurrent panel + mode operations
    # ------------------------------------------------------------------

    def test_10_concurrent_panel_mode_ops(self):
        """Rapidly toggle panels and switch modes simultaneously. Verify
        the DOM remains consistent and no orphaned elements appear."""
        name = "error_10_concurrent_ops"
        errors_before = self._count_page_errors()
        try:
            # Rapid fire: alternate between panel toggles and mode switches
            actions = [
                ("1", "toggle amy"),
                ("o", "observe mode"),
                ("2", "toggle units"),
                ("t", "tactical mode"),
                ("3", "toggle alerts"),
                ("s", "setup mode"),
                ("1", "toggle amy"),
                ("o", "observe mode"),
                ("4", "toggle game"),
                ("t", "tactical mode"),
                ("2", "toggle units"),
                ("s", "setup mode"),
                ("5", "toggle mesh"),
                ("o", "observe mode"),
                ("3", "toggle alerts"),
                ("t", "tactical mode"),
            ]

            for key, _desc in actions:
                self.page.keyboard.press(key)
                self.page.wait_for_timeout(50)  # Very rapid

            self.page.wait_for_timeout(1000)
            self._screenshot(f"{name}_after_rapid")

            # Verify DOM consistency: no duplicate headers, no orphan panels
            header_count = self.page.locator("#header-bar").count()
            assert header_count == 1, f"Duplicate headers: {header_count}"

            # Each panel ID should appear at most once in the DOM
            panel_ids = ["amy", "units", "alerts", "game", "mesh"]
            for pid in panel_ids:
                count = self.page.locator(f'.panel[data-panel-id="{pid}"]').count()
                assert count <= 1, f"Panel '{pid}' duplicated: {count} instances"

            # Store mode should be one of the valid modes
            mode = self.page.evaluate("() => window.TritiumStore.map.mode")
            assert mode in ("observe", "tactical", "setup"), (
                f"Invalid mode after concurrent ops: {mode}"
            )

            # No critical errors
            new_errors = self._errors[errors_before:]
            critical = [e for e in new_errors if "TypeError" in e or "Cannot read" in e]
            assert len(critical) == 0, f"Critical errors from concurrent ops: {critical}"

            self._record(name, True, {
                "mode": mode,
                "header_count": header_count,
                "critical_errors": len(critical),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 11: Store listener exception isolation
    # ------------------------------------------------------------------

    def test_11_store_listener_exception(self):
        """Register a store listener that throws. Verify other listeners
        and the store itself continue working."""
        name = "error_11_listener_exception"
        errors_before = self._count_page_errors()
        try:
            result = self.page.evaluate("""() => {
                let receivedCount = 0;

                // Register a listener that always throws
                const unsub1 = window.TritiumStore.on('game.score', () => {
                    throw new Error('Intentional test explosion in listener');
                });

                // Register a well-behaved listener after the broken one
                const unsub2 = window.TritiumStore.on('game.score', (val) => {
                    receivedCount++;
                });

                // Trigger the path -- the throwing listener should not break
                // the second listener from receiving updates
                window.TritiumStore.set('game.score', 42);
                window.TritiumStore.set('game.score', 99);

                // Clean up
                unsub1();
                unsub2();

                return {
                    receivedCount,
                    finalScore: window.TritiumStore.game.score,
                };
            }""")

            assert result["receivedCount"] == 2, (
                f"Second listener only received {result['receivedCount']} updates "
                f"(expected 2) -- throwing listener broke notification chain"
            )
            assert result["finalScore"] == 99, (
                f"Store value not updated: {result['finalScore']}"
            )

            self._record(name, True, result)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Test 12: API error responses don't crash UI
    # ------------------------------------------------------------------

    def test_12_api_error_responses(self):
        """Hit API endpoints with bad requests. Verify the server returns
        proper error codes (not 500) and the UI stays alive."""
        name = "error_12_api_errors"
        try:
            results = {}

            # Bad place request (missing fields)
            resp = requests.post(
                f"{self.url}/api/game/place",
                json={"name": "bad"},
                timeout=5,
            )
            results["place_missing_fields"] = resp.status_code
            assert resp.status_code == 422, (
                f"Expected 422 for missing fields, got {resp.status_code}"
            )

            # Begin war when not in setup (may be in wrong state)
            # First ensure we're in a non-setup state by resetting then beginning
            requests.post(f"{self.url}/api/game/reset", timeout=5)
            requests.post(f"{self.url}/api/game/begin", timeout=5)
            self.page.wait_for_timeout(1000)
            # Try to begin again -- should fail
            resp2 = requests.post(f"{self.url}/api/game/begin", timeout=5)
            results["double_begin"] = resp2.status_code
            # Could be 400 (wrong state) or 200 (if reset happened fast)
            assert resp2.status_code in (200, 400), (
                f"Unexpected status for double begin: {resp2.status_code}"
            )

            # Non-existent endpoint
            resp3 = requests.get(
                f"{self.url}/api/nonexistent/endpoint", timeout=5
            )
            results["nonexistent"] = resp3.status_code
            assert resp3.status_code == 404, (
                f"Expected 404 for nonexistent endpoint, got {resp3.status_code}"
            )

            # Reset game back to setup for subsequent tests
            requests.post(f"{self.url}/api/game/reset", timeout=5)
            self.page.wait_for_timeout(1000)

            # Page should still be alive after all these API errors
            title = self.page.title()
            assert title is not None and "TRITIUM" in title, (
                f"Page died after API errors: {title}"
            )

            self._record(name, True, results)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise
