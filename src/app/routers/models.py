# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Model export/import API for federation model sharing.

Endpoints:
    GET  /api/intelligence/models            — List trained models
    GET  /api/intelligence/models/{name}/export — Download model pickle
    POST /api/intelligence/models/import      — Upload model for deployment
"""
from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from pydantic import BaseModel, Field
from loguru import logger

from app.auth import require_auth

router = APIRouter(prefix="/api/intelligence/models", tags=["intelligence-models"], dependencies=[Depends(require_auth)])

# Maximum upload size: 100MB
MAX_MODEL_SIZE = 100 * 1024 * 1024


def _get_registry():
    """Get or create the singleton ModelRegistry."""
    from tritium_lib.intelligence.model_registry import ModelRegistry
    import os

    db_path = os.environ.get("MODEL_REGISTRY_DB", "data/model_registry.db")
    # Use module-level cache
    if not hasattr(_get_registry, "_instance"):
        _get_registry._instance = ModelRegistry(db_path)
    return _get_registry._instance


class ModelInfo(BaseModel):
    """Model info for listing."""
    id: Optional[int] = None
    name: str
    version: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = 0.0
    size_bytes: int = 0


class ModelListResponse(BaseModel):
    """Response from model list endpoint."""
    models: list[ModelInfo] = Field(default_factory=list)
    total: int = 0


class ModelImportResponse(BaseModel):
    """Response from model import endpoint."""
    success: bool
    name: str = ""
    version: str = ""
    size_bytes: int = 0
    error: Optional[str] = None


@router.get("", response_model=ModelListResponse)
async def list_models(name: Optional[str] = None, limit: int = 100) -> ModelListResponse:
    """List trained models in the registry.

    Optionally filter by model name. Returns metadata without the model data blob.
    """
    try:
        registry = _get_registry()
        models = registry.list_models(name=name, limit=limit)
        return ModelListResponse(
            models=[ModelInfo(**m) for m in models],
            total=len(models),
        )
    except Exception as exc:
        logger.error("Failed to list models: %s", exc)
        return ModelListResponse()


@router.get("/{name}/export")
async def export_model(name: str, version: Optional[str] = None) -> Response:
    """Export (download) a trained model as a pickle file.

    Args:
        name: Model name (e.g. "correlation", "ble_classifier").
        version: Optional specific version. Defaults to latest.

    Returns:
        Binary pickle file download.
    """
    try:
        registry = _get_registry()
        model = registry.load_model(name, version=version)

        if model is None:
            raise HTTPException(
                status_code=404,
                detail=f"Model '{name}' version '{version or 'latest'}' not found",
            )

        filename = f"{name}_{model['version']}.pkl"

        return Response(
            content=model["data"],
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Model-Name": model["name"],
                "X-Model-Version": model["version"],
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to export model '%s': %s", name, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/import", response_model=ModelImportResponse)
async def import_model(
    file: UploadFile = File(...),
    name: str = Form(...),
    version: str = Form(...),
    accuracy: float = Form(0.0),
    training_count: int = Form(0),
    description: str = Form(""),
) -> ModelImportResponse:
    """Import (upload) a model pickle for deployment.

    Accepts a multipart form with the model file and metadata.
    The model is stored in the registry and can be loaded by learners.
    """
    try:
        data = await file.read()

        if len(data) == 0:
            return ModelImportResponse(
                success=False, error="Empty file uploaded"
            )

        if len(data) > MAX_MODEL_SIZE:
            return ModelImportResponse(
                success=False,
                error=f"File too large: {len(data)} bytes (max {MAX_MODEL_SIZE})",
            )

        metadata = {
            "accuracy": accuracy,
            "training_count": training_count,
            "description": description,
            "imported_at": time.time(),
            "original_filename": file.filename or "",
        }

        registry = _get_registry()
        result = registry.save_model(name, version, data, metadata)

        logger.info(
            "Imported model '%s' v%s (%d bytes)",
            name, version, len(data),
        )

        return ModelImportResponse(
            success=True,
            name=name,
            version=version,
            size_bytes=len(data),
        )

    except ValueError as exc:
        return ModelImportResponse(success=False, error=str(exc))
    except Exception as exc:
        logger.error("Failed to import model: %s", exc)
        return ModelImportResponse(success=False, error=str(exc))


@router.get("/stats")
async def model_stats() -> dict[str, Any]:
    """Get model registry statistics."""
    try:
        registry = _get_registry()
        return registry.get_stats()
    except Exception as exc:
        logger.error("Failed to get model stats: %s", exc)
        return {"total_models": 0, "unique_names": 0, "total_size_bytes": 0}


@router.delete("/{name}/{version}")
async def delete_model(name: str, version: str) -> dict[str, Any]:
    """Delete a specific model version from the registry."""
    try:
        registry = _get_registry()
        deleted = registry.delete_model(name, version)
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=f"Model '{name}' version '{version}' not found",
            )
        return {"success": True, "name": name, "version": version}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to delete model: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
