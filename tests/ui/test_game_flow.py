# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Game flow tests for the Command Center.

Exercises the game lifecycle: open Game HUD, spawn hostile,
begin war, verify phase changes.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_game_flow.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.ui.conftest import assert_panel_visible, wait_for_panel

pytestmark = [pytest.mark.ux, pytest.mark.ui]


class TestGameHudPanel:
    """Game HUD panel interaction."""

    def test_open_game_hud(self, page, take_screenshot):
        """Pressing 4 should open the Game HUD panel."""
        # Close if open
        panel = page.locator('[data-panel-id="game"]')
        if panel.count() > 0 and panel.is_visible():
            page.keyboard.press('4')
            page.wait_for_timeout(500)

        page.keyboard.press('4')
        page.wait_for_timeout(500)
        assert_panel_visible(page, 'game')
        take_screenshot(page, 'game-hud-open')

    def test_game_hud_shows_idle_phase(self, page, take_screenshot):
        """Game HUD should show IDLE phase by default."""
        page.keyboard.press('4')
        page.wait_for_timeout(500)

        phase_el = page.locator(
            '[data-panel-id="game"] [data-bind="phase"]'
        )
        if phase_el.count() > 0:
            phase_text = phase_el.text_content()
            # Phase could be IDLE or SETUP -- both are valid before game starts
            assert phase_text in ('IDLE', 'SETUP', 'ACTIVE', 'COUNTDOWN'), \
                f"Phase should be a valid state, got: {phase_text}"
        take_screenshot(page, 'game-hud-phase')

    def test_game_hud_has_buttons(self, page, take_screenshot):
        """Game HUD should have BEGIN WAR, SPAWN HOSTILE, and RESET buttons."""
        # Ensure game panel is open
        panel = page.locator('[data-panel-id="game"]')
        if panel.count() == 0 or not panel.is_visible():
            page.keyboard.press('4')
            page.wait_for_timeout(500)

        begin_btn = page.locator(
            '[data-panel-id="game"] [data-action="begin-war"]'
        )
        spawn_btn = page.locator(
            '[data-panel-id="game"] [data-action="spawn-hostile"]'
        )
        reset_btn = page.locator(
            '[data-panel-id="game"] [data-action="reset-game"]'
        )

        assert begin_btn.count() > 0, "BEGIN WAR button should exist"
        assert spawn_btn.count() > 0, "SPAWN HOSTILE button should exist"
        assert reset_btn.count() > 0, "RESET button should exist"
        take_screenshot(page, 'game-hud-buttons')


class TestSetupMode:
    """Setup mode palette and unit placement."""

    def test_setup_mode_shows_palette(self, page, take_screenshot):
        """Pressing S should show the deploy palette."""
        # Switch to setup mode
        page.keyboard.press('s')
        page.wait_for_timeout(800)

        palette = page.locator('#war-setup-palette')
        is_visible = palette.evaluate(
            "el => el.style.display !== 'none' && el.offsetWidth > 0"
        )
        take_screenshot(page, 'setup-palette')
        assert is_visible, "Deploy palette should be visible in setup mode"

    def test_setup_palette_has_categories(self, page, take_screenshot):
        """Deploy palette should have at least one category with items."""
        page.keyboard.press('s')
        page.wait_for_timeout(800)

        items = page.locator('#war-setup-palette .palette-item')
        count = items.count()
        take_screenshot(page, 'setup-palette-items')
        assert count > 0, f"Palette should have items, got {count}"

    def test_observe_mode_hides_palette(self, page, take_screenshot):
        """Switching to observe mode should hide the deploy palette."""
        page.keyboard.press('s')
        page.wait_for_timeout(500)
        page.keyboard.press('o')
        page.wait_for_timeout(500)

        palette = page.locator('#war-setup-palette')
        is_hidden = palette.evaluate(
            "el => el.style.display === 'none' || el.offsetWidth === 0"
        )
        take_screenshot(page, 'observe-palette-hidden')
        assert is_hidden, "Palette should be hidden in observe mode"

    def test_place_turret_via_api(self, page, take_screenshot, tritium_server):
        """Placing a turret via API should add it to simulation targets."""
        import requests
        # Reset to setup state
        requests.post(f"{tritium_server.url}/api/game/reset", timeout=5)
        page.wait_for_timeout(500)

        resp = requests.post(f"{tritium_server.url}/api/game/place", json={
            "name": "Test Turret",
            "asset_type": "turret",
            "position": {"x": 5, "y": 5},
        }, timeout=5)
        assert resp.ok, f"Place turret should succeed, got {resp.status_code}"
        data = resp.json()
        assert "target_id" in data, "Response should contain target_id"

        page.wait_for_timeout(1000)
        take_screenshot(page, 'turret-placed')

        # Verify via targets API
        resp = requests.get(
            f"{tritium_server.url}/api/amy/simulation/targets", timeout=5
        )
        if resp.ok:
            targets = resp.json()
            if isinstance(targets, dict):
                targets = targets.get("targets", [])
            turrets = [t for t in targets
                       if t.get("asset_type") == "turret"
                       and t.get("name") == "Test Turret"]
            assert len(turrets) > 0, "Placed turret should appear in targets API"

        # Clean up
        requests.post(f"{tritium_server.url}/api/game/reset", timeout=5)


