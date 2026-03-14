# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the floor plan plugin.

Provides REST endpoints for:
- Floor plan CRUD (upload image, geo-reference, manage rooms)
- Indoor target localization (assign targets to rooms)
- Building occupancy queries
- WiFi fingerprint collection
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .store import FloorPlanStore


# -- Request / response models ------------------------------------------------

class CreateFloorPlanRequest(BaseModel):
    name: str
    building: str = ""
    floor_level: int = 0
    opacity: float = 0.7
    rotation: float = 0.0


class UpdateFloorPlanRequest(BaseModel):
    name: Optional[str] = None
    building: Optional[str] = None
    floor_level: Optional[int] = None
    bounds: Optional[dict] = None
    anchors: Optional[list[dict]] = None
    status: Optional[str] = None
    opacity: Optional[float] = None
    rotation: Optional[float] = None


class AddRoomRequest(BaseModel):
    name: str
    room_type: str = "other"
    floor_level: int = 0
    polygon: list[dict] = []
    capacity: Optional[int] = None
    tags: list[str] = []
    color: str = "#00f0ff"


class SetIndoorPositionRequest(BaseModel):
    target_id: str
    plan_id: str
    room_id: Optional[str] = None
    floor_level: int = 0
    lat: Optional[float] = None
    lon: Optional[float] = None
    confidence: float = 0.0
    method: str = "trilateration"


class AddFingerprintRequest(BaseModel):
    plan_id: str
    room_id: Optional[str] = None
    lat: float
    lon: float
    floor_level: int = 0
    rssi_map: dict[str, float] = {}
    device_id: str = ""


# -- Router factory ------------------------------------------------------------

