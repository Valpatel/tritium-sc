# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the addon loader."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from engine.addons.loader import AddonLoader


# Match the addon directories used in production (src/app/main.py):
# 1. Local SC addons/ (dev overrides)
# 2. Parent-level tritium-addons/ submodule (where real addons live)
_SC_ROOT = Path(__file__).parent.parent.parent.parent
ADDONS_DIRS = [
    str(_SC_ROOT / "addons"),
    str(_SC_ROOT.parent / "tritium-addons"),
]


class TestAddonDiscovery:
    def test_discover_finds_meshtastic(self):
        loader = AddonLoader(ADDONS_DIRS)
        found = loader.discover()
        assert "meshtastic" in found

    def test_discover_loads_manifest(self):
        loader = AddonLoader(ADDONS_DIRS)
        loader.discover()
        assert "meshtastic" in loader.registry
        entry = loader.registry["meshtastic"]
        assert entry.manifest.name == "Meshtastic LoRa Mesh"
        assert entry.manifest.version == "1.0.0"

    def test_discover_empty_dir(self, tmp_path):
        loader = AddonLoader([str(tmp_path)])
        found = loader.discover()
        assert found == []

    def test_discover_nonexistent_dir(self):
        loader = AddonLoader(["/nonexistent/path"])
        found = loader.discover()
        assert found == []


class TestAddonEnable:
    def test_enable_meshtastic(self):
        loader = AddonLoader(ADDONS_DIRS)
        loader.discover()
        # Use a mock app since we don't have the full SC app in tests
        mock_app = MagicMock()
        mock_app.event_bus = MagicMock()
        mock_app.target_tracker = MagicMock()
        loader.app = mock_app
        result = asyncio.run(loader.enable("meshtastic"))
        assert result is True
        assert "meshtastic" in loader.enabled
        assert loader.registry["meshtastic"].instance is not None

    def test_enable_unknown(self):
        loader = AddonLoader(ADDONS_DIRS)
        loader.discover()
        result = asyncio.run(loader.enable("nonexistent-addon"))
        assert result is False

    def test_enable_twice(self):
        loader = AddonLoader(ADDONS_DIRS)
        loader.discover()
        mock_app = MagicMock()
        loader.app = mock_app
        asyncio.run(loader.enable("meshtastic"))
        result = asyncio.run(loader.enable("meshtastic"))
        assert result is True  # Already enabled, returns True

    def test_disable(self):
        loader = AddonLoader(ADDONS_DIRS)
        loader.discover()
        mock_app = MagicMock()
        loader.app = mock_app
        asyncio.run(loader.enable("meshtastic"))
        result = asyncio.run(loader.disable("meshtastic"))
        assert result is True
        assert "meshtastic" not in loader.enabled


class TestAddonManifests:
    def test_get_manifests_empty(self):
        loader = AddonLoader(ADDONS_DIRS)
        loader.discover()
        assert loader.get_manifests() == []

    def test_get_manifests_after_enable(self):
        loader = AddonLoader(ADDONS_DIRS)
        loader.discover()
        mock_app = MagicMock()
        loader.app = mock_app
        asyncio.run(loader.enable("meshtastic"))
        manifests = loader.get_manifests()
        assert len(manifests) == 1
        assert manifests[0]["id"] == "meshtastic"
        assert manifests[0]["enabled"] is True
        assert len(manifests[0]["panels"]) == 1

    def test_get_all_addons(self):
        loader = AddonLoader(ADDONS_DIRS)
        loader.discover()
        all_addons = loader.get_all_addons()
        assert len(all_addons) >= 1
        mesh = next(a for a in all_addons if a["id"] == "meshtastic")
        assert mesh["name"] == "Meshtastic LoRa Mesh"
        assert mesh["enabled"] is False

    def test_get_health(self):
        loader = AddonLoader(ADDONS_DIRS)
        loader.discover()
        health = loader.get_health()
        assert health["discovered"] >= 1
        assert health["enabled"] == 0
