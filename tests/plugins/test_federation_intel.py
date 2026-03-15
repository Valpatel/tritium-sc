# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Federation plugin intelligence package routes and logic."""

import pytest
from unittest.mock import MagicMock, patch

# Ensure plugins dir is on sys.path (conftest handles this)
from federation.plugin import FederationPlugin


class FakeEventBus:
    def __init__(self):
        self.published = []

    def publish(self, topic, data=None, **kwargs):
        self.published.append((topic, data))


class FakeContext:
    def __init__(self):
        self.event_bus = FakeEventBus()
        self.target_tracker = None
        self.app = None
        self.logger = MagicMock()
        self.settings = {"site_id": "test-site", "site_name": "Test Site"}


@pytest.fixture
def plugin():
    """Create a FederationPlugin configured for testing."""
    p = FederationPlugin()
    ctx = FakeContext()
    # Minimal configure without routes
    p._event_bus = ctx.event_bus
    p._tracker = ctx.target_tracker
    p._app = None
    p._logger = ctx.logger
    p._settings = ctx.settings
    p._running = True
    return p


class TestCreateIntelPackage:
    def test_create_basic(self, plugin):
        result = plugin.create_intel_package(
            title="Test Package",
            description="A test intelligence package",
            created_by="operator",
        )
        assert result.get("title") == "Test Package"
        assert result.get("source_site_id") == "test-site"
        assert result.get("status") == "draft"
        assert "package_id" in result

    def test_create_with_classification(self, plugin):
        result = plugin.create_intel_package(
            title="Secret Intel",
            classification="secret",
            tags=["urgent"],
        )
        assert result.get("classification") == "secret"
        assert "urgent" in result.get("tags", [])

    def test_create_with_invalid_classification_falls_back(self, plugin):
        result = plugin.create_intel_package(
            classification="invalid_level",
        )
        assert result.get("classification") == "unclassified"


class TestListIntelPackages:
    def test_empty(self, plugin):
        packages = plugin.list_intel_packages()
        assert packages == []

    def test_after_create(self, plugin):
        plugin.create_intel_package(title="Pkg 1")
        plugin.create_intel_package(title="Pkg 2")
        packages = plugin.list_intel_packages()
        assert len(packages) == 2
        titles = {p["title"] for p in packages}
        assert "Pkg 1" in titles
        assert "Pkg 2" in titles


class TestGetIntelPackage:
    def test_not_found(self, plugin):
        assert plugin.get_intel_package("nonexistent") is None

    def test_found(self, plugin):
        result = plugin.create_intel_package(title="Found Me")
        pkg_id = result["package_id"]
        retrieved = plugin.get_intel_package(pkg_id)
        assert retrieved is not None
        assert retrieved["title"] == "Found Me"


class TestFinalizeIntelPackage:
    def test_finalize_draft(self, plugin):
        pkg = plugin.create_intel_package(title="Draft")
        result = plugin.finalize_intel_package(pkg["package_id"])
        assert result.get("status") == "finalized"

    def test_finalize_not_found(self, plugin):
        result = plugin.finalize_intel_package("nonexistent")
        assert "error" in result

    def test_finalize_already_finalized(self, plugin):
        pkg = plugin.create_intel_package(title="Already Done")
        plugin.finalize_intel_package(pkg["package_id"])
        result = plugin.finalize_intel_package(pkg["package_id"])
        assert "error" in result


class TestTransmitIntelPackage:
    def test_transmit_finalized(self, plugin):
        pkg = plugin.create_intel_package(title="To Transmit")
        plugin.finalize_intel_package(pkg["package_id"])
        result = plugin.transmit_intel_package(pkg["package_id"])
        assert result.get("status") == "transmitted"

    def test_transmit_not_finalized(self, plugin):
        pkg = plugin.create_intel_package(title="Not Ready")
        result = plugin.transmit_intel_package(pkg["package_id"])
        assert "error" in result

    def test_transmit_not_found(self, plugin):
        result = plugin.transmit_intel_package("nonexistent")
        assert "error" in result


class TestImportIntelPackage:
    def test_import_valid(self, plugin):
        from tritium_lib.models.intelligence_package import (
            IntelligencePackage,
            PackageTarget,
        )
        pkg = IntelligencePackage(
            source_site_id="remote-site",
            title="Incoming Intel",
        )
        pkg.add_target(PackageTarget(target_id="ble_remote_1", name="Remote Device"))
        pkg.finalize()

        result = plugin.import_intel_package(pkg.model_dump())
        assert result.get("success") is True
        assert result["package_id"] == pkg.package_id

    def test_import_expired(self, plugin):
        import time
        from tritium_lib.models.intelligence_package import IntelligencePackage
        pkg = IntelligencePackage(expires_at=time.time() - 100)
        result = plugin.import_intel_package(pkg.model_dump())
        assert result.get("success") is False

    def test_import_invalid_data(self, plugin):
        result = plugin.import_intel_package({"invalid": True, "package_id": 12345})
        # Should handle gracefully
        assert isinstance(result, dict)


class TestDeleteIntelPackage:
    def test_delete_existing(self, plugin):
        pkg = plugin.create_intel_package(title="To Delete")
        assert plugin.delete_intel_package(pkg["package_id"])

    def test_delete_nonexistent(self, plugin):
        assert not plugin.delete_intel_package("nonexistent")
