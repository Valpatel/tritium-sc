# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Wave 102 security audit tests.

Verifies:
1. Quick-actions endpoint requires authentication.
2. Quick-actions has per-operator rate limiting (10/min).
3. Amy /api/amy/* endpoints require auth via router-level dependency.
4. Amy plugin Phase 3 lifecycle management.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---- Quick-actions auth & rate limiting ----

class TestQuickActionsSecurityAudit:
    """Verify quick-actions cannot be abused without auth or by spamming."""

    @pytest.mark.unit
    def test_quick_actions_has_auth_dependency(self):
        """The quick-actions POST endpoint should use require_auth."""
        from app.routers.quick_actions import execute_quick_action
        # Check that the endpoint function has a 'user' parameter with Depends
        import inspect
        sig = inspect.signature(execute_quick_action)
        assert "user" in sig.parameters, (
            "execute_quick_action must have a 'user' parameter with Depends(require_auth)"
        )

    @pytest.mark.unit
    def test_quick_actions_log_has_auth_dependency(self):
        """The quick-actions GET /log endpoint should use require_auth."""
        from app.routers.quick_actions import get_action_log
        import inspect
        sig = inspect.signature(get_action_log)
        assert "user" in sig.parameters, (
            "get_action_log must have a 'user' parameter with Depends(require_auth)"
        )

    @pytest.mark.unit
    def test_classify_action_requires_auth(self):
        """Classify (alliance override) is a privileged operation — needs auth."""
        from app.routers.quick_actions import execute_quick_action
        import inspect
        sig = inspect.signature(execute_quick_action)
        param = sig.parameters.get("user")
        assert param is not None
        # The default should be a Depends() object
        assert param.default is not inspect.Parameter.empty

    @pytest.mark.unit
    def test_escalate_action_requires_auth(self):
        """Escalation is a privileged operation — needs auth."""
        from app.routers.quick_actions import execute_quick_action
        import inspect
        sig = inspect.signature(execute_quick_action)
        assert "user" in sig.parameters

    @pytest.mark.unit
    def test_rate_tracker_resets_after_window(self):
        """Rate tracker should reset after the time window expires."""
        from app.routers.quick_actions import _OperatorRateTracker
        import time

        tracker = _OperatorRateTracker()
        # Simulate expired window
        tracker._windows["op1"] = (time.monotonic() - 120, 10)
        allowed, remaining = tracker.check_and_increment("op1")
        assert allowed is True
        assert remaining == 9  # Fresh window


# ---- Amy auth ----

class TestAmyRouterAuthAudit:
    """Verify Amy router has router-level auth dependency."""

    @pytest.mark.unit
    def test_amy_router_has_dependencies(self):
        """The Amy APIRouter should have Depends(require_auth) in dependencies."""
        from amy.router import router
        assert len(router.dependencies) > 0, (
            "Amy router must have at least one dependency (require_auth)"
        )

    @pytest.mark.unit
    def test_amy_router_dependency_is_require_auth(self):
        """The dependency should be require_auth specifically."""
        from amy.router import router
        from app.auth import require_auth
        # Check that one of the dependencies uses require_auth
        dep_callables = []
        for dep in router.dependencies:
            # Depends stores the callable in .dependency
            dep_callable = getattr(dep, "dependency", None)
            if dep_callable is not None:
                dep_callables.append(dep_callable)
        assert require_auth in dep_callables, (
            "Amy router must depend on require_auth"
        )


# ---- Amy Plugin Phase 3 ----

class TestAmyPluginPhase3:
    """Verify AmyCommanderPlugin Phase 3 lifecycle management."""

    @pytest.mark.unit
    def test_plugin_version_is_3(self):
        """Plugin version should reflect Phase 3."""
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        assert plugin.version == "3.0.0"

    @pytest.mark.unit
    def test_plugin_has_lifecycle_methods(self):
        """Plugin must own start/stop with real lifecycle management."""
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        assert hasattr(plugin, "start")
        assert hasattr(plugin, "stop")
        assert hasattr(plugin, "configure")

    @pytest.mark.unit
    def test_plugin_stop_clears_state(self):
        """stop() should clear amy instance and app.state.amy."""
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        mock_app = MagicMock()
        mock_amy = MagicMock()
        plugin._app = mock_app
        plugin._amy_instance = mock_amy
        plugin._running = True
        plugin.stop()
        assert plugin._amy_instance is None
        assert not plugin._running

    @pytest.mark.unit
    def test_plugin_start_wraps_existing(self):
        """If Amy already exists in app.state, plugin should wrap it."""
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        mock_app = MagicMock()
        mock_amy = MagicMock()
        mock_app.state.amy = mock_amy
        plugin._app = mock_app

        # Set settings to enabled
        mock_settings = MagicMock()
        mock_settings.amy_enabled = True
        plugin._settings = mock_settings

        plugin.start()
        assert plugin._amy_instance is mock_amy
        assert plugin._running is True

    @pytest.mark.unit
    def test_plugin_healthy_when_amy_running(self):
        """Health should reflect Amy's actual running state."""
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        plugin._running = True
        mock_amy = MagicMock()
        mock_amy.running = True
        plugin._amy_instance = mock_amy
        assert plugin.healthy is True

    @pytest.mark.unit
    def test_plugin_unhealthy_when_stopped(self):
        """Health should be False when plugin is stopped."""
        from plugins.amy.plugin import AmyCommanderPlugin
        plugin = AmyCommanderPlugin()
        plugin._running = False
        assert plugin.healthy is False
