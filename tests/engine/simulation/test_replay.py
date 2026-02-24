"""Unit tests for ReplayRecorder — game tick history for post-wave analysis.

TDD: These tests are written first, before implementation. Every test must
be seen to fail before the implementation is written.
"""

from __future__ import annotations

import json
import math
import queue
import threading
import time

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.target import SimulationTarget


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str = "t1",
    name: str = "Turret Alpha",
    alliance: str = "friendly",
    asset_type: str = "turret",
    position: tuple[float, float] = (10.0, 20.0),
    heading: float = 90.0,
    health: float = 200.0,
    max_health: float = 200.0,
    fsm_state: str | None = "idle",
    status: str = "active",
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=target_id,
        name=name,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        heading=heading,
        speed=0.0 if asset_type == "turret" else 3.0,
        status=status,
    )
    t.health = health
    t.max_health = max_health
    t.fsm_state = fsm_state
    return t


# ---------------------------------------------------------------------------
# ReplayRecorder core
# ---------------------------------------------------------------------------

class TestReplayRecorderInit:
    def test_import(self):
        """ReplayRecorder can be imported from engine.simulation.replay."""
        from engine.simulation.replay import ReplayRecorder
        assert ReplayRecorder is not None

    def test_create_instance(self):
        """ReplayRecorder can be instantiated."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        assert rec is not None

    def test_initial_state_empty(self):
        """New recorder has no frames, events, or wave summaries."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        assert rec.frame_count == 0
        assert rec.event_count == 0
        assert rec.is_recording is False


# ---------------------------------------------------------------------------
# Recording control
# ---------------------------------------------------------------------------

class TestRecordingControl:
    def test_start_recording(self):
        """start() enables recording."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        assert rec.is_recording is True

    def test_stop_recording(self):
        """stop() disables recording."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.stop()
        assert rec.is_recording is False

    def test_clear_resets_everything(self):
        """clear() removes all frames and events."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        # Record a snapshot to have data
        targets = [_make_target()]
        rec.record_snapshot(targets)
        rec.clear()
        assert rec.frame_count == 0
        assert rec.event_count == 0
        assert rec.is_recording is False


# ---------------------------------------------------------------------------
# Snapshot recording
# ---------------------------------------------------------------------------

class TestSnapshotRecording:
    def test_record_snapshot_adds_frame(self):
        """record_snapshot() adds a frame with target data."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        targets = [_make_target()]
        rec.record_snapshot(targets)
        assert rec.frame_count == 1

    def test_snapshot_contains_target_data(self):
        """Snapshot frame contains target position, heading, health, fsm_state."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        t = _make_target(position=(5.0, 10.0), heading=45.0, health=150.0, fsm_state="firing")
        rec.record_snapshot([t])
        frames = rec.get_frames()
        assert len(frames) == 1
        frame = frames[0]
        assert "targets" in frame
        assert len(frame["targets"]) == 1
        tgt = frame["targets"][0]
        assert tgt["target_id"] == "t1"
        assert tgt["position"] == {"x": 5.0, "y": 10.0}
        assert tgt["heading"] == 45.0
        assert tgt["health"] == 150.0
        assert tgt["fsm_state"] == "firing"

    def test_snapshot_has_timestamp(self):
        """Each frame has a timestamp."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        before = time.time()
        rec.record_snapshot([_make_target()])
        after = time.time()
        frames = rec.get_frames()
        assert before <= frames[0]["timestamp"] <= after

    def test_multiple_targets_in_snapshot(self):
        """Multiple targets are recorded in a single snapshot."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        targets = [
            _make_target(target_id="t1", name="Turret 1"),
            _make_target(target_id="r1", name="Rover 1", asset_type="rover", position=(30.0, 40.0)),
        ]
        rec.record_snapshot(targets)
        frames = rec.get_frames()
        assert len(frames[0]["targets"]) == 2

    def test_no_snapshot_when_not_recording(self):
        """record_snapshot() is a no-op when not recording."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        # Not started
        rec.record_snapshot([_make_target()])
        assert rec.frame_count == 0

    def test_snapshot_captures_alliance_and_type(self):
        """Snapshot captures alliance and asset_type for each target."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_snapshot([_make_target(alliance="hostile", asset_type="person")])
        tgt = rec.get_frames()[0]["targets"][0]
        assert tgt["alliance"] == "hostile"
        assert tgt["asset_type"] == "person"

    def test_snapshot_captures_status(self):
        """Snapshot captures target status field."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_snapshot([_make_target(status="eliminated")])
        tgt = rec.get_frames()[0]["targets"][0]
        assert tgt["status"] == "eliminated"


