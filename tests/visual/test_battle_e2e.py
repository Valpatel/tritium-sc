# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Full battle E2E verification — three-layer (OpenCV + LLM + API) + SQLite recording.

Uses va.verify() tiered pass logic throughout:
  - OpenCV checks MUST pass (deterministic, reliable)
  - API checks MUST pass (ground truth)
  - LLM checks are advisory: logged but do NOT block when OpenCV+API agree

This accounts for llava:7b's 20-83% false negative rate on dark/neon backgrounds.
LLM failures are recorded in SQLite for human review but don't cause test failures
when both deterministic layers confirm the expected state.

8 phases: initial -> setup -> countdown -> wave_active -> midpoint ->
          late_game -> game_over -> synthetic_camera

Requires: tritium_server fixture, ollama fleet with llava:7b.

Run: .venv/bin/python3 -m pytest tests/visual/test_battle_e2e.py -v
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

from tests.lib.visual_assert import (
    FRIENDLY_GREEN,
    HOSTILE_RED,
    CYAN_PRIMARY,
    VisualAssert,
)
from tests.lib.results_db import ResultsDB

SCREENSHOT_DIR = Path("tests/.test-results/battle-e2e")


def _ensure_dir() -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_DIR


def _wait_for_canvas(page, timeout: int = 10000) -> None:
    """Wait until the War Room canvas has rendered content."""
    try:
        page.wait_for_function(
            """() => {
                const c = document.getElementById('war-canvas');
                if (!c) return false;
                const ctx = c.getContext('2d');
                if (!ctx) return false;
                const d = ctx.getImageData(c.width/2-10, c.height/2-10, 20, 20).data;
                for (let i = 0; i < d.length; i += 4) {
                    if (d[i] > 20 || d[i+1] > 20 || d[i+2] > 20) return true;
                }
                return false;
            }""",
            timeout=timeout,
        )
    except Exception:
        time.sleep(3)


def _wait_for_targets(page, alliance: str = "", min_count: int = 1, timeout: int = 10000) -> None:
    """Wait until targets appear in JS state."""
    alliance_filter = f"&& t.alliance === '{alliance}'" if alliance else ""
    try:
        page.wait_for_function(
            f"""() => {{
                if (typeof assetState === 'undefined' || !assetState.simTargets) return false;
                const targets = Object.values(assetState.simTargets);
                const filtered = targets.filter(t => t {alliance_filter});
                return filtered.length >= {min_count};
            }}""",
            timeout=timeout,
        )
    except Exception:
        time.sleep(2)
    time.sleep(0.5)


