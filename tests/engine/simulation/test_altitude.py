# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for altitude and 3D building collision awareness.

Phase 1: Data model (altitude field, building heights)
Phase 2: Altitude assignment (drones, turrets on roofs)
Phase 3: 3D collision (drones vs buildings at altitude)
"""

import math
from unittest.mock import MagicMock, patch

import pytest

from engine.simulation.target import SimulationTarget
from engine.tactical.obstacles import BuildingObstacles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    asset_type: str = "drone",
    alliance: str = "friendly",
    position: tuple[float, float] = (0.0, 0.0),
    speed: float = 4.0,
    is_combatant: bool = True,
    altitude: float = 0.0,
    **kwargs,
) -> SimulationTarget:
    """Create a SimulationTarget with sensible defaults for altitude tests."""
    return SimulationTarget(
        target_id=f"test-{asset_type}-1",
        name=f"Test {asset_type}",
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=speed,
        is_combatant=is_combatant,
        altitude=altitude,
        **kwargs,
    )


def _make_obstacles_with_heights(
    polygons: list[list[tuple[float, float]]],
    heights: list[float],
) -> BuildingObstacles:
    """Create a BuildingObstacles with explicit polygons and heights."""
    obs = BuildingObstacles()
    obs.polygons = polygons
    obs._heights = heights
    obs._compute_aabbs()
    return obs


def _square_polygon(cx: float, cy: float, half: float = 5.0) -> list[tuple[float, float]]:
    """Return a square polygon centered at (cx, cy)."""
    return [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]


# ===========================================================================
# Phase 1 — Data model
# ===========================================================================


class TestAltitudeDataModel:
    """SimulationTarget has an altitude field, serialized correctly."""

    def test_target_has_altitude_field(self):
        """Default altitude is 0.0."""
        t = _make_target(asset_type="rover", speed=2.0)
        assert hasattr(t, "altitude")
        assert t.altitude == 0.0

    def test_altitude_field_accepts_value(self):
        """altitude can be set at construction."""
        t = _make_target(altitude=15.0)
        assert t.altitude == 15.0

    def test_altitude_in_to_dict(self):
        """to_dict() includes altitude."""
        t = _make_target(altitude=12.5)
        d = t.to_dict()
        assert "altitude" in d
        assert d["altitude"] == 12.5

    def test_altitude_propagates_to_geo(self):
        """to_dict() passes z=altitude to local_to_latlng."""
        t = _make_target(altitude=20.0, position=(10.0, 20.0))
        with patch("engine.tactical.geo.local_to_latlng") as mock_geo:
            mock_geo.return_value = {"lat": 1.0, "lng": 2.0, "alt": 20.0}
            d = t.to_dict()
            mock_geo.assert_called_once_with(10.0, 20.0, 20.0)
            assert d["alt"] == 20.0


class TestBuildingHeights:
    """BuildingObstacles stores per-building heights."""

    def test_building_heights_stored_via_overture(self):
        """load_from_overture() stores heights in _heights list."""
        obs = BuildingObstacles()
        obs.load_from_overture([
            {"polygon": [(0, 0), (10, 0), (10, 10), (0, 10)], "height": 12.0},
            {"polygon": [(20, 20), (30, 20), (30, 30), (20, 30)], "height": 6.0},
        ])
        assert hasattr(obs, "_heights")
        assert len(obs._heights) == 2
        assert obs._heights[0] == 12.0
        assert obs._heights[1] == 6.0

    def test_building_heights_default_in_overture(self):
        """load_from_overture() defaults height to 8.0 if not specified."""
        obs = BuildingObstacles()
        obs.load_from_overture([
            {"polygon": [(0, 0), (10, 0), (10, 10), (0, 10)]},
        ])
        assert obs._heights[0] == 8.0

    def test_building_height_at_inside(self):
        """building_height_at() returns roof height for point inside building."""
        poly = _square_polygon(5.0, 5.0)
        obs = _make_obstacles_with_heights([poly], [12.0])
        result = obs.building_height_at(5.0, 5.0)
        assert result == 12.0

    def test_building_height_at_outside(self):
        """building_height_at() returns None for point outside any building."""
        poly = _square_polygon(5.0, 5.0)
        obs = _make_obstacles_with_heights([poly], [12.0])
        result = obs.building_height_at(50.0, 50.0)
        assert result is None

    def test_building_height_at_aabb_filtered(self):
        """building_height_at() skips buildings whose AABB doesn't contain the point."""
        # Building far away — point at origin should not even ray-cast
        poly = _square_polygon(100.0, 100.0)
        obs = _make_obstacles_with_heights([poly], [20.0])
        result = obs.building_height_at(0.0, 0.0)
        assert result is None

    def test_building_height_at_multiple_buildings(self):
        """building_height_at() returns height of the containing building."""
        poly1 = _square_polygon(5.0, 5.0)
        poly2 = _square_polygon(50.0, 50.0)
        obs = _make_obstacles_with_heights([poly1, poly2], [10.0, 25.0])
        assert obs.building_height_at(5.0, 5.0) == 10.0
        assert obs.building_height_at(50.0, 50.0) == 25.0
        assert obs.building_height_at(30.0, 30.0) is None

    def test_to_dicts_uses_per_building_height(self):
        """to_dicts() uses per-building heights instead of default_height."""
        poly1 = _square_polygon(5.0, 5.0)
        poly2 = _square_polygon(50.0, 50.0)
        obs = _make_obstacles_with_heights([poly1, poly2], [10.0, 25.0])
        dicts = obs.to_dicts()
        assert dicts[0]["height"] == 10.0
        assert dicts[1]["height"] == 25.0


