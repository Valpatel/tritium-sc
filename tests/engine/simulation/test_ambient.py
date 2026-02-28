# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for AmbientSpawner and ambient-related features."""

from __future__ import annotations

import math

import pytest

from engine.simulation.ambient import (
    AmbientSpawner,
    _CAR_NAMES,
    _CAT_NAMES,
    _DELIVERY_NAMES,
    _DOG_NAMES,
    _MAP_MAX,
    _MAP_MIN,
    _NEIGHBOR_NAMES,
)
from engine.simulation.target import SimulationTarget, _DRAIN_RATES

pytestmark = pytest.mark.unit


class MockEngine:
    """Minimal engine stand-in for AmbientSpawner tests."""

    def __init__(self) -> None:
        self.targets: list[SimulationTarget] = []

    def add_target(self, target: SimulationTarget) -> None:
        self.targets.append(target)

    def get_targets(self) -> list[SimulationTarget]:
        return list(self.targets)


@pytest.fixture
def engine() -> MockEngine:
    return MockEngine()


@pytest.fixture
def spawner(engine: MockEngine) -> AmbientSpawner:
    return AmbientSpawner(engine)


# -- Name management --------------------------------------------------------


class TestPickName:
    def test_returns_name_from_list(self, spawner: AmbientSpawner) -> None:
        name = spawner._pick_name(_NEIGHBOR_NAMES)
        assert name in _NEIGHBOR_NAMES

    def test_returns_unique_names(self, spawner: AmbientSpawner) -> None:
        names = [spawner._pick_name(_DOG_NAMES) for _ in range(len(_DOG_NAMES))]
        assert len(set(names)) == len(_DOG_NAMES)

    def test_suffix_when_all_exhausted(self, spawner: AmbientSpawner) -> None:
        # Exhaust all cat names
        for _ in range(len(_CAT_NAMES)):
            spawner._pick_name(_CAT_NAMES)
        # Next pick must add a suffix
        extra = spawner._pick_name(_CAT_NAMES)
        assert extra not in _CAT_NAMES
        # Should end with a number suffix
        parts = extra.rsplit(" ", 1)
        assert len(parts) == 2
        assert parts[1].isdigit()
        assert parts[0] in _CAT_NAMES

    def test_suffix_increments(self, spawner: AmbientSpawner) -> None:
        for _ in range(len(_CAT_NAMES)):
            spawner._pick_name(_CAT_NAMES)
        first = spawner._pick_name(_CAT_NAMES)
        second = spawner._pick_name(_CAT_NAMES)
        assert first != second

    def test_name_tracked_in_used_set(self, spawner: AmbientSpawner) -> None:
        name = spawner._pick_name(_NEIGHBOR_NAMES)
        assert name in spawner._used_names


class TestReleaseName:
    def test_release_makes_name_available(self, spawner: AmbientSpawner) -> None:
        name = spawner._pick_name(_DOG_NAMES)
        assert name in spawner._used_names
        spawner.release_name(name)
        assert name not in spawner._used_names

    def test_release_unknown_name_no_error(self, spawner: AmbientSpawner) -> None:
        spawner.release_name("Nonexistent")  # should not raise

    def test_released_name_reusable(self, spawner: AmbientSpawner) -> None:
        # Use all dog names
        used = [spawner._pick_name(_DOG_NAMES) for _ in range(len(_DOG_NAMES))]
        # Release one
        released = used[0]
        spawner.release_name(released)
        # Next pick should return the released name (only one available)
        name = spawner._pick_name(_DOG_NAMES)
        assert name == released


# -- Edge position generators -----------------------------------------------


class TestRandomEdge:
    def test_returns_tuple(self, spawner: AmbientSpawner) -> None:
        pos = spawner._random_edge()
        assert isinstance(pos, tuple)
        assert len(pos) == 2

    def test_on_map_boundary(self, spawner: AmbientSpawner) -> None:
        """At least one coordinate should be at (or near) the map edge."""
        for _ in range(50):
            x, y = spawner._random_edge()
            on_edge = (
                abs(x - _MAP_MAX) < 0.01
                or abs(x - _MAP_MIN) < 0.01
                or abs(y - _MAP_MAX) < 0.01
                or abs(y - _MAP_MIN) < 0.01
            )
            assert on_edge, f"({x}, {y}) not on any edge"

    def test_coordinate_within_bounds(self, spawner: AmbientSpawner) -> None:
        for _ in range(50):
            x, y = spawner._random_edge()
            assert _MAP_MIN <= x <= _MAP_MAX
            assert _MAP_MIN <= y <= _MAP_MAX


class TestOppositeEdge:
    def test_north_to_south(self, spawner: AmbientSpawner) -> None:
        pos = (5.0, _MAP_MAX)
        opp = spawner._opposite_edge(pos)
        assert opp[1] == _MAP_MIN

    def test_south_to_north(self, spawner: AmbientSpawner) -> None:
        pos = (5.0, _MAP_MIN)
        opp = spawner._opposite_edge(pos)
        assert opp[1] == _MAP_MAX

    def test_east_to_west(self, spawner: AmbientSpawner) -> None:
        pos = (_MAP_MAX, 5.0)
        opp = spawner._opposite_edge(pos)
        assert opp[0] == _MAP_MIN

    def test_west_to_east(self, spawner: AmbientSpawner) -> None:
        pos = (_MAP_MIN, 5.0)
        opp = spawner._opposite_edge(pos)
        assert opp[0] == _MAP_MAX

    def test_x_jitter_applied(self, spawner: AmbientSpawner) -> None:
        """Opposite edge adds random x/y jitter (up to +/-10)."""
        pos = (0.0, _MAP_MAX)
        results = [spawner._opposite_edge(pos) for _ in range(20)]
        x_values = [r[0] for r in results]
        # Not all x values should be identical (randomness)
        assert len(set(x_values)) > 1


