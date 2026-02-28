# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Building collision avoidance tests.

TDD: These tests are written BEFORE the implementation.

Three-layer defense:
1. Spawn-time: waypoint generators validate points aren't inside buildings
2. Add-time: engine.add_target() filters waypoints inside buildings
3. Tick-time: movement methods reject position updates into buildings

Flying units (drone, scout_drone, swarm_drone) are exempt from collision.
Pedestrians CAN enter buildings via doors but not through solid walls.
"""

import math
import time
import pytest
from unittest.mock import MagicMock

from engine.tactical.obstacles import BuildingObstacles, _point_in_polygon
from engine.simulation.target import SimulationTarget
from engine.simulation.engine import SimulationEngine
from engine.simulation.ambient import AmbientSpawner


# ---------------------------------------------------------------------------
# Test fixtures: buildings
# ---------------------------------------------------------------------------

def _make_square_building(cx: float, cy: float, half: float = 5.0):
    """Return a square polygon centered at (cx, cy)."""
    return [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]


def _make_obstacles_with_buildings(buildings: list[list[tuple[float, float]]]) -> BuildingObstacles:
    """Create BuildingObstacles loaded with given polygons (no API call)."""
    obs = BuildingObstacles()
    obs.polygons = buildings
    # Trigger AABB computation if the method exists
    if hasattr(obs, '_compute_aabbs'):
        obs._compute_aabbs()
    return obs


def _make_many_buildings(count: int = 227) -> list[list[tuple[float, float]]]:
    """Generate many small buildings spread across the map."""
    buildings = []
    cols = int(math.ceil(math.sqrt(count)))
    spacing = 20.0
    for i in range(count):
        row = i // cols
        col = i % cols
        cx = col * spacing - (cols * spacing / 2)
        cy = row * spacing - (cols * spacing / 2)
        buildings.append(_make_square_building(cx, cy, half=3.0))
    return buildings


def _make_engine_with_buildings(buildings: list[list[tuple[float, float]]]) -> SimulationEngine:
    """Create a SimulationEngine with building obstacles loaded."""
    bus = MagicMock()
    bus.subscribe.return_value = MagicMock()
    bus.subscribe.return_value.get = MagicMock(side_effect=Exception("timeout"))
    engine = SimulationEngine(bus, map_bounds=200.0)
    obs = _make_obstacles_with_buildings(buildings)
    engine.set_obstacles(obs)
    return engine


# ===========================================================================
# TestBuildingObstaclesAABB
# ===========================================================================


class TestBuildingObstaclesAABB:
    """AABB bounding box pre-filter for point_in_building performance."""

    def test_aabbs_computed_after_polygon_set(self):
        """After loading polygons, _aabbs should be populated."""
        obs = BuildingObstacles()
        obs.polygons = [_make_square_building(0, 0)]
        if hasattr(obs, '_compute_aabbs'):
            obs._compute_aabbs()
        assert hasattr(obs, '_aabbs'), "BuildingObstacles should have _aabbs attribute"
        assert len(obs._aabbs) == 1

    def test_aabb_rejects_distant_point(self):
        """A point far from all buildings should be rejected by AABB fast path."""
        obs = _make_obstacles_with_buildings([_make_square_building(0, 0, half=5.0)])
        # Point at (1000, 1000) is far from the building at (0,0)
        assert obs.point_in_building(1000.0, 1000.0) is False

    def test_point_in_building_correct_with_aabb(self):
        """AABB optimization must not change correctness of point_in_building."""
        building = _make_square_building(10.0, 20.0, half=5.0)
        obs = _make_obstacles_with_buildings([building])
        # Inside
        assert obs.point_in_building(10.0, 20.0) is True
        # Outside
        assert obs.point_in_building(0.0, 0.0) is False
        # Edge (just outside)
        assert obs.point_in_building(16.0, 20.0) is False

    def test_performance_aabb_under_budget(self):
        """1000 calls with 227 buildings should complete in under 50ms."""
        buildings = _make_many_buildings(227)
        obs = _make_obstacles_with_buildings(buildings)
        # Test point far from all buildings (AABB fast-reject case)
        start = time.perf_counter()
        for _ in range(1000):
            obs.point_in_building(9999.0, 9999.0)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 50.0, f"1000 calls took {elapsed_ms:.1f}ms (budget: 50ms)"


# ===========================================================================
# TestBugProof — These prove the bug EXISTS before the fix
# ===========================================================================


class TestBugProof:
    """Prove that units currently walk through buildings (the bug).

    These tests should PASS on the unfixed code (confirming the bug exists)
    and CONTINUE to pass after the fix (the fix prevents the behavior).
    """

    def test_legacy_tick_walks_through_building(self):
        """A person with waypoints crossing a building moves through it.

        Before the fix: the person walks straight through.
        After the fix: the person skips the blocked waypoint.
        """
        building = _make_square_building(0, 0, half=5.0)
        # Person starts at (-20, 0), waypoint at (20, 0) — straight through building
        target = SimulationTarget(
            target_id="bug-proof-1",
            name="Walker",
            alliance="neutral",
            asset_type="person",
            position=(-20.0, 0.0),
            speed=5.0,
            waypoints=[(20.0, 0.0)],
            is_combatant=False,
        )
        # Tick 200 times (20 seconds at 0.1s) — enough to cross the map
        for _ in range(200):
            target.tick(0.1)

        # The person should have reached the other side or despawned
        # This test just proves the tick loop runs without collision checks
        # The person's path crossed through (0,0) which is inside the building
        # We verify the target moved significantly in the X direction
        assert target.position[0] > -20.0, "Target should have moved"

    def test_yard_wander_can_land_inside_building(self):
        """AmbientSpawner._yard_wander() can generate points in buildings.

        We run many iterations and check if ANY point lands inside.
        With a building at (0,0) covering -5 to +5, and yard_wander
        generating points in the -15 to +15 range, collisions are expected.
        """
        building = _make_square_building(0, 0, half=5.0)
        bus = MagicMock()
        bus.subscribe.return_value = MagicMock()
        bus.subscribe.return_value.get = MagicMock(side_effect=Exception("timeout"))
        engine = SimulationEngine(bus, map_bounds=200.0)
        spawner = AmbientSpawner(engine)

        found_inside = False
        for _ in range(500):
            start, waypoints = spawner._yard_wander()
            for wp in [start] + waypoints:
                if _point_in_polygon(wp[0], wp[1], building):
                    found_inside = True
                    break
            if found_inside:
                break

        # This is a probabilistic test — with 500 tries and a 10x10 building
        # in a 30x30 yard area, hitting it is very likely (~11% per point)
        # We just confirm it's POSSIBLE (the bug exists)
        # If this flakes, it proves the coverage is low, not that the bug is fixed
        assert found_inside, "yard_wander should be able to generate points inside buildings (proving the bug)"

    def test_no_tick_time_collision_check(self):
        """A target with no collision checker moves freely through any position."""
        target = SimulationTarget(
            target_id="bug-proof-3",
            name="Unchecked",
            alliance="neutral",
            asset_type="person",
            position=(-10.0, 0.0),
            speed=5.0,
            waypoints=[(10.0, 0.0)],
            is_combatant=False,
        )
        # Verify no collision check attribute exists or it's None
        checker = getattr(target, '_collision_check', None)
        assert checker is None, "Default target should have no collision checker"


# ===========================================================================
# TestCollisionChecker
# ===========================================================================


class TestCollisionChecker:
    """Collision check integration with SimulationTarget tick methods."""

    def test_no_checker_by_default(self):
        """New target has _collision_check = None."""
        target = SimulationTarget(
            target_id="cc-1",
            name="Default",
            alliance="neutral",
            asset_type="person",
            position=(0.0, 0.0),
            speed=1.0,
            is_combatant=False,
        )
        assert getattr(target, '_collision_check', None) is None

    def test_set_checker_ground_unit(self):
        """Ground units (rover, person, tank) accept a collision checker."""
        for asset_type in ("rover", "person", "tank"):
            target = SimulationTarget(
                target_id=f"cc-ground-{asset_type}",
                name=f"Ground {asset_type}",
                alliance="friendly" if asset_type != "person" else "neutral",
                asset_type=asset_type,
                position=(0.0, 0.0),
                speed=2.0,
                is_combatant=(asset_type != "person"),
            )
            target.set_collision_check(lambda x, y: False)
            assert target._collision_check is not None

    def test_set_checker_flying_unit_ignored(self):
        """Flying units (drone, scout_drone, swarm_drone) are exempt."""
        for asset_type in ("drone", "scout_drone", "swarm_drone"):
            target = SimulationTarget(
                target_id=f"cc-fly-{asset_type}",
                name=f"Flying {asset_type}",
                alliance="friendly",
                asset_type=asset_type,
                position=(0.0, 0.0),
                speed=5.0,
                is_combatant=True,
            )
            target.set_collision_check(lambda x, y: True)
            # Flying units should ignore the checker
            assert target._collision_check is None

    def test_legacy_tick_stops_at_building(self):
        """With collision checker, person never enters building interior."""
        building = _make_square_building(0, 0, half=5.0)
        obs = _make_obstacles_with_buildings([building])

        target = SimulationTarget(
            target_id="cc-stop-1",
            name="Blocked Person",
            alliance="neutral",
            asset_type="person",
            position=(-20.0, 0.0),
            speed=5.0,
            waypoints=[(20.0, 0.0)],
            is_combatant=False,
        )
        target.set_collision_check(obs.point_in_building)

        # Tick 200 times
        for _ in range(200):
            target.tick(0.1)
            # At no point should the target be inside the building
            assert not obs.point_in_building(target.position[0], target.position[1]), \
                f"Target entered building at {target.position}"

    def test_legacy_tick_skips_blocked_waypoint(self):
        """When a waypoint is blocked, the target advances to the next one."""
        building = _make_square_building(0, 0, half=5.0)
        obs = _make_obstacles_with_buildings([building])

        # Waypoints: through building -> safe position
        target = SimulationTarget(
            target_id="cc-skip-1",
            name="Skipper",
            alliance="neutral",
            asset_type="person",
            position=(-20.0, 0.0),
            speed=5.0,
            waypoints=[(0.0, 0.0), (20.0, 20.0)],  # First wp inside building, second safe
            is_combatant=False,
        )
        target.set_collision_check(obs.point_in_building)

        for _ in range(400):
            target.tick(0.1)
            if target.status != "active":
                break

        # Target should have eventually despawned (reached final waypoint) or
        # moved past the blocked waypoint. It should NOT be stuck at start.
        assert target.position[0] > -20.0 or target.status != "active"

    def test_legacy_tick_terminal_when_all_blocked(self):
        """When all waypoints are blocked, target reaches terminal status."""
        building = _make_square_building(0, 0, half=5.0)
        obs = _make_obstacles_with_buildings([building])

        target = SimulationTarget(
            target_id="cc-term-1",
            name="AllBlocked",
            alliance="neutral",
            asset_type="person",
            position=(-20.0, 0.0),
            speed=5.0,
            waypoints=[(0.0, 0.0), (2.0, 2.0)],  # Both inside building
            is_combatant=False,
        )
        target.set_collision_check(obs.point_in_building)

        for _ in range(200):
            target.tick(0.1)
            if target.status != "active":
                break

        # Should have reached a terminal status since all waypoints are blocked
        assert target.status in ("despawned", "idle"), \
            f"Expected terminal status, got {target.status}"

    def test_controller_tick_stops_at_building(self):
        """Combatant with MovementController doesn't enter building."""
        building = _make_square_building(0, 0, half=5.0)
        obs = _make_obstacles_with_buildings([building])

        target = SimulationTarget(
            target_id="cc-ctrl-1",
            name="CombatBlocker",
            alliance="hostile",
            asset_type="person",
            position=(-20.0, 0.0),
            speed=5.0,
            waypoints=[(20.0, 0.0)],
            is_combatant=True,
            health=80.0,
            max_health=80.0,
            weapon_range=40.0,
            weapon_cooldown=2.5,
            weapon_damage=10.0,
        )
        target.set_collision_check(obs.point_in_building)

        for _ in range(200):
            target.tick(0.1)
            assert not obs.point_in_building(target.position[0], target.position[1]), \
                f"Combatant entered building at {target.position}"

    def test_flying_unit_passes_through(self):
        """Drone moves through building position freely (no collision)."""
        building = _make_square_building(0, 0, half=5.0)
        obs = _make_obstacles_with_buildings([building])

        target = SimulationTarget(
            target_id="cc-fly-1",
            name="FlyOver",
            alliance="friendly",
            asset_type="drone",
            position=(-20.0, 0.0),
            speed=10.0,
            waypoints=[(20.0, 0.0)],
            is_combatant=True,
            health=60.0,
            max_health=60.0,
            weapon_range=50.0,
            weapon_cooldown=1.0,
            weapon_damage=8.0,
        )
        # Even if we try to set a checker, flying units should be exempt
        target.set_collision_check(obs.point_in_building)

        # Tick until arrival
        passed_through = False
        for _ in range(200):
            target.tick(0.1)
            if abs(target.position[0]) < 4.0 and abs(target.position[1]) < 4.0:
                passed_through = True
            if target.status != "active":
                break

        # Drone should have passed through the building area
        assert passed_through or target.position[0] > 10.0, \
            "Drone should fly freely through building area"


