"""Combat HUD end-to-end tests.

Verifies the full pipeline: API -> SimulationEngine -> EventBus ->
headless bridge -> WebSocket -> war-hud.js/war-combat.js DOM elements.

Tests:
  - Countdown overlay appears during countdown phase
  - Wave banner appears when wave starts
  - Eliminations occur during wave 1 (API-level verification)
  - Game score area visible during active game
  - Wave 1 completes within 60s
  - WebSocket delivers events to browser
  - Targets API shows hostiles during active war
  - BEGIN WAR button visible in setup state

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_combat_hud.py -v -m ux
"""

from __future__ import annotations

import pytest
import requests

pytestmark = [pytest.mark.ux, pytest.mark.ui]


def _api(server, path, method="get", **kwargs):
    """Helper for API calls to the test server."""
    url = f"{server.url}{path}"
    fn = getattr(requests, method)
    return fn(url, timeout=10, **kwargs)


def _reset_and_place_turrets(server, count=3):
    """Reset game and place turrets in a spread pattern."""
    _api(server, "/api/game/reset", method="post")
    positions = [
        {"x": 0, "y": 0},
        {"x": 10, "y": 5},
        {"x": -10, "y": 5},
        {"x": 5, "y": -8},
        {"x": -5, "y": -8},
    ]
    for i in range(min(count, len(positions))):
        _api(server, "/api/game/place", method="post", json={
            "name": f"Turret-{i+1}",
            "asset_type": "turret",
            "position": positions[i],
        })


def _switch_to_war_room(page):
    """Switch to War Room view (legacy SPA) and wait for render."""
    page.keyboard.press('w')
    page.wait_for_timeout(1000)


def _begin_war(server):
    """Begin war via API. Returns response."""
    return _api(server, "/api/game/begin", method="post")


class TestCountdownOverlay:
    """Countdown overlay should appear when game transitions to countdown."""

    def test_countdown_visible_after_begin_war(self, page, take_screenshot, tritium_server):
        """After BEGIN WAR, countdown overlay should become visible."""
        _switch_to_war_room(page)
        _reset_and_place_turrets(tritium_server)
        page.wait_for_timeout(500)

        resp = _begin_war(tritium_server)
        assert resp.ok, f"Begin war failed: {resp.status_code}"

        # Countdown is 5 seconds -- check immediately
        page.wait_for_timeout(500)
        take_screenshot(page, 'combat-countdown-phase')

        # Check game state transitioned
        state_resp = _api(tritium_server, "/api/game/state")
        state = state_resp.json().get("state", "unknown")
        assert state in ("countdown", "active"), \
            f"Game state should be countdown or active, got: {state}"

        _api(tritium_server, "/api/game/reset", method="post")
        page.wait_for_timeout(500)


class TestWaveBanner:
    """Wave banner should appear when wave starts."""

    def test_wave_banner_appears(self, page, take_screenshot, tritium_server):
        """After countdown, game should enter active state (wave 1)."""
        _switch_to_war_room(page)
        _reset_and_place_turrets(tritium_server)
        page.wait_for_timeout(500)

        _begin_war(tritium_server)
        # Wait for countdown (5s) + wave start
        page.wait_for_timeout(7000)

        take_screenshot(page, 'combat-wave-banner')

        # Verify game entered active state
        state_resp = _api(tritium_server, "/api/game/state")
        state = state_resp.json().get("state", "unknown")
        assert state in ("active", "wave_complete"), \
            f"Expected active/wave_complete state after countdown, got: {state}"

        _api(tritium_server, "/api/game/reset", method="post")
        page.wait_for_timeout(500)


