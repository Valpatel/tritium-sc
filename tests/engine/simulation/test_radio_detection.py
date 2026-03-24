# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for radio signal detection in VisionSystem.

Radio detection detects targets through walls at extended range (100m)
when those targets have radio signatures (bluetooth_mac, wifi_mac, cell_id).
Radio-detected targets are NOT visually visible but carry radio_detected=True
and radio_signal_strength based on distance.
"""

import math
import pytest

from tritium_lib.sim_engine.core.entity import SimulationTarget
from engine.simulation.terrain import TerrainMap
from tritium_lib.sim_engine.core.spatial import SpatialGrid
from tritium_lib.sim_engine.world.vision import VisionSystem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str,
    alliance: str = "friendly",
    asset_type: str = "turret",
    position: tuple[float, float] = (0.0, 0.0),
    heading: float = 0.0,
    **kwargs,
) -> SimulationTarget:
    """Create a minimal SimulationTarget for radio tests."""
    return SimulationTarget(
        target_id=target_id,
        name=target_id,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        heading=heading,
        speed=0.0 if asset_type == "turret" else 2.0,
        is_combatant=alliance != "neutral",
        **kwargs,
    )


def _build_grid(targets: list[SimulationTarget]) -> SpatialGrid:
    grid = SpatialGrid()
    grid.rebuild(targets)
    return grid


def _targets_dict(targets: list[SimulationTarget]) -> dict[str, SimulationTarget]:
    return {t.target_id: t for t in targets}


# ===========================================================================
# TestRadioDetectionFields
# ===========================================================================


class TestRadioDetectionFields:
    """SimulationTarget must have radio_detected and radio_signal_strength fields."""

    def test_radio_detected_default_false(self):
        """New targets start with radio_detected=False."""
        t = _make_target("t1")
        assert t.radio_detected is False

    def test_radio_signal_strength_default_zero(self):
        """New targets start with radio_signal_strength=0.0."""
        t = _make_target("t1")
        assert t.radio_signal_strength == 0.0

    def test_radio_detected_in_to_dict(self):
        """to_dict includes radio_detected field."""
        t = _make_target("t1")
        d = t.to_dict()
        assert "radio_detected" in d
        assert d["radio_detected"] is False

    def test_radio_signal_strength_in_to_dict(self):
        """to_dict includes radio_signal_strength field."""
        t = _make_target("t1")
        d = t.to_dict()
        assert "radio_signal_strength" in d
        assert d["radio_signal_strength"] == 0.0


# ===========================================================================
# TestRadioDetectionBasic
# ===========================================================================


class TestRadioDetectionBasic:
    """Radio detection pass in VisionSystem."""

    def test_person_with_radio_detected_through_wall(self):
        """Person hostile with radio signatures is radio-detected through buildings."""
        terrain = TerrainMap(200.0)
        # Place building between turret and enemy
        terrain.set_cell(0, 15, "building")
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        # Person type gets bluetooth_mac, wifi_mac, cell_id automatically
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        assert enemy.identity is not None
        assert enemy.identity.bluetooth_mac != ""
        targets = [turret, enemy]
        vs = VisionSystem(terrain_map=terrain)
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        # Visual detection blocked by building
        assert "h1" not in state.friendly_visible
        # But radio detection should work
        assert "h1" in state.radio_detected

    def test_person_radio_detected_at_extended_range(self):
        """Person hostile detected via radio at 80m (beyond normal vision range)."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        # turret cone_range=40, vision_radius=25 -- 80m is way beyond visual
        enemy = _make_target("h1", "hostile", "person", (0, 80))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible
        assert "h1" in state.radio_detected

    def test_radio_detection_range_100m(self):
        """Radio detection range is 100m -- enemy at 99m detected, at 110m not."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        near = _make_target("h1", "hostile", "person", (0, 99))
        far = _make_target("h2", "hostile", "person", (0, 110))
        targets = [turret, near, far]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.radio_detected
        assert "h2" not in state.radio_detected

    def test_robot_without_radio_not_radio_detected(self):
        """Turret asset_type does have wifi/ble MACs but is a friendly -- no radio tracking of friendlies."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        rover = _make_target("r1", "friendly", "rover", (50, 0))
        targets = [turret, rover]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        # Friendlies should not appear in radio_detected
        assert "r1" not in state.radio_detected

    def test_animal_no_radio_signature(self):
        """Animals have no radio signatures -- not radio-detected."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        animal = _make_target("a1", "hostile", "animal", (0, 50))
        targets = [turret, animal]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "a1" not in state.radio_detected


# ===========================================================================
# TestRadioSignalStrength
# ===========================================================================


class TestRadioSignalStrength:
    """Radio signal strength decreases with distance."""

    def test_close_target_strong_signal(self):
        """Target at 10m has signal strength close to 1.0."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (10, 0))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.radio_detected
        assert state.radio_signal_strength["h1"] > 0.8

    def test_far_target_weak_signal(self):
        """Target at 90m has weak signal strength."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (0, 90))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.radio_detected
        assert state.radio_signal_strength["h1"] < 0.3

    def test_signal_strength_decreases_with_distance(self):
        """Closer targets have stronger signal than farther ones."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        near = _make_target("h1", "hostile", "person", (20, 0))
        far = _make_target("h2", "hostile", "person", (80, 0))
        targets = [turret, near, far]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert state.radio_signal_strength["h1"] > state.radio_signal_strength["h2"]


# ===========================================================================
# TestRadioDetectionNoLOS
# ===========================================================================


class TestRadioDetectionNoLOS:
    """Radio detection ignores LOS (goes through buildings)."""

    def test_through_multiple_buildings(self):
        """Radio signal passes through multiple buildings."""
        terrain = TerrainMap(200.0)
        terrain.set_cell(0, 10, "building")
        terrain.set_cell(0, 20, "building")
        terrain.set_cell(0, 30, "building")
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (0, 40))
        targets = [turret, enemy]
        vs = VisionSystem(terrain_map=terrain)
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        # Visual blocked
        assert "h1" not in state.friendly_visible
        # Radio goes through
        assert "h1" in state.radio_detected

    def test_no_terrain_still_works(self):
        """Radio detection works even without terrain map."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (0, 50))
        targets = [turret, enemy]
        vs = VisionSystem()  # no terrain
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.radio_detected


# ===========================================================================
# TestRadioDetectedOnTarget
# ===========================================================================


class TestRadioDetectedOnTarget:
    """Engine sets radio_detected on SimulationTarget after vision tick."""

    def test_target_radio_detected_set(self):
        """After vision tick, target.radio_detected is True for radio-seen hostiles."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (0, 80))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        # The engine would normally set these, but verify the state contains the info
        assert "h1" in state.radio_detected
        assert "h1" in state.radio_signal_strength

    def test_visually_detected_also_radio(self):
        """If both visually and radio detected, both flags should be set."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        # Person within visual range AND has radio
        enemy = _make_target("h1", "hostile", "person", (0, 5))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible
        assert "h1" in state.radio_detected


# ===========================================================================
# TestRadioDetectionDeadUnits
# ===========================================================================


class TestRadioDetectionDeadUnits:
    """Dead/eliminated units should not be radio-detected."""

    def test_eliminated_not_radio_detected(self):
        """Eliminated hostile's radio should not be detected."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (0, 50))
        enemy.status = "eliminated"
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.radio_detected

    def test_destroyed_not_radio_detected(self):
        """Destroyed hostile's radio should not be detected."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (0, 50))
        enemy.status = "destroyed"
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.radio_detected
