# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the AI router — analysis tasks, timeline, hyperlapse,
compression, status, and single-frame detection endpoints.

Tests state management (analysis_tasks dict), request/response models,
and API behavior with mocked YOLO/torch/cv2 dependencies.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.routers.ai import (
    AnalysisRequest,
    AnalysisStatus,
    TimelineResponse,
    analysis_tasks,
    get_video_paths,
    router,
)


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAIModels:
    """Validate AI request/response models."""

    def test_analysis_request_defaults(self):
        r = AnalysisRequest(channel=1, date="2026-02-20")
        assert r.channel == 1
        assert r.date == "2026-02-20"
        assert r.sample_rate == 15

    def test_analysis_request_custom_sample_rate(self):
        r = AnalysisRequest(channel=3, date="2026-01-01", sample_rate=30)
        assert r.sample_rate == 30

    def test_analysis_request_missing_fields(self):
        with pytest.raises(ValidationError):
            AnalysisRequest()

    def test_analysis_status(self):
        s = AnalysisStatus(
            task_id="analysis_1_2026-02-20",
            status="running",
            progress=42.5,
            message="Processing video 3/10",
        )
        assert s.task_id == "analysis_1_2026-02-20"
        assert s.status == "running"
        assert s.progress == pytest.approx(42.5)
        assert s.result is None

    def test_analysis_status_with_result(self):
        s = AnalysisStatus(
            task_id="t1", status="complete", progress=100,
            message="Done", result={"events": []},
        )
        assert s.result == {"events": []}

    def test_timeline_response(self):
        r = TimelineResponse(
            date="2026-02-20", channel=1,
            events=[{"type": "person", "start": 100}],
            total_people=5, total_vehicles=2,
            active_hours=[8, 9, 10, 14, 15],
            peak_hour=9,
        )
        assert r.total_people == 5
        assert len(r.active_hours) == 5
        assert r.peak_hour == 9

    def test_timeline_response_no_peak(self):
        r = TimelineResponse(
            date="2026-02-20", channel=1,
            events=[], total_people=0, total_vehicles=0,
            active_hours=[], peak_hour=None,
        )
        assert r.peak_hour is None
        assert r.events == []


# ---------------------------------------------------------------------------
# get_video_paths
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetVideoPaths:
    """get_video_paths resolves channel/date to list of .mp4 files."""

    def test_no_channel_dir(self):
        with patch("app.routers.ai.get_video_paths") as mock_gvp:
            # Test the actual function by patching what it calls
            pass
        # Call directly with mocked imports
        with patch("app.routers.videos.find_channel_dir", return_value=None):
            result = get_video_paths(99, "2026-02-20")
            assert result == []

    def test_no_date_dir(self):
        mock_ch = MagicMock()
        with patch("app.routers.videos.find_channel_dir", return_value=mock_ch), \
             patch("app.routers.videos.find_date_dir", return_value=None):
            result = get_video_paths(1, "2026-99-99")
            assert result == []

    def test_finds_mp4_files(self):
        with tempfile.TemporaryDirectory() as td:
            date_dir = Path(td) / "2026-02-20"
            date_dir.mkdir()
            (date_dir / "video_001.mp4").write_bytes(b"\x00")
            (date_dir / "video_002.mp4").write_bytes(b"\x00")
            (date_dir / "thumbs.db").write_bytes(b"\x00")
            with patch("app.routers.videos.find_channel_dir", return_value=Path(td)), \
                 patch("app.routers.videos.find_date_dir", return_value=date_dir):
                result = get_video_paths(1, "2026-02-20")
                assert len(result) == 2
                assert all(p.suffix == ".mp4" for p in result)

    def test_empty_date_dir(self):
        with tempfile.TemporaryDirectory() as td:
            date_dir = Path(td) / "2026-02-20"
            date_dir.mkdir()
            with patch("app.routers.videos.find_channel_dir", return_value=Path(td)), \
                 patch("app.routers.videos.find_date_dir", return_value=date_dir):
                result = get_video_paths(1, "2026-02-20")
                assert result == []

    def test_sorted_output(self):
        with tempfile.TemporaryDirectory() as td:
            date_dir = Path(td) / "2026-02-20"
            date_dir.mkdir()
            (date_dir / "c_video.mp4").write_bytes(b"\x00")
            (date_dir / "a_video.mp4").write_bytes(b"\x00")
            (date_dir / "b_video.mp4").write_bytes(b"\x00")
            with patch("app.routers.videos.find_channel_dir", return_value=Path(td)), \
                 patch("app.routers.videos.find_date_dir", return_value=date_dir):
                result = get_video_paths(1, "2026-02-20")
                names = [p.name for p in result]
                assert names == sorted(names)


