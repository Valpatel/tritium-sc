# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for headless WS bridge combat event forwarding.

Verifies that start_headless_event_bridge forwards ALL combat events to
WebSocket clients, not just telemetry and game state.

Bug: The headless bridge whitelist omits projectile_fired, projectile_hit,
elimination_streak, and has a typo (wave_started vs wave_start).

Run: .venv/bin/python3 -m pytest tests/engine/api/test_headless_bridge_combat.py -v
"""

from __future__ import annotations

import asyncio
import json
import time
from queue import Queue
from unittest.mock import AsyncMock, patch

import pytest


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _event_loop():
    """Provide a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


class FakeEventBus:
    """Minimal EventBus substitute for testing the bridge."""

    def __init__(self):
        self._queue = Queue()

    def subscribe(self):
        return self

    def get(self, timeout=1.0):
        return self._queue.get(timeout=timeout)

    def push(self, event_type: str, data: dict):
        self._queue.put({"type": event_type, "data": data})


def _collect_broadcast(mgr_mock, timeout=2.0, count=1):
    """Wait for broadcast calls on a mocked ConnectionManager and return messages."""
    deadline = time.time() + timeout
    messages = []
    while time.time() < deadline and len(messages) < count:
        loop = asyncio.get_event_loop()
        # Pump the event loop to process run_coroutine_threadsafe calls
        loop.run_until_complete(asyncio.sleep(0.05))
        for call_args in mgr_mock.broadcast.call_args_list:
            msg = call_args[0][0]
            if msg not in messages:
                messages.append(msg)
    return messages


