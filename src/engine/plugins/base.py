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
    from engine.tactical.target_tracker import TargetTracker
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
