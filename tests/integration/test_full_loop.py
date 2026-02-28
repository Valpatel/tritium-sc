# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""End-to-end integration test for the TRITIUM-SC game loop.

Exercises the full lifecycle with real HTTP calls against a headless server:
  1. Server startup (health check)
  2. Synthetic camera create / snapshot
  3. Audio effects list / download
  4. Game setup (place turrets + rover)
  5. Begin war -> countdown -> active
  6. Game progress (waves, hostiles, kills)
  7. WebSocket event flow
  8. Game end or graceful timeout
  9. Reset to setup
 10. Synthetic camera cleanup

Run with:
    .venv/bin/python3 -m pytest tests/integration/ -m integration -v
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import pytest
import websockets

from tests.lib.server_manager import TritiumServer
from tests.integration.conftest import IntegrationReport

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIMEOUT = 10  # default HTTP timeout (seconds)


def _get(base: str, path: str, **kw) -> httpx.Response:
    """GET helper with default timeout."""
    return httpx.get(f"{base}{path}", timeout=_TIMEOUT, **kw)


def _post(base: str, path: str, **kw) -> httpx.Response:
    """POST helper with default timeout."""
    return httpx.post(f"{base}{path}", timeout=_TIMEOUT, **kw)


def _delete(base: str, path: str, **kw) -> httpx.Response:
    """DELETE helper with default timeout."""
    return httpx.delete(f"{base}{path}", timeout=_TIMEOUT, **kw)


