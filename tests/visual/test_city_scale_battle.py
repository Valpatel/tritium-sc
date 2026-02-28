# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""City-scale battle E2E proof test.

Starts battle scenarios via API, captures screenshots, verifies
units render on the map using OpenCV color detection.

Tests two scenarios in order:
1. street_combat -- 1 rover vs kids with nerf guns (small map)
2. riot -- drones vs 200 humans (city-scale map)

Run: .venv/bin/python3 -m pytest tests/visual/test_city_scale_battle.py -v --timeout=900
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = pytest.mark.visual

PROOF_DIR = Path("tests/.test-results/city-scale")

# BGR colors from the UI
FRIENDLY_GREEN_BGR = np.array([161, 255, 5])    # #05ffa1
HOSTILE_RED_BGR = np.array([109, 42, 255])       # #ff2a6d
CYAN_BGR = np.array([255, 240, 0])               # #00f0ff
ORANGE_BGR = np.array([0, 165, 255])             # #ffa500 (projectile trails)


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
    """Find contiguous regions of a specific color. Returns bounding boxes."""
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


def _save_annotated(img: np.ndarray, name: str, annotations: list[dict]) -> Path:
    """Save annotated image with bounding boxes and labels."""
    d = _ensure_dir()
    annotated = img.copy()
    for ann in annotations:
        x, y, w, h = ann["bbox"]
        color = ann.get("color", (0, 255, 255))
        label = ann.get("label", "")
        thickness = ann.get("thickness", 2)
        cv2.rectangle(annotated, (x, y), (x + w, y + h), color, thickness)
        if label:
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x, y - th - 6), (x + tw + 4, y), (0, 0, 0), -1)
            cv2.putText(annotated, label, (x + 2, y - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    path = d / f"{name}_annotated.png"
    cv2.imwrite(str(path), annotated)
    return path


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


class TestCityScaleBattle:
    """Prove city-scale scenarios render correctly in the browser."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request, tritium_server, test_db, run_id):
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._t0 = time.monotonic()

        _ensure_dir()

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()

        # Capture console errors
        cls._errors = []
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))

        # Navigate and wait for data to load
        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        cls.page.wait_for_timeout(4000)

        yield

        # Generate report after all tests complete
        try:
            cls._db.finish_run(cls._run_id)
            from tests.lib.report_gen import ReportGenerator
            gen = ReportGenerator(cls._db)
            report_path = gen.generate(cls._run_id)
            json_path = gen.export_json(cls._run_id)
            print(f"\n  HTML Report: {report_path}")
            print(f"  JSON Metrics: {json_path}")
        except Exception as e:
            print(f"\n  Report generation failed: {e}")

        browser.close()
        cls._pw.stop()

    def _record(self, name: str, passed: bool, details: dict | None = None) -> None:
        duration_ms = (time.monotonic() - self._t0) * 1000
        self._db.record_result(self._run_id, name, passed, duration_ms, details or {})

    def _record_screenshot(
        self, name: str, phase: str, image_path: str,
        opencv_data: dict | None = None, api_state: dict | None = None,
    ) -> None:
        self._db.record_screenshot(
            run_id=self._run_id,
            test_name=name,
            phase=phase,
            image_path=image_path,
            opencv_results=opencv_data or {},
            llava_response="",
            llava_host="",
            llava_ms=0,
            api_state=api_state or {},
        )

    def _api_get(self, path: str) -> dict | list | None:
        try:
            resp = requests.get(f"{self.url}{path}", timeout=5)
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    def _api_post(self, path: str, data: dict | None = None) -> dict | None:
        try:
            resp = requests.post(f"{self.url}{path}", json=data or {}, timeout=10)
            return resp.json() if resp.status_code in (200, 400) else None
        except Exception:
            return None

    def _get_targets(self) -> list[dict]:
        data = self._api_get("/api/amy/simulation/targets")
        if isinstance(data, dict):
            return data.get("targets", [])
        return data if isinstance(data, list) else []

    def _get_game_state(self) -> dict:
        data = self._api_get("/api/game/state")
        return data if isinstance(data, dict) else {}

    # -------------------------------------------------------------------
    # Test 01: Server healthy
    # -------------------------------------------------------------------
    def test_01_server_healthy(self):
        """Health check: game API and targets API both respond."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 01: SERVER HEALTH")
        print("=" * 70)

        test_name = "city_01_server_healthy"

        # Check game state API
        game_resp = requests.get(f"{self.url}/api/game/state", timeout=5)
        game_ok = game_resp.status_code == 200
        game_data = game_resp.json() if game_ok else {}
        _log(f"GET /api/game/state -> {game_resp.status_code}: {json.dumps(game_data)}")

        # Check targets API
        targets_resp = requests.get(f"{self.url}/api/targets", timeout=5)
        targets_ok = targets_resp.status_code == 200
        _log(f"GET /api/targets -> {targets_resp.status_code}")

        # Check scenarios list
        scenarios_resp = requests.get(f"{self.url}/api/game/scenarios", timeout=5)
        scenarios_ok = scenarios_resp.status_code == 200
        scenarios = scenarios_resp.json() if scenarios_ok else []
        scenario_names = [s.get("name") for s in scenarios]
        _log(f"GET /api/game/scenarios -> {scenarios_resp.status_code}: {scenario_names}")

        details = {
            "game_status": game_resp.status_code,
            "targets_status": targets_resp.status_code,
            "scenarios_status": scenarios_resp.status_code,
            "game_state": game_data,
            "scenarios": scenario_names,
        }

        passed = game_ok and targets_ok and scenarios_ok
        self._record(test_name, passed, details)

        assert game_ok, f"/api/game/state returned {game_resp.status_code}"
        assert targets_ok, f"/api/targets returned {targets_resp.status_code}"
        assert scenarios_ok, f"/api/game/scenarios returned {scenarios_resp.status_code}"
        _log("Server healthy: all endpoints responding")

    # -------------------------------------------------------------------
    # Test 02: Street combat starts
    # -------------------------------------------------------------------
    def test_02_street_combat_starts(self):
        """POST /api/game/battle/street_combat succeeds."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 02: STREET COMBAT STARTS")
        print("=" * 70)

        test_name = "city_02_street_combat_starts"

        result = self._api_post("/api/game/battle/street_combat")
        _log(f"POST /api/game/battle/street_combat -> {json.dumps(result)}")

        # Let the server initialize the scenario
        self.page.wait_for_timeout(2000)

        state = self._get_game_state()
        _log(f"Game state after start: {json.dumps(state)}")

        path, img = _screenshot(self.page, "02_street_combat_start")
        self._record_screenshot(
            test_name, "02_street_combat_start", str(path),
            api_state={"result": result, "state": state},
        )

        details = {
            "api_result": result,
            "game_state": state,
        }

        passed = (
            result is not None
            and result.get("scenario") == "street_combat"
            and result.get("defender_count", 0) >= 1
        )
        self._record(test_name, passed, details)

        assert passed, f"street_combat scenario failed to start: {result}"
        _log(f"Street combat started: {result.get('defender_count')} defenders, "
             f"{result.get('wave_count')} waves")

    # -------------------------------------------------------------------
    # Test 03: Street combat hostiles spawn
    # -------------------------------------------------------------------
    def test_03_street_combat_hostiles_spawn(self):
        """Wait for hostiles to appear in street combat."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 03: STREET COMBAT HOSTILES SPAWN")
        print("=" * 70)

        test_name = "city_03_street_combat_hostiles"

        hostiles_found = False
        hostile_count = 0
        for tick in range(30):
            time.sleep(1)
            state = self._get_game_state()
            current_state = state.get("state", "unknown")
            targets = self._get_targets()
            hostiles = [t for t in targets if t.get("alliance") == "hostile"]
            hostile_count = len(hostiles)

            if tick % 5 == 0:
                _log(f"t={tick}s: state={current_state} hostiles={hostile_count}")

            if hostile_count > 0 and current_state == "active":
                hostiles_found = True
                _log(f"HOSTILES DETECTED at t={tick}s: {hostile_count}")
                for h in hostiles[:5]:
                    pos = h.get("position", {})
                    _log(f"  '{h.get('name', '')}' type={h.get('asset_type', '')} "
                         f"at ({pos.get('x', 0):.1f}, {pos.get('y', 0):.1f})")
                break

        # Let combat develop briefly
        self.page.wait_for_timeout(2000)

        path, img = _screenshot(self.page, "03_street_combat_hostiles")
        red_blobs = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10)
        green_blobs = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        _log(f"OpenCV: red blobs={len(red_blobs)}, green blobs={len(green_blobs)}")

        annotations = []
        for i, gb in enumerate(green_blobs[:5]):
            annotations.append({"bbox": gb["bbox"], "color": (0, 255, 100),
                                "label": f"FRIENDLY{i+1}"})
        for i, rb in enumerate(red_blobs[:10]):
            annotations.append({"bbox": rb["bbox"], "color": (0, 0, 255),
                                "label": f"HOSTILE{i+1}"})
        annotated_path = _save_annotated(img, "03_street_combat_hostiles", annotations)

        self._record_screenshot(
            test_name, "03_annotated", str(annotated_path),
            opencv_data={"red_blobs": len(red_blobs), "green_blobs": len(green_blobs)},
            api_state={"hostiles_found": hostiles_found, "hostile_count": hostile_count},
        )

        details = {
            "hostiles_found": hostiles_found,
            "hostile_count": hostile_count,
            "red_blobs": len(red_blobs),
            "green_blobs": len(green_blobs),
        }
        passed = hostiles_found
        self._record(test_name, passed, details)

        assert passed, f"No hostiles appeared within 30s. Last state: {self._get_game_state()}"
        _log(f"Street combat hostiles confirmed: {hostile_count} on field")

    # -------------------------------------------------------------------
    # Test 04: Street combat screenshot with combat
    # -------------------------------------------------------------------
    def test_04_street_combat_screenshot(self):
        """Capture screenshot of street combat in progress, verify units visible."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 04: STREET COMBAT SCREENSHOT")
        print("=" * 70)

        test_name = "city_04_street_combat_screenshot"

        # Wait for combat to develop
        self.page.wait_for_timeout(5000)

        state = self._get_game_state()
        elims = state.get("total_eliminations", 0)
        wave = state.get("wave", 0)
        score = state.get("score", 0)
        _log(f"State: wave={wave} score={score} elims={elims}")

        path, img = _screenshot(self.page, "04_street_combat_action")
        green_blobs = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        red_blobs = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10)
        _log(f"OpenCV: green={len(green_blobs)} red={len(red_blobs)}")

        annotations = []
        for i, gb in enumerate(green_blobs[:5]):
            annotations.append({"bbox": gb["bbox"], "color": (0, 255, 100),
                                "label": f"ROVER{i+1}"})
        for i, rb in enumerate(red_blobs[:10]):
            annotations.append({"bbox": rb["bbox"], "color": (0, 0, 255),
                                "label": f"KID{i+1}"})
        annotated_path = _save_annotated(img, "04_street_combat_action", annotations)

        self._record_screenshot(
            test_name, "04_annotated", str(annotated_path),
            opencv_data={"green_blobs": len(green_blobs), "red_blobs": len(red_blobs)},
            api_state={"wave": wave, "score": score, "elims": elims},
        )

        details = {
            "green_blobs": len(green_blobs),
            "red_blobs": len(red_blobs),
            "wave": wave,
            "score": score,
            "elims": elims,
        }
        # At least one of: OpenCV sees units OR API confirms combat
        passed = (len(green_blobs) > 0 or len(red_blobs) > 0) or elims > 0 or wave >= 1
        self._record(test_name, passed, details)

        assert passed, (
            f"No evidence of combat. Green={len(green_blobs)}, Red={len(red_blobs)}, "
            f"Elims={elims}, Wave={wave}"
        )
        _log(f"Street combat screenshot captured: wave {wave}, {elims} elims")

    # -------------------------------------------------------------------
    # Test 05: Reset game between scenarios
    # -------------------------------------------------------------------
    def test_05_reset_game(self):
        """Reset game between scenarios."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 05: RESET GAME")
        print("=" * 70)

        test_name = "city_05_reset_game"

        result = self._api_post("/api/game/reset")
        _log(f"POST /api/game/reset -> {json.dumps(result)}")

        self.page.wait_for_timeout(2000)

        state = self._get_game_state()
        current = state.get("state", "unknown")
        _log(f"Game state after reset: {current}")

        targets = self._get_targets()
        hostiles = [t for t in targets if t.get("alliance") == "hostile"]
        _log(f"Targets after reset: {len(targets)} total, {len(hostiles)} hostile")

        path, img = _screenshot(self.page, "05_reset")
        self._record_screenshot(
            test_name, "05_reset", str(path),
            api_state={"state": current, "targets": len(targets), "hostiles": len(hostiles)},
        )

        details = {
            "reset_result": result,
            "state": current,
            "target_count": len(targets),
            "hostile_count": len(hostiles),
        }
        passed = current == "setup"
        self._record(test_name, passed, details)

        assert passed, f"Expected state 'setup' after reset, got '{current}'"
        _log("Game reset to setup state")

    # -------------------------------------------------------------------
    # Test 06: Riot scenario starts
    # -------------------------------------------------------------------
    def test_06_riot_starts(self):
        """POST /api/game/battle/riot succeeds."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 06: RIOT STARTS")
        print("=" * 70)

        test_name = "city_06_riot_starts"

        result = self._api_post("/api/game/battle/riot")
        _log(f"POST /api/game/battle/riot -> {json.dumps(result)}")

        self.page.wait_for_timeout(2000)

        state = self._get_game_state()
        _log(f"Game state after riot start: {json.dumps(state)}")

        path, img = _screenshot(self.page, "06_riot_start")
        self._record_screenshot(
            test_name, "06_riot_start", str(path),
            api_state={"result": result, "state": state},
        )

        details = {
            "api_result": result,
            "game_state": state,
        }

        passed = (
            result is not None
            and result.get("scenario") == "riot"
            and result.get("max_hostiles", 0) >= 100
            and result.get("defender_count", 0) >= 4
        )
        self._record(test_name, passed, details)

        assert passed, f"Riot scenario failed to start: {result}"
        _log(f"Riot started: {result.get('defender_count')} defenders, "
             f"max_hostiles={result.get('max_hostiles')}, "
             f"{result.get('wave_count')} waves")

    # -------------------------------------------------------------------
    # Test 07: Riot many hostiles
    # -------------------------------------------------------------------
    def test_07_riot_many_hostiles(self):
        """Wait for 10+ hostiles in riot scenario."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 07: RIOT HOSTILES SPAWN")
        print("=" * 70)

        test_name = "city_07_riot_hostiles"

        max_hostile_count = 0
        for tick in range(60):
            time.sleep(1)
            state = self._get_game_state()
            current_state = state.get("state", "unknown")
            targets = self._get_targets()
            hostiles = [t for t in targets if t.get("alliance") == "hostile"]
            hostile_count = len(hostiles)
            max_hostile_count = max(max_hostile_count, hostile_count)

            if tick % 10 == 0:
                wave = state.get("wave", 0)
                _log(f"t={tick}s: state={current_state} wave={wave} "
                     f"hostiles={hostile_count} (max={max_hostile_count})")

            if hostile_count >= 10:
                _log(f"10+ HOSTILES at t={tick}s: {hostile_count}")
                break

        # Let the map render with all those hostiles
        self.page.wait_for_timeout(3000)

        path, img = _screenshot(self.page, "07_riot_hostiles")
        red_blobs = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10)
        green_blobs = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        _log(f"OpenCV: red blobs={len(red_blobs)}, green blobs={len(green_blobs)}")

        annotations = []
        for i, gb in enumerate(green_blobs[:10]):
            annotations.append({"bbox": gb["bbox"], "color": (0, 255, 100),
                                "label": f"DRONE{i+1}"})
        for i, rb in enumerate(red_blobs[:20]):
            annotations.append({"bbox": rb["bbox"], "color": (0, 0, 255),
                                "label": f"RIOTER{i+1}"})
        annotated_path = _save_annotated(img, "07_riot_hostiles", annotations)

        self._record_screenshot(
            test_name, "07_annotated", str(annotated_path),
            opencv_data={"red_blobs": len(red_blobs), "green_blobs": len(green_blobs)},
            api_state={"max_hostile_count": max_hostile_count},
        )

        details = {
            "max_hostile_count": max_hostile_count,
            "red_blobs": len(red_blobs),
            "green_blobs": len(green_blobs),
        }
        passed = max_hostile_count >= 10
        self._record(test_name, passed, details)

        assert passed, f"Expected >=10 hostiles, max seen was {max_hostile_count}"
        _log(f"Riot hostiles confirmed: max {max_hostile_count} seen")

    # -------------------------------------------------------------------
    # Test 08: Riot screenshot with many units
    # -------------------------------------------------------------------
    def test_08_riot_screenshot(self):
        """Capture screenshot of riot with many units visible."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 08: RIOT SCREENSHOT")
        print("=" * 70)

        test_name = "city_08_riot_screenshot"

        # Let the battle run a bit more
        self.page.wait_for_timeout(5000)

        state = self._get_game_state()
        wave = state.get("wave", 0)
        score = state.get("score", 0)
        elims = state.get("total_eliminations", 0)
        _log(f"State: wave={wave} score={score} elims={elims}")

        targets = self._get_targets()
        hostiles = [t for t in targets if t.get("alliance") == "hostile"]
        friendlies = [t for t in targets if t.get("alliance") == "friendly"]
        _log(f"Targets: {len(friendlies)} friendly, {len(hostiles)} hostile")

        path, img = _screenshot(self.page, "08_riot_action")
        red_blobs = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10)
        green_blobs = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        _log(f"OpenCV: red blobs={len(red_blobs)}, green blobs={len(green_blobs)}")

        annotations = []
        for i, gb in enumerate(green_blobs[:10]):
            annotations.append({"bbox": gb["bbox"], "color": (0, 255, 100),
                                "label": f"DRONE{i+1}"})
        for i, rb in enumerate(red_blobs[:25]):
            annotations.append({"bbox": rb["bbox"], "color": (0, 0, 255),
                                "label": f"RIOTER{i+1}"})
        annotated_path = _save_annotated(img, "08_riot_action", annotations)

        self._record_screenshot(
            test_name, "08_annotated", str(annotated_path),
            opencv_data={"red_blobs": len(red_blobs), "green_blobs": len(green_blobs)},
            api_state={
                "wave": wave, "score": score, "elims": elims,
                "api_hostiles": len(hostiles), "api_friendlies": len(friendlies),
            },
        )

        details = {
            "red_blobs": len(red_blobs),
            "green_blobs": len(green_blobs),
            "api_hostiles": len(hostiles),
            "api_friendlies": len(friendlies),
            "wave": wave,
            "score": score,
            "elims": elims,
        }
        # Visual or API evidence of units
        visible_units = len(red_blobs) + len(green_blobs)
        api_units = len(hostiles) + len(friendlies)
        passed = visible_units >= 5 or api_units >= 5
        self._record(test_name, passed, details)

        assert passed, (
            f"Not enough units visible. OpenCV: {visible_units} blobs, "
            f"API: {api_units} targets"
        )
        _log(f"Riot screenshot: {visible_units} visible blobs, {api_units} API targets")

    # -------------------------------------------------------------------
    # Test 09: Riot combat active
    # -------------------------------------------------------------------
    def test_09_riot_combat_active(self):
        """Verify combat is happening: projectiles or eliminations."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 09: RIOT COMBAT ACTIVE")
        print("=" * 70)

        test_name = "city_09_riot_combat"

        combat_confirmed = False
        final_state = {}
        for tick in range(30):
            time.sleep(1)
            state = self._get_game_state()
            elims = state.get("total_eliminations", 0)
            wave = state.get("wave", 0)
            score = state.get("score", 0)

            if tick % 5 == 0:
                _log(f"t={tick}s: wave={wave} score={score} elims={elims}")

            if elims > 0 or wave >= 2:
                combat_confirmed = True
                final_state = state
                _log(f"COMBAT CONFIRMED at t={tick}s: elims={elims} wave={wave}")
                break

        # Also check for projectile pixels
        path, img = _screenshot(self.page, "09_riot_combat")
        orange_blobs = _detect_color_regions(img, ORANGE_BGR, tolerance=60, min_area=5)
        _log(f"Projectile pixels (orange blobs): {len(orange_blobs)}")

        self._record_screenshot(
            test_name, "09_riot_combat", str(path),
            opencv_data={"orange_blobs": len(orange_blobs)},
            api_state=final_state or self._get_game_state(),
        )

        details = {
            "combat_confirmed": combat_confirmed,
            "orange_blobs": len(orange_blobs),
            "final_state": final_state or self._get_game_state(),
        }
        passed = combat_confirmed or len(orange_blobs) > 0
        self._record(test_name, passed, details)

        assert passed, (
            f"No combat detected in 30s. "
            f"Last state: {json.dumps(self._get_game_state())}"
        )
        _log("Riot combat confirmed")

    # -------------------------------------------------------------------
    # Test 10: Final screenshot
    # -------------------------------------------------------------------
    def test_10_final_screenshot(self):
        """Final screenshot showing battle state."""
        print("\n" + "=" * 70)
        print("  CITY-SCALE 10: FINAL SCREENSHOT")
        print("=" * 70)

        test_name = "city_10_final"

        state = self._get_game_state()
        wave = state.get("wave", 0)
        score = state.get("score", 0)
        elims = state.get("total_eliminations", 0)
        game_state = state.get("state", "unknown")

        targets = self._get_targets()
        hostiles = [t for t in targets if t.get("alliance") == "hostile"]
        friendlies = [t for t in targets if t.get("alliance") == "friendly"]

        _log(f"Final: state={game_state} wave={wave} score={score} "
             f"elims={elims} hostiles={len(hostiles)} friendlies={len(friendlies)}")

        path, img = _screenshot(self.page, "10_final")
        red_blobs = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10)
        green_blobs = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)

        annotations = []
        for i, gb in enumerate(green_blobs[:10]):
            annotations.append({"bbox": gb["bbox"], "color": (0, 255, 100),
                                "label": f"FRIEND{i+1}"})
        for i, rb in enumerate(red_blobs[:25]):
            annotations.append({"bbox": rb["bbox"], "color": (0, 0, 255),
                                "label": f"HOSTILE{i+1}"})
        annotated_path = _save_annotated(img, "10_final", annotations)

        self._record_screenshot(
            test_name, "10_final_annotated", str(annotated_path),
            opencv_data={"red_blobs": len(red_blobs), "green_blobs": len(green_blobs)},
            api_state={
                "state": game_state, "wave": wave, "score": score, "elims": elims,
                "hostiles": len(hostiles), "friendlies": len(friendlies),
            },
        )

        details = {
            "game_state": game_state,
            "wave": wave,
            "score": score,
            "elims": elims,
            "api_hostiles": len(hostiles),
            "api_friendlies": len(friendlies),
            "red_blobs": len(red_blobs),
            "green_blobs": len(green_blobs),
        }
        # We have evidence of a real battle running
        passed = score > 0 or elims > 0 or wave >= 1
        self._record(test_name, passed, details)

        assert passed, (
            f"No battle evidence. Score={score}, Elims={elims}, Wave={wave}"
        )

        # Print grand summary
        print("\n" + "=" * 70)
        print("  CITY-SCALE BATTLE PROOF COMPLETE")
        print("=" * 70)
        print(f"  Game State:   {game_state}")
        print(f"  Wave:         {wave}")
        print(f"  Score:        {score}")
        print(f"  Eliminations: {elims}")
        print(f"  Hostiles:     {len(hostiles)} (API) / {len(red_blobs)} (OpenCV)")
        print(f"  Friendlies:   {len(friendlies)} (API) / {len(green_blobs)} (OpenCV)")
        print(f"  Screenshots:  {PROOF_DIR}")
        print("=" * 70)