# -- Path generators --------------------------------------------------------


class TestSidewalkPath:
    def test_returns_two_waypoints(self, spawner: AmbientSpawner) -> None:
        start = spawner._random_edge()
        path = spawner._sidewalk_path(start)
        assert len(path) == 2

    def test_midpoint_clamped_to_map(self, spawner: AmbientSpawner) -> None:
        start = (_MAP_MAX, _MAP_MAX)
        path = spawner._sidewalk_path(start)
        for x, y in path:
            assert _MAP_MIN <= x <= _MAP_MAX
            assert _MAP_MIN <= y <= _MAP_MAX


class TestRoadPath:
    def test_returns_two_waypoints(self, spawner: AmbientSpawner) -> None:
        """Road paths now follow the street grid (L-shaped), producing 2 waypoints."""
        start = spawner._random_edge()
        path = spawner._road_path(start)
        assert len(path) == 2

    def test_endpoint_on_opposite_edge(self, spawner: AmbientSpawner) -> None:
        start = (0.0, _MAP_MAX)  # north edge
        path = spawner._road_path(start)
        # Last waypoint should be on the opposite (south) edge
        assert path[-1][1] == _MAP_MIN  # should go to south


class TestYardWander:
    def test_returns_start_and_waypoints(self, spawner: AmbientSpawner) -> None:
        start, waypoints = spawner._yard_wander()
        assert isinstance(start, tuple)
        assert len(start) == 2
        assert isinstance(waypoints, list)
        assert len(waypoints) >= 4  # 3-5 wander + 1 exit

    def test_wander_count_range(self, spawner: AmbientSpawner) -> None:
        lengths = set()
        for _ in range(50):
            _, waypoints = spawner._yard_wander()
            lengths.add(len(waypoints))
        # 3-5 wander points + 1 exit = 4-6 total waypoints
        assert lengths.issubset({4, 5, 6})

    def test_exit_point_on_edge(self, spawner: AmbientSpawner) -> None:
        _, waypoints = spawner._yard_wander()
        exit_x, exit_y = waypoints[-1]
        on_edge = (
            abs(exit_x - _MAP_MAX) < 0.01
            or abs(exit_x - _MAP_MIN) < 0.01
            or abs(exit_y - _MAP_MAX) < 0.01
            or abs(exit_y - _MAP_MIN) < 0.01
        )
        assert on_edge

    def test_waypoints_clamped(self, spawner: AmbientSpawner) -> None:
        for _ in range(20):
            _, waypoints = spawner._yard_wander()
            for x, y in waypoints:
                assert _MAP_MIN <= x <= _MAP_MAX
                assert _MAP_MIN <= y <= _MAP_MAX


class TestDeliveryPath:
    def test_returns_start_and_three_waypoints(self, spawner: AmbientSpawner) -> None:
        start, waypoints = spawner._delivery_path()
        assert isinstance(start, tuple)
        assert len(waypoints) == 3

    def test_door_pause_pattern(self, spawner: AmbientSpawner) -> None:
        """Waypoints[0] and [1] should be the same (door pause)."""
        _, waypoints = spawner._delivery_path()
        assert waypoints[0] == waypoints[1]

    def test_return_edge_is_last(self, spawner: AmbientSpawner) -> None:
        _, waypoints = spawner._delivery_path()
        rx, ry = waypoints[2]
        on_edge = (
            abs(rx - _MAP_MAX) < 0.01
            or abs(rx - _MAP_MIN) < 0.01
            or abs(ry - _MAP_MAX) < 0.01
            or abs(ry - _MAP_MIN) < 0.01
        )
        assert on_edge

    def test_start_on_edge(self, spawner: AmbientSpawner) -> None:
        start, _ = spawner._delivery_path()
        sx, sy = start
        on_edge = (
            abs(sx - _MAP_MAX) < 0.01
            or abs(sx - _MAP_MIN) < 0.01
            or abs(sy - _MAP_MAX) < 0.01
            or abs(sy - _MAP_MIN) < 0.01
        )
        assert on_edge


# -- Individual spawn methods -----------------------------------------------


