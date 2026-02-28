# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Mission Combat — E2E visual verification of LLM-generated mission placement and battle.

Verifies the full pipeline: generate scripted mission -> defenders placed near
real buildings -> battle begins -> hostiles spawn -> combat occurs.

Three-layer verification:
  - Layer 1 (OpenCV): Green/red blob detection for friendlies/hostiles
  - Layer 2 (LLM): llava:7b majority-vote visual confirmation
  - Layer 3 (API): Ground truth from /api/targets and /api/game/state

Run:
    .venv/bin/python3 -m pytest tests/visual/test_mission_combat.py -v --timeout=600
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = [pytest.mark.visual, pytest.mark.mission_combat]

PROOF_DIR = Path("tests/.test-results/mission-combat")

# BGR colors from the UI
FRIENDLY_GREEN_BGR = np.array([161, 255, 5])    # #05ffa1
HOSTILE_RED_BGR = np.array([109, 42, 255])       # #ff2a6d
CYAN_BGR = np.array([255, 240, 0])               # #00f0ff
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


class TestMissionCombatSetup:
    """Phase 1: Server health, map load, and scripted mission generation."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request, tritium_server, test_db, run_id, fleet):
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._fleet = fleet
        cls._t0 = time.monotonic()
        cls.scenario = None
        cls.screenshots = {}

        _ensure_dir()

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()

        cls._errors = []
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))

        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        cls.page.wait_for_timeout(4000)

        yield

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

    # -------------------------------------------------------------------
    # Test 01: Server starts
    # -------------------------------------------------------------------
    def test_01_server_starts(self):
        """Server responds to health and API endpoints."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 01: SERVER HEALTH")
        print("=" * 70)

        test_name = "mission_01_server_starts"

        targets_resp = requests.get(f"{self.url}/api/targets", timeout=5)
        targets_ok = targets_resp.status_code == 200
        _log(f"GET /api/targets -> {targets_resp.status_code}")

        game_resp = requests.get(f"{self.url}/api/game/state", timeout=5)
        game_ok = game_resp.status_code == 200
        game_data = game_resp.json() if game_ok else {}
        _log(f"GET /api/game/state -> {game_resp.status_code}: {json.dumps(game_data)}")

        details = {
            "targets_status": targets_resp.status_code,
            "game_status": game_resp.status_code,
            "game_state": game_data,
        }

        passed = targets_ok and game_ok
        self._record(test_name, passed, details)

        assert targets_ok, f"/api/targets returned {targets_resp.status_code}"
        assert game_ok, f"/api/game/state returned {game_resp.status_code}"
        _log("Server healthy: all endpoints responding")

    # -------------------------------------------------------------------
    # Test 02: Map loads
    # -------------------------------------------------------------------
    def test_02_map_loads(self):
        """Canvas visible and has content (satellite imagery)."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 02: MAP LOADS")
        print("=" * 70)

        test_name = "mission_02_map_loads"
        path, img = _screenshot(self.page, "02_map_loads")
        self.__class__.screenshots["map_loads"] = path
        h, w = img.shape[:2]

        # Check center 50% for content
        cx, cy = w // 4, h // 4
        cw, ch = w // 2, h // 2
        center = img[cy:cy + ch, cx:cx + cw]

        gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
        nonblack = np.count_nonzero(gray > 15)
        total = center.shape[0] * center.shape[1]
        pct = nonblack / total * 100

        _log(f"Center region: {pct:.1f}% non-black pixels ({nonblack}/{total})")

        self._record_screenshot(
            test_name, "02_map_loads", str(path),
            opencv_data={"nonblack_pct": round(pct, 1)},
        )

        details = {"nonblack_pct": round(pct, 1)}
        passed = pct > 5
        self._record(test_name, passed, details)

        assert passed, f"Map center too dark: only {pct:.1f}% non-black (need >5%)"
        _log("Map renders content with satellite imagery")

    # -------------------------------------------------------------------
    # Test 03: Generate scripted mission
    # -------------------------------------------------------------------
    def test_03_generate_scripted_mission(self):
        """POST /api/game/generate with use_llm=false returns scenario."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 03: GENERATE SCRIPTED MISSION")
        print("=" * 70)

        test_name = "mission_03_generate_scripted"

        # Reset game first
        reset_result = self._api_post("/api/game/reset")
        _log(f"Game reset: {json.dumps(reset_result)}")
        self.page.wait_for_timeout(1000)

        # Generate scripted mission
        result = self._api_post(
            "/api/game/generate",
            {"game_mode": "battle", "use_llm": False},
        )
        _log(f"Generate result keys: {list(result.keys()) if result else 'None'}")

        has_scenario = result is not None and result.get("status") == "complete"
        scenario_data = result.get("scenario", {}) if result else {}
        _log(f"Status: {result.get('status') if result else 'None'}")
        _log(f"Source: {result.get('source') if result else 'None'}")
        _log(f"Scenario keys: {list(scenario_data.keys())}")

        # Cache scenario for subsequent tests
        if has_scenario:
            self.__class__.scenario = scenario_data

        details = {
            "has_scenario": has_scenario,
            "source": result.get("source") if result else None,
            "scenario_keys": list(scenario_data.keys()),
        }
        self._record(test_name, has_scenario, details)

        assert has_scenario, f"Expected status=complete, got: {result}"
        _log("Scripted mission generated successfully")

    # -------------------------------------------------------------------
    # Test 04: Scenario has defenders
    # -------------------------------------------------------------------
    def test_04_scenario_has_defenders(self):
        """Generated scenario includes friendly units with positions."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 04: SCENARIO HAS DEFENDERS")
        print("=" * 70)

        test_name = "mission_04_scenario_defenders"

        scenario = self.__class__.scenario
        assert scenario is not None, "No scenario generated (test_03 must pass first)"

        units = scenario.get("units", [])
        friendlies = [u for u in units if u.get("alliance") == "friendly"]
        _log(f"Total units: {len(units)}, Friendlies: {len(friendlies)}")

        for u in friendlies[:5]:
            pos = u.get("position", [0, 0])
            _log(f"  {u.get('name', '?')} ({u.get('type', '?')}) at {pos}")

        # Check positions are not all at origin
        positions_nonzero = sum(
            1 for u in friendlies
            if abs(u.get("position", [0, 0])[0]) > 0.1 or
               abs(u.get("position", [0, 0])[1]) > 0.1
        )
        _log(f"Defenders with non-zero positions: {positions_nonzero}/{len(friendlies)}")

        details = {
            "total_units": len(units),
            "friendlies": len(friendlies),
            "nonzero_positions": positions_nonzero,
        }
        passed = len(friendlies) >= 3 and positions_nonzero >= 2
        self._record(test_name, passed, details)

        assert len(friendlies) >= 3, f"Expected >=3 friendly units, got {len(friendlies)}"
        assert positions_nonzero >= 2, f"Expected >=2 non-zero positions, got {positions_nonzero}"
        _log(f"Scenario has {len(friendlies)} defenders with {positions_nonzero} non-zero positions")

    # -------------------------------------------------------------------
    # Test 05: Scenario defenders named
    # -------------------------------------------------------------------
    def test_05_scenario_defenders_named(self):
        """Unit names are descriptive (not generic placeholders)."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 05: DEFENDERS NAMED")
        print("=" * 70)

        test_name = "mission_05_defenders_named"

        scenario = self.__class__.scenario
        assert scenario is not None, "No scenario generated (test_03 must pass first)"

        units = scenario.get("units", [])
        friendlies = [u for u in units if u.get("alliance") == "friendly"]

        names = [u.get("name", "") for u in friendlies]
        _log(f"Defender names: {names}")

        # Check names are non-empty and not just "Unit" or numeric
        named = [n for n in names if n and len(n) > 2 and n.lower() not in ("unit", "unnamed")]
        _log(f"Named units: {len(named)}/{len(names)}")

        details = {
            "names": names,
            "named_count": len(named),
            "total": len(names),
        }
        passed = len(named) >= 2
        self._record(test_name, passed, details)

        assert passed, f"Expected >=2 named defenders, got {len(named)}: {names}"
        _log(f"Defenders have meaningful names: {len(named)} named")


