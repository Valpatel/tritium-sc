"""Unit tests for the /api/geo/overlay endpoint.

Tests the GET /api/geo/overlay endpoint which returns pre-loaded road
polylines and building polygons from app.state. Validates behavior with
populated data, empty data, and missing state attributes.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.geo import router

pytestmark = pytest.mark.unit


def _make_app(
    road_polylines: list | None = None,
    building_dicts: list | None = None,
    *,
    set_roads: bool = True,
    set_buildings: bool = True,
) -> FastAPI:
    """Create a minimal FastAPI app with the geo router and optional state."""
    app = FastAPI()
    app.include_router(router)
    if set_roads:
        app.state.road_polylines = road_polylines
    if set_buildings:
        app.state.building_dicts = building_dicts
    return app


# ---------------------------------------------------------------------------
# Basic overlay endpoint behavior
# ---------------------------------------------------------------------------

class TestOverlayEndpointBasics:
    """GET /api/geo/overlay returns roads and buildings from app.state."""

    def test_empty_state_returns_empty_arrays(self) -> None:
        """When state has None values, endpoint returns empty arrays."""
        app = _make_app(road_polylines=None, building_dicts=None)
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        assert resp.status_code == 200
        data = resp.json()
        assert data["roads"] == []
        assert data["buildings"] == []

    def test_missing_state_attributes_returns_empty(self) -> None:
        """When app.state has no road/building attrs at all, fallback to empty."""
        app = _make_app(set_roads=False, set_buildings=False)
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        assert resp.status_code == 200
        data = resp.json()
        assert data["roads"] == []
        assert data["buildings"] == []

    def test_response_has_both_keys(self) -> None:
        """Response always contains both 'roads' and 'buildings' keys."""
        app = _make_app(road_polylines=[], building_dicts=[])
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        assert resp.status_code == 200
        data = resp.json()
        assert "roads" in data
        assert "buildings" in data


# ---------------------------------------------------------------------------
# Roads data
# ---------------------------------------------------------------------------

class TestOverlayRoads:
    """Verify road polyline data passes through correctly."""

    SAMPLE_ROADS: list[dict] = [
        {"points": [[0.0, 0.0], [10.0, 5.0]], "class": "residential"},
        {"points": [[10.0, 5.0], [20.0, 15.0]], "class": "secondary"},
        {"points": [[-5.0, 3.0], [8.0, -2.0]], "class": "service"},
    ]

    def test_roads_returned_verbatim(self) -> None:
        """Pre-loaded road polylines are returned exactly as stored."""
        app = _make_app(road_polylines=self.SAMPLE_ROADS, building_dicts=[])
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        data = resp.json()
        assert len(data["roads"]) == 3
        assert data["roads"][0]["class"] == "residential"
        assert data["roads"][1]["class"] == "secondary"
        assert data["roads"][2]["class"] == "service"

    def test_road_points_structure(self) -> None:
        """Each road has a 'points' list of two-element coordinate arrays."""
        app = _make_app(road_polylines=self.SAMPLE_ROADS, building_dicts=[])
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        road = resp.json()["roads"][0]
        assert "points" in road
        assert len(road["points"]) == 2
        assert road["points"][0] == [0.0, 0.0]
        assert road["points"][1] == [10.0, 5.0]

    def test_single_road(self) -> None:
        """Endpoint works with a single road segment."""
        roads = [{"points": [[1.0, 2.0], [3.0, 4.0]], "class": "path"}]
        app = _make_app(road_polylines=roads, building_dicts=[])
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        assert len(resp.json()["roads"]) == 1

    def test_many_roads(self) -> None:
        """Endpoint handles many road segments."""
        roads = [
            {"points": [[float(i), 0.0], [float(i + 1), 0.0]], "class": "residential"}
            for i in range(100)
        ]
        app = _make_app(road_polylines=roads, building_dicts=[])
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        assert len(resp.json()["roads"]) == 100

    def test_roads_none_buildings_populated(self) -> None:
        """Roads can be empty while buildings have data."""
        buildings = [{"polygon": [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0]], "height": 8.0}]
        app = _make_app(road_polylines=None, building_dicts=buildings)
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        data = resp.json()
        assert data["roads"] == []
        assert len(data["buildings"]) == 1


# ---------------------------------------------------------------------------
# Buildings data
# ---------------------------------------------------------------------------

class TestOverlayBuildings:
    """Verify building polygon data passes through correctly."""

    SAMPLE_BUILDINGS: list[dict] = [
        {
            "polygon": [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]],
            "height": 8.0,
        },
        {
            "polygon": [[20.0, 20.0], [30.0, 20.0], [30.0, 30.0], [20.0, 30.0]],
            "height": 12.0,
        },
    ]

    def test_buildings_returned_verbatim(self) -> None:
        """Pre-loaded building dicts are returned exactly as stored."""
        app = _make_app(road_polylines=[], building_dicts=self.SAMPLE_BUILDINGS)
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        data = resp.json()
        assert len(data["buildings"]) == 2
        assert data["buildings"][0]["height"] == 8.0
        assert data["buildings"][1]["height"] == 12.0

    def test_building_polygon_structure(self) -> None:
        """Each building has 'polygon' (list of [x,y]) and 'height'."""
        app = _make_app(road_polylines=[], building_dicts=self.SAMPLE_BUILDINGS)
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        bldg = resp.json()["buildings"][0]
        assert "polygon" in bldg
        assert "height" in bldg
        assert len(bldg["polygon"]) == 4
        assert bldg["polygon"][0] == [0.0, 0.0]

    def test_single_building(self) -> None:
        buildings = [{"polygon": [[0, 0], [5, 0], [5, 5]], "height": 6.0}]
        app = _make_app(road_polylines=[], building_dicts=buildings)
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        assert len(resp.json()["buildings"]) == 1

    def test_buildings_none_roads_populated(self) -> None:
        """Buildings can be empty while roads have data."""
        roads = [{"points": [[0.0, 0.0], [5.0, 5.0]], "class": "residential"}]
        app = _make_app(road_polylines=roads, building_dicts=None)
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        data = resp.json()
        assert len(data["roads"]) == 1
        assert data["buildings"] == []


# ---------------------------------------------------------------------------
# Combined data
# ---------------------------------------------------------------------------

class TestOverlayCombined:
    """Test the overlay endpoint with both roads and buildings populated."""

    def test_both_populated(self) -> None:
        roads = [{"points": [[0.0, 0.0], [10.0, 0.0]], "class": "residential"}]
        buildings = [{"polygon": [[5.0, 5.0], [15.0, 5.0], [15.0, 15.0]], "height": 10.0}]
        app = _make_app(road_polylines=roads, building_dicts=buildings)
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        data = resp.json()
        assert len(data["roads"]) == 1
        assert len(data["buildings"]) == 1

    def test_large_dataset(self) -> None:
        """Endpoint handles realistically sized overlay data."""
        roads = [
            {"points": [[float(i), 0.0], [float(i + 1), 1.0]], "class": "residential"}
            for i in range(200)
        ]
        buildings = [
            {
                "polygon": [
                    [float(i), float(j)]
                    for j in range(4)
                ],
                "height": 8.0,
            }
            for i in range(50)
        ]
        app = _make_app(road_polylines=roads, building_dicts=buildings)
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        data = resp.json()
        assert len(data["roads"]) == 200
        assert len(data["buildings"]) == 50

    def test_content_type_is_json(self) -> None:
        """Response content type is application/json."""
        app = _make_app(road_polylines=[], building_dicts=[])
        client = TestClient(app)
        resp = client.get("/api/geo/overlay")
        assert "application/json" in resp.headers["content-type"]

    def test_method_not_allowed(self) -> None:
        """POST to /api/geo/overlay is not allowed."""
        app = _make_app(road_polylines=[], building_dicts=[])
        client = TestClient(app)
        resp = client.post("/api/geo/overlay")
        assert resp.status_code == 405
