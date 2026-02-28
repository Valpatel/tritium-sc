# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the synthetic feed router -- CRUD, MJPEG streaming, snapshots.

Tests Pydantic models, SyntheticFeedManager logic, and all endpoints
with mocked renderers (no OpenCV rendering, no real frame generation).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.routers.synthetic_feed import (
    CreateFeedRequest,
    FeedResponse,
    SyntheticFeedConfig,
    SyntheticFeedManager,
    router,
)


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _fresh_manager() -> SyntheticFeedManager:
    """Create a clean manager for each test."""
    return SyntheticFeedManager()


def _fake_frame(width: int = 640, height: int = 480) -> np.ndarray:
    """Return a small synthetic BGR frame."""
    return np.zeros((height, width, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyntheticFeedModels:
    """Validate request/response Pydantic models."""

    def test_create_feed_request_defaults(self):
        r = CreateFeedRequest(feed_id="cam1")
        assert r.feed_id == "cam1"
        assert r.scene_type == "bird_eye"
        assert r.fps == 10
        assert r.width == 640
        assert r.height == 480

    def test_create_feed_request_custom(self):
        r = CreateFeedRequest(
            feed_id="cam2",
            scene_type="battle",
            fps=30,
            width=1280,
            height=720,
        )
        assert r.scene_type == "battle"
        assert r.fps == 30
        assert r.width == 1280
        assert r.height == 720

    def test_create_feed_request_missing_id(self):
        with pytest.raises(ValidationError):
            CreateFeedRequest()

    def test_feed_response_all_fields(self):
        r = FeedResponse(
            feed_id="cam1",
            scene_type="bird_eye",
            fps=10,
            width=640,
            height=480,
            frame_count=42,
            created_at="2026-02-24T00:00:00+00:00",
        )
        assert r.feed_id == "cam1"
        assert r.frame_count == 42

    def test_feed_response_missing_fields(self):
        with pytest.raises(ValidationError):
            FeedResponse(feed_id="cam1")


# ---------------------------------------------------------------------------
# SyntheticFeedConfig
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyntheticFeedConfig:
    """Validate the dataclass config."""

    def test_defaults(self):
        cfg = SyntheticFeedConfig(feed_id="test1")
        assert cfg.scene_type == "bird_eye"
        assert cfg.fps == 10
        assert cfg.width == 640
        assert cfg.height == 480

    def test_custom_values(self):
        cfg = SyntheticFeedConfig(
            feed_id="test2",
            scene_type="street_cam",
            fps=30,
            width=1920,
            height=1080,
        )
        assert cfg.scene_type == "street_cam"
        assert cfg.width == 1920

    def test_to_dict(self):
        cfg = SyntheticFeedConfig(feed_id="test3")
        d = cfg.to_dict()
        assert d["feed_id"] == "test3"
        assert d["scene_type"] == "bird_eye"
        assert isinstance(d, dict)


# ---------------------------------------------------------------------------
# SyntheticFeedManager
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyntheticFeedManager:
    """Test the manager class directly."""

    def test_create_feed(self):
        mgr = _fresh_manager()
        cfg = SyntheticFeedConfig(feed_id="cam1")
        result = mgr.create_feed(cfg)
        assert result["feed_id"] == "cam1"
        assert result["scene_type"] == "bird_eye"
        assert result["frame_count"] == 0
        assert "created_at" in result

    def test_create_duplicate_raises(self):
        mgr = _fresh_manager()
        cfg = SyntheticFeedConfig(feed_id="cam1")
        mgr.create_feed(cfg)
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_feed(cfg)

    def test_create_invalid_scene_type_defaults_to_bird_eye(self):
        mgr = _fresh_manager()
        cfg = SyntheticFeedConfig(feed_id="cam1", scene_type="nonexistent")
        result = mgr.create_feed(cfg)
        assert result["scene_type"] == "bird_eye"

    def test_list_feeds_empty(self):
        mgr = _fresh_manager()
        assert mgr.list_feeds() == []

    def test_list_feeds_multiple(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="a"))
        mgr.create_feed(SyntheticFeedConfig(feed_id="b"))
        feeds = mgr.list_feeds()
        assert len(feeds) == 2
        ids = {f["feed_id"] for f in feeds}
        assert ids == {"a", "b"}

    def test_get_feed_exists(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1"))
        result = mgr.get_feed("cam1")
        assert result is not None
        assert result["feed_id"] == "cam1"

    def test_get_feed_not_found(self):
        mgr = _fresh_manager()
        assert mgr.get_feed("nonexistent") is None

    def test_delete_feed(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1"))
        mgr.delete_feed("cam1")
        assert mgr.get_feed("cam1") is None

    def test_delete_feed_not_found(self):
        mgr = _fresh_manager()
        with pytest.raises(KeyError, match="not found"):
            mgr.delete_feed("nonexistent")

    def test_generate_frame(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1", width=320, height=240))
        with patch(
            "app.routers.synthetic_feed._RENDERERS",
            {"bird_eye": lambda **kw: _fake_frame(kw["resolution"][0], kw["resolution"][1])},
        ):
            frame = mgr.generate_frame("cam1")
            assert isinstance(frame, np.ndarray)
            assert frame.shape == (240, 320, 3)
            # frame_count should have incremented
            info = mgr.get_feed("cam1")
            assert info["frame_count"] == 1

    def test_generate_frame_increments_count(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1"))
        with patch(
            "app.routers.synthetic_feed._RENDERERS",
            {"bird_eye": lambda **kw: _fake_frame()},
        ):
            mgr.generate_frame("cam1")
            mgr.generate_frame("cam1")
            mgr.generate_frame("cam1")
            assert mgr.get_feed("cam1")["frame_count"] == 3

    def test_generate_frame_not_found(self):
        mgr = _fresh_manager()
        with pytest.raises(KeyError, match="not found"):
            mgr.generate_frame("nonexistent")

    def test_get_snapshot_returns_jpeg_bytes(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1"))
        with patch(
            "app.routers.synthetic_feed._RENDERERS",
            {"bird_eye": lambda **kw: _fake_frame()},
        ):
            jpeg = mgr.get_snapshot("cam1")
            assert isinstance(jpeg, bytes)
            # JPEG magic bytes
            assert jpeg[:2] == b"\xff\xd8"

    def test_get_snapshot_not_found(self):
        mgr = _fresh_manager()
        with pytest.raises(KeyError):
            mgr.get_snapshot("nonexistent")

    def test_mjpeg_frames_not_found(self):
        mgr = _fresh_manager()
        with pytest.raises(KeyError, match="not found"):
            # Exhaust the generator to trigger the error
            next(mgr.mjpeg_frames("nonexistent"))

    def test_mjpeg_frames_yields_boundary(self):
        """Check that the first yielded chunk has the MJPEG boundary."""
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1", fps=10))
        with patch(
            "app.routers.synthetic_feed._RENDERERS",
            {"bird_eye": lambda **kw: _fake_frame()},
        ), patch("app.routers.synthetic_feed.time.sleep"):
            gen = mgr.mjpeg_frames("cam1")
            chunk = next(gen)
            assert b"--frame" in chunk
            assert b"Content-Type: image/jpeg" in chunk
            assert b"Content-Length:" in chunk

    def test_create_cctv_scene_type(self):
        mgr = _fresh_manager()
        cfg = SyntheticFeedConfig(feed_id="cctv1", scene_type="cctv")
        result = mgr.create_feed(cfg)
        assert result["scene_type"] == "cctv"

    def test_generate_frame_street_cam_passes_camera_name(self):
        """street_cam renderer should receive camera_name kwarg."""
        mock_renderer = MagicMock(return_value=_fake_frame())
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="st1", scene_type="street_cam"))
        with patch(
            "app.routers.synthetic_feed._RENDERERS",
            {"street_cam": mock_renderer, "bird_eye": mock_renderer},
        ):
            mgr.generate_frame("st1")
            call_kwargs = mock_renderer.call_args[1]
            assert call_kwargs["camera_name"] == "SYN-st1"

    def test_generate_frame_neighborhood_passes_camera_name(self):
        mock_renderer = MagicMock(return_value=_fake_frame())
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="nb1", scene_type="neighborhood"))
        with patch(
            "app.routers.synthetic_feed._RENDERERS",
            {"neighborhood": mock_renderer, "bird_eye": mock_renderer},
        ):
            mgr.generate_frame("nb1")
            call_kwargs = mock_renderer.call_args[1]
            assert call_kwargs["camera_name"] == "SYN-nb1"

    def test_generate_frame_cctv_passes_extra_kwargs(self):
        mock_renderer = MagicMock(return_value=_fake_frame())
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cc1", scene_type="cctv"))
        with patch(
            "app.routers.synthetic_feed._RENDERERS",
            {"cctv": mock_renderer, "bird_eye": mock_renderer},
        ):
            mgr.generate_frame("cc1")
            call_kwargs = mock_renderer.call_args[1]
            assert call_kwargs["camera_name"] == "SYN-cc1"
            assert call_kwargs["scene_type"] == "front_door"
            assert call_kwargs["frame_number"] == 0

    def test_feed_metadata_fields(self):
        mgr = _fresh_manager()
        cfg = SyntheticFeedConfig(
            feed_id="cam1", scene_type="battle", fps=15, width=800, height=600,
        )
        result = mgr.create_feed(cfg)
        assert result["fps"] == 15
        assert result["width"] == 800
        assert result["height"] == 600


# ---------------------------------------------------------------------------
# List Cameras Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListCamerasEndpoint:
    """GET /api/synthetic/cameras -- list all feeds."""

    def test_empty_list(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/synthetic/cameras")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_list_with_feeds(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1"))
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam2", scene_type="battle"))
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/synthetic/cameras")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            ids = {d["feed_id"] for d in data}
            assert ids == {"cam1", "cam2"}


# ---------------------------------------------------------------------------
# Get Camera Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetCameraEndpoint:
    """GET /api/synthetic/cameras/{feed_id} -- get a specific feed."""

    def test_get_existing_feed(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1", scene_type="battle"))
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/synthetic/cameras/cam1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["feed_id"] == "cam1"
            assert data["scene_type"] == "battle"

    def test_get_nonexistent_feed(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/synthetic/cameras/nonexistent")
            assert resp.status_code == 404
            assert "not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Create Camera Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCameraEndpoint:
    """POST /api/synthetic/cameras -- create a new feed."""

    def test_create_default(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.post(
                "/api/synthetic/cameras",
                json={"feed_id": "new1"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["feed_id"] == "new1"
            assert data["scene_type"] == "bird_eye"
            assert data["frame_count"] == 0

    def test_create_custom(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.post(
                "/api/synthetic/cameras",
                json={
                    "feed_id": "new2",
                    "scene_type": "battle",
                    "fps": 30,
                    "width": 1280,
                    "height": 720,
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["scene_type"] == "battle"
            assert data["fps"] == 30
            assert data["width"] == 1280

    def test_create_duplicate_409(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1"))
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.post(
                "/api/synthetic/cameras",
                json={"feed_id": "cam1"},
            )
            assert resp.status_code == 409
            assert "already exists" in resp.json()["detail"]

    def test_create_missing_feed_id(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.post("/api/synthetic/cameras", json={})
            assert resp.status_code == 422

    def test_create_invalid_scene_type_falls_back(self):
        """Invalid scene_type defaults to bird_eye rather than error."""
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.post(
                "/api/synthetic/cameras",
                json={"feed_id": "cam_bad", "scene_type": "bogus"},
            )
            assert resp.status_code == 201
            assert resp.json()["scene_type"] == "bird_eye"

    def test_create_cctv_type(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.post(
                "/api/synthetic/cameras",
                json={"feed_id": "cc1", "scene_type": "cctv"},
            )
            assert resp.status_code == 201
            assert resp.json()["scene_type"] == "cctv"


# ---------------------------------------------------------------------------
# Delete Camera Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteCameraEndpoint:
    """DELETE /api/synthetic/cameras/{feed_id} -- remove a feed."""

    def test_delete_existing(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1"))
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.delete("/api/synthetic/cameras/cam1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "deleted"
            assert data["feed_id"] == "cam1"

    def test_delete_nonexistent_404(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.delete("/api/synthetic/cameras/nonexistent")
            assert resp.status_code == 404
            assert "not found" in resp.json()["detail"]

    def test_delete_then_get_returns_404(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1"))
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            del_resp = client.delete("/api/synthetic/cameras/cam1")
            assert del_resp.status_code == 200
            get_resp = client.get("/api/synthetic/cameras/cam1")
            assert get_resp.status_code == 404


# ---------------------------------------------------------------------------
# Snapshot Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSnapshotEndpoint:
    """GET /api/synthetic/cameras/{feed_id}/snapshot -- single JPEG frame."""

    def test_snapshot_returns_jpeg(self):
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1"))
        with patch("app.routers.synthetic_feed._manager", mgr), \
             patch(
                 "app.routers.synthetic_feed._RENDERERS",
                 {"bird_eye": lambda **kw: _fake_frame()},
             ):
            client = TestClient(_make_app())
            resp = client.get("/api/synthetic/cameras/cam1/snapshot")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/jpeg"
            # JPEG magic bytes
            assert resp.content[:2] == b"\xff\xd8"

    def test_snapshot_nonexistent_404(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/synthetic/cameras/nonexistent/snapshot")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# MJPEG Stream Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMjpegEndpoint:
    """GET /api/synthetic/cameras/{feed_id}/mjpeg -- MJPEG streaming."""

    def test_mjpeg_nonexistent_404(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/synthetic/cameras/nonexistent/mjpeg")
            assert resp.status_code == 404

    def test_mjpeg_returns_multipart_content_type(self):
        """Verify the streaming response has the correct content type."""
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1", fps=10))

        # Mock mjpeg_frames to yield exactly one frame then stop
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        single_frame = (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(fake_jpeg)).encode() + b"\r\n"
            b"\r\n" + fake_jpeg + b"\r\n"
        )

        def _one_frame(feed_id):
            yield single_frame

        mgr.mjpeg_frames = _one_frame

        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/synthetic/cameras/cam1/mjpeg")
            assert resp.status_code == 200
            assert "multipart/x-mixed-replace" in resp.headers["content-type"]
            assert b"--frame" in resp.content

    def test_mjpeg_stream_contains_jpeg_data(self):
        """The streamed data should contain JPEG magic bytes."""
        mgr = _fresh_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam1", fps=10))

        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 20
        single_frame = (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(fake_jpeg)).encode() + b"\r\n"
            b"\r\n" + fake_jpeg + b"\r\n"
        )

        def _one_frame(feed_id):
            yield single_frame

        mgr.mjpeg_frames = _one_frame

        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/synthetic/cameras/cam1/mjpeg")
            assert b"\xff\xd8" in resp.content


# ---------------------------------------------------------------------------
# get_manager helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetManager:
    """Test the get_manager singleton accessor."""

    def test_get_manager_returns_instance(self):
        from app.routers.synthetic_feed import get_manager
        mgr = get_manager()
        assert isinstance(mgr, SyntheticFeedManager)

    def test_get_manager_returns_same_instance(self):
        from app.routers.synthetic_feed import get_manager
        assert get_manager() is get_manager()


# ---------------------------------------------------------------------------
# Full CRUD Workflow
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCRUDWorkflow:
    """End-to-end CRUD via the API."""

    def test_create_list_get_delete(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())

            # Create
            resp = client.post(
                "/api/synthetic/cameras",
                json={"feed_id": "workflow1", "scene_type": "battle"},
            )
            assert resp.status_code == 201

            # List
            resp = client.get("/api/synthetic/cameras")
            assert resp.status_code == 200
            assert len(resp.json()) == 1

            # Get
            resp = client.get("/api/synthetic/cameras/workflow1")
            assert resp.status_code == 200
            assert resp.json()["scene_type"] == "battle"

            # Delete
            resp = client.delete("/api/synthetic/cameras/workflow1")
            assert resp.status_code == 200

            # Verify gone
            resp = client.get("/api/synthetic/cameras/workflow1")
            assert resp.status_code == 404

            resp = client.get("/api/synthetic/cameras")
            assert resp.status_code == 200
            assert len(resp.json()) == 0

    def test_multiple_feeds_independent(self):
        mgr = _fresh_manager()
        with patch("app.routers.synthetic_feed._manager", mgr):
            client = TestClient(_make_app())

            client.post("/api/synthetic/cameras", json={"feed_id": "a"})
            client.post("/api/synthetic/cameras", json={"feed_id": "b"})
            client.post("/api/synthetic/cameras", json={"feed_id": "c"})

            # Delete one, others remain
            client.delete("/api/synthetic/cameras/b")
            resp = client.get("/api/synthetic/cameras")
            ids = {f["feed_id"] for f in resp.json()}
            assert ids == {"a", "c"}
