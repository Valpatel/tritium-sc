# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TRITIUM-SC Plugin System.

Supports open-source and closed-source extensions via a standard
plugin interface with lifecycle management, dependency resolution,
and multi-source discovery.
"""

from engine.plugins.base import PluginInterface, PluginContext
from engine.plugins.manager import PluginManager, PluginDependencyError
from engine.plugins.data_provider import (
    DataProviderPlugin,
    DataItem,
    EnrichmentResult,
    Subscription,
    Bounds,
    TimeRange,
)
from engine.plugins.layer_registry import LayerRegistry, RegisteredLayer

__all__ = [
    "PluginInterface",
    "PluginContext",
    "PluginManager",
    "PluginDependencyError",
    "DataProviderPlugin",
    "DataItem",
    "EnrichmentResult",
    "Subscription",
    "Bounds",
    "TimeRange",
    "LayerRegistry",
    "RegisteredLayer",
]