# ===========================================================================
# TestPedestrianBuildingEntry
# ===========================================================================


class TestPedestrianBuildingEntry:
    """Pedestrians can enter buildings via doors but not through walls."""

    def test_pedestrian_can_reach_door_position(self):
        """Person navigating to a DoorPoint is NOT blocked."""
        building = _make_square_building(0, 0, half=5.0)
        obs = _make_obstacles_with_buildings([building])

        # Door is at the midpoint of an edge — inside the building polygon boundary
        # For a square from -5 to +5, the midpoint of the south edge is (0, -5)
        door_pos = (0.0, -5.0)

        target = SimulationTarget(
            target_id="ped-door-1",
            name="DoorVisitor",
            alliance="neutral",
            asset_type="person",
            position=(0.0, -20.0),
            speed=5.0,
            waypoints=[door_pos],
            is_combatant=False,
        )

        # Create a door-aware collision check
        def door_aware_check(x: float, y: float) -> bool:
            """Block if in building AND not near a door."""
            if not obs.point_in_building(x, y):
                return False
            # Within 2m of door = passable
            if math.hypot(x - door_pos[0], y - door_pos[1]) <= 2.0:
                return False
            return True

        target.set_collision_check(door_aware_check)

        for _ in range(200):
            target.tick(0.1)
            if target.status != "active":
                break

        # Person should reach near the door
        dist_to_door = math.hypot(
            target.position[0] - door_pos[0],
            target.position[1] - door_pos[1],
        )
        assert dist_to_door < 3.0 or target.status == "despawned", \
            f"Pedestrian should reach door, was at {target.position} (dist={dist_to_door:.1f})"

    def test_pedestrian_blocked_by_solid_wall(self):
        """Person not near a door IS blocked by building wall."""
        building = _make_square_building(0, 0, half=5.0)
        obs = _make_obstacles_with_buildings([building])

        # No doors — pure wall check
        target = SimulationTarget(
            target_id="ped-wall-1",
            name="WallBlocked",
            alliance="neutral",
            asset_type="person",
            position=(-20.0, 0.0),
            speed=5.0,
            waypoints=[(0.0, 0.0)],  # Center of building — no door
            is_combatant=False,
        )
        target.set_collision_check(obs.point_in_building)

        for _ in range(200):
            target.tick(0.1)
            assert not obs.point_in_building(target.position[0], target.position[1]), \
                f"Pedestrian entered building wall at {target.position}"

    def test_vehicle_always_blocked_by_building(self):
        """Vehicle cannot enter buildings even at door positions."""
        building = _make_square_building(0, 0, half=5.0)
        obs = _make_obstacles_with_buildings([building])

        target = SimulationTarget(
            target_id="veh-block-1",
            name="BlockedVehicle",
            alliance="neutral",
            asset_type="vehicle",
            position=(-20.0, 0.0),
            speed=8.0,
            waypoints=[(0.0, 0.0)],
            is_combatant=False,
        )
        target.set_collision_check(obs.point_in_building)

        for _ in range(200):
            target.tick(0.1)
            assert not obs.point_in_building(target.position[0], target.position[1]), \
                f"Vehicle entered building at {target.position}"


