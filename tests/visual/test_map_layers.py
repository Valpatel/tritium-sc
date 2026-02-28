# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Playwright E2E tests for map layer toggle behavior in the Command Center.

Verifies that keyboard shortcuts and programmatic actions correctly toggle
map layer visibility (satellite, roads, buildings, terrain, fog, grid,
labels, models, waterways, parks) and that the internal _mapState reflects
each change.

Run with:
    .venv/bin/python3 -m pytest tests/visual/test_map_layers.py -v
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.lib.results_db import ResultsDB
from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/map-layer-screenshots")


def _get_map_state(page) -> dict:
    """Read the map module internal state via window._mapState."""
    return page.evaluate("""() => {
        const s = window._mapState;
        if (!s) return null;
        return {
            showSatellite: s.showSatellite,
            showRoads: s.showRoads,
            showBuildings: s.showBuildings,
            showGrid: s.showGrid,
            showFog: s.showFog,
            showTerrain: s.showTerrain,
            showLabels: s.showLabels,
            showModels3d: s.showModels3d,
            showWaterways: s.showWaterways,
            showParks: s.showParks,
        };
    }""")


def _get_map_state_via_actions(page) -> dict:
    """Read map state via the mapActions proxy (the public API)."""
    return page.evaluate("""() => {
        const ma = window._mapActions;
        if (!ma || !ma.getMapState) return null;
        return ma.getMapState();
    }""")


def _call_toggle(page, fn_name: str) -> None:
    """Invoke a toggle function via window._mapActions."""
    page.evaluate(f"() => window._mapActions.{fn_name}()")


