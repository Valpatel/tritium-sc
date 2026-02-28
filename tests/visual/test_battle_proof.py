# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Battle Proof — end-to-end 10-wave battle verification with screenshots.

Runs a FULL battle from server health check through victory/defeat,
capturing screenshots and recording metrics at every stage. Each test
is ordered so later tests depend on state built by earlier ones.

Uses the same pattern as test_game_loop_proof.py:
- ResultsDB recording for interactive HTML reports
- OpenCV color detection for unit/hostile verification
- Playwright for DOM assertions
- Screenshot proof at every phase

Run:
    .venv/bin/python3 -m pytest tests/visual/test_battle_proof.py -v --timeout=900
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

PROOF_DIR = Path("tests/.test-results/battle-proof")

# BGR colors from the UI
FRIENDLY_GREEN_BGR = np.array([161, 255, 5])    # #05ffa1
HOSTILE_RED_BGR = np.array([109, 42, 255])       # #ff2a6d
CYAN_BGR = np.array([255, 240, 0])               # #00f0ff
YELLOW_BGR = np.array([10, 238, 252])            # #fcee0a
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


class TestBattleProof:
    """End-to-end battle proof: every stage captured with screenshots."""

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
        browser = cls._pw.chromium.launch(headless=True)
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
            resp = requests.post(f"{self.url}{path}", json=data or {}, timeout=5)
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
    # Test 00: Server healthy
    # -------------------------------------------------------------------
    def test_proof_00_server_healthy(self):
        """Server responds to health check."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 00: SERVER HEALTH")
        print("=" * 70)

        test_name = "battle_00_server_healthy"

        # Check targets API
        targets_resp = requests.get(f"{self.url}/api/targets", timeout=5)
        targets_ok = targets_resp.status_code == 200
        _log(f"GET /api/targets -> {targets_resp.status_code}")

        # Check game state API
        game_resp = requests.get(f"{self.url}/api/game/state", timeout=5)
        game_ok = game_resp.status_code == 200
        game_data = game_resp.json() if game_ok else {}
        _log(f"GET /api/game/state -> {game_resp.status_code}: {json.dumps(game_data)}")

        # Check simulation targets
        sim_resp = requests.get(f"{self.url}/api/amy/simulation/targets", timeout=5)
        sim_ok = sim_resp.status_code == 200
        _log(f"GET /api/amy/simulation/targets -> {sim_resp.status_code}")

        details = {
            "targets_status": targets_resp.status_code,
            "game_status": game_resp.status_code,
            "sim_status": sim_resp.status_code,
            "game_state": game_data,
        }

        passed = targets_ok and game_ok and sim_ok
        self._record(test_name, passed, details)

        assert targets_ok, f"/api/targets returned {targets_resp.status_code}"
        assert game_ok, f"/api/game/state returned {game_resp.status_code}"
        assert sim_ok, f"/api/amy/simulation/targets returned {sim_resp.status_code}"
        _log("Server healthy: all endpoints responding")

    # -------------------------------------------------------------------
    # Test 01: Map renders content
    # -------------------------------------------------------------------
    def test_proof_01_map_renders_content(self):
        """Canvas has non-black pixels (satellite imagery loaded)."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 01: MAP RENDERS CONTENT")
        print("=" * 70)

        test_name = "battle_01_map_renders"
        path, img = _screenshot(self.page, "01_map_content")
        h, w = img.shape[:2]

        # Check the center 50% of the canvas (avoid header/status/panels)
        cx, cy = w // 4, h // 4
        cw, ch = w // 2, h // 2
        center = img[cy:cy + ch, cx:cx + cw]

        gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
        nonblack = np.count_nonzero(gray > 15)
        total = center.shape[0] * center.shape[1]
        pct = nonblack / total * 100

        _log(f"Center region: {pct:.1f}% non-black pixels ({nonblack}/{total})")

        self._record_screenshot(
            test_name, "01_map_content", str(path),
            opencv_data={"nonblack_pct": round(pct, 1)},
        )

        details = {"nonblack_pct": round(pct, 1), "nonblack_px": nonblack, "total_px": total}
        passed = pct > 5
        self._record(test_name, passed, details)

        assert passed, f"Map center too dark: only {pct:.1f}% non-black (need >5%)"
        _log("Map renders content with satellite imagery")

    # -------------------------------------------------------------------
    # Test 02: Units on map
    # -------------------------------------------------------------------
    def test_proof_02_units_on_map(self):
        """Friendly units visible as green pixels."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 02: UNITS ON MAP")
        print("=" * 70)

        test_name = "battle_02_units_on_map"

        # Wait for store to have units
        self.page.wait_for_timeout(2000)
        unit_count = self.page.evaluate("""() => {
            const store = window.TritiumStore || window.store;
            if (!store) return 0;
            const units = store.units || store.targets;
            if (!units) return 0;
            return units.size || units.length || Object.keys(units).length || 0;
        }""")
        _log(f"TritiumStore unit count: {unit_count}")

        path, img = _screenshot(self.page, "02_units")
        green_regions = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        _log(f"Green blobs detected: {len(green_regions)}")

        annotations = []
        for i, gr in enumerate(green_regions[:10]):
            annotations.append({"bbox": gr["bbox"], "color": (0, 255, 100),
                                "label": f"UNIT-F{i+1} (area={gr['area']:.0f})"})

        annotated_path = _save_annotated(img, "02_units", annotations)

        self._record_screenshot(
            test_name, "02_units_annotated", str(annotated_path),
            opencv_data={"green_blobs": len(green_regions)},
            api_state={"store_units": unit_count},
        )

        details = {"green_blobs": len(green_regions), "store_units": unit_count}
        # Either DOM or OpenCV should show units
        passed = len(green_regions) >= 3 or unit_count >= 3
        self._record(test_name, passed, details)

        assert passed, (
            f"Expected >=3 units. Green blobs: {len(green_regions)}, "
            f"Store units: {unit_count}"
        )
        _log(f"Units confirmed: {len(green_regions)} green blobs, {unit_count} in store")

    # -------------------------------------------------------------------
    # Test 03: Header shows data
    # -------------------------------------------------------------------
    def test_proof_03_header_shows_data(self):
        """Header has unit count, clock, connection status."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 03: HEADER DATA")
        print("=" * 70)

        test_name = "battle_03_header_data"
        path, img = _screenshot(self.page, "03_header")

        checks = {}

        # Unit count
        units_text = self.page.evaluate(
            "() => document.querySelector('#header-units .stat-value')?.textContent?.trim() || ''"
        )
        checks["unit_count"] = len(units_text) > 0 and units_text != "0"
        _log(f"Unit count: '{units_text}' -> {'PASS' if checks['unit_count'] else 'FAIL'}")

        # Clock
        clock_text = self.page.evaluate(
            "() => document.querySelector('#header-clock')?.textContent?.trim() || ''"
        )
        checks["clock"] = "UTC" in clock_text.upper() or ":" in clock_text
        _log(f"Clock: '{clock_text}' -> {'PASS' if checks['clock'] else 'FAIL'}")

        # Connection status
        conn_text = self.page.evaluate(
            "() => document.querySelector('#connection-status .conn-label')?.textContent?.trim() || ''"
        )
        checks["connection"] = len(conn_text.strip()) > 0
        _log(f"Connection: '{conn_text}' -> {'PASS' if checks['connection'] else 'FAIL'}")

        self._record_screenshot(
            test_name, "03_header", str(path),
            api_state={"units": units_text, "clock": clock_text, "connection": conn_text},
        )

        pass_count = sum(1 for v in checks.values() if v)
        details = {"checks": checks, "units": units_text, "clock": clock_text, "connection": conn_text}
        passed = pass_count >= 2  # at least 2 of 3 checks pass
        self._record(test_name, passed, details)

        assert passed, f"Header checks: {pass_count}/3 passed. {checks}"
        _log(f"Header data: {pass_count}/3 checks passed")

    # -------------------------------------------------------------------
    # Test 04: Panels visible
    # -------------------------------------------------------------------
    def test_proof_04_panels_visible(self):
        """At least 2 floating panels are visible with content."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 04: PANELS VISIBLE")
        print("=" * 70)

        test_name = "battle_04_panels_visible"
        path, img = _screenshot(self.page, "04_panels")

        panel_data = self.page.evaluate("""() => {
            const panels = document.querySelectorAll('.panel');
            return [...panels].filter(p =>
                p.offsetParent !== null && p.style.display !== 'none'
            ).map(p => {
                const r = p.getBoundingClientRect();
                return {
                    title: p.querySelector('.panel-title')?.textContent?.trim() || 'untitled',
                    x: Math.round(r.x), y: Math.round(r.y),
                    w: Math.round(r.width), h: Math.round(r.height),
                    hasItems: p.querySelectorAll('.panel-list-item, li, .target-entry, .unit-entry').length
                };
            });
        }""")

        _log(f"Visible panels: {len(panel_data)}")
        for p in panel_data:
            _log(f"  '{p['title']}' {p['w']}x{p['h']} at ({p['x']},{p['y']}) items={p['hasItems']}")

        annotations = []
        for i, p in enumerate(panel_data):
            annotations.append({"bbox": (p["x"], p["y"], p["w"], p["h"]),
                                "color": (255, 0, 255),
                                "label": f"PANEL: {p['title']}"})
        annotated_path = _save_annotated(img, "04_panels", annotations)

        self._record_screenshot(
            test_name, "04_panels_annotated", str(annotated_path),
            api_state={"panels": panel_data},
        )

        details = {"panel_count": len(panel_data), "panels": panel_data}
        passed = len(panel_data) >= 2
        self._record(test_name, passed, details)

        assert passed, f"Expected >=2 visible panels, got {len(panel_data)}"
        _log(f"Panels confirmed: {len(panel_data)} visible")

    # -------------------------------------------------------------------
    # Test 05: Setup — place turrets
    # -------------------------------------------------------------------
    def test_proof_05_setup_place_turrets(self):
        """Place 3 turrets via API and verify in store."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 05: PLACE TURRETS")
        print("=" * 70)

        test_name = "battle_05_place_turrets"

        # Reset game first
        reset_result = self._api_post("/api/game/reset")
        _log(f"Game reset: {json.dumps(reset_result)}")
        self.page.wait_for_timeout(1000)

        # Place 3 turrets
        turret_positions = [
            {"name": "Alpha Turret", "asset_type": "turret", "position": {"x": 0, "y": 0}},
            {"name": "Bravo Turret", "asset_type": "turret", "position": {"x": 8, "y": 0}},
            {"name": "Charlie Turret", "asset_type": "turret", "position": {"x": -8, "y": 0}},
        ]

        placed = []
        for turret in turret_positions:
            result = self._api_post("/api/game/place", turret)
            placed.append(result)
            _log(f"Placed '{turret['name']}': {json.dumps(result)}")

        self.page.wait_for_timeout(2000)

        # Verify via targets API
        targets = self._get_targets()
        friendlies = [t for t in targets if t.get("alliance") == "friendly"]
        turrets = [t for t in friendlies if t.get("asset_type") == "turret"]
        _log(f"Targets: {len(targets)} total, {len(friendlies)} friendly, {len(turrets)} turrets")

        path, img = _screenshot(self.page, "05_turrets_placed")
        green_blobs = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        _log(f"Green blobs after placement: {len(green_blobs)}")

        self._record_screenshot(
            test_name, "05_turrets_placed", str(path),
            opencv_data={"green_blobs": len(green_blobs)},
            api_state={"friendlies": len(friendlies), "turrets": len(turrets)},
        )

        details = {
            "placed": len(placed),
            "total_targets": len(targets),
            "friendlies": len(friendlies),
            "turrets": len(turrets),
            "green_blobs": len(green_blobs),
        }
        # Need at least 3 placed AND visible in API
        passed = len(turrets) >= 3
        self._record(test_name, passed, details)

        assert passed, f"Expected >=3 turrets in targets API, got {len(turrets)}"
        _log(f"Turrets placed and confirmed: {len(turrets)} in API")

    # -------------------------------------------------------------------
    # Test 06: Battle countdown
    # -------------------------------------------------------------------
    def test_proof_06_battle_countdown(self):
        """POST /api/game/begin -- countdown appears."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 06: BATTLE COUNTDOWN")
        print("=" * 70)

        test_name = "battle_06_countdown"

        # Begin war
        begin_result = self._api_post("/api/game/begin")
        _log(f"Begin war: {json.dumps(begin_result)}")

        # Wait briefly for countdown to appear in UI
        self.page.wait_for_timeout(1000)

        # Check game state
        state = self._get_game_state()
        current_state = state.get("state", "unknown")
        countdown = state.get("countdown", -1)
        _log(f"Game state: {current_state}, countdown: {countdown}")

        # Try to observe countdown element
        countdown_visible = self.page.evaluate("""() => {
            const el = document.getElementById('war-countdown');
            if (!el) return false;
            return el.style.display !== 'none' || el.classList.contains('active');
        }""")
        _log(f"Countdown element visible: {countdown_visible}")

        path, img = _screenshot(self.page, "06_countdown")

        self._record_screenshot(
            test_name, "06_countdown", str(path),
            api_state={"state": current_state, "countdown": countdown},
        )

        details = {
            "begin_result": begin_result,
            "game_state": current_state,
            "countdown": countdown,
            "countdown_visible": countdown_visible,
        }
        # State should be countdown or active (might transition fast)
        passed = current_state in ("countdown", "active")
        self._record(test_name, passed, details)

        assert passed, f"Expected state countdown/active, got '{current_state}'"
        _log(f"Battle countdown confirmed: state={current_state}")

    # -------------------------------------------------------------------
    # Test 07: Combat active — hostiles visible
    # -------------------------------------------------------------------
    def test_proof_07_combat_active(self):
        """Wave 1 active -- hostiles visible, units engaging."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 07: COMBAT ACTIVE")
        print("=" * 70)

        test_name = "battle_07_combat_active"

        # Wait for game to reach active state with hostiles
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
                for h in hostiles[:3]:
                    pos = h.get("position", {})
                    _log(f"  '{h.get('name', '')}' at ({pos.get('x', 0):.1f}, {pos.get('y', 0):.1f})")
                break

        # Wait a bit for combat to develop
        self.page.wait_for_timeout(3000)

        path, img = _screenshot(self.page, "07_combat_active")
        red_blobs = _detect_color_regions(img, HOSTILE_RED_BGR, tolerance=60, min_area=10)
        green_blobs = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        _log(f"Red blobs: {len(red_blobs)}, Green blobs: {len(green_blobs)}")

        annotations = []
        for i, gb in enumerate(green_blobs[:8]):
            annotations.append({"bbox": gb["bbox"], "color": (0, 255, 100),
                                "label": f"FRIENDLY{i+1}"})
        for i, rb in enumerate(red_blobs[:8]):
            annotations.append({"bbox": rb["bbox"], "color": (0, 0, 255),
                                "label": f"HOSTILE{i+1}"})
        annotated_path = _save_annotated(img, "07_combat_active", annotations)

        self._record_screenshot(
            test_name, "07_combat_annotated", str(annotated_path),
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
        _log(f"Combat active confirmed: {hostile_count} hostiles on field")

    # -------------------------------------------------------------------
    # Test 08: Projectiles or effects
    # -------------------------------------------------------------------
    def test_proof_08_projectiles_or_effects(self):
        """Combat effects visible during active battle."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 08: PROJECTILES / EFFECTS")
        print("=" * 70)

        test_name = "battle_08_projectiles"

        # Take rapid screenshots looking for projectile-colored pixels
        shots = []
        max_yellow = 0
        max_orange = 0
        for i in range(5):
            self.page.wait_for_timeout(400)
            path, img = _screenshot(self.page, f"08_fx_{i}")
            yellow_regions = _detect_color_regions(img, YELLOW_BGR, tolerance=60, min_area=5)
            orange_regions = _detect_color_regions(img, ORANGE_BGR, tolerance=60, min_area=5)
            max_yellow = max(max_yellow, len(yellow_regions))
            max_orange = max(max_orange, len(orange_regions))
            shots.append({"yellow": len(yellow_regions), "orange": len(orange_regions)})

        _log(f"Projectile scan: max yellow={max_yellow}, max orange={max_orange}")

        # Also check elimination feed DOM
        elim_entries = self.page.evaluate("""() => {
            const feed = document.getElementById('war-elimination-feed');
            if (!feed) return 0;
            return feed.querySelectorAll('.war-elimination-entry, .war-kill-entry').length;
        }""")
        _log(f"Elimination feed entries: {elim_entries}")

        # Check projectiles API
        projectiles = self._api_get("/api/game/projectiles")
        proj_count = len(projectiles) if isinstance(projectiles, list) else 0
        _log(f"API projectiles: {proj_count}")

        # Use the last screenshot for recording
        path, img = _screenshot(self.page, "08_effects_final")

        self._record_screenshot(
            test_name, "08_effects", str(path),
            opencv_data={"max_yellow": max_yellow, "max_orange": max_orange},
            api_state={"elim_entries": elim_entries, "projectiles_api": proj_count},
        )

        details = {
            "shots": shots,
            "max_yellow": max_yellow,
            "max_orange": max_orange,
            "elim_entries": elim_entries,
            "projectiles_api": proj_count,
        }
        # At least one evidence of combat: projectile pixels, elimination entries, or API projectiles
        passed = max_yellow > 0 or max_orange > 0 or elim_entries > 0 or proj_count > 0
        self._record(test_name, passed, details)

        assert passed, (
            f"No combat effects detected. Yellow={max_yellow}, Orange={max_orange}, "
            f"Elim entries={elim_entries}, API projectiles={proj_count}"
        )
        _log("Combat effects confirmed")

    # -------------------------------------------------------------------
    # Test 09: Elimination feed
    # -------------------------------------------------------------------
    def test_proof_09_elimination_feed(self):
        """Kill feed shows at least one elimination."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 09: ELIMINATION FEED")
        print("=" * 70)

        test_name = "battle_09_elimination_feed"

        # Wait up to 30s for an elimination
        elim_count = 0
        game_elims = 0
        for tick in range(30):
            time.sleep(1)
            state = self._get_game_state()
            game_elims = state.get("total_eliminations", 0)

            elim_count = self.page.evaluate("""() => {
                const feed = document.getElementById('war-elimination-feed');
                if (!feed) return 0;
                return feed.querySelectorAll('.war-elimination-entry, .war-kill-entry').length;
            }""")

            if tick % 5 == 0:
                _log(f"t={tick}s: DOM entries={elim_count}, API elims={game_elims}")

            if game_elims > 0:
                _log(f"ELIMINATION at t={tick}s: API reports {game_elims} total")
                break

        path, img = _screenshot(self.page, "09_elimination_feed")

        self._record_screenshot(
            test_name, "09_elimination_feed", str(path),
            api_state={"dom_entries": elim_count, "api_eliminations": game_elims},
        )

        details = {
            "dom_entries": elim_count,
            "api_eliminations": game_elims,
        }
        # API elimination count is the reliable signal
        passed = game_elims > 0
        self._record(test_name, passed, details)

        assert passed, f"No eliminations in 30s. DOM entries={elim_count}, API elims={game_elims}"
        _log(f"Elimination confirmed: {game_elims} total")

    # -------------------------------------------------------------------
    # Test 10: Wave progresses
    # -------------------------------------------------------------------
    def test_proof_10_wave_progresses(self):
        """Wave number increases (wave 2+ reached)."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 10: WAVE PROGRESSION")
        print("=" * 70)

        test_name = "battle_10_wave_progression"

        max_wave = 0
        last_state = ""
        for tick in range(120):
            time.sleep(1)
            state = self._get_game_state()
            wave = state.get("wave", 0)
            phase = state.get("state", "unknown")
            score = state.get("score", 0)
            elims = state.get("total_eliminations", 0)

            if wave > max_wave:
                max_wave = wave
                _log(f"WAVE {wave} reached at t={tick}s (state={phase}, score={score}, elims={elims})")
                # Screenshot on wave transition
                path, img = _screenshot(self.page, f"10_wave_{wave}")
                self._record_screenshot(
                    test_name, f"10_wave_{wave}", str(path),
                    api_state={"wave": wave, "state": phase, "score": score},
                )

            if wave >= 2:
                _log(f"Wave 2+ reached at t={tick}s")
                break

            if phase in ("victory", "defeat"):
                _log(f"Game ended at wave {wave}: {phase}")
                break

            last_state = phase
            if tick % 10 == 0:
                _log(f"t={tick}s: wave={wave} state={phase} score={score} elims={elims}")

        path, img = _screenshot(self.page, "10_wave_progress")

        details = {
            "max_wave": max_wave,
            "last_state": last_state,
            "final_game_state": self._get_game_state(),
        }
        passed = max_wave >= 2
        self._record(test_name, passed, details)

        assert passed, f"Wave did not progress beyond {max_wave}. Last state: {last_state}"
        _log(f"Wave progression confirmed: reached wave {max_wave}")

    # -------------------------------------------------------------------
    # Test 11: Battle ends
    # -------------------------------------------------------------------
    def test_proof_11_battle_ends(self):
        """Battle reaches victory or defeat."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 11: BATTLE CONCLUSION")
        print("=" * 70)

        test_name = "battle_11_conclusion"

        # Check if already ended from previous test
        state = self._get_game_state()
        current = state.get("state", "unknown")

        if current in ("victory", "defeat"):
            _log(f"Battle already concluded: {current}")
        else:
            # Wait up to 600s (10 min) for battle to end
            for tick in range(600):
                time.sleep(1)
                state = self._get_game_state()
                current = state.get("state", "unknown")
                wave = state.get("wave", 0)
                score = state.get("score", 0)

                if tick % 30 == 0:
                    _log(f"t={tick}s: wave={wave} state={current} score={score}")

                if current in ("victory", "defeat"):
                    _log(f"Battle concluded at t={tick}s: {current}")
                    break

        path, img = _screenshot(self.page, "11_conclusion")

        final_state = self._get_game_state()
        result = final_state.get("state", "unknown")

        self._record_screenshot(
            test_name, "11_conclusion", str(path),
            api_state=final_state,
        )

        details = {
            "result": result,
            "final_state": final_state,
        }
        passed = result in ("victory", "defeat")
        self._record(test_name, passed, details)

        assert passed, f"Battle did not conclude. Final state: {result}. Full: {json.dumps(final_state)}"
        _log(f"Battle concluded: {result}")

    # -------------------------------------------------------------------
    # Test 12: Final score
    # -------------------------------------------------------------------
    def test_proof_12_final_score(self):
        """Final score and stats are displayed."""
        print("\n" + "=" * 70)
        print("  BATTLE PROOF 12: FINAL SCORE")
        print("=" * 70)

        test_name = "battle_12_final_score"

        state = self._get_game_state()
        score = state.get("score", 0)
        elims = state.get("total_eliminations", 0)
        waves = state.get("wave", 0)
        result = state.get("state", "unknown")

        _log(f"Final: result={result} score={score} elims={elims} waves={waves}")

        # Check game over overlay
        gameover_visible = self.page.evaluate("""() => {
            const el = document.getElementById('war-game-over');
            if (!el) return false;
            return el.style.display !== 'none' && el.offsetParent !== null;
        }""")
        _log(f"Game over overlay visible: {gameover_visible}")

        # Get any score text from the overlay
        gameover_text = self.page.evaluate("""() => {
            const el = document.getElementById('war-game-over');
            if (!el) return '';
            return el.textContent?.trim()?.substring(0, 200) || '';
        }""")
        _log(f"Game over text: '{gameover_text[:100]}'")

        path, img = _screenshot(self.page, "12_final_score")

        self._record_screenshot(
            test_name, "12_final_score", str(path),
            api_state={
                "result": result,
                "score": score,
                "eliminations": elims,
                "waves": waves,
                "gameover_visible": gameover_visible,
            },
        )

        details = {
            "result": result,
            "score": score,
            "eliminations": elims,
            "waves_completed": waves,
            "gameover_visible": gameover_visible,
            "gameover_text": gameover_text[:200],
        }
        # Score should be > 0 if any eliminations happened
        passed = score > 0 or elims > 0
        self._record(test_name, passed, details)

        assert passed, f"No score recorded. Score={score}, Elims={elims}"
        _log(f"Final score confirmed: {score} points, {elims} eliminations over {waves} waves")

        # Print grand summary
        print("\n" + "=" * 70)
        print("  BATTLE PROOF COMPLETE")
        print("=" * 70)
        print(f"  Result:       {result.upper()}")
        print(f"  Score:        {score}")
        print(f"  Eliminations: {elims}")
        print(f"  Waves:        {waves}")
        print(f"  Game Over UI: {'visible' if gameover_visible else 'not visible'}")
        print("=" * 70)
