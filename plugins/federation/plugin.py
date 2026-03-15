# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FederationPlugin — manages connections to other Tritium installations.

Enables multi-site federation via MQTT bridge:
  - Site discovery (announce/heartbeat)
  - Target sharing (real-time position updates across sites)
  - Dossier synchronization (share accumulated intelligence)
  - Alert forwarding (cross-site threat notifications)

Each federated site is connected via its own MQTT client that subscribes
to the remote site's federation topic tree.

Configuration: sites are stored in data/federation_sites.json.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

try:
    from tritium_lib.models.federation import (
        ConnectionState,
        FederatedSite,
        FederationMessage,
        FederationMessageType,
        SharedTarget,
        SiteConnection,
        federation_topic,
        is_message_expired,
    )
except ImportError:  # pragma: no cover
    FederatedSite = None  # type: ignore[assignment,misc]

try:
    from tritium_lib.models.intelligence_package import (
        IntelClassification,
        IntelligencePackage,
        PackageDossier,
        PackageEvent,
        PackageEvidence,
        PackageImportResult,
        PackageStatus,
        PackageTarget,
        create_intelligence_package,
        validate_package_import,
    )
    _HAS_INTEL_PKG = True
except ImportError:  # pragma: no cover
    _HAS_INTEL_PKG = False

log = logging.getLogger("federation")