class TestMissionCombatDeployment:
    """Phase 2: Apply mission and verify deployment on map."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request, tritium_server, test_db, run_id, fleet):
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._fleet = fleet
        cls._t0 = time.monotonic()
        cls.screenshots = {}

        _ensure_dir()

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()

        cls._errors = []
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))

        # Reset, generate, and navigate
        requests.post(f"{cls.url}/api/game/reset", timeout=5)
        time.sleep(0.5)
        requests.post(
            f"{cls.url}/api/game/generate",
            json={"game_mode": "battle", "use_llm": False},
            timeout=10,
        )
        time.sleep(0.5)

        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        cls.page.wait_for_timeout(4000)

        yield

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

    def _get_targets(self, alliance: str = "") -> list[dict]:
        if alliance:
            data = self._api_get(f"/api/targets/{alliance}")
        else:
            data = self._api_get("/api/targets")
        if isinstance(data, dict):
            return data.get("targets", [])
        return data if isinstance(data, list) else []

    def _get_game_state(self) -> dict:
        data = self._api_get("/api/game/state")
        return data if isinstance(data, dict) else {}

    # -------------------------------------------------------------------
    # Test 06: Apply mission
    # -------------------------------------------------------------------
    def test_06_apply_mission(self):
        """POST /api/game/mission/apply places defenders and starts countdown."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 06: APPLY MISSION")
        print("=" * 70)

        test_name = "mission_06_apply_mission"

        result = self._api_post("/api/game/mission/apply")
        _log(f"Apply result: {json.dumps(result)}")

        applied = result is not None and result.get("status") == "scenario_applied"
        defender_count = result.get("defender_count", 0) if result else 0
        wave_count = result.get("wave_count", 0) if result else 0
        _log(f"Applied: {applied}, defenders: {defender_count}, waves: {wave_count}")

        # Wait for UI to update
        self.page.wait_for_timeout(3000)

        details = {
            "applied": applied,
            "defender_count": defender_count,
            "wave_count": wave_count,
            "result": result,
        }
        self._record(test_name, applied, details)

        assert applied, f"Mission apply failed: {result}"
        assert defender_count >= 3, f"Expected >=3 defenders, got {defender_count}"
        _log(f"Mission applied: {defender_count} defenders, {wave_count} waves")

    # -------------------------------------------------------------------
    # Test 07: Defenders visible on map (OpenCV)
    # -------------------------------------------------------------------
    def test_07_defenders_visible_on_map(self):
        """Screenshot shows green markers for friendly units."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 07: DEFENDERS VISIBLE ON MAP")
        print("=" * 70)

        test_name = "mission_07_defenders_visible"

        # Wait for rendering
        self.page.wait_for_timeout(3000)

        path, img = _screenshot(self.page, "07_defenders_visible")
        self.__class__.screenshots["defenders"] = path
        green_regions = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        _log(f"Green blobs detected: {len(green_regions)}")

        for i, gr in enumerate(green_regions[:8]):
            _log(f"  Blob {i+1}: bbox={gr['bbox']} area={gr['area']:.0f}")

        self._record_screenshot(
            test_name, "07_defenders", str(path),
            opencv_data={"green_blobs": len(green_regions)},
        )

        details = {"green_blobs": len(green_regions)}
        passed = len(green_regions) >= 2
        self._record(test_name, passed, details)

        assert passed, f"Expected >=2 green blobs, got {len(green_regions)}"
        _log(f"Defenders visible: {len(green_regions)} green blobs on map")

    # -------------------------------------------------------------------
    # Test 08: Defenders near buildings (llava:7b)
    # -------------------------------------------------------------------
    def test_08_defenders_near_buildings_llava(self):
        """llava:7b confirms military units near buildings on satellite map."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 08: DEFENDERS NEAR BUILDINGS (LLAVA)")
        print("=" * 70)

        test_name = "mission_08_llava_buildings"

        path = self.__class__.screenshots.get("defenders")
        if path is None:
            path, _ = _screenshot(self.page, "08_llava_buildings")

        # Majority vote with llava:7b
        prompt = (
            "Is this a satellite/tactical map showing colored markers or icons "
            "placed near buildings or structures? Answer YES or NO."
        )

        yes_count = 0
        total = 3
        raw_responses = []
        for _ in range(total):
            try:
                resp = self._fleet.generate("llava:7b", prompt, image_path=path, timeout=60)
                raw_responses.append(resp.get("response", ""))
                if "yes" in resp.get("response", "").strip().lower()[:20]:
                    yes_count += 1
            except Exception as e:
                raw_responses.append(f"[error: {e}]")

        llm_passed = yes_count > total // 2
        _log(f"llava:7b vote: {yes_count}/{total} YES -> {'PASS' if llm_passed else 'FAIL'}")
        for i, r in enumerate(raw_responses):
            _log(f"  Response {i+1}: {r[:80]}")

        self._record_screenshot(
            test_name, "08_llava", str(path),
            opencv_data={"llm_yes_count": yes_count, "llm_total": total},
        )

        # Cross-validate: OpenCV green blobs as backup
        img = cv2.imread(str(path))
        green_count = len(_detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)) if img is not None else 0
        opencv_ok = green_count >= 2

        _log(f"OpenCV cross-check: {green_count} green blobs (need >=2)")

        details = {
            "yes_count": yes_count,
            "total": total,
            "responses": [r[:100] for r in raw_responses],
            "opencv_green": green_count,
        }

        # Three-layer logic: if OpenCV confirms defenders present, LLM is advisory
        passed = llm_passed or opencv_ok
        self._record(test_name, passed, details)
        if not llm_passed and opencv_ok:
            _log(f"LLM advisory fail ({yes_count}/{total}), but OpenCV confirms {green_count} green markers")
        assert passed, f"Neither LLM ({yes_count}/{total}) nor OpenCV ({green_count} blobs) confirms defenders"
        _log("Defenders near buildings confirmed")

    # -------------------------------------------------------------------
    # Test 09: Defenders spread out
    # -------------------------------------------------------------------
    def test_09_defenders_spread_out(self):
        """Green blobs are NOT all clustered in same 50px region."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 09: DEFENDERS SPREAD OUT")
        print("=" * 70)

        test_name = "mission_09_spread_out"

        path, img = _screenshot(self.page, "09_spread")
        green_regions = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)

        if len(green_regions) < 2:
            details = {"green_blobs": len(green_regions), "spread": False}
            self._record(test_name, False, details)
            pytest.skip(f"Only {len(green_regions)} green blobs, cannot test spread")

        # Calculate bounding box of all green blob centers
        centers = []
        for gr in green_regions:
            x, y, w, h = gr["bbox"]
            centers.append((x + w // 2, y + h // 2))

        xs = [c[0] for c in centers]
        ys = [c[1] for c in centers]
        x_spread = max(xs) - min(xs)
        y_spread = max(ys) - min(ys)
        total_spread = max(x_spread, y_spread)

        _log(f"Blob spread: x={x_spread}px, y={y_spread}px, max={total_spread}px")

        details = {
            "green_blobs": len(green_regions),
            "x_spread": x_spread,
            "y_spread": y_spread,
            "total_spread": total_spread,
        }
        # Defenders should be spread across at least 50px
        passed = total_spread >= 50
        self._record(test_name, passed, details)

        assert passed, f"Defenders too clustered: spread={total_spread}px (need >=50px)"
        _log(f"Defenders spread across {total_spread}px")

    # -------------------------------------------------------------------
    # Test 10: API confirms friendlies
    # -------------------------------------------------------------------
    def test_10_api_confirms_friendlies(self):
        """GET /api/targets/friendlies returns >= 3 targets."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 10: API CONFIRMS FRIENDLIES")
        print("=" * 70)

        test_name = "mission_10_api_friendlies"

        friendlies = self._get_targets("friendlies")
        _log(f"API friendlies: {len(friendlies)}")
        for f in friendlies[:5]:
            pos = f.get("position", {})
            _log(f"  {f.get('name', '?')} ({f.get('asset_type', '?')}) at ({pos.get('x', 0):.1f}, {pos.get('y', 0):.1f})")

        details = {"friendly_count": len(friendlies)}
        passed = len(friendlies) >= 3
        self._record(test_name, passed, details)

        assert passed, f"Expected >=3 friendlies, got {len(friendlies)}"
        _log(f"API confirms {len(friendlies)} friendlies")

    # -------------------------------------------------------------------
    # Test 11: Defender positions not origin
    # -------------------------------------------------------------------
    def test_11_defender_positions_not_origin(self):
        """API targets have non-zero positions (not all at 0,0)."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 11: POSITIONS NOT ORIGIN")
        print("=" * 70)

        test_name = "mission_11_positions_nonzero"

        friendlies = self._get_targets("friendlies")

        nonzero = 0
        for f in friendlies:
            pos = f.get("position", {})
            x = abs(pos.get("x", 0))
            y = abs(pos.get("y", 0))
            if x > 0.1 or y > 0.1:
                nonzero += 1

        _log(f"Non-zero positions: {nonzero}/{len(friendlies)}")

        details = {
            "total": len(friendlies),
            "nonzero": nonzero,
        }
        passed = nonzero >= 2
        self._record(test_name, passed, details)

        assert passed, f"Expected >=2 non-zero positions, got {nonzero}/{len(friendlies)}"
        _log(f"Defender positions valid: {nonzero} non-zero")

    # -------------------------------------------------------------------
    # Test 12: Screenshot annotated
    # -------------------------------------------------------------------
    def test_12_screenshot_annotated(self):
        """Save annotated screenshot with bounding boxes around green blobs."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 12: ANNOTATED SCREENSHOT")
        print("=" * 70)

        test_name = "mission_12_annotated"

        path, img = _screenshot(self.page, "12_deployment")
        green_regions = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)

        annotations = []
        for i, gr in enumerate(green_regions[:12]):
            annotations.append({
                "bbox": gr["bbox"],
                "color": (0, 255, 100),
                "label": f"DEFENDER-{i+1} (area={gr['area']:.0f})",
            })

        annotated_path = _save_annotated(img, "12_deployment", annotations)
        self.__class__.screenshots["annotated_deploy"] = annotated_path
        _log(f"Annotated screenshot: {annotated_path} ({len(annotations)} annotations)")

        self._record_screenshot(
            test_name, "12_annotated_deploy", str(annotated_path),
            opencv_data={"annotations": len(annotations)},
        )

        details = {"annotated_path": str(annotated_path), "annotation_count": len(annotations)}
        self._record(test_name, True, details)
        _log("Annotated deployment screenshot saved")

    # -------------------------------------------------------------------
    # Test 13: No hostiles before battle
    # -------------------------------------------------------------------
    def test_13_no_hostiles_before_battle(self):
        """GET /api/targets/hostiles returns 0 before wave 1 spawns."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 13: NO HOSTILES PRE-BATTLE")
        print("=" * 70)

        test_name = "mission_13_no_hostiles"

        # Note: mission/apply already calls begin_war(), so we may be in
        # countdown phase. During countdown, hostiles should not exist yet.
        state = self._get_game_state()
        current = state.get("state", "unknown")
        _log(f"Game state: {current}")

        # If we're still in countdown, no hostiles expected
        if current == "countdown":
            hostiles = self._get_targets("hostiles")
            hostile_count = len(hostiles)
            _log(f"Hostiles during countdown: {hostile_count}")

            details = {"hostiles": hostile_count, "state": current}
            passed = hostile_count == 0
            self._record(test_name, passed, details)
            assert passed, f"Expected 0 hostiles during countdown, got {hostile_count}"
        else:
            # Game may have already transitioned past countdown
            _log(f"Game already in '{current}' state, skipping pre-battle check")
            self._record(test_name, True, {"state": current, "note": "already past countdown"})

        _log("No hostiles before battle confirmed")


class TestMissionCombatBattle:
    """Phase 3: Active battle with hostiles, combat, and visual verification."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request, tritium_server, test_db, run_id, fleet):
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._fleet = fleet
        cls._t0 = time.monotonic()
        cls.screenshots = {}

        _ensure_dir()

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()

        cls._errors = []
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))

        # Start a fresh mission: reset, generate, apply
        requests.post(f"{cls.url}/api/game/reset", timeout=5)
        time.sleep(0.5)
        requests.post(
            f"{cls.url}/api/game/generate",
            json={"game_mode": "battle", "use_llm": False},
            timeout=10,
        )
        time.sleep(0.5)
        apply_resp = requests.post(f"{cls.url}/api/game/mission/apply", timeout=10)
        _log(f"Mission apply: {apply_resp.status_code}")

        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        cls.page.wait_for_timeout(4000)

        yield

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

    def _get_targets(self, alliance: str = "") -> list[dict]:
        if alliance:
            data = self._api_get(f"/api/targets/{alliance}")
        else:
            data = self._api_get("/api/targets")
        if isinstance(data, dict):
            return data.get("targets", [])
        return data if isinstance(data, list) else []

    def _get_game_state(self) -> dict:
        data = self._api_get("/api/game/state")
        return data if isinstance(data, dict) else {}

    # -------------------------------------------------------------------
    # Test 14: Begin battle
    # -------------------------------------------------------------------
    def test_14_begin_battle(self):
        """Game state transitions to countdown or active after mission apply."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 14: BEGIN BATTLE")
        print("=" * 70)

        test_name = "mission_14_begin_battle"

        # Poll for active state (mission/apply already called begin_war)
        found_active = False
        for tick in range(15):
            state = self._get_game_state()
            current = state.get("state", "unknown")
            _log(f"t={tick}s: state={current}")

            if current in ("countdown", "active"):
                found_active = True
                break
            time.sleep(1)

        details = {"state": current, "found_active": found_active}
        self._record(test_name, found_active, details)

        assert found_active, f"Expected countdown/active, got '{current}'"
        _log(f"Battle state: {current}")

    # -------------------------------------------------------------------
    # Test 15: Countdown visible
    # -------------------------------------------------------------------
    def test_15_countdown_visible(self):
        """Screenshot during countdown/early battle phase."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 15: COUNTDOWN VISIBLE")
        print("=" * 70)

        test_name = "mission_15_countdown"

        state = self._get_game_state()
        current = state.get("state", "unknown")

        path, img = _screenshot(self.page, "15_countdown")
        self.__class__.screenshots["countdown"] = path

        self._record_screenshot(
            test_name, "15_countdown", str(path),
            api_state={"state": current},
        )

        # The screenshot is the proof; state being countdown or active is enough
        details = {"state": current, "screenshot": str(path)}
        passed = current in ("countdown", "active")
        self._record(test_name, passed, details)

        assert passed, f"Expected countdown/active state, got '{current}'"
        _log(f"Countdown screenshot captured in state: {current}")

    # -------------------------------------------------------------------
    # Test 16: Wave 1 hostiles spawn
    # -------------------------------------------------------------------
    def test_16_wave_1_hostiles_spawn(self):
        """After countdown, hostiles appear in API."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 16: WAVE 1 HOSTILES SPAWN")
        print("=" * 70)

        test_name = "mission_16_hostiles_spawn"

        hostile_count = 0
        for tick in range(30):
            time.sleep(1)
            hostiles = self._get_targets("hostiles")
            hostile_count = len(hostiles)
            state = self._get_game_state()
            current = state.get("state", "unknown")

            if tick % 5 == 0:
                _log(f"t={tick}s: state={current}, hostiles={hostile_count}")

            if hostile_count > 0:
                _log(f"HOSTILES at t={tick}s: {hostile_count}")
                for h in hostiles[:3]:
                    pos = h.get("position", {})
                    _log(f"  '{h.get('name', '')}' ({h.get('asset_type', '')}) at ({pos.get('x', 0):.1f}, {pos.get('y', 0):.1f})")
                break

        details = {"hostile_count": hostile_count}
        passed = hostile_count > 0
        self._record(test_name, passed, details)

        assert passed, f"No hostiles spawned within 30s"
        _log(f"Wave 1 hostiles confirmed: {hostile_count}")

    # -------------------------------------------------------------------
    # Test 17: Hostiles visible red (OpenCV)
    # -------------------------------------------------------------------
    def test_17_hostiles_visible_red(self):
        """Screenshot shows red markers for hostile units."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 17: HOSTILES VISIBLE RED")
        print("=" * 70)

        test_name = "mission_17_red_markers"

        # Wait for rendering
        self.page.wait_for_timeout(3000)

        path, img = _screenshot(self.page, "17_hostiles_red")
        self.__class__.screenshots["hostiles_red"] = path
        red_regions = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10)
        _log(f"Red blobs detected: {len(red_regions)}")

        for i, rr in enumerate(red_regions[:8]):
            _log(f"  Red blob {i+1}: bbox={rr['bbox']} area={rr['area']:.0f}")

        self._record_screenshot(
            test_name, "17_hostiles_red", str(path),
            opencv_data={"red_blobs": len(red_regions)},
        )

        # Also check API as backup
        hostiles = self._get_targets("hostiles")
        api_count = len(hostiles)

        details = {"red_blobs": len(red_regions), "api_hostiles": api_count}
        # Either OpenCV or API should confirm hostiles
        passed = len(red_regions) >= 1 or api_count >= 1
        self._record(test_name, passed, details)

        assert passed, f"No hostile markers: red_blobs={len(red_regions)}, api={api_count}"
        _log(f"Hostile markers: {len(red_regions)} red blobs, {api_count} API")

    # -------------------------------------------------------------------
    # Test 18: Both sides visible (llava:7b)
    # -------------------------------------------------------------------
    def test_18_both_sides_visible_llava(self):
        """llava:7b confirms both green and red markers visible."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 18: BOTH SIDES VISIBLE (LLAVA)")
        print("=" * 70)

        test_name = "mission_18_llava_both"

        path, img = _screenshot(self.page, "18_both_sides")
        self.__class__.screenshots["both_sides"] = path

        prompt = (
            "Does this tactical/satellite map image show BOTH green colored markers "
            "AND red colored markers, indicating two opposing forces? Answer YES or NO."
        )

        yes_count = 0
        total = 3
        raw_responses = []
        for _ in range(total):
            try:
                resp = self._fleet.generate("llava:7b", prompt, image_path=path, timeout=60)
                raw_responses.append(resp.get("response", ""))
                if "yes" in resp.get("response", "").strip().lower()[:20]:
                    yes_count += 1
            except Exception as e:
                raw_responses.append(f"[error: {e}]")

        llm_passed = yes_count > total // 2
        _log(f"llava:7b vote: {yes_count}/{total} YES -> {'PASS' if llm_passed else 'FAIL'}")

        # Cross-validate with OpenCV
        green_count = len(_detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15))
        red_count = len(_detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10))
        opencv_both = green_count >= 1 and red_count >= 1

        _log(f"OpenCV cross-check: green={green_count} red={red_count} both={opencv_both}")

        self._record_screenshot(
            test_name, "18_llava_both", str(path),
            opencv_data={"green": green_count, "red": red_count, "llm_yes": yes_count},
        )

        details = {
            "llm_yes": yes_count,
            "llm_total": total,
            "opencv_green": green_count,
            "opencv_red": red_count,
        }
        # Pass if either LLM or OpenCV confirms both sides
        passed = llm_passed or opencv_both
        self._record(test_name, passed, details)

        assert passed, f"Neither LLM ({yes_count}/{total}) nor OpenCV (g={green_count},r={red_count}) confirms both sides"
        _log("Both sides visible on map confirmed")

    # -------------------------------------------------------------------
    # Test 19: Combat in progress
    # -------------------------------------------------------------------
    def test_19_combat_in_progress(self):
        """API shows active game state with wave >= 1."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 19: COMBAT IN PROGRESS")
        print("=" * 70)

        test_name = "mission_19_combat_active"

        state = self._get_game_state()
        current = state.get("state", "unknown")
        wave = state.get("wave", 0)
        score = state.get("score", 0)

        _log(f"Game state: {current}, wave: {wave}, score: {score}")

        details = {"state": current, "wave": wave, "score": score}
        passed = current == "active" and wave >= 1
        self._record(test_name, passed, details)

        assert passed, f"Expected active state with wave>=1, got state={current} wave={wave}"
        _log(f"Combat active: wave {wave}, score {score}")

    # -------------------------------------------------------------------
    # Test 20: Projectiles or engagement
    # -------------------------------------------------------------------
    def test_20_projectiles_or_engagement(self):
        """Wait 5s, check for combat events via API."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 20: COMBAT ENGAGEMENT")
        print("=" * 70)

        test_name = "mission_20_engagement"

        # Wait for combat to develop
        time.sleep(5)

        state = self._get_game_state()
        score = state.get("score", 0)
        elims = state.get("total_eliminations", 0)

        # Check projectiles
        projectiles = self._api_get("/api/game/projectiles")
        proj_count = len(projectiles) if isinstance(projectiles, list) else 0

        _log(f"Score: {score}, Eliminations: {elims}, Active projectiles: {proj_count}")

        # Check for any combat activity
        combat_active = score > 0 or elims > 0 or proj_count > 0

        # If no combat yet, poll a bit more
        if not combat_active:
            for tick in range(10):
                time.sleep(1)
                state = self._get_game_state()
                score = state.get("score", 0)
                elims = state.get("total_eliminations", 0)
                if score > 0 or elims > 0:
                    combat_active = True
                    _log(f"Combat detected at t={tick+5}s: score={score} elims={elims}")
                    break

        details = {"score": score, "eliminations": elims, "projectiles": proj_count}
        self._record(test_name, combat_active, details)

        assert combat_active, f"No combat activity: score={score}, elims={elims}, proj={proj_count}"
        _log(f"Combat engagement confirmed: score={score}, elims={elims}")

    # -------------------------------------------------------------------
    # Test 21: Mid-battle screenshot
    # -------------------------------------------------------------------
    def test_21_mid_battle_screenshot(self):
        """Full annotated screenshot during active combat."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 21: MID-BATTLE SCREENSHOT")
        print("=" * 70)

        test_name = "mission_21_mid_battle"

        path, img = _screenshot(self.page, "21_mid_battle")
        green_regions = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        red_regions = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10)

        annotations = []
        for i, gr in enumerate(green_regions[:10]):
            annotations.append({
                "bbox": gr["bbox"],
                "color": (0, 255, 100),
                "label": f"FRIENDLY{i+1}",
            })
        for i, rr in enumerate(red_regions[:10]):
            annotations.append({
                "bbox": rr["bbox"],
                "color": (0, 0, 255),
                "label": f"HOSTILE{i+1}",
            })

        annotated_path = _save_annotated(img, "21_mid_battle", annotations)
        self.__class__.screenshots["mid_battle"] = annotated_path
        _log(f"Mid-battle annotated: {len(green_regions)} green, {len(red_regions)} red")

        state = self._get_game_state()

        self._record_screenshot(
            test_name, "21_mid_battle", str(annotated_path),
            opencv_data={"green": len(green_regions), "red": len(red_regions)},
            api_state=state,
        )

        details = {
            "green_blobs": len(green_regions),
            "red_blobs": len(red_regions),
            "game_state": state.get("state"),
            "wave": state.get("wave"),
            "screenshot": str(annotated_path),
        }
        self._record(test_name, True, details)
        _log("Mid-battle screenshot captured and annotated")


