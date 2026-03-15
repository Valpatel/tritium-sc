# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Amy Commander plugin shell."""

import pytest

from engine.plugins.base import PluginInterface


@pytest.mark.unit
class TestAmyCommanderPlugin:
    """Verify Amy Commander plugin interface and wrapper behavior."""

    def test_implements_plugin_interface(self):
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        assert isinstance(plugin, PluginInterface)

    def test_plugin_identity(self):
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        assert plugin.plugin_id == "tritium.amy-commander"
        assert plugin.name == "Amy AI Commander"
        assert plugin.version == "1.0.0"

    def test_capabilities(self):
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        caps = plugin.capabilities
        assert "ai" in caps
        assert "routes" in caps
        assert "ui" in caps
        assert "background" in caps

    def test_not_healthy_when_stopped(self):
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        assert plugin.healthy is False

    def test_healthy_when_running(self):
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        plugin._running = True
        assert plugin.healthy is True

    def test_start_marks_running(self):
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        plugin.start()
        assert plugin._running is True

    def test_stop_marks_not_running(self):
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        plugin.start()
        plugin.stop()
        assert plugin._running is False

    def test_get_status_no_amy(self):
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        status = plugin.get_status()
        assert status["status"] == "not_initialized"
        assert status["running"] is False

    def test_amy_accessor_returns_none(self):
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        assert plugin.amy is None

    def test_loader_exports_class(self):
        from plugins.amy_loader import AmyCommanderPlugin as Loaded
        assert Loaded is not None
        plugin = Loaded()
        assert plugin.plugin_id == "tritium.amy-commander"
