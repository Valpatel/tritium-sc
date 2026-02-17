"""Unit tests for the geo engine coordinate transforms and helpers."""

from __future__ import annotations

import math

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Python-side coordinate helpers (mirrors frontend/js/geo.js logic)
# ---------------------------------------------------------------------------

METERS_PER_DEG_LAT = 111320


def meters_per_deg_lng(lat: float) -> float:
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def latlng_to_game(
    lat: float, lng: float, center_lat: float, center_lng: float
) -> tuple[float, float]:
    """Convert lat/lng to game coords (meters from center). X=East, Y=North."""
    y = (lat - center_lat) * METERS_PER_DEG_LAT
    x = (lng - center_lng) * meters_per_deg_lng(center_lat)
    return x, y


def game_to_latlng(
    x: float, y: float, center_lat: float, center_lng: float
) -> tuple[float, float]:
    """Convert game coords back to lat/lng."""
    lat = center_lat + y / METERS_PER_DEG_LAT
    lng = center_lng + x / meters_per_deg_lng(center_lat)
    return lat, lng


def tile_for_latlng(lat: float, lng: float, zoom: int) -> tuple[int, int, int]:
    """Slippy-map tile coordinates for a lat/lng at a given zoom."""
    n = 2 ** zoom
    x = int((lng + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y, zoom


def tile_bounds(x: int, y: int, z: int) -> dict:
    """Get lat/lng bounds of a tile."""
    n = 2 ** z
    west = x / n * 360 - 180
    east = (x + 1) / n * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return {"north": north, "south": south, "west": west, "east": east}


# ---------------------------------------------------------------------------
# Tests: Round-trip accuracy
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """latlng -> game -> latlng should be identity (within float precision)."""

    # Dublin, CA
    CENTER_LAT = 37.7161
    CENTER_LNG = -121.9138

    def test_center_is_origin(self):
        x, y = latlng_to_game(
            self.CENTER_LAT, self.CENTER_LNG,
            self.CENTER_LAT, self.CENTER_LNG,
        )
        assert abs(x) < 1e-6
        assert abs(y) < 1e-6

    def test_round_trip_nearby(self):
        """A point 100m north and 50m east should round-trip accurately."""
        lat0, lng0 = self.CENTER_LAT, self.CENTER_LNG
        x0, y0 = 50.0, 100.0

        lat, lng = game_to_latlng(x0, y0, lat0, lng0)
        x1, y1 = latlng_to_game(lat, lng, lat0, lng0)

        assert abs(x1 - x0) < 0.01  # sub-centimeter
        assert abs(y1 - y0) < 0.01

    def test_round_trip_origin(self):
        lat, lng = game_to_latlng(0, 0, self.CENTER_LAT, self.CENTER_LNG)
        assert abs(lat - self.CENTER_LAT) < 1e-10
        assert abs(lng - self.CENTER_LNG) < 1e-10

    @pytest.mark.parametrize("x,y", [
        (0, 0),
        (100, 0),
        (0, 100),
        (-200, 300),
        (500, -500),
    ])
    def test_round_trip_parametric(self, x, y):
        lat, lng = game_to_latlng(x, y, self.CENTER_LAT, self.CENTER_LNG)
        x2, y2 = latlng_to_game(lat, lng, self.CENTER_LAT, self.CENTER_LNG)
        assert abs(x2 - x) < 0.01
        assert abs(y2 - y) < 0.01


# ---------------------------------------------------------------------------
# Tests: Known distances
# ---------------------------------------------------------------------------

class TestKnownDistances:
    """Verify coordinate transforms produce reasonable real-world distances."""

    CENTER_LAT = 37.7161
    CENTER_LNG = -121.9138

    def test_one_degree_lat_is_111km(self):
        """1 degree of latitude is ~111.32 km at any latitude."""
        x, y = latlng_to_game(
            self.CENTER_LAT + 1, self.CENTER_LNG,
            self.CENTER_LAT, self.CENTER_LNG,
        )
        assert abs(x) < 0.01
        assert abs(y - 111320) < 1  # within 1 meter

    def test_one_degree_lng_at_37(self):
        """1 degree of longitude at 37.7N is ~88 km."""
        x, y = latlng_to_game(
            self.CENTER_LAT, self.CENTER_LNG + 1,
            self.CENTER_LAT, self.CENTER_LNG,
        )
        assert abs(y) < 0.01
        expected = 111320 * math.cos(math.radians(self.CENTER_LAT))
        assert abs(x - expected) < 1

    def test_100m_north(self):
        lat, lng = game_to_latlng(0, 100, self.CENTER_LAT, self.CENTER_LNG)
        delta_lat = lat - self.CENTER_LAT
        meters = delta_lat * METERS_PER_DEG_LAT
        assert abs(meters - 100) < 0.01

    def test_100m_east(self):
        lat, lng = game_to_latlng(100, 0, self.CENTER_LAT, self.CENTER_LNG)
        delta_lng = lng - self.CENTER_LNG
        meters = delta_lng * meters_per_deg_lng(self.CENTER_LAT)
        assert abs(meters - 100) < 0.01


# ---------------------------------------------------------------------------
# Tests: Tile coordinates
# ---------------------------------------------------------------------------

class TestTileCoords:
    def test_zoom_0_single_tile(self):
        """At zoom 0, entire world is one tile (0, 0)."""
        x, y, z = tile_for_latlng(0, 0, 0)
        assert x == 0
        assert y == 0
        assert z == 0

    def test_known_tile(self):
        """Verify a known lat/lng produces expected tile at zoom 19."""
        # Dublin, CA at zoom 19 — just check it's reasonable
        x, y, z = tile_for_latlng(37.7161, -121.9138, 19)
        assert z == 19
        # At zoom 19, tiles are very small; x,y should be large numbers
        assert x > 0
        assert y > 0
        # Sanity: tile numbers at zoom 19 are in the ~80k-160k range
        assert 50000 < x < 300000
        assert 50000 < y < 300000

    def test_tile_bounds_contain_center(self):
        """The tile containing a point should have bounds that include it."""
        lat, lng = 37.7161, -121.9138
        x, y, z = tile_for_latlng(lat, lng, 17)
        bounds = tile_bounds(x, y, z)
        assert bounds["south"] <= lat <= bounds["north"]
        assert bounds["west"] <= lng <= bounds["east"]

    @pytest.mark.parametrize("zoom", [1, 5, 10, 15, 19])
    def test_tile_bounds_contain_center_at_zoom(self, zoom):
        lat, lng = 37.7161, -121.9138
        x, y, z = tile_for_latlng(lat, lng, zoom)
        bounds = tile_bounds(x, y, z)
        assert bounds["south"] <= lat <= bounds["north"]
        assert bounds["west"] <= lng <= bounds["east"]

    def test_adjacent_tiles_share_edge(self):
        """Two horizontally adjacent tiles should share an edge."""
        x, y, z = 100, 100, 15
        b1 = tile_bounds(x, y, z)
        b2 = tile_bounds(x + 1, y, z)
        assert abs(b1["east"] - b2["west"]) < 1e-10


# ---------------------------------------------------------------------------
# Tests: Tile bounds -> game coords
# ---------------------------------------------------------------------------

class TestTileBoundsGameCoords:
    CENTER_LAT = 37.7161
    CENTER_LNG = -121.9138

    def test_center_tile_spans_origin(self):
        """The tile at the center should have game-coord bounds spanning (0,0)."""
        x, y, z = tile_for_latlng(self.CENTER_LAT, self.CENTER_LNG, 19)
        bounds = tile_bounds(x, y, z)
        nw_game = latlng_to_game(
            bounds["north"], bounds["west"],
            self.CENTER_LAT, self.CENTER_LNG,
        )
        se_game = latlng_to_game(
            bounds["south"], bounds["east"],
            self.CENTER_LAT, self.CENTER_LNG,
        )
        # nw_game.x (west) should be <= 0 and se_game.x (east) should be >= 0
        assert nw_game[0] <= 0 <= se_game[0]
        # nw_game.y (north) should be >= 0 and se_game.y (south) should be <= 0
        assert se_game[1] <= 0 <= nw_game[1]


# ---------------------------------------------------------------------------
# Tests: Building height estimation
# ---------------------------------------------------------------------------

class TestBuildingHeightEstimation:
    """Test the height estimation logic (mirrors _estimateBuildingHeight in geo.js)."""

    @staticmethod
    def _estimate(tags: dict) -> float:
        if "height" in tags:
            h = float(tags["height"])
            if not math.isnan(h):
                return h
        if "building:levels" in tags:
            levels = int(tags["building:levels"])
            return levels * 3
        btype = tags.get("building", "")
        if btype in ("garage", "garages", "shed"):
            return 3
        if btype in ("house", "residential", "detached"):
            return 7
        if btype in ("apartments", "commercial"):
            return 12
        if btype in ("industrial", "warehouse"):
            return 8
        return 6

    def test_explicit_height(self):
        assert self._estimate({"height": "15"}) == 15.0

    def test_levels(self):
        assert self._estimate({"building:levels": "4"}) == 12.0

    def test_house(self):
        assert self._estimate({"building": "house"}) == 7

    def test_garage(self):
        assert self._estimate({"building": "garage"}) == 3

    def test_apartments(self):
        assert self._estimate({"building": "apartments"}) == 12

    def test_generic(self):
        assert self._estimate({"building": "yes"}) == 6


# ---------------------------------------------------------------------------
# Tests: Meters per pixel
# ---------------------------------------------------------------------------

class TestMetersPerPixel:
    def test_zoom_0_equator(self):
        """At zoom 0, equator: ~156543 m/pixel."""
        mpp = 156543.03392 * math.cos(0) / (2 ** 0)
        assert abs(mpp - 156543.03392) < 0.01

    def test_higher_zoom_less_meters(self):
        lat = 37.7
        mpp_17 = 156543.03392 * math.cos(math.radians(lat)) / (2 ** 17)
        mpp_19 = 156543.03392 * math.cos(math.radians(lat)) / (2 ** 19)
        assert mpp_19 < mpp_17
        # At zoom 19, ~0.3m/pixel at mid-latitudes
        assert 0.1 < mpp_19 < 0.5


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_north_pole_area(self):
        """Transforms should still work near extreme latitudes."""
        center_lat, center_lng = 89.0, 0.0
        x, y = latlng_to_game(89.001, 0.001, center_lat, center_lng)
        lat2, lng2 = game_to_latlng(x, y, center_lat, center_lng)
        assert abs(lat2 - 89.001) < 1e-6
        assert abs(lng2 - 0.001) < 1e-6

    def test_equator(self):
        """At the equator, meters_per_deg_lng equals METERS_PER_DEG_LAT."""
        mpdl = meters_per_deg_lng(0.0)
        assert abs(mpdl - METERS_PER_DEG_LAT) < 1

    def test_negative_coordinates(self):
        """Southern/western hemisphere should work fine."""
        center_lat, center_lng = -33.8688, 151.2093  # Sydney
        x, y = latlng_to_game(-33.8588, 151.2193, center_lat, center_lng)
        lat2, lng2 = game_to_latlng(x, y, center_lat, center_lng)
        assert abs(lat2 - (-33.8588)) < 1e-6
        assert abs(lng2 - 151.2193) < 1e-6
