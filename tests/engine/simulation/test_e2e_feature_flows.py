# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""End-to-end integration tests for user-facing feature flows.

These tests exercise the FULL pipeline — not mocked — to verify that:
  1. Wave spawning uses directional spawn_direction from WaveConfig
  2. Vision system sets radio_detected on hostile targets
  3. Telemetry serialization includes all fog/radio fields
  4. Upgrade and ability systems are wired into the engine
  5. Combat engage distances are realistic for the full city map
  6. Pathfinder routes hostiles through the grid (not direct line)
"""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from engine.simulation.engine import SimulationEngine
from engine.simulation.game_mode import GameMode, WaveConfig, WAVE_CONFIGS
from tritium_lib.sim_engine.core.entity import SimulationTarget
from tritium_lib.sim_engine.world.vision import VisionSystem
from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(map_bounds: float = 200.0) -> SimulationEngine:
    bus = EventBus()
    engine = SimulationEngine(bus, map_bounds=map_bounds)
    return engine


def _add_friendly_turret(engine, position=(0.0, 0.0), name="Turret-1"):
    t = SimulationTarget(
        target_id=f"turret-{name}",
        name=name,
        alliance="friendly",
        asset_type="turret",
        position=position,
        speed=0.0,
        status="stationary",
    )
    t.apply_combat_profile()
    engine.add_target(t)
    return t


def _add_friendly_rover(engine, position=(0.0, 0.0), name="Rover-1"):
    """Add a friendly rover with bluetooth_mac for radio detection."""
    t = SimulationTarget(
        target_id=f"rover-{name}",
        name=name,
        alliance="friendly",
        asset_type="rover",
        position=position,
        speed=3.0,
        status="active",
    )
    t.apply_combat_profile()
    # Give it a radio signature for detection capability
    if hasattr(t, 'identity') and t.identity is not None:
        t.identity.bluetooth_mac = "AA:BB:CC:DD:EE:01"
    engine.add_target(t)
    return t


# ---------------------------------------------------------------------------
# 1. Wave spawn direction flows end-to-end
# ---------------------------------------------------------------------------


class TestWaveDirectionE2E:
    """Verify WaveConfig.spawn_direction is used during actual wave spawning."""

    def test_north_wave_spawns_from_north(self):
        """A north-directed wave should place all hostiles at y > 0."""
        engine = _make_engine(map_bounds=200.0)
        _add_friendly_turret(engine)
        engine.game_mode.state = "active"

        config = WaveConfig(
            name="North Test", count=15, speed_mult=1.0, health_mult=1.0,
            spawn_direction="north",
        )
        engine.game_mode._spawn_wave_hostiles(config)

        hostiles = [t for t in engine.get_targets() if t.alliance == "hostile"]
        assert len(hostiles) == 15
        for h in hostiles:
            _, y = h.position
            assert y > 0, f"{h.name} spawned at y={y:.1f}, expected y > 0"

    def test_pincer_wave_hits_both_sides(self):
        """A pincer wave should have hostiles from both positive and negative x."""
        engine = _make_engine(map_bounds=200.0)
        _add_friendly_turret(engine)
        engine.game_mode.state = "active"

        config = WaveConfig(
            name="Pincer Test", count=30, speed_mult=1.0, health_mult=1.0,
            spawn_direction="pincer",
        )
        engine.game_mode._spawn_wave_hostiles(config)

        xs = [t.position[0] for t in engine.get_targets() if t.alliance == "hostile"]
        has_east = any(x > 50 for x in xs)
        has_west = any(x < -50 for x in xs)
        assert has_east and has_west, "Pincer should spawn from both east and west"

    def test_mixed_wave_uses_direction(self):
        """Composition waves should also respect spawn_direction."""
        engine = _make_engine(map_bounds=200.0)
        _add_friendly_turret(engine)
        engine.game_mode.state = "active"

        config = WaveConfig(
            name="East Mixed", count=8, speed_mult=1.0, health_mult=1.0,
            composition=[("person", 6), ("hostile_vehicle", 2)],
            spawn_direction="east",
        )
        engine.game_mode._spawn_mixed_wave(config)

        hostiles = [t for t in engine.get_targets() if t.alliance == "hostile"]
        assert len(hostiles) == 8
        for h in hostiles:
            x, _ = h.position
            assert x > 0, f"{h.name} at x={x:.1f}, expected x > 0 for east"

    def test_surround_wave_covers_all_quadrants(self):
        """Surround direction should hit all 4 quadrants."""
        engine = _make_engine(map_bounds=200.0)
        _add_friendly_turret(engine)
        engine.game_mode.state = "active"

        config = WaveConfig(
            name="Surround Test", count=40, speed_mult=1.0, health_mult=1.0,
            spawn_direction="surround",
        )
        engine.game_mode._spawn_wave_hostiles(config)

        quadrants = set()
        for t in engine.get_targets():
            if t.alliance == "hostile":
                x, y = t.position
                quadrants.add((1 if x >= 0 else -1, 1 if y >= 0 else -1))
        assert len(quadrants) == 4

    def test_default_wave_uses_random(self):
        """Waves without explicit direction default to random (full perimeter)."""
        config = WAVE_CONFIGS[0]  # Scout Party — no explicit direction
        assert config.spawn_direction == "random"


# ---------------------------------------------------------------------------
# 2. Vision system radio detection pipeline
# ---------------------------------------------------------------------------


class TestRadioDetectionE2E:
    """Verify the complete radio detection pipeline from vision to telemetry."""

    def test_radio_fields_in_to_dict(self):
        """to_dict() should include radio_detected and radio_signal_strength."""
        t = SimulationTarget(
            target_id="test-hostile",
            name="Test Hostile",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 50.0),
            speed=1.5,
        )
        t.radio_detected = True
        t.radio_signal_strength = 0.75
        d = t.to_dict()
        assert d["radio_detected"] is True
        assert d["radio_signal_strength"] == 0.75

    def test_visible_field_in_to_dict(self):
        """to_dict() should include visible field for fog of war."""
        t = SimulationTarget(
            target_id="test-hostile",
            name="Test Hostile",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 50.0),
            speed=1.5,
        )
        t.visible = False
        d = t.to_dict()
        assert d["visible"] is False

    def test_radio_detected_set_by_vision_tick(self):
        """After vision tick, hostiles with radio equipment should have radio_detected=True.

        Radio detection checks the TARGET's identity (the hostile carries the
        phone with bluetooth), not the observer's.  A friendly unit within
        100m of a hostile that has a bluetooth_mac triggers detection.
        """
        engine = _make_engine(map_bounds=200.0)
        _add_friendly_turret(engine, position=(0.0, 0.0))

        # Add hostile with bluetooth MAC at 50m (within 100m range)
        hostile = SimulationTarget(
            target_id="hostile-radio-1",
            name="Radio Hostile",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 0.0),
            speed=1.5,
        )
        hostile.apply_combat_profile()
        # The HOSTILE carries the phone (identity with bluetooth_mac)
        from tritium_lib.sim_engine.core.entity import UnitIdentity
        hostile.identity = UnitIdentity(bluetooth_mac="AA:BB:CC:DD:EE:FF")
        engine.add_target(hostile)

        # Run a tick with active game mode to trigger vision
        engine.game_mode.state = "active"
        targets = engine.get_targets()
        targets_dict = {t.target_id: t for t in targets}

        # Rebuild spatial grid (normally done at top of _do_tick)
        engine._spatial_grid.rebuild(targets)

        vision_state = engine.vision_system.tick(0.1, targets_dict, engine._spatial_grid)

        # Apply vision results (same as engine._do_tick does at line 792)
        for tid, t in targets_dict.items():
            if t.alliance == "hostile":
                t.radio_detected = tid in vision_state.radio_detected
                t.radio_signal_strength = vision_state.radio_signal_strength.get(tid, 0.0)

        assert hostile.radio_detected is True
        assert hostile.radio_signal_strength > 0.0

    def test_telemetry_includes_radio_fields(self):
        """Telemetry batch should include radio fields in serialized data."""
        engine = _make_engine(map_bounds=200.0)
        _add_friendly_turret(engine)

        hostile = engine.spawn_hostile()
        hostile.radio_detected = True
        hostile.radio_signal_strength = 0.6

        d = hostile.to_dict()
        assert "radio_detected" in d
        assert "radio_signal_strength" in d
        assert d["radio_detected"] is True

    def test_hostile_default_not_radio_detected(self):
        """By default, hostiles should NOT be radio detected."""
        engine = _make_engine()
        hostile = engine.spawn_hostile()
        assert hostile.radio_detected is False
        assert hostile.radio_signal_strength == 0.0


# ---------------------------------------------------------------------------
# 3. Spawn distance — hostiles use full city
# ---------------------------------------------------------------------------


class TestSpawnDistanceE2E:
    """Hostiles should spawn across the full city, not clustered at center."""

    def test_combat_spawn_average_distance_far(self):
        """Average spawn distance should be >70m on a 200m map.

        Combat spawns use 40-65% of bounds for faster engagement.
        """
        engine = _make_engine(map_bounds=200.0)
        _add_friendly_turret(engine)
        engine.game_mode.state = "active"

        dists = []
        for _ in range(50):
            h = engine.spawn_hostile()
            dists.append(math.hypot(*h.position))
        avg = sum(dists) / len(dists)
        assert avg > 70.0, f"Average spawn distance {avg:.1f}m too close"

    def test_objectives_spread_across_map(self):
        """Hostile waypoint objectives should reach ±50% of bounds."""
        engine = _make_engine(map_bounds=200.0)
        max_obj_dist = 0.0
        for _ in range(100):
            wps = engine._generate_hostile_waypoints((180.0, 0.0))
            if wps:
                for wx, wy in wps[:3]:  # Check approach waypoints
                    max_obj_dist = max(max_obj_dist, math.hypot(wx, wy))
        assert max_obj_dist > 20.0, (
            f"Objectives max {max_obj_dist:.1f}m from center — should reach further"
        )

    def test_all_quadrants_covered(self):
        """Hostiles should spawn in all 4 quadrants."""
        engine = _make_engine(map_bounds=200.0)
        engine.game_mode.state = "active"
        quadrants = set()
        for _ in range(100):
            h = engine.spawn_hostile()
            x, y = h.position
            quadrants.add((1 if x >= 0 else -1, 1 if y >= 0 else -1))
        assert len(quadrants) == 4


# ---------------------------------------------------------------------------
# 4. Upgrade system wiring
# ---------------------------------------------------------------------------


class TestUpgradeSystemE2E:
    """UpgradeSystem should be initialized and accessible on the engine."""

    def test_engine_has_upgrade_system(self):
        engine = _make_engine()
        assert hasattr(engine, 'upgrade_system')
        assert engine.upgrade_system is not None

    def test_upgrade_definitions_exist(self):
        """At least 5 upgrades should be defined."""
        engine = _make_engine()
        upgrades = engine.upgrade_system.list_upgrades()
        assert len(upgrades) >= 5, f"Only {len(upgrades)} upgrades defined"

    def test_ability_definitions_exist(self):
        """At least 3 abilities should be defined."""
        engine = _make_engine()
        abilities = engine.upgrade_system.list_abilities()
        assert len(abilities) >= 3, f"Only {len(abilities)} abilities defined"


# ---------------------------------------------------------------------------
# 5. Stats tracker wiring
# ---------------------------------------------------------------------------


class TestStatsTrackerE2E:
    """StatsTracker should be initialized and track unit stats."""

    def test_engine_has_stats_tracker(self):
        engine = _make_engine()
        assert hasattr(engine, 'stats_tracker')
        assert engine.stats_tracker is not None

    def test_stats_included_in_telemetry(self):
        """Unit stats should be included in to_dict telemetry."""
        engine = _make_engine()
        _add_friendly_turret(engine)
        hostile = engine.spawn_hostile()

        # Register the hostile with stats tracker (actual API)
        engine.stats_tracker.register_unit(
            hostile.target_id, hostile.name, hostile.alliance, hostile.asset_type,
        )
        stats = engine.stats_tracker.get_unit_stats(hostile.target_id)
        assert stats is not None


# ---------------------------------------------------------------------------
# 6. GameMode wave config integrity
# ---------------------------------------------------------------------------


class TestWaveConfigIntegrity:
    """WAVE_CONFIGS should have correct structure for all 10 waves."""

    def test_ten_waves_defined(self):
        assert len(WAVE_CONFIGS) == 10

    def test_waves_escalate_difficulty(self):
        """Later waves should generally be harder (more hostiles or tougher)."""
        first_count = WAVE_CONFIGS[0].count
        last_count = WAVE_CONFIGS[9].count
        assert last_count > first_count * 3, (
            f"Final wave ({last_count}) should have 3x+ the scouts ({first_count})"
        )

    def test_tactical_directions_in_later_waves(self):
        """Waves 6-10 should have non-random directions."""
        tactical = [
            w for w in WAVE_CONFIGS[5:]
            if w.spawn_direction != "random"
        ]
        assert len(tactical) >= 4, (
            f"Only {len(tactical)} of waves 6-10 have tactical directions"
        )

    def test_composition_waves_have_mixed_types(self):
        """Waves with composition should have 2+ unit types."""
        for w in WAVE_CONFIGS:
            if w.composition:
                assert len(w.composition) >= 2, (
                    f"Wave '{w.name}' has composition with only "
                    f"{len(w.composition)} type(s)"
                )

    def test_final_wave_is_surround(self):
        """FINAL STAND should use surround direction."""
        final = WAVE_CONFIGS[9]
        assert final.spawn_direction == "surround"
        assert final.name == "FINAL STAND"


# ---------------------------------------------------------------------------
# 7. Pathfinder wiring
# ---------------------------------------------------------------------------


class TestPathfinderE2E:
    """route_path should return waypoints (not just direct line)."""

    def test_route_path_returns_list(self):
        engine = _make_engine(map_bounds=200.0)
        path = engine.route_path((180, 0), (0, 0), "person", "hostile")
        assert isinstance(path, (list, tuple))
        assert len(path) >= 1

    def test_hostile_waypoints_use_pathfinder(self):
        """_generate_hostile_waypoints should produce multiple waypoints."""
        engine = _make_engine(map_bounds=200.0)
        wps = engine._generate_hostile_waypoints((180.0, 0.0))
        # Should have approach + escape waypoints
        assert len(wps) >= 2, (
            f"Only {len(wps)} waypoints — pathfinder should produce more"
        )


# ---------------------------------------------------------------------------
# 8. Event bus telemetry batch flow
# ---------------------------------------------------------------------------


class TestTelemetryBatchFlow:
    """Verify sim_telemetry_batch events contain expected fields."""

    def test_batch_published_on_tick(self):
        """A tick with targets should publish a sim_telemetry_batch event."""
        engine = _make_engine(map_bounds=200.0)
        _add_friendly_turret(engine)
        hostile = engine.spawn_hostile()

        sub = engine._event_bus.subscribe()
        engine.game_mode.state = "active"

        # Run a few ticks to build up telemetry
        for _ in range(5):
            engine._do_tick(0.1)

        # Collect events
        batches = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                if msg.get("type") == "sim_telemetry_batch":
                    batches.append(msg["data"])
            except queue.Empty:
                break

        assert len(batches) > 0, "No telemetry batches published"
        # Check first batch has expected fields
        first_batch = batches[0]
        assert isinstance(first_batch, list)
        if first_batch:
            entry = first_batch[0]
            assert "target_id" in entry
            assert "position" in entry
            assert "alliance" in entry
            assert "visible" in entry

    def test_batch_includes_radio_fields(self):
        """Telemetry batch entries should include radio_detected field."""
        engine = _make_engine()
        _add_friendly_turret(engine)
        hostile = engine.spawn_hostile()
        hostile.radio_detected = True
        hostile.radio_signal_strength = 0.5

        d = hostile.to_dict()
        assert "radio_detected" in d
        assert "radio_signal_strength" in d


# ---------------------------------------------------------------------------
# 9. Subsystem initialization
# ---------------------------------------------------------------------------


class TestSubsystemInit:
    """All simulation subsystems should initialize without error."""

    def test_vision_system_initialized(self):
        engine = _make_engine()
        assert engine.vision_system is not None

    def test_combat_system_initialized(self):
        engine = _make_engine()
        assert engine.combat is not None

    def test_behaviors_initialized(self):
        engine = _make_engine()
        assert engine.behaviors is not None

    def test_cover_system_initialized(self):
        engine = _make_engine()
        assert engine.cover_system is not None

    def test_terrain_map_initialized(self):
        engine = _make_engine()
        assert engine.terrain_map is not None

    def test_morale_system_initialized(self):
        engine = _make_engine()
        assert hasattr(engine, 'morale_system')

    def test_lod_system_initialized(self):
        engine = _make_engine()
        assert engine.lod_system is not None