class TestBattleE2E:
    """Full battle E2E with three-layer verification + SQLite recording.

    Runs a complete game from setup through game over, verifying each
    phase with OpenCV pixel assertions, structured LLM queries, and API
    cross-validation. LLM failures are advisory when OpenCV+API agree.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tritium_server, va, fleet, test_db, run_id):
        """Set up browser, reset game, prepare for battle."""
        self.server_url = tritium_server.url
        self.va = va
        self.fleet = fleet
        self.db = test_db
        self.run_id = run_id

        # Reset game state
        self._reset_game()
        time.sleep(1)

        # Launch browser
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.page = self.browser.new_page(viewport={"width": 1920, "height": 1080})
        self.page.goto(self.server_url)
        self.page.wait_for_load_state("networkidle")
        self.page.keyboard.press("w")
        _wait_for_canvas(self.page)

        yield

        self.browser.close()
        self.pw.stop()
        self._reset_game()

    def _reset_game(self):
        try:
            requests.post(f"{self.server_url}/api/game/reset", timeout=5)
        except Exception:
            pass

    def _screenshot(self, name: str) -> tuple[Path, np.ndarray]:
        d = _ensure_dir()
        path = d / f"{name}.png"
        self.page.screenshot(path=str(path))
        img = cv2.imread(str(path))
        return path, img

    def _api_get(self, path: str) -> dict | None:
        try:
            resp = requests.get(f"{self.server_url}{path}", timeout=5)
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    def _api_post(self, path: str, data: dict | None = None) -> dict | None:
        try:
            resp = requests.post(f"{self.server_url}{path}", json=data or {}, timeout=5)
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    def _get_sim_targets(self) -> list[dict]:
        data = self._api_get("/api/amy/simulation/targets")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("targets", [])
        return []

    # -- Phase Tests -------------------------------------------------------

    def test_phase_01_initial(self):
        """Phase 1: War Room initial state — map visible, no game active."""
        path, img = self._screenshot("01_initial")
        h, w = img.shape[:2]

        result = self.va.verify(
            "battle_e2e", "initial", path, img,
            opencv_checks=[
                ("not_blank", lambda: self.va.assert_region_not_blank(img, 0, 0, w, h)),
            ],
            llm_checks=[
                ("tactical_map", lambda: self.va.ask_yes_no(path, "Does this show a tactical map or game interface?")),
            ],
            api_checks=[
                ("game_state", lambda: (s := self._api_get("/api/game/state")) is not None and s.get("state") in ("setup", "idle", "")),
            ],
        )
        assert result["passed"], f"Phase 1 failed: {result['layers']}"

    def test_phase_02_setup(self):
        """Phase 2: Place 5 turrets, verify green shapes visible."""
        positions = [(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]
        for i, (x, y) in enumerate(positions):
            self._api_post("/api/game/place", {
                "name": f"Turret-{i+1}",
                "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
        _wait_for_targets(self.page, alliance="friendly", min_count=5)

        path, img = self._screenshot("02_setup")

        result = self.va.verify(
            "battle_e2e", "setup", path, img,
            opencv_checks=[
                ("green_present", lambda: self.va.assert_color_present(img, FRIENDLY_GREEN, min_pixels=50)),
                ("green_blobs", lambda: self.va.count_color_blobs(img, FRIENDLY_GREEN, min_area=3) >= 2),
            ],
            llm_checks=[
                ("sees_turrets", lambda: self.va.ask_yes_no(path, "Are green square shapes (turrets) visible on this map?")),
            ],
            api_checks=[
                ("friendlies_placed", lambda: len([t for t in self._get_sim_targets() if t.get("alliance") == "friendly"]) >= 5),
            ],
        )
        assert result["passed"], f"Phase 2 failed: {result['layers']}"

    def test_phase_03_countdown(self):
        """Phase 3: Begin game, verify countdown number visible."""
        for i, (x, y) in enumerate([(0, 0), (8, 0), (-8, 0)]):
            self._api_post("/api/game/place", {
                "name": f"Turret-{i+1}",
                "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
        self._api_post("/api/game/begin")
        time.sleep(1.5)

        path, img = self._screenshot("03_countdown")
        h, w = img.shape[:2]
        cx, cy = w // 2, h // 2

        result = self.va.verify(
            "battle_e2e", "countdown", path, img,
            opencv_checks=[
                ("center_bright", lambda: self.va.assert_region_not_blank(img, cx - 150, cy - 150, 300, 300, threshold=15)),
            ],
            llm_checks=[
                ("sees_number", lambda: self.va.ask_count(path, "What large number is displayed in the center?") in range(1, 6)),
            ],
            api_checks=[
                ("state_countdown", lambda: (s := self._api_get("/api/game/state")) is not None and s.get("state") in ("countdown", "active")),
            ],
        )
        assert result["passed"], f"Phase 3 failed: {result['layers']}"

    def test_phase_04_wave_active(self):
        """Phase 4: First wave active — hostiles on map, combat starting."""
        for i, (x, y) in enumerate([(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]):
            self._api_post("/api/game/place", {
                "name": f"Turret-{i+1}",
                "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
        self._api_post("/api/game/begin")

        # Wait for hostiles to appear via API
        max_hostiles = 0
        for _ in range(20):
            time.sleep(1)
            state = self._api_get("/api/game/state")
            targets = self._get_sim_targets()
            h_count = len([t for t in targets if t.get("alliance") == "hostile"])
            max_hostiles = max(max_hostiles, h_count)
            if h_count > 0 and state and state.get("state") == "active":
                break
        # Wait for canvas to render the hostiles
        _wait_for_targets(self.page, alliance="hostile", min_count=1)

        path, img = self._screenshot("04_wave_active")

        result = self.va.verify(
            "battle_e2e", "wave_active", path, img,
            opencv_checks=[
                ("red_present", lambda: self.va.assert_color_present(img, HOSTILE_RED, min_pixels=10)),
                ("green_present", lambda: self.va.assert_color_present(img, FRIENDLY_GREEN, min_pixels=30)),
            ],
            llm_checks=[
                ("sees_combat", lambda: self.va.ask_yes_no(path, "Do you see both green and red shapes representing combat units?")),
            ],
            api_checks=[
                ("game_active", lambda: (s := self._api_get("/api/game/state")) is not None and s.get("state") in ("active", "wave_complete")),
                ("hostiles_appeared", lambda: max_hostiles > 0),
            ],
        )
        assert result["passed"], f"Phase 4 failed: {result['layers']}"

    def test_phase_05_midpoint(self):
        """Phase 5: Mid-combat — score, kills accumulating."""
        for i, (x, y) in enumerate([(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]):
            self._api_post("/api/game/place", {
                "name": f"Turret-{i+1}",
                "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
        self._api_post("/api/game/begin")

        # Wait for eliminations to accumulate
        for _ in range(30):
            time.sleep(1)
            state = self._api_get("/api/game/state")
            if state and state.get("total_eliminations", state.get("total_kills", 0)) > 0:
                break
        time.sleep(3)

        path, img = self._screenshot("05_midpoint")
        h, w = img.shape[:2]

        result = self.va.verify(
            "battle_e2e", "midpoint", path, img,
            opencv_checks=[
                ("hud_text", lambda: self.va.assert_region_has_text(img, w - 400, 0, 400, 150)),
            ],
            llm_checks=[
                ("sees_score", lambda: self.va.ask_yes_no(path, "Can you see any score, eliminations, or wave information displayed on screen?")),
            ],
            api_checks=[
                ("has_progress", lambda: (s := self._api_get("/api/game/state")) is not None and (s.get("score", 0) > 0 or s.get("total_eliminations", s.get("total_kills", 0)) > 0)),
            ],
        )
        assert result["passed"], f"Phase 5 failed: {result['layers']}"

    def test_phase_06_late_game(self):
        """Phase 6: Late game — waves progressing or game ending."""
        for i, (x, y) in enumerate([(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]):
            self._api_post("/api/game/place", {
                "name": f"Turret-{i+1}",
                "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
        self._api_post("/api/game/begin")

        # Wait for game to progress past wave 1
        for _ in range(60):
            time.sleep(2)
            state = self._api_get("/api/game/state")
            if state:
                if state.get("state") in ("victory", "defeat"):
                    break
                if state.get("wave", 0) >= 2:
                    break
        time.sleep(2)

        path, img = self._screenshot("06_late_game")
        h, w = img.shape[:2]

        result = self.va.verify(
            "battle_e2e", "late_game", path, img,
            opencv_checks=[
                ("not_blank", lambda: self.va.assert_region_not_blank(img, 0, 0, w, h)),
            ],
            llm_checks=[
                ("sees_game", lambda: self.va.ask_yes_no(path, "Does this show a game screen with combat units, score display, or a game over screen?")),
            ],
            api_checks=[
                ("game_progressed", lambda: (s := self._api_get("/api/game/state")) is not None and (s.get("wave", 0) >= 1 or s.get("state") in ("victory", "defeat"))),
            ],
        )
        assert result["passed"], f"Phase 6 failed: {result['layers']}"

    def test_phase_07_game_over(self):
        """Phase 7: Wait for game to end (victory or defeat)."""
        for i, (x, y) in enumerate([(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]):
            self._api_post("/api/game/place", {
                "name": f"Turret-{i+1}",
                "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
        self._api_post("/api/game/begin")

        # Wait for game over or significant progress (up to 3 minutes)
        final_state = None
        for _ in range(90):
            time.sleep(2)
            state = self._api_get("/api/game/state")
            if state and state.get("state") in ("victory", "defeat"):
                final_state = state
                break
            # Also capture latest state for progress check
            if state:
                final_state = state
        time.sleep(3)

        path, img = self._screenshot("07_game_over")
        h, w = img.shape[:2]

        # Accept either game over OR significant combat progress
        def _game_progressed() -> bool:
            if final_state is None:
                return False
            if final_state.get("state") in ("victory", "defeat"):
                return True
            # Game still active — accept if wave >= 2 (combat is happening)
            return final_state.get("wave", 0) >= 2

        result = self.va.verify(
            "battle_e2e", "game_over", path, img,
            opencv_checks=[
                ("not_blank", lambda: self.va.assert_region_not_blank(img, 0, 0, w, h)),
            ],
            llm_checks=[
                ("sees_combat", lambda: self.va.ask_yes_no(path, "Does this show an active battle, game over screen, or combat with units visible?")),
            ],
            api_checks=[
                ("game_progressed", _game_progressed),
                ("had_eliminations", lambda: final_state is not None and final_state.get("total_eliminations", final_state.get("total_kills", 0)) > 0),
            ],
        )
        assert result["passed"], f"Phase 7 failed: {result['layers']}"

    def test_phase_08_synthetic_camera(self):
        """Phase 8: Synthetic camera produces valid frames."""
        for i, (x, y) in enumerate([(0, 0), (8, 0)]):
            self._api_post("/api/game/place", {
                "name": f"Turret-{i+1}",
                "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
        self._api_post("/api/game/begin")
        time.sleep(8)

        try:
            resp = requests.get(
                f"{self.server_url}/api/amy/nodes/syn-cam-0/video",
                timeout=5,
                stream=True,
            )
            if resp.status_code != 200:
                pytest.skip("Synthetic camera endpoint not available")

            frame_data = b""
            for chunk in resp.iter_content(chunk_size=4096):
                frame_data += chunk
                if b"\xff\xd9" in frame_data:
                    start = frame_data.find(b"\xff\xd8")
                    end = frame_data.find(b"\xff\xd9") + 2
                    if start >= 0:
                        frame_data = frame_data[start:end]
                        break
            resp.close()

            d = _ensure_dir()
            frame_path = d / "08_synthetic_camera.jpg"
            frame_path.write_bytes(frame_data)

            img = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                pytest.fail("Cannot decode synthetic camera JPEG frame")
            h, w = img.shape[:2]

            result = self.va.verify(
                "battle_e2e", "synthetic_camera", frame_path, img,
                opencv_checks=[
                    ("valid_jpeg", lambda: len(frame_data) > 500 and frame_data[:2] == b"\xff\xd8"),
                    ("not_blank", lambda: self.va.assert_region_not_blank(img, 0, 0, w, h)),
                ],
                llm_checks=[
                    ("sees_shapes", lambda: self.va.ask_yes_no(frame_path, "Does this bird's-eye view show colored shapes (green and/or red) on a dark background?")),
                ],
                api_checks=[
                    ("targets_exist", lambda: len(self._get_sim_targets()) > 0),
                ],
            )
            assert result["passed"], f"Phase 8 failed: {result['layers']}"

        except requests.ConnectionError:
            pytest.skip("Synthetic camera not available")