class TestSpawnNeighbor:
    def test_creates_neutral_person(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_neighbor()
        assert len(engine.targets) == 1
        t = engine.targets[0]
        assert t.alliance == "neutral"
        assert t.asset_type == "person"

    def test_speed_is_walking(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_neighbor()
        assert engine.targets[0].speed == 1.2

    def test_has_waypoints(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_neighbor()
        assert len(engine.targets[0].waypoints) >= 1


class TestSpawnCar:
    def test_creates_neutral_vehicle(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_car()
        assert len(engine.targets) == 1
        t = engine.targets[0]
        assert t.alliance == "neutral"
        assert t.asset_type == "vehicle"

    def test_speed_is_driving(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_car()
        assert engine.targets[0].speed == 8.0

    def test_road_path_street_following(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        """Cars follow L-shaped street paths (2 waypoints: corner + destination)."""
        spawner._spawn_car()
        assert len(engine.targets[0].waypoints) == 2


class TestSpawnDog:
    def test_creates_neutral_animal(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_dog()
        assert len(engine.targets) == 1
        t = engine.targets[0]
        assert t.alliance == "neutral"
        assert t.asset_type == "animal"

    def test_speed(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_dog()
        assert engine.targets[0].speed == 2.0

    def test_yard_wander_path(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_dog()
        # yard_wander: 3-5 wander + 1 exit
        assert len(engine.targets[0].waypoints) >= 4


class TestSpawnCat:
    def test_creates_neutral_animal(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_cat()
        assert len(engine.targets) == 1
        t = engine.targets[0]
        assert t.alliance == "neutral"
        assert t.asset_type == "animal"

    def test_speed(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_cat()
        assert engine.targets[0].speed == 1.5


class TestSpawnDelivery:
    def test_creates_neutral_person(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_delivery()
        assert len(engine.targets) == 1
        t = engine.targets[0]
        assert t.alliance == "neutral"
        assert t.asset_type == "person"

    def test_speed(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_delivery()
        assert engine.targets[0].speed == 1.0

    def test_delivery_path_length(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_delivery()
        assert len(engine.targets[0].waypoints) == 3


# -- _spawn_random dispatch -------------------------------------------------


class TestSpawnRandom:
    def test_low_roll_spawns_neighbor(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("random.random", lambda: 0.10)
        spawner._spawn_random()
        assert len(engine.targets) == 1
        assert engine.targets[0].speed == 1.2  # neighbor speed

    def test_roll_0_35_spawns_car(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("random.random", lambda: 0.40)
        spawner._spawn_random()
        assert len(engine.targets) == 1
        assert engine.targets[0].asset_type == "vehicle"

    def test_roll_0_55_spawns_dog(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("random.random", lambda: 0.60)
        spawner._spawn_random()
        assert len(engine.targets) == 1
        assert engine.targets[0].speed == 2.0  # dog speed

    def test_roll_0_70_spawns_cat(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("random.random", lambda: 0.75)
        spawner._spawn_random()
        assert len(engine.targets) == 1
        assert engine.targets[0].speed == 1.5  # cat speed

    def test_roll_0_80_spawns_delivery(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("random.random", lambda: 0.90)
        spawner._spawn_random()
        assert len(engine.targets) == 1
        assert engine.targets[0].speed == 1.0  # delivery speed


# -- MAX_NEUTRALS cap -------------------------------------------------------


class TestMaxNeutrals:
    def test_max_neutrals_is_80(self) -> None:
        assert AmbientSpawner.MAX_NEUTRALS == 80

    def test_count_excludes_despawned(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        """Despawned/destroyed neutrals should not count toward the cap."""
        # Fill with 8 neutrals, then despawn one
        for _ in range(8):
            spawner._spawn_neighbor()
        assert len(engine.targets) == 8
        engine.targets[0].status = "despawned"
        # Count live neutrals (mimicking _spawn_loop logic)
        neutral_count = sum(
            1 for t in engine.get_targets()
            if t.alliance == "neutral" and t.status not in ("despawned", "destroyed")
        )
        assert neutral_count == 7  # room for one more


# -- Enabled toggle ---------------------------------------------------------


class TestEnabledToggle:
    def test_default_enabled(self, spawner: AmbientSpawner) -> None:
        assert spawner.enabled is True

    def test_disable(self, spawner: AmbientSpawner) -> None:
        spawner.enabled = False
        assert spawner.enabled is False


# -- Neutral despawn -------------------------------------------------------


class TestNeutralDespawn:
    def test_neutral_single_waypoint_despawns(self) -> None:
        """Neutral target reaching its only waypoint should despawn."""
        t = SimulationTarget(
            target_id="n1", name="Neighbor", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=100.0, waypoints=[(1.0, 0.0)],
        )
        for _ in range(20):
            t.tick(0.1)
        assert t.status == "despawned"

    def test_neutral_multi_waypoint_despawns(self) -> None:
        """Neutral target reaching its final waypoint should despawn (not loop)."""
        t = SimulationTarget(
            target_id="n1", name="Neighbor", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=100.0, waypoints=[(2.0, 0.0), (4.0, 0.0), (6.0, 0.0)],
        )
        for _ in range(100):
            t.tick(0.1)
        assert t.status == "despawned"

    def test_friendly_does_not_despawn(self) -> None:
        """Friendly target should never get 'despawned' status."""
        t = SimulationTarget(
            target_id="f1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=100.0, waypoints=[(2.0, 0.0), (4.0, 0.0), (6.0, 0.0)],
        )
        for _ in range(100):
            t.tick(0.1)
        assert t.status != "despawned"
        # Without loop_waypoints, friendly arrives at end
        assert t.status == "arrived"

    def test_hostile_single_waypoint_escapes(self) -> None:
        """Hostile target completing its path should escape, not despawn."""
        t = SimulationTarget(
            target_id="h1", name="Intruder", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
            speed=100.0, waypoints=[(1.0, 0.0)],
        )
        for _ in range(20):
            t.tick(0.1)
        assert t.status == "escaped"


# -- Vehicle / animal drain rates ------------------------------------------


class TestDrainRates:
    def test_vehicle_no_drain(self) -> None:
        t = SimulationTarget(
            target_id="c1", name="Car", alliance="neutral",
            asset_type="vehicle", position=(0.0, 0.0),
            battery=1.0, waypoints=[(100.0, 0.0)],
        )
        t.tick(100.0)
        assert t.battery == 1.0

    def test_animal_no_drain(self) -> None:
        t = SimulationTarget(
            target_id="d1", name="Dog", alliance="neutral",
            asset_type="animal", position=(0.0, 0.0),
            battery=1.0, waypoints=[(100.0, 0.0)],
        )
        t.tick(100.0)
        assert t.battery == 1.0


# ============================================================================
# EDGE CASE TESTS — Pass 3
# ============================================================================


# -- _opposite_edge non-edge positions (edge case #2) ----------------------


class TestOppositeEdgeNonEdge:
    """_opposite_edge when position is NOT near any map edge."""

    def test_center_defaults_to_east(self, spawner: AmbientSpawner) -> None:
        """Position (0, 0) is far from all edges. The else branch sends to x=MAP_MAX (east)."""
        opp = spawner._opposite_edge((0.0, 0.0))
        assert opp[0] == _MAP_MAX

    def test_interior_point_defaults_to_east(self, spawner: AmbientSpawner) -> None:
        """Any interior point not within 2 units of an edge goes east."""
        opp = spawner._opposite_edge((10.0, 10.0))
        assert opp[0] == _MAP_MAX

    def test_near_edge_but_outside_threshold(self, spawner: AmbientSpawner) -> None:
        """Position at y=27 is 3 units from north edge (threshold=2), so else branch fires."""
        opp = spawner._opposite_edge((0.0, 27.0))
        # 27 is 3 away from MAP_MAX=30, which is > 2, so else branch -> east
        assert opp[0] == _MAP_MAX

    def test_just_inside_threshold(self, spawner: AmbientSpawner) -> None:
        """Position at y=28.5 is 1.5 from north edge (< 2), so matches north->south."""
        opp = spawner._opposite_edge((0.0, 28.5))
        assert opp[1] == _MAP_MIN

    def test_origin_y_jitter_clamped(self, spawner: AmbientSpawner) -> None:
        """Else branch uses y + jitter; verify it's clamped within map."""
        for _ in range(50):
            opp = spawner._opposite_edge((0.0, 0.0))
            assert _MAP_MIN <= opp[1] <= _MAP_MAX


# -- _random_edge coordinate ranges (edge case #3) -------------------------


class TestRandomEdgeCoordinateRange:
    """Variable coordinate uses 0.8 factor, so spans [-24, 24] not [-30, 30]."""

    def test_variable_coord_never_at_corner(self, spawner: AmbientSpawner) -> None:
        """The non-edge coordinate should never exceed MAP_MAX * 0.8 = 24."""
        for _ in range(200):
            x, y = spawner._random_edge()
            if abs(y - _MAP_MAX) < 0.01 or abs(y - _MAP_MIN) < 0.01:
                # y is on edge, so x is the variable coordinate
                assert abs(x) <= _MAP_MAX * 0.8 + 0.01
            else:
                # x is on edge, so y is the variable coordinate
                assert abs(y) <= _MAP_MAX * 0.8 + 0.01

    def test_edge_coord_is_exactly_at_boundary(self, spawner: AmbientSpawner) -> None:
        """The fixed edge coordinate should be exactly _MAP_MAX or _MAP_MIN."""
        for _ in range(100):
            x, y = spawner._random_edge()
            at_x_edge = abs(x) == _MAP_MAX
            at_y_edge = abs(y) == _MAP_MAX
            assert at_x_edge or at_y_edge


# -- Neutral target with no waypoints (edge case #4) -----------------------


class TestNeutralEmptyWaypoints:
    def test_empty_waypoints_becomes_idle(self) -> None:
        """Neutral target with waypoints=[] should become idle, not crash."""
        t = SimulationTarget(
            target_id="n1", name="Lost", alliance="neutral",
            asset_type="person", position=(5.0, 5.0),
            speed=1.0, waypoints=[],
        )
        t.tick(1.0)
        assert t.status == "idle"

    def test_empty_waypoints_never_despawns(self) -> None:
        """Idle target with no waypoints never transitions to despawned."""
        t = SimulationTarget(
            target_id="n1", name="Stuck", alliance="neutral",
            asset_type="person", position=(5.0, 5.0),
            speed=1.0, waypoints=[],
        )
        for _ in range(100):
            t.tick(1.0)
        assert t.status == "idle"

    def test_empty_waypoints_position_unchanged(self) -> None:
        """No waypoints means no movement."""
        t = SimulationTarget(
            target_id="n1", name="Still", alliance="neutral",
            asset_type="person", position=(5.0, 5.0),
            speed=1.0, waypoints=[],
        )
        t.tick(10.0)
        assert t.position == (5.0, 5.0)


# -- Waypoint arrival threshold and overshoot (edge case #5) ----------------


class TestWaypointArrival:
    def test_arrival_threshold_is_one_unit(self) -> None:
        """Target within 1.0 unit of waypoint should advance/despawn."""
        t = SimulationTarget(
            target_id="t1", name="Close", alliance="neutral",
            asset_type="person", position=(0.5, 0.0),
            speed=1.0, waypoints=[(1.0, 0.0)],
        )
        # dist = 0.5, which is < 1.0 threshold
        t.tick(0.1)
        assert t.status == "despawned"

    def test_just_outside_threshold(self) -> None:
        """Target at exactly 1.0 unit from waypoint should NOT arrive (< 1.0 required)."""
        t = SimulationTarget(
            target_id="t1", name="Edge", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=0.01, waypoints=[(1.0, 0.0)],
        )
        # dist = 1.0 which is NOT < 1.0
        t.tick(0.001)
        assert t.status == "active"

    def test_large_dt_no_overshoot(self) -> None:
        """With huge dt, step is clamped to dist — no overshoot past waypoint."""
        t = SimulationTarget(
            target_id="t1", name="Fast", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=100.0, waypoints=[(5.0, 0.0)],
        )
        # speed * dt = 100 * 1000 = 100000, but dist is only 5.0
        t.tick(1000.0)
        # Should be at exactly (5.0, 0.0) — not beyond
        assert abs(t.position[0] - 5.0) < 0.001
        assert abs(t.position[1]) < 0.001

    def test_two_tick_arrival_for_distant_approach(self) -> None:
        """Target needs one tick to approach, next tick dist < 1.0 triggers arrival."""
        t = SimulationTarget(
            target_id="t1", name="Approach", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=10.0, waypoints=[(5.0, 0.0)],
        )
        t.tick(0.5)  # moves 5.0 to the waypoint
        assert t.status == "active"  # at waypoint but arrival not checked yet
        t.tick(0.1)  # now dist < 1.0, arrival triggers
        assert t.status == "despawned"


# -- _pick_name edge cases (edge cases #6, #7) ----------------------------


class TestPickNameEdgeCases:
    def test_single_element_list_exhausted(self, spawner: AmbientSpawner) -> None:
        """When a list has one name and it's used, suffix is added."""
        single = ["Solo"]
        first = spawner._pick_name(single)
        assert first == "Solo"
        second = spawner._pick_name(single)
        assert second == "Solo 2"
        third = spawner._pick_name(single)
        assert third == "Solo 3"

    def test_many_suffixes_no_infinite_loop(self, spawner: AmbientSpawner) -> None:
        """Even with many used names, _pick_name terminates."""
        tiny = ["X"]
        for i in range(50):
            name = spawner._pick_name(tiny)
            assert name is not None
        # First is "X", then "X 2" through "X 50"
        assert "X" in spawner._used_names
        assert "X 50" in spawner._used_names

    def test_suffix_starts_at_2(self, spawner: AmbientSpawner) -> None:
        """After exhaustion, first suffix should be 2, not 1."""
        names = ["A", "B"]
        spawner._pick_name(names)
        spawner._pick_name(names)
        third = spawner._pick_name(names)
        # Both A and B used; suffix starts at 2
        parts = third.rsplit(" ", 1)
        assert int(parts[1]) >= 2

    def test_release_suffixed_name(self, spawner: AmbientSpawner) -> None:
        """Releasing a suffixed name should work correctly."""
        tiny = ["Only"]
        spawner._pick_name(tiny)  # "Only"
        suffixed = spawner._pick_name(tiny)  # "Only 2"
        assert suffixed == "Only 2"
        spawner.release_name(suffixed)
        assert "Only 2" not in spawner._used_names
        # "Only" is still used, so next pick should get "Only 2" again
        again = spawner._pick_name(tiny)
        assert again == "Only 2"


# -- Zero speed target (edge case) ----------------------------------------


class TestZeroSpeed:
    def test_zero_speed_becomes_stationary(self) -> None:
        """Target with speed=0 should become stationary, not crash."""
        t = SimulationTarget(
            target_id="t1", name="Sentry", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            speed=0.0, waypoints=[(10.0, 10.0)],
        )
        t.tick(1.0)
        assert t.status == "stationary"

    def test_zero_speed_no_movement(self) -> None:
        """Stationary target should not move."""
        t = SimulationTarget(
            target_id="t1", name="Sentry", alliance="friendly",
            asset_type="turret", position=(5.0, 5.0),
            speed=0.0, waypoints=[(10.0, 10.0)],
        )
        t.tick(100.0)
        assert t.position == (5.0, 5.0)


# -- Destroyed / low_battery targets don't move (edge case) ----------------


class TestDestroyedAndLowBattery:
    def test_destroyed_does_not_move(self) -> None:
        t = SimulationTarget(
            target_id="t1", name="Wreck", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=5.0, waypoints=[(100.0, 0.0)], status="destroyed",
        )
        t.tick(10.0)
        assert t.position == (0.0, 0.0)

    def test_low_battery_does_not_move(self) -> None:
        t = SimulationTarget(
            target_id="t1", name="Dead", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=5.0, waypoints=[(100.0, 0.0)], status="low_battery",
        )
        t.tick(10.0)
        assert t.position == (0.0, 0.0)

    def test_battery_drains_to_low_battery(self) -> None:
        """Target battery draining below 0.05 should transition to low_battery."""
        t = SimulationTarget(
            target_id="t1", name="Drone", alliance="friendly",
            asset_type="drone", position=(0.0, 0.0),
            speed=1.0, battery=0.06, waypoints=[(100.0, 0.0)],
        )
        # drone drain = 0.002/s, need to drain 0.02 to get below 0.05
        # 0.06 - 0.002 * 10 = 0.04 < 0.05
        t.tick(10.0)
        assert t.status == "low_battery"

    def test_battery_never_negative(self) -> None:
        """Battery should clamp at 0.0, never go negative."""
        t = SimulationTarget(
            target_id="t1", name="Drone", alliance="friendly",
            asset_type="drone", position=(0.0, 0.0),
            speed=1.0, battery=0.001, waypoints=[(100.0, 0.0)],
        )
        t.tick(1000.0)
        assert t.battery >= 0.0


# -- Unknown asset_type drain rate fallback (edge case #9) -----------------


class TestUnknownAssetTypeDrain:
    def test_unknown_type_uses_fallback_drain(self) -> None:
        """Asset type not in _DRAIN_RATES gets fallback rate of 0.001/s."""
        t = SimulationTarget(
            target_id="t1", name="UFO", alliance="unknown",
            asset_type="spaceship", position=(0.0, 0.0),
            speed=1.0, battery=1.0, waypoints=[(100.0, 0.0)],
        )
        t.tick(100.0)
        # fallback drain = 0.001 * 100 = 0.1
        assert abs(t.battery - 0.9) < 0.001

    def test_all_ambient_types_in_drain_rates(self) -> None:
        """All asset types used by AmbientSpawner must have entries in _DRAIN_RATES."""
        ambient_types = {"person", "vehicle", "animal"}
        for atype in ambient_types:
            assert atype in _DRAIN_RATES, f"{atype} missing from _DRAIN_RATES"


# -- to_dict completeness (edge case #10) ----------------------------------


class TestToDictCompleteness:
    def test_all_required_fields_present(self) -> None:
        """to_dict() must include all fields needed by the frontend."""
        t = SimulationTarget(
            target_id="t1", name="Test", alliance="neutral",
            asset_type="person", position=(1.5, -2.3),
            heading=45.0, speed=1.2, battery=0.8,
            status="active",
        )
        d = t.to_dict()
        required = {
            "target_id", "name", "alliance", "asset_type",
            "position", "heading", "speed", "battery",
            "status",
        }
        assert required.issubset(d.keys()), f"Missing: {required - d.keys()}"

    def test_position_format_is_dict(self) -> None:
        """Position should be serialized as {x, y} dict, not tuple."""
        t = SimulationTarget(
            target_id="t1", name="Test", alliance="neutral",
            asset_type="person", position=(3.0, -4.0),
        )
        d = t.to_dict()
        assert isinstance(d["position"], dict)
        assert "x" in d["position"] and "y" in d["position"]
        assert d["position"]["x"] == 3.0
        assert d["position"]["y"] == -4.0

    def test_battery_rounded(self) -> None:
        """Battery should be rounded to 4 decimal places."""
        t = SimulationTarget(
            target_id="t1", name="Test", alliance="neutral",
            asset_type="drone", position=(0.0, 0.0),
            battery=0.123456789,
        )
        d = t.to_dict()
        assert d["battery"] == round(0.123456789, 4)

    def test_default_values_in_dict(self) -> None:
        """Verify to_dict with all defaults."""
        t = SimulationTarget(
            target_id="t1", name="Min", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
        )
        d = t.to_dict()
        assert d["heading"] == 0.0
        assert d["speed"] == 1.0
        assert d["battery"] == 1.0
        assert d["status"] == "active"


# -- Heading calculation (target.py tick) ----------------------------------


class TestHeadingCalculation:
    def test_heading_north(self) -> None:
        """Moving north (+y) should give heading ~0 degrees."""
        t = SimulationTarget(
            target_id="t1", name="N", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=1.0, waypoints=[(0.0, 10.0)],
        )
        t.tick(1.0)
        assert abs(t.heading) < 1.0 or abs(t.heading - 360) < 1.0

    def test_heading_east(self) -> None:
        """Moving east (+x) should give heading ~90 degrees."""
        t = SimulationTarget(
            target_id="t1", name="E", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=1.0, waypoints=[(10.0, 0.0)],
        )
        t.tick(1.0)
        assert abs(t.heading - 90.0) < 1.0

    def test_heading_south(self) -> None:
        """Moving south (-y) should give heading ~180 degrees."""
        t = SimulationTarget(
            target_id="t1", name="S", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=1.0, waypoints=[(0.0, -10.0)],
        )
        t.tick(1.0)
        assert abs(t.heading - 180.0) < 1.0 or abs(t.heading + 180.0) < 1.0

    def test_heading_west(self) -> None:
        """Moving west (-x) should give heading ~-90 degrees."""
        t = SimulationTarget(
            target_id="t1", name="W", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=1.0, waypoints=[(-10.0, 0.0)],
        )
        t.tick(1.0)
        assert abs(t.heading - (-90.0)) < 1.0


# -- Patrol looping for non-neutral targets --------------------------------


class TestPatrolLooping:
    def test_friendly_loops_back_to_start(self) -> None:
        """Friendly multi-waypoint target with loop_waypoints should loop index back to 0."""
        t = SimulationTarget(
            target_id="f1", name="Patrol", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=100.0, waypoints=[(0.5, 0.0), (0.5, 0.5)],
            loop_waypoints=True,
        )
        # Fast enough to reach all waypoints quickly
        for _ in range(50):
            t.tick(0.1)
        # Should still be active (looping), not arrived or despawned
        assert t.status == "active"
        # _waypoint_index should have looped (could be 0 or any valid index)
        assert 0 <= t._waypoint_index < len(t.waypoints)

    def test_friendly_one_shot_arrives(self) -> None:
        """Friendly multi-waypoint dispatch without loop should arrive."""
        t = SimulationTarget(
            target_id="f1", name="Dispatch", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=100.0, waypoints=[(0.5, 0.0), (0.5, 0.5)],
            loop_waypoints=False,
        )
        for _ in range(50):
            t.tick(0.1)
        assert t.status == "arrived"

    def test_hostile_multi_waypoint_escapes(self) -> None:
        """Hostile multi-waypoint target should escape at path end, not loop."""
        t = SimulationTarget(
            target_id="h1", name="Intruder", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
            speed=100.0, waypoints=[(0.5, 0.0), (0.5, 0.5), (0.0, 0.5)],
        )
        for _ in range(100):
            t.tick(0.1)
        assert t.status == "escaped"


# -- _clamp edge cases -----------------------------------------------------


class TestClamp:
    def test_clamp_above_max(self, spawner: AmbientSpawner) -> None:
        assert spawner._clamp(100.0) == _MAP_MAX

    def test_clamp_below_min(self, spawner: AmbientSpawner) -> None:
        assert spawner._clamp(-100.0) == _MAP_MIN

    def test_clamp_within_bounds(self, spawner: AmbientSpawner) -> None:
        assert spawner._clamp(0.0) == 0.0

    def test_clamp_at_boundaries(self, spawner: AmbientSpawner) -> None:
        assert spawner._clamp(_MAP_MAX) == _MAP_MAX
        assert spawner._clamp(_MAP_MIN) == _MAP_MIN


# -- _spawn_random boundary roll values ------------------------------------


class TestSpawnRandomBoundaries:
    """Test exact boundary values of the roll thresholds."""

    def test_roll_exactly_0_gives_neighbor(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("random.random", lambda: 0.0)
        spawner._spawn_random()
        assert engine.targets[0].speed == 1.2

    def test_roll_exactly_0_35_gives_car(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """roll=0.35 is NOT < 0.35, so falls through to car check (< 0.55)."""
        monkeypatch.setattr("random.random", lambda: 0.35)
        spawner._spawn_random()
        assert engine.targets[0].asset_type == "vehicle"

    def test_roll_exactly_0_55_gives_dog(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """roll=0.55 is NOT < 0.55, so falls through to dog check (< 0.70)."""
        monkeypatch.setattr("random.random", lambda: 0.55)
        spawner._spawn_random()
        assert engine.targets[0].speed == 2.0  # dog speed

    def test_roll_exactly_0_70_gives_cat(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """roll=0.70 is NOT < 0.70, so falls through to cat check (< 0.80)."""
        monkeypatch.setattr("random.random", lambda: 0.70)
        spawner._spawn_random()
        assert engine.targets[0].speed == 1.5  # cat speed

    def test_roll_exactly_0_80_gives_delivery(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """roll=0.80 is NOT < 0.80, so falls through to else (delivery)."""
        monkeypatch.setattr("random.random", lambda: 0.80)
        spawner._spawn_random()
        assert engine.targets[0].speed == 1.0  # delivery speed

    def test_roll_0_9999_gives_delivery(
        self, spawner: AmbientSpawner, engine: MockEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("random.random", lambda: 0.9999)
        spawner._spawn_random()
        assert engine.targets[0].speed == 1.0


# -- Multi-waypoint index advancement -------------------------------------


class TestWaypointIndexAdvancement:
    def test_advances_through_all_waypoints(self) -> None:
        """Target should visit each waypoint in order."""
        t = SimulationTarget(
            target_id="t1", name="Walker", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=100.0, waypoints=[(0.1, 0.0), (0.2, 0.0), (0.3, 0.0)],
        )
        # Tick until it reaches waypoint 0 (dist < 1.0 immediately since 0.1 < 1.0)
        t.tick(0.01)
        assert t._waypoint_index == 1
        t.tick(0.01)
        assert t._waypoint_index == 2
        t.tick(0.01)
        assert t.status == "despawned"

    def test_waypoint_index_starts_at_zero(self) -> None:
        t = SimulationTarget(
            target_id="t1", name="New", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            waypoints=[(10.0, 0.0)],
        )
        assert t._waypoint_index == 0


# -- Delivery door-pause edge case -----------------------------------------


class TestDeliveryDoorPause:
    def test_delivery_pauses_at_door(self) -> None:
        """Delivery target visits the door waypoint, then the duplicate door again."""
        # Simulate a delivery target with known positions
        t = SimulationTarget(
            target_id="d1", name="Pizza", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            speed=100.0,
            waypoints=[(0.1, 0.0), (0.1, 0.0), (0.2, 0.0)],
        )
        # First tick: dist to wp0 is 0.1 < 1.0, advance to wp1
        t.tick(0.01)
        assert t._waypoint_index == 1
        # Second tick: wp1 is same as wp0, dist still < 1.0, advance to wp2
        t.tick(0.01)
        assert t._waypoint_index == 2
        # Third tick: dist to wp2 < 1.0, last waypoint -> despawn
        t.tick(0.01)
        assert t.status == "despawned"


# -- Spawned targets have valid UUIDs -------------------------------------


class TestSpawnedTargetIds:
    def test_neighbor_has_uuid(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_neighbor()
        tid = engine.targets[0].target_id
        # Should be a valid UUID-like string (36 chars with hyphens)
        assert len(tid) == 36
        assert tid.count("-") == 4

    def test_all_spawn_types_unique_ids(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        spawner._spawn_neighbor()
        spawner._spawn_car()
        spawner._spawn_dog()
        spawner._spawn_cat()
        spawner._spawn_delivery()
        ids = [t.target_id for t in engine.targets]
        assert len(set(ids)) == 5

    def test_names_across_types_tracked(
        self, spawner: AmbientSpawner, engine: MockEngine
    ) -> None:
        """Names from different spawn types share the same _used_names set."""
        spawner._spawn_neighbor()
        spawner._spawn_car()
        n_name = engine.targets[0].name
        c_name = engine.targets[1].name
        assert n_name in spawner._used_names
        assert c_name in spawner._used_names


# -- Negative dt edge case -------------------------------------------------


class TestNegativeDt:
    def test_negative_dt_does_not_crash(self) -> None:
        """Negative dt should not crash; battery stays non-negative."""
        t = SimulationTarget(
            target_id="t1", name="Backwards", alliance="neutral",
            asset_type="drone", position=(0.0, 0.0),
            speed=1.0, battery=0.5, waypoints=[(10.0, 0.0)],
        )
        # Negative dt: drain becomes negative, but battery won't exceed 1.0
        t.tick(-1.0)
        assert t.battery >= 0.0

    def test_zero_dt_no_change(self) -> None:
        """dt=0 should leave target unchanged."""
        t = SimulationTarget(
            target_id="t1", name="Still", alliance="neutral",
            asset_type="person", position=(5.0, 5.0),
            speed=1.0, battery=1.0, waypoints=[(10.0, 0.0)],
        )
        t.tick(0.0)
        assert t.position == (5.0, 5.0)
        assert t.battery == 1.0


# ============================================================================
# STREET GRID TESTS
# ============================================================================


class TestStreetGrid:
    """Verify that the street grid path functions produce believable paths."""

    def test_street_path_returns_two_waypoints(self) -> None:
        from engine.simulation.ambient import _street_path
        path = _street_path((-30.0, 0.0), (30.0, 0.0))
        assert len(path) == 2

    def test_street_path_corner_near_street(self) -> None:
        """The intermediate corner should be near a street intersection."""
        from engine.simulation.ambient import _street_path, _STREETS_NS_X, _STREET_JITTER
        path = _street_path((-30.0, 5.0), (30.0, -5.0))
        corner_x, corner_y = path[0]
        # Corner x should be within jitter of a NS street
        min_dist = min(abs(corner_x - sx) for sx in _STREETS_NS_X)
        assert min_dist <= _STREET_JITTER + 0.01

    def test_snap_to_nearest_street(self) -> None:
        from engine.simulation.ambient import _snap_to_nearest_street, _STREETS_NS_X, _STREETS_EW_Y, _STREET_JITTER
        # Point at (5, 5) is closer to NS street x=10 (dist=5) and EW street y=10 (dist=5)
        # Either snap direction is valid
        for _ in range(20):
            sx, sy = _snap_to_nearest_street(5.0, 5.0)
            ns_match = any(abs(sx - s) <= _STREET_JITTER + 0.01 for s in _STREETS_NS_X)
            ew_match = any(abs(sy - s) <= _STREET_JITTER + 0.01 for s in _STREETS_EW_Y)
            assert ns_match or ew_match

    def test_sidewalk_path_follows_streets(self, spawner: AmbientSpawner) -> None:
        """Sidewalk paths should now produce L-shaped street-following paths."""
        start = (-30.0, 0.0)
        path = spawner._sidewalk_path(start)
        assert len(path) == 2  # corner + destination
        # The corner should be near a street line
        from engine.simulation.ambient import _STREETS_NS_X, _STREET_JITTER
        corner_x = path[0][0]
        min_dist = min(abs(corner_x - sx) for sx in _STREETS_NS_X)
        assert min_dist <= _STREET_JITTER + 0.01


# ============================================================================
# TIME-OF-DAY TESTS
# ============================================================================


class TestTimeOfDay:
    """Verify time-of-day activity scaling."""

    def test_hour_activity_returns_tuple(self) -> None:
        from engine.simulation.ambient import _hour_activity
        result = _hour_activity()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_hour_activity_values_positive(self) -> None:
        from engine.simulation.ambient import _hour_activity
        ambient, hostile = _hour_activity()
        assert ambient > 0
        assert hostile > 0

    def test_daytime_high_ambient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """During daytime (10am), ambient should be 1.0 and hostile low."""
        from engine.simulation import ambient as amb_mod
        from datetime import datetime as _dt

        class FakeDatetime(_dt):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 2, 16, 10, 0, 0)

        monkeypatch.setattr(amb_mod, "datetime", FakeDatetime)
        ambient, hostile = amb_mod._hour_activity()
        assert ambient == 1.0
        assert hostile == 0.3

    def test_night_high_hostile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """At 3am, ambient should be minimal and hostile at peak."""
        from engine.simulation import ambient as amb_mod
        from datetime import datetime as _dt

        class FakeDatetime(_dt):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 2, 16, 3, 0, 0)

        monkeypatch.setattr(amb_mod, "datetime", FakeDatetime)
        ambient, hostile = amb_mod._hour_activity()
        assert ambient == 0.1
        assert hostile == 1.0

    def test_late_evening_moderate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """At 11pm, ambient should be low and hostile high."""
        from engine.simulation import ambient as amb_mod
        from datetime import datetime as _dt

        class FakeDatetime(_dt):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 2, 16, 23, 0, 0)

        monkeypatch.setattr(amb_mod, "datetime", FakeDatetime)
        ambient, hostile = amb_mod._hour_activity()
        assert ambient == 0.3
        assert hostile == 0.8