# ---------------------------------------------------------------------------
# AI Status Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAIStatusEndpoint:
    """GET /api/ai/status — AI module status and capabilities."""

    def test_status_with_gpu(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_name.return_value = "NVIDIA RTX 4090"
        with patch.dict("sys.modules", {"torch": mock_torch}), \
             patch("app.routers.ai.analysis_tasks", {"t1": {"status": "running"}}):
            # Need to also mock the YOLO import
            import sys
            mock_detector = MagicMock()
            mock_detector.YOLO_AVAILABLE = True
            sys.modules["app.ai.detector"] = mock_detector
            try:
                client = TestClient(_make_app())
                resp = client.get("/api/ai/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["yolo_available"] is True
                assert data["gpu_available"] is True
                assert data["gpu_name"] == "NVIDIA RTX 4090"
                assert data["active_tasks"] == 1
            finally:
                del sys.modules["app.ai.detector"]

    def test_status_no_gpu(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        import sys
        mock_detector = MagicMock()
        mock_detector.YOLO_AVAILABLE = False
        sys.modules["app.ai.detector"] = mock_detector
        sys.modules["torch"] = mock_torch
        try:
            client = TestClient(_make_app())
            resp = client.get("/api/ai/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["gpu_available"] is False
            assert data["gpu_name"] is None
        finally:
            del sys.modules["app.ai.detector"]
            del sys.modules["torch"]

    def test_status_import_error(self):
        """When torch/YOLO not installed, return degraded status."""
        import sys
        # Remove torch and detector if cached
        for mod in ["torch", "app.ai.detector"]:
            sys.modules.pop(mod, None)
        with patch.dict("sys.modules", {"torch": None, "app.ai.detector": None}):
            client = TestClient(_make_app())
            resp = client.get("/api/ai/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["yolo_available"] is False
            assert data["gpu_available"] is False


# ---------------------------------------------------------------------------
# Analysis Task Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAnalyzeEndpoint:
    """POST /api/ai/analyze — start background analysis."""

    def setup_method(self):
        analysis_tasks.clear()

    def teardown_method(self):
        analysis_tasks.clear()

    def test_no_videos_404(self):
        with patch("app.routers.ai.get_video_paths", return_value=[]):
            client = TestClient(_make_app())
            resp = client.post("/api/ai/analyze", json={
                "channel": 1, "date": "2026-02-20",
            })
            assert resp.status_code == 404
            assert "No videos found" in resp.json()["detail"]

    def test_start_new_analysis(self):
        fake_paths = [Path("/fake/video1.mp4"), Path("/fake/video2.mp4")]
        with patch("app.routers.ai.get_video_paths", return_value=fake_paths), \
             patch("app.routers.ai.run_analysis"):
            client = TestClient(_make_app())
            resp = client.post("/api/ai/analyze", json={
                "channel": 1, "date": "2026-02-20",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["task_id"] == "analysis_1_2026-02-20"
            assert data["status"] == "pending"
            assert "2 videos" in data["message"]

    def test_already_running(self):
        analysis_tasks["analysis_1_2026-02-20"] = {
            "status": "running",
            "progress": 45.0,
            "message": "Processing...",
        }
        fake_paths = [Path("/fake/video1.mp4")]
        with patch("app.routers.ai.get_video_paths", return_value=fake_paths):
            client = TestClient(_make_app())
            resp = client.post("/api/ai/analyze", json={
                "channel": 1, "date": "2026-02-20",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "running"
            assert data["progress"] == pytest.approx(45.0)
            assert "already in progress" in data["message"]

    def test_resubmit_completed_restarts(self):
        """If a previous analysis completed, re-posting starts a new one."""
        analysis_tasks["analysis_1_2026-02-20"] = {
            "status": "complete",
            "progress": 100,
            "message": "Done",
            "result": {},
        }
        fake_paths = [Path("/fake/video1.mp4")]
        with patch("app.routers.ai.get_video_paths", return_value=fake_paths), \
             patch("app.routers.ai.run_analysis"):
            client = TestClient(_make_app())
            resp = client.post("/api/ai/analyze", json={
                "channel": 1, "date": "2026-02-20",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "pending"  # Reset to pending

    def test_task_id_format(self):
        """Task ID is deterministic from channel and date."""
        fake_paths = [Path("/fake/v.mp4")]
        with patch("app.routers.ai.get_video_paths", return_value=fake_paths), \
             patch("app.routers.ai.run_analysis"):
            client = TestClient(_make_app())
            resp = client.post("/api/ai/analyze", json={
                "channel": 5, "date": "2026-03-15",
            })
            assert resp.json()["task_id"] == "analysis_5_2026-03-15"


# ---------------------------------------------------------------------------
# Analysis Status Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAnalysisStatusEndpoint:
    """GET /api/ai/analyze/{task_id} — task status retrieval."""

    def setup_method(self):
        analysis_tasks.clear()

    def teardown_method(self):
        analysis_tasks.clear()

    def test_task_not_found(self):
        client = TestClient(_make_app())
        resp = client.get("/api/ai/analyze/nonexistent_task")
        assert resp.status_code == 404
        assert "Task not found" in resp.json()["detail"]

    def test_pending_task(self):
        analysis_tasks["t1"] = {
            "status": "pending", "progress": 0,
            "message": "Starting...", "result": None,
        }
        client = TestClient(_make_app())
        resp = client.get("/api/ai/analyze/t1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["progress"] == 0

    def test_running_task(self):
        analysis_tasks["t1"] = {
            "status": "running", "progress": 55.5,
            "message": "Processing video 6/10",
        }
        client = TestClient(_make_app())
        resp = client.get("/api/ai/analyze/t1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["progress"] == pytest.approx(55.5)

    def test_complete_task_with_result(self):
        analysis_tasks["t1"] = {
            "status": "complete", "progress": 100,
            "message": "Done",
            "result": {"events": [{"type": "person"}], "total_people": 3},
        }
        client = TestClient(_make_app())
        resp = client.get("/api/ai/analyze/t1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        assert data["result"]["total_people"] == 3

    def test_failed_task(self):
        analysis_tasks["t1"] = {
            "status": "failed", "progress": 30,
            "message": "CUDA out of memory",
        }
        client = TestClient(_make_app())
        resp = client.get("/api/ai/analyze/t1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert "CUDA" in data["message"]


# ---------------------------------------------------------------------------
# Timeline Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTimelineEndpoint:
    """GET /api/ai/timeline/{channel}/{date} — analyzed timeline retrieval."""

    def setup_method(self):
        analysis_tasks.clear()

    def teardown_method(self):
        analysis_tasks.clear()

    def test_not_analyzed(self):
        client = TestClient(_make_app())
        resp = client.get("/api/ai/timeline/1/2026-02-20")
        assert resp.status_code == 404
        assert "not analyzed" in resp.json()["detail"]

    def test_analysis_in_progress(self):
        analysis_tasks["analysis_1_2026-02-20"] = {
            "status": "running", "progress": 50,
            "message": "Processing...",
        }
        client = TestClient(_make_app())
        resp = client.get("/api/ai/timeline/1/2026-02-20")
        assert resp.status_code == 202
        assert "in progress" in resp.json()["detail"]

    def test_analysis_failed(self):
        analysis_tasks["analysis_1_2026-02-20"] = {
            "status": "failed", "progress": 30,
            "message": "Error occurred",
        }
        client = TestClient(_make_app())
        resp = client.get("/api/ai/timeline/1/2026-02-20")
        assert resp.status_code == 202

    def test_complete_timeline(self):
        analysis_tasks["analysis_1_2026-02-20"] = {
            "status": "complete", "progress": 100,
            "message": "Done",
            "result": {
                "date": "2026-02-20",
                "channel": 1,
                "events": [{"type": "person", "start": 100}],
                "total_people": 5,
                "total_vehicles": 2,
                "active_hours": [8, 9, 10],
                "peak_hour": 9,
            },
        }
        client = TestClient(_make_app())
        resp = client.get("/api/ai/timeline/1/2026-02-20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_people"] == 5
        assert data["peak_hour"] == 9
        assert len(data["events"]) == 1


# ---------------------------------------------------------------------------
# Hyperlapse Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHyperlapseEndpoints:
    """Hyperlapse generation and video streaming."""

    def test_generate_no_videos(self):
        with patch("app.routers.ai.get_video_paths", return_value=[]):
            client = TestClient(_make_app())
            resp = client.post("/api/ai/hyperlapse/1/2026-02-20")
            assert resp.status_code == 404
            assert "No videos found" in resp.json()["detail"]

    def test_video_not_generated(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("app.routers.ai.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                client = TestClient(_make_app())
                resp = client.get("/api/ai/hyperlapse/1/2026-02-20/video")
                assert resp.status_code == 404
                assert "not generated" in resp.json()["detail"]

    def test_serve_existing_hyperlapse(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / ".cache" / "hyperlapse"
            cache_dir.mkdir(parents=True)
            video_path = cache_dir / "hyperlapse_ch1_2026-02-20.mp4"
            video_path.write_bytes(b"\x00\x00\x00\x1c" + b"ftyp" + b"\x00" * 50)
            with patch("app.routers.ai.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                client = TestClient(_make_app())
                resp = client.get("/api/ai/hyperlapse/1/2026-02-20/video")
                assert resp.status_code == 200
                assert resp.headers["content-type"] == "video/mp4"


# ---------------------------------------------------------------------------
# Compression Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCompressionEndpoint:
    """POST /api/ai/compression/{channel}/{date} — compression analysis."""

    def setup_method(self):
        analysis_tasks.clear()

    def teardown_method(self):
        analysis_tasks.clear()

    def test_no_prior_analysis(self):
        client = TestClient(_make_app())
        resp = client.post("/api/ai/compression/1/2026-02-20")
        assert resp.status_code == 400
        assert "Run analysis first" in resp.json()["detail"]

    def test_analysis_not_complete(self):
        analysis_tasks["analysis_1_2026-02-20"] = {
            "status": "running", "progress": 50, "message": "...",
        }
        client = TestClient(_make_app())
        resp = client.post("/api/ai/compression/1/2026-02-20")
        assert resp.status_code == 400

    def test_compression_with_complete_analysis(self):
        analysis_tasks["analysis_1_2026-02-20"] = {
            "status": "complete", "progress": 100, "message": "Done",
            "result": {
                "events": [
                    {"type": "person", "duration_seconds": 120},
                    {"type": "vehicle", "duration_seconds": 60},
                ],
            },
        }
        with tempfile.TemporaryDirectory() as td:
            # Create fake video files to measure size
            date_dir = Path(td) / "2026-02-20"
            date_dir.mkdir()
            (date_dir / "video_001.mp4").write_bytes(b"\x00" * 1024 * 1024)  # 1MB
            (date_dir / "video_002.mp4").write_bytes(b"\x00" * 2 * 1024 * 1024)  # 2MB
            with patch("app.routers.ai.get_video_paths") as mock_gvp:
                mock_gvp.return_value = [
                    date_dir / "video_001.mp4",
                    date_dir / "video_002.mp4",
                ]
                client = TestClient(_make_app())
                resp = client.post("/api/ai/compression/1/2026-02-20")
                assert resp.status_code == 200
                data = resp.json()
                assert data["channel"] == 1
                assert data["total_videos"] == 2
                assert data["total_size_mb"] == pytest.approx(3.0, abs=0.1)
                assert data["active_segments"] == 2
                assert data["active_duration_seconds"] == pytest.approx(180.0)
                assert data["potential_savings_percent"] > 99  # 180s vs 86400s


# ---------------------------------------------------------------------------
# Detect Single Frame Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDetectFrameEndpoint:
    """GET /api/ai/detect/frame/{channel}/{date}/{filename} — single frame detection."""

    def test_video_not_found(self):
        with patch("app.routers.ai.get_video_paths", return_value=[]):
            client = TestClient(_make_app())
            resp = client.get("/api/ai/detect/frame/1/2026-02-20/nonexistent.mp4")
            assert resp.status_code == 404
            assert "Video not found" in resp.json()["detail"]

    def test_video_found_but_wrong_filename(self):
        fake_paths = [Path("/fake/other_video.mp4")]
        with patch("app.routers.ai.get_video_paths", return_value=fake_paths):
            client = TestClient(_make_app())
            resp = client.get("/api/ai/detect/frame/1/2026-02-20/nonexistent.mp4")
            assert resp.status_code == 404