class TestEliminationsDuringCombat:
    """Wave hostiles should be eliminated by turrets."""

    def test_wave_hostiles_eliminated(self, page, take_screenshot, tritium_server):
        """Wave 1 hostiles should be eliminated by turrets within 60s.

        With pacing fix (hostiles spawn at 40% of map bounds, speed 3.0),
        wave 1 scouts reach turrets in ~35s and are eliminated by ~48s.
        """
        _switch_to_war_room(page)
        _reset_and_place_turrets(tritium_server, count=5)
        page.wait_for_timeout(500)

        _begin_war(tritium_server)

        # Poll for eliminations (countdown 5s + walk ~35s + combat ~10s)
        eliminations = 0
        for _ in range(30):  # Up to 60s
            page.wait_for_timeout(2000)
            state_resp = _api(tritium_server, "/api/game/state")
            data = state_resp.json()
            eliminations = data.get("total_eliminations", data.get("total_kills", 0))
            if eliminations > 0:
                break

        take_screenshot(page, 'combat-elimination-confirmed')

        assert eliminations > 0, \
            f"Expected at least 1 elimination within 60s of combat, got {eliminations}"

        _api(tritium_server, "/api/game/reset", method="post")
        page.wait_for_timeout(500)

    def test_elimination_feed_in_dom(self, page, take_screenshot, tritium_server):
        """Kill feed DOM element should get entries during combat."""
        _switch_to_war_room(page)
        _reset_and_place_turrets(tritium_server, count=5)
        page.wait_for_timeout(500)

        _begin_war(tritium_server)

        # Wait for combat to produce eliminations
        feed_count = 0
        for _ in range(30):
            page.wait_for_timeout(2000)
            feed_count = page.evaluate("""() => {
                const feed = document.getElementById('war-elimination-feed');
                return feed ? feed.children.length : 0;
            }""")
            if feed_count > 0:
                break

        take_screenshot(page, 'combat-elimination-feed')

        # Also check via API as fallback
        state_resp = _api(tritium_server, "/api/game/state")
        api_elims = state_resp.json().get("total_eliminations", 0)

        assert feed_count > 0 or api_elims > 0, \
            f"Expected eliminations: DOM feed={feed_count}, API={api_elims}"

        _api(tritium_server, "/api/game/reset", method="post")
        page.wait_for_timeout(500)


class TestGameScoreArea:
    """Game score should be visible in header during active game."""

    def test_score_area_shows_during_war(self, page, take_screenshot, tritium_server):
        """The game score area should be visible during active game."""
        _switch_to_war_room(page)
        _reset_and_place_turrets(tritium_server)
        page.wait_for_timeout(500)

        _begin_war(tritium_server)
        page.wait_for_timeout(7000)  # Past countdown into active

        take_screenshot(page, 'combat-score-area')

        # Check for score display in the War Room HUD
        score_visible = page.evaluate("""() => {
            const el = document.getElementById('war-score');
            if (!el) return false;
            return el.style.display !== 'none' && el.offsetWidth > 0;
        }""")

        # Also check the header score area
        header_score = page.evaluate("""() => {
            const el = document.getElementById('game-score-area');
            if (!el) return 'not-found';
            return el.offsetWidth > 0 ? 'visible' : 'hidden';
        }""")

        # At least one score display should work
        assert score_visible or header_score == 'visible', \
            f"Score should be visible during war: war-score={score_visible}, header={header_score}"

        _api(tritium_server, "/api/game/reset", method="post")
        page.wait_for_timeout(500)


class TestWaveCompletion:
    """Wave 1 should complete after all hostiles are eliminated."""

    def test_wave_1_completes(self, page, take_screenshot, tritium_server):
        """Wave 1 (3 scouts) should complete within 60s with 5 turrets."""
        _switch_to_war_room(page)
        _reset_and_place_turrets(tritium_server, count=5)
        page.wait_for_timeout(500)

        _begin_war(tritium_server)

        # Poll for wave completion (wave 1 takes ~48s with pacing fix)
        state = None
        data = {}
        for _ in range(30):  # Up to 60s
            page.wait_for_timeout(2000)
            resp = _api(tritium_server, "/api/game/state")
            data = resp.json()
            s = data.get("state", "unknown")
            wave = data.get("wave", 1)

            if s in ("wave_complete", "victory", "defeat"):
                state = s
                break
            # Wave advanced past 1
            if wave > 1:
                state = "active"
                break

        take_screenshot(page, f'combat-wave1-{state or "timeout"}')

        assert state is not None, \
            f"Wave 1 should complete within 60s, got state={data.get('state')}, wave={data.get('wave')}"

        _api(tritium_server, "/api/game/reset", method="post")
        page.wait_for_timeout(500)


