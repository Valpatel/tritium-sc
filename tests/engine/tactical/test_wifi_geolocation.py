# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for engine.tactical.wifi_geolocation — WiFi BSSID geolocation provider."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engine.tactical.wifi_geolocation import (
    GeoResult,
    WiFiGeolocationProvider,
    register_wifi_geolocation,
)
from engine.tactical.enrichment import EnrichmentPipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider() -> WiFiGeolocationProvider:
    """In-memory provider seeded with stub data."""
    p = WiFiGeolocationProvider(db_path=":memory:")
    yield p
    p.close()


@pytest.fixture
def pipeline() -> EnrichmentPipeline:
    """Enrichment pipeline without EventBus."""
    return EnrichmentPipeline(event_bus=None)


# ---------------------------------------------------------------------------
# GeoResult dataclass
# ---------------------------------------------------------------------------


class TestGeoResult:
    """GeoResult is a simple frozen dataclass."""

    def test_create(self):
        r = GeoResult(lat=37.77, lng=-122.42, accuracy_meters=50.0, source="stub")
        assert r.lat == 37.77
        assert r.lng == -122.42
        assert r.accuracy_meters == 50.0
        assert r.source == "stub"

    def test_frozen(self):
        r = GeoResult(lat=0.0, lng=0.0, accuracy_meters=10.0, source="test")
        with pytest.raises(AttributeError):
            r.lat = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# WiFiGeolocationProvider — query
# ---------------------------------------------------------------------------


class TestProviderQuery:
    """Test BSSID lookup via query()."""

    def test_known_bssid(self, provider: WiFiGeolocationProvider):
        result = provider.query("00:1A:2B:3C:4D:5E")
        assert result is not None
        assert isinstance(result, GeoResult)
        assert abs(result.lat - 37.7749) < 0.001
        assert abs(result.lng - (-122.4194)) < 0.001
        assert result.accuracy_meters == 50.0
        assert result.source == "stub"

    def test_unknown_bssid(self, provider: WiFiGeolocationProvider):
        result = provider.query("FF:FF:FF:FF:FF:FF")
        assert result is None

    def test_empty_bssid(self, provider: WiFiGeolocationProvider):
        assert provider.query("") is None

    def test_invalid_bssid(self, provider: WiFiGeolocationProvider):
        assert provider.query("not-a-mac") is None
        assert provider.query("ZZ:ZZ:ZZ:ZZ:ZZ:ZZ") is None

    def test_bssid_normalization_lowercase(self, provider: WiFiGeolocationProvider):
        """Lowercase input should match uppercase DB entries."""
        result = provider.query("00:1a:2b:3c:4d:5e")
        assert result is not None
        assert abs(result.lat - 37.7749) < 0.001

    def test_bssid_normalization_dashes(self, provider: WiFiGeolocationProvider):
        """Dash-separated input should work."""
        result = provider.query("00-1A-2B-3C-4D-5E")
        assert result is not None

    def test_bssid_normalization_no_separator(self, provider: WiFiGeolocationProvider):
        """12-char hex without separators should work."""
        result = provider.query("001A2B3C4D5E")
        assert result is not None

    def test_stub_count(self, provider: WiFiGeolocationProvider):
        """Stub database should have exactly 50 entries."""
        assert provider.count() == 50

    def test_espressif_bssid(self, provider: WiFiGeolocationProvider):
        """Espressif dev board entry exists."""
        result = provider.query("24:0A:C4:00:01:01")
        assert result is not None
        assert result.source == "stub"

    def test_raspberry_pi_bssid(self, provider: WiFiGeolocationProvider):
        """Raspberry Pi AP entry exists."""
        result = provider.query("B8:27:EB:00:01:01")
        assert result is not None
        assert abs(result.lat - 51.5074) < 0.001  # London

    def test_mobile_hotspot_low_accuracy(self, provider: WiFiGeolocationProvider):
        """Mobile hotspot entries should have high accuracy_meters."""
        result = provider.query("CC:11:22:33:44:01")
        assert result is not None
        assert result.accuracy_meters >= 150.0


# ---------------------------------------------------------------------------
# WiFiGeolocationProvider — insert / persistence
# ---------------------------------------------------------------------------


