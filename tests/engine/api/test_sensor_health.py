# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the sensor health API endpoint."""

import pytest
from unittest.mock import MagicMock

from app.routers.sensor_health import _device_health, _camera_health


class TestDeviceHealth:
    """Tests for _device_health helper."""

    def test_offline_is_red(self):
        assert _device_health({"status": "offline"}) == "red"

    def test_online_recent_is_green(self):
        import time
        assert _device_health({"status": "online", "last_seen": time.time() - 10}) == "green"

    def test_stale_is_yellow(self):
        import time
        assert _device_health({"status": "online", "last_seen": time.time() - 90}) == "yellow"

    def test_very_stale_is_red(self):
        import time
        assert _device_health({"status": "online", "last_seen": time.time() - 200}) == "red"

    def test_low_battery_is_yellow(self):
        import time
        assert _device_health({"status": "online", "last_seen": time.time(), "battery_pct": 10}) == "yellow"

    def test_no_last_seen_online_is_green(self):
        assert _device_health({"status": "online"}) == "green"


class TestCameraHealth:
    """Tests for _camera_health helper."""

    def test_enabled_is_green(self):
        assert _camera_health({"enabled": True}) == "green"

    def test_disabled_is_red(self):
        assert _camera_health({"enabled": False}) == "red"

    def test_default_enabled_is_green(self):
        assert _camera_health({}) == "green"
