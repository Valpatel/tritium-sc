# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the weather sensor addon.

All tests run without network access — wttr.in calls are mocked.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tritium_lib.sdk import SensorAddon, AddonInfo
from tritium_lib.sdk.manifest import load_manifest, validate_manifest


# ---------------------------------------------------------------------------
# Manifest tests
# ---------------------------------------------------------------------------

MANIFEST_PATH = Path(__file__).parent.parent / "tritium_addon.toml"


class TestManifest:
    def test_manifest_loads(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.id == "sensor-weather"
        assert m.name == "Weather Station"
        assert m.version == "1.0.0"

    def test_manifest_valid(self):
        m = load_manifest(MANIFEST_PATH)
        errors = validate_manifest(m)
        assert errors == [], f"Manifest errors: {errors}"

    def test_manifest_has_panel(self):
        m = load_manifest(MANIFEST_PATH)
        assert len(m.panels) == 1
        assert m.panels[0]["id"] == "weather-current"

    def test_manifest_category(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.category_window == "sensors"

    def test_manifest_permissions(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.perm_network is True
        assert m.perm_serial is False

    def test_manifest_config_fields(self):
        m = load_manifest(MANIFEST_PATH)
        assert "latitude" in m.config_fields
        assert "longitude" in m.config_fields
        assert "location" in m.config_fields
        assert "poll_interval" in m.config_fields


# ---------------------------------------------------------------------------
# Addon class tests
# ---------------------------------------------------------------------------

SAMPLE_WEATHER = {
    "temp_C": "18",
    "temp_F": "64",
    "FeelsLikeC": "16",
    "humidity": "72",
    "windspeedKmph": "12",
    "winddir16Point": "WSW",
    "weatherDesc": [{"value": "Partly cloudy"}],
    "visibility": "16",
    "pressure": "1015",
    "cloudcover": "50",
    "uvIndex": "3",
}


class TestAddonClass:
    def test_import(self):
        from weather_addon import WeatherAddon
        addon = WeatherAddon()
        assert addon.info.id == "sensor-weather"

    def test_is_sensor(self):
        from weather_addon import WeatherAddon
        assert issubclass(WeatherAddon, SensorAddon)

    def test_get_panels(self):
        from weather_addon import WeatherAddon
        addon = WeatherAddon()
        panels = addon.get_panels()
        assert len(panels) == 1
        assert panels[0]["id"] == "weather-current"

    def test_health_check_not_registered(self):
        from weather_addon import WeatherAddon
        addon = WeatherAddon()
        h = addon.health_check()
        assert h["status"] == "not_registered"


# ---------------------------------------------------------------------------
# Gather tests
# ---------------------------------------------------------------------------

class TestGather:
    def test_gather_empty_before_fetch(self):
        from weather_addon import WeatherAddon
        addon = WeatherAddon()
        result = asyncio.run(addon.gather())
        assert result == []

    def test_gather_returns_target_after_fetch(self):
        from weather_addon import WeatherAddon
        addon = WeatherAddon()
        addon._last_weather = SAMPLE_WEATHER
        addon._last_fetch = time.time()

        result = asyncio.run(addon.gather())
        assert len(result) == 1

        target = result[0]
        assert target["target_id"] == "weather-station"
        assert target["source"] == "weather"
        assert target["asset_type"] == "weather_station"
        assert target["alliance"] == "neutral"
        assert target["lat"] == 37.7749
        assert target["lng"] == -122.4194
        assert target["properties"]["temperature_c"] == "18"
        assert target["properties"]["conditions"] == "Partly cloudy"
        assert target["properties"]["humidity"] == "72"

    def test_gather_target_has_required_fields(self):
        from weather_addon import WeatherAddon
        addon = WeatherAddon()
        addon._last_weather = SAMPLE_WEATHER
        addon._last_fetch = time.time()

        target = asyncio.run(addon.gather())[0]
        required = ["target_id", "source", "lat", "lng", "position"]
        for field in required:
            assert field in target, f"Missing required field: {field}"

    def test_fetch_weather_sync_parses_json(self):
        """Test that fetch_weather_sync correctly parses a wttr.in response."""
        from weather_addon import WeatherAddon
        import json

        addon = WeatherAddon()
        fake_response = json.dumps({
            "current_condition": [SAMPLE_WEATHER],
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("weather_addon.urlopen", return_value=mock_resp):
            result = addon.fetch_weather_sync("TestCity")
            assert result is not None
            assert result["temp_C"] == "18"
            assert result["weatherDesc"][0]["value"] == "Partly cloudy"

    def test_fetch_weather_sync_handles_error(self):
        """Test that fetch errors return None instead of raising."""
        from weather_addon import WeatherAddon
        from urllib.error import URLError

        addon = WeatherAddon()
        with patch("weather_addon.urlopen", side_effect=URLError("timeout")):
            result = addon.fetch_weather_sync("BadCity")
            assert result is None


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_degraded_no_data(self):
        from weather_addon import WeatherAddon
        addon = WeatherAddon()
        addon._registered = True
        h = addon.health_check()
        assert h["status"] == "degraded"

    def test_health_ok_with_fresh_data(self):
        from weather_addon import WeatherAddon
        addon = WeatherAddon()
        addon._registered = True
        addon._last_weather = SAMPLE_WEATHER
        addon._last_fetch = time.time()
        h = addon.health_check()
        assert h["status"] == "ok"

    def test_health_degraded_stale_data(self):
        from weather_addon import WeatherAddon
        addon = WeatherAddon()
        addon._registered = True
        addon._last_weather = SAMPLE_WEATHER
        addon._last_fetch = time.time() - 2000  # very old
        addon._poll_interval = 300
        h = addon.health_check()
        assert h["status"] == "degraded"
        assert "Stale" in h["detail"]