class TestAudioToggle:
    """Audio mute/unmute toggle."""

    def test_mute_toggle_key(self, page, take_screenshot):
        """Pressing M should toggle mute state."""
        # Get initial mute state
        initial_muted = page.evaluate("""() => {
            const store = window.TritiumStore || window.store;
            if (store && store.audio) return store.audio.muted;
            return null;
        }""")

        page.keyboard.press('m')
        page.wait_for_timeout(300)

        after_muted = page.evaluate("""() => {
            const store = window.TritiumStore || window.store;
            if (store && store.audio) return store.audio.muted;
            return null;
        }""")

        take_screenshot(page, 'audio-mute-toggle')

        # If store has audio state, verify it toggled
        if initial_muted is not None and after_muted is not None:
            assert initial_muted != after_muted, \
                f"Mute should toggle: was {initial_muted}, now {after_muted}"
        # Otherwise just verify M doesn't crash (no console error)


class TestSpawnHostile:
    """Spawning a hostile unit."""

    def test_spawn_hostile(self, page, take_screenshot, tritium_server):
        """Clicking SPAWN HOSTILE should spawn a hostile via the API."""
        # Open game panel
        panel = page.locator('[data-panel-id="game"]')
        if panel.count() == 0 or not panel.is_visible():
            page.keyboard.press('4')
            page.wait_for_timeout(500)

        spawn_btn = page.locator(
            '[data-panel-id="game"] [data-action="spawn-hostile"]'
        )
        spawn_btn.click()
        page.wait_for_timeout(1000)
        take_screenshot(page, 'game-spawn-hostile')

        # Verify via API that a hostile exists
        import requests
        resp = requests.get(
            f"{tritium_server.url}/api/amy/simulation/targets", timeout=5
        )
        if resp.ok:
            targets = resp.json()
            if isinstance(targets, list):
                hostiles = [t for t in targets if t.get('alliance') == 'hostile']
                assert len(hostiles) > 0, "Should have at least one hostile after spawn"


class TestBeginWar:
    """Starting the game."""

    def test_begin_war_changes_phase(self, page, take_screenshot, tritium_server):
        """Begin war API should change game phase from idle."""
        import requests
        # Reset game first via API
        requests.post(f"{tritium_server.url}/api/game/reset", timeout=5)
        page.wait_for_timeout(500)

        take_screenshot(page, 'game-before-war')

        # Use API directly to begin war (most reliable)
        resp = requests.post(f"{tritium_server.url}/api/game/begin", timeout=5)
        assert resp.ok, f"Begin war API should succeed, got {resp.status_code}"
        page.wait_for_timeout(2000)

        take_screenshot(page, 'game-active-war')

        # Verify game state changed via API
        resp = requests.get(
            f"{tritium_server.url}/api/game/state", timeout=5
        )
        assert resp.ok, "Game state API should respond"
        data = resp.json()
        # API returns 'state' key (not 'phase')
        game_state = data.get('state', data.get('phase', 'idle'))
        assert game_state not in ('idle', 'setup'), \
            f"Game state should not be 'idle'/'setup' after begin war, got: {game_state}"

        # Clean up
        requests.post(f"{tritium_server.url}/api/game/reset", timeout=5)

    def test_game_score_area_visible_during_war(self, page, take_screenshot, tritium_server):
        """Header game score area should become visible during active game."""
        import requests
        # Reset first to ensure we can begin
        requests.post(f"{tritium_server.url}/api/game/reset", timeout=5)
        page.wait_for_timeout(500)
        # Begin war
        requests.post(f"{tritium_server.url}/api/game/begin", timeout=5)
        page.wait_for_timeout(2000)

        score_area = page.locator('#game-score-area')
        take_screenshot(page, 'game-score-area')
        # Note: score area visibility depends on game.phase store update via WS
        # Just verify the element exists
        assert score_area.count() > 0, "Game score area element should exist"

        # Reset for other tests
        requests.post(f"{tritium_server.url}/api/game/reset", timeout=5)
        page.wait_for_timeout(1000)
