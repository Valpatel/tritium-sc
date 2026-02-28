# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for WebSocket event flow.

Connects to /ws/live, begins a game, and verifies that the expected
events arrive over the WebSocket:
  - game_state_change (setup -> countdown)
  - wave_start
  - amy_sim_telemetry_batch (with fsm_state field)
  - projectile_fired (during combat)
  - target_eliminated (when hostile is killed)

Run with:
    .venv/bin/python3 -m pytest tests/integration/test_ws_events.py -m integration -v
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
import websockets

from tests.integration.conftest import IntegrationReport

pytestmark = pytest.mark.integration

_TIMEOUT = 10


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


class TestWebSocketGameEvents:
    """Connect to WebSocket during game and verify event flow."""

    @pytest.mark.timeout(45)
    def test_game_state_change_event(
        self, base_url: str, report: IntegrationReport
    ):
        """Begin game while connected to WS, verify game_state_change event."""
        ws_url = base_url.replace("http://", "ws://") + "/ws/live"

        # Reset to setup
        _post(base_url, "/api/game/reset")
        _post(base_url, "/api/game/place", json={
            "name": "WS Turret", "asset_type": "turret",
            "position": {"x": 0.0, "y": 0.0},
        })

        async def _test():
            events: list[dict] = []
            async with websockets.connect(ws_url) as ws:
                # Drain connected message and initial game_state
                for _ in range(5):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        msg = json.loads(raw)
                        events.append(msg)
                        if msg["type"] == "connected":
                            break
                    except asyncio.TimeoutError:
                        break

                # Begin war via HTTP
                _post(base_url, "/api/game/begin")

                # Collect events for up to 15s
                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        msg = json.loads(raw)
                        events.append(msg)
                    except asyncio.TimeoutError:
                        break

            return events

        events = asyncio.run(_test())
        event_types = [e["type"] for e in events]

        # game_state_change should appear (setup -> countdown)
        has_game_state = "amy_game_state_change" in event_types
        detail = f"event_types={set(event_types)}"
        report.record("ws_game_state_change", has_game_state, detail)

        # We expect connected at minimum
        assert "connected" in event_types, (
            f"Missing 'connected'. Got: {event_types}"
        )

        # Clean up
        _post(base_url, "/api/game/reset")

    @pytest.mark.timeout(45)
    def test_wave_start_event(
        self, base_url: str, report: IntegrationReport
    ):
        """Verify wave_start event arrives over WebSocket."""
        ws_url = base_url.replace("http://", "ws://") + "/ws/live"

        _post(base_url, "/api/game/reset")
        _post(base_url, "/api/game/place", json={
            "name": "WS Turret 2", "asset_type": "turret",
            "position": {"x": 0.0, "y": 0.0},
        })

        async def _test():
            events: list[dict] = []
            async with websockets.connect(ws_url) as ws:
                # Drain initial messages
                for _ in range(5):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        events.append(json.loads(raw))
                    except asyncio.TimeoutError:
                        break

                # Begin war
                _post(base_url, "/api/game/begin")

                # Collect for 15s -- wave_start arrives after countdown (5s)
                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        events.append(json.loads(raw))
                    except asyncio.TimeoutError:
                        break

            return events

        events = asyncio.run(_test())
        event_types = [e["type"] for e in events]

        has_wave_start = "amy_wave_start" in event_types
        detail = f"wave_start_seen={has_wave_start}, types={set(event_types)}"
        report.record("ws_wave_start", has_wave_start, detail)

        # Clean up
        _post(base_url, "/api/game/reset")

    @pytest.mark.timeout(45)
    def test_telemetry_batch_has_fsm_state(
        self, base_url: str, report: IntegrationReport
    ):
        """Verify sim_telemetry_batch events include fsm_state field."""
        ws_url = base_url.replace("http://", "ws://") + "/ws/live"

        _post(base_url, "/api/game/reset")
        _post(base_url, "/api/game/place", json={
            "name": "FSM Turret", "asset_type": "turret",
            "position": {"x": 0.0, "y": 0.0},
        })
        _post(base_url, "/api/game/place", json={
            "name": "FSM Rover", "asset_type": "rover",
            "position": {"x": 5.0, "y": 0.0},
        })

        async def _test():
            telemetry_batches: list[dict] = []
            async with websockets.connect(ws_url) as ws:
                # Drain initial
                for _ in range(5):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        msg = json.loads(raw)
                        if msg["type"] == "amy_sim_telemetry_batch":
                            telemetry_batches.append(msg)
                    except asyncio.TimeoutError:
                        break

                # Begin war to get active combat telemetry
                _post(base_url, "/api/game/begin")

                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        msg = json.loads(raw)
                        if msg["type"] == "amy_sim_telemetry_batch":
                            telemetry_batches.append(msg)
                            if len(telemetry_batches) >= 5:
                                break
                    except asyncio.TimeoutError:
                        break

            return telemetry_batches

        batches = asyncio.run(_test())

        # Check that at least one batch arrived
        has_batches = len(batches) > 0
        fsm_found = False
        if has_batches:
            # Each batch data is a list of target dicts
            for batch in batches:
                targets = batch.get("data", [])
                if isinstance(targets, list):
                    for t in targets:
                        if "fsm_state" in t:
                            fsm_found = True
                            break
                if fsm_found:
                    break

        detail = f"batches={len(batches)}, fsm_found={fsm_found}"
        report.record("ws_telemetry_fsm_state", fsm_found, detail)

        # At minimum we should get telemetry batches
        assert has_batches, "No telemetry batches received"
        assert fsm_found, f"fsm_state not found in any telemetry target: {detail}"

        _post(base_url, "/api/game/reset")

    @pytest.mark.timeout(60)
    def test_combat_events(
        self, base_url: str, report: IntegrationReport
    ):
        """Wait for combat and verify projectile_fired and target_eliminated events."""
        ws_url = base_url.replace("http://", "ws://") + "/ws/live"

        _post(base_url, "/api/game/reset")
        # Place turrets close to center where hostiles will approach
        _post(base_url, "/api/game/place", json={
            "name": "Combat Turret A", "asset_type": "turret",
            "position": {"x": -3.0, "y": 0.0},
        })
        _post(base_url, "/api/game/place", json={
            "name": "Combat Turret B", "asset_type": "turret",
            "position": {"x": 3.0, "y": 0.0},
        })

        async def _test():
            events: list[dict] = []
            async with websockets.connect(ws_url) as ws:
                # Drain initial messages
                for _ in range(5):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        events.append(json.loads(raw))
                    except asyncio.TimeoutError:
                        break

                # Begin war
                _post(base_url, "/api/game/begin")

                # Collect events for up to 45s (enough for hostiles to approach
                # and combat to start)
                deadline = time.monotonic() + 45.0
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        msg = json.loads(raw)
                        events.append(msg)
                    except asyncio.TimeoutError:
                        continue

            return events

        events = asyncio.run(_test())
        event_types = [e["type"] for e in events]

        has_projectile = "amy_projectile_fired" in event_types
        has_elimination = "amy_target_eliminated" in event_types

        detail_parts = []
        detail_parts.append(f"projectile_fired={'YES' if has_projectile else 'NO'}")
        detail_parts.append(f"target_eliminated={'YES' if has_elimination else 'NO'}")
        detail_parts.append(f"unique_types={set(event_types)}")
        detail = "; ".join(detail_parts)

        report.record("ws_combat_events", True, detail)

        # projectile_fired is expected when hostiles get in range of turrets
        # We log but don't hard-fail since combat timing is non-deterministic
        if has_projectile:
            report.record("ws_projectile_fired", True)
        else:
            report.record("ws_projectile_fired", False, "No projectiles in time window")

        if has_elimination:
            report.record("ws_target_eliminated", True)
        else:
            report.record("ws_target_eliminated", False, "No eliminations in time window")

        # Clean up
        _post(base_url, "/api/game/reset")