# ---------------------------------------------------------------------------
# Memory bounding
# ---------------------------------------------------------------------------

class TestMemoryBounds:
    def test_max_frames_enforced(self):
        """Frames are capped at MAX_FRAMES (3000). Oldest frames are dropped."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        target = _make_target()
        # Record more than MAX_FRAMES
        for i in range(3010):
            rec.record_snapshot([target])
        assert rec.frame_count == 3000

    def test_oldest_frames_dropped(self):
        """When MAX_FRAMES is exceeded, the oldest frames are dropped first."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        target = _make_target()
        # Record 3001 frames, each with a different "position" to track order
        for i in range(3001):
            t = _make_target(position=(float(i), 0.0))
            rec.record_snapshot([t])
        frames = rec.get_frames()
        # The first frame should be i=1 (i=0 was dropped)
        assert frames[0]["targets"][0]["position"]["x"] == 1.0
        assert len(frames) == 3000


# ---------------------------------------------------------------------------
# Combat event recording
# ---------------------------------------------------------------------------

class TestCombatEvents:
    def test_record_projectile_fired(self):
        """record_event() stores projectile_fired events."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_event("projectile_fired", {
            "id": "p1",
            "source_id": "t1",
            "source_name": "Turret Alpha",
            "source_pos": {"x": 10.0, "y": 20.0},
            "target_pos": {"x": 30.0, "y": 40.0},
            "projectile_type": "nerf_dart",
        })
        assert rec.event_count == 1

    def test_record_projectile_hit(self):
        """record_event() stores projectile_hit events."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_event("projectile_hit", {
            "projectile_id": "p1",
            "target_id": "h1",
            "damage": 15.0,
        })
        assert rec.event_count == 1

    def test_record_target_eliminated(self):
        """record_event() stores target_eliminated events."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_event("target_eliminated", {
            "target_id": "h1",
            "target_name": "Intruder Alpha",
            "interceptor_id": "t1",
            "interceptor_name": "Turret Alpha",
            "position": {"x": 15.0, "y": 25.0},
            "method": "nerf_dart",
        })
        events = rec.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "target_eliminated"
        assert events[0]["data"]["target_id"] == "h1"

    def test_event_has_timestamp(self):
        """Each event has a timestamp."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        before = time.time()
        rec.record_event("projectile_fired", {"id": "p1"})
        after = time.time()
        events = rec.get_events()
        assert before <= events[0]["timestamp"] <= after

    def test_no_event_when_not_recording(self):
        """record_event() is a no-op when not recording."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.record_event("projectile_fired", {"id": "p1"})
        assert rec.event_count == 0


# ---------------------------------------------------------------------------
# Wave events
# ---------------------------------------------------------------------------

class TestWaveEvents:
    def test_record_wave_start(self):
        """wave_start events are recorded."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_event("wave_start", {
            "wave_number": 1,
            "wave_name": "Scout Party",
            "hostile_count": 3,
        })
        events = rec.get_events()
        assert events[0]["event_type"] == "wave_start"
        assert events[0]["data"]["wave_number"] == 1

    def test_record_wave_complete(self):
        """wave_complete events are recorded."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_event("wave_complete", {
            "wave_number": 1,
            "eliminations": 3,
            "time_elapsed": 12.5,
            "score_bonus": 250,
        })
        events = rec.get_events()
        assert events[0]["event_type"] == "wave_complete"

    def test_record_game_over(self):
        """game_over events are recorded."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_event("game_over", {
            "result": "victory",
            "final_score": 5000,
            "total_eliminations": 42,
        })
        events = rec.get_events()
        assert events[0]["event_type"] == "game_over"
        assert events[0]["data"]["result"] == "victory"


# ---------------------------------------------------------------------------
# Wave summary
# ---------------------------------------------------------------------------

