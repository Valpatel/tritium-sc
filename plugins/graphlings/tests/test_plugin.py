# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GraphlingsPlugin — TDD: written before implementation."""
from __future__ import annotations

import logging
import os
import time
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_context():
    """Create a mock PluginContext matching tritium-sc's PluginContext shape."""
    ctx = MagicMock()
    ctx.event_bus = MagicMock()
    ctx.event_bus.subscribe.return_value = MagicMock()  # queue-like
    ctx.target_tracker = MagicMock()
    ctx.simulation_engine = MagicMock()
    ctx.app = MagicMock()
    ctx.logger = logging.getLogger("test.graphlings")
    ctx.plugin_manager = MagicMock()
    ctx.settings = {}
    return ctx


# ── Identity ──────────────────────────────────────────────────────


class TestPluginIdentity:
    """Plugin exposes correct PluginInterface identity properties."""

    def test_plugin_id(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        assert p.plugin_id == "com.graphlings.agent"

    def test_name(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        assert p.name == "Graphlings Agent Bridge"

    def test_version_semver(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        parts = p.version.split(".")
        assert len(parts) == 3, "version must be semver (x.y.z)"
        assert all(part.isdigit() for part in parts)

    def test_capabilities(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        expected = {"ai", "data_source", "routes", "background"}
        assert p.capabilities == expected


# ── Configuration ────────────────────────────────────────────────


class TestPluginConfigure:
    """Plugin stores references from PluginContext during configure()."""

    def test_stores_event_bus(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        assert p._event_bus is ctx.event_bus

    def test_stores_tracker(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        assert p._tracker is ctx.target_tracker

    def test_stores_engine(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        assert p._engine is ctx.simulation_engine

    def test_registers_routes(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        # app.get should have been called to register /api/graphlings/status
        ctx.app.get.assert_called()


# ── Lifecycle ────────────────────────────────────────────────────


class TestPluginLifecycle:
    """Plugin starts and stops cleanly."""

    def test_start_sets_running(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        p.start()
        try:
            assert p._running is True
            assert p._agent_thread is not None
        finally:
            p.stop()

    def test_stop_clears_running(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        p.start()
        p.stop()
        assert p._running is False

    def test_double_start_is_idempotent(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        p.start()
        thread1 = p._agent_thread
        p.start()  # should not create a second thread
        assert p._agent_thread is thread1
        p.stop()

    def test_stop_without_start_is_safe(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        # Should not raise
        p.stop()

    def test_healthy_before_start(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        # Not started yet, no thread — healthy is True (no failure)
        assert p.healthy is True

    def test_healthy_while_running(self):
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        p.start()
        try:
            assert p.healthy is True
        finally:
            p.stop()

    def test_handles_missing_server_gracefully(self):
        """Plugin starts even if Graphling server is unreachable."""
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        # Should not raise even if server is down
        p.start()
        p.stop()

    def test_stop_recalls_deployed_agents(self):
        """Stop recalls all deployed graphlings."""
        from graphlings.plugin import GraphlingsPlugin

        p = GraphlingsPlugin()
        ctx = _make_mock_context()
        p.configure(ctx)
        p.start()
        # Simulate deployed agents
        p._deployed["soul-1"] = "target-1"
        p._deployed["soul-2"] = "target-2"
        p.stop()
        assert len(p._deployed) == 0


# ── Config ───────────────────────────────────────────────────────


class TestGraphlingsConfig:
    """GraphlingsConfig defaults and environment overrides."""

    def test_defaults(self):
        from graphlings.config import GraphlingsConfig

        cfg = GraphlingsConfig()
        assert cfg.max_agents == 5
        assert cfg.think_interval_seconds == 3.0
        assert cfg.perception_radius == 50.0
        assert cfg.default_context == "npc_game"
        assert cfg.default_service_name == "tritium-sc"
        assert cfg.default_consciousness_min == 2
        assert cfg.default_consciousness_max == 5

    def test_server_url_default(self):
        from graphlings.config import GraphlingsConfig

        cfg = GraphlingsConfig()
        assert "100.93.184.1" in cfg.server_url
        assert "4774" in cfg.server_url

    def test_spawn_points(self):
        from graphlings.config import GraphlingsConfig

        cfg = GraphlingsConfig()
        assert "marketplace" in cfg.spawn_points
        assert "watchtower" in cfg.spawn_points
        assert "tavern" in cfg.spawn_points

    def test_from_env_overrides_server_url(self):
        from graphlings.config import GraphlingsConfig

        with patch.dict(os.environ, {"GRAPHLINGS_SERVER_URL": "http://localhost:9999"}):
            cfg = GraphlingsConfig.from_env()
            assert cfg.server_url == "http://localhost:9999"

    def test_from_env_overrides_max_agents(self):
        from graphlings.config import GraphlingsConfig

        with patch.dict(os.environ, {"GRAPHLINGS_MAX_AGENTS": "10"}):
            cfg = GraphlingsConfig.from_env()
            assert cfg.max_agents == 10

    def test_from_env_overrides_timeout(self):
        from graphlings.config import GraphlingsConfig

        with patch.dict(os.environ, {"GRAPHLINGS_SERVER_TIMEOUT": "10.0"}):
            cfg = GraphlingsConfig.from_env()
            assert cfg.server_timeout == 10.0

    def test_from_env_overrides_think_interval(self):
        from graphlings.config import GraphlingsConfig

        with patch.dict(os.environ, {"GRAPHLINGS_THINK_INTERVAL": "5.0"}):
            cfg = GraphlingsConfig.from_env()
            assert cfg.think_interval_seconds == 5.0

    def test_from_env_overrides_perception_radius(self):
        from graphlings.config import GraphlingsConfig

        with patch.dict(os.environ, {"GRAPHLINGS_PERCEPTION_RADIUS": "100.0"}):
            cfg = GraphlingsConfig.from_env()
            assert cfg.perception_radius == 100.0


# ── Discovery ────────────────────────────────────────────────────


class TestPluginDiscovery:
    """Plugin is discoverable by PluginManager."""

    def test_package_exports_plugin_class(self):
        """graphlings package exports GraphlingsPlugin."""
        from graphlings import GraphlingsPlugin

        p = GraphlingsPlugin()
        assert p.plugin_id == "com.graphlings.agent"

    def test_is_subclass_of_plugin_interface(self):
        """GraphlingsPlugin extends PluginInterface."""
        from engine.plugins.base import PluginInterface
        from graphlings.plugin import GraphlingsPlugin

        assert issubclass(GraphlingsPlugin, PluginInterface)

    def test_not_abstract(self):
        """GraphlingsPlugin can be instantiated (all abstract methods implemented)."""
        from graphlings.plugin import GraphlingsPlugin

        # Should not raise
        p = GraphlingsPlugin()
        assert p is not None

    def test_plugin_manager_discovers_via_loader(self):
        """PluginManager finds GraphlingsPlugin via graphlings_loader.py."""
        from pathlib import Path

        from engine.plugins.manager import PluginManager

        mgr = PluginManager()
        plugins_dir = str(Path(__file__).resolve().parent.parent.parent)
        found = mgr.discover(paths=[plugins_dir])

        plugin_ids = [p.plugin_id for p in found]
        assert "com.graphlings.agent" in plugin_ids
