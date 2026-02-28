# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the discovery router — NVR scanning, auto-registration,
and status endpoint.

Tests with mocked discover_cameras() and real async SQLite in-memory DB.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models import Camera
from app.routers.discovery import (
    DiscoveredCamera,
    DiscoveryResult,
    router,
)


# ---------------------------------------------------------------------------
# Async DB + App Factory
# ---------------------------------------------------------------------------

def _make_test_app():
    """Create FastAPI app with in-memory SQLite DB."""
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


def _make_camera_info(channel=1, name="Cam 1", online=True):
    """Create a mock CameraInfo object."""
    cam = MagicMock()
    cam.channel = channel
    cam.name = name
    cam.online = online
    cam.rtsp_main = f"rtsp://10.0.0.5:554/ch{channel}/main"
    cam.rtsp_sub = f"rtsp://10.0.0.5:554/ch{channel}/sub"
    return cam


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDiscoveryModels:
    """Validate discovery request/response models."""

    def test_discovered_camera(self):
        d = DiscoveredCamera(
            channel=1, name="Cam 1", online=True,
            rtsp_main="rtsp://10.0.0.5:554/ch1/main",
            rtsp_sub="rtsp://10.0.0.5:554/ch1/sub",
        )
        assert d.registered is False
        assert d.online is True

    def test_discovered_camera_registered(self):
        d = DiscoveredCamera(
            channel=1, name="Cam 1", online=True,
            rtsp_main="rtsp://x", rtsp_sub="rtsp://x",
            registered=True,
        )
        assert d.registered is True

    def test_discovery_result(self):
        r = DiscoveryResult(
            discovered=4, registered=2,
            cameras=[
                DiscoveredCamera(
                    channel=1, name="Cam 1", online=True,
                    rtsp_main="rtsp://x", rtsp_sub="rtsp://x",
                ),
            ],
        )
        assert r.discovered == 4
        assert len(r.cameras) == 1


# ---------------------------------------------------------------------------
# Scan Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestScanEndpoint:
    """GET /api/discovery/scan — NVR camera discovery."""

    def test_scan_no_cameras_found(self):
        with patch("app.routers.discovery.discover_cameras", new_callable=AsyncMock, return_value=[]):
            with TestClient(_make_test_app()) as client:
                resp = client.get("/api/discovery/scan")
                assert resp.status_code == 503
                assert "no cameras found" in resp.json()["detail"]

    def test_scan_finds_cameras(self):
        cameras = [
            _make_camera_info(1, "Front Door", True),
            _make_camera_info(2, "Backyard", True),
            _make_camera_info(3, "Garage", False),
        ]
        with patch("app.routers.discovery.discover_cameras", new_callable=AsyncMock, return_value=cameras):
            with TestClient(_make_test_app()) as client:
                resp = client.get("/api/discovery/scan")
                assert resp.status_code == 200
                data = resp.json()
                assert data["discovered"] == 3
                assert data["registered"] == 0
                assert len(data["cameras"]) == 3
                # Check online/offline
                online = [c for c in data["cameras"] if c["online"]]
                assert len(online) == 2

    def test_scan_marks_registered(self):
        """Pre-registered cameras are flagged."""
        cameras = [
            _make_camera_info(1, "Front Door", True),
            _make_camera_info(2, "Backyard", True),
        ]
        with patch("app.routers.discovery.discover_cameras", new_callable=AsyncMock, return_value=cameras):
            with TestClient(_make_test_app()) as client:
                # Pre-register channel 1 via cameras API
                # Need to add camera router too for this
                from app.routers.cameras import router as cam_router
                client.app.include_router(cam_router)
                client.post("/api/cameras", json={"channel": 1, "name": "Already Registered"})

                resp = client.get("/api/discovery/scan")
                assert resp.status_code == 200
                data = resp.json()
                assert data["registered"] == 1
                # Channel 1 should be marked as registered
                ch1 = next(c for c in data["cameras"] if c["channel"] == 1)
                assert ch1["registered"] is True
                ch2 = next(c for c in data["cameras"] if c["channel"] == 2)
                assert ch2["registered"] is False


# ---------------------------------------------------------------------------
# Register Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRegisterEndpoint:
    """POST /api/discovery/register — auto-register cameras."""

    def test_register_no_cameras(self):
        with patch("app.routers.discovery.discover_cameras", new_callable=AsyncMock, return_value=[]):
            with TestClient(_make_test_app()) as client:
                resp = client.post("/api/discovery/register")
                assert resp.status_code == 503

    def test_register_online_only(self):
        cameras = [
            _make_camera_info(1, "Front Door", True),
            _make_camera_info(2, "Backyard", False),
            _make_camera_info(3, "Garage", True),
        ]
        with patch("app.routers.discovery.discover_cameras", new_callable=AsyncMock, return_value=cameras):
            with TestClient(_make_test_app()) as client:
                resp = client.post("/api/discovery/register?online_only=true")
                assert resp.status_code == 200
                data = resp.json()
                assert data["added"] == 2  # Only online
                assert data["skipped"] == 1
                assert data["total"] == 3

    def test_register_all_cameras(self):
        cameras = [
            _make_camera_info(1, "Front Door", True),
            _make_camera_info(2, "Backyard", False),
        ]
        with patch("app.routers.discovery.discover_cameras", new_callable=AsyncMock, return_value=cameras):
            with TestClient(_make_test_app()) as client:
                resp = client.post("/api/discovery/register?online_only=false")
                assert resp.status_code == 200
                data = resp.json()
                assert data["added"] == 2
                assert data["skipped"] == 0

    def test_register_updates_existing(self):
        """Re-registering updates existing cameras instead of duplicating."""
        cameras = [_make_camera_info(1, "Updated Name", True)]
        with patch("app.routers.discovery.discover_cameras", new_callable=AsyncMock, return_value=cameras):
            with TestClient(_make_test_app()) as client:
                # Include cameras router to pre-register
                from app.routers.cameras import router as cam_router
                client.app.include_router(cam_router)
                client.post("/api/cameras", json={"channel": 1, "name": "Old Name"})

                resp = client.post("/api/discovery/register")
                assert resp.status_code == 200
                data = resp.json()
                assert data["updated"] == 1
                assert data["added"] == 0


# ---------------------------------------------------------------------------
# Status Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNVRStatusEndpoint:
    """GET /api/discovery/status — NVR connection status."""

    def test_status_not_configured(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.nvr_host = None
            with TestClient(_make_test_app()) as client:
                resp = client.get("/api/discovery/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "not_configured"

    def test_status_connected(self):
        cameras = [
            _make_camera_info(1, "Cam 1", True),
            _make_camera_info(2, "Cam 2", True),
            _make_camera_info(3, "Cam 3", False),
        ]
        with patch("app.config.settings") as mock_settings, \
             patch("app.routers.discovery.discover_cameras", new_callable=AsyncMock, return_value=cameras):
            mock_settings.nvr_host = "10.0.0.5"
            with TestClient(_make_test_app()) as client:
                resp = client.get("/api/discovery/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "connected"
                assert data["host"] == "10.0.0.5"
                assert data["total_channels"] == 3
                assert data["online"] == 2
                assert data["offline"] == 1

    def test_status_error(self):
        with patch("app.config.settings") as mock_settings, \
             patch("app.routers.discovery.discover_cameras", new_callable=AsyncMock,
                   side_effect=ConnectionError("Connection refused")):
            mock_settings.nvr_host = "10.0.0.5"
            with TestClient(_make_test_app()) as client:
                resp = client.get("/api/discovery/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "error"
                assert "Connection refused" in data["error"]