class FederationPlugin(PluginInterface):
    """Multi-site federation via MQTT bridge.

    Manages connections to remote Tritium installations for target
    sharing, dossier sync, and cross-site situational awareness.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._settings: dict = {}

        self._running = False
        self._sites: dict[str, FederatedSite] = {}  # site_id -> FederatedSite
        self._connections: dict[str, SiteConnection] = {}  # site_id -> SiteConnection
        self._shared_targets: dict[str, SharedTarget] = {}  # target_id -> SharedTarget
        self._lock = threading.Lock()
        self._heartbeat_thread: Optional[threading.Thread] = None

        self._sites_file: str = ""

        # Intelligence packages: package_id -> package dict
        self._intel_packages: dict[str, dict] = {}

    # -- PluginInterface identity -------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.federation"

    @property
    def name(self) -> str:
        return "Federation"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"bridge", "data_source", "routes"}

    # -- PluginInterface lifecycle ------------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Store references and load saved sites."""
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log
        self._settings = ctx.settings or {}

        # Sites persistence file
        data_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(data_dir, exist_ok=True)
        self._sites_file = os.path.join(data_dir, "federation_sites.json")

        # Load saved sites
        self._load_sites()

        # Register routes
        self._register_routes()

        self._logger.info(
            "Federation plugin configured (%d sites)", len(self._sites)
        )

    def start(self) -> None:
        """Start federation heartbeat loop."""
        if self._running:
            return
        if FederatedSite is None:
            log.warning("tritium-lib federation models not available — federation disabled")
            return

        self._running = True

        # Initialize connections for all enabled sites
        for site_id, site in self._sites.items():
            if site.enabled:
                self._connections[site_id] = SiteConnection(
                    site_id=site_id,
                    state=ConnectionState.DISCONNECTED,
                )

        # Start heartbeat thread
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="federation-heartbeat",
        )
        self._heartbeat_thread.start()

        self._logger.info("Federation plugin started")

    def stop(self) -> None:
        """Disconnect all sites and stop heartbeat."""
        if not self._running:
            return
        self._running = False

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=3.0)

        # Mark all connections as disconnected
        with self._lock:
            for conn in self._connections.values():
                conn.state = ConnectionState.DISCONNECTED

        self._save_sites()
        self._logger.info("Federation plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Public API ---------------------------------------------------------

    def add_site(self, site: FederatedSite) -> str:
        """Register a new federated site. Returns site_id."""
        with self._lock:
            self._sites[site.site_id] = site
            self._connections[site.site_id] = SiteConnection(
                site_id=site.site_id,
                state=ConnectionState.DISCONNECTED,
            )
        self._save_sites()
        self._logger.info("Added federated site: %s (%s)", site.name, site.site_id)

        # Publish event
        if self._event_bus:
            self._event_bus.publish("federation:site_added", data={
                "site_id": site.site_id,
                "name": site.name,
            })

        return site.site_id

    def remove_site(self, site_id: str) -> bool:
        """Remove a federated site. Returns True if found."""
        with self._lock:
            if site_id not in self._sites:
                return False
            del self._sites[site_id]
            self._connections.pop(site_id, None)
        self._save_sites()
        self._logger.info("Removed federated site: %s", site_id)
        return True

    def get_site(self, site_id: str) -> Optional[FederatedSite]:
        """Get a federated site by ID."""
        with self._lock:
            return self._sites.get(site_id)

    def list_sites(self) -> list[dict]:
        """List all federated sites with connection status."""
        with self._lock:
            result = []
            for site_id, site in self._sites.items():
                conn = self._connections.get(site_id)
                entry = site.model_dump()
                if conn:
                    entry["connection"] = conn.model_dump()
                result.append(entry)
            return result

    def get_connection(self, site_id: str) -> Optional[SiteConnection]:
        """Get connection state for a site."""
        with self._lock:
            return self._connections.get(site_id)

    def share_target(self, target: SharedTarget) -> None:
        """Share a target with federated sites."""
        with self._lock:
            self._shared_targets[target.target_id] = target

        if self._event_bus:
            self._event_bus.publish("federation:target_shared", data={
                "target_id": target.target_id,
                "source_site_id": target.source_site_id,
            })

    def receive_target(self, target: SharedTarget) -> None:
        """Process a target received from a federated site."""
        with self._lock:
            self._shared_targets[target.target_id] = target

        # Push to TargetTracker if available
        if self._tracker is not None:
            self._tracker.update_from_federation({
                "target_id": target.target_id,
                "source_site": target.source_site_id,
                "name": target.name,
                "entity_type": target.entity_type,
                "alliance": target.alliance,
                "lat": target.lat,
                "lng": target.lng,
                "confidence": target.confidence,
                "source": target.source,
            })

        if self._event_bus:
            self._event_bus.publish("federation:target_received", data={
                "target_id": target.target_id,
                "source_site_id": target.source_site_id,
            })

    def get_shared_targets(self) -> list[dict]:
        """Get all shared targets from federated sites."""
        with self._lock:
            return [t.model_dump() for t in self._shared_targets.values()]

    def get_stats(self) -> dict:
        """Get federation statistics."""
        with self._lock:
            connected = sum(
                1 for c in self._connections.values()
                if c.state == ConnectionState.CONNECTED
            )
            return {
                "total_sites": len(self._sites),
                "connected_sites": connected,
                "shared_targets": len(self._shared_targets),
                "enabled_sites": sum(
                    1 for s in self._sites.values() if s.enabled
                ),
            }

    # -- Persistence --------------------------------------------------------

    def _load_sites(self) -> None:
        """Load sites from JSON file."""
        if FederatedSite is None:
            return
        if not os.path.exists(self._sites_file):
            return
        try:
            with open(self._sites_file, "r") as f:
                data = json.load(f)
            for entry in data:
                site = FederatedSite(**entry)
                self._sites[site.site_id] = site
            self._logger.info("Loaded %d federated sites", len(self._sites))
        except Exception as exc:
            self._logger.error("Failed to load federation sites: %s", exc)

    def _save_sites(self) -> None:
        """Save sites to JSON file."""
        if FederatedSite is None:
            return
        try:
            with self._lock:
                data = [s.model_dump() for s in self._sites.values()]
            with open(self._sites_file, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as exc:
            self._logger.error("Failed to save federation sites: %s", exc)

    # -- Background tasks ---------------------------------------------------

    def _heartbeat_loop(self) -> None:
        """Periodic heartbeat for federation health monitoring."""
        while self._running:
            try:
                self._send_heartbeats()
            except Exception as exc:
                log.error("Federation heartbeat error: %s", exc)
            # Sleep in small increments so we can stop quickly
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1.0)

    def _send_heartbeats(self) -> None:
        """Send heartbeat to all connected sites."""
        if FederatedSite is None:
            return

        with self._lock:
            sites = list(self._sites.values())

        for site in sites:
            if not site.enabled:
                continue
            conn = self._connections.get(site.site_id)
            if conn:
                conn.last_heartbeat = time.time()

    # -- Intelligence packages -----------------------------------------------

    def create_intel_package(
        self,
        title: str = "",
        description: str = "",
        target_ids: list[str] | None = None,
        include_events: bool = True,
        include_dossiers: bool = True,
        include_evidence: bool = False,
        classification: str = "unclassified",
        created_by: str = "",
        destination_site_id: str = "",
        destination_site_name: str = "",
        tags: list[str] | None = None,
    ) -> dict:
        """Create an intelligence package from selected targets.

        Gathers target data from the tracker, associated events and dossiers,
        and bundles them into a portable package.
        """
        if not _HAS_INTEL_PKG:
            return {"error": "Intelligence package models not available"}

        # Map classification string to enum
        try:
            cls_enum = IntelClassification(classification)
        except ValueError:
            cls_enum = IntelClassification.UNCLASSIFIED

        # Determine source site info
        site_id = self._settings.get("site_id", "local")
        site_name = self._settings.get("site_name", "Local Site")

        pkg = create_intelligence_package(
            source_site_id=site_id,
            source_site_name=site_name,
            title=title,
            description=description,
            created_by=created_by,
            classification=cls_enum,
            tags=tags or [],
        )
        pkg.destination_site_id = destination_site_id
        pkg.destination_site_name = destination_site_name

        # Gather targets from tracker
        targets_to_include = target_ids or []
        if self._tracker is not None and targets_to_include:
            for tid in targets_to_include:
                target_data = None
                # Try to get target from tracker
                if hasattr(self._tracker, "get_target"):
                    target_data = self._tracker.get_target(tid)
                elif hasattr(self._tracker, "targets"):
                    target_data = self._tracker.targets.get(tid)

                if target_data is None:
                    continue

                # Convert to PackageTarget
                if isinstance(target_data, dict):
                    pt = PackageTarget(
                        target_id=tid,
                        name=target_data.get("name", ""),
                        entity_type=target_data.get("entity_type", "unknown"),
                        classification=target_data.get("classification", "unknown"),
                        alliance=target_data.get("alliance", "unknown"),
                        source=target_data.get("source", ""),
                        lat=target_data.get("lat"),
                        lng=target_data.get("lng"),
                        confidence=target_data.get("confidence", 0.5),
                        identifiers=target_data.get("identifiers", {}),
                        threat_level=target_data.get("threat_level", "none"),
                        first_seen=target_data.get("first_seen", 0),
                        last_seen=target_data.get("last_seen", 0),
                        sighting_count=target_data.get("sighting_count", 0),
                    )
                    pkg.add_target(pt)
        elif not targets_to_include:
            # If no specific targets, include all from shared targets
            with self._lock:
                for st in self._shared_targets.values():
                    pt = PackageTarget(
                        target_id=st.target_id,
                        name=st.name,
                        entity_type=st.entity_type,
                        classification=st.classification,
                        alliance=st.alliance,
                        source=st.source,
                        lat=st.lat,
                        lng=st.lng,
                        confidence=st.confidence,
                    )
                    pkg.add_target(pt)

        # Store the package
        pkg_dict = pkg.model_dump()
        with self._lock:
            self._intel_packages[pkg.package_id] = pkg_dict

        self._logger.info(
            "Created intel package %s: %d targets, %d events, %d dossiers",
            pkg.package_id, pkg.target_count, pkg.event_count, pkg.dossier_count,
        )

        if self._event_bus:
            self._event_bus.publish("federation:intel_package_created", data={
                "package_id": pkg.package_id,
                "title": title,
                "target_count": pkg.target_count,
            })

        return pkg_dict

    def list_intel_packages(self) -> list[dict]:
        """List all intelligence packages (metadata only)."""
        with self._lock:
            return [
                {
                    "package_id": p.get("package_id", ""),
                    "title": p.get("title", ""),
                    "status": p.get("status", "draft"),
                    "classification": p.get("classification", "unclassified"),
                    "source_site_name": p.get("source_site_name", ""),
                    "target_count": p.get("target_count", 0),
                    "event_count": p.get("event_count", 0),
                    "dossier_count": p.get("dossier_count", 0),
                    "evidence_count": p.get("evidence_count", 0),
                    "created_at": p.get("created_at", 0),
                    "created_by": p.get("created_by", ""),
                    "tags": p.get("tags", []),
                }
                for p in self._intel_packages.values()
            ]

    def get_intel_package(self, package_id: str) -> Optional[dict]:
        """Get a full intelligence package by ID."""
        with self._lock:
            return self._intel_packages.get(package_id)

    def finalize_intel_package(self, package_id: str) -> dict:
        """Finalize a package, marking it ready for transmission."""
        with self._lock:
            pkg = self._intel_packages.get(package_id)
            if pkg is None:
                return {"error": "Package not found"}
            if pkg.get("status") != "draft":
                return {"error": f"Package is {pkg.get('status')}, not draft"}
            pkg["status"] = "finalized"
            pkg["finalized_at"] = time.time()
        self._logger.info("Finalized intel package %s", package_id)
        return {"package_id": package_id, "status": "finalized"}

    def transmit_intel_package(self, package_id: str) -> dict:
        """Transmit a finalized package to its destination site via MQTT."""
        with self._lock:
            pkg = self._intel_packages.get(package_id)
            if pkg is None:
                return {"error": "Package not found"}
            if pkg.get("status") != "finalized":
                return {"error": f"Package must be finalized first (current: {pkg.get('status')})"}

        # Publish via event bus for MQTT bridge to pick up
        if self._event_bus:
            self._event_bus.publish("federation:intel_package_transmit", data=pkg)

        with self._lock:
            pkg["status"] = "transmitted"
            # Add custody entry
            custody = pkg.get("custody_chain", [])
            custody.append({
                "actor": "system",
                "action": "transmitted",
                "timestamp": time.time(),
                "site_id": pkg.get("source_site_id", ""),
                "site_name": pkg.get("source_site_name", ""),
            })
            pkg["custody_chain"] = custody

        self._logger.info("Transmitted intel package %s", package_id)
        return {"package_id": package_id, "status": "transmitted"}

    def import_intel_package(
        self,
        package_data: dict,
        merge_targets: bool = True,
        merge_dossiers: bool = True,
    ) -> dict:
        """Import an intelligence package from another site."""
        if not _HAS_INTEL_PKG:
            return {"success": False, "errors": ["Intelligence package models not available"]}

        try:
            pkg = IntelligencePackage(**package_data)
        except Exception as exc:
            return {"success": False, "errors": [f"Invalid package data: {exc}"]}

        # Validate
        site_id = self._settings.get("site_id", "local")
        validation = validate_package_import(pkg, local_site_id=site_id)
        if not validation.success:
            return {
                "success": False,
                "errors": validation.errors,
                "warnings": validation.warnings,
            }

        # Import targets into tracker
        targets_imported = 0
        targets_merged = 0
        if merge_targets and self._tracker is not None:
            for target in pkg.targets:
                target_data = {
                    "target_id": target.target_id,
                    "name": target.name,
                    "entity_type": target.entity_type,
                    "classification": target.classification,
                    "alliance": target.alliance,
                    "source": f"federation:{pkg.source_site_id}",
                    "lat": target.lat,
                    "lng": target.lng,
                    "confidence": target.confidence,
                }
                if hasattr(self._tracker, "update_from_federation"):
                    self._tracker.update_from_federation(target_data)
                    targets_imported += 1

        # Store the received package
        pkg.status = PackageStatus.IMPORTED
        pkg.add_custody_entry(
            actor="system",
            action="imported",
            site_id=site_id,
        )
        pkg_dict = pkg.model_dump()
        with self._lock:
            self._intel_packages[pkg.package_id] = pkg_dict

        self._logger.info(
            "Imported intel package %s: %d targets",
            pkg.package_id, targets_imported,
        )

        if self._event_bus:
            self._event_bus.publish("federation:intel_package_imported", data={
                "package_id": pkg.package_id,
                "source_site": pkg.source_site_id,
                "targets_imported": targets_imported,
            })

        return {
            "success": True,
            "package_id": pkg.package_id,
            "targets_imported": targets_imported,
            "targets_merged": targets_merged,
            "events_imported": len(pkg.events),
            "dossiers_imported": len(pkg.dossiers),
            "evidence_imported": len(pkg.evidence),
            "warnings": validation.warnings,
        }

    def delete_intel_package(self, package_id: str) -> bool:
        """Delete an intelligence package. Returns True if found."""
        with self._lock:
            if package_id not in self._intel_packages:
                return False
            del self._intel_packages[package_id]
        self._logger.info("Deleted intel package %s", package_id)
        return True

    # -- HTTP routes --------------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for federation management."""
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