def create_router(store: FloorPlanStore) -> APIRouter:
    """Build and return the floor plan APIRouter."""
    router = APIRouter(prefix="/api/floorplans", tags=["floorplans"])

    # -- Floor plan CRUD -------------------------------------------------------

    @router.get("")
    async def list_floorplans(
        building: Optional[str] = None,
        floor_level: Optional[int] = None,
        status: Optional[str] = None,
    ):
        """List all floor plans, optionally filtered."""
        plans = store.list_plans(
            building=building, floor_level=floor_level, status=status
        )
        return {"floorplans": plans, "count": len(plans)}

    @router.post("")
    async def create_floorplan(body: CreateFloorPlanRequest):
        """Create a new floor plan (metadata only, upload image separately)."""
        plan = store.create_plan(
            name=body.name,
            building=body.building,
            floor_level=body.floor_level,
            opacity=body.opacity,
            rotation=body.rotation,
        )
        return {"floorplan": plan}

    @router.post("/upload")
    async def upload_floorplan(
        file: UploadFile = File(...),
        name: str = Form(""),
        building: str = Form(""),
        floor_level: int = Form(0),
    ):
        """Upload a floor plan image and create metadata.

        Accepts PNG, SVG, or JPG files.
        """
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        # Validate file type
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ("png", "svg", "jpg", "jpeg"):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format: {ext}. Use PNG, SVG, or JPG.",
            )

        fmt = "jpg" if ext == "jpeg" else ext
        filename = f"{uuid.uuid4().hex[:12]}.{fmt}"

        # Save the image file
        dest = store.image_dir / filename
        try:
            with dest.open("wb") as f:
                shutil.copyfileobj(file.file, f)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save image: {exc}",
            )

        # Determine image dimensions (best-effort)
        width, height = 0, 0
        if fmt in ("png", "jpg"):
            try:
                from PIL import Image
                img = Image.open(dest)
                width, height = img.size
                img.close()
            except ImportError:
                pass  # PIL not available, skip dimension detection
            except Exception:
                pass

        display_name = name or file.filename.rsplit(".", 1)[0]
        plan = store.create_plan(
            name=display_name,
            building=building,
            floor_level=floor_level,
            image_path=filename,
            image_format=fmt,
            image_width=width,
            image_height=height,
        )
        return {"floorplan": plan}

    @router.get("/{plan_id}")
    async def get_floorplan(plan_id: str):
        """Get floor plan details."""
        plan = store.get_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Floor plan not found")
        return {"floorplan": plan}

    @router.put("/{plan_id}")
    async def update_floorplan(plan_id: str, body: UpdateFloorPlanRequest):
        """Update floor plan metadata (bounds, anchors, status, etc.)."""
        updates = body.model_dump(exclude_none=True)
        plan = store.update_plan(plan_id, updates)
        if plan is None:
            raise HTTPException(status_code=404, detail="Floor plan not found")
        return {"floorplan": plan}

    @router.delete("/{plan_id}")
    async def delete_floorplan(plan_id: str):
        """Delete a floor plan and its image file."""
        removed = store.delete_plan(plan_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Floor plan not found")
        return {"removed": True, "plan_id": plan_id}

    # -- Image serving ---------------------------------------------------------

    @router.get("/{plan_id}/image")
    async def get_floorplan_image(plan_id: str):
        """Serve the floor plan image file."""
        from fastapi.responses import FileResponse

        plan = store.get_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Floor plan not found")

        img_path = plan.get("image_path", "")
        if not img_path:
            raise HTTPException(status_code=404, detail="No image for this plan")

        full_path = store.image_dir / img_path
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="Image file not found")

        media_type = {
            "png": "image/png",
            "svg": "image/svg+xml",
            "jpg": "image/jpeg",
        }.get(plan.get("image_format", "png"), "application/octet-stream")

        return FileResponse(str(full_path), media_type=media_type)

    # -- Room management -------------------------------------------------------

    @router.post("/{plan_id}/rooms")
    async def add_room(plan_id: str, body: AddRoomRequest):
        """Add a room/zone to a floor plan."""
        room_data = body.model_dump()
        room = store.add_room(plan_id, room_data)
        if room is None:
            raise HTTPException(status_code=404, detail="Floor plan not found")
        return {"room": room}

    @router.delete("/{plan_id}/rooms/{room_id}")
    async def remove_room(plan_id: str, room_id: str):
        """Remove a room from a floor plan."""
        removed = store.remove_room(plan_id, room_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Room not found")
        return {"removed": True, "room_id": room_id}

    # -- Indoor positions ------------------------------------------------------

    @router.get("/positions/all")
    async def get_all_positions():
        """Get all current indoor target positions."""
        positions = store.get_all_positions()
        return {"positions": positions, "count": len(positions)}

    @router.post("/positions")
    async def set_position(body: SetIndoorPositionRequest):
        """Set/update indoor position for a target."""
        store.set_position(body.target_id, body.model_dump())
        return {"set": True, "target_id": body.target_id}

    @router.get("/positions/{target_id}")
    async def get_position(target_id: str):
        """Get current indoor position for a target."""
        pos = store.get_position(target_id)
        if pos is None:
            raise HTTPException(status_code=404, detail="Position not found")
        return {"position": pos}

    # -- Building occupancy ----------------------------------------------------

    @router.get("/{plan_id}/occupancy")
    async def get_occupancy(plan_id: str):
        """Get room-level occupancy for a floor plan.

        Returns target count per room/zone:
        "Conference Room: 3 people, 5 devices"
        """
        occ = store.compute_occupancy(plan_id)
        if occ is None:
            raise HTTPException(status_code=404, detail="Floor plan not found")
        return {"occupancy": occ}

    # -- WiFi fingerprints -----------------------------------------------------

    @router.post("/fingerprints")
    async def add_fingerprint(body: AddFingerprintRequest):
        """Add a WiFi RSSI fingerprint at a known position."""
        fp = store.add_fingerprint(body.model_dump())
        return {"fingerprint": fp}

    @router.get("/fingerprints/list")
    async def list_fingerprints(
        plan_id: Optional[str] = None,
        room_id: Optional[str] = None,
    ):
        """List WiFi RSSI fingerprints."""
        fps = store.get_fingerprints(plan_id=plan_id, room_id=room_id)
        return {"fingerprints": fps, "count": len(fps)}

    @router.delete("/fingerprints/clear")
    async def clear_fingerprints(plan_id: Optional[str] = None):
        """Clear WiFi fingerprints."""
        count = store.clear_fingerprints(plan_id=plan_id)
        return {"cleared": count}

    return router
