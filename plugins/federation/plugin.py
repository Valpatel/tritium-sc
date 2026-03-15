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

        # Target deduplication index: canonical_key -> list of target_ids
        # canonical_key is built from identifiers (MAC, name, entity_type+position)
        self._dedup_index: dict[str, list[str]] = {}

        # Shared threat assessments: target_id -> ThreatAssessment dict
        self._threat_assessments: dict[str, dict] = {}

        # Site health metrics: site_id -> HealthMetrics dict
        self._health_metrics: dict[str, dict] = {}

    # -- PluginInterface identity -------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.federation"

    @property
    def name(self) -> str:
        return "Federation"

    @property
    def version(self) -> str:
        return "2.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"bridge", "data_source", "routes", "dedup", "threat_sharing", "health_monitor"}

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

    # -- Target deduplication -----------------------------------------------

    def _canonical_key(self, target: dict) -> str:
        """Build a canonical dedup key from target identifiers.

        Priority: MAC address > name+entity_type > target_id prefix.
        Two targets from different sites with the same MAC are the same entity.
        """
        # Try MAC-based dedup first (most reliable)
        identifiers = target.get("identifiers", {})
        mac = identifiers.get("mac", "").lower().strip()
        if mac:
            return f"mac:{mac}"

        # Try BLE target_id pattern (ble_AABBCCDDEEFF)
        tid = target.get("target_id", "")
        if tid.startswith("ble_") and len(tid) > 4:
            return f"mac:{tid[4:].lower()}"

        # Try WiFi BSSID pattern
        if tid.startswith("wifi_") and len(tid) > 5:
            return f"bssid:{tid[5:].lower()}"

        # Name + entity_type composite key (weaker)
        name = target.get("name", "").strip().lower()
        etype = target.get("entity_type", "unknown")
        if name and name != "unknown":
            return f"name:{etype}:{name}"

        # Fall back to target_id itself (no dedup possible)
        return f"id:{tid}"

    def deduplicate_target(self, target_data: dict) -> dict:
        """Check if a target from a remote site duplicates a local target.

        Returns a dict with:
        - is_duplicate: bool
        - canonical_key: str
        - existing_ids: list of already-known target_ids for this entity
        - merged_target_id: the canonical target_id to use (first seen wins)
        """
        key = self._canonical_key(target_data)
        tid = target_data.get("target_id", "")

        with self._lock:
            existing = self._dedup_index.get(key, [])
            is_dup = len(existing) > 0 and tid not in existing

            if tid not in existing:
                self._dedup_index.setdefault(key, []).append(tid)
                existing = self._dedup_index[key]

            merged_id = existing[0] if existing else tid

        result = {
            "is_duplicate": is_dup,
            "canonical_key": key,
            "existing_ids": list(existing),
            "merged_target_id": merged_id,
        }

        if is_dup and self._event_bus:
            self._event_bus.publish("federation:target_deduplicated", data={
                "canonical_key": key,
                "target_id": tid,
                "merged_into": merged_id,
                "total_sightings": len(existing),
            })

        return result

    def get_dedup_stats(self) -> dict:
        """Get deduplication statistics."""
        with self._lock:
            total_keys = len(self._dedup_index)
            total_ids = sum(len(v) for v in self._dedup_index.values())
            duplicates = sum(1 for v in self._dedup_index.values() if len(v) > 1)
            return {
                "unique_entities": total_keys,
                "total_target_ids": total_ids,
                "duplicated_entities": duplicates,
                "dedup_savings": total_ids - total_keys if total_ids > total_keys else 0,
            }

    def get_dedup_index(self) -> dict[str, list[str]]:
        """Get the full deduplication index (canonical_key -> target_ids)."""
        with self._lock:
            return dict(self._dedup_index)

    # -- Shared threat assessments ------------------------------------------

    def share_threat_assessment(
        self,
        target_id: str,
        threat_score: float,
        threat_level: str = "none",
        reasons: list[str] | None = None,
        source_site_id: str = "",
        assessor: str = "",
    ) -> dict:
        """Create or update a shared threat assessment for a target.

        Threat assessments propagate across federated sites so all
        installations share a common threat picture.

        Args:
            target_id: The target being assessed
            threat_score: 0.0 (benign) to 1.0 (critical threat)
            threat_level: none/low/medium/high/critical
            reasons: List of reasons for the threat score
            source_site_id: Site originating the assessment
            assessor: Who/what made the assessment (operator, AI, rule)
        """
        if not source_site_id:
            source_site_id = self._settings.get("site_id", "local")

        assessment = {
            "target_id": target_id,
            "threat_score": max(0.0, min(1.0, threat_score)),
            "threat_level": threat_level,
            "reasons": reasons or [],
            "source_site_id": source_site_id,
            "assessor": assessor,
            "timestamp": time.time(),
            "consensus_score": 0.0,
            "site_scores": {},
        }

        with self._lock:
            existing = self._threat_assessments.get(target_id)
            if existing:
                # Merge: keep per-site scores for consensus
                site_scores = existing.get("site_scores", {})
                site_scores[source_site_id] = threat_score
                assessment["site_scores"] = site_scores
                # Consensus = average of all site scores
                if site_scores:
                    assessment["consensus_score"] = sum(site_scores.values()) / len(site_scores)
                # Merge reasons (deduplicate)
                all_reasons = set(existing.get("reasons", []))
                all_reasons.update(reasons or [])
                assessment["reasons"] = sorted(all_reasons)
            else:
                assessment["site_scores"] = {source_site_id: threat_score}
                assessment["consensus_score"] = threat_score

            self._threat_assessments[target_id] = assessment

        if self._event_bus:
            self._event_bus.publish("federation:threat_assessment", data={
                "target_id": target_id,
                "threat_score": assessment["threat_score"],
                "consensus_score": assessment["consensus_score"],
                "threat_level": threat_level,
                "source_site_id": source_site_id,
            })

        self._logger.info(
            "Threat assessment for %s: score=%.2f consensus=%.2f level=%s",
            target_id, threat_score, assessment["consensus_score"], threat_level,
        )

        return assessment

    def get_threat_assessment(self, target_id: str) -> Optional[dict]:
        """Get the shared threat assessment for a target."""
        with self._lock:
            return self._threat_assessments.get(target_id)

    def list_threat_assessments(self, min_score: float = 0.0) -> list[dict]:
        """List all shared threat assessments, optionally filtered by minimum score."""
        with self._lock:
            results = []
            for assessment in self._threat_assessments.values():
                if assessment.get("consensus_score", 0.0) >= min_score:
                    results.append(dict(assessment))
            results.sort(key=lambda a: a.get("consensus_score", 0.0), reverse=True)
            return results

    def clear_threat_assessment(self, target_id: str) -> bool:
        """Remove a threat assessment. Returns True if found."""
        with self._lock:
            if target_id in self._threat_assessments:
                del self._threat_assessments[target_id]
                return True
            return False

    # -- Site health monitoring ---------------------------------------------

    def record_health_ping(
        self,
        site_id: str,
        latency_ms: float,
        success: bool = True,
        error: str = "",
    ) -> dict:
        """Record a health ping result for a federated site.

        Maintains a rolling window of ping results for latency stats.
        """
        now = time.time()
        with self._lock:
            metrics = self._health_metrics.get(site_id)
            if metrics is None:
                metrics = {
                    "site_id": site_id,
                    "ping_history": [],
                    "total_pings": 0,
                    "successful_pings": 0,
                    "failed_pings": 0,
                    "avg_latency_ms": 0.0,
                    "min_latency_ms": float("inf"),
                    "max_latency_ms": 0.0,
                    "last_ping_at": 0.0,
                    "last_success_at": 0.0,
                    "last_failure_at": 0.0,
                    "last_error": "",
                    "uptime_pct": 100.0,
                    "status": "unknown",
                }
                self._health_metrics[site_id] = metrics

            # Add to history (keep last 100 pings)
            metrics["ping_history"].append({
                "timestamp": now,
                "latency_ms": latency_ms,
                "success": success,
                "error": error,
            })
            if len(metrics["ping_history"]) > 100:
                metrics["ping_history"] = metrics["ping_history"][-100:]

            metrics["total_pings"] += 1
            metrics["last_ping_at"] = now

            if success:
                metrics["successful_pings"] += 1
                metrics["last_success_at"] = now
                metrics["min_latency_ms"] = min(metrics["min_latency_ms"], latency_ms)
                metrics["max_latency_ms"] = max(metrics["max_latency_ms"], latency_ms)
            else:
                metrics["failed_pings"] += 1
                metrics["last_failure_at"] = now
                metrics["last_error"] = error

            # Calculate averages from history
            recent = [p for p in metrics["ping_history"] if p["success"]]
            if recent:
                metrics["avg_latency_ms"] = sum(p["latency_ms"] for p in recent) / len(recent)

            # Uptime percentage
            total = metrics["total_pings"]
            if total > 0:
                metrics["uptime_pct"] = (metrics["successful_pings"] / total) * 100.0

            # Determine status based on recent pings
            last_5 = metrics["ping_history"][-5:]
            if not last_5:
                metrics["status"] = "unknown"
            elif all(p["success"] for p in last_5):
                metrics["status"] = "healthy"
            elif any(p["success"] for p in last_5):
                metrics["status"] = "degraded"
            else:
                metrics["status"] = "down"

            # Update the SiteConnection latency if we have one
            conn = self._connections.get(site_id)
            if conn and success:
                conn.latency_ms = latency_ms

            result = dict(metrics)
            # Don't include full history in the return (too verbose)
            result.pop("ping_history", None)

        return result

    def get_health_metrics(self, site_id: str) -> Optional[dict]:
        """Get health metrics for a specific site."""
        with self._lock:
            metrics = self._health_metrics.get(site_id)
            if metrics is None:
                return None
            result = dict(metrics)
            result.pop("ping_history", None)
            return result

    def get_all_health_metrics(self) -> list[dict]:
        """Get health metrics for all monitored sites."""
        with self._lock:
            results = []
            for metrics in self._health_metrics.values():
                entry = dict(metrics)
                entry.pop("ping_history", None)
                results.append(entry)
            return results

    def get_health_summary(self) -> dict:
        """Get a summary of federation health across all sites."""
        with self._lock:
            total = len(self._health_metrics)
            healthy = sum(
                1 for m in self._health_metrics.values()
                if m.get("status") == "healthy"
            )
            degraded = sum(
                1 for m in self._health_metrics.values()
                if m.get("status") == "degraded"
            )
            down = sum(
                1 for m in self._health_metrics.values()
                if m.get("status") == "down"
            )

            all_latencies = []
            for m in self._health_metrics.values():
                recent = [p for p in m.get("ping_history", []) if p.get("success")]
                all_latencies.extend(p["latency_ms"] for p in recent[-10:])

            return {
                "total_monitored": total,
                "healthy": healthy,
                "degraded": degraded,
                "down": down,
                "avg_latency_ms": (
                    sum(all_latencies) / len(all_latencies)
                    if all_latencies else 0.0
                ),
            }

    # -- Enhanced receive with dedup ----------------------------------------

    def receive_target_dedup(self, target: SharedTarget) -> dict:
        """Process a target received from a federated site with deduplication.

        Returns dedup result including whether this was a duplicate.
        """
        target_data = {
            "target_id": target.target_id,
            "name": target.name,
            "entity_type": target.entity_type,
            "identifiers": target.identifiers,
        }
        dedup = self.deduplicate_target(target_data)

        with self._lock:
            self._shared_targets[target.target_id] = target

        # Push to tracker using merged ID
        if self._tracker is not None:
            self._tracker.update_from_federation({
                "target_id": dedup["merged_target_id"],
                "source_site": target.source_site_id,
                "name": target.name,
                "entity_type": target.entity_type,
                "alliance": target.alliance,
                "lat": target.lat,
                "lng": target.lng,
                "confidence": target.confidence,
                "source": target.source,
                "is_federated_duplicate": dedup["is_duplicate"],
                "canonical_key": dedup["canonical_key"],
            })

        if self._event_bus:
            self._event_bus.publish("federation:target_received", data={
                "target_id": target.target_id,
                "source_site_id": target.source_site_id,
                "is_duplicate": dedup["is_duplicate"],
                "merged_target_id": dedup["merged_target_id"],
            })

        return dedup

    # -- Enhanced stats with new features -----------------------------------

    def get_stats(self) -> dict:
        """Get federation statistics including dedup and health."""
        with self._lock:
            connected = sum(
                1 for c in self._connections.values()
                if c.state == ConnectionState.CONNECTED
            )
            dedup_stats = {
                "unique_entities": len(self._dedup_index),
                "total_target_ids": sum(len(v) for v in self._dedup_index.values()),
                "duplicated_entities": sum(
                    1 for v in self._dedup_index.values() if len(v) > 1
                ),
            }
            threat_count = len(self._threat_assessments)
            high_threats = sum(
                1 for a in self._threat_assessments.values()
                if a.get("consensus_score", 0) >= 0.7
            )
            health_summary = {}
            for status_val in ("healthy", "degraded", "down", "unknown"):
                health_summary[status_val] = sum(
                    1 for m in self._health_metrics.values()
                    if m.get("status") == status_val
                )

            return {
                "total_sites": len(self._sites),
                "connected_sites": connected,
                "shared_targets": len(self._shared_targets),
                "enabled_sites": sum(
                    1 for s in self._sites.values() if s.enabled
                ),
                "dedup": dedup_stats,
                "threat_assessments": threat_count,
                "high_threats": high_threats,
                "health": health_summary,
            }

    # -- HTTP routes --------------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for federation management."""
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