class TestProviderInsert:
    """Test inserting custom BSSID entries."""

    def test_insert_and_query(self, provider: WiFiGeolocationProvider):
        provider.insert("FE:DC:BA:98:76:54", 48.8566, 2.3522, 15.0, "wigle")
        result = provider.query("FE:DC:BA:98:76:54")
        assert result is not None
        assert abs(result.lat - 48.8566) < 0.001
        assert result.source == "wigle"

    def test_insert_updates_existing(self, provider: WiFiGeolocationProvider):
        """INSERT OR REPLACE should update existing entry."""
        provider.insert("00:1A:2B:3C:4D:5E", 0.0, 0.0, 5.0, "updated")
        result = provider.query("00:1A:2B:3C:4D:5E")
        assert result is not None
        assert result.lat == 0.0
        assert result.source == "updated"

    def test_insert_invalid_bssid_raises(self, provider: WiFiGeolocationProvider):
        with pytest.raises(ValueError, match="Invalid BSSID"):
            provider.insert("bad", 0.0, 0.0, 10.0)

    def test_count_after_insert(self, provider: WiFiGeolocationProvider):
        initial = provider.count()
        provider.insert("FE:DC:BA:98:76:00", 0.0, 0.0, 10.0)
        assert provider.count() == initial + 1

    def test_disk_persistence(self):
        """Data persists when using a file-backed database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Write
            p1 = WiFiGeolocationProvider(db_path=db_path)
            p1.insert("AB:CD:EF:01:23:45", 10.0, 20.0, 30.0, "test")
            p1.close()

            # Read back with new instance
            p2 = WiFiGeolocationProvider(db_path=db_path)
            result = p2.query("AB:CD:EF:01:23:45")
            assert result is not None
            assert result.lat == 10.0
            p2.close()
        finally:
            Path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# WiFiGeolocationProvider — enrichment callback
# ---------------------------------------------------------------------------


class TestProviderEnrich:
    """Test the async enrich() callback used by EnrichmentPipeline."""

    @pytest.mark.asyncio
    async def test_enrich_known_bssid(self, provider: WiFiGeolocationProvider):
        result = await provider.enrich("target1", {"bssid": "00:1A:2B:3C:4D:5E"})
        assert result is not None
        assert result.provider == "wifi_geolocation"
        assert result.enrichment_type == "geolocation"
        assert "lat" in result.data
        assert "lng" in result.data
        assert "accuracy_meters" in result.data
        assert "bssid" in result.data
        assert result.confidence > 0.0

    @pytest.mark.asyncio
    async def test_enrich_unknown_bssid(self, provider: WiFiGeolocationProvider):
        result = await provider.enrich("target2", {"bssid": "FF:FF:FF:FF:FF:FF"})
        assert result is None

    @pytest.mark.asyncio
    async def test_enrich_no_bssid(self, provider: WiFiGeolocationProvider):
        result = await provider.enrich("target3", {"mac": "AA:BB:CC:DD:EE:FF"})
        assert result is None

    @pytest.mark.asyncio
    async def test_enrich_empty_identifiers(self, provider: WiFiGeolocationProvider):
        result = await provider.enrich("target4", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_enrich_high_accuracy_high_confidence(
        self, provider: WiFiGeolocationProvider
    ):
        """Enterprise AP with <25m accuracy should get 0.9 confidence."""
        result = await provider.enrich("target5", {"bssid": "BB:11:22:33:44:02"})
        assert result is not None
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_enrich_low_accuracy_low_confidence(
        self, provider: WiFiGeolocationProvider
    ):
        """Mobile hotspot with >200m accuracy should get 0.3 confidence."""
        result = await provider.enrich("target6", {"bssid": "CC:11:22:33:44:02"})
        assert result is not None
        assert result.confidence == 0.3


# ---------------------------------------------------------------------------
# Confidence mapping
# ---------------------------------------------------------------------------


class TestAccuracyToConfidence:
    """Test the accuracy-to-confidence conversion."""

    def test_very_high_accuracy(self, provider: WiFiGeolocationProvider):
        assert provider._accuracy_to_confidence(10.0) == 0.9

    def test_high_accuracy(self, provider: WiFiGeolocationProvider):
        assert provider._accuracy_to_confidence(25.0) == 0.9

    def test_medium_accuracy(self, provider: WiFiGeolocationProvider):
        assert provider._accuracy_to_confidence(50.0) == 0.8

    def test_low_accuracy(self, provider: WiFiGeolocationProvider):
        assert provider._accuracy_to_confidence(100.0) == 0.7

    def test_poor_accuracy(self, provider: WiFiGeolocationProvider):
        assert provider._accuracy_to_confidence(200.0) == 0.5

    def test_very_poor_accuracy(self, provider: WiFiGeolocationProvider):
        assert provider._accuracy_to_confidence(500.0) == 0.3


# ---------------------------------------------------------------------------
# Pipeline registration
# ---------------------------------------------------------------------------


class TestPipelineRegistration:
    """Test register_wifi_geolocation() helper."""

    def test_register_adds_provider(self, pipeline: EnrichmentPipeline):
        provider = register_wifi_geolocation(pipeline)
        assert "wifi_geolocation" in pipeline.get_provider_names()
        provider.close()

    @pytest.mark.asyncio
    async def test_pipeline_enrich_with_bssid(self, pipeline: EnrichmentPipeline):
        """Full pipeline enrichment should include wifi_geolocation results."""
        provider = register_wifi_geolocation(pipeline)
        try:
            results = await pipeline.enrich("wifi_ap_1", {
                "bssid": "00:1A:2B:3C:4D:5E",
                "mac": "00:1A:2B:3C:4D:5E",
            })
            providers = {r.provider for r in results}
            assert "wifi_geolocation" in providers

            # Find the geo result
            geo = next(r for r in results if r.provider == "wifi_geolocation")
            assert geo.enrichment_type == "geolocation"
            assert abs(geo.data["lat"] - 37.7749) < 0.001
        finally:
            provider.close()

    @pytest.mark.asyncio
    async def test_pipeline_no_bssid_no_geo(self, pipeline: EnrichmentPipeline):
        """Without bssid in identifiers, geo provider returns nothing."""
        provider = register_wifi_geolocation(pipeline)
        try:
            results = await pipeline.enrich("ble_device_1", {
                "mac": "24:0A:C4:12:34:56",
                "name": "ESP32-Test",
            })
            providers = {r.provider for r in results}
            assert "wifi_geolocation" not in providers
        finally:
            provider.close()

    @pytest.mark.asyncio
    async def test_pipeline_caching(self, pipeline: EnrichmentPipeline):
        """Repeated enrichment should return cached results."""
        provider = register_wifi_geolocation(pipeline)
        try:
            r1 = await pipeline.enrich("wifi_cached", {"bssid": "00:1A:2B:3C:4D:5E"})
            r2 = await pipeline.enrich("wifi_cached", {"bssid": "00:1A:2B:3C:4D:5E"})
            assert len(r1) == len(r2)
            geo1 = next(r for r in r1 if r.provider == "wifi_geolocation")
            geo2 = next(r for r in r2 if r.provider == "wifi_geolocation")
            assert geo1.timestamp == geo2.timestamp  # Same cached object
        finally:
            provider.close()