# ===========================================================================
# Phase 2 — Altitude assignment
# ===========================================================================


class TestAltitudeAssignment:
    """Engine assigns cruising altitude to flying types, roof altitude to turrets."""

    def _make_engine(self, obstacles=None):
        """Create a minimal SimulationEngine for testing add_target."""
        from engine.simulation.engine import SimulationEngine
        from engine.comms.event_bus import EventBus
        eb = EventBus()
        eng = SimulationEngine(eb, map_bounds=200.0)
        if obstacles is not None:
            eng.set_obstacles(obstacles)
        return eng

    def test_drone_gets_cruising_altitude(self):
        """Drone gets cruising_altitude from unit type registry (15.0)."""
        eng = self._make_engine()
        t = _make_target(asset_type="drone", speed=4.0, altitude=0.0)
        eng.add_target(t)
        assert t.altitude == 15.0

    def test_scout_drone_gets_cruising_altitude(self):
        """Scout drone gets cruising_altitude = 10.0."""
        eng = self._make_engine()
        t = _make_target(asset_type="scout_drone", speed=5.0, altitude=0.0)
        eng.add_target(t)
        assert t.altitude == 10.0

    def test_swarm_drone_gets_cruising_altitude(self):
        """Swarm drone gets cruising_altitude = 8.0."""
        eng = self._make_engine()
        t = _make_target(asset_type="swarm_drone", alliance="hostile", speed=6.0, altitude=0.0)
        eng.add_target(t)
        assert t.altitude == 8.0

    def test_turret_on_building_gets_roof_altitude(self):
        """Turret positioned inside a building gets altitude = building height."""
        poly = _square_polygon(10.0, 10.0)
        obs = _make_obstacles_with_heights([poly], [15.0])
        eng = self._make_engine(obstacles=obs)
        t = _make_target(
            asset_type="turret", speed=0.0, position=(10.0, 10.0),
            is_combatant=True, altitude=0.0,
        )
        eng.add_target(t)
        assert t.altitude == 15.0

    def test_turret_outside_building_stays_ground(self):
        """Turret NOT inside a building keeps altitude = 0."""
        poly = _square_polygon(100.0, 100.0)
        obs = _make_obstacles_with_heights([poly], [15.0])
        eng = self._make_engine(obstacles=obs)
        t = _make_target(
            asset_type="turret", speed=0.0, position=(10.0, 10.0),
            is_combatant=True, altitude=0.0,
        )
        eng.add_target(t)
        assert t.altitude == 0.0

    def test_ground_unit_stays_at_zero(self):
        """Ground units (rover, person, tank) stay at altitude 0."""
        eng = self._make_engine()
        for atype in ("rover", "person", "tank"):
            t = _make_target(asset_type=atype, speed=2.0, altitude=0.0)
            eng.add_target(t)
            assert t.altitude == 0.0, f"{atype} should stay at altitude 0"

    def test_cruising_altitude_on_unit_type_base(self):
        """UnitType base class has cruising_altitude = 0.0 by default."""
        from engine.units.base import UnitType
        assert hasattr(UnitType, "cruising_altitude")
        assert UnitType.cruising_altitude == 0.0

    def test_drone_type_cruising_altitude(self):
        """Drone UnitType has cruising_altitude = 15.0."""
        from engine.units.robots.drone import Drone
        assert Drone.cruising_altitude == 15.0

    def test_scout_drone_type_cruising_altitude(self):
        """ScoutDrone UnitType has cruising_altitude = 10.0."""
        from engine.units.robots.scout_drone import ScoutDrone
        assert ScoutDrone.cruising_altitude == 10.0

    def test_swarm_drone_type_cruising_altitude(self):
        """SwarmDrone UnitType has cruising_altitude = 8.0."""
        from engine.units.people.swarm_drone import SwarmDrone
        assert SwarmDrone.cruising_altitude == 8.0


# ===========================================================================
# Phase 3 — 3D collision
# ===========================================================================


