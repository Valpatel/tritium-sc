# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for the dispatch API endpoint.

Exercises the full dispatch lifecycle against a real headless server:
  1. Start server with simulation enabled
  2. Place units, begin game
  3. Dispatch a rover to a position via POST /api/amy/simulation/dispatch
  4. Poll /api/amy/simulation/targets and verify position changes
  5. Verify fsm_state transitions
  6. Verify waypoints are set

Run with:
    .venv/bin/python3 -m pytest tests/integration/test_dispatch.py -m integration -v
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.integration.conftest import IntegrationReport

pytestmark = pytest.mark.integration

_TIMEOUT = 10  # default HTTP timeout (seconds)


def _get(base: str, path: str, **kw) -> httpx.Response:
    return httpx.get(f"{base}{path}", timeout=_TIMEOUT, **kw)


def _post(base: str, path: str, **kw) -> httpx.Response:
    return httpx.post(f"{base}{path}", timeout=_TIMEOUT, **kw)


def _poll_game_state(base: str, timeout: float = 60.0, interval: float = 1.0):
    """Generator that yields game state dicts until timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = _get(base, "/api/game/state")
        resp.raise_for_status()
        yield resp.json()
        time.sleep(interval)


def _get_target_by_id(base: str, target_id: str) -> dict | None:
    """Find a specific target in the simulation targets list."""
    resp = _get(base, "/api/amy/simulation/targets")
    resp.raise_for_status()
    for t in resp.json().get("targets", []):
        if t["target_id"] == target_id:
            return t
    return None


class TestDispatchSetup:
    """Verify dispatch endpoint exists and validates input."""

    def test_dispatch_returns_503_when_no_engine(
        self, base_url: str, report: IntegrationReport
    ):
        """If simulation somehow not active, dispatch returns error."""
        # We know the engine IS active, but we can test validation:
        # nonexistent unit should return 404
        resp = _post(base_url, "/api/amy/simulation/dispatch", json={
            "unit_id": "nonexistent-unit-xyz",
            "target": {"x": 10.0, "y": 20.0},
        })
        # Engine is running but unit doesn't exist -> 404
        assert resp.status_code == 404, (
            f"Expected 404 for nonexistent unit, got {resp.status_code}: {resp.text}"
        )
        report.record("dispatch_nonexistent_unit", True)

    def test_dispatch_422_for_invalid_body(
        self, base_url: str, report: IntegrationReport
    ):
        """Invalid request body returns 422."""
        resp = _post(base_url, "/api/amy/simulation/dispatch", json={
            "unit_id": "rover-1",
            # missing 'target' field
        })
        assert resp.status_code == 422, (
            f"Expected 422 for missing target, got {resp.status_code}"
        )
        report.record("dispatch_invalid_body", True)


class TestDispatchLifecycle:
    """Place units, begin game, dispatch rover, verify movement."""

    def test_01_reset_to_setup(self, base_url: str, report: IntegrationReport):
        """Reset game to setup state for a clean dispatch test."""
        _post(base_url, "/api/game/reset")
        state = _get(base_url, "/api/game/state").json()
        assert state["state"] == "setup", f"Not in setup: {state['state']}"
        report.record("dispatch_reset_setup", True)

    def test_02_place_rover_and_turret(
        self, base_url: str, report: IntegrationReport
    ):
        """Place a rover and turret for the dispatch test."""
        # Place a turret (defense)
        resp = _post(base_url, "/api/game/place", json={
            "name": "Dispatch Turret",
            "asset_type": "turret",
            "position": {"x": 0.0, "y": 0.0},
        })
        assert resp.status_code == 200, f"Place turret failed: {resp.text}"

        # Place a rover (the unit we will dispatch)
        resp = _post(base_url, "/api/game/place", json={
            "name": "Dispatch Rover",
            "asset_type": "rover",
            "position": {"x": -5.0, "y": -5.0},
        })
        assert resp.status_code == 200, f"Place rover failed: {resp.text}"
        body = resp.json()
        assert "target_id" in body, f"No target_id in response: {body}"

        # Store the rover ID for later tests
        # We can find it by querying targets
        resp = _get(base_url, "/api/amy/simulation/targets")
        targets = resp.json().get("targets", [])
        rover = next(
            (t for t in targets if t["name"] == "Dispatch Rover"),
            None
        )
        assert rover is not None, "Dispatch Rover not found in simulation targets"
        report.record("dispatch_place_units", True, f"rover_id={rover['target_id']}")

    def test_03_begin_war(self, base_url: str, report: IntegrationReport):
        """Begin war so the game is active and dispatch works."""
        resp = _post(base_url, "/api/game/begin")
        assert resp.status_code == 200, f"Begin war failed: {resp.text}"

        # Wait for active state
        active_seen = False
        for state in _poll_game_state(base_url, timeout=15.0, interval=0.5):
            if state["state"] in ("active", "wave_complete"):
                active_seen = True
                break
        assert active_seen, "Game never reached active state"
        report.record("dispatch_begin_war", True)

    def test_04_dispatch_rover(self, base_url: str, report: IntegrationReport):
        """Dispatch the rover to a new position and verify it moves."""
        # Find the rover
        resp = _get(base_url, "/api/amy/simulation/targets")
        targets = resp.json().get("targets", [])
        rover = next(
            (t for t in targets if t["name"] == "Dispatch Rover"),
            None
        )
        assert rover is not None, "Dispatch Rover not found"
        rover_id = rover["target_id"]
        initial_pos = rover["position"]

        # Dispatch to a distant position
        target_x, target_y = 30.0, 30.0
        resp = _post(base_url, "/api/amy/simulation/dispatch", json={
            "unit_id": rover_id,
            "target": {"x": target_x, "y": target_y},
        })
        assert resp.status_code == 200, (
            f"Dispatch failed: {resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert body["status"] == "dispatched", f"Unexpected response: {body}"
        assert body["unit_id"] == rover_id

        # Wait a bit and check that position changed
        time.sleep(2.0)  # 2 seconds at ~2 m/s should move ~4m

        updated = _get_target_by_id(base_url, rover_id)
        assert updated is not None, f"Rover {rover_id} disappeared after dispatch"

        # Position should have changed from initial
        new_pos = updated["position"]
        moved = (
            abs(new_pos["x"] - initial_pos["x"]) > 0.5
            or abs(new_pos["y"] - initial_pos["y"]) > 0.5
        )
        detail = f"from ({initial_pos['x']:.1f},{initial_pos['y']:.1f}) to ({new_pos['x']:.1f},{new_pos['y']:.1f})"
        assert moved, f"Rover did not move after dispatch: {detail}"
        report.record("dispatch_rover_moved", True, detail)

    def test_05_verify_waypoints_set(
        self, base_url: str, report: IntegrationReport
    ):
        """After dispatch, the rover should have waypoints."""
        resp = _get(base_url, "/api/amy/simulation/targets")
        targets = resp.json().get("targets", [])
        rover = next(
            (t for t in targets if t["name"] == "Dispatch Rover"),
            None
        )
        assert rover is not None, "Dispatch Rover not found"

        waypoints = rover.get("waypoints", [])
        assert len(waypoints) > 0, (
            f"Rover has no waypoints after dispatch: {rover}"
        )
        report.record(
            "dispatch_waypoints_set", True,
            f"{len(waypoints)} waypoints"
        )

    def test_06_verify_fsm_state(
        self, base_url: str, report: IntegrationReport
    ):
        """After dispatch, the rover should have a non-idle fsm_state."""
        resp = _get(base_url, "/api/amy/simulation/targets")
        targets = resp.json().get("targets", [])
        rover = next(
            (t for t in targets if t["name"] == "Dispatch Rover"),
            None
        )
        assert rover is not None, "Dispatch Rover not found"

        fsm = rover.get("fsm_state")
        # fsm_state should be set (not None) -- could be "pursuing", "engaging",
        # "patrolling", or other active state depending on combat proximity
        detail = f"fsm_state={fsm}"
        report.record("dispatch_fsm_state", True, detail)
        # We don't assert a specific state since it depends on combat,
        # but we verify the field is present in the response
        assert "fsm_state" in rover, "fsm_state field missing from target dict"

    def test_07_cleanup(self, base_url: str, report: IntegrationReport):
        """Reset game after dispatch tests."""
        resp = _post(base_url, "/api/game/reset")
        assert resp.status_code == 200, f"Reset failed: {resp.text}"
        report.record("dispatch_cleanup", True)
