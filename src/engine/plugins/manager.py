# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Plugin manager — discovery, lifecycle, and dependency resolution.

Handles the full plugin lifecycle:
  discover() -> register() -> configure() -> start() -> [running] -> stop()

Plugins are discovered from:
1. Explicit registration via register()
2. Directory scan (Python files in specified paths)
3. TRITIUM_PLUGINS environment variable (comma-separated module paths)
4. Entry points (pip packages declaring 'tritium_plugins')
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from engine.plugins.base import PluginInterface, PluginContext

logger = logging.getLogger(__name__)


class PluginDependencyError(Exception):
    """Raised when plugin dependencies cannot be resolved."""


class PluginManager:
    """Manages plugin lifecycle: discovery, configuration, start/stop."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginInterface] = {}
        self._start_order: list[str] = []
        self._configured: set[str] = set()
        self._started: set[str] = set()
        self._failed: set[str] = set()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, plugin: PluginInterface) -> None:
        """Register a plugin instance.

        Raises ValueError if a plugin with the same ID is already registered.
        """
        pid = plugin.plugin_id
        if pid in self._plugins:
            raise ValueError(
                f"Plugin '{pid}' already registered "
                f"(existing: {self._plugins[pid].name})"
            )
        self._plugins[pid] = plugin
        logger.info(f"Plugin registered: {pid} ({plugin.name} v{plugin.version})")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, paths: list[str] | None = None) -> list[PluginInterface]:
        """Discover plugins from directories and environment variable.

        Args:
            paths: Directories to scan for plugin Python files.

        Returns:
            List of discovered plugin instances (not yet registered).
        """
        found: list[PluginInterface] = []

        # Scan directories
        scan_paths = list(paths or [])

        # Also scan from env var
        env_plugins = os.environ.get("TRITIUM_PLUGINS", "")
        if env_plugins:
            for p in env_plugins.split(","):
                p = p.strip()
                if p:
                    scan_paths.append(p)

        for path_str in scan_paths:
            path = Path(path_str)
            if path.is_file() and path.suffix == ".py":
                plugins = self._load_plugins_from_file(path)
                found.extend(plugins)
            elif path.is_dir():
                for py_file in sorted(path.glob("*.py")):
                    if py_file.name.startswith("_"):
                        continue
                    plugins = self._load_plugins_from_file(py_file)
                    found.extend(plugins)

        # Try entry points (pip packages)
        found.extend(self._discover_entry_points())

        return found

    def _load_plugins_from_file(self, path: Path) -> list[PluginInterface]:
        """Load plugin classes from a Python file."""
        plugins: list[PluginInterface] = []
        module_name = f"_tritium_plugin_{path.stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                return []

            module = importlib.util.module_from_spec(spec)
            # Temporarily add to sys.modules for imports within the plugin
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, PluginInterface)
                    and obj is not PluginInterface
                    and not inspect.isabstract(obj)
                ):
                    try:
                        instance = obj()
                        plugins.append(instance)
                        logger.debug(f"Discovered plugin: {instance.plugin_id} from {path}")
                    except Exception as e:
                        logger.warning(f"Failed to instantiate plugin from {path}: {e}")

        except SyntaxError as e:
            logger.warning(f"Syntax error in plugin file {path}: {e}")
        except Exception as e:
            logger.warning(f"Failed to load plugin from {path}: {e}")
        finally:
            sys.modules.pop(module_name, None)

        return plugins

    def _discover_entry_points(self) -> list[PluginInterface]:
        """Discover plugins from pip package entry points."""
        plugins: list[PluginInterface] = []
        try:
            if sys.version_info >= (3, 12):
                from importlib.metadata import entry_points
                eps = entry_points(group="tritium_plugins")
            else:
                from importlib.metadata import entry_points
                all_eps = entry_points()
                eps = all_eps.get("tritium_plugins", [])

            for ep in eps:
                try:
                    cls = ep.load()
                    if inspect.isclass(cls) and issubclass(cls, PluginInterface):
                        instance = cls()
                        plugins.append(instance)
                        logger.info(f"Discovered entry point plugin: {instance.plugin_id}")
                except Exception as e:
                    logger.warning(f"Failed to load entry point {ep.name}: {e}")

        except Exception as e:
            logger.debug(f"Entry point discovery not available: {e}")

        return plugins

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def configure_all(self, ctx_factory: Callable[[str], PluginContext]) -> None:
        """Configure all registered plugins in dependency order.

        Args:
            ctx_factory: Callable that takes a plugin_id and returns
                a PluginContext for that plugin.

        Raises:
            PluginDependencyError: If circular dependencies exist.
        """
        # Resolve dependency order
        self._start_order = self._topological_sort()

        # Configure in order
        for pid in self._start_order:
            plugin = self._plugins[pid]

            # Check if all dependencies are present
            missing = [d for d in plugin.dependencies if d not in self._plugins]
            if missing:
                logger.warning(
                    f"Plugin '{pid}' has missing dependencies: {missing}. Skipping."
                )
                self._failed.add(pid)
                continue

            try:
                ctx = ctx_factory(pid)
                plugin.configure(ctx)
                self._configured.add(pid)
                logger.debug(f"Plugin configured: {pid}")
            except Exception as e:
                logger.error(f"Plugin '{pid}' failed to configure: {e}")
                self._failed.add(pid)

    def start_all(self) -> dict[str, bool]:
        """Start all configured plugins in dependency order.

        Returns:
            Dict mapping plugin_id to success (True/False).
        """
        results: dict[str, bool] = {}

        for pid in self._start_order:
            plugin = self._plugins[pid]

            # Skip if already failed (configure failure or missing deps)
            if pid in self._failed:
                results[pid] = False
                continue

            # Skip if a dependency failed
            dep_failed = any(
                d in self._failed for d in plugin.dependencies
            )
            if dep_failed:
                logger.warning(
                    f"Plugin '{pid}' skipped — dependency failed."
                )
                self._failed.add(pid)
                results[pid] = False
                continue

            try:
                plugin.start()
                self._started.add(pid)
                results[pid] = True
                logger.info(f"Plugin started: {pid}")
            except Exception as e:
                logger.error(f"Plugin '{pid}' failed to start: {e}")
                self._failed.add(pid)
                results[pid] = False

        return results

    def stop_all(self) -> None:
        """Stop all started plugins in reverse dependency order."""
        for pid in reversed(self._start_order):
            if pid not in self._started:
                continue
            plugin = self._plugins[pid]
            try:
                plugin.stop()
                logger.info(f"Plugin stopped: {pid}")
            except Exception as e:
                logger.error(f"Plugin '{pid}' failed to stop: {e}")
            finally:
                self._started.discard(pid)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_plugin(self, plugin_id: str) -> PluginInterface | None:
        """Get a plugin by ID, or None if not found."""
        return self._plugins.get(plugin_id)

    def list_plugins(self) -> list[dict]:
        """List all plugins with status info."""
        result = []
        for pid, plugin in self._plugins.items():
            if pid in self._failed:
                status = "failed"
            elif pid in self._started:
                status = "running"
            elif pid in self._configured:
                status = "configured"
            else:
                status = "registered"

            result.append({
                "id": pid,
                "name": plugin.name,
                "version": plugin.version,
                "capabilities": sorted(plugin.capabilities),
                "dependencies": list(plugin.dependencies),
                "status": status,
                "healthy": plugin.healthy if pid in self._started else False,
            })
        return result

    def health_check(self) -> dict[str, bool]:
        """Check health of all started plugins."""
        return {
            pid: self._plugins[pid].healthy
            for pid in self._started
        }

    # ------------------------------------------------------------------
    # Dependency resolution
    # ------------------------------------------------------------------

    def _topological_sort(self) -> list[str]:
        """Topological sort of plugins by dependency order.

        Raises PluginDependencyError on circular dependencies.
        """
        # Build adjacency: plugin -> deps it needs first
        graph: dict[str, list[str]] = {}
        for pid, plugin in self._plugins.items():
            graph[pid] = [
                d for d in plugin.dependencies if d in self._plugins
            ]

        # Kahn's algorithm
        in_degree: dict[str, int] = defaultdict(int)
        for pid in graph:
            in_degree.setdefault(pid, 0)
            for dep in graph[pid]:
                in_degree[dep]  # ensure dep is in dict
                # pid depends on dep -> dep must come first
                # But we track in_degree as "how many things must come before me"

        # Recompute: in_degree[x] = number of plugins that must start AFTER x
        # Actually: for topological sort, in_degree[x] = number of x's dependencies
        in_degree = {pid: len(deps) for pid, deps in graph.items()}

        queue = [pid for pid, deg in in_degree.items() if deg == 0]
        order: list[str] = []

        while queue:
            # Sort for deterministic order among equal-degree nodes
            queue.sort()
            current = queue.pop(0)
            order.append(current)

            # For all plugins that depend on current, reduce their in-degree
            for pid, deps in graph.items():
                if current in deps:
                    in_degree[pid] -= 1
                    if in_degree[pid] == 0:
                        queue.append(pid)

        if len(order) != len(graph):
            # Find the cycle
            remaining = set(graph.keys()) - set(order)
            raise PluginDependencyError(
                f"Circular dependency detected among plugins: {remaining}"
            )

        return order
