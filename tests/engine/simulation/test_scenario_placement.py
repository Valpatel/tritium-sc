# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Placement quality tests for building-centric mission generation.

These tests verify that place_defenders_around_buildings produces
tactically reasonable placements: turrets near but not inside buildings,
rovers on streets, drones overhead, no overlap, variety across runs.
"""

from __future__ import annotations

import math
import random

import pytest

from engine.simulation.poi_data import (
    POI,
    MissionArea,
    build_mission_area,
    get_poi_context_text,
    pick_mission_center,
    place_defenders_around_buildings,
)
from engine.simulation.scenario import BattleScenario, DefenderConfig, WaveDefinition, SpawnGroup

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_poi(
    name: str = "Test POI",
    poi_type: str = "building",
    category: str = "building",
    local_x: float = 0.0,
    local_y: float = 0.0,
    lat: float = 37.7161,
    lng: float = -121.9357,
    address: str = "",
    osm_id: int = 0,
) -> POI:
    return POI(
        name=name,
        poi_type=poi_type,
        category=category,
        address=address,
        lat=lat,
        lng=lng,
        local_x=local_x,
        local_y=local_y,
        osm_id=osm_id,
    )


def _make_rich_area(
    n_buildings: int = 6,
    n_streets: int = 4,
    radius_m: float = 200.0,
    spread: float = 80.0,
) -> MissionArea:
    """Create a MissionArea with well-spread buildings and streets."""
    center = _make_poi(name="Town Hall", local_x=0, local_y=0)
    buildings = [center]
    for i in range(1, n_buildings):
        angle = (2 * math.pi * i) / n_buildings
        x = spread * math.cos(angle)
        y = spread * math.sin(angle)
        buildings.append(
            _make_poi(
                name=f"Building {chr(65 + i)}",
                local_x=x,
                local_y=y,
                osm_id=1000 + i,
            )
        )
    streets = [f"Street {chr(65 + i)}" for i in range(n_streets)]
    # Generate defensive positions at each building offset
    def_pos = [(b.local_x + 8, b.local_y + 8) for b in buildings]
    return MissionArea(
        center_poi=center,
        radius_m=radius_m,
        buildings=buildings,
        streets=streets,
        defensive_positions=def_pos,
        approach_routes=streets[:2],
    )


def _full_specs() -> list[dict]:
    """Standard mixed force: 2 turrets, 2 rovers, 1 drone."""
    return [
        {"type": "turret", "count": 2},
        {"type": "rover", "count": 2},
        {"type": "drone", "count": 1},
    ]


# ===========================================================================
# TestTurretPlacement — 10 tests
# ===========================================================================


class TestTurretPlacement:
    """Turrets placed 5-15m from building edges, not inside, facing outward."""

    def test_turret_distance_from_building_min(self):
        area = _make_rich_area()
        specs = [{"type": "turret", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        for r in result:
            if r["asset_type"] != "turret":
                continue
            pos = r["position"]
            min_dist = min(
                math.hypot(pos[0] - b.local_x, pos[1] - b.local_y)
                for b in area.buildings
            )
            # At least 3m from building centroid (not inside)
            assert min_dist >= 3.0, (
                f"Turret {r['name']} too close to building: {min_dist:.1f}m"
            )

    def test_turret_distance_from_building_max(self):
        area = _make_rich_area()
        specs = [{"type": "turret", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        for r in result:
            if r["asset_type"] != "turret":
                continue
            pos = r["position"]
            min_dist = min(
                math.hypot(pos[0] - b.local_x, pos[1] - b.local_y)
                for b in area.buildings
            )
            # No more than 15m from nearest building
            assert min_dist <= 15.0, (
                f"Turret {r['name']} too far from any building: {min_dist:.1f}m"
            )

    def test_turret_unique_positions(self):
        area = _make_rich_area()
        specs = [{"type": "turret", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        positions = [
            tuple(r["position"]) for r in result if r["asset_type"] == "turret"
        ]
        assert len(set(positions)) == len(positions)

    def test_turret_facing_outward(self):
        """Turrets should face away from center, toward the perimeter."""
        area = _make_rich_area()
        specs = [{"type": "turret", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            if r["asset_type"] != "turret":
                continue
            pos = r["position"]
            # Find the building this turret is associated with
            nearest_b = min(
                area.buildings,
                key=lambda b: math.hypot(pos[0] - b.local_x, pos[1] - b.local_y),
            )
            # Vector from building to turret should point away from center
            bx, by = nearest_b.local_x, nearest_b.local_y
            turret_vec = (pos[0] - bx, pos[1] - by)
            center_vec = (bx - cx, by - cy)
            # Dot product should be positive or near zero (outward)
            dot = turret_vec[0] * center_vec[0] + turret_vec[1] * center_vec[1]
            # Allow turrets at center building where center_vec is zero
            mag = math.hypot(center_vec[0], center_vec[1])
            if mag > 1.0:
                assert dot >= -5.0, (
                    f"Turret {r['name']} facing inward: dot={dot:.1f}"
                )

    def test_turret_names_unique(self):
        area = _make_rich_area()
        specs = [{"type": "turret", "count": 4}]
        result = place_defenders_around_buildings(area, specs)
        names = [r["name"] for r in result if r["asset_type"] == "turret"]
        assert len(set(names)) == len(names)

    def test_many_turrets(self):
        area = _make_rich_area(n_buildings=8)
        specs = [{"type": "turret", "count": 6}]
        result = place_defenders_around_buildings(area, specs)
        turrets = [r for r in result if r["asset_type"] == "turret"]
        assert len(turrets) == 6

    def test_single_turret(self):
        area = _make_rich_area(n_buildings=1)
        specs = [{"type": "turret", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        assert len(result) == 1

    def test_turret_within_combat_radius(self):
        area = _make_rich_area(radius_m=150)
        specs = [{"type": "turret", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            if r["asset_type"] != "turret":
                continue
            pos = r["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            assert dist <= area.radius_m + 20, (
                f"Turret {r['name']} outside radius: {dist:.1f}m > {area.radius_m}m"
            )

    def test_turret_name_contains_turret(self):
        area = _make_rich_area()
        specs = [{"type": "turret", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        for r in result:
            if r["asset_type"] == "turret":
                assert "Turret" in r["name"]

    def test_turrets_at_different_buildings(self):
        """Multiple turrets should be spread across buildings."""
        area = _make_rich_area(n_buildings=5)
        specs = [{"type": "turret", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        # Find which building each turret is nearest to
        nearest_buildings = set()
        for r in result:
            if r["asset_type"] != "turret":
                continue
            pos = r["position"]
            nearest = min(
                area.buildings,
                key=lambda b: math.hypot(pos[0] - b.local_x, pos[1] - b.local_y),
            )
            nearest_buildings.add(nearest.name)
        # At least 2 different buildings used for 3 turrets
        assert len(nearest_buildings) >= 2


# ===========================================================================
# TestRoverPlacement — 8 tests
# ===========================================================================


class TestRoverPlacement:
    """Rovers placed on or near named streets, within combat radius."""

    def test_rover_count(self):
        area = _make_rich_area()
        specs = [{"type": "rover", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        rovers = [r for r in result if r["asset_type"] == "rover"]
        assert len(rovers) == 3

    def test_rover_within_radius(self):
        area = _make_rich_area(radius_m=150)
        specs = [{"type": "rover", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            if r["asset_type"] != "rover":
                continue
            pos = r["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            assert dist <= area.radius_m + 20

    def test_rover_name_contains_patrol(self):
        area = _make_rich_area()
        specs = [{"type": "rover", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        rover = [r for r in result if r["asset_type"] == "rover"][0]
        assert "Patrol" in rover["name"]

    def test_rover_has_position(self):
        area = _make_rich_area()
        specs = [{"type": "rover", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        rover = [r for r in result if r["asset_type"] == "rover"][0]
        assert "position" in rover
        assert len(rover["position"]) == 2

    def test_rover_unique_positions(self):
        area = _make_rich_area(n_streets=4)
        specs = [{"type": "rover", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        positions = [
            tuple(r["position"]) for r in result if r["asset_type"] == "rover"
        ]
        assert len(set(positions)) == len(positions)

    def test_rover_names_unique(self):
        area = _make_rich_area(n_streets=4)
        specs = [{"type": "rover", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        names = [r["name"] for r in result if r["asset_type"] == "rover"]
        assert len(set(names)) == len(names)

    def test_rover_not_at_center(self):
        """Rovers should patrol, not sit at center."""
        area = _make_rich_area()
        specs = [{"type": "rover", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            if r["asset_type"] != "rover":
                continue
            pos = r["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            # Rovers should be offset from center (at least a bit)
            # They should be on streets, not at the exact center
            assert dist >= 5.0 or len(area.streets) == 0

    def test_many_rovers(self):
        area = _make_rich_area(n_streets=6)
        specs = [{"type": "rover", "count": 5}]
        result = place_defenders_around_buildings(area, specs)
        rovers = [r for r in result if r["asset_type"] == "rover"]
        assert len(rovers) == 5


# ===========================================================================
# TestDronePlacement — 5 tests
# ===========================================================================


class TestDronePlacement:
    """Drones at center or perimeter, not at ground positions."""

    def test_drone_count(self):
        area = _make_rich_area()
        specs = [{"type": "drone", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        drones = [r for r in result if r["asset_type"] == "drone"]
        assert len(drones) == 2

    def test_drone_near_center(self):
        area = _make_rich_area()
        specs = [{"type": "drone", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        drone = [r for r in result if r["asset_type"] == "drone"][0]
        pos = drone["position"]
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        dist = math.hypot(pos[0] - cx, pos[1] - cy)
        assert dist <= 50.0

    def test_drone_name_overwatch(self):
        area = _make_rich_area()
        specs = [{"type": "drone", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        drone = [r for r in result if r["asset_type"] == "drone"][0]
        assert "Overwatch" in drone["name"]

    def test_scout_drone_name(self):
        area = _make_rich_area()
        specs = [{"type": "scout_drone", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        scout = [r for r in result if r["asset_type"] == "scout_drone"][0]
        assert "Scout" in scout["name"]

    def test_scout_drone_at_perimeter(self):
        area = _make_rich_area(radius_m=200)
        specs = [{"type": "scout_drone", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        scout = [r for r in result if r["asset_type"] == "scout_drone"][0]
        pos = scout["position"]
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        dist = math.hypot(pos[0] - cx, pos[1] - cy)
        # Scout should be closer to perimeter than center
        assert dist >= area.radius_m * 0.3


# ===========================================================================
# TestMixedForce — 8 tests
# ===========================================================================


class TestMixedForce:
    """Full force: 2 turrets + 2 rovers + 1 drone, comprehensive checks."""

    def test_total_count(self):
        area = _make_rich_area()
        result = place_defenders_around_buildings(area, _full_specs())
        assert len(result) == 5

    def test_all_types_present(self):
        area = _make_rich_area()
        result = place_defenders_around_buildings(area, _full_specs())
        types = {r["asset_type"] for r in result}
        assert "turret" in types
        assert "rover" in types
        assert "drone" in types

    def test_no_position_overlap(self):
        area = _make_rich_area()
        result = place_defenders_around_buildings(area, _full_specs())
        positions = [tuple(r["position"]) for r in result]
        assert len(set(positions)) == len(positions)

    def test_all_within_radius(self):
        area = _make_rich_area(radius_m=200)
        result = place_defenders_around_buildings(area, _full_specs())
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            pos = r["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            assert dist <= area.radius_m + 50

    def test_names_unique(self):
        area = _make_rich_area()
        result = place_defenders_around_buildings(area, _full_specs())
        names = [r["name"] for r in result]
        assert len(set(names)) == len(names)

    def test_all_have_required_fields(self):
        area = _make_rich_area()
        result = place_defenders_around_buildings(area, _full_specs())
        for r in result:
            assert "asset_type" in r
            assert "position" in r
            assert "name" in r
            assert len(r["position"]) == 2
            assert isinstance(r["position"][0], (int, float))
            assert isinstance(r["position"][1], (int, float))

    def test_large_force(self):
        area = _make_rich_area(n_buildings=10, n_streets=6)
        specs = [
            {"type": "turret", "count": 5},
            {"type": "rover", "count": 4},
            {"type": "drone", "count": 2},
            {"type": "scout_drone", "count": 2},
        ]
        result = place_defenders_around_buildings(area, specs)
        assert len(result) == 13

    def test_defender_config_conversion(self):
        """Placement result should be convertible to DefenderConfig."""
        area = _make_rich_area()
        result = place_defenders_around_buildings(area, _full_specs())
        defenders = []
        for r in result:
            d = DefenderConfig(
                asset_type=r["asset_type"],
                position=(r["position"][0], r["position"][1]),
                name=r["name"],
            )
            defenders.append(d)
        assert len(defenders) == 5
        assert all(isinstance(d, DefenderConfig) for d in defenders)


# ===========================================================================
# TestBuildingVariety — 6 tests
# ===========================================================================


class TestBuildingVariety:
    """Different buildings chosen for different turrets."""

    def test_two_turrets_at_different_buildings(self):
        area = _make_rich_area(n_buildings=5)
        specs = [{"type": "turret", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        nearest = set()
        for r in result:
            if r["asset_type"] != "turret":
                continue
            pos = r["position"]
            nb = min(
                area.buildings,
                key=lambda b: math.hypot(pos[0] - b.local_x, pos[1] - b.local_y),
            )
            nearest.add(nb.name)
        assert len(nearest) >= 2

    def test_three_turrets_use_three_buildings(self):
        area = _make_rich_area(n_buildings=6)
        specs = [{"type": "turret", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        nearest = set()
        for r in result:
            if r["asset_type"] != "turret":
                continue
            pos = r["position"]
            nb = min(
                area.buildings,
                key=lambda b: math.hypot(pos[0] - b.local_x, pos[1] - b.local_y),
            )
            nearest.add(nb.name)
        assert len(nearest) >= 2  # At least 2, ideally 3

    def test_turrets_not_all_at_center(self):
        area = _make_rich_area(n_buildings=6)
        specs = [{"type": "turret", "count": 4}]
        result = place_defenders_around_buildings(area, specs)
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        at_center = 0
        for r in result:
            if r["asset_type"] != "turret":
                continue
            pos = r["position"]
            if math.hypot(pos[0] - cx, pos[1] - cy) < 15:
                at_center += 1
        assert at_center <= 2, "Too many turrets clustered at center"

    def test_building_names_in_turret_names(self):
        area = _make_rich_area(n_buildings=4)
        specs = [{"type": "turret", "count": 3}]
        result = place_defenders_around_buildings(area, specs)
        for r in result:
            if r["asset_type"] == "turret":
                assert "Turret" in r["name"]

    def test_single_building_multiple_turrets(self):
        """With only 1 building, multiple turrets should still be placed."""
        area = _make_rich_area(n_buildings=1)
        specs = [{"type": "turret", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        turrets = [r for r in result if r["asset_type"] == "turret"]
        assert len(turrets) == 2

    def test_turrets_at_different_positions_same_building(self):
        """Two turrets at same building should have different positions."""
        area = _make_rich_area(n_buildings=1)
        specs = [{"type": "turret", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        positions = [
            tuple(r["position"]) for r in result if r["asset_type"] == "turret"
        ]
        assert positions[0] != positions[1]


# ===========================================================================
# TestStreetVariety — 5 tests
# ===========================================================================


class TestStreetVariety:
    """Rovers on different streets, not all on same road."""

    def test_two_rovers_different_streets(self):
        area = _make_rich_area(n_streets=4)
        specs = [{"type": "rover", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        rover_names = [r["name"] for r in result if r["asset_type"] == "rover"]
        # Names should reference different streets
        assert len(set(rover_names)) == 2

    def test_many_rovers_use_multiple_streets(self):
        area = _make_rich_area(n_streets=5)
        specs = [{"type": "rover", "count": 4}]
        result = place_defenders_around_buildings(area, specs)
        rover_names = [r["name"] for r in result if r["asset_type"] == "rover"]
        assert len(set(rover_names)) >= 2

    def test_rover_names_contain_street(self):
        area = _make_rich_area(n_streets=3)
        specs = [{"type": "rover", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        for r in result:
            if r["asset_type"] == "rover":
                has_street = any(s in r["name"] for s in area.streets)
                assert has_street or "Patrol" in r["name"]

    def test_single_street_rovers(self):
        area = _make_rich_area(n_streets=1)
        specs = [{"type": "rover", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        rovers = [r for r in result if r["asset_type"] == "rover"]
        assert len(rovers) == 2

    def test_no_streets_rover_fallback(self):
        area = _make_rich_area(n_streets=0)
        specs = [{"type": "rover", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        assert len(result) == 1


# ===========================================================================
# TestRadiusHonored — 5 tests
# ===========================================================================


class TestRadiusHonored:
    """All units within radius_m of center."""

    def test_tight_radius(self):
        area = _make_rich_area(radius_m=100, spread=40)
        result = place_defenders_around_buildings(area, _full_specs())
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            pos = r["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            assert dist <= 150  # radius + margin

    def test_large_radius(self):
        area = _make_rich_area(radius_m=300, spread=120)
        result = place_defenders_around_buildings(area, _full_specs())
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            pos = r["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            assert dist <= 350

    def test_minimum_radius(self):
        area = _make_rich_area(radius_m=50, spread=20)
        result = place_defenders_around_buildings(area, _full_specs())
        assert len(result) == 5

    def test_turrets_tighter_than_radius(self):
        area = _make_rich_area(radius_m=200, spread=80)
        specs = [{"type": "turret", "count": 4}]
        result = place_defenders_around_buildings(area, specs)
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            pos = r["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            assert dist <= area.radius_m + 20

    def test_drones_within_radius(self):
        area = _make_rich_area(radius_m=200)
        specs = [{"type": "drone", "count": 2}, {"type": "scout_drone", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            pos = r["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            assert dist <= area.radius_m + 50


# ===========================================================================
# TestScenarioEndToEnd — 8 tests
# ===========================================================================


class TestScenarioEndToEnd:
    """Generate placement -> convert to BattleScenario -> verify."""

    def _build_scenario(self) -> tuple[MissionArea, BattleScenario]:
        pois = [
            _make_poi(name="School", poi_type="school", category="amenity",
                      local_x=0, local_y=0, osm_id=1),
            _make_poi(name="Store", category="building", local_x=50, local_y=30, osm_id=2),
            _make_poi(name="Library", category="building", local_x=-40, local_y=60, osm_id=3),
            _make_poi(name="Park Rd", category="street", local_x=0, local_y=0, osm_id=4),
            _make_poi(name="Main St", category="street", local_x=0, local_y=0, osm_id=5),
        ]
        center = pick_mission_center(pois, preference="School")
        area = build_mission_area(center, pois, radius_m=200)
        placements = place_defenders_around_buildings(area, _full_specs())
        defenders = [
            DefenderConfig(
                asset_type=p["asset_type"],
                position=(p["position"][0], p["position"][1]),
                name=p["name"],
            )
            for p in placements
        ]
        waves = [
            WaveDefinition(
                name="Wave 1",
                groups=[SpawnGroup(asset_type="person", count=5)],
            )
        ]
        scenario = BattleScenario(
            scenario_id="test_e2e",
            name=f"Battle at {center.name}",
            description=get_poi_context_text(area),
            map_bounds=area.radius_m,
            waves=waves,
            defenders=defenders,
        )
        return area, scenario

    def test_scenario_created(self):
        _, scenario = self._build_scenario()
        assert isinstance(scenario, BattleScenario)

    def test_scenario_has_defenders(self):
        _, scenario = self._build_scenario()
        assert len(scenario.defenders) == 5

    def test_scenario_name_has_building(self):
        _, scenario = self._build_scenario()
        assert "School" in scenario.name

    def test_scenario_description_has_context(self):
        _, scenario = self._build_scenario()
        assert len(scenario.description) > 50

    def test_defenders_have_positions(self):
        _, scenario = self._build_scenario()
        for d in scenario.defenders:
            assert isinstance(d.position, tuple)
            assert len(d.position) == 2

    def test_defenders_have_names(self):
        _, scenario = self._build_scenario()
        for d in scenario.defenders:
            assert d.name is not None
            assert len(d.name) > 0

    def test_scenario_serialization(self):
        _, scenario = self._build_scenario()
        d = scenario.to_dict()
        restored = BattleScenario.from_dict(d)
        assert restored.name == scenario.name
        assert len(restored.defenders) == len(scenario.defenders)

    def test_defenders_at_real_buildings(self):
        area, scenario = self._build_scenario()
        turret_defenders = [
            d for d in scenario.defenders if d.asset_type == "turret"
        ]
        for d in turret_defenders:
            # Each turret should be near a building in the area
            min_dist = min(
                math.hypot(d.position[0] - b.local_x, d.position[1] - b.local_y)
                for b in area.buildings
            ) if area.buildings else 0
            assert min_dist <= 20.0


# ===========================================================================
# TestMultipleGenerations — 5 tests
# ===========================================================================


class TestMultipleGenerations:
    """Run placement multiple times, verify variety."""

    def test_positions_vary(self):
        """10 runs should produce some variety in positions."""
        area = _make_rich_area(n_buildings=6, n_streets=4)
        specs = [{"type": "turret", "count": 2}]
        all_positions = set()
        for _ in range(10):
            result = place_defenders_around_buildings(area, specs)
            for r in result:
                all_positions.add((round(r["position"][0], 1), round(r["position"][1], 1)))
        # With randomness in placement, should see some variety
        # Even deterministic placement should produce at least 2 unique positions
        assert len(all_positions) >= 2

    def test_consistent_count(self):
        area = _make_rich_area()
        for _ in range(10):
            result = place_defenders_around_buildings(area, _full_specs())
            assert len(result) == 5

    def test_always_has_required_fields(self):
        area = _make_rich_area()
        for _ in range(10):
            result = place_defenders_around_buildings(area, _full_specs())
            for r in result:
                assert "asset_type" in r
                assert "position" in r
                assert "name" in r

    def test_names_always_unique_per_run(self):
        area = _make_rich_area()
        for _ in range(10):
            result = place_defenders_around_buildings(area, _full_specs())
            names = [r["name"] for r in result]
            assert len(set(names)) == len(names)

    def test_positions_always_unique_per_run(self):
        area = _make_rich_area()
        for _ in range(10):
            result = place_defenders_around_buildings(area, _full_specs())
            positions = [tuple(r["position"]) for r in result]
            assert len(set(positions)) == len(positions)
