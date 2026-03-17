# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Addon loader — discovers addons from directories, resolves dependencies, manages lifecycle."""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from tritium_lib.sdk import AddonBase
from tritium_lib.sdk.manifest import AddonManifest, load_manifest, validate_manifest

log = logging.getLogger("addons.loader")


class AddonEntry:
    """Internal tracking for a discovered addon."""

    def __init__(self, manifest: AddonManifest, path: Path):
        self.manifest = manifest
        self.path = path
        self.instance: AddonBase | None = None
        self.enabled = False
        self.error: str | None = None
        self.crash_count = 0


class AddonLoader:
    """Discovers, loads, enables, and disables addons.

    Usage::

        loader = AddonLoader(["addons/", "~/.tritium/addons/"], app)
        loader.discover()
        await loader.enable("meshtastic")
        # ... later ...
        await loader.disable("meshtastic")
    """

    def __init__(self, addon_dirs: list[str], app: Any = None):
        self.addon_dirs = [Path(d).expanduser().resolve() for d in addon_dirs]
        self.app = app
        self.registry: dict[str, AddonEntry] = {}
        self.enabled: set[str] = set()

    def discover(self) -> list[str]:
        """Scan addon directories for tritium_addon.toml manifests.

        Returns:
            List of discovered addon IDs.
        """
        discovered = []
        for d in self.addon_dirs:
            if not d.exists():
                continue
            for manifest_path in d.glob("*/tritium_addon.toml"):
                try:
                    manifest = load_manifest(manifest_path)
                    errors = validate_manifest(manifest)
                    if errors:
                        log.warning(f"Invalid manifest {manifest_path}: {errors}")
                        continue
                    self.registry[manifest.id] = AddonEntry(manifest, manifest_path.parent)
                    discovered.append(manifest.id)
                    log.info(f"Discovered addon: {manifest.id} v{manifest.version} at {manifest_path.parent}")
                except Exception as e:
                    log.warning(f"Failed to load manifest {manifest_path}: {e}")

        return discovered

    async def enable(self, addon_id: str) -> bool:
        """Enable an addon: import module, instantiate, register with app.

        Args:
            addon_id: ID from the addon's manifest.

        Returns:
            True if successfully enabled.
        """
        entry = self.registry.get(addon_id)
        if not entry:
            log.error(f"Unknown addon: {addon_id}")
            return False

        if addon_id in self.enabled:
            log.info(f"Addon already enabled: {addon_id}")
            return True

        # Check dependencies
        for dep in entry.manifest.requires:
            dep_id = dep.split(">=")[0].split("<")[0].strip()
            if dep_id not in self.enabled:
                log.error(f"Addon '{addon_id}' requires '{dep_id}' which is not enabled")
                return False

        # Add addon's module path to sys.path
        module_path = entry.path
        addon_module_dir = str(module_path)
        if addon_module_dir not in sys.path:
            sys.path.insert(0, addon_module_dir)

        # Import the addon module
        try:
            module_name = entry.manifest.module
            if not module_name:
                module_name = f"{addon_id.replace('-', '_')}_addon"
            module = importlib.import_module(module_name)
        except ImportError as e:
            log.error(f"Failed to import addon module '{module_name}': {e}")
            entry.error = str(e)
            return False

        # Find the AddonBase subclass
        addon_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and issubclass(attr, AddonBase)
                    and attr is not AddonBase and not attr.__name__.startswith("_")):
                addon_class = attr
                break

        if not addon_class:
            log.error(f"No AddonBase subclass found in {module_name}")
            entry.error = "No AddonBase subclass found"
            return False

        # Instantiate and register
        try:
            instance = addon_class()
            await instance.register(self.app)
            entry.instance = instance
            entry.enabled = True
            entry.error = None
            self.enabled.add(addon_id)
            log.info(f"Enabled addon: {addon_id} ({addon_class.__name__})")
            return True
        except Exception as e:
            log.error(f"Failed to register addon '{addon_id}': {e}")
            entry.error = str(e)
            entry.crash_count += 1
            return False

    async def disable(self, addon_id: str) -> bool:
        """Disable an addon: unregister, cleanup.

        Args:
            addon_id: ID of the addon to disable.

        Returns:
            True if successfully disabled.
        """
        entry = self.registry.get(addon_id)
        if not entry or not entry.instance:
            return False

        try:
            await entry.instance.unregister(self.app)
        except Exception as e:
            log.warning(f"Addon unregister error for '{addon_id}': {e}")

        entry.instance = None
        entry.enabled = False
        self.enabled.discard(addon_id)
        log.info(f"Disabled addon: {addon_id}")
        return True

    def get_manifests(self) -> list[dict]:
        """Return frontend-compatible manifest data for all enabled addons."""
        result = []
        for addon_id in self.enabled:
            entry = self.registry.get(addon_id)
            if entry and entry.manifest:
                data = entry.manifest.to_frontend_json()
                data["enabled"] = True
                data["healthy"] = entry.instance.health_check()["status"] == "ok" if entry.instance else False
                result.append(data)
        return result

    def get_all_addons(self) -> list[dict]:
        """Return info about all discovered addons (enabled or not)."""
        result = []
        for addon_id, entry in self.registry.items():
            result.append({
                "id": addon_id,
                "name": entry.manifest.name,
                "version": entry.manifest.version,
                "description": entry.manifest.description,
                "category": entry.manifest.category_window,
                "enabled": entry.enabled,
                "error": entry.error,
                "crash_count": entry.crash_count,
                "path": str(entry.path),
            })
        return result

    def get_health(self) -> dict:
        """Overall addon system health."""
        return {
            "discovered": len(self.registry),
            "enabled": len(self.enabled),
            "healthy": sum(1 for aid in self.enabled
                          if self.registry[aid].instance
                          and self.registry[aid].instance.health_check()["status"] == "ok"),
            "errors": sum(1 for e in self.registry.values() if e.error),
        }
