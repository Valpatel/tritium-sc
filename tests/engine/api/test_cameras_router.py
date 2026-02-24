"""Unit tests for the cameras router — CRUD with async SQLite in-memory DB.

Tests create, list, get, update, delete endpoints with a real async
SQLAlchemy session backed by an in-memory SQLite database.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models import Camera
from app.routers.cameras import (
    CameraCreate,
    CameraUpdate,
    CameraResponse,
    router,
)


# ---------------------------------------------------------------------------
# Async DB Fixtures
# ---------------------------------------------------------------------------

def _make_test_app():
    """Create FastAPI app with in-memory SQLite DB.

    Uses StaticPool so all connections share the same in-memory database.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    return app


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCameraModels:
    """Validate camera request/response models."""

    def test_camera_create_defaults(self):
        c = CameraCreate(channel=1, name="Front Door")
        assert c.enabled is True
        assert c.rtsp_url is None
        assert c.substream_url is None

    def test_camera_create_all_fields(self):
        c = CameraCreate(
            channel=2, name="Garage",
            rtsp_url="rtsp://192.168.1.100:554/cam2",
            substream_url="rtsp://192.168.1.100:554/cam2/sub",
            enabled=False,
        )
        assert c.rtsp_url == "rtsp://192.168.1.100:554/cam2"
        assert c.enabled is False

    def test_camera_create_missing_fields(self):
        with pytest.raises(ValidationError):
            CameraCreate()

    def test_camera_update_empty(self):
        u = CameraUpdate()
        assert u.name is None
        assert u.enabled is None

    def test_camera_update_partial(self):
        u = CameraUpdate(name="New Name", enabled=False)
        assert u.name == "New Name"
        assert u.enabled is False

    def test_camera_response(self):
        r = CameraResponse(
            id=1, channel=1, name="Test",
            rtsp_url=None, substream_url=None, enabled=True,
        )
        assert r.id == 1


# ---------------------------------------------------------------------------
# CRUD Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCameraCRUD:
    """Camera create, list, get, update, delete with real async DB."""

    def test_list_empty(self):
        with TestClient(_make_test_app()) as client:
            resp = client.get("/api/cameras")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_create_camera(self):
        with TestClient(_make_test_app()) as client:
            resp = client.post("/api/cameras", json={
                "channel": 1, "name": "Front Door",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["channel"] == 1
            assert data["name"] == "Front Door"
            assert data["enabled"] is True
            assert data["id"] >= 1

    def test_create_camera_with_urls(self):
        with TestClient(_make_test_app()) as client:
            resp = client.post("/api/cameras", json={
                "channel": 2, "name": "Garage",
                "rtsp_url": "rtsp://10.0.0.5:554/cam2",
                "substream_url": "rtsp://10.0.0.5:554/cam2/sub",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["rtsp_url"] == "rtsp://10.0.0.5:554/cam2"
            assert data["substream_url"] == "rtsp://10.0.0.5:554/cam2/sub"

    def test_create_duplicate_channel(self):
        with TestClient(_make_test_app()) as client:
            client.post("/api/cameras", json={"channel": 1, "name": "Cam 1"})
            resp = client.post("/api/cameras", json={"channel": 1, "name": "Duplicate"})
            assert resp.status_code == 400
            assert "Channel already exists" in resp.json()["detail"]

    def test_list_cameras(self):
        with TestClient(_make_test_app()) as client:
            client.post("/api/cameras", json={"channel": 3, "name": "Cam 3"})
            client.post("/api/cameras", json={"channel": 1, "name": "Cam 1"})
            client.post("/api/cameras", json={"channel": 2, "name": "Cam 2"})
            resp = client.get("/api/cameras")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 3
            # Should be ordered by channel
            channels = [c["channel"] for c in data]
            assert channels == [1, 2, 3]

    def test_get_camera(self):
        with TestClient(_make_test_app()) as client:
            create = client.post("/api/cameras", json={"channel": 1, "name": "Cam 1"})
            cam_id = create.json()["id"]
            resp = client.get(f"/api/cameras/{cam_id}")
            assert resp.status_code == 200
            assert resp.json()["name"] == "Cam 1"

    def test_get_camera_not_found(self):
        with TestClient(_make_test_app()) as client:
            resp = client.get("/api/cameras/999")
            assert resp.status_code == 404

    def test_update_camera(self):
        with TestClient(_make_test_app()) as client:
            create = client.post("/api/cameras", json={"channel": 1, "name": "Old Name"})
            cam_id = create.json()["id"]
            resp = client.patch(f"/api/cameras/{cam_id}", json={"name": "New Name"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "New Name"
            # Channel shouldn't change
            assert resp.json()["channel"] == 1

    def test_update_camera_not_found(self):
        with TestClient(_make_test_app()) as client:
            resp = client.patch("/api/cameras/999", json={"name": "X"})
            assert resp.status_code == 404

    def test_update_camera_partial(self):
        with TestClient(_make_test_app()) as client:
            create = client.post("/api/cameras", json={
                "channel": 1, "name": "Cam 1", "enabled": True,
            })
            cam_id = create.json()["id"]
            # Only update enabled, leave name
            resp = client.patch(f"/api/cameras/{cam_id}", json={"enabled": False})
            assert resp.status_code == 200
            assert resp.json()["enabled"] is False
            assert resp.json()["name"] == "Cam 1"  # Unchanged

    def test_delete_camera(self):
        with TestClient(_make_test_app()) as client:
            create = client.post("/api/cameras", json={"channel": 1, "name": "Cam 1"})
            cam_id = create.json()["id"]
            resp = client.delete(f"/api/cameras/{cam_id}")
            assert resp.status_code == 200
            assert resp.json()["status"] == "deleted"
            # Verify actually gone
            resp = client.get(f"/api/cameras/{cam_id}")
            assert resp.status_code == 404

    def test_delete_camera_not_found(self):
        with TestClient(_make_test_app()) as client:
            resp = client.delete("/api/cameras/999")
            assert resp.status_code == 404
