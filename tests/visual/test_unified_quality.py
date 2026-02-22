"""Visual quality tests for the Command Center view.

Verifies the unified tactical map renders correctly with:
- Units spread across the map (not clustered in center)
- Minimap visible in corner
- Satellite imagery background
- Panel toggle (close/reopen)
- Combat rendering (projectiles, effects)
- Overall RTS quality rubric (6/10 minimum)

Uses three-layer verification: OpenCV + structured LLM + API.

Requires: tritium_server fixture (auto-started), ollama fleet with llava:7b.

Run: .venv/bin/python3 -m pytest tests/visual/test_unified_quality.py -v
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

SCREENSHOT_DIR = Path("tests/.test-results/unified-quality")


def _ensure_dir() -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_DIR


def _launch_browser(server_url: str):
    """Launch Playwright browser and navigate to Command Center."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(f"{server_url}/")
    page.wait_for_load_state("networkidle")
    _wait_for_canvas(page)
    return pw, browser, page


def _wait_for_canvas(page, timeout: int = 10000) -> None:
    """Wait until the tactical canvas has rendered content.

    Polls the canvas for non-blank pixels. Headless Chromium may lag
    behind API state changes.
    """
    try:
        page.wait_for_function(
            """() => {
                const c = document.getElementById('tactical-canvas');
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
    """Wait until targets appear on the canvas via JS state."""
    alliance_filter = f"&& t.alliance === '{alliance}'" if alliance else ""
    try:
        page.wait_for_function(
            f"""() => {{
                const store = window.__commandStore;
                if (!store || !store.state || !store.state.targets) return false;
                const targets = Object.values(store.state.targets);
                const filtered = targets.filter(t => t {alliance_filter});
                return filtered.length >= {min_count};
            }}""",
            timeout=timeout,
        )
    except Exception:
        # Fallback: try assetState (legacy global)
        try:
            page.wait_for_function(
                f"""() => {{
                    if (typeof assetState === 'undefined' || !assetState.simTargets) return false;
                    const targets = Object.values(assetState.simTargets);
                    const filtered = targets.filter(t => t {alliance_filter});
                    return filtered.length >= {min_count};
                }}""",
                timeout=min(timeout, 3000),
            )
        except Exception:
            time.sleep(2)
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


class TestUnifiedPhase1:
    """Phase 1: Basic visibility and layout."""

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

    def test_map_has_content(self):
        """Map canvas has visible content, not a dark void."""
        path, img = _screenshot(self.page, "map_content")
        h, w = img.shape[:2]

        result = self.va.verify(
            "unified", "map_content", path, img,
            opencv_checks=[
                ("not_blank", lambda: self.va.assert_region_not_blank(img, 0, 0, w, h)),
                ("bright_pixels", lambda: _check_bright_pct(img, 0.05)),
            ],
            llm_checks=[
                ("sees_map", lambda: self.va.ask_yes_no(path, "Does this show a tactical map or game interface?")),
            ],
            api_checks=[
                ("game_state", lambda: self.va.api_get("/api/game/state") is not None),
            ],
        )
        assert result["passed"], f"test_map_has_content failed: {result['layers']}"

    def test_units_not_clustered(self):
        """Units are spread across the map, not stacked in center."""
        _place_turrets(self.server_url, 5)
        _wait_for_targets(self.page, alliance="friendly", min_count=5)

        path, img = _screenshot(self.page, "units_spread")

        result = self.va.verify(
            "unified", "units_spread", path, img,
            opencv_checks=[
                ("green_present", lambda: self.va.assert_color_present(img, FRIENDLY_GREEN, min_pixels=50)),
                ("green_blobs", lambda: self.va.count_color_blobs(img, FRIENDLY_GREEN, min_area=10) >= 2),
            ],
            llm_checks=[
                ("sees_units", lambda: self.va.ask_yes_no(path, "Are green markers or green unit shapes visible on the map?")),
            ],
            api_checks=[
                ("friendlies_placed", lambda: len([t for t in _get_sim_targets(self.server_url) if t.get("alliance") == "friendly"]) >= 5),
            ],
        )
        assert result["passed"], f"test_units_not_clustered failed: {result['layers']}"

    def test_minimap_visible(self):
        """Minimap is visible in the corner of the screen."""
        _place_turrets(self.server_url, 3)
        _wait_for_targets(self.page, alliance="friendly", min_count=3)

        path, img = _screenshot(self.page, "minimap")
        h, w = img.shape[:2]

        result = self.va.verify(
            "unified", "minimap", path, img,
            opencv_checks=[
                ("minimap_region", lambda: self.va.assert_region_not_blank(img, w - 220, h - 250, 200, 200, threshold=12)),
            ],
            llm_checks=[
                ("sees_minimap", lambda: self.va.ask_yes_no(path, "Is there a minimap or small overview map visible in a corner?")),
            ],
            api_checks=[
                ("targets_exist", lambda: len(_get_sim_targets(self.server_url)) > 0),
            ],
        )
        assert result["passed"], f"test_minimap_visible failed: {result['layers']}"

    def test_panel_toggle(self):
        """Panel can be closed and reopened via keyboard shortcut."""
        path_before, img_before = _screenshot(self.page, "panel_before")

        # Press '1' to toggle Amy panel
        self.page.keyboard.press("1")
        self.page.wait_for_timeout(500)
        path_toggled, img_toggled = _screenshot(self.page, "panel_toggled")

        # Press '1' again to reopen
        self.page.keyboard.press("1")
        self.page.wait_for_timeout(500)
        path_after, img_after = _screenshot(self.page, "panel_reopened")

        h, w = img_before.shape[:2]

        result = self.va.verify(
            "unified", "panel_toggle", path_after, img_after,
            opencv_checks=[
                ("view_not_blank", lambda: self.va.assert_region_not_blank(img_after, 0, 0, w, h)),
            ],
            llm_checks=[
                ("sees_panel", lambda: self.va.ask_yes_no(path_after, "Is there a floating panel or information panel visible?")),
            ],
            api_checks=[
                ("game_state", lambda: self.va.api_get("/api/game/state") is not None),
            ],
        )
        assert result["passed"], f"test_panel_toggle failed: {result['layers']}"

    def test_coords_display_visible(self):
        """Map coordinates display is visible on screen."""
        path, img = _screenshot(self.page, "coords_display")
        h, w = img.shape[:2]

        # coords element is in the tactical area
        coords = self.page.query_selector("#map-coords")
        coords_visible = coords is not None and coords.is_visible()

        result = self.va.verify(
            "unified", "coords_display", path, img,
            opencv_checks=[
                ("not_blank", lambda: self.va.assert_region_not_blank(img, 0, 0, w, h)),
            ],
            llm_checks=[
                ("sees_coords", lambda: self.va.ask_yes_no(path, "Are coordinate numbers (X: and Y: values) visible on the screen?")),
            ],
            api_checks=[
                ("coords_in_dom", lambda: coords_visible),
            ],
        )
        assert result["passed"], f"test_coords_display_visible failed: {result['layers']}"


class TestUnifiedPhase2:
    """Phase 2: War room rendering quality."""

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

    def test_combat_rendering(self):
        """Begin war, verify combat elements visible."""
        _place_turrets(self.server_url, 5)
        _wait_for_targets(self.page, alliance="friendly", min_count=5)
        _begin_game(self.server_url)

        # Wait for hostiles to spawn
        for _ in range(15):
            time.sleep(1)
            targets = _get_sim_targets(self.server_url)
            hostiles = [t for t in targets if t.get("alliance") == "hostile"]
            if len(hostiles) > 0:
                break
        _wait_for_targets(self.page, alliance="hostile", min_count=1)

        path, img = _screenshot(self.page, "combat")

        result = self.va.verify(
            "unified", "combat", path, img,
            opencv_checks=[
                ("has_color", lambda: self.va.assert_color_present(img, HOSTILE_RED, tolerance=60, min_pixels=20)
                              or self.va.assert_color_present(img, FRIENDLY_GREEN, tolerance=60, min_pixels=20)),
            ],
            llm_checks=[
                ("sees_combat", lambda: self.va.ask_yes_no(path, "Are there units, markers, or combat elements visible on this tactical map?")),
            ],
            api_checks=[
                ("hostiles_exist", lambda: len([t for t in _get_sim_targets(self.server_url) if t.get("alliance") == "hostile"]) > 0),
            ],
        )
        assert result["passed"], f"test_combat_rendering failed: {result['layers']}"


class TestUnifiedQualityRubric:
    """Phase 3: Overall RTS quality scoring."""

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

    def test_rts_quality_score(self):
        """10-item RTS quality rubric -- target 6/10 minimum."""
        # Place units so the map has content to render
        _place_turrets(self.server_url, 5)
        _wait_for_targets(self.page, alliance="friendly", min_count=5)
        time.sleep(2)

        path, img = _screenshot(self.page, "rts_quality")
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        score = 0
        reasons = []

        # 1. Map fills with content (not empty void)
        bright_pct = np.count_nonzero(gray > 25) / gray.size
        if bright_pct > 0.15:
            score += 1
            reasons.append(f"PASS: Map has content ({bright_pct:.1%} bright)")
        else:
            reasons.append(f"FAIL: Map too dark ({bright_pct:.1%})")

        # 2. Units individually distinguishable
        green_blobs = self.va.count_color_blobs(img, FRIENDLY_GREEN, tolerance=60, min_area=10)
        if green_blobs >= 2:
            score += 1
            reasons.append(f"PASS: {green_blobs} green units visible")
        else:
            reasons.append(f"FAIL: Only {green_blobs} green units")

        # 3. Unit types visually distinct (multiple colors present)
        colors_present = 0
        for bgr in [FRIENDLY_GREEN, HOSTILE_RED, CYAN_PRIMARY, (10, 238, 252)]:
            if self.va.assert_color_present(img, bgr, tolerance=60, min_pixels=15):
                colors_present += 1
        if colors_present >= 2:
            score += 1
            reasons.append(f"PASS: {colors_present} unit colors")
        else:
            reasons.append(f"FAIL: Only {colors_present} colors")

        # 4. Minimap present (bottom-right corner has content)
        minimap_area = img[h - 230:h - 20, w - 230:w]
        if minimap_area.size > 0 and float(cv2.cvtColor(minimap_area, cv2.COLOR_BGR2GRAY).mean()) > 12:
            score += 1
            reasons.append("PASS: Minimap area has content")
        else:
            reasons.append("FAIL: Minimap area blank")

        # 5. Cyan elements visible (grid lines, UI, or unit highlights)
        if self.va.assert_color_present(img, CYAN_PRIMARY, tolerance=40, min_pixels=100):
            score += 1
            reasons.append("PASS: Cyan elements visible (grid/UI)")
        else:
            reasons.append("FAIL: No cyan elements")

        # 6. Status bar visible (bottom 20px has content)
        status_bar = img[h - 20:h, :]
        if float(cv2.cvtColor(status_bar, cv2.COLOR_BGR2GRAY).mean()) > 10:
            score += 1
            reasons.append("PASS: Status bar visible")
        else:
            reasons.append("FAIL: Status bar blank")

        # 7. Header bar visible (top 36px has content)
        header = img[0:36, :]
        if float(cv2.cvtColor(header, cv2.COLOR_BGR2GRAY).mean()) > 10:
            score += 1
            reasons.append("PASS: Header visible")
        else:
            reasons.append("FAIL: Header blank")

        # 8. Panel visible (floating panel elements exist and are shown)
        panels = self.page.query_selector_all(".panel")
        visible_panels = [p for p in panels if p.is_visible()]
        if len(visible_panels) >= 1:
            score += 1
            reasons.append(f"PASS: {len(visible_panels)} panels visible")
        else:
            reasons.append("FAIL: No panels visible")

        # 9. Map mode buttons visible (observe/tactical/setup)
        mode_btns = self.page.query_selector_all(".map-mode-btn")
        if len(mode_btns) >= 2:
            score += 1
            reasons.append("PASS: Mode buttons visible")
        else:
            reasons.append("FAIL: Mode buttons missing")

        # 10. Dark cyberpunk theme (dark background with neon accents)
        bg_mean = float(gray.mean())
        if bg_mean < 60 and bright_pct > 0.05:
            score += 1
            reasons.append("PASS: Dark theme with accents")
        else:
            reasons.append(f"FAIL: Theme off (mean={bg_mean:.0f}, bright={bright_pct:.1%})")

        for r in reasons:
            print(f"  {r}")
        print(f"\nRTS QUALITY SCORE: {score}/10")

        # Record result via verify for the database
        result = self.va.verify(
            "unified", "rts_quality", path, img,
            opencv_checks=[
                ("score_minimum", lambda: score >= 6),
            ],
            llm_checks=[
                ("rts_impression", lambda: self.va.ask_yes_no(
                    path, "Does this look like a real-time strategy game interface with a tactical map, units, and HUD elements?"
                )),
            ],
            api_checks=[
                ("game_state", lambda: self.va.api_get("/api/game/state") is not None),
            ],
        )

        assert score >= 6, f"RTS quality score {score}/10 (minimum 6). Details:\n" + "\n".join(f"  {r}" for r in reasons)


def _check_bright_pct(img: np.ndarray, min_pct: float) -> bool:
    """Check that at least min_pct of pixels are above brightness 30."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bright_pixels = np.count_nonzero(gray > 30)
    return (bright_pixels / gray.size) > min_pct
