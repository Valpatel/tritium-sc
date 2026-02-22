"""Unit tests for app/config.py — Settings validation, defaults, env parsing.

Tests Pydantic settings model: default values, type coercion, and
environment variable override behavior.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Settings


@pytest.mark.unit
class TestSettingsDefaults:
    """Default values without any environment variables."""

    def test_app_name(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.app_name == "TRITIUM"

    def test_debug_default_false(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.debug is False

    def test_database_url(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert "sqlite" in s.database_url

    def test_host_and_port(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.host == "0.0.0.0"
            assert s.port == 8000

    def test_mqtt_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.mqtt_enabled is True
            assert s.mqtt_host == "localhost"
            assert s.mqtt_port == 1883
            assert s.mqtt_site_id == "home"

    def test_influx_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.influx_enabled is True
            assert s.influx_url == "http://localhost:8086"
            assert s.influx_org == "tritium"
            assert s.influx_bucket == "telemetry"

    def test_simulation_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.simulation_enabled is True
            assert s.simulation_mode == "sim"

    def test_amy_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.amy_enabled is True
            assert s.amy_wake_word == "amy"
            assert s.amy_think_interval == 8.0

    def test_detection_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.detection_confidence == 0.5
            assert s.motion_threshold == 25.0

    def test_map_center_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.map_center_lat == 37.7749
            assert s.map_center_lng == -122.4194
            assert s.map_center_alt == 16.0


@pytest.mark.unit
class TestSettingsEnvOverride:
    """Environment variable overrides."""

    def test_debug_from_env(self):
        with patch.dict(os.environ, {"DEBUG": "true"}, clear=True):
            s = Settings(_env_file=None)
            assert s.debug is True

    def test_port_from_env(self):
        with patch.dict(os.environ, {"PORT": "9000"}, clear=True):
            s = Settings(_env_file=None)
            assert s.port == 9000

    def test_mqtt_enabled_from_env(self):
        with patch.dict(os.environ, {"MQTT_ENABLED": "true"}, clear=True):
            s = Settings(_env_file=None)
            assert s.mqtt_enabled is True

    def test_mqtt_host_from_env(self):
        with patch.dict(os.environ, {"MQTT_HOST": "broker.example.com"}, clear=True):
            s = Settings(_env_file=None)
            assert s.mqtt_host == "broker.example.com"

    def test_amy_disabled_from_env(self):
        with patch.dict(os.environ, {"AMY_ENABLED": "false"}, clear=True):
            s = Settings(_env_file=None)
            assert s.amy_enabled is False

    def test_simulation_disabled_from_env(self):
        with patch.dict(os.environ, {"SIMULATION_ENABLED": "false"}, clear=True):
            s = Settings(_env_file=None)
            assert s.simulation_enabled is False

    def test_case_insensitive(self):
        with patch.dict(os.environ, {"debug": "true"}, clear=True):
            s = Settings(_env_file=None)
            assert s.debug is True

    def test_map_center_from_env(self):
        with patch.dict(os.environ, {
            "MAP_CENTER_LAT": "37.7749",
            "MAP_CENTER_LNG": "-122.4194",
        }, clear=True):
            s = Settings(_env_file=None)
            assert abs(s.map_center_lat - 37.7749) < 0.001
            assert abs(s.map_center_lng - (-122.4194)) < 0.001

    def test_think_interval_from_env(self):
        with patch.dict(os.environ, {"AMY_THINK_INTERVAL": "4.5"}, clear=True):
            s = Settings(_env_file=None)
            assert s.amy_think_interval == 4.5


@pytest.mark.unit
class TestSettingsTypes:
    """Type coercion and validation."""

    def test_recordings_path_is_path(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert isinstance(s.recordings_path, Path)

    def test_extra_fields_ignored(self):
        """Extra environment variables should not cause errors."""
        with patch.dict(os.environ, {
            "RANDOM_EXTRA_VAR": "ignored",
            "ANOTHER_UNKNOWN": "also_ignored",
        }, clear=True):
            s = Settings(_env_file=None)
            assert s.app_name == "TRITIUM"

    def test_nvr_optional(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.nvr_host is None
            assert s.nvr_user is None
            assert s.nvr_pass is None

    def test_nvr_port_default(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.nvr_port == 443

    def test_amy_camera_device_optional(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.amy_camera_device is None