# ===========================================================================
# TestEngineWiring
# ===========================================================================


class TestEngineWiring:
    """Engine.add_target() sets collision checkers and filters waypoints."""

    def test_add_target_sets_collision_checker(self):
        """Engine with obstacles sets collision checker on ground units."""
        engine = _make_engine_with_buildings([_make_square_building(0, 0)])
        target = SimulationTarget(
            target_id="ew-1",
            name="GroundUnit",
            alliance="neutral",
            asset_type="person",
            position=(-20.0, 0.0),
            speed=1.0,
            is_combatant=False,
        )
        engine.add_target(target)
        assert target._collision_check is not None, \
            "Engine should set collision checker when obstacles are loaded"

    def test_add_target_filters_inside_waypoints(self):
        """Waypoints inside buildings are removed at add time."""
        building = _make_square_building(0, 0, half=5.0)
        engine = _make_engine_with_buildings([building])

        target = SimulationTarget(
            target_id="ew-filter-1",
            name="FilteredWP",
            alliance="neutral",
            asset_type="person",
            position=(-20.0, 0.0),
            speed=1.0,
            waypoints=[(0.0, 0.0), (20.0, 0.0)],  # First inside, second safe
            is_combatant=False,
        )
        engine.add_target(target)

        # The inside waypoint should have been removed
        for wp in target.waypoints:
            assert not engine.obstacles.point_in_building(wp[0], wp[1]), \
                f"Waypoint {wp} is inside a building and should have been filtered"

    def test_add_target_preserves_valid_waypoints(self):
        """Clean waypoints are untouched."""
        building = _make_square_building(0, 0, half=5.0)
        engine = _make_engine_with_buildings([building])

        safe_waypoints = [(-20.0, -20.0), (20.0, 20.0)]
        target = SimulationTarget(
            target_id="ew-preserve-1",
            name="SafeWP",
            alliance="neutral",
            asset_type="person",
            position=(-25.0, -25.0),
            speed=1.0,
            waypoints=list(safe_waypoints),
            is_combatant=False,
        )
        engine.add_target(target)
        assert len(target.waypoints) == 2, "Safe waypoints should be preserved"

    def test_add_target_no_checker_without_obstacles(self):
        """Without obstacles loaded, no checker is set."""
        bus = MagicMock()
        bus.subscribe.return_value = MagicMock()
        bus.subscribe.return_value.get = MagicMock(side_effect=Exception("timeout"))
        engine = SimulationEngine(bus, map_bounds=200.0)
        # No set_obstacles call

        target = SimulationTarget(
            target_id="ew-noobs-1",
            name="NoObs",
            alliance="neutral",
            asset_type="person",
            position=(0.0, 0.0),
            speed=1.0,
            is_combatant=False,
        )
        engine.add_target(target)
        assert getattr(target, '_collision_check', None) is None

    def test_flying_target_keeps_all_waypoints(self):
        """Drone waypoints are not filtered even if inside buildings."""
        building = _make_square_building(0, 0, half=5.0)
        engine = _make_engine_with_buildings([building])

        target = SimulationTarget(
            target_id="ew-fly-1",
            name="FlyWP",
            alliance="friendly",
            asset_type="drone",
            position=(-20.0, 0.0),
            speed=10.0,
            waypoints=[(0.0, 0.0), (20.0, 0.0)],  # First inside building
            is_combatant=True,
            health=60.0,
            max_health=60.0,
            weapon_range=50.0,
            weapon_cooldown=1.0,
            weapon_damage=8.0,
        )
        engine.add_target(target)
        assert len(target.waypoints) == 2, "Flying unit waypoints should NOT be filtered"


