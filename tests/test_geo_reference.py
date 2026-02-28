# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for amy.tactical.geo — server-side geo-reference and coordinate transforms."""

import math
import pytest

from amy.tactical.geo import (
    GeoReference,
    METERS_PER_DEG_LAT,
    init_reference,
    get_reference,
    is_initialized,
    local_to_latlng,
    latlng_to_local,
    local_to_latlng_2d,
)


# Test reference point — San Francisco Civic Center (public landmark)
TEST_LAT = 37.7749
TEST_LNG = -122.4194


@pytest.fixture(autouse=True)
def reset_reference():
    """Reset the geo reference before each test."""
    import amy.tactical.geo as geo_mod
    geo_mod._ref = GeoReference()
    yield
    geo_mod._ref = GeoReference()


class TestGeoReference:
    """Test the GeoReference dataclass and module-level singleton."""

    @pytest.mark.unit
    def test_default_not_initialized(self):
        assert not is_initialized()
        ref = get_reference()
        assert ref.lat == 0.0
        assert ref.lng == 0.0
        assert not ref.initialized

    @pytest.mark.unit
    def test_init_reference(self):
        ref = init_reference(TEST_LAT, TEST_LNG, 50.0)
        assert ref.initialized
        assert ref.lat == pytest.approx(TEST_LAT)
        assert ref.lng == pytest.approx(TEST_LNG)
        assert ref.alt == 50.0

    @pytest.mark.unit
    def test_is_initialized_after_init(self):
        init_reference(TEST_LAT, TEST_LNG)
        assert is_initialized()

    @pytest.mark.unit
    def test_get_reference_returns_same(self):
        init_reference(TEST_LAT, TEST_LNG)
        ref = get_reference()
        assert ref.lat == pytest.approx(TEST_LAT)
        assert ref.lng == pytest.approx(TEST_LNG)

    @pytest.mark.unit
    def test_meters_per_deg_lng(self):
        ref = GeoReference(lat=TEST_LAT, lng=TEST_LNG, initialized=True)
        expected = METERS_PER_DEG_LAT * math.cos(math.radians(TEST_LAT))
        assert ref.meters_per_deg_lng == pytest.approx(expected)

    @pytest.mark.unit
    def test_reinit_updates(self):
        init_reference(10.0, 20.0)
        init_reference(TEST_LAT, TEST_LNG)
        ref = get_reference()
        assert ref.lat == pytest.approx(TEST_LAT)


class TestCoordinateTransforms:
    """Test local_to_latlng and latlng_to_local."""

    @pytest.mark.unit
    def test_origin_is_reference(self):
        init_reference(TEST_LAT, TEST_LNG, 100.0)
        result = local_to_latlng(0.0, 0.0, 0.0)
        assert result["lat"] == pytest.approx(TEST_LAT)
        assert result["lng"] == pytest.approx(TEST_LNG)
        assert result["alt"] == pytest.approx(100.0)

    @pytest.mark.unit
    def test_roundtrip_local_to_latlng_to_local(self):
        init_reference(TEST_LAT, TEST_LNG)
        # 100m east, 50m north
        geo = local_to_latlng(100.0, 50.0, 10.0)
        x, y, z = latlng_to_local(geo["lat"], geo["lng"], geo["alt"])
        assert x == pytest.approx(100.0, abs=0.01)
        assert y == pytest.approx(50.0, abs=0.01)
        assert z == pytest.approx(10.0, abs=0.01)

    @pytest.mark.unit
    def test_roundtrip_latlng_to_local_to_latlng(self):
        init_reference(TEST_LAT, TEST_LNG)
        # Slightly offset from center
        lat = TEST_LAT + 0.001
        lng = TEST_LNG + 0.001
        x, y, z = latlng_to_local(lat, lng)
        result = local_to_latlng(x, y, z)
        assert result["lat"] == pytest.approx(lat, abs=1e-7)
        assert result["lng"] == pytest.approx(lng, abs=1e-7)

    @pytest.mark.unit
    def test_north_is_positive_y(self):
        init_reference(TEST_LAT, TEST_LNG)
        # Point north of reference should have positive y
        x, y, _ = latlng_to_local(TEST_LAT + 0.001, TEST_LNG)
        assert y > 0
        assert abs(x) < 0.1  # same longitude = ~0 east offset

    @pytest.mark.unit
    def test_east_is_positive_x(self):
        init_reference(TEST_LAT, TEST_LNG)
        # Point east of reference should have positive x
        x, y, _ = latlng_to_local(TEST_LAT, TEST_LNG + 0.001)
        assert x > 0
        assert abs(y) < 0.1  # same latitude = ~0 north offset

    @pytest.mark.unit
    def test_100m_north(self):
        init_reference(TEST_LAT, TEST_LNG)
        geo = local_to_latlng(0.0, 100.0)
        # 100m north should add ~0.000899 degrees latitude
        delta_lat = geo["lat"] - TEST_LAT
        meters = delta_lat * METERS_PER_DEG_LAT
        assert meters == pytest.approx(100.0, abs=0.1)

    @pytest.mark.unit
    def test_100m_east(self):
        init_reference(TEST_LAT, TEST_LNG)
        geo = local_to_latlng(100.0, 0.0)
        # 100m east
        meters_per_deg_lng = METERS_PER_DEG_LAT * math.cos(math.radians(TEST_LAT))
        delta_lng = geo["lng"] - TEST_LNG
        meters = delta_lng * meters_per_deg_lng
        assert meters == pytest.approx(100.0, abs=0.1)

    @pytest.mark.unit
    def test_local_to_latlng_2d(self):
        init_reference(TEST_LAT, TEST_LNG)
        lat, lng = local_to_latlng_2d(50.0, 50.0)
        assert lat > TEST_LAT  # north
        assert lng > TEST_LNG  # east

    @pytest.mark.unit
    def test_uninitialised_returns_zero(self):
        result = local_to_latlng(100.0, 50.0)
        assert result["lat"] == 0.0
        assert result["lng"] == 0.0

    @pytest.mark.unit
    def test_uninitialised_latlng_to_local_returns_zero(self):
        x, y, z = latlng_to_local(TEST_LAT, TEST_LNG)
        assert x == 0.0
        assert y == 0.0


