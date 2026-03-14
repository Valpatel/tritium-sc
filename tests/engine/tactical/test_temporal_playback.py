# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TemporalPlayback engine and playback API router."""

import sys
import time
from pathlib import Path

import pytest

_sc_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_sc_root / "src"))

from engine.tactical.temporal_playback import (
    TemporalPlayback,
    MapSnapshot,
    DEFAULT_MAX_SNAPSHOTS,
)


@pytest.fixture
def playback():
    return TemporalPlayback(snapshot_interval=0.0)  # no rate limiting


# -- Recording tests -------------------------------------------------------

class TestRecording:
    def test_record_snapshot(self, playback):
        targets = [{"target_id": "t1", "position": {"x": 10, "y": 20}}]
        result = playback.record_snapshot(targets, timestamp=1000.0)
        assert result is True
        assert playback.snapshot_count == 1

    def test_record_multiple(self, playback):
        for i in range(5):
            playback.record_snapshot(
                [{"target_id": f"t{i}"}], timestamp=1000.0 + i
            )
        assert playback.snapshot_count == 5

    def test_rate_limiting(self):
        pb = TemporalPlayback(snapshot_interval=10.0)
        pb.record_snapshot([{"target_id": "t1"}], timestamp=1000.0)
        # Should be rejected (within 10s interval)
        result = pb.record_snapshot([{"target_id": "t2"}], timestamp=1005.0)
        assert result is False
        assert pb.snapshot_count == 1

    def test_max_snapshots_pruning(self):
        pb = TemporalPlayback(max_snapshots=5, snapshot_interval=0.0)
        for i in range(10):
            pb.record_snapshot([{"target_id": f"t{i}"}], timestamp=1000.0 + i)
        assert pb.snapshot_count == 5


# -- Query tests -----------------------------------------------------------

class TestQueries:
    def test_get_state_at(self, playback):
        playback.record_snapshot(
            [{"target_id": "t1", "position": {"x": 10, "y": 20}}],
            timestamp=1000.0,
        )
        playback.record_snapshot(
            [{"target_id": "t2", "position": {"x": 30, "y": 40}}],
            timestamp=2000.0,
        )
        # Query at 1500 should return first snapshot
        state = playback.get_state_at(1500.0)
        assert len(state["targets"]) == 1
        assert state["targets"][0]["target_id"] == "t1"

    def test_get_state_empty(self, playback):
        state = playback.get_state_at(1000.0)
        assert state["targets"] == []
        assert state["target_count"] == 0

    def test_get_time_range(self, playback):
        playback.record_snapshot([{}], timestamp=1000.0)
        playback.record_snapshot([{}], timestamp=2000.0)
        tr = playback.get_time_range()
        assert tr["start"] == 1000.0
        assert tr["end"] == 2000.0
        assert tr["duration_s"] == 1000.0
        assert tr["snapshot_count"] == 2

    def test_get_time_range_empty(self, playback):
        tr = playback.get_time_range()
        assert tr["snapshot_count"] == 0

    def test_get_snapshots_between(self, playback):
        for i in range(10):
            playback.record_snapshot(
                [{"target_id": f"t{i}"}], timestamp=1000.0 + i * 100
            )
        snaps = playback.get_snapshots_between(1200.0, 1600.0)
        assert len(snaps) >= 3  # should get ~4 snapshots

    def test_get_snapshots_downsampled(self, playback):
        for i in range(100):
            playback.record_snapshot([{}], timestamp=1000.0 + i)
        snaps = playback.get_snapshots_between(1000.0, 1100.0, max_count=10)
        assert len(snaps) <= 10


# -- Playback control tests -----------------------------------------------

class TestPlaybackControls:
    def test_start_playback(self, playback):
        playback.record_snapshot([{}], timestamp=1000.0)
        result = playback.start_playback(speed=2.0)
        assert result["status"] == "playing"
        assert result["speed"] == 2.0

    def test_stop_playback(self, playback):
        playback.record_snapshot([{}], timestamp=1000.0)
        playback.start_playback()
        result = playback.stop_playback()
        assert result["status"] == "stopped"

    def test_seek(self, playback):
        playback.record_snapshot(
            [{"target_id": "t1"}], timestamp=1000.0
        )
        playback.record_snapshot(
            [{"target_id": "t2"}], timestamp=2000.0
        )
        result = playback.seek(1500.0)
        assert result["playback_time"] == 1500.0

    def test_playback_status(self, playback):
        status = playback.get_playback_status()
        assert status["active"] is False
        playback.record_snapshot([{}], timestamp=1000.0)
        playback.start_playback()
        status = playback.get_playback_status()
        assert status["active"] is True

    def test_start_empty(self, playback):
        result = playback.start_playback()
        assert "error" in result

    def test_speed_clamped(self, playback):
        playback.record_snapshot([{}], timestamp=1000.0)
        result = playback.start_playback(speed=999.0)
        assert result["speed"] <= 100.0


# -- Trajectory tests ------------------------------------------------------

class TestTrajectory:
    def test_get_trajectory(self, playback):
        for i in range(5):
            playback.record_snapshot(
                [{"target_id": "t1", "position": {"x": i * 10.0, "y": 0.0}}],
                timestamp=1000.0 + i * 10.0,
            )
        traj = playback.get_target_trajectory("t1")
        assert len(traj) == 5
        assert traj[0]["x"] == 0.0
        assert traj[4]["x"] == 40.0

    def test_trajectory_time_range(self, playback):
        for i in range(10):
            playback.record_snapshot(
                [{"target_id": "t1", "position": {"x": i, "y": 0}}],
                timestamp=1000.0 + i * 10.0,
            )
        traj = playback.get_target_trajectory("t1", start=1030.0, end=1070.0)
        assert len(traj) >= 3

    def test_trajectory_missing_target(self, playback):
        playback.record_snapshot(
            [{"target_id": "t1", "position": {"x": 0, "y": 0}}],
            timestamp=1000.0,
        )
        traj = playback.get_target_trajectory("nonexistent")
        assert traj == []

    def test_trajectory_with_list_position(self, playback):
        playback.record_snapshot(
            [{"target_id": "t1", "position": [5.0, 10.0]}],
            timestamp=1000.0,
        )
        traj = playback.get_target_trajectory("t1")
        assert len(traj) == 1
        assert traj[0]["x"] == 5.0
        assert traj[0]["y"] == 10.0


# -- Clear/maintenance tests -----------------------------------------------

class TestMaintenance:
    def test_clear(self, playback):
        playback.record_snapshot([{}], timestamp=1000.0)
        assert playback.snapshot_count == 1
        playback.clear()
        assert playback.snapshot_count == 0


# -- MapSnapshot tests -----------------------------------------------------

class TestMapSnapshot:
    def test_to_dict(self):
        snap = MapSnapshot(
            timestamp=1000.0,
            targets=[{"id": "t1"}],
            events=[{"type": "alert"}],
            alerts=[],
        )
        d = snap.to_dict()
        assert d["timestamp"] == 1000.0
        assert d["target_count"] == 1
        assert len(d["events"]) == 1
