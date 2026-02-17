"""API routers for TRITIUM-SC."""

from app.routers.cameras import router as cameras_router
from app.routers.videos import router as videos_router
from app.routers.ws import router as ws_router

__all__ = ["cameras_router", "videos_router", "ws_router"]
