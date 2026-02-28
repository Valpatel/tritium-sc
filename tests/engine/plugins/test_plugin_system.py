# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the TRITIUM-SC plugin system.

TDD: These tests are written BEFORE the implementation.
Run them, watch them fail, then implement.
"""

import pytest
import threading
import time
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Test PluginInterface
# ---------------------------------------------------------------------------

class TestPluginInterface:
    """Test the abstract base class for plugins."""

    def test_cannot_instantiate_abstract(self):
        """PluginInterface is abstract — cannot be instantiated directly."""
        from engine.plugins.base import PluginInterface
        with pytest.raises(TypeError):
            PluginInterface()

    def test_concrete_plugin_requires_plugin_id(self):
        """Concrete plugins must define plugin_id."""
        from engine.plugins.base import PluginInterface

        class BadPlugin(PluginInterface):
            name = "Bad"
            version = "0.1.0"
            def start(self): pass
            def stop(self): pass

        with pytest.raises(TypeError):
            BadPlugin()

    def test_concrete_plugin_requires_name(self):
        """Concrete plugins must define name."""
        from engine.plugins.base import PluginInterface

        class BadPlugin(PluginInterface):
            plugin_id = "test.bad"
            version = "0.1.0"
            def start(self): pass
            def stop(self): pass

        with pytest.raises(TypeError):
            BadPlugin()

    def test_concrete_plugin_requires_version(self):
        """Concrete plugins must define version."""
        from engine.plugins.base import PluginInterface

        class BadPlugin(PluginInterface):
            plugin_id = "test.bad"
            name = "Bad"
            def start(self): pass
            def stop(self): pass

        with pytest.raises(TypeError):
            BadPlugin()

    def test_concrete_plugin_requires_start(self):
        """Concrete plugins must implement start()."""
        from engine.plugins.base import PluginInterface

        class BadPlugin(PluginInterface):
            plugin_id = "test.bad"
            name = "Bad"
            version = "0.1.0"
            def stop(self): pass

        with pytest.raises(TypeError):
            BadPlugin()

    def test_concrete_plugin_requires_stop(self):
        """Concrete plugins must implement stop()."""
        from engine.plugins.base import PluginInterface

        class BadPlugin(PluginInterface):
            plugin_id = "test.bad"
            name = "Bad"
            version = "0.1.0"
            def start(self): pass

        with pytest.raises(TypeError):
            BadPlugin()

    def test_valid_concrete_plugin(self):
        """A properly defined plugin can be instantiated."""
        from engine.plugins.base import PluginInterface

        class GoodPlugin(PluginInterface):
            plugin_id = "test.good"
            name = "Good Plugin"
            version = "1.0.0"
            def start(self): pass
            def stop(self): pass

        p = GoodPlugin()
        assert p.plugin_id == "test.good"
        assert p.name == "Good Plugin"
        assert p.version == "1.0.0"

    def test_default_capabilities_empty(self):
        """Default capabilities is an empty set."""
        from engine.plugins.base import PluginInterface

        class MinPlugin(PluginInterface):
            plugin_id = "test.min"
            name = "Min"
            version = "0.1.0"
            def start(self): pass
            def stop(self): pass

        p = MinPlugin()
        assert p.capabilities == set()

    def test_custom_capabilities(self):
        """Plugins can declare capabilities."""
        from engine.plugins.base import PluginInterface

        class BridgePlugin(PluginInterface):
            plugin_id = "test.bridge"
            name = "Bridge"
            version = "0.1.0"
            capabilities = {"bridge", "background"}
            def start(self): pass
            def stop(self): pass

        p = BridgePlugin()
        assert "bridge" in p.capabilities
        assert "background" in p.capabilities

    def test_default_dependencies_empty(self):
        """Default dependencies is an empty list."""
        from engine.plugins.base import PluginInterface

        class MinPlugin(PluginInterface):
            plugin_id = "test.min"
            name = "Min"
            version = "0.1.0"
            def start(self): pass
            def stop(self): pass

        p = MinPlugin()
        assert p.dependencies == []

    def test_default_healthy_true(self):
        """Default health check returns True."""
        from engine.plugins.base import PluginInterface

        class MinPlugin(PluginInterface):
            plugin_id = "test.min"
            name = "Min"
            version = "0.1.0"
            def start(self): pass
            def stop(self): pass

        p = MinPlugin()
        assert p.healthy is True

    def test_configure_is_optional(self):
        """configure() has a default no-op implementation."""
        from engine.plugins.base import PluginInterface, PluginContext

        class MinPlugin(PluginInterface):
            plugin_id = "test.min"
            name = "Min"
            version = "0.1.0"
            def start(self): pass
            def stop(self): pass

        p = MinPlugin()
        ctx = MagicMock(spec=PluginContext)
        p.configure(ctx)  # Should not raise


# ---------------------------------------------------------------------------
# Test PluginContext
# ---------------------------------------------------------------------------

class TestPluginContext:
    """Test the context object passed to plugins."""

    def test_context_has_event_bus(self):
        from engine.plugins.base import PluginContext
        ctx = PluginContext(
            event_bus=MagicMock(),
            target_tracker=MagicMock(),
            simulation_engine=None,
            settings={},
            app=None,
            logger=MagicMock(),
            plugin_manager=MagicMock(),
        )
        assert ctx.event_bus is not None

    def test_context_settings_dict(self):
        from engine.plugins.base import PluginContext
        ctx = PluginContext(
            event_bus=MagicMock(),
            target_tracker=MagicMock(),
            simulation_engine=None,
            settings={"api_url": "http://localhost:4774"},
            app=None,
            logger=MagicMock(),
            plugin_manager=MagicMock(),
        )
        assert ctx.settings["api_url"] == "http://localhost:4774"

    def test_context_simulation_engine_optional(self):
        from engine.plugins.base import PluginContext
        ctx = PluginContext(
            event_bus=MagicMock(),
            target_tracker=MagicMock(),
            simulation_engine=None,
            settings={},
            app=None,
            logger=MagicMock(),
            plugin_manager=MagicMock(),
        )
        assert ctx.simulation_engine is None


# ---------------------------------------------------------------------------
# Test PluginManager
# ---------------------------------------------------------------------------

def _make_plugin(plugin_id="test.p1", name="P1", version="1.0.0",
                 capabilities=None, dependencies=None):
    """Helper to create a test plugin instance."""
    from engine.plugins.base import PluginInterface

    _pid = plugin_id
    _name = name
    _ver = version
    _caps = capabilities or set()
    _deps = dependencies or []

    class TestPlugin(PluginInterface):
        @property
        def plugin_id(self):
            return _pid

        @property
        def name(self):
            return _name

        @property
        def version(self):
            return _ver

        @property
        def capabilities(self):
            return _caps

        @property
        def dependencies(self):
            return _deps

        def start(self):
            pass

        def stop(self):
            pass

    return TestPlugin()


class TestPluginManager:
    """Test the plugin manager lifecycle."""

    def test_register_plugin(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        p = _make_plugin("test.a", "A")
        mgr.register(p)
        assert mgr.get_plugin("test.a") is p

    def test_register_duplicate_raises(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        p1 = _make_plugin("test.dup", "Dup1")
        p2 = _make_plugin("test.dup", "Dup2")
        mgr.register(p1)
        with pytest.raises(ValueError, match="already registered"):
            mgr.register(p2)

    def test_get_plugin_not_found(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        assert mgr.get_plugin("nonexistent") is None

    def test_list_plugins_empty(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        assert mgr.list_plugins() == []

    def test_list_plugins_returns_info(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        mgr.register(_make_plugin("test.a", "Alpha", "1.2.3",
                                   capabilities={"bridge"}))
        plugins = mgr.list_plugins()
        assert len(plugins) == 1
        info = plugins[0]
        assert info["id"] == "test.a"
        assert info["name"] == "Alpha"
        assert info["version"] == "1.2.3"
        assert "bridge" in info["capabilities"]

    def test_configure_all_calls_configure(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        p = _make_plugin("test.a")
        p.configure = MagicMock()
        mgr.register(p)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        p.configure.assert_called_once_with(ctx)

    def test_start_all_calls_start(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        p = _make_plugin("test.a")
        p.start = MagicMock()
        mgr.register(p)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        results = mgr.start_all()
        p.start.assert_called_once()
        assert results["test.a"] is True

    def test_stop_all_calls_stop(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        p = _make_plugin("test.a")
        p.stop = MagicMock()
        mgr.register(p)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()
        mgr.stop_all()
        p.stop.assert_called_once()

    def test_start_failure_isolated(self):
        """A plugin that fails to start doesn't crash the manager."""
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()

        p_bad = _make_plugin("test.bad", "Bad")
        p_bad.start = MagicMock(side_effect=RuntimeError("boom"))
        p_good = _make_plugin("test.good", "Good")
        p_good.start = MagicMock()

        mgr.register(p_bad)
        mgr.register(p_good)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        results = mgr.start_all()

        assert results["test.bad"] is False
        assert results["test.good"] is True
        p_good.start.assert_called_once()

    def test_configure_failure_isolated(self):
        """A plugin that fails to configure doesn't crash the manager."""
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()

        p = _make_plugin("test.bad", "Bad")
        p.configure = MagicMock(side_effect=RuntimeError("bad config"))
        mgr.register(p)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        # Plugin should be marked as failed, won't start
        results = mgr.start_all()
        assert results["test.bad"] is False

    def test_stop_failure_isolated(self):
        """A plugin that fails to stop doesn't crash the manager."""
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()

        p = _make_plugin("test.bad", "Bad")
        p.stop = MagicMock(side_effect=RuntimeError("stop failed"))
        mgr.register(p)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()
        # Should not raise
        mgr.stop_all()

    def test_health_check(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()

        p = _make_plugin("test.a")
        mgr.register(p)
        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()

        health = mgr.health_check()
        assert health["test.a"] is True

    def test_health_check_unhealthy_plugin(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()

        p = _make_plugin("test.sick")
        type(p).healthy = property(lambda self: False)
        mgr.register(p)
        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()

        health = mgr.health_check()
        assert health["test.sick"] is False


# ---------------------------------------------------------------------------
# Test Dependency Resolution
# ---------------------------------------------------------------------------

class TestDependencyResolution:
    """Test topological sort and dependency handling."""

    def test_no_dependencies_start_order(self):
        """Plugins with no deps start in registration order."""
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        order = []

        p1 = _make_plugin("test.a")
        p1.start = lambda: order.append("a")
        p2 = _make_plugin("test.b")
        p2.start = lambda: order.append("b")

        mgr.register(p1)
        mgr.register(p2)
        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()

        assert order == ["a", "b"]

    def test_dependency_order(self):
        """Plugins start after their dependencies."""
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        order = []

        p_base = _make_plugin("test.base")
        p_base.start = lambda: order.append("base")
        p_dep = _make_plugin("test.dep", dependencies=["test.base"])
        p_dep.start = lambda: order.append("dep")

        # Register in reverse order to test resolution
        mgr.register(p_dep)
        mgr.register(p_base)
        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()

        assert order.index("base") < order.index("dep")

    def test_stop_reverse_dependency_order(self):
        """Plugins stop in reverse dependency order."""
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        order = []

        p_base = _make_plugin("test.base")
        p_base.stop = lambda: order.append("base")
        p_dep = _make_plugin("test.dep", dependencies=["test.base"])
        p_dep.stop = lambda: order.append("dep")

        mgr.register(p_base)
        mgr.register(p_dep)
        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()
        mgr.stop_all()

        assert order.index("dep") < order.index("base")

    def test_circular_dependency_raises(self):
        """Circular dependencies raise PluginDependencyError."""
        from engine.plugins.manager import PluginManager, PluginDependencyError
        mgr = PluginManager()

        p1 = _make_plugin("test.a", dependencies=["test.b"])
        p2 = _make_plugin("test.b", dependencies=["test.a"])

        mgr.register(p1)
        mgr.register(p2)

        ctx = MagicMock()
        with pytest.raises(PluginDependencyError, match="[Cc]ircular"):
            mgr.configure_all(lambda pid: ctx)

    def test_missing_dependency_skips_plugin(self):
        """A plugin with a missing dependency is skipped (not crashed)."""
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()

        p = _make_plugin("test.needs", dependencies=["test.missing"])
        p.start = MagicMock()
        mgr.register(p)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        results = mgr.start_all()

        assert results["test.needs"] is False
        p.start.assert_not_called()

    def test_transitive_dependency(self):
        """A -> B -> C: all start in correct order."""
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        order = []

        p_c = _make_plugin("test.c")
        p_c.start = lambda: order.append("c")
        p_b = _make_plugin("test.b", dependencies=["test.c"])
        p_b.start = lambda: order.append("b")
        p_a = _make_plugin("test.a", dependencies=["test.b"])
        p_a.start = lambda: order.append("a")

        # Register in reverse order
        mgr.register(p_a)
        mgr.register(p_b)
        mgr.register(p_c)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()

        assert order == ["c", "b", "a"]

    def test_failed_dependency_cascades(self):
        """If a dependency fails to start, dependents are skipped."""
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()

        p_base = _make_plugin("test.base")
        p_base.start = MagicMock(side_effect=RuntimeError("broken"))
        p_dep = _make_plugin("test.dep", dependencies=["test.base"])
        p_dep.start = MagicMock()

        mgr.register(p_base)
        mgr.register(p_dep)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        results = mgr.start_all()

        assert results["test.base"] is False
        assert results["test.dep"] is False
        p_dep.start.assert_not_called()


# ---------------------------------------------------------------------------
# Test Discovery
# ---------------------------------------------------------------------------

class TestPluginDiscovery:
    """Test plugin discovery from directories and entry points."""

    def test_discover_from_directory(self, tmp_path):
        """Discover plugins from a directory of Python files."""
        from engine.plugins.manager import PluginManager

        # Write a simple plugin file
        plugin_file = tmp_path / "my_plugin.py"
        plugin_file.write_text("""
from engine.plugins.base import PluginInterface

class MyTestPlugin(PluginInterface):
    plugin_id = "test.discovered"
    name = "Discovered"
    version = "0.1.0"
    def start(self): pass
    def stop(self): pass
""")

        mgr = PluginManager()
        found = mgr.discover(paths=[str(tmp_path)])
        ids = [p.plugin_id for p in found]
        assert "test.discovered" in ids

    def test_discover_skips_invalid_files(self, tmp_path):
        """Discovery skips files that don't define valid plugins."""
        from engine.plugins.manager import PluginManager

        bad_file = tmp_path / "not_a_plugin.py"
        bad_file.write_text("x = 42\n")

        mgr = PluginManager()
        found = mgr.discover(paths=[str(tmp_path)])
        assert len(found) == 0

    def test_discover_skips_syntax_errors(self, tmp_path):
        """Discovery skips files with syntax errors."""
        from engine.plugins.manager import PluginManager

        bad_file = tmp_path / "broken.py"
        bad_file.write_text("def incomplete(:\n")

        mgr = PluginManager()
        found = mgr.discover(paths=[str(tmp_path)])
        assert len(found) == 0

    def test_discover_from_env_var(self, tmp_path, monkeypatch):
        """Discover plugins from TRITIUM_PLUGINS env var."""
        from engine.plugins.manager import PluginManager

        plugin_file = tmp_path / "env_plugin.py"
        plugin_file.write_text("""
from engine.plugins.base import PluginInterface

class EnvPlugin(PluginInterface):
    plugin_id = "test.env"
    name = "EnvPlugin"
    version = "0.1.0"
    def start(self): pass
    def stop(self): pass
""")

        monkeypatch.setenv("TRITIUM_PLUGINS", str(plugin_file))
        mgr = PluginManager()
        found = mgr.discover()
        ids = [p.plugin_id for p in found]
        assert "test.env" in ids


# ---------------------------------------------------------------------------
# Test Plugin Info / Serialization
# ---------------------------------------------------------------------------

class TestPluginInfo:
    """Test plugin info serialization for the API."""

    def test_list_plugins_format(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        mgr.register(_make_plugin("test.x", "X", "2.0.0",
                                   capabilities={"bridge", "ai"}))
        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()

        plugins = mgr.list_plugins()
        assert len(plugins) == 1
        p = plugins[0]
        assert p["id"] == "test.x"
        assert p["name"] == "X"
        assert p["version"] == "2.0.0"
        assert set(p["capabilities"]) == {"bridge", "ai"}
        assert p["healthy"] is True
        assert p["status"] in ("running", "started")

    def test_list_plugins_failed_status(self):
        from engine.plugins.manager import PluginManager
        mgr = PluginManager()
        p = _make_plugin("test.fail")
        p.start = MagicMock(side_effect=RuntimeError("nope"))
        mgr.register(p)

        ctx = MagicMock()
        mgr.configure_all(lambda pid: ctx)
        mgr.start_all()

        plugins = mgr.list_plugins()
        assert plugins[0]["status"] == "failed"