# ===========================================================================
# TestAmbientSpawnerBuildings
# ===========================================================================


class TestAmbientSpawnerBuildings:
    """AmbientSpawner path generators respect building boundaries."""

    def test_yard_wander_avoids_buildings(self):
        """All generated wander points should be outside buildings."""
        buildings = [_make_square_building(0, 0, half=5.0)]
        engine = _make_engine_with_buildings(buildings)
        spawner = AmbientSpawner(engine)

        obs = engine.obstacles
        for _ in range(100):
            start, waypoints = spawner._yard_wander()
            for pt in [start] + waypoints:
                assert not obs.point_in_building(pt[0], pt[1]), \
                    f"Yard wander point {pt} is inside a building"

    def test_delivery_door_avoids_buildings(self):
        """Delivery 'front door' position should not be inside a building."""
        buildings = [_make_square_building(0, 0, half=5.0)]
        engine = _make_engine_with_buildings(buildings)
        spawner = AmbientSpawner(engine)

        obs = engine.obstacles
        for _ in range(100):
            start, waypoints = spawner._delivery_path()
            for pt in waypoints:
                assert not obs.point_in_building(pt[0], pt[1]), \
                    f"Delivery waypoint {pt} is inside a building"

    def test_street_path_corner_avoids_buildings(self):
        """L-shaped corner point should not land inside a building."""
        from engine.simulation.ambient import _street_path
        buildings = [
            _make_square_building(-10, -10, half=3.0),  # At a street corner
            _make_square_building(10, 10, half=3.0),
        ]
        obs = _make_obstacles_with_buildings(buildings)

        # _street_path is a module-level function that doesn't know about buildings
        # After the fix, AmbientSpawner should validate the corner
        engine = _make_engine_with_buildings(buildings)
        spawner = AmbientSpawner(engine)

        # Spawn multiple neighbors and check paths
        for _ in range(50):
            start = spawner._random_edge()
            waypoints = spawner._sidewalk_path(start)
            for pt in waypoints:
                assert not obs.point_in_building(pt[0], pt[1]), \
                    f"Street path corner {pt} is inside a building"

    def test_fallback_when_yard_blocked(self):
        """Heavily built area falls back to edge path."""
        # Fill the yard area (-15 to +15) with buildings
        buildings = [
            _make_square_building(x, y, half=4.0)
            for x in range(-12, 13, 8)
            for y in range(-12, 13, 8)
        ]
        engine = _make_engine_with_buildings(buildings)
        spawner = AmbientSpawner(engine)
        obs = engine.obstacles

        # Should still generate valid paths (edge-only fallback)
        for _ in range(50):
            start, waypoints = spawner._yard_wander()
            for pt in [start] + waypoints:
                assert not obs.point_in_building(pt[0], pt[1]), \
                    f"Fallback wander point {pt} is inside a building"


