# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Meshtastic bridge plugin."""

import pytest

from engine.plugins.base import PluginInterface


@pytest.mark.unit
class TestMeshtasticPlugin:
    """Verify Meshtastic plugin interface and configuration."""

    def test_implements_plugin_interface(self):
        from plugins.meshtastic.plugin import MeshtasticPlugin
        plugin = MeshtasticPlugin()
        assert isinstance(plugin, PluginInterface)

    def test_plugin_identity(self):
        from plugins.meshtastic.plugin import MeshtasticPlugin
        plugin = MeshtasticPlugin()
        assert plugin.plugin_id == "tritium.meshtastic"
        assert plugin.name == "Meshtastic Bridge"
        assert plugin.version == "0.1.0"

    def test_capabilities(self):
        from plugins.meshtastic.plugin import MeshtasticPlugin
        plugin = MeshtasticPlugin()
        caps = plugin.capabilities
        assert "bridge" in caps
        assert "data_source" in caps
        assert "routes" in caps

    def test_default_config(self):
        from plugins.meshtastic.plugin import MeshtasticConfig
        config = MeshtasticConfig()
        assert config.connection_type == "serial"
        assert config.enabled is False
        assert config.poll_interval == 5.0

    def test_disabled_start_is_healthy(self):
        from plugins.meshtastic.plugin import MeshtasticPlugin
        plugin = MeshtasticPlugin()
        plugin._config.enabled = False
        plugin._running = True
        plugin.start()
        assert plugin.healthy is True

    def test_send_text_without_radio_returns_false(self):
        from plugins.meshtastic.plugin import MeshtasticPlugin
        plugin = MeshtasticPlugin()
        plugin._logger = __import__("logging").getLogger("test")
        assert plugin.send_text("hello") is False

    def test_send_waypoint_without_radio_returns_false(self):
        from plugins.meshtastic.plugin import MeshtasticPlugin
        plugin = MeshtasticPlugin()
        assert plugin.send_waypoint(37.0, -122.0, "Base") is False

    def test_nodes_start_empty(self):
        from plugins.meshtastic.plugin import MeshtasticPlugin
        plugin = MeshtasticPlugin()
        assert plugin._nodes == {}
