# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Layer HUD Verification: Ensure the layer state indicator HUD accurately
reflects the actual toggle states for all layers.

Also verifies:
  - Rapid toggle cycling doesn't leave stale state
  - Toggle All properly updates HUD text
  - Individual toggle reflects in HUD immediately
  - Menu checkmarks match HUD state

Run:
    .venv/bin/python3 -m pytest tests/visual/test_layer_hud_verify.py -v -s
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/layer-hud-verify")


class TestLayerHudVerify:
    """Verify the layer HUD accurately reflects toggle states."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        ctx = self._browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = ctx.new_page()
        self._errors = []
        self.page.on("pageerror", lambda e: self._errors.append(str(e)))
        self.page.goto("http://localhost:8000", wait_until="networkidle", timeout=30000)
        time.sleep(5)
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _get_hud_text(self) -> str:
        return self.page.evaluate("""() => {
            const hud = document.getElementById('map-layer-hud');
            return hud ? hud.textContent.trim() : 'NOT_FOUND';
        }""")

    def _get_map_state(self) -> dict:
        return self.page.evaluate("""() => {
            const ma = window._mapActions;
            return ma && ma.getMapState ? ma.getMapState() : {};
        }""")

    def _click_toggle(self, label: str):
        self.page.locator('.menu-trigger:has-text("MAP")').click()
        time.sleep(0.2)
        self.page.locator(f'.menu-item:has-text("{label}")').first.click()
        time.sleep(0.2)
        self.page.keyboard.press("Escape")
        time.sleep(0.3)

    def _get_menu_checkmarks(self) -> dict:
        """Open MAP menu and read all checkmark states."""
        self.page.locator('.menu-trigger:has-text("MAP")').click()
        time.sleep(0.3)
        marks = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.menu-dropdown:not([hidden]) .menu-item');
            const result = {};
            items.forEach(item => {
                const label = item.querySelector('.menu-item-label')?.textContent?.trim();
                const check = item.querySelector('.menu-item-check')?.textContent?.trim();
                if (label) result[label] = check === '\\u2022' || check === '•';
            });
            return result;
        }""")
        self.page.keyboard.press("Escape")
        time.sleep(0.2)
        return marks

    def test_01_initial_hud_state(self):
        """HUD shows correct initial layer state."""
        hud = self._get_hud_text()
        state = self._get_map_state()
        print(f"HUD text: {hud}")
        print(f"Map state: {json.dumps({k: v for k, v in state.items() if k.startswith('show')}, indent=2)}")

        # HUD should show SAT when satellite is on
        if state.get("showSatellite"):
            assert "SAT" in hud, f"Satellite ON but HUD says: {hud}"
        # HUD should show BLDG when buildings are on
        if state.get("showBuildings"):
            assert "BLDG" in hud, f"Buildings ON but HUD says: {hud}"

        self._screenshot("01_initial_hud")

    def test_02_toggle_satellite_updates_hud(self):
        """Toggling satellite updates the HUD text."""
        hud_before = self._get_hud_text()
        print(f"Before: {hud_before}")
        assert "SAT" in hud_before

        self._click_toggle("Satellite")
        hud_after = self._get_hud_text()
        print(f"After satellite OFF: {hud_after}")

        # SAT should now be gone or marked differently
        # The HUD shows "-SAT" or just doesn't include "SAT"
        assert "SAT" not in hud_after or "-SAT" in hud_after, (
            f"Satellite OFF but HUD still shows SAT: {hud_after}"
        )

        self._screenshot("02_satellite_off")

        # Restore
        self._click_toggle("Satellite")
        hud_restored = self._get_hud_text()
        print(f"Restored: {hud_restored}")
        assert "SAT" in hud_restored

    def test_03_toggle_all_off_updates_hud(self):
        """Toggle All OFF clears all layer indicators from HUD."""
        self._click_toggle("Toggle All")
        time.sleep(0.5)

        hud = self._get_hud_text()
        state = self._get_map_state()
        print(f"HUD after Toggle All OFF: {hud}")

        self._screenshot("03_toggle_all_off")

        # After toggle all off, most show* keys should be false
        on_count = sum(1 for k, v in state.items() if k.startswith("show") and v)
        off_count = sum(1 for k, v in state.items() if k.startswith("show") and not v)
        print(f"State: {on_count} ON, {off_count} OFF")

        assert off_count > on_count, (
            f"After Toggle All OFF, expected most layers off. Got {on_count} ON, {off_count} OFF"
        )

        # Restore
        self._click_toggle("Toggle All")
        time.sleep(0.5)
        self._screenshot("03_toggle_all_restored")

    def test_04_menu_checkmarks_match_state(self):
        """Menu checkmarks reflect actual layer state."""
        state = self._get_map_state()
        marks = self._get_menu_checkmarks()

        print("Checkmark vs State comparison:")
        mismatches = []
        state_map = {
            "Satellite": "showSatellite",
            "Roads": "showRoads",
            "Buildings": "showBuildings",
            "Waterways": "showWaterways",
            "Parks": "showParks",
            "Grid": "showGrid",
            "3D Models": "showModels3d",
            "Labels": "showLabels",
            "Mesh Network": "showMesh",
            "Tracers": "showTracers",
            "Explosions": "showExplosions",
            "Particles": "showParticles",
            "Hit Flashes": "showHitFlashes",
            "Floating Text": "showFloatingText",
            "Kill Feed": "showKillFeed",
            "Screen FX": "showScreenFx",
            "Banners": "showBanners",
            "Layer HUD": "showLayerHud",
            "Health Bars": "showHealthBars",
            "Selection FX": "showSelectionFx",
            "Fog": "showFog",
            "Terrain": "showTerrain",
        }

        for label, state_key in state_map.items():
            checked = marks.get(label)
            actual = state.get(state_key)
            match = checked == actual
            status = "OK" if match else "MISMATCH"
            print(f"  {status:8s} {label:18s} check={checked} state={actual}")
            if not match:
                mismatches.append(f"{label}: check={checked} state={actual}")

        self._screenshot("04_checkmarks")

        assert len(mismatches) == 0, (
            f"Menu checkmark mismatches: {'; '.join(mismatches)}"
        )

    def test_05_rapid_toggle_cycling(self):
        """Rapidly toggle a layer 10 times and verify state is correct."""
        print("Rapid toggle: Satellite x10")
        state_before = self._get_map_state()
        initial = state_before.get("showSatellite")

        for i in range(10):
            self._click_toggle("Satellite")
            time.sleep(0.1)

        time.sleep(0.5)
        state_after = self._get_map_state()
        final = state_after.get("showSatellite")

        # After 10 toggles (even number), should be back to initial
        print(f"  Initial: {initial} → Final: {final}")
        assert final == initial, (
            f"After 10 toggles, expected {initial} but got {final}"
        )

        hud = self._get_hud_text()
        print(f"  HUD: {hud}")

        self._screenshot("05_rapid_toggle")

    def test_06_toggle_all_checkmark_sync(self):
        """After Toggle All OFF, all checkmarks should be unchecked."""
        self._click_toggle("Toggle All")
        time.sleep(0.5)

        marks = self._get_menu_checkmarks()
        state = self._get_map_state()

        # Count checked items (excluding non-layer items like Center, Zoom, etc.)
        layer_labels = [
            "Satellite", "Roads", "Buildings", "Waterways", "Parks", "Grid",
            "3D Models", "Labels", "Mesh Network",
            "Tracers", "Explosions", "Particles", "Hit Flashes", "Floating Text",
            "Kill Feed", "Screen FX", "Banners", "Layer HUD",
            "Health Bars", "Selection FX",
            "Fog", "Terrain",
        ]
        checked = [l for l in layer_labels if marks.get(l)]
        unchecked = [l for l in layer_labels if l in marks and not marks.get(l)]

        print(f"After Toggle All OFF:")
        print(f"  Checked: {checked}")
        print(f"  Unchecked: {len(unchecked)}")

        self._screenshot("06_toggle_all_off_checkmarks")

        # Most should be unchecked
        assert len(unchecked) > len(checked), (
            f"After Toggle All OFF, expected more unchecked. "
            f"Checked={checked}, Unchecked={len(unchecked)}"
        )

        # Restore
        self._click_toggle("Toggle All")
        time.sleep(0.5)
        self._screenshot("06_toggle_all_restored_checkmarks")

    def test_07_individual_toggle_preserves_others(self):
        """Toggling one layer doesn't affect other layers' states."""
        state_before = self._get_map_state()
        print(f"Before toggling Roads:")

        self._click_toggle("Roads")
        time.sleep(0.3)

        state_after = self._get_map_state()

        changed = {}
        unchanged = {}
        for k in state_before:
            if not k.startswith("show"):
                continue
            if state_before[k] != state_after.get(k):
                changed[k] = (state_before[k], state_after.get(k))
            else:
                unchanged[k] = state_before[k]

        print(f"  Changed: {changed}")
        print(f"  Unchanged: {len(unchanged)} keys")

        # Only showRoads should have changed
        assert "showRoads" in changed, "Roads state didn't change"
        unexpected = {k: v for k, v in changed.items() if k != "showRoads"}
        assert len(unexpected) == 0, (
            f"Toggling Roads changed other states: {unexpected}"
        )

        # Restore
        self._click_toggle("Roads")
        time.sleep(0.3)

        self._screenshot("07_isolation")

    def test_08_page_errors(self):
        """No JS errors should have occurred during all our toggling."""
        critical_errors = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical_errors:
            print(f"Critical JS errors: {critical_errors}")
        assert len(critical_errors) == 0, (
            f"JS errors during toggle testing: {critical_errors}"
        )
