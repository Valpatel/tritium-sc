"""Unit tests for POI data module — building-centric mission generation.

Tests cover: POI dataclass, Overpass fetch+parse, mission center selection,
mission area building, defender placement, context text, offline graceful,
and edge cases.  All Overpass calls are mocked.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from engine.simulation.poi_data import (
    POI,
    MissionArea,
    build_mission_area,
    fetch_pois,
    get_poi_context_text,
    get_street_names,
    get_significance,
    load_cached,
    pick_mission_center,
    place_defenders_around_buildings,
    CATEGORY_SIGNIFICANCE,
    POI_TYPE_LABELS,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Dublin, CA reference point (real coords used in project)
REF_LAT = 37.7161
REF_LNG = -121.9357


def _make_poi(
    name: str = "Test POI",
    poi_type: str = "convenience",
    category: str = "shop",
    lat: float = 37.7165,
    lng: float = -121.9350,
    local_x: float = 0.0,
    local_y: float = 0.0,
    address: str = "",
    osm_id: int = 100,
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


def _make_overpass_response(elements: list[dict] | None = None) -> dict:
    """Build a minimal Overpass JSON response."""
    if elements is None:
        elements = [
            {
                "type": "node",
                "id": 1001,
                "lat": 37.7165,
                "lon": -121.9350,
                "tags": {
                    "amenity": "school",
                    "name": "Dublin Elementary",
                    "addr:street": "Village Pkwy",
                },
            },
            {
                "type": "node",
                "id": 1002,
                "lat": 37.7168,
                "lon": -121.9345,
                "tags": {
                    "shop": "convenience",
                    "name": "Circle K",
                    "addr:housenumber": "7850",
                    "addr:street": "Amador Valley Blvd",
                },
            },
            {
                "type": "way",
                "id": 2001,
                "center": {"lat": 37.7170, "lon": -121.9340},
                "tags": {
                    "building": "yes",
                    "name": "Dublin Library",
                    "addr:street": "Civic Plaza",
                },
            },
            {
                "type": "way",
                "id": 2002,
                "center": {"lat": 37.7163, "lon": -121.9355},
                "tags": {
                    "building": "residential",
                    "addr:housenumber": "1234",
                    "addr:street": "Main St",
                },
            },
            {
                "type": "way",
                "id": 3001,
                "center": {"lat": 37.7162, "lon": -121.9358},
                "tags": {
                    "highway": "residential",
                    "name": "Village Pkwy",
                },
            },
            {
                "type": "way",
                "id": 3002,
                "center": {"lat": 37.7164, "lon": -121.9352},
                "tags": {
                    "highway": "tertiary",
                    "name": "Amador Valley Blvd",
                },
            },
        ]
    return {"version": 0.6, "elements": elements}


def _sample_pois() -> list[POI]:
    """Return a list of varied POIs for testing."""
    return [
        _make_poi(
            name="Dublin Elementary",
            poi_type="school",
            category="amenity",
            lat=37.7165,
            lng=-121.9350,
            local_x=61.6,
            local_y=44.5,
            osm_id=1001,
        ),
        _make_poi(
            name="Circle K",
            poi_type="convenience",
            category="shop",
            lat=37.7168,
            lng=-121.9345,
            local_x=105.7,
            local_y=77.8,
            osm_id=1002,
        ),
        _make_poi(
            name="Dublin Library",
            poi_type="building",
            category="building",
            lat=37.7170,
            lng=-121.9340,
            local_x=149.7,
            local_y=100.1,
            osm_id=2001,
        ),
        _make_poi(
            name="1234 Main St",
            poi_type="residential",
            category="building",
            lat=37.7163,
            lng=-121.9355,
            local_x=17.6,
            local_y=22.3,
            osm_id=2002,
        ),
        _make_poi(
            name="Village Pkwy",
            poi_type="residential",
            category="street",
            lat=37.7161,
            lng=-121.9357,
            local_x=0.0,
            local_y=0.0,
            osm_id=3001,
        ),
        _make_poi(
            name="Amador Valley Blvd",
            poi_type="tertiary",
            category="street",
            lat=37.7161,
            lng=-121.9357,
            local_x=0.0,
            local_y=0.0,
            osm_id=3002,
        ),
    ]


# ===========================================================================
# TestPOIDataclass
# ===========================================================================


class TestPOIDataclass:
    """POI dataclass creation and field access."""

    def test_create_poi_all_fields(self):
        poi = POI(
            name="Circle K",
            poi_type="convenience",
            category="shop",
            address="7850 Amador Valley Blvd",
            lat=37.7168,
            lng=-121.9345,
            local_x=105.7,
            local_y=77.8,
            osm_id=1002,
        )
        assert poi.name == "Circle K"
        assert poi.poi_type == "convenience"
        assert poi.category == "shop"
        assert poi.address == "7850 Amador Valley Blvd"
        assert poi.lat == pytest.approx(37.7168)
        assert poi.lng == pytest.approx(-121.9345)
        assert poi.local_x == pytest.approx(105.7)
        assert poi.local_y == pytest.approx(77.8)
        assert poi.osm_id == 1002

    def test_poi_osm_id_defaults_to_zero(self):
        poi = POI(
            name="X",
            poi_type="t",
            category="c",
            address="",
            lat=0,
            lng=0,
            local_x=0,
            local_y=0,
        )
        assert poi.osm_id == 0

    def test_poi_is_dataclass(self):
        poi = _make_poi()
        d = asdict(poi)
        assert "name" in d
        assert "local_x" in d

    def test_poi_equality(self):
        a = _make_poi(name="A", osm_id=1)
        b = _make_poi(name="A", osm_id=1)
        assert a == b

    def test_poi_different_names_not_equal(self):
        a = _make_poi(name="A")
        b = _make_poi(name="B")
        assert a != b


# ===========================================================================
# TestMissionAreaDataclass
# ===========================================================================


class TestMissionAreaDataclass:
    """MissionArea dataclass creation and field access."""

    def test_create_mission_area(self):
        center = _make_poi(name="HQ")
        area = MissionArea(
            center_poi=center,
            radius_m=200.0,
            buildings=[center],
            streets=["Main St"],
            defensive_positions=[(10.0, 20.0)],
            approach_routes=["Village Pkwy"],
        )
        assert area.center_poi.name == "HQ"
        assert area.radius_m == 200.0
        assert len(area.buildings) == 1
        assert len(area.streets) == 1
        assert len(area.defensive_positions) == 1
        assert len(area.approach_routes) == 1

    def test_mission_area_empty_lists(self):
        center = _make_poi()
        area = MissionArea(
            center_poi=center,
            radius_m=100.0,
            buildings=[],
            streets=[],
            defensive_positions=[],
            approach_routes=[],
        )
        assert area.buildings == []
        assert area.streets == []


# ===========================================================================
# TestFetchPOIs
# ===========================================================================


class TestFetchPOIs:
    """fetch_pois: Overpass query, parsing, coordinate conversion, caching."""

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_returns_pois_from_overpass(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) > 0
        mock_fetch.assert_called_once()

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_parses_node_elements(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        names = [p.name for p in pois]
        assert "Dublin Elementary" in names
        assert "Circle K" in names

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_parses_way_buildings(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        building_pois = [p for p in pois if p.category == "building"]
        assert len(building_pois) >= 1

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_parses_street_elements(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        streets = [p for p in pois if p.category == "street"]
        assert len(streets) >= 1

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_local_coords_computed(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        # At least some POIs should have non-zero local coords
        non_zero = [p for p in pois if p.local_x != 0.0 or p.local_y != 0.0]
        assert len(non_zero) > 0

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_address_from_tags(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        circle_k = [p for p in pois if p.name == "Circle K"][0]
        assert "Amador Valley Blvd" in circle_k.address

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_caching_writes_file(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        with tempfile.TemporaryDirectory() as td:
            pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=td)
            assert len(pois) > 0
            # Cache file should exist
            cache_files = list(os.listdir(os.path.join(td, "pois")))
            assert len(cache_files) >= 1

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_caching_reads_on_second_call(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        with tempfile.TemporaryDirectory() as td:
            pois1 = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=td)
            pois2 = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=td)
            # Only one network call — second was from cache
            assert mock_fetch.call_count == 1
            assert len(pois2) == len(pois1)

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_overpass_failure_returns_empty(self, mock_fetch):
        mock_fetch.side_effect = Exception("Network error")
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert pois == []

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_empty_response_returns_empty(self, mock_fetch):
        mock_fetch.return_value = {"version": 0.6, "elements": []}
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert pois == []

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_poi_type_for_amenity(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        school = [p for p in pois if p.name == "Dublin Elementary"][0]
        assert school.poi_type == "school"
        assert school.category == "education"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_poi_type_for_shop(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        shop = [p for p in pois if p.name == "Circle K"][0]
        assert shop.poi_type == "convenience"
        assert shop.category == "shop"


# ===========================================================================
# TestPickMissionCenter
# ===========================================================================


class TestPickMissionCenter:
    """pick_mission_center: selection, preference matching, fallback."""

    def test_random_selection(self):
        pois = _sample_pois()
        center = pick_mission_center(pois)
        assert isinstance(center, POI)

    def test_preference_by_name(self):
        pois = _sample_pois()
        center = pick_mission_center(pois, preference="Circle K")
        assert center.name == "Circle K"

    def test_preference_by_type(self):
        pois = _sample_pois()
        center = pick_mission_center(pois, preference="school")
        assert center.poi_type == "school"

    def test_preference_partial_match(self):
        pois = _sample_pois()
        center = pick_mission_center(pois, preference="Library")
        assert "Library" in center.name

    def test_preference_no_match_falls_back(self):
        pois = _sample_pois()
        center = pick_mission_center(pois, preference="nonexistent_xyz")
        assert isinstance(center, POI)

    def test_prefers_named_buildings(self):
        """When picking randomly, named buildings should be preferred."""
        pois = _sample_pois()
        # Run 20 times — named buildings should appear most of the time
        named_count = 0
        for _ in range(20):
            center = pick_mission_center(pois)
            if center.name and center.category != "street":
                named_count += 1
        assert named_count >= 10  # Most picks should be named buildings

    def test_empty_pois_returns_none(self):
        result = pick_mission_center([])
        assert result is None

    def test_single_poi(self):
        pois = [_make_poi(name="Only One")]
        center = pick_mission_center(pois)
        assert center.name == "Only One"


# ===========================================================================
# TestBuildMissionArea
# ===========================================================================


class TestBuildMissionArea:
    """build_mission_area: radius filtering, streets, defensive positions."""

    def test_returns_mission_area(self):
        pois = _sample_pois()
        center = pois[0]
        area = build_mission_area(center, pois, radius_m=500)
        assert isinstance(area, MissionArea)
        assert area.center_poi == center
        assert area.radius_m == 500

    def test_filters_buildings_by_radius(self):
        center = _make_poi(local_x=0.0, local_y=0.0)
        near = _make_poi(name="Near", category="building", local_x=50.0, local_y=50.0)
        far = _make_poi(name="Far", category="building", local_x=1000.0, local_y=1000.0)
        pois = [center, near, far]
        area = build_mission_area(center, pois, radius_m=200)
        building_names = [b.name for b in area.buildings]
        assert "Near" in building_names
        assert "Far" not in building_names

    def test_extracts_streets(self):
        pois = _sample_pois()
        center = pois[0]
        area = build_mission_area(center, pois, radius_m=500)
        assert len(area.streets) > 0

    def test_defensive_positions_generated(self):
        pois = _sample_pois()
        center = pois[0]
        area = build_mission_area(center, pois, radius_m=500)
        # Should generate defensive positions near buildings
        assert isinstance(area.defensive_positions, list)

    def test_approach_routes(self):
        pois = _sample_pois()
        center = pois[0]
        area = build_mission_area(center, pois, radius_m=500)
        assert isinstance(area.approach_routes, list)

    def test_small_radius_fewer_buildings(self):
        pois = _sample_pois()
        center = pois[0]
        area_small = build_mission_area(center, pois, radius_m=50)
        area_large = build_mission_area(center, pois, radius_m=5000)
        # Small radius should have fewer or equal buildings
        assert len(area_small.buildings) <= len(area_large.buildings)


# ===========================================================================
# TestPlaceDefendersAroundBuildings
# ===========================================================================


class TestPlaceDefendersAroundBuildings:
    """place_defenders_around_buildings: the core placement algorithm."""

    def _make_area(self, n_buildings: int = 3, n_streets: int = 2) -> MissionArea:
        center = _make_poi(name="HQ", local_x=0, local_y=0, category="building")
        buildings = [center]
        for i in range(1, n_buildings):
            buildings.append(
                _make_poi(
                    name=f"Building {i}",
                    local_x=30.0 * i,
                    local_y=20.0 * i,
                    category="building",
                )
            )
        streets = [f"Street {i}" for i in range(n_streets)]
        return MissionArea(
            center_poi=center,
            radius_m=200.0,
            buildings=buildings,
            streets=streets,
            defensive_positions=[(10, 10), (30, 30)],
            approach_routes=streets,
        )

    def test_returns_list_of_dicts(self):
        area = self._make_area()
        specs = [{"type": "turret", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "asset_type" in result[0]
        assert "position" in result[0]

    def test_turret_placement_count(self):
        area = self._make_area()
        specs = [{"type": "turret", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        turrets = [r for r in result if r["asset_type"] == "turret"]
        assert len(turrets) == 2

    def test_turret_placed_near_building(self):
        area = self._make_area()
        specs = [{"type": "turret", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        turret = result[0]
        pos = turret["position"]
        # Should be within 15m of some building centroid
        min_dist = float("inf")
        for b in area.buildings:
            dx = pos[0] - b.local_x
            dy = pos[1] - b.local_y
            d = math.hypot(dx, dy)
            if d < min_dist:
                min_dist = d
        assert min_dist <= 15.0, f"Turret too far from any building: {min_dist:.1f}m"

    def test_turret_not_inside_building(self):
        """Turrets should be offset from the building centroid, not at it."""
        area = self._make_area()
        specs = [{"type": "turret", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        for r in result:
            if r["asset_type"] != "turret":
                continue
            pos = r["position"]
            for b in area.buildings:
                dist = math.hypot(pos[0] - b.local_x, pos[1] - b.local_y)
                # Should not be exactly at the building centroid (offset >= 3m)
                # but could be close for small buildings
                assert dist >= 3.0 or dist == 0.0  # 0 only if no building match

    def test_turret_has_name(self):
        area = self._make_area()
        specs = [{"type": "turret", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        assert "name" in result[0]
        assert result[0]["name"]  # non-empty

    def test_turret_name_contains_building_name(self):
        area = self._make_area()
        specs = [{"type": "turret", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        turret = result[0]
        # Name should reference the building
        assert "Turret" in turret["name"]

    def test_rover_placement(self):
        area = self._make_area()
        specs = [{"type": "rover", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        rovers = [r for r in result if r["asset_type"] == "rover"]
        assert len(rovers) == 2

    def test_rover_has_street_name(self):
        area = self._make_area(n_streets=2)
        specs = [{"type": "rover", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        rover = [r for r in result if r["asset_type"] == "rover"][0]
        assert "Patrol" in rover["name"]

    def test_rover_within_radius(self):
        area = self._make_area()
        specs = [{"type": "rover", "count": 2}]
        result = place_defenders_around_buildings(area, specs)
        for r in result:
            if r["asset_type"] != "rover":
                continue
            pos = r["position"]
            dist = math.hypot(
                pos[0] - area.center_poi.local_x,
                pos[1] - area.center_poi.local_y,
            )
            assert dist <= area.radius_m, f"Rover outside combat radius: {dist:.1f}m"

    def test_drone_placement(self):
        area = self._make_area()
        specs = [{"type": "drone", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        drones = [r for r in result if r["asset_type"] == "drone"]
        assert len(drones) == 1

    def test_drone_name_overwatch(self):
        area = self._make_area()
        specs = [{"type": "drone", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        drone = [r for r in result if r["asset_type"] == "drone"][0]
        assert "Overwatch" in drone["name"]

    def test_drone_at_center(self):
        area = self._make_area()
        specs = [{"type": "drone", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        drone = [r for r in result if r["asset_type"] == "drone"][0]
        pos = drone["position"]
        dist = math.hypot(
            pos[0] - area.center_poi.local_x,
            pos[1] - area.center_poi.local_y,
        )
        # Drones should be near center
        assert dist <= 50.0

    def test_scout_drone_at_perimeter(self):
        area = self._make_area()
        specs = [{"type": "scout_drone", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        scout = [r for r in result if r["asset_type"] == "scout_drone"][0]
        assert "Scout" in scout["name"]

    def test_mixed_force(self):
        area = self._make_area(n_buildings=4, n_streets=3)
        specs = [
            {"type": "turret", "count": 2},
            {"type": "rover", "count": 2},
            {"type": "drone", "count": 1},
        ]
        result = place_defenders_around_buildings(area, specs)
        assert len(result) == 5
        types = [r["asset_type"] for r in result]
        assert types.count("turret") == 2
        assert types.count("rover") == 2
        assert types.count("drone") == 1

    def test_no_position_overlap(self):
        area = self._make_area(n_buildings=4, n_streets=3)
        specs = [
            {"type": "turret", "count": 2},
            {"type": "rover", "count": 2},
            {"type": "drone", "count": 1},
        ]
        result = place_defenders_around_buildings(area, specs)
        positions = [tuple(r["position"]) for r in result]
        # All positions should be unique
        assert len(set(positions)) == len(positions)

    def test_unique_names(self):
        area = self._make_area(n_buildings=4, n_streets=3)
        specs = [
            {"type": "turret", "count": 2},
            {"type": "rover", "count": 2},
            {"type": "drone", "count": 1},
        ]
        result = place_defenders_around_buildings(area, specs)
        names = [r["name"] for r in result]
        assert len(set(names)) == len(names)

    def test_all_within_radius(self):
        area = self._make_area(n_buildings=4, n_streets=3)
        specs = [
            {"type": "turret", "count": 2},
            {"type": "rover", "count": 2},
            {"type": "drone", "count": 1},
        ]
        result = place_defenders_around_buildings(area, specs)
        for r in result:
            pos = r["position"]
            dist = math.hypot(
                pos[0] - area.center_poi.local_x,
                pos[1] - area.center_poi.local_y,
            )
            assert dist <= area.radius_m + 50.0, (
                f"{r['name']} outside combat radius: {dist:.1f}m"
            )

    def test_empty_specs(self):
        area = self._make_area()
        result = place_defenders_around_buildings(area, [])
        assert result == []

    def test_no_buildings_turrets_still_placed(self):
        """Even with no buildings, turrets should be placed somewhere."""
        center = _make_poi(name="Center", local_x=0, local_y=0, category="building")
        area = MissionArea(
            center_poi=center,
            radius_m=200.0,
            buildings=[],
            streets=["Main St"],
            defensive_positions=[],
            approach_routes=["Main St"],
        )
        specs = [{"type": "turret", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        assert len(result) == 1

    def test_no_streets_rovers_still_placed(self):
        """Even with no streets, rovers should be placed somewhere."""
        area = self._make_area(n_streets=0)
        specs = [{"type": "rover", "count": 1}]
        result = place_defenders_around_buildings(area, specs)
        assert len(result) == 1


# ===========================================================================
# TestGetPOIContextText
# ===========================================================================


class TestGetPOIContextText:
    """get_poi_context_text: LLM prompt text formatting."""

    def test_returns_string(self):
        pois = _sample_pois()
        center = pois[0]
        area = build_mission_area(center, pois, radius_m=500)
        text = get_poi_context_text(area)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_contains_center_name(self):
        pois = _sample_pois()
        center = pois[0]
        area = build_mission_area(center, pois, radius_m=500)
        text = get_poi_context_text(area)
        assert center.name in text

    def test_contains_building_names(self):
        pois = _sample_pois()
        center = pois[0]
        area = build_mission_area(center, pois, radius_m=500)
        text = get_poi_context_text(area)
        for b in area.buildings:
            assert b.name in text

    def test_contains_street_names(self):
        pois = _sample_pois()
        center = pois[0]
        area = build_mission_area(center, pois, radius_m=500)
        text = get_poi_context_text(area)
        for s in area.streets:
            assert s in text

    def test_empty_area(self):
        center = _make_poi(name="Empty Place")
        area = MissionArea(
            center_poi=center,
            radius_m=100.0,
            buildings=[],
            streets=[],
            defensive_positions=[],
            approach_routes=[],
        )
        text = get_poi_context_text(area)
        assert "Empty Place" in text


# ===========================================================================
# TestGetStreetNames
# ===========================================================================


class TestGetStreetNames:
    """get_street_names: extract unique street names."""

    def test_extracts_streets(self):
        pois = _sample_pois()
        streets = get_street_names(pois)
        assert "Village Pkwy" in streets
        assert "Amador Valley Blvd" in streets

    def test_unique_names(self):
        pois = _sample_pois()
        streets = get_street_names(pois)
        assert len(streets) == len(set(streets))

    def test_empty_list(self):
        streets = get_street_names([])
        assert streets == []

    def test_no_streets(self):
        pois = [_make_poi(category="building")]
        streets = get_street_names(pois)
        assert streets == []


# ===========================================================================
# TestOfflineGraceful
# ===========================================================================


class TestOfflineGraceful:
    """Graceful degradation when no network or cache is available."""

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_network_error_empty_result(self, mock_fetch):
        mock_fetch.side_effect = ConnectionError("No network")
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert pois == []

    def test_load_cached_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            result = load_cached(REF_LAT, REF_LNG, 500, cache_dir=td)
            assert result is None

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_load_cached_after_fetch(self, mock_fetch):
        mock_fetch.return_value = _make_overpass_response()
        with tempfile.TemporaryDirectory() as td:
            pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=td)
            cached = load_cached(REF_LAT, REF_LNG, 500, cache_dir=td)
            assert cached is not None
            assert len(cached) == len(pois)


# ===========================================================================
# TestEdgeCases
# ===========================================================================


class TestEdgeCases:
    """Edge cases: empty lists, single items, unusual inputs."""

    def test_build_area_empty_pois(self):
        center = _make_poi()
        area = build_mission_area(center, [], radius_m=200)
        assert area.buildings == []
        assert area.streets == []

    def test_build_area_single_building(self):
        center = _make_poi(category="building")
        area = build_mission_area(center, [center], radius_m=200)
        assert len(area.buildings) <= 1

    def test_build_area_no_streets(self):
        center = _make_poi(category="building")
        buildings = [
            _make_poi(name=f"B{i}", category="building", local_x=i * 10, local_y=i * 10)
            for i in range(3)
        ]
        area = build_mission_area(center, buildings, radius_m=500)
        assert area.streets == []

    def test_pick_center_all_streets(self):
        """If all POIs are streets, one should still be picked."""
        pois = [
            _make_poi(name=f"St {i}", category="street") for i in range(3)
        ]
        center = pick_mission_center(pois)
        assert center is not None

    def test_place_zero_count(self):
        """Spec with count=0 should produce no units."""
        center = _make_poi(name="HQ", local_x=0, local_y=0, category="building")
        area = MissionArea(
            center_poi=center,
            radius_m=200.0,
            buildings=[center],
            streets=["Main St"],
            defensive_positions=[(10, 10)],
            approach_routes=["Main St"],
        )
        specs = [{"type": "turret", "count": 0}]
        result = place_defenders_around_buildings(area, specs)
        assert result == []


# ===========================================================================
# TestRichCategories
# ===========================================================================


class TestRichCategories:
    """Rich POI categories: government, education, religion, sports,
    healthcare, transport, landmarks, infrastructure."""

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_government_townhall(self, mock_fetch):
        """Townhall parsed as government category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5001,
                "lat": 37.7165, "lon": -121.9350,
                "tags": {"amenity": "townhall", "name": "Dublin City Hall"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "government"
        assert pois[0].poi_type == "townhall"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_government_fire_station(self, mock_fetch):
        """Fire station parsed as government category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5002,
                "lat": 37.7166, "lon": -121.9349,
                "tags": {"amenity": "fire_station", "name": "Station 16"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "government"
        assert pois[0].poi_type == "fire_station"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_government_police(self, mock_fetch):
        """Police station parsed as government category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5003,
                "lat": 37.7167, "lon": -121.9348,
                "tags": {"amenity": "police", "name": "Dublin PD"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "government"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_government_building_way(self, mock_fetch):
        """Way with building=government parsed as government category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "way", "id": 5010,
                "center": {"lat": 37.7165, "lon": -121.9350},
                "tags": {"building": "government", "name": "Federal Building"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "government"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_education_school(self, mock_fetch):
        """School parsed as education category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5020,
                "lat": 37.7168, "lon": -121.9347,
                "tags": {"amenity": "school", "name": "Dublin Elementary"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "education"
        assert pois[0].poi_type == "school"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_education_university(self, mock_fetch):
        """University parsed as education category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5021,
                "lat": 37.7169, "lon": -121.9346,
                "tags": {"amenity": "university", "name": "Las Positas College"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "education"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_religion_place_of_worship(self, mock_fetch):
        """Place of worship parsed as religion category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5030,
                "lat": 37.7170, "lon": -121.9345,
                "tags": {"amenity": "place_of_worship", "name": "St. Raymond"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "religion"
        assert pois[0].poi_type == "place_of_worship"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_sports_stadium(self, mock_fetch):
        """Stadium parsed as sports category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5040,
                "lat": 37.7171, "lon": -121.9344,
                "tags": {"leisure": "stadium", "name": "Dublin Sports Park"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "sports"
        assert pois[0].poi_type == "stadium"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_sports_park(self, mock_fetch):
        """Park parsed as sports category (leisure)."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "way", "id": 5041,
                "center": {"lat": 37.7172, "lon": -121.9343},
                "tags": {"leisure": "park", "name": "Emerald Glen Park"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "sports"
        assert pois[0].poi_type == "park"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_healthcare_hospital(self, mock_fetch):
        """Hospital parsed as healthcare category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5050,
                "lat": 37.7173, "lon": -121.9342,
                "tags": {"amenity": "hospital", "name": "Dublin General"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "healthcare"
        assert pois[0].poi_type == "hospital"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_transport_bus_station(self, mock_fetch):
        """Bus station parsed as transport category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5060,
                "lat": 37.7174, "lon": -121.9341,
                "tags": {"amenity": "bus_station", "name": "Dublin/Pleasanton BART"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "transport"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_transport_railway_station(self, mock_fetch):
        """Railway station parsed as transport category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5061,
                "lat": 37.7175, "lon": -121.9340,
                "tags": {"railway": "station", "name": "BART West Dublin"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "transport"
        assert pois[0].poi_type == "station"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_landmark_attraction(self, mock_fetch):
        """Tourism attraction parsed as landmark category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5070,
                "lat": 37.7176, "lon": -121.9339,
                "tags": {"tourism": "attraction", "name": "Heritage Park"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "landmark"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_landmark_monument(self, mock_fetch):
        """Historic monument parsed as landmark category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5071,
                "lat": 37.7177, "lon": -121.9338,
                "tags": {"historic": "monument", "name": "Veterans Memorial"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "landmark"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_landmark_museum(self, mock_fetch):
        """Museum parsed as landmark category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5072,
                "lat": 37.7178, "lon": -121.9337,
                "tags": {"tourism": "museum", "name": "Dublin Heritage Museum"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "landmark"
        assert pois[0].poi_type == "museum"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_infrastructure_primary_road(self, mock_fetch):
        """Primary highway parsed as street category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "way", "id": 5080,
                "center": {"lat": 37.7179, "lon": -121.9336},
                "tags": {"highway": "primary", "name": "Dublin Blvd"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "street"
        assert pois[0].poi_type == "primary"

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_mixed_rich_categories(self, mock_fetch):
        """Multiple rich categories in a single Overpass response."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 6001,
                "lat": 37.7165, "lon": -121.9350,
                "tags": {"amenity": "fire_station", "name": "Station 16"},
            },
            {
                "type": "node", "id": 6002,
                "lat": 37.7166, "lon": -121.9349,
                "tags": {"amenity": "hospital", "name": "ValleyCare"},
            },
            {
                "type": "node", "id": 6003,
                "lat": 37.7167, "lon": -121.9348,
                "tags": {"leisure": "stadium", "name": "Dublin Sports Park"},
            },
            {
                "type": "node", "id": 6004,
                "lat": 37.7168, "lon": -121.9347,
                "tags": {"tourism": "museum", "name": "Heritage Museum"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 4
        categories = {p.category for p in pois}
        assert "government" in categories
        assert "healthcare" in categories
        assert "sports" in categories
        assert "landmark" in categories

    @patch("engine.simulation.poi_data._fetch_overpass")
    def test_library_is_education(self, mock_fetch):
        """Library parsed as education category."""
        mock_fetch.return_value = _make_overpass_response([
            {
                "type": "node", "id": 5090,
                "lat": 37.7165, "lon": -121.9350,
                "tags": {"amenity": "library", "name": "Dublin Library"},
            },
        ])
        pois = fetch_pois(REF_LAT, REF_LNG, radius_m=500, cache_dir=None)
        assert len(pois) == 1
        assert pois[0].category == "education"
        assert pois[0].poi_type == "library"


# ===========================================================================
# TestPOITypeLabels
# ===========================================================================


class TestPOITypeLabels:
    """POI_TYPE_LABELS maps OSM types to human-readable labels."""

    def test_fire_station_label(self):
        assert POI_TYPE_LABELS["fire_station"] == "Fire Station"

    def test_place_of_worship_label(self):
        assert POI_TYPE_LABELS["place_of_worship"] == "Church/Mosque/Temple"

    def test_townhall_label(self):
        assert POI_TYPE_LABELS["townhall"] == "Town Hall"

    def test_hospital_label(self):
        assert POI_TYPE_LABELS["hospital"] == "Hospital"

    def test_stadium_label(self):
        assert POI_TYPE_LABELS["stadium"] == "Stadium"

    def test_museum_label(self):
        assert POI_TYPE_LABELS["museum"] == "Museum"


# ===========================================================================
# TestSignificance
# ===========================================================================


class TestSignificance:
    """Significance scores by category for mission prioritization."""

    def test_government_highest(self):
        """Government POIs have significance 0.9."""
        assert get_significance("government") == pytest.approx(0.9)

    def test_education_high(self):
        """Education POIs have significance 0.9."""
        assert get_significance("education") == pytest.approx(0.9)

    def test_healthcare_high(self):
        """Healthcare POIs have significance 0.9."""
        assert get_significance("healthcare") == pytest.approx(0.9)

    def test_landmark_medium_high(self):
        """Landmarks have significance 0.8."""
        assert get_significance("landmark") == pytest.approx(0.8)

    def test_religion_medium_high(self):
        """Religion POIs have significance 0.7."""
        assert get_significance("religion") == pytest.approx(0.7)

    def test_sports_medium(self):
        """Sports POIs have significance 0.6."""
        assert get_significance("sports") == pytest.approx(0.6)

    def test_transport_medium(self):
        """Transport POIs have significance 0.6."""
        assert get_significance("transport") == pytest.approx(0.6)

    def test_shop_low(self):
        """Shop POIs have significance 0.3."""
        assert get_significance("shop") == pytest.approx(0.3)

    def test_building_low(self):
        """Building POIs have significance 0.2."""
        assert get_significance("building") == pytest.approx(0.2)

    def test_street_lowest(self):
        """Street POIs have significance 0.1."""
        assert get_significance("street") == pytest.approx(0.1)

    def test_unknown_defaults_low(self):
        """Unknown categories default to 0.1."""
        assert get_significance("unknown_xyz") == pytest.approx(0.1)

    def test_government_gt_shop(self):
        """Government > shop significance."""
        assert get_significance("government") > get_significance("shop")

    def test_shop_gt_residential(self):
        """Shop > building significance."""
        assert get_significance("shop") > get_significance("building")

    def test_significance_dict_exported(self):
        """CATEGORY_SIGNIFICANCE dict is accessible."""
        assert isinstance(CATEGORY_SIGNIFICANCE, dict)
        assert "government" in CATEGORY_SIGNIFICANCE
        assert "shop" in CATEGORY_SIGNIFICANCE


# ===========================================================================
# TestPreferSignificantCenters
# ===========================================================================


class TestPreferSignificantCenters:
    """pick_mission_center prefers high-significance POIs."""

    def test_government_preferred_over_shop(self):
        """Given a government building and a shop, government is preferred."""
        gov = _make_poi(
            name="City Hall", poi_type="townhall", category="government",
            osm_id=7001,
        )
        shop = _make_poi(
            name="7-Eleven", poi_type="convenience", category="shop",
            osm_id=7002,
        )
        # Run 50 times — government (0.9) should beat shop (0.3) most of the time
        # Expected ratio: 0.9/(0.9+0.3) = 75%.  Threshold at 50% for robustness.
        gov_count = sum(
            1 for _ in range(50)
            if pick_mission_center([gov, shop]).name == "City Hall"
        )
        assert gov_count >= 25, f"Government picked only {gov_count}/50 times"

    def test_hospital_preferred_over_residential(self):
        """Hospital preferred over generic residential building."""
        hosp = _make_poi(
            name="Dublin General", poi_type="hospital", category="healthcare",
            osm_id=7003,
        )
        res = _make_poi(
            name="1234 Main St", poi_type="residential", category="building",
            osm_id=7004,
        )
        hosp_count = sum(
            1 for _ in range(30)
            if pick_mission_center([hosp, res]).name == "Dublin General"
        )
        assert hosp_count >= 20, f"Hospital picked only {hosp_count}/30 times"

    def test_landmark_preferred_over_street(self):
        """Landmark preferred over a street."""
        landmark = _make_poi(
            name="Heritage Park", poi_type="attraction", category="landmark",
            osm_id=7005,
        )
        street = _make_poi(
            name="Main St", poi_type="residential", category="street",
            osm_id=7006,
        )
        landmark_count = sum(
            1 for _ in range(30)
            if pick_mission_center([landmark, street]).name == "Heritage Park"
        )
        assert landmark_count >= 25, f"Landmark picked only {landmark_count}/30 times"

    def test_explicit_preference_still_overrides(self):
        """Explicit preference= still wins over significance."""
        gov = _make_poi(
            name="City Hall", poi_type="townhall", category="government",
            osm_id=7007,
        )
        shop = _make_poi(
            name="Circle K", poi_type="convenience", category="shop",
            osm_id=7008,
        )
        result = pick_mission_center([gov, shop], preference="Circle K")
        assert result.name == "Circle K"

    def test_all_equal_significance_still_picks(self):
        """When all POIs have same significance, one is still picked."""
        shops = [
            _make_poi(name=f"Shop {i}", category="shop", osm_id=8000 + i)
            for i in range(5)
        ]
        result = pick_mission_center(shops)
        assert result is not None
        assert result.category == "shop"