class TestHeadlessBridgeCombatEvents:
    """Verify that the headless bridge forwards all combat event types."""

    def _start_bridge(self, bus, loop, mgr_mock):
        """Start the headless bridge with a mock manager."""
        with patch("app.routers.ws.manager", mgr_mock):
            from app.routers.ws import start_headless_event_bridge
            start_headless_event_bridge(bus, loop)

    def _assert_event_forwarded(self, bus, event_type, data, expected_ws_type=None):
        """Push an event onto the bus and verify it reaches WebSocket clients."""
        loop = asyncio.get_event_loop()
        mgr_mock = AsyncMock()

        with patch("app.routers.ws.manager", mgr_mock):
            from app.routers.ws import start_headless_event_bridge
            start_headless_event_bridge(bus, loop)

            bus.push(event_type, data)
            messages = _collect_broadcast(mgr_mock, timeout=2.0, count=1)

        if expected_ws_type is None:
            expected_ws_type = f"amy_{event_type}"

        assert len(messages) >= 1, (
            f"Event '{event_type}' was NOT forwarded to WebSocket. "
            f"The headless bridge is silently dropping it."
        )

        found = False
        for msg in messages:
            if msg.get("type") == expected_ws_type:
                found = True
                assert msg["data"] == data
                break

        assert found, (
            f"Expected WS message type '{expected_ws_type}', "
            f"got types: {[m.get('type') for m in messages]}"
        )

    def test_projectile_fired_forwarded(self):
        """projectile_fired events must reach the browser for tracer rendering."""
        bus = FakeEventBus()
        data = {
            "source_id": "turret-1",
            "target_id": "h-1",
            "source_pos": {"x": 10.0, "y": 20.0},
            "target_pos": {"x": 50.0, "y": 60.0},
            "weapon_type": "turret_cannon",
        }
        self._assert_event_forwarded(bus, "projectile_fired", data)

    def test_projectile_hit_forwarded(self):
        """projectile_hit events must reach the browser for impact effects."""
        bus = FakeEventBus()
        data = {
            "target_id": "h-1",
            "source_id": "turret-1",
            "damage": 25.0,
            "position": {"x": 50.0, "y": 60.0},
        }
        self._assert_event_forwarded(bus, "projectile_hit", data)

    def test_elimination_streak_forwarded(self):
        """elimination_streak events must reach the browser for streak banners."""
        bus = FakeEventBus()
        data = {
            "source_id": "turret-1",
            "streak": 3,
            "label": "TRIPLE KILL",
        }
        self._assert_event_forwarded(bus, "elimination_streak", data)

    def test_wave_start_forwarded(self):
        """wave_start (not wave_started) must reach the browser for wave banners.

        The engine publishes 'wave_start' — verify the bridge matches this name."""
        bus = FakeEventBus()
        data = {
            "wave": 3,
            "wave_name": "The Surge",
            "hostile_count": 15,
        }
        self._assert_event_forwarded(bus, "wave_start", data)

    def test_target_eliminated_forwarded(self):
        """target_eliminated events reach the browser (was already working)."""
        bus = FakeEventBus()
        data = {
            "target_id": "h-1",
            "source_id": "turret-1",
            "position": {"x": 50.0, "y": 60.0},
        }
        self._assert_event_forwarded(bus, "target_eliminated", data)

    def test_game_state_change_forwarded(self):
        """game_state_change events reach the browser (was already working)."""
        bus = FakeEventBus()
        data = {
            "state": "active",
            "wave": 1,
            "total_waves": 10,
        }
        self._assert_event_forwarded(bus, "game_state_change", data)

    def test_wave_complete_forwarded(self):
        """wave_complete events reach the browser (was already working)."""
        bus = FakeEventBus()
        data = {
            "wave": 3,
            "eliminations": 12,
            "score_bonus": 100,
        }
        self._assert_event_forwarded(bus, "wave_complete", data)

    def test_game_over_forwarded(self):
        """game_over events reach the browser (was already working)."""
        bus = FakeEventBus()
        data = {
            "result": "victory",
            "score": 5000,
            "total_eliminations": 45,
        }
        self._assert_event_forwarded(bus, "game_over", data)

    def test_backstory_generated_forwarded(self):
        """backstory_generated events should reach the browser."""
        bus = FakeEventBus()
        data = {
            "backstory": "The enemy approaches from the east...",
            "wave": 1,
        }
        self._assert_event_forwarded(bus, "backstory_generated", data)

    def test_upgrade_applied_forwarded(self):
        """upgrade_applied events should reach the browser for HUD updates."""
        bus = FakeEventBus()
        data = {
            "unit_id": "tank-01",
            "upgrade_id": "armor_plating",
        }
        self._assert_event_forwarded(bus, "upgrade_applied", data)

    def test_ability_activated_forwarded(self):
        """ability_activated events should reach the browser for ability tracking."""
        bus = FakeEventBus()
        data = {
            "unit_id": "rover-01",
            "ability_id": "speed_boost",
            "duration": 10,
        }
        self._assert_event_forwarded(bus, "ability_activated", data)

    def test_ability_expired_forwarded(self):
        """ability_expired events should reach the browser to clear ability state."""
        bus = FakeEventBus()
        data = {
            "unit_id": "rover-01",
            "ability_id": "speed_boost",
        }
        self._assert_event_forwarded(bus, "ability_expired", data)

    def test_hazard_spawned_via_existing_bridge(self):
        """hazard_spawned events should reach the browser via allowlist."""
        bus = FakeEventBus()
        data = {
            "hazard_id": "h-1", "hazard_type": "roadblock",
            "position": {"x": 10, "y": 20},
        }
        self._assert_event_forwarded(bus, "hazard_spawned", data)

    def test_weapon_jam_via_existing_bridge(self):
        """weapon_jam events should reach the browser via allowlist."""
        bus = FakeEventBus()
        data = {
            "unit_id": "turret-01", "jam_duration": 2.5,
        }
        self._assert_event_forwarded(bus, "weapon_jam", data)

    def test_robot_thought_forwarded(self):
        """robot_thought events should reach the browser."""
        bus = FakeEventBus()
        data = {
            "robotId": "rover-02",
            "text": "Scanning sector 4",
        }
        self._assert_event_forwarded(bus, "robot_thought", data)

    def test_detection_forwarded(self):
        """detection events (YOLO camera) should reach the browser."""
        bus = FakeEventBus()
        data = {
            "camera_id": "cam-01",
            "class": "person",
            "confidence": 0.95,
        }
        self._assert_event_forwarded(bus, "detection", data)


class TestHeadlessBridgeMissingEvents:
    """Events published by engine subsystems that the headless bridge drops.

    These events are published by engine subsystems during gameplay but are
    NOT in the headless bridge allowlist, so they never reach WebSocket
    clients in headless mode.
    """

    def _assert_event_forwarded(self, bus, event_type, data, expected_ws_type=None):
        """Push an event onto the bus and verify it reaches WebSocket clients."""
        loop = asyncio.get_event_loop()
        mgr_mock = AsyncMock()

        with patch("app.routers.ws.manager", mgr_mock):
            from app.routers.ws import start_headless_event_bridge
            start_headless_event_bridge(bus, loop)

            bus.push(event_type, data)
            messages = _collect_broadcast(mgr_mock, timeout=2.0, count=1)

        if expected_ws_type is None:
            expected_ws_type = f"amy_{event_type}"

        assert len(messages) >= 1, (
            f"Event '{event_type}' was NOT forwarded to WebSocket. "
            f"The headless bridge allowlist is silently dropping it."
        )

        found = any(m.get("type") == expected_ws_type for m in messages)
        assert found, (
            f"Expected WS message type '{expected_ws_type}', "
            f"got types: {[m.get('type') for m in messages]}"
        )

    def test_hazard_spawned_forwarded(self):
        """hazard_spawned events (from HazardManager) should reach the browser."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "hazard_spawned", {
            "hazard_id": "h-1", "hazard_type": "roadblock",
            "position": {"x": 10, "y": 20},
        })

    def test_hazard_expired_forwarded(self):
        """hazard_expired events should reach the browser for map cleanup."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "hazard_expired", {
            "hazard_id": "h-1", "hazard_type": "fire",
        })

    def test_ammo_depleted_forwarded(self):
        """ammo_depleted events (from WeaponSystem) should reach the browser."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "ammo_depleted", {
            "unit_id": "turret-01", "weapon": "turret_cannon",
        })

    def test_ammo_low_forwarded(self):
        """ammo_low events should reach the browser for HUD warnings."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "ammo_low", {
            "unit_id": "rover-01", "ammo": 5, "max_ammo": 30,
        })

    def test_weapon_jam_forwarded(self):
        """weapon_jam events (from turret/drone/rover behaviors) should reach the browser."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "weapon_jam", {
            "unit_id": "turret-01", "jam_duration": 2.0,
        })

    def test_npc_alliance_change_forwarded(self):
        """npc_alliance_change events should reach the browser for unit color updates."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "npc_alliance_change", {
            "unit_id": "person-01", "old_alliance": "neutral",
            "new_alliance": "hostile",
        })

    def test_sensor_triggered_forwarded(self):
        """sensor_triggered events should reach the browser for sensor overlay."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "sensor_triggered", {
            "sensor_id": "tripwire-01", "triggered_by": "hostile-5",
        })

    def test_sensor_cleared_forwarded(self):
        """sensor_cleared events should reach the browser."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "sensor_cleared", {
            "sensor_id": "tripwire-01",
        })

    def test_target_neutralized_forwarded(self):
        """target_neutralized events (from engine stall detection) should reach the browser."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "target_neutralized", {
            "target_id": "hostile-12", "reason": "stalled",
        })

    def test_npc_thought_forwarded(self):
        """npc_thought events should reach the browser for thought bubble display."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "npc_thought", {
            "unit_id": "person-01", "text": "What was that noise?",
            "emotion": "curious", "importance": "high", "duration": 5,
        })

    def test_infrastructure_damage_forwarded(self):
        """infrastructure_damage events should reach the browser for health bar updates."""
        bus = FakeEventBus()
        self._assert_event_forwarded(bus, "infrastructure_damage", {
            "building_id": "b-1", "damage": 50.0,
            "remaining": 200.0,
        })
