# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Camera management endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Camera

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


class CameraCreate(BaseModel):
    """Schema for creating a camera."""

    channel: int
    name: str
    rtsp_url: Optional[str] = None
    substream_url: Optional[str] = None
    enabled: bool = True


class CameraUpdate(BaseModel):
    """Schema for updating a camera."""

    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    substream_url: Optional[str] = None
    enabled: Optional[bool] = None


class CameraResponse(BaseModel):
    """Schema for camera response."""

    id: int
    channel: int
    name: str
    rtsp_url: Optional[str]
    substream_url: Optional[str]
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=list[CameraResponse])
async def list_cameras(db: AsyncSession = Depends(get_db)):
    """List all cameras."""
    result = await db.execute(select(Camera).order_by(Camera.channel))
    cameras = result.scalars().all()
    return cameras


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific camera."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera


@router.post("", response_model=CameraResponse)
async def create_camera(camera: CameraCreate, db: AsyncSession = Depends(get_db)):
    """Create a new camera."""
    # Check if channel already exists
    result = await db.execute(select(Camera).where(Camera.channel == camera.channel))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Channel already exists")

    db_camera = Camera(**camera.model_dump())
    db.add(db_camera)
    await db.flush()
    await db.refresh(db_camera)
    return db_camera


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: int, camera: CameraUpdate, db: AsyncSession = Depends(get_db)
):
    """Update a camera."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    db_camera = result.scalar_one_or_none()
    if not db_camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    update_data = camera.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_camera, field, value)

    await db.flush()
    await db.refresh(db_camera)
    return db_camera


@router.delete("/{camera_id}")
async def delete_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a camera."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    db_camera = result.scalar_one_or_none()
    if not db_camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    await db.delete(db_camera)
    return {"status": "deleted"}