class TestSimTargetGeoIntegration:
    """Test that SimulationTarget.to_dict() includes real coordinates."""

    @pytest.mark.unit
    def test_to_dict_includes_latlng(self):
        init_reference(TEST_LAT, TEST_LNG)

        from amy.simulation.target import SimulationTarget
        target = SimulationTarget(
            target_id="test-1",
            name="Test Rover",
            alliance="friendly",
            asset_type="rover",
            position=(10.0, 20.0),
        )
        d = target.to_dict()
        assert "lat" in d
        assert "lng" in d
        assert "alt" in d
        assert d["position"]["x"] == 10.0
        assert d["position"]["y"] == 20.0
        # lat/lng should be offset from reference
        assert d["lat"] > TEST_LAT  # 20m north
        assert d["lng"] > TEST_LNG  # 10m east

    @pytest.mark.unit
    def test_to_dict_at_origin(self):
        init_reference(TEST_LAT, TEST_LNG)

        from amy.simulation.target import SimulationTarget
        target = SimulationTarget(
            target_id="test-2",
            name="Origin",
            alliance="hostile",
            asset_type="person",
            position=(0.0, 0.0),
        )
        d = target.to_dict()
        assert d["lat"] == pytest.approx(TEST_LAT)
        assert d["lng"] == pytest.approx(TEST_LNG)


class TestTrackedTargetGeoIntegration:
    """Test that TrackedTarget.to_dict() includes real coordinates."""

    @pytest.mark.unit
    def test_to_dict_includes_latlng(self):
        init_reference(TEST_LAT, TEST_LNG)

        from amy.tactical.target_tracker import TrackedTarget
        target = TrackedTarget(
            target_id="track-1",
            name="Tracked Rover",
            alliance="friendly",
            asset_type="rover",
            position=(-5.0, 15.0),
        )
        d = target.to_dict()
        assert "lat" in d
        assert "lng" in d
        assert "alt" in d
        assert d["lat"] > TEST_LAT  # 15m north
        assert d["lng"] < TEST_LNG  # 5m west


class TestLatlngToLocalSpawn:
    """Test spawning targets at real-world lat/lng coordinates."""

    @pytest.mark.unit
    def test_spawn_at_latlng(self):
        init_reference(TEST_LAT, TEST_LNG)

        # A point ~100m north, ~50m east of reference
        target_lat = TEST_LAT + 100.0 / METERS_PER_DEG_LAT
        meters_per_deg_lng = METERS_PER_DEG_LAT * math.cos(math.radians(TEST_LAT))
        target_lng = TEST_LNG + 50.0 / meters_per_deg_lng

        x, y, z = latlng_to_local(target_lat, target_lng)
        assert x == pytest.approx(50.0, abs=0.1)
        assert y == pytest.approx(100.0, abs=0.1)

    @pytest.mark.unit
    def test_spawn_at_negative_offset(self):
        init_reference(TEST_LAT, TEST_LNG)

        # 30m south, 20m west
        target_lat = TEST_LAT - 30.0 / METERS_PER_DEG_LAT
        meters_per_deg_lng = METERS_PER_DEG_LAT * math.cos(math.radians(TEST_LAT))
        target_lng = TEST_LNG - 20.0 / meters_per_deg_lng

        x, y, z = latlng_to_local(target_lat, target_lng)
        assert x == pytest.approx(-20.0, abs=0.1)
        assert y == pytest.approx(-30.0, abs=0.1)
