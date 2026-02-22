"""Camera discovery and auto-registration endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.database import get_db
from app.discovery.nvr import discover_cameras, CameraInfo
from app.models import Camera

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


class DiscoveredCamera(BaseModel):
    """Schema for discovered camera."""

    channel: int
    name: str
    online: bool
    rtsp_main: str
    rtsp_sub: str
    registered: bool = False


class DiscoveryResult(BaseModel):
    """Schema for discovery result."""

    discovered: int
    registered: int
    cameras: list[DiscoveredCamera]


@router.get("/scan", response_model=DiscoveryResult)
async def scan_cameras(db: AsyncSession = Depends(get_db)):
    """Scan NVR for cameras and return discovery results."""
    logger.info("Starting camera discovery scan...")

    cameras = await discover_cameras()
    if not cameras:
        raise HTTPException(status_code=503, detail="Failed to connect to NVR or no cameras found")

    # Check which are already registered
    result = await db.execute(select(Camera.channel))
    registered_channels = {row[0] for row in result.fetchall()}

    discovered_cameras = []
    for cam in cameras:
        discovered_cameras.append(
            DiscoveredCamera(
                channel=cam.channel,
                name=cam.name,
                online=cam.online,
                rtsp_main=cam.rtsp_main,
                rtsp_sub=cam.rtsp_sub,
                registered=cam.channel in registered_channels,
            )
        )

    return DiscoveryResult(
        discovered=len(cameras),
        registered=len(registered_channels),
        cameras=discovered_cameras,
    )


@router.post("/register", response_model=dict)
async def register_cameras(
    online_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Auto-register discovered cameras into the database."""
    logger.info(f"Auto-registering cameras (online_only={online_only})...")

    cameras = await discover_cameras()
    if not cameras:
        raise HTTPException(status_code=503, detail="Failed to discover cameras")

    # Get already registered channels
    result = await db.execute(select(Camera.channel))
    registered_channels = {row[0] for row in result.fetchall()}

    added = 0
    updated = 0
    skipped = 0

    for cam in cameras:
        # Skip offline cameras if online_only
        if online_only and not cam.online:
            skipped += 1
            continue

        if cam.channel in registered_channels:
            # Update existing camera
            result = await db.execute(
                select(Camera).where(Camera.channel == cam.channel)
            )
            db_camera = result.scalar_one()
            db_camera.name = cam.name
            db_camera.rtsp_url = cam.rtsp_main
            db_camera.substream_url = cam.rtsp_sub
            db_camera.enabled = cam.online
            updated += 1
        else:
            # Add new camera
            db_camera = Camera(
                channel=cam.channel,
                name=cam.name,
                rtsp_url=cam.rtsp_main,
                substream_url=cam.rtsp_sub,
                enabled=cam.online,
            )
            db.add(db_camera)
            added += 1

    await db.commit()

    logger.info(f"Camera registration complete: {added} added, {updated} updated, {skipped} skipped")

    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "total": len(cameras),
    }


@router.get("/status")
async def nvr_status():
    """Check NVR connection status."""
    from app.config import settings

    host = settings.nvr_host
    if not host:
        return {"status": "not_configured", "host": None}

    try:
        cameras = await discover_cameras()
        online_count = sum(1 for c in cameras if c.online)
        return {
            "status": "connected",
            "host": host,
            "total_channels": len(cameras),
            "online": online_count,
            "offline": len(cameras) - online_count,
        }
    except Exception as e:
        return {
            "status": "error",
            "host": host,
            "error": str(e),
        }
