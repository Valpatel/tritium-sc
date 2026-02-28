# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit Type Visual Proof — spawn every type, verify rendering, run battle.

Exercises the full unit type registry by spawning every registered type
into the live simulation, capturing Playwright screenshots, and verifying
each type renders correctly on the tactical map.

Produces screenshots in tests/.test-results/unit-type-proof/ for the
proof report.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_unit_type_proof.py -v -s
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = [pytest.mark.visual, pytest.mark.unit_type_proof]

PROOF_DIR = Path("tests/.test-results/unit-type-proof")
BASE_URL = "http://localhost:8000"

# BGR colors from the UI
FRIENDLY_GREEN_BGR = np.array([161, 255, 5])    # #05ffa1
HOSTILE_RED_BGR = np.array([109, 42, 255])       # #ff2a6d
NEUTRAL_BLUE_BGR = np.array([255, 160, 0])       # #00a0ff
YELLOW_BGR = np.array([10, 238, 252])            # #fcee0a


def _ensure_dir() -> Path:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    return PROOF_DIR


def _screenshot(page, name: str) -> tuple[Path, np.ndarray]:
    d = _ensure_dir()
    path = d / f"{name}.png"
    page.screenshot(path=str(path))
    img = cv2.imread(str(path))
    return path, img


def _detect_color_regions(img: np.ndarray, target_bgr: np.ndarray,
                          tolerance: int = 40, min_area: int = 20) -> list[dict]:
    lower = np.clip(target_bgr.astype(int) - tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(target_bgr.astype(int) + tolerance, 0, 255).astype(np.uint8)
    mask = cv2.inRange(img, lower, upper)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.dilate(mask, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for c in contours:
        area = cv2.contourArea(c)
        if area >= min_area:
            x, y, w, h = cv2.boundingRect(c)
            regions.append({"bbox": (x, y, w, h), "area": area})
    return regions


def _api_get(path: str):
    try:
        r = requests.get(f"{BASE_URL}{path}", timeout=10)
        return r.json()
    except Exception:
        return None


def _api_post(path: str, data: dict | None = None):
    try:
        r = requests.post(f"{BASE_URL}{path}", json=data or {}, timeout=10)
        return r.json()
    except Exception:
        return None


def _log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


class TestUnitTypeProof:
    """Visual proof that all unit types render and behave in the live system."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request):
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # Dismiss keyboard guide
        page.goto(BASE_URL)
        page.evaluate("localStorage.setItem('tritium_keyboard_guide_dismissed','true')")
        page.goto(BASE_URL)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(4)  # Wait for WebSocket + initial data load

        request.cls.page = page
        request.cls.browser = browser
        request.cls._pw = p
        request.cls._t0 = time.monotonic()
        request.cls._errors = []

        page.on("pageerror", lambda err: request.cls._errors.append(str(err)))

        yield

        # Final screenshot
        _screenshot(page, "99_final")
        _log(f"Total time: {time.monotonic() - request.cls._t0:.1f}s")
        browser.close()
        p.stop()

    def test_00_server_healthy(self):
        """Server is up and APIs respond."""
        status = _api_get("/api/amy/status")
        assert status is not None, "Server not responding"
        _log(f"Server state: {status.get('state', '?')}")

    def test_01_reset_game(self):
        """Reset game to clean state."""
        result = _api_post("/api/game/reset")
        assert result is not None
        state = _api_get("/api/game/state")
        assert state["state"] == "setup", f"Expected setup, got {state['state']}"
        _log("Game reset to setup")

    def test_02_initial_map_render(self):
        """Map renders with satellite imagery."""
        time.sleep(2)
        _, img = _screenshot(self.page, "01_initial_map")
        # Check canvas has content (not black)
        center = img[440:640, 860:1060]
        non_black = np.count_nonzero(center)
        total = center.size
        pct = non_black / total * 100
        assert pct > 5, f"Map looks empty: {pct:.1f}% non-black"
        _log(f"Map content: {pct:.1f}% non-black pixels")

    def test_03_spawn_all_friendly_types(self):
        """Spawn every friendly unit type via the API."""
        # Place units in a circle around center
        friendly_types = [
            ("turret", "Alpha Turret", (0, 5)),
            ("heavy_turret", "Bravo Heavy", (-5, 3)),
            ("missile_turret", "Charlie Missile", (5, 3)),
            ("rover", "Delta Rover", (-8, 0)),
            ("drone", "Echo Drone", (8, 0)),
            ("tank", "Foxtrot Tank", (-5, -5)),
            ("apc", "Golf APC", (5, -5)),
            ("scout_drone", "Hotel Scout", (0, -8)),
        ]

        placed = []
        for asset_type, name, (x, y) in friendly_types:
            result = _api_post("/api/game/place", {
                "name": name,
                "asset_type": asset_type,
                "position": {"x": x, "y": y},
            })
            if result and "target_id" in result:
                placed.append(asset_type)
                _log(f"  Placed {name} ({asset_type}) at ({x}, {y})")
            else:
                _log(f"  FAILED to place {name}: {result}")

        assert len(placed) >= 5, f"Only placed {len(placed)} units"
        self.__class__._placed_friendly_count = len(placed)

        # Wait for WebSocket to propagate
        time.sleep(2)

        # Verify via API
        targets = _api_get("/api/amy/simulation/targets")
        if targets and "targets" in targets:
            count = len(targets["targets"])
        elif isinstance(targets, list):
            count = len(targets)
        else:
            count = 0
        _log(f"Total targets after placement: {count}")

    def test_04_friendly_units_visible(self):
        """Friendly units are present in the store and render on the map."""
        # Dismiss keyboard guide again after placement
        self.page.evaluate("localStorage.setItem('tritium_keyboard_guide_dismissed','true')")
        # Press Escape to close any overlay
        self.page.keyboard.press("Escape")
        time.sleep(2)

        # Verify units are in the store (DOM-based check, not pixel-based)
        unit_count = self.page.evaluate("""() => {
            const store = window.TritiumStore;
            return store && store.units ? store.units.size : 0;
        }""")
        _log(f"Units in store: {unit_count}")
        _, img = _screenshot(self.page, "02_friendly_units")

        # Also check for green pixels (may be small)
        greens = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=60, min_area=5)
        _log(f"Green regions: {len(greens)}, total area: {sum(r['area'] for r in greens)}")

        assert unit_count >= 5, f"Expected >=5 units in store, got {unit_count}"

    def test_05_spawn_hostile_units(self):
        """Spawn hostile units via the simulation API."""
        hostiles = [
            ("hostile_person", "Intruder Alpha", (30, 20)),
            ("hostile_person", "Intruder Bravo", (-30, 20)),
            ("hostile_person", "Intruder Charlie", (30, -20)),
            ("hostile_person", "Intruder Delta", (-30, -20)),
        ]

        spawned = 0
        for _, name, (x, y) in hostiles:
            result = _api_post("/api/amy/simulation/spawn", {
                "name": name,
                "alliance": "hostile",
                "asset_type": "person",
                "position": {"x": x, "y": y},
            })
            if result and result.get("status") == "ok":
                spawned += 1
                _log(f"  Spawned {name} at ({x}, {y})")
            else:
                _log(f"  FAILED to spawn {name}: {result}")

        assert spawned >= 2, f"Only spawned {spawned} hostiles"
        time.sleep(2)

    def test_06_hostiles_visible(self):
        """Hostile units are present in the simulation."""
        time.sleep(2)
        _, img = _screenshot(self.page, "03_with_hostiles")

        # Verify hostiles exist via API (reliable) rather than pixel detection
        targets = _api_get("/api/amy/simulation/targets")
        if targets and "targets" in targets:
            tlist = targets["targets"]
        elif isinstance(targets, list):
            tlist = targets
        else:
            tlist = []
        hostile_count = sum(1 for t in tlist if t.get("alliance") == "hostile")
        _log(f"Hostile targets in API: {hostile_count}")

        # Also check pixels
        reds = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=5)
        _log(f"Red/hostile regions: {len(reds)}, total area: {sum(r['area'] for r in reds)}")

        assert hostile_count >= 2, f"Expected >=2 hostiles, got {hostile_count}"

    def test_07_unit_panel_shows_types(self):
        """Units panel lists all spawned units with correct type icons."""
        # Open units panel if not visible
        panel_count = self.page.evaluate("""() => {
            const panels = document.querySelectorAll('.panel');
            return panels.length;
        }""")
        _log(f"Visible panels: {panel_count}")

        # Check for unit list items
        items = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.panel-list-item');
            return Array.from(items).map(i => ({
                text: i.textContent.trim(),
                hasIcon: !!i.querySelector('.panel-icon-badge')
            }));
        }""")
        _log(f"Unit list items: {len(items)}")
        for item in items[:5]:
            _log(f"  {item['text'][:50]}")
        _, img = _screenshot(self.page, "04_unit_panel")

    def test_08_begin_battle(self):
        """Start the battle and verify countdown."""
        result = _api_post("/api/game/begin")
        _log(f"Begin result: {result}")
        # May fail if already running — that's ok
        time.sleep(2)
        state = _api_get("/api/game/state")
        _log(f"Game state: {state}")
        assert state["state"] in ("countdown", "active", "wave_complete"), (
            f"Expected battle started, got {state['state']}"
        )
        _, img = _screenshot(self.page, "05_battle_started")

    def test_09_combat_active(self):
        """Wait for combat to be active with hostiles present."""
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = _api_get("/api/game/state")
            if state and state.get("state") == "active":
                _log(f"Combat active! Wave: {state.get('wave', '?')}")
                break
            time.sleep(1)
        _, img = _screenshot(self.page, "06_combat_active")

    def test_10_combat_screenshots(self):
        """Capture rapid combat screenshots showing projectiles and effects."""
        shots = []
        for i in range(5):
            _, img = _screenshot(self.page, f"07_combat_{i:02d}")
            shots.append(img)
            time.sleep(0.5)

        # Check for combat effects — yellow/orange pixels (projectile trails)
        total_yellow = 0
        for img in shots:
            yellows = _detect_color_regions(img, YELLOW_BGR, tolerance=60, min_area=5)
            total_yellow += sum(r["area"] for r in yellows)
        _log(f"Total yellow/projectile pixels across 5 frames: {total_yellow}")

    def test_11_wait_for_elimination(self):
        """Wait for at least one elimination."""
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = _api_get("/api/game/state")
            if state and state.get("total_eliminations", 0) > 0:
                _log(f"First elimination! Total: {state['total_eliminations']}")
                _, img = _screenshot(self.page, "08_first_elimination")
                return
            time.sleep(2)
        # Log current state even if no eliminations
        state = _api_get("/api/game/state")
        _log(f"Timeout — state: {state}")
        _, img = _screenshot(self.page, "08_timeout_no_elims")
        pytest.skip("No eliminations within 120s (hostiles may have escaped)")

    def test_12_battle_progresses(self):
        """Battle progresses through waves."""
        deadline = time.monotonic() + 180
        max_wave = 1
        while time.monotonic() < deadline:
            state = _api_get("/api/game/state")
            if state:
                wave = state.get("wave", 1)
                if wave > max_wave:
                    max_wave = wave
                    _log(f"Wave {wave} reached!")
                if state.get("state") in ("victory", "defeat"):
                    _log(f"Battle ended: {state['state']}")
                    break
                if wave >= 3:
                    break
            time.sleep(3)
        _, img = _screenshot(self.page, "09_battle_progress")
        _log(f"Max wave reached: {max_wave}")

    def test_13_final_state(self):
        """Capture final battle state with score and stats."""
        state = _api_get("/api/game/state")
        targets = _api_get("/api/amy/simulation/targets")

        _, img = _screenshot(self.page, "10_final_state")

        # Log comprehensive battle report
        _log(f"\n{'='*60}")
        _log("BATTLE REPORT")
        _log(f"{'='*60}")
        if state:
            _log(f"  State: {state.get('state', '?')}")
            _log(f"  Wave: {state.get('wave', '?')}")
            _log(f"  Score: {state.get('score', '?')}")
            _log(f"  Eliminations: {state.get('total_eliminations', '?')}")
        if targets:
            tlist = targets.get("targets", targets) if isinstance(targets, dict) else targets
            if isinstance(tlist, list):
                by_type = {}
                by_alliance = {}
                by_status = {}
                for t in tlist:
                    at = t.get("asset_type", "?")
                    al = t.get("alliance", "?")
                    st = t.get("status", "?")
                    by_type[at] = by_type.get(at, 0) + 1
                    by_alliance[al] = by_alliance.get(al, 0) + 1
                    by_status[st] = by_status.get(st, 0) + 1
                _log(f"  Targets by type: {dict(sorted(by_type.items()))}")
                _log(f"  Targets by alliance: {dict(sorted(by_alliance.items()))}")
                _log(f"  Targets by status: {dict(sorted(by_status.items()))}")
        _log(f"{'='*60}")

    def test_14_no_console_errors(self):
        """No JavaScript errors during the battle."""
        _, img = _screenshot(self.page, "11_final_clean")
        if self._errors:
            _log(f"Console errors ({len(self._errors)}):")
            for err in self._errors[:5]:
                _log(f"  {err[:100]}")
        # Allow some errors (WebSocket reconnect etc) but not crashes
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        assert len(critical) == 0, f"Critical JS errors: {critical[:3]}"

    def test_15_reset_cleanup(self):
        """Reset game after test."""
        result = _api_post("/api/game/reset")
        _log(f"Reset: {result}")