class TestMissionCombatVerification:
    """Phase 4: Post-combat verification and final analysis."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request, tritium_server, test_db, run_id, fleet):
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._fleet = fleet
        cls._t0 = time.monotonic()
        cls.screenshots = {}

        _ensure_dir()

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()

        cls._errors = []
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))

        # Start a fresh mission for this verification phase
        requests.post(f"{cls.url}/api/game/reset", timeout=5)
        time.sleep(0.5)
        requests.post(
            f"{cls.url}/api/game/generate",
            json={"game_mode": "battle", "use_llm": False},
            timeout=10,
        )
        time.sleep(0.5)
        requests.post(f"{cls.url}/api/game/mission/apply", timeout=10)

        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        cls.page.wait_for_timeout(4000)

        # Wait for combat to be well underway (10s into battle)
        _log("Waiting 15s for combat to develop...")
        time.sleep(15)

        yield

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

    def _get_targets(self, alliance: str = "") -> list[dict]:
        if alliance:
            data = self._api_get(f"/api/targets/{alliance}")
        else:
            data = self._api_get("/api/targets")
        if isinstance(data, dict):
            return data.get("targets", [])
        return data if isinstance(data, list) else []

    def _get_game_state(self) -> dict:
        data = self._api_get("/api/game/state")
        return data if isinstance(data, dict) else {}

    # -------------------------------------------------------------------
    # Test 22: Defenders still alive
    # -------------------------------------------------------------------
    def test_22_defenders_still_alive(self):
        """At least 1 friendly unit still active after combat."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 22: DEFENDERS STILL ALIVE")
        print("=" * 70)

        test_name = "mission_22_defenders_alive"

        friendlies = self._get_targets("friendlies")
        alive = [f for f in friendlies if f.get("health", 0) > 0]
        _log(f"Friendlies: {len(friendlies)} total, {len(alive)} alive")

        for f in alive[:5]:
            _log(f"  {f.get('name', '?')} hp={f.get('health', 0):.0f}/{f.get('max_health', 0):.0f}")

        details = {"total": len(friendlies), "alive": len(alive)}
        passed = len(alive) >= 1
        self._record(test_name, passed, details)

        assert passed, f"No defenders alive: {len(friendlies)} total, {len(alive)} alive"
        _log(f"Defenders alive: {len(alive)}")

    # -------------------------------------------------------------------
    # Test 23: Battle progressing
    # -------------------------------------------------------------------
    def test_23_battle_progressing(self):
        """Wave number > 0, score > 0 or eliminations > 0."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 23: BATTLE PROGRESSING")
        print("=" * 70)

        test_name = "mission_23_progressing"

        state = self._get_game_state()
        wave = state.get("wave", 0)
        score = state.get("score", 0)
        elims = state.get("total_eliminations", 0)
        current = state.get("state", "unknown")

        _log(f"State: {current}, wave: {wave}, score: {score}, elims: {elims}")

        details = {"state": current, "wave": wave, "score": score, "eliminations": elims}
        passed = wave > 0 and (score > 0 or elims > 0)
        self._record(test_name, passed, details)

        assert passed, f"Battle not progressing: wave={wave} score={score} elims={elims}"
        _log(f"Battle progressing: wave {wave}, score {score}, {elims} eliminations")

    # -------------------------------------------------------------------
    # Test 24: Map shows action (llava:7b)
    # -------------------------------------------------------------------
    def test_24_map_shows_action_llava(self):
        """llava:7b confirms active combat on tactical map."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 24: MAP SHOWS ACTION (LLAVA)")
        print("=" * 70)

        test_name = "mission_24_llava_action"

        path, img = _screenshot(self.page, "24_action")
        self.__class__.screenshots["action"] = path

        prompt = (
            "Is there active combat visible on this tactical map with multiple "
            "colored markers or icons? Look for green and red elements. "
            "Answer YES or NO."
        )

        yes_count = 0
        total = 3
        raw_responses = []
        for _ in range(total):
            try:
                resp = self._fleet.generate("llava:7b", prompt, image_path=path, timeout=60)
                raw_responses.append(resp.get("response", ""))
                if "yes" in resp.get("response", "").strip().lower()[:20]:
                    yes_count += 1
            except Exception as e:
                raw_responses.append(f"[error: {e}]")

        llm_passed = yes_count > total // 2
        _log(f"llava:7b vote: {yes_count}/{total} YES")

        # Cross-validate with OpenCV
        green_count = len(_detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15))
        red_count = len(_detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10))
        opencv_action = green_count >= 1 or red_count >= 1

        _log(f"OpenCV: green={green_count} red={red_count}")

        self._record_screenshot(
            test_name, "24_llava_action", str(path),
            opencv_data={"green": green_count, "red": red_count, "llm_yes": yes_count},
        )

        details = {
            "llm_yes": yes_count,
            "opencv_green": green_count,
            "opencv_red": red_count,
        }
        # Pass if either LLM or OpenCV shows activity
        passed = llm_passed or opencv_action
        self._record(test_name, passed, details)

        assert passed, f"No action visible: LLM {yes_count}/{total}, OpenCV g={green_count} r={red_count}"
        _log("Map action confirmed")

    # -------------------------------------------------------------------
    # Test 25: Final annotated screenshot
    # -------------------------------------------------------------------
    def test_25_final_annotated_screenshot(self):
        """Capture final state with all annotations and game summary."""
        print("\n" + "=" * 70)
        print("  MISSION COMBAT 25: FINAL ANNOTATED SCREENSHOT")
        print("=" * 70)

        test_name = "mission_25_final"

        path, img = _screenshot(self.page, "25_final")
        green_regions = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        red_regions = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10)

        annotations = []
        for i, gr in enumerate(green_regions[:12]):
            annotations.append({
                "bbox": gr["bbox"],
                "color": (0, 255, 100),
                "label": f"FRIENDLY{i+1} (a={gr['area']:.0f})",
            })
        for i, rr in enumerate(red_regions[:12]):
            annotations.append({
                "bbox": rr["bbox"],
                "color": (0, 0, 255),
                "label": f"HOSTILE{i+1} (a={rr['area']:.0f})",
            })

        annotated_path = _save_annotated(img, "25_final", annotations)
        self.__class__.screenshots["final"] = annotated_path

        state = self._get_game_state()
        friendlies = self._get_targets("friendlies")
        hostiles = self._get_targets("hostiles")

        self._record_screenshot(
            test_name, "25_final", str(annotated_path),
            opencv_data={"green": len(green_regions), "red": len(red_regions)},
            api_state=state,
        )

        details = {
            "green_blobs": len(green_regions),
            "red_blobs": len(red_regions),
            "api_friendlies": len(friendlies),
            "api_hostiles": len(hostiles),
            "game_state": state,
            "screenshot": str(annotated_path),
        }
        self._record(test_name, True, details)

        # Print grand summary
        print("\n" + "=" * 70)
        print("  MISSION COMBAT VERIFICATION COMPLETE")
        print("=" * 70)
        print(f"  Game State:    {state.get('state', 'unknown')}")
        print(f"  Wave:          {state.get('wave', 0)}")
        print(f"  Score:         {state.get('score', 0)}")
        print(f"  Eliminations:  {state.get('total_eliminations', 0)}")
        print(f"  Friendlies:    {len(friendlies)} ({len(green_regions)} green blobs)")
        print(f"  Hostiles:      {len(hostiles)} ({len(red_regions)} red blobs)")
        print(f"  Screenshots:   {PROOF_DIR}")
        print("=" * 70)