class TestThreeDCollision:
    """Flying units use altitude-aware building collision."""

    def test_drone_above_building_no_collision(self):
        """Drone at 15m altitude, building 8m tall -> no collision."""
        poly = _square_polygon(5.0, 5.0)
        obs = _make_obstacles_with_heights([poly], [8.0])

        t = _make_target(asset_type="drone", altitude=15.0, position=(5.0, 5.0))
        t.set_collision_check(
            obs.point_in_building,
            height_at=obs.building_height_at,
        )
        # If drone is above, collision check should return False (not blocked)
        assert t._collision_check is None or not t._collision_check(5.0, 5.0)

    def test_drone_below_building_collision(self):
        """Drone at 5m altitude, building 8m tall -> blocked."""
        poly = _square_polygon(5.0, 5.0)
        obs = _make_obstacles_with_heights([poly], [8.0])

        t = _make_target(asset_type="drone", altitude=5.0, position=(5.0, 5.0))
        t.set_collision_check(
            obs.point_in_building,
            height_at=obs.building_height_at,
        )
        assert t._collision_check is not None
        assert t._collision_check(5.0, 5.0) is True

    def test_drone_equal_height_collision(self):
        """Drone at 8m altitude, building 8m tall -> blocked (at roof level)."""
        poly = _square_polygon(5.0, 5.0)
        obs = _make_obstacles_with_heights([poly], [8.0])

        t = _make_target(asset_type="drone", altitude=8.0, position=(5.0, 5.0))
        t.set_collision_check(
            obs.point_in_building,
            height_at=obs.building_height_at,
        )
        assert t._collision_check is not None
        assert t._collision_check(5.0, 5.0) is True

    def test_drone_above_tall_building_blocked(self):
        """Drone at 15m altitude, building 20m tall -> blocked."""
        poly = _square_polygon(5.0, 5.0)
        obs = _make_obstacles_with_heights([poly], [20.0])

        t = _make_target(asset_type="drone", altitude=15.0, position=(5.0, 5.0))
        t.set_collision_check(
            obs.point_in_building,
            height_at=obs.building_height_at,
        )
        assert t._collision_check is not None
        assert t._collision_check(5.0, 5.0) is True

    def test_drone_outside_building_footprint_clear(self):
        """Drone outside building footprint -> no collision regardless of altitude."""
        poly = _square_polygon(100.0, 100.0)
        obs = _make_obstacles_with_heights([poly], [20.0])

        t = _make_target(asset_type="drone", altitude=5.0, position=(0.0, 0.0))
        t.set_collision_check(
            obs.point_in_building,
            height_at=obs.building_height_at,
        )
        # Outside footprint: height_at returns None, so no collision
        assert t._collision_check is None or not t._collision_check(0.0, 0.0)

    def test_ground_unit_still_uses_2d_collision(self):
        """Ground units (rover) are blocked by buildings regardless of height."""
        poly = _square_polygon(5.0, 5.0)
        obs = _make_obstacles_with_heights([poly], [8.0])

        t = _make_target(asset_type="rover", altitude=0.0, speed=2.0, position=(5.0, 5.0))
        t.set_collision_check(obs.point_in_building)
        assert t._collision_check is not None
        assert t._collision_check(5.0, 5.0) is True

    def test_3d_collision_during_tick(self):
        """Drone ticking through building area at low altitude -> position reverted."""
        poly = _square_polygon(15.0, 0.0, half=5.0)  # building at x=10..20
        obs = _make_obstacles_with_heights([poly], [12.0])

        from engine.simulation.engine import SimulationEngine
        from engine.comms.event_bus import EventBus
        eb = EventBus()
        eng = SimulationEngine(eb, map_bounds=200.0)
        eng.set_obstacles(obs)

        # Drone at altitude 5m (below building 12m), moving through building
        t = _make_target(
            asset_type="drone", altitude=5.0,
            position=(5.0, 0.0), speed=4.0,
        )
        t.waypoints = [(25.0, 0.0)]
        eng.add_target(t)
        # Engine should set altitude from registry (15.0), but we override
        t.altitude = 5.0
        # Re-set collision check with 3D awareness at the new altitude
        t.set_collision_check(
            obs.point_in_building,
            height_at=obs.building_height_at,
        )

        initial_x = t.position[0]
        # Tick several times — drone should not end up inside the building
        for _ in range(20):
            t.tick(0.1)
        # Drone should not be inside the building footprint
        # (either stopped before it, or skipped past)
        if 10.0 <= t.position[0] <= 20.0:
            # If inside footprint range, collision should have been blocked
            pytest.fail(
                f"Drone ended up inside building footprint at x={t.position[0]}"
            )

    def test_3d_no_collision_during_tick(self):
        """Drone ticking through building area at high altitude -> passes through."""
        poly = _square_polygon(15.0, 0.0, half=5.0)  # building at x=10..20
        obs = _make_obstacles_with_heights([poly], [8.0])

        from engine.simulation.engine import SimulationEngine
        from engine.comms.event_bus import EventBus
        eb = EventBus()
        eng = SimulationEngine(eb, map_bounds=200.0)
        eng.set_obstacles(obs)

        # Drone at altitude 15m (above building 8m)
        t = _make_target(
            asset_type="drone", altitude=0.0,
            position=(5.0, 0.0), speed=4.0,
        )
        t.waypoints = [(25.0, 0.0)]
        eng.add_target(t)
        # Engine sets altitude to 15.0 from registry, which is above 8m building
        assert t.altitude == 15.0

        # Tick several times — drone should pass through building area
        for _ in range(30):
            t.tick(0.1)
        # Drone should have reached beyond the building
        assert t.position[0] > 15.0, (
            f"Drone should have passed through building area, but x={t.position[0]}"
        )
