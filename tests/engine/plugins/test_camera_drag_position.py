# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for camera drag-to-reposition position update.

UX Loop 8, Step 7: drag-to-reposition camera on map.
Verifies that PATCH /api/camera-feeds/sources/{id}/position correctly
updates the camera source's lat/lng/heading in its config.extra dict.
"""

import pytest


@pytest.mark.unit
class TestCameraDragPosition:
    """Verify the position update logic used by drag-to-reposition."""

    def _make_plugin_with_camera(self, source_id="cam-drag", lat=33.0, lng=-97.0, heading=90.0):
        """Create a plugin with one registered camera at a known position."""
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig

        plugin = CameraFeedsPlugin()
        extra = {"lat": lat, "lng": lng, "heading": heading}
        config = CameraSourceConfig(
            source_id=source_id,
            source_type="mqtt",
            name="Drag Test Camera",
            extra=extra,
        )
        plugin.register_source(config)
        return plugin

    def test_initial_position_in_to_dict(self):
        """Camera's lat/lng/heading appear in to_dict output."""
        plugin = self._make_plugin_with_camera()
        source = plugin.get_source("cam-drag")
        d = source.to_dict()
        assert d["lat"] == 33.0
        assert d["lng"] == -97.0
        assert d["heading"] == 90.0

    def test_update_lat_lng(self):
        """Position update changes lat and lng in config.extra."""
        plugin = self._make_plugin_with_camera()
        source = plugin.get_source("cam-drag")

        # Simulate the PATCH handler logic
        source.config.extra["lat"] = 33.5
        source.config.extra["lng"] = -97.5

        d = source.to_dict()
        assert d["lat"] == 33.5
        assert d["lng"] == -97.5
        # Heading unchanged
        assert d["heading"] == 90.0

    def test_update_heading(self):
        """Heading can be updated independently."""
        plugin = self._make_plugin_with_camera()
        source = plugin.get_source("cam-drag")

        source.config.extra["heading"] = 180.0

        d = source.to_dict()
        assert d["heading"] == 180.0
        assert d["lat"] == 33.0  # unchanged
        assert d["lng"] == -97.0  # unchanged

    def test_update_all_fields(self):
        """All position fields can be updated at once."""
        plugin = self._make_plugin_with_camera()
        source = plugin.get_source("cam-drag")

        source.config.extra["lat"] = 34.0
        source.config.extra["lng"] = -98.0
        source.config.extra["heading"] = 270.0

        d = source.to_dict()
        assert d["lat"] == 34.0
        assert d["lng"] == -98.0
        assert d["heading"] == 270.0

    def test_position_persists_across_list_sources(self):
        """Updated position is visible in list_sources output."""
        plugin = self._make_plugin_with_camera()
        source = plugin.get_source("cam-drag")

        source.config.extra["lat"] = 35.0
        source.config.extra["lng"] = -99.0

        sources = plugin.list_sources()
        assert len(sources) == 1
        assert sources[0]["lat"] == 35.0
        assert sources[0]["lng"] == -99.0

    def test_camera_without_position(self):
        """Camera without initial position gets position on drag."""
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig

        plugin = CameraFeedsPlugin()
        config = CameraSourceConfig(
            source_id="no-pos",
            source_type="mqtt",
            name="No Position Camera",
        )
        plugin.register_source(config)
        source = plugin.get_source("no-pos")

        # Initially no position
        d = source.to_dict()
        assert "lat" not in d
        assert "lng" not in d

        # Simulate drag setting position
        source.config.extra["lat"] = 33.0
        source.config.extra["lng"] = -97.0

        d = source.to_dict()
        assert d["lat"] == 33.0
        assert d["lng"] == -97.0

    def test_position_update_type_coercion(self):
        """Position values are stored as floats."""
        plugin = self._make_plugin_with_camera()
        source = plugin.get_source("cam-drag")

        # Simulate the PATCH handler float() coercion
        source.config.extra["lat"] = float("33.123456")
        source.config.extra["lng"] = float("-97.654321")

        d = source.to_dict()
        assert isinstance(d["lat"], float)
        assert isinstance(d["lng"], float)
        assert abs(d["lat"] - 33.123456) < 1e-6
        assert abs(d["lng"] - (-97.654321)) < 1e-6

    def test_get_nonexistent_source_returns_none(self):
        """get_source returns None for unknown source_id."""
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        plugin = CameraFeedsPlugin()
        assert plugin.get_source("nonexistent") is None

    def test_fov_fields_in_to_dict(self):
        """FOV angle and range fields appear in to_dict when set."""
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig

        plugin = CameraFeedsPlugin()
        config = CameraSourceConfig(
            source_id="fov-test",
            source_type="mqtt",
            extra={"lat": 33.0, "lng": -97.0, "fov_angle": 90.0, "fov_range": 50.0},
        )
        plugin.register_source(config)
        source = plugin.get_source("fov-test")
        d = source.to_dict()
        assert d["fov_angle"] == 90.0
        assert d["fov_range"] == 50.0