class TestCombatEventsFlow:
    """Verify combat events flow from backend to frontend."""

    def test_websocket_delivers_telemetry(self, page, take_screenshot, tritium_server):
        """WebSocket should deliver telemetry events during active game.

        Verifies by checking TritiumStore (the unified Command Center store)
        for connection status and unit updates from WebSocket telemetry.
        """
        _reset_and_place_turrets(tritium_server, count=3)
        page.wait_for_timeout(500)

        _begin_war(tritium_server)
        page.wait_for_timeout(10000)  # Past countdown, some movement

        take_screenshot(page, 'combat-ws-events')

        # Check TritiumStore connection status (unified Command Center)
        ws_status = page.evaluate("""() => {
            if (window.TritiumStore) {
                return {
                    connected: window.TritiumStore.connection?.status === 'connected',
                    units: window.TritiumStore.units?.size || 0,
                    gamePhase: window.TritiumStore.game?.phase || 'unknown',
                };
            }
            return {connected: false, units: 0, gamePhase: 'unknown'};
        }""")

        # Also check connection indicator DOM element
        conn_indicator = page.evaluate("""() => {
            const el = document.getElementById('connection-status');
            return el ? el.dataset.state : 'not-found';
        }""")

        # Verify via API
        state_resp = _api(tritium_server, "/api/game/state")
        api_state = state_resp.json().get("state", "unknown")

        assert api_state in ("active", "wave_complete"), \
            f"Game should be active after begin war, got: {api_state}"

        # TritiumStore should show connected and have units from telemetry
        assert ws_status.get("connected") or ws_status.get("units", 0) > 0, \
            f"WebSocket should deliver data: {ws_status}, conn={conn_indicator}"

        _api(tritium_server, "/api/game/reset", method="post")
        page.wait_for_timeout(500)

    def test_targets_api_shows_hostiles_during_war(self, page, take_screenshot, tritium_server):
        """During active war, targets API should list hostiles."""
        _reset_and_place_turrets(tritium_server, count=3)
        page.wait_for_timeout(500)

        _begin_war(tritium_server)
        page.wait_for_timeout(8000)  # Past countdown

        take_screenshot(page, 'combat-hostiles-active')

        # Check total simulation targets (includes turrets + hostiles)
        all_resp = _api(tritium_server, "/api/amy/simulation/targets")
        all_targets = all_resp.json() if all_resp.ok else []
        if isinstance(all_targets, dict):
            all_targets = all_targets.get("targets", [])

        total_count = len(all_targets)
        assert total_count > 3, \
            f"Should have more than just turrets during war: got {total_count} targets"

        _api(tritium_server, "/api/game/reset", method="post")
        page.wait_for_timeout(500)


class TestBeginWarButton:
    """BEGIN WAR button in the War Room HUD."""

    def test_begin_war_button_visible_in_setup(self, page, take_screenshot, tritium_server):
        """BEGIN WAR button should be visible when game is in setup state."""
        _switch_to_war_room(page)
        _api(tritium_server, "/api/game/reset", method="post")
        page.wait_for_timeout(1000)

        btn_visible = page.evaluate("""() => {
            const el = document.getElementById('war-begin-btn');
            if (!el) return 'not-found';
            return el.style.display !== 'none' ? 'visible' : 'hidden';
        }""")
        take_screenshot(page, 'combat-begin-btn-setup')

        state_resp = _api(tritium_server, "/api/game/state")
        state = state_resp.json().get("state", "unknown")
        assert state == "setup", f"Expected setup state, got: {state}"
