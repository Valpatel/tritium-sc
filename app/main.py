"""TRITIUM-SC - Security Central - Intelligence Platform.

Main FastAPI application.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config import settings
from app.database import init_db, async_session
from app.routers import cameras_router, videos_router, ws_router
from app.routers.discovery import router as discovery_router
from app.routers.ai import router as ai_router
from app.routers.search import router as search_router
from app.routers.zones import router as zones_router
from app.routers.assets import router as assets_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("=" * 60)
    logger.info("  TRITIUM-SC v0.1.0 - INITIALIZING")
    logger.info("=" * 60)

    # Initialize database
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    # Check recordings path
    if settings.recordings_path.exists():
        logger.info(f"Recordings path: {settings.recordings_path}")
    else:
        logger.warning(f"Recordings path not found: {settings.recordings_path}")

    # Auto-discover cameras from NVR
    try:
        from app.discovery.nvr import discover_cameras
        from app.models import Camera
        from sqlalchemy import select

        cameras = await discover_cameras()
        if cameras:
            async with async_session() as db:
                result = await db.execute(select(Camera.channel))
                existing = {row[0] for row in result.fetchall()}

                added = 0
                for cam in cameras:
                    if cam.online and cam.channel not in existing:
                        db.add(Camera(
                            channel=cam.channel,
                            name=cam.name,
                            rtsp_url=cam.rtsp_main,
                            substream_url=cam.rtsp_sub,
                            enabled=True,
                        ))
                        added += 1
                await db.commit()

            online = sum(1 for c in cameras if c.online)
            logger.info(f"NVR: {len(cameras)} channels, {online} online, {added} auto-registered")
    except Exception as e:
        logger.warning(f"Auto-discovery failed: {e}")

    logger.info("=" * 60)
    logger.info("  TRITIUM-SC ONLINE")
    logger.info("=" * 60)

    yield

    logger.info("TRITIUM-SC shutting down...")


# Create FastAPI app
app = FastAPI(
    title="TRITIUM-SC",
    description="Security Central - Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(cameras_router)
app.include_router(videos_router)
app.include_router(ws_router)
app.include_router(discovery_router)
app.include_router(ai_router)
app.include_router(search_router)
app.include_router(zones_router)
app.include_router(assets_router)

# Static files
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main dashboard."""
    index_path = frontend_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(
        content="""
        <html>
            <head><title>TRITIUM-SC</title></head>
            <body style="background: #0a0a0f; color: #00f0ff; font-family: monospace;">
                <h1>TRITIUM-SC v0.1.0</h1>
                <p>Frontend not found. Please check installation.</p>
            </body>
        </html>
        """
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "operational",
        "version": "0.1.0",
        "system": "TRITIUM-SC",
    }


@app.get("/api/status")
async def status():
    """System status endpoint."""
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "recordings_path": str(settings.recordings_path),
        "recordings_exists": settings.recordings_path.exists(),
        "database": "connected",
    }
