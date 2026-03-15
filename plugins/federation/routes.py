# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Federation plugin.

Includes site management, target sharing, and intelligence package
export/import for portable inter-site intelligence sharing.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

try:
    from app.auth import require_auth
except ImportError:
    async def require_auth():  # type: ignore[misc]
        return {"sub": "anonymous"}

if TYPE_CHECKING:
    from .plugin import FederationPlugin

try:
    from tritium_lib.models.federation import FederatedSite, SharedTarget
except ImportError:  # pragma: no cover
    FederatedSite = None  # type: ignore[assignment,misc]
    SharedTarget = None  # type: ignore[assignment,misc]

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


class AddSiteRequest(BaseModel):
    """Request body for adding a federated site."""
    name: str = "Remote Site"
    description: str = ""
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    role: str = "peer"
    share_policy: str = "targets_only"
    lat: float | None = None
    lng: float | None = None
    tags: list[str] = []
    enabled: bool = True


class IntelPackageRequest(BaseModel):
    """Request body for creating an intelligence package."""
    title: str = ""
    description: str = ""
    target_ids: list[str] = Field(default_factory=list)
    include_events: bool = True
    include_dossiers: bool = True
    include_evidence: bool = False
    classification: str = "unclassified"
    created_by: str = ""
    destination_site_id: str = ""
    destination_site_name: str = ""
    tags: list[str] = Field(default_factory=list)


class IntelPackageImportRequest(BaseModel):
    """Request body for importing an intelligence package."""
    package_data: dict = Field(default_factory=dict)
    merge_targets: bool = True
    merge_dossiers: bool = True


class ThreatAssessmentRequest(BaseModel):
    """Request body for sharing a threat assessment."""
    target_id: str
    threat_score: float = Field(ge=0.0, le=1.0)
    threat_level: str = "none"
    reasons: list[str] = Field(default_factory=list)
    source_site_id: str = ""
    assessor: str = ""


class HealthPingRequest(BaseModel):
    """Request body for recording a health ping."""
    site_id: str
    latency_ms: float = Field(ge=0.0)
    success: bool = True
    error: str = ""


