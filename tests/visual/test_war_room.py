# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""War Room visual verification — three-layer (OpenCV + LLM + API).

Every test uses va.verify() with tiered pass logic:
  - OpenCV checks MUST pass (deterministic, reliable)
  - API checks MUST pass (ground truth)
  - LLM checks are advisory: logged but do NOT block when OpenCV+API agree

This design accounts for llava:7b's 20-83% false negative rate on dark/neon
backgrounds. LLM failures are recorded for human review but don't fail the test
when both deterministic layers agree the state is correct.

Requires: tritium_server fixture (auto-started), ollama fleet with llava:7b.

Run: .venv/bin/python3 -m pytest tests/visual/test_war_room.py -v
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

from tests.lib.visual_assert import (
    CYAN_PRIMARY,
    FRIENDLY_GREEN,
    HOSTILE_RED,
    VisualAssert,
)

SCREENSHOT_DIR = Path("tests/.test-results/war-room-screenshots")


def _ensure_dir() -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_DIR


def _launch_browser(server_url: str):
    """Launch Playwright browser and navigate to War Room."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    # Navigate to War Room
    page.keyboard.press("w")
    # Wait for canvas to actually initialize and render a frame
    _wait_for_canvas(page)
    return pw, browser, page


def _wait_for_canvas(page, timeout: int = 10000) -> None:
    """Wait until the War Room canvas has rendered content.

    Polls the canvas for non-blank pixels. Headless Chromium may lag
    behind API state changes — this replaces fixed time.sleep() calls.
    """
    try:
        page.wait_for_function(
            """() => {
                const c = document.getElementById('war-canvas');
                if (!c) return false;
                const ctx = c.getContext('2d');
                if (!ctx) return false;
                // Sample center pixels — if any are non-black, canvas has rendered
                const d = ctx.getImageData(c.width/2-10, c.height/2-10, 20, 20).data;
                for (let i = 0; i < d.length; i += 4) {
                    if (d[i] > 20 || d[i+1] > 20 || d[i+2] > 20) return true;
                }
                return false;
            }""",
            timeout=timeout,
        )
    except Exception:
        # Fallback: canvas may not have the id or getContext fails in headless
        time.sleep(3)


def _wait_for_targets(page, alliance: str = "", min_count: int = 1, timeout: int = 10000) -> None:
    """Wait until targets appear on the canvas via JS state.

    Args:
        page: Playwright page
        alliance: Filter by alliance ('friendly', 'hostile', or '' for any)
        min_count: Minimum number of matching targets
        timeout: Max wait in ms
    """
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
    # Extra frame for canvas to actually draw the targets
    time.sleep(0.5)


def _screenshot(page, name: str) -> tuple[Path, np.ndarray]:
    """Take screenshot, return path and numpy array."""
    d = _ensure_dir()
    path = d / f"{name}.png"
    page.screenshot(path=str(path))
    img = cv2.imread(str(path))
    return path, img


def _place_turrets(server_url: str, count: int = 5) -> list[dict]:
    """Place turrets via API and return responses."""
    positions = [(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]
    results = []
    for i, (x, y) in enumerate(positions[:count]):
        try:
            resp = requests.post(
                f"{server_url}/api/game/place",
                json={"name": f"Turret-{i+1}", "asset_type": "turret", "position": {"x": x, "y": y}},
                timeout=5,
            )
            results.append(resp.json() if resp.status_code == 200 else {})
        except Exception:
            results.append({})
    return results


def _begin_game(server_url: str) -> dict | None:
    """Start game via API."""
    try:
        resp = requests.post(f"{server_url}/api/game/begin", timeout=5)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def _get_game_state(server_url: str) -> dict | None:
    """Get current game state."""
    try:
        resp = requests.get(f"{server_url}/api/game/state", timeout=5)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def _get_sim_targets(server_url: str) -> list[dict]:
    """Get simulation targets (handles both list and {targets:[]} formats)."""
    try:
        resp = requests.get(f"{server_url}/api/amy/simulation/targets", timeout=5)
        data = resp.json() if resp.status_code == 200 else []
        if isinstance(data, dict):
            return data.get("targets", [])
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _reset_game(server_url: str) -> None:
    """Reset game state."""
    try:
        requests.post(f"{server_url}/api/game/reset", timeout=5)
    except Exception:
        pass


class TestWarRoomVisual:
    """Three-layer verification of War Room Canvas 2D rendering.

    Uses va.verify() tiered pass logic:
    - OpenCV: deterministic pixel checks (MUST pass)
    - API: ground truth state (MUST pass)
    - LLM: advisory only when OpenCV+API agree (accounts for 20-83% false negative rate)
    """

    @pytest.fixture(autouse=True)
    def _setup_browser(self, tritium_server, va):
        """Set up browser for each test, tear down after."""
        self.server_url = tritium_server.url
        self.va = va
        _reset_game(self.server_url)
        time.sleep(1)
        self.pw, self.browser, self.page = _launch_browser(self.server_url)
        yield
        self.browser.close()
        self.pw.stop()
        _reset_game(self.server_url)

    def test_initial_view(self):
        """War Room shows map with canvas content."""
        path, img = _screenshot(self.page, "initial_view")
        h, w = img.shape[:2]

        result = self.va.verify(
            "war_room", "initial_view", path, img,
            opencv_checks=[
                ("not_blank", lambda: self.va.assert_region_not_blank(img, 0, 0, w, h)),
            ],
            llm_checks=[
                ("tactical_map", lambda: self.va.ask_yes_no(path, "Does this show a tactical map or game interface?")),
            ],
            api_checks=[
                ("game_state", lambda: self.va.api_get("/api/game/state") is not None),
            ],
        )
        assert result["passed"], f"test_initial_view failed: {result['layers']}"

    def test_turrets_render_green(self):
        """Placed turrets appear as green shapes on canvas."""
        _place_turrets(self.server_url, 5)
        _wait_for_targets(self.page, alliance="friendly", min_count=5)

        path, img = _screenshot(self.page, "turrets_green")

        result = self.va.verify(
            "war_room", "turrets_green", path, img,
            opencv_checks=[
                ("green_present", lambda: self.va.assert_color_present(img, FRIENDLY_GREEN, min_pixels=50)),
                ("green_blobs", lambda: self.va.count_color_blobs(img, FRIENDLY_GREEN, min_area=3) >= 2),
            ],
            llm_checks=[
                ("sees_green", lambda: self.va.ask_yes_no(path, "Are green square shapes visible on this tactical map?")),
                ("green_count", lambda: self.va.ask_count(path, "How many green squares or green markers are visible?") >= 3),
            ],
            api_checks=[
                ("friendlies_placed", lambda: len([t for t in _get_sim_targets(self.server_url) if t.get("alliance") == "friendly"]) >= 5),
            ],
        )
        assert result["passed"], f"test_turrets_render_green failed: {result['layers']}"

    def test_hostiles_render_red(self):
        """Hostile units appear as red diamond shapes after game starts."""
        _place_turrets(self.server_url, 3)
        _begin_game(self.server_url)
        # Wait for hostiles to spawn via API
        for _ in range(15):
            time.sleep(1)
            targets = _get_sim_targets(self.server_url)
            hostiles = [t for t in targets if t.get("alliance") == "hostile"]
            if len(hostiles) > 0:
                break
        # Wait for canvas to render them
        _wait_for_targets(self.page, alliance="hostile", min_count=1)

        path, img = _screenshot(self.page, "hostiles_red")

        result = self.va.verify(
            "war_room", "hostiles_red", path, img,
            opencv_checks=[
                ("red_present", lambda: self.va.assert_color_present(img, HOSTILE_RED, min_pixels=20)),
            ],
            llm_checks=[
                ("sees_red", lambda: self.va.ask_yes_no(path, "Are red diamond shapes or red markers visible?")),
            ],
            api_checks=[
                ("hostiles_exist", lambda: len([t for t in _get_sim_targets(self.server_url) if t.get("alliance") == "hostile"]) > 0),
            ],
        )
        assert result["passed"], f"test_hostiles_render_red failed: {result['layers']}"

    def test_countdown_renders(self):
        """Countdown shows large number in center."""
        _place_turrets(self.server_url, 2)
        _begin_game(self.server_url)
        time.sleep(1.5)

        path, img = _screenshot(self.page, "countdown")
        h, w = img.shape[:2]
        cx, cy = w // 2, h // 2
        region_size = 200
        x1 = max(0, cx - region_size)
        y1 = max(0, cy - region_size)

        result = self.va.verify(
            "war_room", "countdown", path, img,
            opencv_checks=[
                ("center_bright", lambda: self.va.assert_region_not_blank(img, x1, y1, region_size * 2, region_size * 2, threshold=15)),
            ],
            llm_checks=[
                ("sees_number", lambda: self.va.ask_count(path, "What large number is displayed in the center of the screen?") in [1, 2, 3, 4, 5]),
            ],
            api_checks=[
                ("state_countdown", lambda: _get_game_state(self.server_url) is not None and _get_game_state(self.server_url).get("state") in ("countdown", "active")),
            ],
        )
        assert result["passed"], f"test_countdown_renders failed: {result['layers']}"

    def test_hud_score_visible(self):
        """HUD shows score during active game."""
        _place_turrets(self.server_url, 3)
        _begin_game(self.server_url)
        # Wait for active state
        for _ in range(10):
            time.sleep(1)
            state = _get_game_state(self.server_url)
            if state and state.get("state") == "active":
                break
        time.sleep(3)

        path, img = _screenshot(self.page, "hud_score")
        h, w = img.shape[:2]

        result = self.va.verify(
            "war_room", "hud_score", path, img,
            opencv_checks=[
                ("hud_text", lambda: self.va.assert_region_has_text(img, w - 400, 0, 400, 100)),
            ],
            llm_checks=[
                ("sees_score", lambda: self.va.ask_yes_no(path, "Is a score display or score number visible on this screen?")),
            ],
            api_checks=[
                ("has_score", lambda: _get_game_state(self.server_url) is not None and "score" in _get_game_state(self.server_url)),
            ],
        )
        assert result["passed"], f"test_hud_score_visible failed: {result['layers']}"

    def test_minimap_present(self):
        """Minimap renders in bottom-left corner."""
        _place_turrets(self.server_url, 3)
        _wait_for_targets(self.page, alliance="friendly", min_count=3)

        path, img = _screenshot(self.page, "minimap")
        h, w = img.shape[:2]
        minimap_size = 150

        result = self.va.verify(
            "war_room", "minimap", path, img,
            opencv_checks=[
                ("bottom_left_content", lambda: self.va.assert_region_not_blank(img, 0, h - minimap_size, minimap_size, minimap_size)),
            ],
            llm_checks=[
                ("sees_minimap", lambda: self.va.ask_yes_no(path, "Is there a minimap or small overview map in the bottom-left corner?")),
            ],
            api_checks=[
                ("targets_exist", lambda: len(_get_sim_targets(self.server_url)) > 0),
            ],
        )
        assert result["passed"], f"test_minimap_present failed: {result['layers']}"

    def test_projectile_trails(self):
        """Projectile trails visible during combat."""
        _place_turrets(self.server_url, 5)
        _begin_game(self.server_url)
        # Wait for active combat with kills
        for _ in range(20):
            time.sleep(1)
            state = _get_game_state(self.server_url)
            if state and state.get("state") == "active" and state.get("total_kills", 0) > 0:
                break
        time.sleep(2)

        path, img = _screenshot(self.page, "projectile_trails")

        def _check_trails() -> bool:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, bright = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
            edges = cv2.Canny(bright, 50, 150)
            lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=20,
                                    minLineLength=15, maxLineGap=10)
            return lines is not None and len(lines) >= 1

        result = self.va.verify(
            "war_room", "projectile_trails", path, img,
            opencv_checks=[
                ("bright_lines", _check_trails),
            ],
            llm_checks=[
                ("sees_trails", lambda: self.va.ask_yes_no(path, "Are there lines, trails, or projectile effects between units?")),
            ],
            api_checks=[
                ("combat_active", lambda: _get_game_state(self.server_url) is not None and _get_game_state(self.server_url).get("state") in ("active", "wave_complete", "victory", "defeat")),
            ],
        )
        assert result["passed"], f"test_projectile_trails failed: {result['layers']}"

    def test_health_bars(self):
        """Health bars visible above damaged units."""
        _place_turrets(self.server_url, 5)
        _begin_game(self.server_url)
        # Wait for damage to occur
        for _ in range(25):
            time.sleep(1)
            targets = _get_sim_targets(self.server_url)
            damaged = [t for t in targets
                       if t.get("health", 100) < t.get("max_health", 100)
                       and t.get("health", 0) > 0]
            if len(damaged) > 0:
                break
        time.sleep(2)

        path, img = _screenshot(self.page, "health_bars")

        def _count_health_bars() -> bool:
            total = 0
            for bgr_color in [FRIENDLY_GREEN, HOSTILE_RED]:
                lower = np.array([max(0, c - 40) for c in bgr_color], dtype=np.uint8)
                upper = np.array([min(255, c + 40) for c in bgr_color], dtype=np.uint8)
                mask = cv2.inRange(img, lower, upper)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for c in contours:
                    x, y, w, h = cv2.boundingRect(c)
                    if w > 6 and h >= 2 and w / max(h, 1) > 2.0 and cv2.contourArea(c) >= 10:
                        total += 1
            return total >= 1

        result = self.va.verify(
            "war_room", "health_bars", path, img,
            opencv_checks=[
                ("bar_shapes", _count_health_bars),
            ],
            llm_checks=[
                ("sees_bars", lambda: self.va.ask_yes_no(path, "Are health bars visible above any units or characters?")),
            ],
            api_checks=[
                ("damaged_units", lambda: len([t for t in _get_sim_targets(self.server_url) if t.get("health", 100) < t.get("max_health", 100)]) > 0),
            ],
        )
        assert result["passed"], f"test_health_bars failed: {result['layers']}"

    def test_wave_banner(self):
        """Wave transition shows banner text."""
        _place_turrets(self.server_url, 5)
        _begin_game(self.server_url)
        # Wait for first wave
        for _ in range(15):
            time.sleep(1)
            state = _get_game_state(self.server_url)
            if state and state.get("wave", 0) >= 1:
                break

        path, img = _screenshot(self.page, "wave_banner")
        h, w = img.shape[:2]

        def _check_center_bright() -> bool:
            cx, cy = w // 2, h // 2
            banner_w, banner_h = min(600, w // 2), min(200, h // 4)
            x1 = max(0, cx - banner_w // 2)
            y1 = max(0, cy - banner_h // 2)
            return self.va.assert_region_not_blank(img, x1, y1, banner_w, banner_h, threshold=15)

        result = self.va.verify(
            "war_room", "wave_banner", path, img,
            opencv_checks=[
                ("center_bright", _check_center_bright),
            ],
            llm_checks=[
                ("sees_wave", lambda: self.va.ask_yes_no(path, "Is there a wave banner, wave number text, or wave indicator?")),
            ],
            api_checks=[
                ("wave_started", lambda: _get_game_state(self.server_url) is not None and _get_game_state(self.server_url).get("wave", 0) >= 1),
            ],
        )
        assert result["passed"], f"test_wave_banner failed: {result['layers']}"

    def test_elimination_feed(self):
        """Elimination feed shows neutralization messages after eliminations."""
        _place_turrets(self.server_url, 5)
        _begin_game(self.server_url)
        # Wait for eliminations
        for _ in range(30):
            time.sleep(1)
            state = _get_game_state(self.server_url)
            if state and state.get("total_eliminations", state.get("total_kills", 0)) > 0:
                break
        time.sleep(2)

        path, img = _screenshot(self.page, "elimination_feed")
        h, w = img.shape[:2]

        def _check_elimination_feed_text() -> bool:
            feed_w = min(400, w // 3)
            feed_h = min(300, h // 2)
            x1 = w - feed_w
            region = img[0:feed_h, x1:x1+feed_w]
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            text_regions = [c for c in contours if 3 < cv2.contourArea(c) < 3000]
            return len(text_regions) >= 2

        result = self.va.verify(
            "war_room", "elimination_feed", path, img,
            opencv_checks=[
                ("feed_text", _check_elimination_feed_text),
            ],
            llm_checks=[
                ("sees_eliminations", lambda: self.va.ask_yes_no(
                    path,
                    "Is there colored text showing elimination messages, neutralization notifications, "
                    "or an elimination feed on the right side of the screen?",
                )),
            ],
            api_checks=[
                ("eliminations_recorded", lambda: _get_game_state(self.server_url) is not None and _get_game_state(self.server_url).get("total_eliminations", _get_game_state(self.server_url).get("total_kills", 0)) > 0),
            ],
        )
        assert result["passed"], f"test_elimination_feed failed: {result['layers']}"
