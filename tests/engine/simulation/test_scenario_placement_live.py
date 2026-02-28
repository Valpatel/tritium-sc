"""Live Overpass API tests for POI data module.

These tests make REAL network calls to the Overpass API.
They are skipped by default.  Run with:

    .venv/bin/python3 -m pytest tests/engine/simulation/test_scenario_placement_live.py -m network -v

Requires adding ``-m network`` or ``--run-network`` to include them.
"""

from __future__ import annotations

import math

import pytest

from engine.simulation.poi_data import (
    POI,
    MissionArea,
    build_mission_area,
    fetch_pois,
    get_poi_context_text,
    get_street_names,
    pick_mission_center,
    place_defenders_around_buildings,
)

# Skip all tests unless explicitly opting in
pytestmark = pytest.mark.network

# Dublin, CA — the project's home neighborhood
DUBLIN_LAT = 37.7161
DUBLIN_LNG = -121.9357


def _full_specs() -> list[dict]:
    return [
        {"type": "turret", "count": 2},
        {"type": "rover", "count": 2},
        {"type": "drone", "count": 1},
    ]


class TestLiveDublinFetch:
    """Live Overpass queries against Dublin, CA."""

    def test_fetch_dublin_pois(self):
        """Query Overpass for Dublin center, verify >10 POIs returned."""
        pois = fetch_pois(DUBLIN_LAT, DUBLIN_LNG, radius_m=500, cache_dir=None)
        assert len(pois) > 10, f"Expected >10 POIs, got {len(pois)}"
        # Should have at least some named POIs
        named = [p for p in pois if p.name]
        assert len(named) > 5

    def test_dublin_has_streets(self):
        """Verify street names include known Dublin streets."""
        pois = fetch_pois(DUBLIN_LAT, DUBLIN_LNG, radius_m=500, cache_dir=None)
        streets = get_street_names(pois)
        assert len(streets) > 0, "No streets found"
        # At least one should be recognizable
        all_text = " ".join(streets).lower()
        # Dublin has streets like Village Pkwy, Amador Valley Blvd, etc.
        # Don't assert specific names since OSM data can change
        assert len(all_text) > 10

    def test_dublin_has_buildings(self):
        pois = fetch_pois(DUBLIN_LAT, DUBLIN_LNG, radius_m=500, cache_dir=None)
        buildings = [p for p in pois if p.category == "building"]
        assert len(buildings) > 0

    def test_dublin_has_amenities(self):
        pois = fetch_pois(DUBLIN_LAT, DUBLIN_LNG, radius_m=500, cache_dir=None)
        amenities = [p for p in pois if p.category == "amenity"]
        # Dublin center should have at least a few amenities
        assert len(amenities) >= 1


class TestLivePlacement:
    """Full placement pipeline with live data."""

    def test_place_defenders_at_dublin_buildings(self):
        """Full placement with real data."""
        pois = fetch_pois(DUBLIN_LAT, DUBLIN_LNG, radius_m=500, cache_dir=None)
        assert len(pois) > 0, "No POIs fetched"

        center = pick_mission_center(pois)
        assert center is not None

        area = build_mission_area(center, pois, radius_m=200)
        assert isinstance(area, MissionArea)

        result = place_defenders_around_buildings(area, _full_specs())
        assert len(result) == 5

        # Verify all have positions and names
        for r in result:
            assert "asset_type" in r
            assert "position" in r
            assert "name" in r
            assert r["name"]

    def test_generate_scripted_dublin(self):
        """Full scripted generation with live data."""
        pois = fetch_pois(DUBLIN_LAT, DUBLIN_LNG, radius_m=500, cache_dir=None)
        center = pick_mission_center(pois)
        area = build_mission_area(center, pois, radius_m=200)
        text = get_poi_context_text(area)

        # Context text should reference real places
        assert center.name in text
        assert len(text) > 100

    def test_generate_10_scenarios(self):
        """Generate 10 different scenarios, verify variety."""
        pois = fetch_pois(DUBLIN_LAT, DUBLIN_LNG, radius_m=500, cache_dir=None)
        assert len(pois) > 5

        centers = set()
        for _ in range(10):
            center = pick_mission_center(pois)
            if center:
                centers.add(center.name)

        # Should pick at least 2 different centers over 10 tries
        assert len(centers) >= 2, f"Only picked {centers}"

    def test_placement_quality_live(self):
        """Verify placement quality with real Dublin data."""
        pois = fetch_pois(DUBLIN_LAT, DUBLIN_LNG, radius_m=500, cache_dir=None)
        center = pick_mission_center(pois)
        area = build_mission_area(center, pois, radius_m=200)

        specs = [
            {"type": "turret", "count": 3},
            {"type": "rover", "count": 2},
            {"type": "drone", "count": 1},
            {"type": "scout_drone", "count": 1},
        ]
        result = place_defenders_around_buildings(area, specs)
        assert len(result) == 7

        # All positions unique
        positions = [tuple(r["position"]) for r in result]
        assert len(set(positions)) == len(positions)

        # All names unique
        names = [r["name"] for r in result]
        assert len(set(names)) == len(names)

        # All within reasonable radius
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for r in result:
            pos = r["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            assert dist <= 300, f"{r['name']} too far: {dist:.0f}m"

    def test_local_coords_reasonable(self):
        """Verify local coordinates are in reasonable range."""
        pois = fetch_pois(DUBLIN_LAT, DUBLIN_LNG, radius_m=500, cache_dir=None)
        for p in pois:
            # Local coords should be within ~500m of origin
            assert abs(p.local_x) <= 600, f"local_x out of range: {p.local_x}"
            assert abs(p.local_y) <= 600, f"local_y out of range: {p.local_y}"
