# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for engine.comms.mesh_web_source.MeshWebSource.

TDD — written before implementation.
"""

from __future__ import annotations

import queue
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from engine.comms.mesh_web_source import MeshWebSource


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEventBus:
    """Lightweight EventBus stand-in that records published events."""

    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict | None = None):
        self.published.append((event_type, data))

    def subscribe(self) -> queue.Queue:
        return queue.Queue()

    def unsubscribe(self, q: queue.Queue) -> None:
        pass


class MockTargetTracker:
    """Lightweight TargetTracker stand-in that records calls."""

    def __init__(self):
        self.sim_updates: list[dict] = []
        self._targets: dict = {}

    def update_from_simulation(self, data: dict) -> None:
        self.sim_updates.append(data)

    def remove(self, target_id: str) -> bool:
        return self._targets.pop(target_id, None) is not None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus():
    return MockEventBus()


@pytest.fixture
def tracker():
    return MockTargetTracker()


@pytest.fixture
def source(event_bus, tracker):
    return MeshWebSource(
        event_bus=event_bus,
        target_tracker=tracker,
        poll_interval=60,
    )


# ===========================================================================
# Init / Config
# ===========================================================================


@pytest.mark.unit
class TestInit:
    def test_stores_config(self, source):
        assert source._poll_interval == 60

    def test_initial_state(self, source):
        assert source._running is False
        assert source._poll_count == 0
        assert source._last_error == ""
        assert len(source._known_nodes) == 0

    def test_default_poll_interval(self, event_bus, tracker):
        s = MeshWebSource(event_bus=event_bus, target_tracker=tracker)
        assert s._poll_interval == 60


# ===========================================================================
# Stats
# ===========================================================================


@pytest.mark.unit
class TestStats:
    def test_stats_returns_all_fields(self, source):
        s = source.stats
        assert s["running"] is False
        assert s["poll_count"] == 0
        assert s["nodes_known"] == 0
        assert s["last_error"] == ""

    def test_stats_reflects_changes(self, source):
        source._poll_count = 5
        source._known_nodes["n1"] = {"node_id": "n1", "seen_count": 3}
        source._last_error = "timeout"
        s = source.stats
        assert s["poll_count"] == 5
        assert s["nodes_known"] == 1
        assert s["last_error"] == "timeout"


# ===========================================================================
# Poll processing
# ===========================================================================


@pytest.mark.unit
class TestPoll:
    def test_poll_returns_nodes(self, source, event_bus):
        """Mock HTTP response should produce a parsed node list."""
        mock_nodes = [
            {
                "node_id": "web_001",
                "lat": 37.7749,
                "lng": -122.4194,
                "name": "Public Node 1",
                "protocol": "meshtastic",
                "last_seen": "2026-02-26T00:00:00Z",
            },
            {
                "node_id": "web_002",
                "lat": 37.7850,
                "lng": -122.4100,
                "name": "Public Node 2",
                "protocol": "meshcore",
                "last_seen": "2026-02-26T00:00:00Z",
            },
        ]

        with patch("engine.tactical.geo.latlng_to_local", return_value=(10.0, 20.0, 0.0)):
            source.process_poll_result(mock_nodes)

        assert source._poll_count == 1
        assert len(source._known_nodes) == 2

        events = [e for e in event_bus.published if e[0] == "mesh_web:nodes_updated"]
        assert len(events) == 1
        data = events[0][1]
        assert data["count"] == 2

    def test_nodes_registered_in_tracker(self, source, tracker):
        """Web nodes should appear in TargetTracker."""
        mock_nodes = [
            {
                "node_id": "web_010",
                "lat": 37.7749,
                "lng": -122.4194,
                "name": "Tracker Test Node",
                "protocol": "meshtastic",
                "last_seen": "2026-02-26T00:00:00Z",
            },
        ]

        with patch("engine.tactical.geo.latlng_to_local", return_value=(5.0, 15.0, 0.0)):
            source.process_poll_result(mock_nodes)

        assert len(tracker.sim_updates) == 1
        update = tracker.sim_updates[0]
        assert update["target_id"] == "meshweb_web_010"
        assert update["alliance"] == "friendly"
        assert update["asset_type"] == "mesh_radio"
        assert update["position"]["x"] == 5.0
        assert update["position"]["y"] == 15.0

    def test_web_source_metadata(self, source, tracker):
        """Web nodes should have source='web' in metadata."""
        mock_nodes = [
            {
                "node_id": "web_020",
                "lat": 37.7749,
                "lng": -122.4194,
                "name": "Metadata Test",
                "protocol": "meshtastic",
                "last_seen": "2026-02-26T00:00:00Z",
            },
        ]

        with patch("engine.tactical.geo.latlng_to_local", return_value=(0.0, 0.0, 0.0)):
            source.process_poll_result(mock_nodes)

        assert len(tracker.sim_updates) == 1
        update = tracker.sim_updates[0]
        assert update.get("metadata", {}).get("source") == "web"


# ===========================================================================
# Stale node removal
# ===========================================================================


@pytest.mark.unit
class TestStaleRemoval:
    def test_stale_nodes_removed_after_5_polls(self, source, tracker, event_bus):
        """Nodes not seen for 5 consecutive polls should be removed."""
        initial_nodes = [
            {
                "node_id": "web_050",
                "lat": 37.7749,
                "lng": -122.4194,
                "name": "Stale Test",
                "protocol": "meshtastic",
                "last_seen": "2026-02-26T00:00:00Z",
            },
        ]

        with patch("engine.tactical.geo.latlng_to_local", return_value=(0.0, 0.0, 0.0)):
            # First poll: node appears
            source.process_poll_result(initial_nodes)
            assert "web_050" in source._known_nodes

            # 5 more polls without the node
            for _ in range(5):
                source.process_poll_result([])

        # Node should have been removed
        assert "web_050" not in source._known_nodes

    def test_node_seen_again_resets_counter(self, source, tracker):
        """Node that reappears should have its stale counter reset."""
        node = {
            "node_id": "web_060",
            "lat": 37.7749,
            "lng": -122.4194,
            "name": "Resilient Node",
            "protocol": "meshtastic",
            "last_seen": "2026-02-26T00:00:00Z",
        }

        with patch("engine.tactical.geo.latlng_to_local", return_value=(0.0, 0.0, 0.0)):
            # Initial poll
            source.process_poll_result([node])

            # 3 polls without the node
            for _ in range(3):
                source.process_poll_result([])

            # Node reappears
            source.process_poll_result([node])

            # 3 more polls without the node (should NOT trigger removal yet)
            for _ in range(3):
                source.process_poll_result([])

        # Node should still be present (only 3 missed polls since last seen)
        assert "web_060" in source._known_nodes

    def test_empty_poll_does_not_crash(self, source):
        """Processing an empty poll result should not crash."""
        source.process_poll_result([])
        assert source._poll_count == 1


# ===========================================================================
# Coordinate conversion
# ===========================================================================


@pytest.mark.unit
class TestCoordinates:
    def test_latlng_converted_to_local(self, source, tracker):
        """lat/lng should be converted via geo.latlng_to_local."""
        node = {
            "node_id": "web_070",
            "lat": 38.0,
            "lng": -121.0,
            "name": "Coord Test",
            "protocol": "meshtastic",
            "last_seen": "2026-02-26T00:00:00Z",
        }

        with patch("engine.tactical.geo.latlng_to_local", return_value=(100.0, 200.0, 5.0)) as mock_geo:
            source.process_poll_result([node])
            mock_geo.assert_called_once_with(38.0, -121.0, 0.0)

        update = tracker.sim_updates[0]
        assert update["position"]["x"] == 100.0
        assert update["position"]["y"] == 200.0

    def test_zero_coords_skipped(self, source, tracker):
        """Nodes at (0,0) should be skipped."""
        node = {
            "node_id": "web_080",
            "lat": 0.0,
            "lng": 0.0,
            "name": "Zero Coord",
            "protocol": "meshtastic",
            "last_seen": "2026-02-26T00:00:00Z",
        }

        source.process_poll_result([node])
        assert len(tracker.sim_updates) == 0


# ===========================================================================
# start() / stop()
# ===========================================================================


@pytest.mark.unit
class TestStartStop:
    def test_start_sets_running(self, source):
        """start() should set running flag (polling thread would start)."""
        source.start()
        assert source._running is True
        source.stop()

    def test_stop_clears_running(self, source):
        source._running = True
        source.stop()
        assert source._running is False

    def test_start_idempotent(self, source):
        """Calling start() twice does nothing the second time."""
        source._running = True
        source.start()  # should be no-op
        source.stop()