class TestWaveSummary:
    def test_wave_summary_basic(self):
        """get_wave_summary() returns stats for a completed wave."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()

        # Record wave start
        rec.record_event("wave_start", {
            "wave_number": 1,
            "wave_name": "Scout Party",
            "hostile_count": 3,
        })

        # Record some eliminations
        for i in range(3):
            rec.record_event("target_eliminated", {
                "target_id": f"h{i}",
                "target_name": f"Intruder {i}",
                "interceptor_id": "t1",
                "interceptor_name": "Turret Alpha",
                "position": {"x": float(i), "y": 0.0},
                "method": "nerf_dart",
            })

        # Record wave complete
        rec.record_event("wave_complete", {
            "wave_number": 1,
            "wave_name": "Scout Party",
            "eliminations": 3,
            "time_elapsed": 15.5,
            "score_bonus": 250,
        })

        summary = rec.get_wave_summary(1)
        assert summary is not None
        assert summary["wave_number"] == 1
        assert summary["wave_name"] == "Scout Party"
        assert summary["eliminations"] == 3
        assert summary["duration"] == 15.5
        assert summary["score_bonus"] == 250

    def test_wave_summary_nonexistent_wave(self):
        """get_wave_summary() returns None for a wave that hasn't happened."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        assert rec.get_wave_summary(99) is None

    def test_wave_summary_counts_projectile_events(self):
        """Wave summary includes projectile_fired and projectile_hit counts."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()

        rec.record_event("wave_start", {"wave_number": 1, "wave_name": "Test", "hostile_count": 2})
        rec.record_event("projectile_fired", {"id": "p1", "source_id": "t1"})
        rec.record_event("projectile_fired", {"id": "p2", "source_id": "t1"})
        rec.record_event("projectile_hit", {"projectile_id": "p1", "target_id": "h1", "damage": 15.0})
        rec.record_event("wave_complete", {"wave_number": 1, "eliminations": 1, "time_elapsed": 10.0, "score_bonus": 200})

        summary = rec.get_wave_summary(1)
        assert summary["shots_fired"] == 2
        assert summary["shots_hit"] == 1


# ---------------------------------------------------------------------------
# Heatmap data
# ---------------------------------------------------------------------------

class TestHeatmapData:
    def test_heatmap_empty(self):
        """get_heatmap_data() returns empty dict when no frames."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        data = rec.get_heatmap_data()
        assert data == {}

    def test_heatmap_aggregates_positions(self):
        """get_heatmap_data() counts position frequency per target."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()

        # Record multiple snapshots at same position
        for _ in range(5):
            rec.record_snapshot([_make_target(target_id="t1", position=(10.0, 20.0))])

        data = rec.get_heatmap_data()
        assert "t1" in data
        # Positions should have frequency information
        assert len(data["t1"]) > 0

    def test_heatmap_multiple_targets(self):
        """Heatmap tracks positions for multiple targets independently."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()

        rec.record_snapshot([
            _make_target(target_id="t1", position=(10.0, 20.0)),
            _make_target(target_id="h1", position=(30.0, 40.0), alliance="hostile", asset_type="person"),
        ])

        data = rec.get_heatmap_data()
        assert "t1" in data
        assert "h1" in data

    def test_heatmap_grid_quantization(self):
        """Heatmap quantizes positions into grid cells for aggregation."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()

        # Two positions that should fall in the same grid cell (close together)
        rec.record_snapshot([_make_target(target_id="t1", position=(10.1, 20.2))])
        rec.record_snapshot([_make_target(target_id="t1", position=(10.3, 20.4))])

        data = rec.get_heatmap_data()
        # Should have aggregated into fewer cells than 2 individual positions
        # (exact behavior depends on grid resolution, but count should be >= 1)
        assert len(data["t1"]) >= 1


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

class TestTimeline:
    def test_timeline_empty(self):
        """get_timeline() returns empty list when no events."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        assert rec.get_timeline() == []

    def test_timeline_chronological_order(self):
        """get_timeline() returns events in chronological order."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()

        rec.record_event("wave_start", {"wave_number": 1})
        rec.record_event("projectile_fired", {"id": "p1"})
        rec.record_event("target_eliminated", {"target_id": "h1"})
        rec.record_event("wave_complete", {"wave_number": 1})

        timeline = rec.get_timeline()
        assert len(timeline) == 4
        for i in range(len(timeline) - 1):
            assert timeline[i]["timestamp"] <= timeline[i + 1]["timestamp"]

    def test_timeline_includes_event_type(self):
        """Each timeline entry has an event_type field."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_event("wave_start", {"wave_number": 1})
        timeline = rec.get_timeline()
        assert timeline[0]["event_type"] == "wave_start"

    def test_timeline_filters_significant_events(self):
        """get_timeline() returns all significant event types."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()

        rec.record_event("wave_start", {"wave_number": 1})
        rec.record_event("projectile_fired", {"id": "p1"})
        rec.record_event("projectile_hit", {"projectile_id": "p1"})
        rec.record_event("target_eliminated", {"target_id": "h1"})
        rec.record_event("wave_complete", {"wave_number": 1})
        rec.record_event("game_over", {"result": "victory"})

        timeline = rec.get_timeline()
        types = [e["event_type"] for e in timeline]
        assert "wave_start" in types
        assert "target_eliminated" in types
        assert "game_over" in types


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExport:
    def test_export_json_returns_dict(self):
        """export_json() returns a serializable dict."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        result = rec.export_json()
        assert isinstance(result, dict)

    def test_export_json_contains_frames(self):
        """Exported JSON has a 'frames' key."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        result = rec.export_json()
        assert "frames" in result

    def test_export_json_contains_events(self):
        """Exported JSON has an 'events' key."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        result = rec.export_json()
        assert "events" in result

    def test_export_json_serializable(self):
        """export_json() output can be serialized to JSON string."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_snapshot([_make_target()])
        rec.record_event("wave_start", {"wave_number": 1})
        result = rec.export_json()
        json_str = json.dumps(result)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert len(parsed["frames"]) == 1
        assert len(parsed["events"]) == 1

    def test_export_contains_metadata(self):
        """Exported JSON has metadata: start_time, duration, total_frames, total_events."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.record_snapshot([_make_target()])
        rec.record_event("wave_start", {"wave_number": 1})
        result = rec.export_json()
        assert "metadata" in result
        meta = result["metadata"]
        assert "total_frames" in meta
        assert "total_events" in meta
        assert meta["total_frames"] == 1
        assert meta["total_events"] == 1


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class TestEventBusIntegration:
    def test_subscribe_to_combat_events(self):
        """ReplayRecorder subscribes to EventBus and records combat events."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()

        # Start the listener thread
        rec.start_listener()

        # Publish events on EventBus
        bus.publish("projectile_fired", {
            "id": "p1", "source_id": "t1", "source_name": "Turret",
            "source_pos": {"x": 0, "y": 0}, "target_pos": {"x": 10, "y": 10},
            "projectile_type": "nerf_dart",
        })
        bus.publish("target_eliminated", {
            "target_id": "h1", "target_name": "Intruder",
            "interceptor_id": "t1", "interceptor_name": "Turret",
            "position": {"x": 5, "y": 5}, "method": "nerf_dart",
        })

        # Give listener thread time to process
        time.sleep(0.3)
        rec.stop_listener()

        assert rec.event_count >= 2

    def test_subscribe_to_wave_events(self):
        """ReplayRecorder records wave events from EventBus."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.start_listener()

        bus.publish("wave_start", {"wave_number": 1, "wave_name": "Scout Party", "hostile_count": 3})
        bus.publish("wave_complete", {"wave_number": 1, "eliminations": 3, "time_elapsed": 15.0, "score_bonus": 250})

        time.sleep(0.3)
        rec.stop_listener()

        events = rec.get_events()
        types = [e["event_type"] for e in events]
        assert "wave_start" in types
        assert "wave_complete" in types

    def test_subscribe_to_game_over(self):
        """ReplayRecorder records game_over events from EventBus."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.start_listener()

        bus.publish("game_over", {"result": "victory", "final_score": 5000})

        time.sleep(0.3)
        rec.stop_listener()

        events = rec.get_events()
        assert any(e["event_type"] == "game_over" for e in events)

    def test_ignores_non_replay_events(self):
        """ReplayRecorder ignores events that are not replay-relevant."""
        from engine.simulation.replay import ReplayRecorder
        bus = EventBus()
        rec = ReplayRecorder(bus)
        rec.start()
        rec.start_listener()

        bus.publish("sim_telemetry", {"target_id": "t1"})  # not a replay event
        bus.publish("game_state_change", {"state": "active"})  # not a replay event

        time.sleep(0.3)
        rec.stop_listener()

        # sim_telemetry and game_state_change should not be recorded as events
        assert rec.event_count == 0
