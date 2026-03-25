# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Screenshot sharing API.

Allows operators to upload tactical map screenshots, list them,
retrieve them as PNG, and delete them. Screenshots can also be
broadcast to other operators via WebSocket.

Endpoints:
    POST   /api/screenshots          — upload a screenshot
    GET    /api/screenshots          — list all screenshots (metadata)
    GET    /api/screenshots/{id}     — get screenshot metadata
    GET    /api/screenshots/{id}/png — download raw PNG
    DELETE /api/screenshots/{id}     — delete a screenshot
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from app.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screenshots", tags=["screenshots"], dependencies=[Depends(require_auth)])

# Lazy singleton — created on first use
_store = None
_DB_PATH = Path("data/screenshots.db")


def _get_store():
    global _store
    if _store is None:
        try:
            from tritium_lib.store.screenshot_store import ScreenshotStore
            _store = ScreenshotStore(str(_DB_PATH))
        except Exception as e:
            logger.error("Failed to create ScreenshotStore: %s", e)
            return None
    return _store


@router.post("")
async def upload_screenshot(
    request: Request,
    file: UploadFile = File(...),
    operator: str = Form("unknown"),
    description: str = Form(""),
    width: int = Form(0),
    height: int = Form(0),
):
    """Upload a tactical map screenshot.

    Saves to the ScreenshotStore and optionally broadcasts to
    connected WebSocket clients.
    """
    store = _get_store()
    if store is None:
        return JSONResponse(status_code=500, content={"detail": "Screenshot store unavailable"})

    png_data = await file.read()
    if len(png_data) == 0:
        return JSONResponse(status_code=400, content={"detail": "Empty file"})

    # Limit to 10MB
    if len(png_data) > 10 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"detail": "File too large (max 10MB)"})

    meta = store.save(
        png_data,
        operator=operator,
        description=description,
        width=width,
        height=height,
    )

    # Broadcast to WebSocket clients if event bus available
    try:
        event_bus = getattr(request.app.state, "event_bus", None)
        if event_bus is not None:
            event_bus.emit("screenshot:shared", {
                "screenshot_id": meta["screenshot_id"],
                "operator": operator,
                "description": description,
                "timestamp": meta["timestamp"],
                "width": width,
                "height": height,
            })
    except Exception:
        pass

    return meta


@router.post("/base64")
async def upload_screenshot_base64(request: Request):
    """Upload a screenshot as base64-encoded PNG in JSON body.

    Expected JSON: {"png_base64": "...", "operator": "...", "description": "...",
                    "width": 0, "height": 0}
    """
    store = _get_store()
    if store is None:
        return JSONResponse(status_code=500, content={"detail": "Screenshot store unavailable"})

    body = await request.json()
    png_b64 = body.get("png_base64", "")
    if not png_b64:
        return JSONResponse(status_code=400, content={"detail": "Missing png_base64"})

    # Strip data URL prefix if present
    if "," in png_b64:
        png_b64 = png_b64.split(",", 1)[1]

    try:
        png_data = base64.b64decode(png_b64)
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid base64"})

    if len(png_data) > 10 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"detail": "File too large (max 10MB)"})

    operator = body.get("operator", "unknown")
    description = body.get("description", "")
    width = body.get("width", 0)
    height = body.get("height", 0)

    meta = store.save(
        png_data,
        operator=operator,
        description=description,
        width=width,
        height=height,
    )

    # Broadcast via event bus
    try:
        event_bus = getattr(request.app.state, "event_bus", None)
        if event_bus is not None:
            event_bus.emit("screenshot:shared", {
                "screenshot_id": meta["screenshot_id"],
                "operator": operator,
                "description": description,
                "timestamp": meta["timestamp"],
            })
    except Exception:
        pass

    return meta


@router.get("")
async def list_screenshots(
    limit: int = 50,
    offset: int = 0,
    operator: str | None = None,
):
    """List screenshot metadata (newest first)."""
    store = _get_store()
    if store is None:
        return []

    return store.list_screenshots(limit=limit, offset=offset, operator=operator)


@router.get("/{screenshot_id}")
async def get_screenshot(screenshot_id: str):
    """Get screenshot metadata (without binary)."""
    store = _get_store()
    if store is None:
        return JSONResponse(status_code=500, content={"detail": "Store unavailable"})

    result = store.get(screenshot_id)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Screenshot not found"})

    # Return metadata only (no binary in JSON response)
    result.pop("png_data", None)
    return result


@router.get("/{screenshot_id}/png")
async def get_screenshot_png(screenshot_id: str):
    """Download the raw PNG image."""
    store = _get_store()
    if store is None:
        return JSONResponse(status_code=500, content={"detail": "Store unavailable"})

    result = store.get(screenshot_id)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Screenshot not found"})

    return Response(
        content=result["png_data"],
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="tritium-{screenshot_id[:8]}.png"',
        },
    )


@router.delete("/{screenshot_id}")
async def delete_screenshot(screenshot_id: str):
    """Delete a screenshot."""
    store = _get_store()
    if store is None:
        return JSONResponse(status_code=500, content={"detail": "Store unavailable"})

    if store.delete(screenshot_id):
        return {"deleted": True, "screenshot_id": screenshot_id}
    return JSONResponse(status_code=404, content={"detail": "Screenshot not found"})
