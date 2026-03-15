# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""AmyCommanderPlugin — Phase 2 plugin for the Amy AI Commander.

This wraps the existing src/amy/ code WITHOUT moving any files. It provides
a PluginInterface-compliant wrapper so Amy can be discovered, configured,
and managed through the plugin system alongside other plugins.

Phase 1 (done): Plugin shell wrapping existing code.
Phase 2 (current): Move Amy router registration into this plugin.
Phase 3 (future): Move Amy lifecycle (create/start/stop) fully into plugin.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.plugins.base import PluginInterface, PluginContext

log = logging.getLogger("amy-plugin")


class AmyCommanderPlugin(PluginInterface):
    """Plugin wrapper around the existing Amy AI Commander.

    Phase 2: This plugin now owns Amy's route registration via
    _register_routes(), which is called during configure(). The
    main.py no longer needs to directly include the Amy router.

    The actual Amy lifecycle is still managed by src/app/main.py's lifespan.
    This plugin provides the bridge so plugin-aware systems (fleet dashboard,
    automation, etc.) can interact with Amy through a standard interface.
    """

    def __init__(self) -> None:
        self._amy_instance: Any = None
        self._app: Any = None
        self._logger = log
        self._running = False

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.amy-commander"

    @property
    def name(self) -> str:
        return "Amy AI Commander"

    @property
    def version(self) -> str:
        return "2.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"ai", "routes", "ui", "background"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Store references, register routes, find existing Amy instance."""
        self._app = ctx.app
        self._logger = ctx.logger or self._logger

        # Phase 1: Look for Amy instance already created by main.py lifespan
        if self._app is not None:
            self._amy_instance = getattr(self._app.state, "amy", None)
            if self._amy_instance is not None:
                self._logger.info("Amy commander instance found in app.state")
            else:
                self._logger.info(
                    "Amy commander not yet initialized (will be set later by lifespan)"
                )

        # Phase 2: Register Amy's routes through the plugin system
        self._register_routes()

    def _register_routes(self) -> None:
        """Register Amy's FastAPI routes on the app.

        Imports and includes the router from src/amy/router.py. This
        replaces the direct `app.include_router(amy_router)` call that
        was previously in src/app/main.py.
        """
        if self._app is None:
            self._logger.warning("No app reference, cannot register Amy routes")
            return

        try:
            from amy.router import router as amy_router
            self._app.include_router(amy_router)
            self._logger.info("Amy router registered: /api/amy/*")
        except Exception as exc:
            self._logger.error("Failed to register Amy routes: %s", exc)

    def start(self) -> None:
        """Mark plugin as running.

        Phase 1: Amy is started by main.py lifespan, not by this plugin.
        We just track state for health reporting.
        """
        self._running = True

        # Re-check for Amy instance (may have been created after configure)
        if self._amy_instance is None and self._app is not None:
            self._amy_instance = getattr(self._app.state, "amy", None)

        if self._amy_instance is not None:
            self._logger.info("Amy Commander plugin started (wrapping existing instance)")
        else:
            self._logger.info("Amy Commander plugin started (no Amy instance yet)")

    def stop(self) -> None:
        """Mark plugin as stopped.

        Phase 1: Amy shutdown is handled by main.py lifespan.
        """
        self._running = False
        self._logger.info("Amy Commander plugin stopped")

    @property
    def healthy(self) -> bool:
        """Report health based on Amy's actual state."""
        if not self._running:
            return False
        if self._amy_instance is not None:
            # Check if Amy has a health/running indicator
            return getattr(self._amy_instance, "running", self._running)
        return self._running

    # -- Amy accessors (for plugin-to-plugin communication) ----------------

    @property
    def amy(self) -> Any:
        """Return the wrapped Amy commander instance, or None."""
        # Lazy lookup in case Amy was initialized after us
        if self._amy_instance is None and self._app is not None:
            self._amy_instance = getattr(self._app.state, "amy", None)
        return self._amy_instance

    def get_status(self) -> dict:
        """Return Amy status summary for plugin dashboard integration."""
        amy = self.amy
        if amy is None:
            return {
                "plugin_id": self.plugin_id,
                "status": "not_initialized",
                "running": False,
            }

        return {
            "plugin_id": self.plugin_id,
            "status": "running" if getattr(amy, "running", False) else "stopped",
            "running": getattr(amy, "running", False),
            "mode": getattr(amy, "_mode", "unknown"),
            "think_count": getattr(amy, "_think_count", 0),
            "node_count": len(getattr(amy, "nodes", {})),
        }
