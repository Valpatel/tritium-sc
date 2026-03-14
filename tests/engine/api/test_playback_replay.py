# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for playback replay SSE endpoint."""

import pytest
import time


class MockPlayback:
    """Minimal mock of TemporalPlayback for testing."""

    def __init__(self, snapshots=None):
        self._snapshots = snapshots or []

    def get_snapshots_between(self, start, end, max_count=100):
        return [
            s for s in self._snapshots
            if start <= s.get("timestamp", 0) <= end
        ][:max_count]

    def get_time_range(self):
        return {"start": 0.0, "end": 100.0, "duration_s": 100.0, "snapshot_count": len(self._snapshots)}

    def get_state_at(self, timestamp):
        return {"timestamp": timestamp, "targets": [], "events": []}

    def start_playback(self, start_time=None, speed=1.0):
        return {"status": "started"}

    def stop_playback(self):
        return {"status": "stopped"}

    def seek(self, timestamp):
        return {"status": "seeked", "timestamp": timestamp}

    def get_playback_status(self):
        return {"active": False, "time": 0.0, "speed": 1.0}

    def get_target_trajectory(self, target_id, start=None, end=None):
        return []


def _make_client(playback=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.playback import router

    app = FastAPI()
    app.include_router(router)

    if playback:
        app.state.temporal_playback = playback

    return TestClient(app)


@pytest.mark.unit
def test_replay_no_playback():
    """Replay endpoint returns error when playback not initialized."""
    client = _make_client()
    resp = client.get("/api/playback/replay?start=0&end=100")
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().split("\n") if l.startswith("data:")]
    assert len(lines) >= 1
    assert "not initialized" in lines[0].lower() or "error" in lines[0].lower()


@pytest.mark.unit
def test_replay_with_snapshots():
    """Replay returns SSE events for each snapshot."""
    now = time.time()
    snapshots = [
        {"timestamp": now, "targets": [{"id": "t1", "x": 0, "y": 0}], "events": []},
        {"timestamp": now + 0.1, "targets": [{"id": "t1", "x": 1, "y": 1}], "events": []},
        {"timestamp": now + 0.2, "targets": [{"id": "t1", "x": 2, "y": 2}], "events": []},
    ]
    pb = MockPlayback(snapshots)
    client = _make_client(pb)

    resp = client.get(f"/api/playback/replay?start={now - 1}&end={now + 1}&speed=100")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    lines = [l for l in resp.text.strip().split("\n") if l.startswith("data:")]
    # 3 data events + 1 done event
    assert len(lines) >= 3


@pytest.mark.unit
def test_replay_empty_range():
    """Replay with no snapshots returns error message."""
    pb = MockPlayback([])
    client = _make_client(pb)
    resp = client.get("/api/playback/replay?start=0&end=1")
    assert resp.status_code == 200
    assert "No snapshots" in resp.text or "error" in resp.text.lower()