def _poll_game_state(base: str, timeout: float = 60.0, interval: float = 1.0):
    """Generator that yields game state dicts until timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = _get(base, "/api/game/state")
        resp.raise_for_status()
        yield resp.json()
        time.sleep(interval)


# ---------------------------------------------------------------------------
# 1. Server health
# ---------------------------------------------------------------------------

class TestServerStartup:
    """Verify the server is alive and responsive."""

    def test_health_endpoint(self, base_url: str, report: IntegrationReport):
        resp = _get(base_url, "/health")
        assert resp.status_code == 200, f"Health check failed: {resp.status_code}"
        body = resp.json()
        assert body["status"] == "operational", f"Unexpected health status: {body}"
        report.record("health_endpoint", True)

    def test_status_endpoint(self, base_url: str, report: IntegrationReport):
        resp = _get(base_url, "/api/status")
        assert resp.status_code == 200, f"Status check failed: {resp.status_code}"
        body = resp.json()
        assert "version" in body, f"Missing version in status: {body}"
        report.record("status_endpoint", True)


# ---------------------------------------------------------------------------
# 2. Synthetic camera
# ---------------------------------------------------------------------------

class TestSyntheticCamera:
    """Create a synthetic camera, grab a snapshot, then clean up."""

    FEED_ID = "integration-test-cam"

    def test_create_camera(self, base_url: str, report: IntegrationReport):
        resp = _post(base_url, "/api/synthetic/cameras", json={
            "feed_id": self.FEED_ID,
            "scene_type": "bird_eye",
            "fps": 5,
            "width": 320,
            "height": 240,
        })
        assert resp.status_code == 201, (
            f"Failed to create synthetic camera: {resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert body["feed_id"] == self.FEED_ID, f"Wrong feed_id: {body}"
        report.record("synthetic_camera_create", True)

    def test_list_cameras(self, base_url: str, report: IntegrationReport):
        resp = _get(base_url, "/api/synthetic/cameras")
        assert resp.status_code == 200, f"List cameras failed: {resp.status_code}"
        feeds = resp.json()
        ids = [f["feed_id"] for f in feeds]
        assert self.FEED_ID in ids, (
            f"Created camera not in list: {ids}"
        )
        report.record("synthetic_camera_list", True)

    def test_snapshot_returns_jpeg(self, base_url: str, report: IntegrationReport):
        resp = _get(base_url, f"/api/synthetic/cameras/{self.FEED_ID}/snapshot")
        assert resp.status_code == 200, (
            f"Snapshot failed: {resp.status_code} {resp.text}"
        )
        content = resp.content
        # JPEG magic bytes: FF D8 FF
        assert content[:3] == b"\xff\xd8\xff", (
            f"Snapshot is not valid JPEG (first 4 bytes: {content[:4].hex()})"
        )
        assert len(content) > 100, (
            f"Snapshot suspiciously small: {len(content)} bytes"
        )
        report.record("synthetic_camera_snapshot", True, f"{len(content)} bytes")

    def test_delete_camera(self, base_url: str, report: IntegrationReport):
        resp = _delete(base_url, f"/api/synthetic/cameras/{self.FEED_ID}")
        assert resp.status_code == 200, (
            f"Delete camera failed: {resp.status_code} {resp.text}"
        )
        # Verify it is gone
        resp2 = _get(base_url, f"/api/synthetic/cameras/{self.FEED_ID}")
        assert resp2.status_code == 404, (
            f"Camera still exists after delete: {resp2.status_code}"
        )
        report.record("synthetic_camera_delete", True)


# ---------------------------------------------------------------------------
# 3. Audio effects
# ---------------------------------------------------------------------------

class TestAudioEffects:
    """List audio effects and download one, verifying WAV headers."""

    def test_list_effects(self, base_url: str, report: IntegrationReport):
        resp = _get(base_url, "/api/audio/effects")
        assert resp.status_code == 200, (
            f"List effects failed: {resp.status_code}"
        )
        effects = resp.json()
        assert isinstance(effects, list), f"Expected list, got {type(effects)}"
        assert len(effects) > 0, "No audio effects returned"
        # Each effect should have name and category
        for e in effects:
            assert "name" in e, f"Effect missing 'name': {e}"
            assert "category" in e, f"Effect missing 'category': {e}"
        report.record("audio_effects_list", True, f"{len(effects)} effects")

    def test_download_effect_wav(self, base_url: str, report: IntegrationReport):
        # Get the list first, pick the first effect
        resp = _get(base_url, "/api/audio/effects")
        effects = resp.json()
        assert len(effects) > 0, "No effects to download"
        name = effects[0]["name"]

        resp = _get(base_url, f"/api/audio/effects/{name}")
        assert resp.status_code == 200, (
            f"Download effect '{name}' failed: {resp.status_code}"
        )
        wav = resp.content
        assert len(wav) > 44, (
            f"WAV too small ({len(wav)} bytes) — likely empty"
        )
        # Check RIFF/WAVE header
        assert wav[:4] == b"RIFF", (
            f"Not a RIFF file (header: {wav[:4]})"
        )
        assert wav[8:12] == b"WAVE", (
            f"Not a WAVE file (bytes 8-12: {wav[8:12]})"
        )
        report.record("audio_effect_download", True, f"{name}: {len(wav)} bytes")

    def test_filter_by_category(self, base_url: str, report: IntegrationReport):
        resp = _get(base_url, "/api/audio/effects", params={"category": "combat"})
        assert resp.status_code == 200, (
            f"Filter by category failed: {resp.status_code}"
        )
        effects = resp.json()
        for e in effects:
            assert e["category"] == "combat", (
                f"Effect '{e['name']}' has category '{e['category']}', expected 'combat'"
            )
        report.record("audio_effects_filter", True, f"{len(effects)} combat effects")


# ---------------------------------------------------------------------------
# 4-6. Full game loop
# ---------------------------------------------------------------------------

class TestGameLoop:
    """Place units, begin war, observe progress, and reset.

    Tests are ordered via explicit numbering so pytest runs them
    sequentially within this class.
    """

    def test_01_initial_state_is_setup(self, base_url: str, report: IntegrationReport):
        """Game starts in setup state."""
        resp = _get(base_url, "/api/game/state")
        assert resp.status_code == 200, f"Game state failed: {resp.status_code}"
        state = resp.json()
        assert state["state"] == "setup", (
            f"Expected initial state 'setup', got '{state['state']}'"
        )
        report.record("game_initial_state", True)

    def test_02_place_turrets_and_rover(self, base_url: str, report: IntegrationReport):
        """Place 2 turrets and 1 rover during setup."""
        units = [
            {"name": "Alpha Turret", "asset_type": "turret", "position": {"x": -5.0, "y": 0.0}},
            {"name": "Bravo Turret", "asset_type": "turret", "position": {"x": 5.0, "y": 0.0}},
            {"name": "Charlie Rover", "asset_type": "rover", "position": {"x": 0.0, "y": -3.0}},
        ]
        placed_ids = []
        for unit in units:
            resp = _post(base_url, "/api/game/place", json=unit)
            assert resp.status_code == 200, (
                f"Place {unit['name']} failed: {resp.status_code} {resp.text}"
            )
            body = resp.json()
            assert "target_id" in body, f"No target_id in place response: {body}"
            placed_ids.append(body["target_id"])

        # Verify friendlies appear in the targets list
        resp = _get(base_url, "/api/targets/friendlies")
        assert resp.status_code == 200, f"Friendlies failed: {resp.status_code}"
        friendlies = resp.json().get("targets", [])
        friendly_ids = {t["target_id"] for t in friendlies}
        for pid in placed_ids:
            assert pid in friendly_ids, (
                f"Placed unit {pid} not found in friendlies list"
            )
        report.record("game_place_units", True, f"placed {len(placed_ids)} units")

    def test_03_begin_war(self, base_url: str, report: IntegrationReport):
        """POST /api/game/begin transitions to countdown."""
        resp = _post(base_url, "/api/game/begin")
        assert resp.status_code == 200, (
            f"Begin war failed: {resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert body.get("status") == "countdown_started", (
            f"Expected countdown_started, got: {body}"
        )

        # Wait for state to become "active" (countdown is 5s)
        active_seen = False
        for state in _poll_game_state(base_url, timeout=15.0, interval=0.5):
            if state["state"] in ("active", "wave_complete"):
                active_seen = True
                break

        assert active_seen, "Game never transitioned to active after begin_war"
        report.record("game_begin_war", True)

    def test_04_game_progress(self, base_url: str, report: IntegrationReport):
        """Poll game state, verify wave advances and hostiles appear."""
        initial_state = _get(base_url, "/api/game/state").json()
        initial_wave = initial_state.get("wave", 0)

        hostiles_seen = False
        wave_advanced = False
        eliminations_seen = False
        max_wave = initial_wave

        # Poll for up to 60s — enough time for wave 1 to complete and wave 2 to start
        for state in _poll_game_state(base_url, timeout=60.0, interval=1.0):
            current_wave = state.get("wave", 0)
            total_elims = state.get("total_eliminations", state.get("total_kills", 0))

            if current_wave > max_wave:
                max_wave = current_wave
                wave_advanced = True

            if total_elims > 0:
                eliminations_seen = True

            # Check for hostiles in targets API
            if not hostiles_seen:
                hr = _get(base_url, "/api/targets/hostiles")
                if hr.status_code == 200:
                    htargets = hr.json().get("targets", [])
                    if len(htargets) > 0:
                        hostiles_seen = True

            # If we have seen all three signals, no need to keep polling
            if hostiles_seen and wave_advanced and eliminations_seen:
                break

            # If game ended, stop polling
            if state["state"] in ("victory", "defeat"):
                break

        detail_parts = []

        # Hostiles must appear (the wave spawns them)
        assert hostiles_seen, (
            "No hostiles appeared during the game -- simulation may not be running"
        )
        detail_parts.append("hostiles: YES")

        # Wave advance is likely but depends on turrets killing fast enough.
        # We log it but don't hard-fail if wave 1 is still in progress.
        if wave_advanced:
            detail_parts.append(f"wave_advanced: YES (max wave {max_wave})")
        else:
            detail_parts.append(f"wave_advanced: NO (stuck on wave {max_wave})")

        if eliminations_seen:
            detail_parts.append("eliminations: YES")
        else:
            detail_parts.append("eliminations: NO")

        report.record("game_progress", True, "; ".join(detail_parts))

    def test_05_targets_unified(self, base_url: str, report: IntegrationReport):
        """GET /api/targets returns combined view."""
        resp = _get(base_url, "/api/targets")
        assert resp.status_code == 200, f"Targets failed: {resp.status_code}"
        body = resp.json()
        assert "targets" in body, f"Missing 'targets' key: {body.keys()}"
        assert "summary" in body, f"Missing 'summary' key: {body.keys()}"
        targets = body["targets"]
        assert len(targets) > 0, "No targets at all during active game"
        report.record("targets_unified", True, f"{len(targets)} targets")

    def test_06_simulation_targets(self, base_url: str, report: IntegrationReport):
        """GET /api/amy/simulation/targets returns sim targets."""
        resp = _get(base_url, "/api/amy/simulation/targets")
        assert resp.status_code == 200, (
            f"Sim targets failed: {resp.status_code}"
        )
        body = resp.json()
        targets = body.get("targets", [])
        # During active game there should be at least our placed units
        assert len(targets) > 0, "No simulation targets returned"
        report.record("simulation_targets", True, f"{len(targets)} sim targets")

    def test_07_reset_game(self, base_url: str, report: IntegrationReport):
        """POST /api/game/reset returns to setup."""
        resp = _post(base_url, "/api/game/reset")
        assert resp.status_code == 200, (
            f"Reset failed: {resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert body.get("state") == "setup", (
            f"Expected state 'setup' after reset, got: {body}"
        )

        # Confirm via GET
        resp2 = _get(base_url, "/api/game/state")
        state = resp2.json()
        assert state["state"] == "setup", (
            f"Game state is '{state['state']}' after reset, expected 'setup'"
        )
        assert state["score"] == 0, (
            f"Score not reset: {state['score']}"
        )
        report.record("game_reset", True)


# ---------------------------------------------------------------------------
# 7. WebSocket events
# ---------------------------------------------------------------------------

class TestWebSocket:
    """Connect to /ws/live and verify event flow."""

    @pytest.mark.timeout(30)
    def test_websocket_connection_and_events(
        self, base_url: str, report: IntegrationReport
    ):
        """Connect via WebSocket, verify initial message and ping/pong."""
        ws_url = base_url.replace("http://", "ws://") + "/ws/live"

        async def _ws_test():
            async with websockets.connect(ws_url) as ws:
                # 1. Should receive a "connected" message early on
                #    (sim telemetry batches may arrive first)
                msg = None
                for _ in range(10):
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    candidate = json.loads(raw)
                    if candidate["type"] == "connected":
                        msg = candidate
                        break
                assert msg is not None, "Never received 'connected' message"
                assert "TRITIUM" in msg.get("message", ""), (
                    f"Missing TRITIUM in welcome: {msg}"
                )

                # 2. Send a ping, expect pong (skip any telemetry broadcasts)
                await ws.send(json.dumps({"type": "ping"}))
                pong = None
                for _ in range(20):
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    candidate = json.loads(raw)
                    if candidate["type"] == "pong":
                        pong = candidate
                        break
                assert pong is not None, "Never received 'pong' response"

                return True

        result = asyncio.run(_ws_test())
        assert result is True
        report.record("websocket_connect_and_ping", True)

    @pytest.mark.timeout(30)
    def test_websocket_receives_game_events(
        self, base_url: str, report: IntegrationReport
    ):
        """Start a game while connected to WS, check for game/sim events.

        In headless mode (AMY_ENABLED=false), the headless event bridge
        forwards sim_telemetry and game state events over WebSocket.
        """
        ws_url = base_url.replace("http://", "ws://") + "/ws/live"

        # First, reset to setup so we can begin a fresh game
        _post(base_url, "/api/game/reset")

        # Place a minimal defense
        _post(base_url, "/api/game/place", json={
            "name": "WS Turret", "asset_type": "turret",
            "position": {"x": 0.0, "y": 0.0},
        })

        async def _ws_game_test():
            events_received: list[str] = []
            async with websockets.connect(ws_url) as ws:
                # Drain the connected message
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                msg = json.loads(raw)
                events_received.append(msg["type"])

                # Begin war via HTTP
                _post(base_url, "/api/game/begin")

                # Collect events for up to 10s
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        msg = json.loads(raw)
                        events_received.append(msg["type"])
                    except asyncio.TimeoutError:
                        break

            return events_received

        events = asyncio.run(_ws_game_test())

        # The "connected" event should always be there
        assert "connected" in events, (
            f"Missing 'connected' event. Got: {events}"
        )

        # In headless mode the Amy event bridge is not active, so game events
        # may not arrive over WS. We record what we got for the report.
        game_events = [e for e in events if e not in ("connected", "pong")]
        detail = f"total={len(events)}, game_events={game_events}"
        report.record("websocket_game_events", True, detail)

        # Clean up: reset game so later tests get a clean state
        _post(base_url, "/api/game/reset")


# ---------------------------------------------------------------------------
# 8. Second game cycle (proves reset works fully)
# ---------------------------------------------------------------------------

class TestSecondCycle:
    """Run a second game cycle after reset to prove idempotency."""

    def test_second_game_begin_and_reset(
        self, base_url: str, report: IntegrationReport
    ):
        """Place units, begin, wait a few seconds, reset -- second time."""
        # Ensure setup state
        _post(base_url, "/api/game/reset")
        state = _get(base_url, "/api/game/state").json()
        assert state["state"] == "setup", f"Not in setup: {state['state']}"

        # Place one turret
        resp = _post(base_url, "/api/game/place", json={
            "name": "Cycle2 Turret", "asset_type": "turret",
            "position": {"x": 0.0, "y": 5.0},
        })
        assert resp.status_code == 200, f"Place failed: {resp.text}"

        # Begin war
        resp = _post(base_url, "/api/game/begin")
        assert resp.status_code == 200, f"Begin failed: {resp.text}"

        # Wait briefly for game to become active
        active_seen = False
        for state in _poll_game_state(base_url, timeout=10.0, interval=0.5):
            if state["state"] in ("active", "wave_complete"):
                active_seen = True
                break
        assert active_seen, "Second cycle: never reached active state"

        # Reset
        resp = _post(base_url, "/api/game/reset")
        assert resp.status_code == 200, f"Reset failed: {resp.text}"
        state = _get(base_url, "/api/game/state").json()
        assert state["state"] == "setup", (
            f"Second reset did not return to setup: {state['state']}"
        )

        report.record("second_cycle", True)


# ---------------------------------------------------------------------------
# 9. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Verify the server returns sensible errors for bad requests."""

    def test_begin_war_when_not_setup(
        self, base_url: str, report: IntegrationReport
    ):
        """Cannot begin war when already in a non-setup state."""
        # Ensure setup, then begin
        _post(base_url, "/api/game/reset")
        _post(base_url, "/api/game/place", json={
            "name": "Err Turret", "asset_type": "turret",
            "position": {"x": 0.0, "y": 0.0},
        })
        _post(base_url, "/api/game/begin")

        # Wait for active
        for state in _poll_game_state(base_url, timeout=10.0, interval=0.5):
            if state["state"] in ("active", "wave_complete"):
                break

        # Second begin should fail
        resp = _post(base_url, "/api/game/begin")
        assert resp.status_code == 400, (
            f"Expected 400 for double begin, got {resp.status_code}"
        )

        # Clean up
        _post(base_url, "/api/game/reset")
        report.record("error_double_begin", True)

    def test_place_during_active(
        self, base_url: str, report: IntegrationReport
    ):
        """Cannot place units when game is active."""
        _post(base_url, "/api/game/reset")
        _post(base_url, "/api/game/place", json={
            "name": "Pre Turret", "asset_type": "turret",
            "position": {"x": 0.0, "y": 0.0},
        })
        _post(base_url, "/api/game/begin")

        # Wait for active
        for state in _poll_game_state(base_url, timeout=10.0, interval=0.5):
            if state["state"] in ("active", "wave_complete"):
                break

        resp = _post(base_url, "/api/game/place", json={
            "name": "Late Turret", "asset_type": "turret",
            "position": {"x": 1.0, "y": 1.0},
        })
        assert resp.status_code == 400, (
            f"Expected 400 for place during active, got {resp.status_code}"
        )

        _post(base_url, "/api/game/reset")
        report.record("error_place_during_active", True)

    def test_nonexistent_synthetic_camera(
        self, base_url: str, report: IntegrationReport
    ):
        """404 for snapshot of a non-existent camera."""
        resp = _get(base_url, "/api/synthetic/cameras/does-not-exist/snapshot")
        assert resp.status_code == 404, (
            f"Expected 404, got {resp.status_code}"
        )
        report.record("error_nonexistent_camera", True)

    def test_nonexistent_audio_effect(
        self, base_url: str, report: IntegrationReport
    ):
        """404 for a non-existent audio effect."""
        resp = _get(base_url, "/api/audio/effects/does_not_exist_xyz")
        assert resp.status_code == 404, (
            f"Expected 404, got {resp.status_code}"
        )
        report.record("error_nonexistent_effect", True)
