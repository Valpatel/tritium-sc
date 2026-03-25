# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Plugin interface and context for TRITIUM-SC extensions.

Every plugin must extend PluginInterface and implement at minimum:
- plugin_id, name, version (class attributes or properties)
- start() and stop() methods

Plugins receive a PluginContext during configure() with references
to the event bus, target tracker, simulation engine, and other services.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from tritium_lib.tracking.target_tracker import TargetTracker
    from engine.simulation.engine import SimulationEngine
    from engine.plugins.manager import PluginManager


@dataclass
class PluginContext:
    """Context object passed to plugins during configuration.

    Provides access to shared services and plugin-specific settings.
    """
    event_bus: Any               # EventBus
    target_tracker: Any          # TargetTracker
    simulation_engine: Any       # SimulationEngine or None
    settings: dict               # Plugin-specific settings
    app: Any                     # FastAPI app or None
    logger: logging.Logger       # Logger scoped to this plugin
    plugin_manager: Any          # PluginManager instance


class PluginInterface(ABC):
    """Base class all TRITIUM-SC plugins must extend.

    Subclasses must define:
    - plugin_id: str  — unique identifier
    - name: str       — human-readable name
    - version: str    — semantic version

    And implement:
    - start()  — begin plugin operation
    - stop()   — gracefully shut down
    """

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique identifier (reverse-domain: 'com.example.my-plugin')."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version (e.g., '1.2.3')."""

    @property
    def capabilities(self) -> set[str]:
        """Capabilities this plugin provides.

        Standard capabilities:
        - 'bridge'      — External system bridge (MQTT, WebSocket, etc.)
        - 'data_source' — Adds targets or data to the system
        - 'ai'          — AI/ML integration (LLM, vision, etc.)
        - 'routes'      — Registers FastAPI routes
        - 'ui'          — Provides frontend panels/layers
        - 'background'  — Runs a background thread/task
        """
        return set()

    @property
    def dependencies(self) -> list[str]:
        """Plugin IDs this plugin depends on."""
        return []

    def configure(self, ctx: PluginContext) -> None:
        """Called once with the plugin context. Store references here.

        Default implementation is a no-op. Override if needed.
        """

    @abstractmethod
    def start(self) -> None:
        """Start the plugin. Called after configure()."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the plugin. Called during shutdown."""

    @property
    def healthy(self) -> bool:
        """Health check. Override to report actual health status."""
        return True


class EventDrainPlugin(PluginInterface):
    """PluginInterface with built-in EventBus subscribe/drain/unsubscribe.

    Subclasses get automatic event queue management:
    - ``configure()`` stores event_bus, app, and logger references.
    - ``start()`` subscribes to EventBus and spawns a drain thread.
    - ``stop()`` tears down the thread and unsubscribes.
    - Override ``_handle_event(event)`` to process each event.
    - Override ``_on_configure(ctx)`` for additional setup (route registration, etc.).
    - Override ``_on_start()`` / ``_on_stop()`` for additional lifecycle work.

    This eliminates ~30 lines of identical boilerplate per plugin.
    """

    def __init__(self) -> None:
        import queue as queue_mod
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self._running = False
        self._event_queue: Any = None  # queue_mod.Queue
        self._event_thread: Any = None  # threading.Thread
        self._queue_mod = queue_mod

    # -- Override points ---------------------------------------------------

    def _on_configure(self, ctx: "PluginContext") -> None:
        """Called after base configure stores references. Override for setup."""

    def _on_start(self) -> None:
        """Called after event drain thread starts. Override for extra threads."""

    def _on_stop(self) -> None:
        """Called before event drain thread stops. Override for cleanup."""

    def _handle_event(self, event: dict) -> None:
        """Process a single EventBus event. Override in subclass."""

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: "PluginContext") -> None:
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._logger = ctx.logger or self._logger
        self._on_configure(ctx)

    def start(self) -> None:
        import threading
        if self._running:
            return
        self._running = True

        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name=f"{self.plugin_id}-events",
            )
            self._event_thread.start()

        self._on_start()

    def stop(self) -> None:
        if not self._running:
            return

        self._on_stop()
        self._running = False

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Internal ----------------------------------------------------------

    def _event_drain_loop(self) -> None:
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._handle_event(event)
            except self._queue_mod.Empty:
                pass
            except Exception as exc:
                self._logger.error("%s event error: %s", self.plugin_id, exc)