# ===========================================================================
# TestIntegration
# ===========================================================================


class TestIntegration:
    """End-to-end integration tests with full engine."""

    def test_100_ticks_no_ground_unit_inside_building(self):
        """Engine with buildings + NPCs: no ground unit ever inside a building."""
        buildings = [
            _make_square_building(-10, 0, half=4.0),
            _make_square_building(10, 0, half=4.0),
            _make_square_building(0, 10, half=3.0),
        ]
        engine = _make_engine_with_buildings(buildings)
        obs = engine.obstacles

        # Add various ground units with paths that cross buildings
        targets = [
            SimulationTarget(
                target_id="int-person-1",
                name="PersonA",
                alliance="neutral",
                asset_type="person",
                position=(-25.0, 0.0),
                speed=3.0,
                waypoints=[(25.0, 0.0)],
                is_combatant=False,
            ),
            SimulationTarget(
                target_id="int-vehicle-1",
                name="CarA",
                alliance="neutral",
                asset_type="vehicle",
                position=(0.0, -25.0),
                speed=8.0,
                waypoints=[(0.0, 25.0)],
                is_combatant=False,
            ),
            SimulationTarget(
                target_id="int-rover-1",
                name="RoverA",
                alliance="friendly",
                asset_type="rover",
                position=(-25.0, 10.0),
                speed=4.0,
                waypoints=[(25.0, 10.0)],
                is_combatant=True,
                health=150.0,
                max_health=150.0,
                weapon_range=60.0,
                weapon_cooldown=2.0,
                weapon_damage=12.0,
            ),
        ]
        for t in targets:
            engine.add_target(t)

        flying_types = {"drone", "scout_drone", "swarm_drone"}
        for tick_num in range(100):
            engine._do_tick(0.1)
            for t in engine.get_targets():
                if t.asset_type in flying_types:
                    continue  # Flying units are exempt
                if t.status not in ("active",):
                    continue
                assert not obs.point_in_building(t.position[0], t.position[1]), \
                    f"Tick {tick_num}: {t.name} ({t.asset_type}) inside building at {t.position}"

    def test_drone_flies_over_buildings(self):
        """Drone CAN be at position inside building bounds."""
        buildings = [_make_square_building(0, 0, half=5.0)]
        engine = _make_engine_with_buildings(buildings)

        target = SimulationTarget(
            target_id="int-drone-1",
            name="DroneOverhead",
            alliance="friendly",
            asset_type="drone",
            position=(-20.0, 0.0),
            speed=10.0,
            waypoints=[(20.0, 0.0)],
            is_combatant=True,
            health=60.0,
            max_health=60.0,
            weapon_range=50.0,
            weapon_cooldown=1.0,
            weapon_damage=8.0,
        )
        engine.add_target(target)

        # Tick until the drone passes over the building area
        passed_building_area = False
        for _ in range(200):
            engine._do_tick(0.1)
            if abs(target.position[0]) < 4.0:
                passed_building_area = True
            if target.status != "active":
                break

        assert passed_building_area or target.position[0] > 15.0, \
            "Drone should fly through building area"

    def test_pedestrian_enters_building_via_door(self):
        """Person with door waypoint reaches building interior."""
        building = _make_square_building(0, 0, half=5.0)
        engine = _make_engine_with_buildings([building])

        # Door position at south edge midpoint
        door_pos = (0.0, -5.0)

        target = SimulationTarget(
            target_id="int-ped-door-1",
            name="DoorPed",
            alliance="neutral",
            asset_type="person",
            position=(0.0, -20.0),
            speed=5.0,
            waypoints=[door_pos],
            is_combatant=False,
        )

        # Set door-aware collision check
        obs = engine.obstacles
        def door_aware_check(x: float, y: float) -> bool:
            if not obs.point_in_building(x, y):
                return False
            if math.hypot(x - door_pos[0], y - door_pos[1]) <= 2.0:
                return False
            return True

        target.set_collision_check(door_aware_check)
        # Bypass engine add_target collision checker — set manually
        with engine._lock:
            engine._targets[target.target_id] = target

        for _ in range(200):
            engine._do_tick(0.1)
            if target.status != "active":
                break

        dist = math.hypot(
            target.position[0] - door_pos[0],
            target.position[1] - door_pos[1],
        )
        assert dist < 3.0 or target.status == "despawned", \
            f"Pedestrian should reach door, was at {target.position} (dist={dist:.1f})"