def create_router(plugin: FederationPlugin) -> APIRouter:
    """Create and return the federation API router."""
    router = APIRouter(prefix="/api/federation", tags=["federation"])

    @router.get("/sites")
    async def list_sites():
        """List all federated sites with connection status."""
        return {"sites": plugin.list_sites()}

    @router.get("/sites/{site_id}")
    async def get_site(site_id: str):
        """Get a specific federated site."""
        site = plugin.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Site not found")
        conn = plugin.get_connection(site_id)
        result = site.model_dump()
        if conn:
            result["connection"] = conn.model_dump()
        return result

    @router.post("/sites")
    async def add_site(req: AddSiteRequest, user: dict = Depends(require_auth)):
        """Register a new federated site."""
        if FederatedSite is None:
            raise HTTPException(
                status_code=503,
                detail="Federation models not available"
            )
        site = FederatedSite(
            name=req.name,
            description=req.description,
            mqtt_host=req.mqtt_host,
            mqtt_port=req.mqtt_port,
            mqtt_username=req.mqtt_username,
            mqtt_password=req.mqtt_password,
            role=req.role,
            share_policy=req.share_policy,
            lat=req.lat,
            lng=req.lng,
            tags=req.tags,
            enabled=req.enabled,
        )
        site_id = plugin.add_site(site)
        return {"site_id": site_id, "name": site.name}

    @router.delete("/sites/{site_id}")
    async def remove_site(site_id: str, user: dict = Depends(require_auth)):
        """Remove a federated site."""
        if not plugin.remove_site(site_id):
            raise HTTPException(status_code=404, detail="Site not found")
        return {"status": "removed", "site_id": site_id}

    @router.get("/targets")
    async def get_shared_targets():
        """Get all targets shared from federated sites."""
        return {"targets": plugin.get_shared_targets()}

    @router.get("/stats")
    async def get_stats():
        """Get federation statistics."""
        return plugin.get_stats()

    # -- Intelligence package routes ----------------------------------------

    @router.post("/intel-packages")
    async def create_intel_package(req: IntelPackageRequest, user: dict = Depends(require_auth)):
        """Create an intelligence package from selected targets.

        Bundles targets, their events, dossiers, and evidence into a
        portable package for sharing with another Tritium installation.
        """
        if not _HAS_INTEL_PKG:
            raise HTTPException(
                status_code=503,
                detail="Intelligence package models not available",
            )
        pkg = plugin.create_intel_package(
            title=req.title,
            description=req.description,
            target_ids=req.target_ids,
            include_events=req.include_events,
            include_dossiers=req.include_dossiers,
            include_evidence=req.include_evidence,
            classification=req.classification,
            created_by=req.created_by,
            destination_site_id=req.destination_site_id,
            destination_site_name=req.destination_site_name,
            tags=req.tags,
        )
        return {
            "package_id": pkg.get("package_id", ""),
            "status": pkg.get("status", "created"),
            "target_count": pkg.get("target_count", 0),
            "event_count": pkg.get("event_count", 0),
            "dossier_count": pkg.get("dossier_count", 0),
            "evidence_count": pkg.get("evidence_count", 0),
        }

    @router.get("/intel-packages")
    async def list_intel_packages():
        """List all intelligence packages (created and received)."""
        packages = plugin.list_intel_packages()
        return {"packages": packages, "count": len(packages)}

    @router.get("/intel-packages/{package_id}")
    async def get_intel_package(package_id: str):
        """Get a specific intelligence package with full contents."""
        pkg = plugin.get_intel_package(package_id)
        if pkg is None:
            raise HTTPException(status_code=404, detail="Package not found")
        return pkg

    @router.post("/intel-packages/{package_id}/finalize")
    async def finalize_intel_package(package_id: str, user: dict = Depends(require_auth)):
        """Finalize a package, marking it ready for transmission."""
        result = plugin.finalize_intel_package(package_id)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @router.post("/intel-packages/{package_id}/transmit")
    async def transmit_intel_package(package_id: str, user: dict = Depends(require_auth)):
        """Transmit a finalized package to its destination site via MQTT."""
        result = plugin.transmit_intel_package(package_id)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @router.post("/intel-packages/import")
    async def import_intel_package(req: IntelPackageImportRequest, user: dict = Depends(require_auth)):
        """Import an intelligence package from another site.

        Validates the package and imports targets, events, and dossiers
        into the local tracker and intelligence stores.
        """
        result = plugin.import_intel_package(
            package_data=req.package_data,
            merge_targets=req.merge_targets,
            merge_dossiers=req.merge_dossiers,
        )
        return result

    @router.delete("/intel-packages/{package_id}")
    async def delete_intel_package(package_id: str, user: dict = Depends(require_auth)):
        """Delete an intelligence package."""
        if not plugin.delete_intel_package(package_id):
            raise HTTPException(status_code=404, detail="Package not found")
        return {"status": "deleted", "package_id": package_id}

    # -- Target deduplication routes ----------------------------------------

    @router.get("/dedup/stats")
    async def get_dedup_stats():
        """Get target deduplication statistics."""
        return plugin.get_dedup_stats()

    @router.get("/dedup/index")
    async def get_dedup_index():
        """Get the full dedup index showing canonical keys and their target IDs."""
        index = plugin.get_dedup_index()
        return {
            "index": index,
            "unique_entities": len(index),
            "total_ids": sum(len(v) for v in index.values()),
        }

    @router.post("/dedup/check")
    async def check_dedup(target_data: dict):
        """Check if a target would be deduplicated against known targets."""
        return plugin.deduplicate_target(target_data)

    # -- Shared threat assessment routes ------------------------------------

    @router.post("/threats")
    async def share_threat_assessment(
        req: ThreatAssessmentRequest,
        user: dict = Depends(require_auth),
    ):
        """Share a threat assessment for a target across federated sites."""
        return plugin.share_threat_assessment(
            target_id=req.target_id,
            threat_score=req.threat_score,
            threat_level=req.threat_level,
            reasons=req.reasons,
            source_site_id=req.source_site_id,
            assessor=req.assessor,
        )

    @router.get("/threats")
    async def list_threat_assessments(min_score: float = 0.0):
        """List all shared threat assessments, optionally filtered by minimum score."""
        assessments = plugin.list_threat_assessments(min_score=min_score)
        return {"assessments": assessments, "count": len(assessments)}

    @router.get("/threats/{target_id}")
    async def get_threat_assessment(target_id: str):
        """Get the shared threat assessment for a specific target."""
        assessment = plugin.get_threat_assessment(target_id)
        if assessment is None:
            raise HTTPException(status_code=404, detail="No threat assessment found")
        return assessment

    @router.delete("/threats/{target_id}")
    async def clear_threat_assessment(
        target_id: str,
        user: dict = Depends(require_auth),
    ):
        """Clear a threat assessment."""
        if not plugin.clear_threat_assessment(target_id):
            raise HTTPException(status_code=404, detail="No threat assessment found")
        return {"status": "cleared", "target_id": target_id}

    # -- Site health monitoring routes --------------------------------------

    @router.post("/health/ping")
    async def record_health_ping(
        req: HealthPingRequest,
        user: dict = Depends(require_auth),
    ):
        """Record a health ping result for a federated site."""
        return plugin.record_health_ping(
            site_id=req.site_id,
            latency_ms=req.latency_ms,
            success=req.success,
            error=req.error,
        )

    @router.get("/health")
    async def get_all_health():
        """Get health metrics for all monitored sites."""
        metrics = plugin.get_all_health_metrics()
        summary = plugin.get_health_summary()
        return {"sites": metrics, "summary": summary}

    @router.get("/health/{site_id}")
    async def get_site_health(site_id: str):
        """Get health metrics for a specific site."""
        metrics = plugin.get_health_metrics(site_id)
        if metrics is None:
            raise HTTPException(status_code=404, detail="No health data for this site")
        return metrics

    @router.get("/health/summary")
    async def get_health_summary():
        """Get a summary of federation health across all sites."""
        return plugin.get_health_summary()

    return router