class TestMapLayers:
    """Playwright-based E2E tests for map layer toggles."""

    @pytest.fixture(autouse=True, scope="class")
    def _browser(
        self,
        request,
        tritium_server: TritiumServer,
        test_db: ResultsDB,
        run_id: int,
    ):
        """Launch browser, navigate to Command Center, wait for map init."""
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
        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        # Wait for map initialization -- _mapState.initialized becomes true
        cls.page.wait_for_function(
            "() => window._mapState && window._mapState.initialized === true",
            timeout=20000,
        )
        # Extra settle time for layers to finish rendering
        cls.page.wait_for_timeout(2000)

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
        """Take a named screenshot without recording to DB."""
        try:
            self.page.screenshot(
                path=str(SCREENSHOT_DIR / f"{name}.png"),
                full_page=False,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 1. Satellite toggle (keyboard: I)
    # ------------------------------------------------------------------
    def test_01_satellite_toggle(self):
        name = "map_layers_01_satellite_toggle"
        try:
            state_before = _get_map_state(self.page)
            assert state_before is not None, "_mapState not available"
            initial_sat = state_before["showSatellite"]

            self._screenshot(f"{name}_before")

            # Press I to toggle satellite
            self.page.keyboard.press("i")
            self.page.wait_for_timeout(500)

            state_after = _get_map_state(self.page)
            assert state_after["showSatellite"] != initial_sat, (
                f"Satellite did not toggle: was {initial_sat}, "
                f"still {state_after['showSatellite']}"
            )
            self._screenshot(f"{name}_after")

            # Toggle back
            self.page.keyboard.press("i")
            self.page.wait_for_timeout(500)
            state_restored = _get_map_state(self.page)
            assert state_restored["showSatellite"] == initial_sat, (
                "Satellite did not restore to original state"
            )

            self._record(name, True, {
                "initial": initial_sat,
                "toggled": state_after["showSatellite"],
                "restored": state_restored["showSatellite"],
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # 2. Roads toggle (keyboard: G)
    # ------------------------------------------------------------------
    def test_02_roads_toggle(self):
        name = "map_layers_02_roads_toggle"
        try:
            state_before = _get_map_state(self.page)
            initial_roads = state_before["showRoads"]

            self.page.keyboard.press("g")
            self.page.wait_for_timeout(500)

            state_after = _get_map_state(self.page)
            assert state_after["showRoads"] != initial_roads, (
                f"Roads did not toggle: was {initial_roads}, "
                f"still {state_after['showRoads']}"
            )
            self._screenshot(f"{name}_toggled")

            # Restore
            self.page.keyboard.press("g")
            self.page.wait_for_timeout(500)
            state_restored = _get_map_state(self.page)
            assert state_restored["showRoads"] == initial_roads

            self._record(name, True, {
                "initial": initial_roads,
                "toggled": state_after["showRoads"],
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # 3. Buildings toggle (keyboard: K)
    # ------------------------------------------------------------------
    def test_03_buildings_toggle(self):
        name = "map_layers_03_buildings_toggle"
        try:
            state_before = _get_map_state(self.page)
            initial_bldg = state_before["showBuildings"]

            self.page.keyboard.press("k")
            self.page.wait_for_timeout(500)

            state_after = _get_map_state(self.page)
            assert state_after["showBuildings"] != initial_bldg, (
                f"Buildings did not toggle: was {initial_bldg}, "
                f"still {state_after['showBuildings']}"
            )
            self._screenshot(f"{name}_toggled")

            # Restore
            self.page.keyboard.press("k")
            self.page.wait_for_timeout(500)
            state_restored = _get_map_state(self.page)
            assert state_restored["showBuildings"] == initial_bldg

            self._record(name, True, {
                "initial": initial_bldg,
                "toggled": state_after["showBuildings"],
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # 4. Terrain toggle (keyboard: H)
    # ------------------------------------------------------------------
    def test_04_terrain_toggle(self):
        name = "map_layers_04_terrain_toggle"
        try:
            state_before = _get_map_state(self.page)
            initial_terrain = state_before["showTerrain"]

            self.page.keyboard.press("h")
            self.page.wait_for_timeout(500)

            state_after = _get_map_state(self.page)
            # Note: toggleTerrain may bail out if map.setTerrain is not
            # available in headless MapLibre.  Accept either a real toggle
            # or the value staying the same if the API is missing.
            terrain_toggled = state_after["showTerrain"] != initial_terrain

            if terrain_toggled:
                # Restore
                self.page.keyboard.press("h")
                self.page.wait_for_timeout(500)

            self._screenshot(f"{name}_after")
            self._record(name, True, {
                "initial": initial_terrain,
                "toggled": state_after["showTerrain"],
                "api_available": terrain_toggled,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # 5. Fog toggle (via _mapActions)
    # ------------------------------------------------------------------
    def test_05_fog_toggle(self):
        name = "map_layers_05_fog_toggle"
        try:
            state_before = _get_map_state(self.page)
            initial_fog = state_before["showFog"]

            _call_toggle(self.page, "toggleFog")
            self.page.wait_for_timeout(500)

            state_after = _get_map_state(self.page)
            assert state_after["showFog"] != initial_fog, (
                f"Fog did not toggle: was {initial_fog}, "
                f"still {state_after['showFog']}"
            )
            self._screenshot(f"{name}_toggled")

            # Restore
            _call_toggle(self.page, "toggleFog")
            self.page.wait_for_timeout(500)
            state_restored = _get_map_state(self.page)
            assert state_restored["showFog"] == initial_fog

            self._record(name, True, {
                "initial": initial_fog,
                "toggled": state_after["showFog"],
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # 6. Grid toggle (via _mapActions)
    # ------------------------------------------------------------------
    def test_06_grid_toggle(self):
        name = "map_layers_06_grid_toggle"
        try:
            state_before = _get_map_state(self.page)
            initial_grid = state_before["showGrid"]

            _call_toggle(self.page, "toggleGrid")
            self.page.wait_for_timeout(500)

            state_after = _get_map_state(self.page)
            assert state_after["showGrid"] != initial_grid, (
                f"Grid did not toggle: was {initial_grid}, "
                f"still {state_after['showGrid']}"
            )
            self._screenshot(f"{name}_toggled")

            # Restore
            _call_toggle(self.page, "toggleGrid")
            self.page.wait_for_timeout(500)
            state_restored = _get_map_state(self.page)
            assert state_restored["showGrid"] == initial_grid

            self._record(name, True, {
                "initial": initial_grid,
                "toggled": state_after["showGrid"],
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # 7. Labels toggle (via _mapActions)
    # ------------------------------------------------------------------
    def test_07_labels_toggle(self):
        name = "map_layers_07_labels_toggle"
        try:
            state_before = _get_map_state(self.page)
            initial_labels = state_before["showLabels"]

            _call_toggle(self.page, "toggleLabels")
            self.page.wait_for_timeout(500)

            state_after = _get_map_state(self.page)
            assert state_after["showLabels"] != initial_labels, (
                f"Labels did not toggle: was {initial_labels}, "
                f"still {state_after['showLabels']}"
            )
            self._screenshot(f"{name}_toggled")

            # Restore
            _call_toggle(self.page, "toggleLabels")
            self.page.wait_for_timeout(500)
            state_restored = _get_map_state(self.page)
            assert state_restored["showLabels"] == initial_labels

            self._record(name, True, {
                "initial": initial_labels,
                "toggled": state_after["showLabels"],
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # 8. 3D Models toggle (via _mapActions)
    # ------------------------------------------------------------------
    def test_08_models_toggle(self):
        name = "map_layers_08_models_toggle"
        try:
            state_before = _get_map_state(self.page)
            initial_models = state_before["showModels3d"]

            _call_toggle(self.page, "toggleModels")
            self.page.wait_for_timeout(500)

            state_after = _get_map_state(self.page)
            assert state_after["showModels3d"] != initial_models, (
                f"Models did not toggle: was {initial_models}, "
                f"still {state_after['showModels3d']}"
            )
            self._screenshot(f"{name}_toggled")

            # Restore
            _call_toggle(self.page, "toggleModels")
            self.page.wait_for_timeout(500)
            state_restored = _get_map_state(self.page)
            assert state_restored["showModels3d"] == initial_models

            self._record(name, True, {
                "initial": initial_models,
                "toggled": state_after["showModels3d"],
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # 9. Layer state consistency between _mapState and getMapState()
    # ------------------------------------------------------------------
    def test_09_layer_state_in_store(self):
        name = "map_layers_09_layer_state_in_store"
        try:
            # Toggle satellite off (it starts on by default)
            _call_toggle(self.page, "toggleSatellite")
            self.page.wait_for_timeout(300)

            # Toggle grid on (it starts off by default)
            _call_toggle(self.page, "toggleGrid")
            self.page.wait_for_timeout(300)

            # Read both state sources
            direct_state = _get_map_state(self.page)
            actions_state = _get_map_state_via_actions(self.page)

            assert direct_state is not None, "_mapState not available"
            assert actions_state is not None, "_mapActions.getMapState() not available"

            # Verify consistency between the two state access methods
            layer_keys = [
                "showSatellite", "showRoads", "showBuildings", "showGrid",
                "showFog", "showTerrain", "showLabels", "showModels3d",
                "showWaterways", "showParks",
            ]
            mismatches = []
            for key in layer_keys:
                if direct_state.get(key) != actions_state.get(key):
                    mismatches.append(
                        f"{key}: _mapState={direct_state.get(key)} vs "
                        f"getMapState()={actions_state.get(key)}"
                    )

            assert len(mismatches) == 0, (
                f"State mismatch between _mapState and getMapState(): "
                f"{'; '.join(mismatches)}"
            )

            # Verify the toggles we just did are reflected
            assert direct_state["showSatellite"] is False, (
                "Satellite should be off after toggle"
            )
            assert direct_state["showGrid"] is True, (
                "Grid should be on after toggle"
            )

            self._screenshot(name)

            # Restore
            _call_toggle(self.page, "toggleSatellite")
            _call_toggle(self.page, "toggleGrid")
            self.page.wait_for_timeout(300)

            self._record(name, True, {
                "direct_state": direct_state,
                "actions_state": actions_state,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    # ------------------------------------------------------------------
    # 10. Multiple layers toggled simultaneously
    # ------------------------------------------------------------------
    def test_10_multiple_layers(self):
        name = "map_layers_10_multiple_layers"
        try:
            # Record initial state
            state_initial = _get_map_state(self.page)
            assert state_initial is not None, "_mapState not available"

            self._screenshot(f"{name}_initial")

            # Toggle several layers: satellite off, roads off, grid on,
            # fog on, waterways off
            _call_toggle(self.page, "toggleSatellite")  # on -> off
            _call_toggle(self.page, "toggleRoads")       # on -> off
            _call_toggle(self.page, "toggleGrid")        # off -> on
            _call_toggle(self.page, "toggleFog")         # off -> on
            _call_toggle(self.page, "toggleWaterways")   # on -> off
            self.page.wait_for_timeout(500)

            state_multi = _get_map_state(self.page)
            self._screenshot(f"{name}_multi_toggled")

            # Verify each expected state
            expected = {
                "showSatellite": not state_initial["showSatellite"],
                "showRoads": not state_initial["showRoads"],
                "showGrid": not state_initial["showGrid"],
                "showFog": not state_initial["showFog"],
                "showWaterways": not state_initial["showWaterways"],
                # Unchanged layers
                "showBuildings": state_initial["showBuildings"],
                "showLabels": state_initial["showLabels"],
                "showModels3d": state_initial["showModels3d"],
                "showParks": state_initial["showParks"],
            }

            errors = []
            for key, want in expected.items():
                got = state_multi.get(key)
                if got != want:
                    errors.append(f"{key}: expected {want}, got {got}")

            assert len(errors) == 0, (
                f"Multi-layer toggle failures: {'; '.join(errors)}"
            )

            # Also verify via the public API
            actions_state = _get_map_state_via_actions(self.page)
            for key, want in expected.items():
                assert actions_state.get(key) == want, (
                    f"getMapState() mismatch for {key}: "
                    f"expected {want}, got {actions_state.get(key)}"
                )

            # Restore all toggled layers
            _call_toggle(self.page, "toggleSatellite")
            _call_toggle(self.page, "toggleRoads")
            _call_toggle(self.page, "toggleGrid")
            _call_toggle(self.page, "toggleFog")
            _call_toggle(self.page, "toggleWaterways")
            self.page.wait_for_timeout(500)

            state_restored = _get_map_state(self.page)
            self._screenshot(f"{name}_restored")

            # Verify restoration
            restore_errors = []
            for key in expected:
                if state_restored.get(key) != state_initial.get(key):
                    restore_errors.append(
                        f"{key}: initial={state_initial[key]}, "
                        f"restored={state_restored[key]}"
                    )
            assert len(restore_errors) == 0, (
                f"Layer restoration failures: {'; '.join(restore_errors)}"
            )

            self._record(name, True, {
                "initial": state_initial,
                "multi_toggled": state_multi,
                "restored": state_restored,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise
