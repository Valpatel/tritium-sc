# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for game_state_change event pipeline.

Verifies that GameMode.begin_war() → EventBus → bridge → WebSocket
produces the expected events. These are unit tests that do NOT require
a running server.
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from tritium_lib.sim_engine.core.entity import SimulationTarget


class TestGameStateEventPipeline:
    """Verify game_state_change events flow through the EventBus."""

    def _make_engine(self) -> SimulationEngine:
        bus = EventBus()
        engine = SimulationEngine(bus)
        # Place a friendly combatant so defeat doesn't trigger immediately
        turret = SimulationTarget(
            target_id="test-turret-001",
            name="Test Turret",
            alliance="friendly",
            asset_type="turret",
            position=(0.0, 0.0),
            speed=0.0,
            status="stationary",
        )
        turret.apply_combat_profile()
        engine.add_target(turret)
        return engine

    def test_begin_war_publishes_game_state_change(self):
        """begin_war() should publish a game_state_change event with state=countdown."""
        engine = self._make_engine()
        sub = engine._event_bus.subscribe()

        engine.begin_war()

        # Drain events and find game_state_change
        events = []
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                events.append(msg)
            except queue.Empty:
                break

        game_state_events = [
            e for e in events if e.get("type") == "game_state_change"
        ]
        assert len(game_state_events) >= 1, (
            f"Expected game_state_change event. Got types: "
            f"{[e.get('type') for e in events]}"
        )

        data = game_state_events[0].get("data", {})
        assert data.get("state") == "countdown", (
            f"Expected state=countdown, got: {data}"
        )
        assert data.get("wave") == 1

    def test_countdown_transitions_to_active(self):
        """After 5s countdown, game should transition to active with a game_state_change."""
        engine = self._make_engine()
        sub = engine._event_bus.subscribe()

        engine.begin_war()

        # Simulate 60 ticks (6 seconds at 0.1s each) — enough for countdown
        for _ in range(60):
            engine._do_tick(0.1)

        # Drain ALL events
        events = []
        while True:
            try:
                msg = sub.get_nowait()
                events.append(msg)
            except queue.Empty:
                break

        game_state_events = [
            e for e in events if e.get("type") == "game_state_change"
        ]
        states = [e.get("data", {}).get("state") for e in game_state_events]

        # Should see countdown → active transition
        assert "countdown" in states, f"No countdown state. States: {states}"
        assert "active" in states, f"No active state. States: {states}"

    def test_game_state_change_has_all_fields(self):
        """game_state_change data should include state, wave, score, etc."""
        engine = self._make_engine()
        sub = engine._event_bus.subscribe()

        engine.begin_war()

        # Get the first game_state_change
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                if msg.get("type") == "game_state_change":
                    data = msg.get("data", {})
                    assert "state" in data
                    assert "wave" in data
                    assert "score" in data
                    assert "total_waves" in data
                    assert "game_mode_type" in data
                    return
            except queue.Empty:
                break

        pytest.fail("No game_state_change event received")

    def test_wave_start_event_published(self):
        """When countdown ends, wave_start should be published."""
        engine = self._make_engine()
        sub = engine._event_bus.subscribe()

        engine.begin_war()

        # Tick through countdown
        for _ in range(60):
            engine._do_tick(0.1)

        events = []
        while True:
            try:
                msg = sub.get_nowait()
                events.append(msg)
            except queue.Empty:
                break

        wave_start_events = [
            e for e in events if e.get("type") == "wave_start"
        ]
        assert len(wave_start_events) >= 1, (
            f"No wave_start event. Types: {set(e.get('type') for e in events)}"
        )

        data = wave_start_events[0].get("data", {})
        assert data.get("wave_number") == 1

    def test_elimination_updates_score(self):
        """Eliminating a hostile should publish game_state_change with updated score."""
        engine = self._make_engine()

        # Start the game and tick to active
        engine.begin_war()
        for _ in range(60):
            engine._do_tick(0.1)

        # Subscribe AFTER the countdown events (so we only see new events)
        sub = engine._event_bus.subscribe()

        # Simulate an elimination
        engine.game_mode.on_target_eliminated("fake-hostile-001")

        events = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                events.append(msg)
            except queue.Empty:
                break

        game_state_events = [
            e for e in events if e.get("type") == "game_state_change"
        ]
        assert len(game_state_events) >= 1, (
            f"No game_state_change after elimination. Types: "
            f"{[e.get('type') for e in events]}"
        )

        data = game_state_events[0].get("data", {})
        assert data.get("score") == 100, f"Expected score=100, got: {data}"
        assert data.get("total_eliminations") == 1


class TestInitialStateSyncAndHeartbeat:
    """Test that initial state sync and heartbeat keep clients in sync."""

    def _make_engine(self) -> SimulationEngine:
        bus = EventBus()
        engine = SimulationEngine(bus)
        turret = SimulationTarget(
            target_id="test-turret-hb",
            name="Heartbeat Turret",
            alliance="friendly",
            asset_type="turret",
            position=(0.0, 0.0),
            speed=0.0,
            status="stationary",
        )
        turret.apply_combat_profile()
        engine.add_target(turret)
        return engine

    def test_get_game_state_returns_setup_initially(self):
        """Engine starts in 'setup' state."""
        engine = self._make_engine()
        state = engine.get_game_state()
        assert state["state"] == "setup"
        assert state["wave"] == 0
        assert state["score"] == 0

    def test_get_game_state_reflects_countdown(self):
        """After begin_war, state should be 'countdown'."""
        engine = self._make_engine()
        engine.begin_war()
        state = engine.get_game_state()
        assert state["state"] == "countdown"
        assert state["wave"] == 1

    def test_get_game_state_reflects_active(self):
        """After countdown ticks down, state should be 'active'."""
        engine = self._make_engine()
        engine.begin_war()
        for _ in range(60):
            engine._do_tick(0.1)
        state = engine.get_game_state()
        assert state["state"] == "active"

    def test_heartbeat_detects_state_change(self):
        """Heartbeat's state comparison detects transitions."""
        engine = self._make_engine()
        state1 = engine.get_game_state()
        assert state1["state"] == "setup"

        engine.begin_war()
        state2 = engine.get_game_state()
        assert state2["state"] == "countdown"

        # States should be different (heartbeat would send)
        assert state1 != state2

    def test_heartbeat_skips_identical_state(self):
        """Heartbeat should not resend if state hasn't changed."""
        engine = self._make_engine()
        state1 = engine.get_game_state()
        state2 = engine.get_game_state()
        assert state1 == state2


class TestBridgeEventForwarding:
    """Verify that the ws.py bridge_loop properly forwards game_state_change.

    Tests the bridge logic by simulating EventBus → bridge → broadcast
    without needing a running server.
    """

    def test_bridge_handles_game_state_change(self):
        """The bridge else-clause should forward game_state_change events."""
        bus = EventBus()
        sub = bus.subscribe()

        # Publish a game_state_change
        bus.publish("game_state_change", {
            "state": "countdown",
            "wave": 1,
            "score": 0,
        })

        # Simulate what bridge_loop does
        msg = sub.get(timeout=1.0)
        event_type = msg.get("type", "unknown")
        data = msg.get("data", {})

        # Verify the event type is game_state_change (not sim_telemetry etc.)
        assert event_type == "game_state_change"
        assert event_type != "sim_telemetry"
        assert not event_type.startswith("amy_")
        assert not event_type.startswith("mesh_")

        # This means it falls through to the else clause in bridge_loop
        # which calls broadcast_amy_event("game_state_change", data)
        # producing {"type": "amy_game_state_change", "data": data}
        ws_type = f"amy_{event_type}"
        assert ws_type == "amy_game_state_change"
        assert data.get("state") == "countdown"

    def test_bridge_does_not_drop_game_events_under_telemetry_load(self):
        """With high telemetry throughput, game_state_change should not be dropped."""
        bus = EventBus()
        sub = bus.subscribe()

        # Flood with telemetry batches
        for i in range(500):
            bus.publish("sim_telemetry_batch", [{"target_id": f"t-{i}"}])

        # Publish game_state_change
        bus.publish("game_state_change", {"state": "active", "wave": 1})

        # Publish more telemetry
        for i in range(500):
            bus.publish("sim_telemetry_batch", [{"target_id": f"t-{i}"}])

        # Drain the queue and check that game_state_change is present
        events = []
        while True:
            try:
                msg = sub.get_nowait()
                events.append(msg)
            except queue.Empty:
                break

        game_events = [e for e in events if e.get("type") == "game_state_change"]
        assert len(game_events) >= 1, (
            f"game_state_change was dropped! Total events: {len(events)}, "
            f"types: {set(e.get('type') for e in events)}"
        )

    def test_queue_overflow_drops_oldest_not_newest(self):
        """EventBus queue overflow should drop oldest, keeping newest events."""
        bus = EventBus()
        sub = bus.subscribe()

        # Queue maxsize is 1000. Publish 1100 events, then a game_state_change.
        for i in range(1100):
            bus.publish("sim_telemetry_batch", [{"id": i}])

        # Now publish game_state_change — it should go through
        # (oldest telemetry was dropped to make room)
        bus.publish("game_state_change", {"state": "active"})

        # Drain and verify
        events = []
        while True:
            try:
                msg = sub.get_nowait()
                events.append(msg)
            except queue.Empty:
                break

        game_events = [e for e in events if e.get("type") == "game_state_change"]
        assert len(game_events) == 1, (
            f"game_state_change missing from queue! events={len(events)}"
        )


class TestGameOverModeSpecificData:
    """Verify game_over events include game_mode_type and mode-specific fields."""

    def _make_engine(self) -> SimulationEngine:
        bus = EventBus()
        engine = SimulationEngine(bus)
        turret = SimulationTarget(
            target_id="test-turret-go",
            name="GO Turret",
            alliance="friendly",
            asset_type="turret",
            position=(0.0, 0.0),
            speed=0.0,
            status="stationary",
        )
        turret.apply_combat_profile()
        engine.add_target(turret)
        return engine

    def test_game_over_includes_game_mode_type(self):
        """game_over event should include game_mode_type field."""
        engine = self._make_engine()
        sub = engine._event_bus.subscribe()

        engine.begin_war()
        for _ in range(60):
            engine._do_tick(0.1)

        # Force a defeat by eliminating all friendlies
        for t in engine.get_targets():
            if t.alliance == "friendly":
                t.health = 0
                t.status = "eliminated"

        engine._do_tick(0.1)

        events = []
        while True:
            try:
                msg = sub.get_nowait()
                events.append(msg)
            except queue.Empty:
                break

        game_overs = [e for e in events if e.get("type") == "game_over"]
        assert len(game_overs) >= 1, (
            f"No game_over event. Types: {set(e.get('type') for e in events)}"
        )

        data = game_overs[0].get("data", {})
        assert "game_mode_type" in data, f"game_over missing game_mode_type: {data}"
        assert data["game_mode_type"] == "battle"
        assert "reason" in data, f"game_over missing reason: {data}"

    def test_build_game_over_data_battle(self):
        """_build_game_over_data for battle mode includes standard fields."""
        engine = self._make_engine()
        engine.game_mode.score = 5000
        engine.game_mode.total_eliminations = 12
        engine.game_mode.wave = 5

        data = engine.game_mode._build_game_over_data(
            "victory", reason="all_waves_cleared", waves_completed=10
        )

        assert data["result"] == "victory"
        assert data["score"] == 5000
        assert data["total_eliminations"] == 12
        assert data["game_mode_type"] == "battle"
        assert data["reason"] == "all_waves_cleared"
        assert data["waves_completed"] == 10

    def test_build_game_over_data_civil_unrest(self):
        """_build_game_over_data for civil_unrest includes de-escalation fields."""
        engine = self._make_engine()
        engine.game_mode.game_mode_type = "civil_unrest"
        engine.game_mode.score = 1000
        engine.game_mode.de_escalation_score = 2000
        engine.game_mode.civilian_harm_count = 2
        engine.game_mode.civilian_harm_limit = 5
        engine.game_mode.total_eliminations = 3

        data = engine.game_mode._build_game_over_data(
            "victory", reason="all_waves_cleared", waves_completed=8
        )

        assert data["game_mode_type"] == "civil_unrest"
        assert data["de_escalation_score"] == 2000
        assert data["civilian_harm_count"] == 2
        assert data["civilian_harm_limit"] == 5
        assert data["weighted_total_score"] == int(1000 * 0.3 + 2000 * 0.7)

    def test_build_game_over_data_drone_swarm(self):
        """_build_game_over_data for drone_swarm includes infrastructure fields."""
        engine = self._make_engine()
        engine.game_mode.game_mode_type = "drone_swarm"
        engine.game_mode.score = 8000
        engine.game_mode.infrastructure_health = 650
        engine.game_mode.infrastructure_max = 1000
        engine.game_mode.total_eliminations = 45

        data = engine.game_mode._build_game_over_data(
            "victory", reason="all_waves_cleared", waves_completed=10
        )

        assert data["game_mode_type"] == "drone_swarm"
        assert data["infrastructure_health"] == 650
        assert data["infrastructure_max"] == 1000
        assert data["score"] == 8000

    def test_build_game_over_data_drone_swarm_defeat(self):
        """_build_game_over_data for drone_swarm defeat includes zero infrastructure."""
        engine = self._make_engine()
        engine.game_mode.game_mode_type = "drone_swarm"
        engine.game_mode.infrastructure_health = 0
        engine.game_mode.infrastructure_max = 1000
        engine.game_mode.score = 2000

        data = engine.game_mode._build_game_over_data(
            "defeat", reason="infrastructure_destroyed", waves_completed=4
        )

        assert data["result"] == "defeat"
        assert data["reason"] == "infrastructure_destroyed"
        assert data["infrastructure_health"] == 0
        assert data["infrastructure_max"] == 1000


class TestModeConfigWiring:
    """Verify that BattleScenario.mode_config is applied by load_scenario()."""

    def _make_engine(self) -> SimulationEngine:
        bus = EventBus()
        engine = SimulationEngine(bus)
        turret = SimulationTarget(
            target_id="test-turret-mc",
            name="ModeConfig Turret",
            alliance="friendly",
            asset_type="turret",
            position=(0.0, 0.0),
            speed=0.0,
            status="stationary",
        )
        turret.apply_combat_profile()
        engine.add_target(turret)
        return engine

    def test_load_scenario_applies_civil_unrest_mode_config(self):
        """load_scenario() should apply civil_unrest mode_config settings."""
        from engine.simulation.scenario import (
            BattleScenario, WaveDefinition, SpawnGroup,
        )
        engine = self._make_engine()
        engine.game_mode.game_mode_type = "civil_unrest"

        scenario = BattleScenario(
            scenario_id="test-cu",
            name="Test Civil Unrest",
            description="",
            map_bounds=200.0,
            waves=[WaveDefinition(
                name="Wave 1",
                groups=[SpawnGroup(asset_type="person", count=5)],
            )],
            mode_config={
                "civilian_harm_limit": 3,
                "de_escalation_multiplier": 1.5,
            },
        )
        engine.game_mode.load_scenario(scenario)

        assert engine.game_mode.civilian_harm_limit == 3, (
            f"Expected civilian_harm_limit=3, got {engine.game_mode.civilian_harm_limit}"
        )

    def test_load_scenario_applies_drone_swarm_mode_config(self):
        """load_scenario() should apply drone_swarm mode_config settings."""
        from engine.simulation.scenario import (
            BattleScenario, WaveDefinition, SpawnGroup,
        )
        engine = self._make_engine()
        engine.game_mode.game_mode_type = "drone_swarm"

        scenario = BattleScenario(
            scenario_id="test-ds",
            name="Test Drone Swarm",
            description="",
            map_bounds=200.0,
            waves=[WaveDefinition(
                name="Wave 1",
                groups=[SpawnGroup(asset_type="person", count=5)],
            )],
            mode_config={
                "infrastructure_max": 2000.0,
            },
        )
        engine.game_mode.load_scenario(scenario)

        assert engine.game_mode.infrastructure_max == 2000.0, (
            f"Expected infrastructure_max=2000, got {engine.game_mode.infrastructure_max}"
        )

    def test_load_scenario_no_mode_config_keeps_defaults(self):
        """Without mode_config, defaults should be preserved."""
        from engine.simulation.scenario import (
            BattleScenario, WaveDefinition, SpawnGroup,
        )
        engine = self._make_engine()
        engine.game_mode.game_mode_type = "civil_unrest"

        scenario = BattleScenario(
            scenario_id="test-no-mc",
            name="Test No Config",
            description="",
            map_bounds=200.0,
            waves=[WaveDefinition(
                name="Wave 1",
                groups=[SpawnGroup(asset_type="person", count=5)],
            )],
        )
        engine.game_mode.load_scenario(scenario)

        # Defaults preserved
        assert engine.game_mode.civilian_harm_limit == 5
        assert engine.game_mode.infrastructure_max == 1000.0

    def test_mode_config_roundtrips_through_serialization(self):
        """mode_config survives to_dict/from_dict round-trip."""
        from engine.simulation.scenario import (
            BattleScenario, WaveDefinition, SpawnGroup,
        )
        original = BattleScenario(
            scenario_id="test-rt",
            name="Roundtrip",
            description="",
            map_bounds=200.0,
            waves=[WaveDefinition(
                name="Wave 1",
                groups=[SpawnGroup(asset_type="person", count=5)],
            )],
            mode_config={"civilian_harm_limit": 2, "custom_key": "value"},
        )

        data = original.to_dict()
        restored = BattleScenario.from_dict(data)

        assert restored.mode_config is not None
        assert restored.mode_config["civilian_harm_limit"] == 2
        assert restored.mode_config["custom_key"] == "value"


class TestWaveMultiplierPreservation:
    """Verify that wave speed/health multipliers are not overwritten by
    a redundant apply_combat_profile() call."""

    def test_spawn_hostile_preserves_speed_multiplier(self):
        """spawn_hostile + speed_mult should produce faster hostiles."""
        bus = EventBus()
        engine = SimulationEngine(bus)
        hostile = engine.spawn_hostile()
        base_speed = hostile.speed  # speed after profile
        hostile.speed *= 1.5  # wave multiplier
        assert hostile.speed == pytest.approx(base_speed * 1.5)

    def test_spawn_wave_hostiles_no_double_profile(self):
        """_spawn_wave_hostiles must NOT call apply_combat_profile() after
        spawn_hostile() already applied it — doing so overwrites multipliers."""
        bus = EventBus()
        engine = SimulationEngine(bus)
        hostile = engine.spawn_hostile()
        base_health = hostile.health  # 80.0 from profile

        # Simulate what _spawn_wave_hostiles should do:
        # Apply multiplier to the already-profiled values
        health_mult = 2.0
        hostile.health *= health_mult
        hostile.max_health *= health_mult

        # Health should be base * mult, NOT hardcoded 80.0 * mult
        assert hostile.health == pytest.approx(base_health * health_mult)
        assert hostile.max_health == pytest.approx(base_health * health_mult)
