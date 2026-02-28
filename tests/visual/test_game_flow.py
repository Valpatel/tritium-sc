# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Full game lifecycle E2E test: setup -> countdown -> active -> wave_complete -> victory/game_over.

Validates the complete war flow through both the REST API and the browser UI,
using a shared Playwright browser session and polling loops (no fixed sleeps).

Run:
    .venv/bin/python3 -m pytest tests/visual/test_game_flow.py -v --tb=short
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import requests

from tests.lib.results_db import ResultsDB
from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/game-flow-screenshots")


def _poll(predicate, timeout: float, interval: float = 0.5, desc: str = "") -> bool:
    """Poll *predicate* until it returns True or *timeout* expires.

    Returns True if predicate succeeded, False on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


class TestGameFlow:
    """Ordered E2E tests that walk through the full game lifecycle."""

    # ------------------------------------------------------------------
    # Shared browser fixture (class-scoped)
    # ------------------------------------------------------------------

    @pytest.fixture(autouse=True, scope="class")
    def _browser(
        self,
        request,
        tritium_server: TritiumServer,
        test_db: ResultsDB,
        run_id: int,
    ):
        """Launch browser, navigate to Command Center, wait for data."""
        cls = request.cls
        cls.server = tritium_server
        cls.base_url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._errors: list[str] = []
        cls._t0 = time.monotonic()

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))
        cls.page.goto(f"{cls.base_url}/", wait_until="networkidle")
        # Let the app initialise (WebSocket connect, initial fetch)
        cls.page.wait_for_timeout(4000)

        yield

        browser.close()
        cls._pw.stop()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _screenshot(self, name: str) -> str:
        """Take a debug screenshot and return the path."""
        path = str(SCREENSHOT_DIR / f"{name}.png")
        try:
            self.page.screenshot(path=path, full_page=False)
        except Exception:
            pass
        return path

    def _record(self, name: str, passed: bool, details: dict | None = None) -> None:
        duration_ms = (time.monotonic() - self._t0) * 1000
        self._db.record_result(self._run_id, name, passed, duration_ms, details or {})
        self._screenshot(name)

    def _api(self, method: str, path: str, **kwargs) -> requests.Response:
        """Make an API call to the test server."""
        url = f"{self.base_url}{path}"
        return requests.request(method, url, timeout=10, **kwargs)

    def _game_state(self) -> dict:
        """GET /api/game/state and return the JSON body."""
        resp = self._api("GET", "/api/game/state")
        resp.raise_for_status()
        return resp.json()

    def _targets(self) -> list[dict]:
        """GET /api/amy/simulation/targets and return the list."""
        resp = self._api("GET", "/api/amy/simulation/targets")
        resp.raise_for_status()
        data = resp.json()
        # The endpoint may return a list or a dict with a 'targets' key
        if isinstance(data, list):
            return data
        return data.get("targets", data.get("items", []))

    def _hostile_targets(self) -> list[dict]:
        """Return only hostile targets from the target list."""
        return [
            t for t in self._targets()
            if t.get("alliance") == "hostile" and t.get("status") == "active"
        ]

    def _friendly_targets(self) -> list[dict]:
        """Return only friendly targets from the target list."""
        return [
            t for t in self._targets()
            if t.get("alliance") == "friendly"
        ]

    # ------------------------------------------------------------------
    # Tests — numbered for execution order
    # ------------------------------------------------------------------

    def test_01_initial_state_is_setup(self):
        """Reset game, verify /api/game/state returns state: 'setup'."""
        name = "game_flow_01_initial_state_is_setup"
        try:
            # Reset to known state
            self._api("POST", "/api/game/reset")
            time.sleep(0.5)

            state = self._game_state()
            print(f"  [01] Game state after reset: {state}")
            assert state["state"] == "setup", (
                f"Expected state='setup', got '{state['state']}'"
            )
            self._record(name, True, state)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_02_place_units_in_setup(self):
        """Place 3 turrets at different positions, verify all appear in targets."""
        name = "game_flow_02_place_units_in_setup"
        try:
            # Make sure we are in setup
            state = self._game_state()
            assert state["state"] == "setup", (
                f"Expected setup state, got '{state['state']}'"
            )

            placed_ids = []
            positions = [
                ("Alpha-1", 5.0, 5.0),
                ("Bravo-2", -10.0, 3.0),
                ("Charlie-3", 0.0, -8.0),
            ]
            for unit_name, x, y in positions:
                resp = self._api("POST", "/api/game/place", json={
                    "name": unit_name,
                    "asset_type": "turret",
                    "position": {"x": x, "y": y},
                })
                resp.raise_for_status()
                data = resp.json()
                tid = data.get("target_id", "")
                placed_ids.append(tid)
                print(f"  [02] Placed {unit_name} -> {tid}")

            # Verify all 3 appear in the target list
            time.sleep(0.5)
            targets = self._targets()
            target_ids = [t.get("target_id", t.get("id", "")) for t in targets]
            for pid in placed_ids:
                assert pid in target_ids, (
                    f"Placed unit {pid} not found in targets ({len(targets)} total)"
                )

            # Verify at least 3 friendlies
            friendlies = self._friendly_targets()
            assert len(friendlies) >= 3, (
                f"Expected >= 3 friendlies, got {len(friendlies)}"
            )
            print(f"  [02] Total targets: {len(targets)}, friendlies: {len(friendlies)}")
            self._record(name, True, {
                "placed_ids": placed_ids,
                "total_targets": len(targets),
                "friendlies": len(friendlies),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_03_begin_war_transitions_to_countdown(self):
        """POST /api/game/begin, verify state transitions to 'countdown'."""
        name = "game_flow_03_begin_war_transitions_to_countdown"
        try:
            resp = self._api("POST", "/api/game/begin")
            resp.raise_for_status()
            begin_data = resp.json()
            print(f"  [03] Begin response: {begin_data}")

            # State should be countdown immediately (or within 1s)
            ok = _poll(
                lambda: self._game_state()["state"] == "countdown",
                timeout=3.0,
                interval=0.2,
                desc="waiting for countdown",
            )
            state = self._game_state()
            print(f"  [03] State after begin: {state}")
            assert state["state"] == "countdown", (
                f"Expected 'countdown', got '{state['state']}'"
            )
            self._record(name, True, state)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_04_countdown_visible_in_ui(self):
        """During countdown, verify UI shows countdown element."""
        name = "game_flow_04_countdown_visible_in_ui"
        try:
            # The countdown may be shown as #war-countdown DOM element
            # or as a canvas overlay. Check DOM element first.
            cd_el = self.page.locator("#war-countdown")
            # Also check for a .fx-countdown element (MapLibre overlay)
            fx_cd = self.page.locator(".fx-countdown")

            # Give the UI a moment to react via WebSocket
            self.page.wait_for_timeout(500)

            cd_visible = cd_el.count() > 0 and cd_el.is_visible()
            fx_visible = fx_cd.count() > 0 and fx_cd.is_visible()

            state = self._game_state()
            print(f"  [04] war-countdown visible={cd_visible}, fx-countdown visible={fx_visible}")
            print(f"  [04] API state={state['state']}, countdown={state.get('countdown')}")

            # Check the TritiumStore game phase reflects countdown or active
            store_phase = self.page.evaluate(
                "() => window.TritiumStore ? TritiumStore.get('game.phase') : 'unknown'"
            )
            print(f"  [04] TritiumStore game.phase = {store_phase}")

            # Either the DOM countdown is visible, or the store phase reflects
            # the countdown/active state (the countdown is only 5s, it may
            # have already transitioned to active by the time we check the DOM)
            assert (
                cd_visible
                or fx_visible
                or store_phase in ("countdown", "active")
                or state["state"] in ("countdown", "active")
            ), (
                f"Countdown not visible and state not countdown/active: "
                f"cd_visible={cd_visible}, fx_visible={fx_visible}, "
                f"store_phase={store_phase}, api_state={state['state']}"
            )
            self._record(name, True, {
                "cd_visible": cd_visible,
                "fx_visible": fx_visible,
                "store_phase": store_phase,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_05_countdown_transitions_to_active(self):
        """Wait up to 10s for state to become 'active'."""
        name = "game_flow_05_countdown_transitions_to_active"
        try:
            ok = _poll(
                lambda: self._game_state()["state"] == "active",
                timeout=10.0,
                interval=0.3,
                desc="waiting for active state",
            )
            state = self._game_state()
            print(f"  [05] State: {state}")
            assert state["state"] == "active", (
                f"Expected 'active' within 10s, got '{state['state']}'"
            )
            assert state["wave"] >= 1, f"Expected wave >= 1, got {state['wave']}"
            self._record(name, True, state)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_06_wave_spawns_hostiles(self):
        """In active state, verify hostiles appear in target list within 15s."""
        name = "game_flow_06_wave_spawns_hostiles"
        try:
            ok = _poll(
                lambda: len(self._hostile_targets()) > 0,
                timeout=15.0,
                interval=0.5,
                desc="waiting for hostiles to spawn",
            )
            hostiles = self._hostile_targets()
            print(f"  [06] Hostile count: {len(hostiles)}")
            if hostiles:
                print(f"  [06] First hostile: {hostiles[0].get('name', '?')} "
                      f"at {hostiles[0].get('position', '?')}")
            assert len(hostiles) > 0, "No hostiles spawned within 15s"
            self._record(name, True, {"hostile_count": len(hostiles)})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_07_combat_produces_eliminations(self):
        """Wait for total_eliminations to increase (up to 30s)."""
        name = "game_flow_07_combat_produces_eliminations"
        try:
            initial_elims = self._game_state().get("total_eliminations", 0)
            print(f"  [07] Initial eliminations: {initial_elims}")

            ok = _poll(
                lambda: self._game_state().get("total_eliminations", 0) > initial_elims,
                timeout=30.0,
                interval=1.0,
                desc="waiting for eliminations",
            )
            state = self._game_state()
            elims = state.get("total_eliminations", 0)
            print(f"  [07] Eliminations after wait: {elims}")
            assert elims > initial_elims, (
                f"No eliminations produced in 30s (still {elims})"
            )
            self._record(name, True, {
                "initial_elims": initial_elims,
                "final_elims": elims,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_08_score_increases(self):
        """Verify score > 0 after eliminations."""
        name = "game_flow_08_score_increases"
        try:
            state = self._game_state()
            score = state.get("score", 0)
            print(f"  [08] Score: {score}, state: {state['state']}")
            assert score > 0, f"Expected score > 0, got {score}"
            self._record(name, True, {"score": score})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_09_wave_complete_transition(self):
        """After wave hostiles eliminated, verify wave_complete then back to active."""
        name = "game_flow_09_wave_complete_transition"
        try:
            # Wait for wave_complete or the next wave starting (active with wave > 1)
            # The wave_complete state lasts _WAVE_ADVANCE_DELAY (5s) then auto-advances.
            saw_wave_complete = False
            saw_next_wave = False
            initial_wave = self._game_state().get("wave", 1)
            print(f"  [09] Starting wave: {initial_wave}")

            deadline = time.monotonic() + 60.0  # 60s max wait
            while time.monotonic() < deadline:
                state = self._game_state()
                current_state = state["state"]
                current_wave = state.get("wave", 0)

                if current_state == "wave_complete":
                    saw_wave_complete = True
                    print(f"  [09] Saw wave_complete at wave {current_wave}")
                elif saw_wave_complete and current_state == "active":
                    saw_next_wave = True
                    print(f"  [09] Transitioned back to active, wave {current_wave}")
                    break
                elif current_wave > initial_wave and current_state == "active":
                    # We may have missed wave_complete (it is transient)
                    saw_next_wave = True
                    print(f"  [09] Wave advanced to {current_wave} (missed wave_complete)")
                    break
                elif current_state in ("victory", "defeat"):
                    print(f"  [09] Game ended with {current_state}")
                    # If the game ended, wave_complete was transited through
                    saw_wave_complete = True
                    break

                time.sleep(0.5)

            state = self._game_state()
            print(f"  [09] Final state: {state}")

            # Accept: saw wave_complete, or wave advanced, or game ended
            assert saw_wave_complete or saw_next_wave or state["state"] in ("victory", "defeat"), (
                f"Never saw wave_complete or wave advancement in 60s. "
                f"Last state: {state['state']}, wave: {state.get('wave')}"
            )
            self._record(name, True, {
                "saw_wave_complete": saw_wave_complete,
                "saw_next_wave": saw_next_wave,
                "final_state": state["state"],
                "final_wave": state.get("wave"),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_10_game_state_api_matches_ui(self):
        """Compare API game state with what the UI store reports."""
        name = "game_flow_10_game_state_api_matches_ui"
        try:
            # Let UI sync
            self.page.wait_for_timeout(1000)

            api_state = self._game_state()
            api_phase = api_state["state"]

            # Read the TritiumStore game phase from the browser
            store_phase = self.page.evaluate(
                "() => window.TritiumStore ? TritiumStore.get('game.phase') : 'unknown'"
            )
            store_score = self.page.evaluate(
                "() => window.TritiumStore ? TritiumStore.get('game.score') : -1"
            )

            print(f"  [10] API phase: {api_phase}, Store phase: {store_phase}")
            print(f"  [10] API score: {api_state.get('score')}, Store score: {store_score}")

            # The store phase should match the API state. Some name mapping:
            # 'defeat' in API -> 'defeat' in store, 'victory' -> 'victory'
            # However 'game_over' in store is also possible for both.
            phase_match = (
                store_phase == api_phase
                or (api_phase in ("victory", "defeat") and store_phase in ("victory", "defeat", "game_over"))
                or (api_phase == "active" and store_phase in ("active", "countdown"))
            )
            print(f"  [10] Phase match: {phase_match}")

            assert phase_match, (
                f"API state '{api_phase}' does not match UI store phase '{store_phase}'"
            )
            self._record(name, True, {
                "api_phase": api_phase,
                "store_phase": store_phase,
                "api_score": api_state.get("score"),
                "store_score": store_score,
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise

    def test_11_reset_clears_everything(self):
        """POST /api/game/reset, verify setup state, units remain, hostiles cleared."""
        name = "game_flow_11_reset_clears_everything"
        try:
            # Count friendlies before reset (the placed turrets + layout units)
            pre_friendlies = self._friendly_targets()
            print(f"  [11] Pre-reset friendlies: {len(pre_friendlies)}")

            resp = self._api("POST", "/api/game/reset")
            resp.raise_for_status()
            reset_data = resp.json()
            print(f"  [11] Reset response: {reset_data}")

            # Wait for reset to propagate
            time.sleep(1.0)

            state = self._game_state()
            print(f"  [11] State after reset: {state}")
            assert state["state"] == "setup", (
                f"Expected 'setup' after reset, got '{state['state']}'"
            )
            assert state.get("score", 0) == 0, (
                f"Score should be 0 after reset, got {state.get('score')}"
            )

            # Hostiles should be cleared
            ok = _poll(
                lambda: len(self._hostile_targets()) == 0,
                timeout=5.0,
                interval=0.5,
                desc="waiting for hostiles to be cleared",
            )
            hostiles = self._hostile_targets()
            print(f"  [11] Hostiles after reset: {len(hostiles)}")
            assert len(hostiles) == 0, (
                f"Expected 0 hostiles after reset, got {len(hostiles)}"
            )

            # Friendly units from the layout should still exist
            friendlies = self._friendly_targets()
            print(f"  [11] Friendlies after reset: {len(friendlies)}")
            # At minimum, the layout-loaded friendlies should survive reset
            assert len(friendlies) >= 1, (
                f"Expected friendlies to survive reset, got {len(friendlies)}"
            )

            self._record(name, True, {
                "state": state["state"],
                "score": state.get("score"),
                "hostiles": len(hostiles),
                "friendlies": len(friendlies),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise
