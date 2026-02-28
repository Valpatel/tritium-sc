# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Visual tests for map mode switching (Observe / Tactical / Setup).

Verifies that pressing O, T, S keys (or clicking mode buttons) changes
the map's visual state: pitch, grid overlay, 3D models, layer visibility.

Uses Playwright to interact with the live Command Center and reads map
state from window._mapState (exposed by map-maplibre.js).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.lib.results_db import ResultsDB
from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/map-mode-screenshots")


class TestMapModes:
    """Playwright tests for map mode visual switching."""

    @pytest.fixture(autouse=True, scope="class")
    def _browser(
        self,
        request,
        tritium_server: TritiumServer,
        test_db: ResultsDB,
        run_id: int,
    ):
        """Launch browser, navigate to Command Center, wait for map load."""
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

        # Wait for map to fully initialize (MapLibre + Three.js)
        cls.page.wait_for_timeout(4000)

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

    def _get_map_state(self) -> dict:
        """Read map state from window._mapState (exposed by map-maplibre.js)."""
        return self.page.evaluate("""() => {
            const s = window._mapState;
            if (!s || !s.map) return null;
            return {
                currentMode: s.currentMode,
                showGrid: s.showGrid,
                showModels3d: s.showModels3d,
                showSatellite: s.showSatellite,
                showBuildings: s.showBuildings,
                showRoads: s.showRoads,
                showLabels: s.showLabels,
                showWaterways: s.showWaterways,
                showParks: s.showParks,
                tiltMode: s.tiltMode,
                pitch: s.map.getPitch(),
            };
        }""")

    def _get_active_mode_button(self) -> str | None:
        """Return the data-map-mode value of the currently active mode button."""
        return self.page.evaluate("""() => {
            const btn = document.querySelector('[data-map-mode].active');
            return btn ? btn.dataset.mapMode : null;
        }""")

    def _get_layer_hud_text(self) -> str:
        """Read the layer HUD text content."""
        return self.page.evaluate("""() => {
            const hud = document.getElementById('map-layer-hud');
            return hud ? hud.textContent : '';
        }""")

    def test_01_initial_state_observe(self):
        """Default mode should be 'observe' with top-down view."""
        name = "map_mode_01_initial_observe"
        try:
            state = self._get_map_state()
            assert state is not None, "Map state not available (map not initialized)"
            assert state["currentMode"] == "observe", \
                f"Expected observe mode, got {state['currentMode']}"
            active_btn = self._get_active_mode_button()
            assert active_btn == "observe", \
                f"Expected observe button active, got {active_btn}"
            self._record(name, True, state)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_02_tactical_mode_tilted(self):
        """T key should switch to tactical: tilted pitch, grid on, 3D models on."""
        name = "map_mode_02_tactical_tilted"
        try:
            self.page.keyboard.press("t")
            self.page.wait_for_timeout(800)  # wait for easeTo animation

            state = self._get_map_state()
            assert state is not None, "Map state not available"
            assert state["currentMode"] == "tactical", \
                f"Expected tactical mode, got {state['currentMode']}"
            assert state["showGrid"] is True, "Grid should be ON in tactical mode"
            assert state["showModels3d"] is True, "3D models should be ON in tactical mode"
            assert state["pitch"] > 10, \
                f"Tactical mode should be tilted (pitch > 10), got {state['pitch']}"
            assert state["tiltMode"] == "tilted", \
                f"tiltMode should be 'tilted', got {state['tiltMode']}"

            active_btn = self._get_active_mode_button()
            assert active_btn == "tactical", \
                f"Expected tactical button active, got {active_btn}"

            hud = self._get_layer_hud_text()
            assert "TACTICAL" in hud, f"HUD should show TACTICAL, got: {hud}"
            assert "GRID" in hud, f"HUD should show GRID, got: {hud}"

            self._record(name, True, state)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_03_setup_mode_topdown_with_grid(self):
        """S key should switch to setup: top-down, grid on, 3D models on."""
        name = "map_mode_03_setup_topdown_grid"
        try:
            self.page.keyboard.press("s")
            self.page.wait_for_timeout(800)

            state = self._get_map_state()
            assert state is not None, "Map state not available"
            assert state["currentMode"] == "setup", \
                f"Expected setup mode, got {state['currentMode']}"
            assert state["showGrid"] is True, "Grid should be ON in setup mode"
            assert state["showModels3d"] is True, "3D models should be ON in setup mode"
            assert state["pitch"] < 5, \
                f"Setup mode should be top-down (pitch < 5), got {state['pitch']}"
            assert state["tiltMode"] == "top-down", \
                f"tiltMode should be 'top-down', got {state['tiltMode']}"
            assert state["showRoads"] is False, "Roads should be OFF in setup mode"
            assert state["showWaterways"] is False, "Waterways should be OFF in setup mode"
            assert state["showParks"] is False, "Parks should be OFF in setup mode"

            active_btn = self._get_active_mode_button()
            assert active_btn == "setup", \
                f"Expected setup button active, got {active_btn}"

            hud = self._get_layer_hud_text()
            assert "SETUP" in hud, f"HUD should show SETUP, got: {hud}"

            self._record(name, True, state)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_04_observe_mode_topdown_no_grid(self):
        """O key should switch to observe: top-down, no grid, no 3D models."""
        name = "map_mode_04_observe_topdown"
        try:
            self.page.keyboard.press("o")
            self.page.wait_for_timeout(800)

            state = self._get_map_state()
            assert state is not None, "Map state not available"
            assert state["currentMode"] == "observe", \
                f"Expected observe mode, got {state['currentMode']}"
            assert state["showGrid"] is False, "Grid should be OFF in observe mode"
            assert state["showModels3d"] is False, "3D models should be OFF in observe mode"
            assert state["pitch"] < 5, \
                f"Observe mode should be top-down (pitch < 5), got {state['pitch']}"
            assert state["showRoads"] is True, "Roads should be ON in observe mode"
            assert state["showWaterways"] is True, "Waterways should be ON in observe mode"
            assert state["showParks"] is True, "Parks should be ON in observe mode"
            assert state["showSatellite"] is True, "Satellite should be ON in observe mode"
            assert state["showBuildings"] is True, "Buildings should be ON in observe mode"

            active_btn = self._get_active_mode_button()
            assert active_btn == "observe", \
                f"Expected observe button active, got {active_btn}"

            hud = self._get_layer_hud_text()
            assert "OBSERVE" in hud, f"HUD should show OBSERVE, got: {hud}"

            self._record(name, True, state)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_05_mode_roundtrip(self):
        """Full roundtrip: O -> T -> S -> O verifying each transition."""
        name = "map_mode_05_roundtrip"
        try:
            transitions = [
                ("o", "observe"),
                ("t", "tactical"),
                ("s", "setup"),
                ("o", "observe"),
            ]
            results = []
            for key, expected_mode in transitions:
                self.page.keyboard.press(key)
                self.page.wait_for_timeout(600)
                state = self._get_map_state()
                assert state is not None, "Map state unavailable"
                actual = state["currentMode"]
                assert actual == expected_mode, \
                    f"After pressing '{key}': expected {expected_mode}, got {actual}"
                results.append({"key": key, "mode": actual, "pitch": state["pitch"]})

            self._record(name, True, {"transitions": results})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_06_grid_visible_in_tactical(self):
        """In tactical mode, grid overlay lines should be rendered."""
        name = "map_mode_06_grid_layers"
        try:
            self.page.keyboard.press("t")
            self.page.wait_for_timeout(800)

            grid_exists = self.page.evaluate("""() => {
                const s = window._mapState;
                if (!s || !s.map) return false;
                return !!(s.map.getLayer('grid-minor') && s.map.getLayer('grid-major'));
            }""")
            assert grid_exists, "Grid layers (grid-minor, grid-major) not found on map"

            grid_visible = self.page.evaluate("""() => {
                const s = window._mapState;
                const minor = s.map.getLayoutProperty('grid-minor', 'visibility');
                const major = s.map.getLayoutProperty('grid-major', 'visibility');
                return { minor, major };
            }""")
            assert grid_visible["minor"] == "visible", \
                f"grid-minor should be visible, got {grid_visible['minor']}"
            assert grid_visible["major"] == "visible", \
                f"grid-major should be visible, got {grid_visible['major']}"

            self._record(name, True, grid_visible)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_07_grid_hidden_in_observe(self):
        """In observe mode, grid overlay lines should be hidden."""
        name = "map_mode_07_grid_hidden"
        try:
            self.page.keyboard.press("o")
            self.page.wait_for_timeout(800)

            grid_visible = self.page.evaluate("""() => {
                const s = window._mapState;
                if (!s || !s.map) return null;
                if (!s.map.getLayer('grid-minor')) return {minor: 'none', major: 'none'};
                const minor = s.map.getLayoutProperty('grid-minor', 'visibility');
                const major = s.map.getLayoutProperty('grid-major', 'visibility');
                return { minor, major };
            }""")
            assert grid_visible is not None, "Could not read grid visibility"
            assert grid_visible["minor"] == "none", \
                f"grid-minor should be hidden in observe, got {grid_visible['minor']}"
            assert grid_visible["major"] == "none", \
                f"grid-major should be hidden in observe, got {grid_visible['major']}"

            self._record(name, True, grid_visible)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_08_button_click_mode_switch(self):
        """Clicking mode buttons (not keyboard) should also switch modes."""
        name = "map_mode_08_button_click"
        try:
            # Click tactical button
            self.page.click('[data-map-mode="tactical"]')
            self.page.wait_for_timeout(800)
            state = self._get_map_state()
            assert state["currentMode"] == "tactical", \
                f"Click tactical: expected tactical, got {state['currentMode']}"

            # Click setup button
            self.page.click('[data-map-mode="setup"]')
            self.page.wait_for_timeout(800)
            state = self._get_map_state()
            assert state["currentMode"] == "setup", \
                f"Click setup: expected setup, got {state['currentMode']}"

            # Click observe button
            self.page.click('[data-map-mode="observe"]')
            self.page.wait_for_timeout(800)
            state = self._get_map_state()
            assert state["currentMode"] == "observe", \
                f"Click observe: expected observe, got {state['currentMode']}"

            self._record(name, True, state)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise
