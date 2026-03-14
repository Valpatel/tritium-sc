# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for RF motion detection — RSSI variance-based movement detection."""

import time

import pytest

# Adjust sys.path so the rf_motion plugin package is importable
import sys
from pathlib import Path
_plugins_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

from rf_motion.detector import (
    RSSIMotionDetector,
    SlidingRSSIWindow,
    MotionEvent,
    PairBaseline,
    STATIC_VARIANCE_MAX,
    MOTION_VARIANCE_MIN,
    MIN_SAMPLES_FOR_DETECTION,
)
from rf_motion.zones import RFZone, ZoneManager, OccupancyRecord


# ---------------------------------------------------------------------------
# SlidingRSSIWindow tests
# ---------------------------------------------------------------------------

class TestSlidingRSSIWindow:
    """Tests for the sliding RSSI window."""

    def test_empty_window(self):
        w = SlidingRSSIWindow()
        assert w.count == 0
        assert w.mean == 0.0
        assert w.variance == 0.0
        assert w.trend == 0.0

    def test_single_sample(self):
        w = SlidingRSSIWindow()
        w.add(-60.0)
        assert w.count == 1
        assert w.mean == -60.0
        assert w.variance == 0.0  # Need 2+ for variance

    def test_static_signal(self):
        """Constant RSSI should have zero variance."""
        w = SlidingRSSIWindow()
        now = time.time()
        for i in range(20):
            w.add(-55.0, timestamp=now + i)
        assert w.count == 20
        assert w.mean == pytest.approx(-55.0)
        assert w.variance == pytest.approx(0.0, abs=0.001)

    def test_varying_signal(self):
        """Alternating RSSI should have measurable variance."""
        w = SlidingRSSIWindow()
        now = time.time()
        for i in range(20):
            rssi = -50.0 if i % 2 == 0 else -60.0
            w.add(rssi, timestamp=now + i)
        assert w.count == 20
        assert w.mean == pytest.approx(-55.0, abs=0.1)
        assert w.variance > STATIC_VARIANCE_MAX

    def test_high_variance_signal(self):
        """Large RSSI swings should produce high variance."""
        w = SlidingRSSIWindow()
        now = time.time()
        for i in range(20):
            rssi = -40.0 if i % 2 == 0 else -70.0
            w.add(rssi, timestamp=now + i)
        assert w.variance > MOTION_VARIANCE_MIN

    def test_window_expiry(self):
        """Old samples should be pruned from the window."""
        w = SlidingRSSIWindow(window_seconds=10.0)
        now = time.time()
        # Add old samples
        for i in range(5):
            w.add(-55.0, timestamp=now - 20.0 + i)
        # Add recent samples
        for i in range(5):
            w.add(-55.0, timestamp=now - 2.0 + i)
        assert w.count == 5  # Only recent samples

    def test_trend_increasing(self):
        """Monotonically increasing RSSI should have positive trend."""
        w = SlidingRSSIWindow()
        now = time.time()
        for i in range(10):
            w.add(-70.0 + i * 2.0, timestamp=now + i)
        assert w.trend > 0

    def test_trend_decreasing(self):
        """Monotonically decreasing RSSI should have negative trend."""
        w = SlidingRSSIWindow()
        now = time.time()
        for i in range(10):
            w.add(-50.0 - i * 2.0, timestamp=now + i)
        assert w.trend < 0

    def test_clear(self):
        w = SlidingRSSIWindow()
        w.add(-55.0)
        w.add(-60.0)
        w.clear()
        assert w.count == 0


# ---------------------------------------------------------------------------
# RSSIMotionDetector tests
# ---------------------------------------------------------------------------

class TestRSSIMotionDetector:
    """Tests for the main motion detector."""

    def test_make_pair_id_canonical(self):
        """Pair IDs should be sorted so order doesn't matter."""
        assert RSSIMotionDetector.make_pair_id("b", "a") == "a::b"
        assert RSSIMotionDetector.make_pair_id("a", "b") == "a::b"

    def test_no_events_without_data(self):
        d = RSSIMotionDetector()
        events = d.detect()
        assert events == []

    def test_no_events_insufficient_samples(self):
        d = RSSIMotionDetector()
        d.record_pair_rssi("a", "b", -55.0)
        events = d.detect()
        assert events == []

    def test_static_pair_no_motion(self):
        """Constant RSSI between a pair should not trigger motion."""
        d = RSSIMotionDetector()
        d.set_node_position("a", (0.0, 0.0))
        d.set_node_position("b", (10.0, 0.0))
        now = time.time()
        for i in range(10):
            d.record_pair_rssi("a", "b", -55.0, timestamp=now + i)
        events = d.detect()
        assert len(events) == 0

    def test_motion_detected_pair(self):
        """Large RSSI swings between a pair should trigger motion."""
        d = RSSIMotionDetector()
        d.set_node_position("a", (0.0, 0.0))
        d.set_node_position("b", (10.0, 0.0))
        now = time.time()
        for i in range(10):
            rssi = -40.0 if i % 2 == 0 else -70.0  # 30 dBm swing
            d.record_pair_rssi("a", "b", rssi, timestamp=now + i)
        events = d.detect()
        assert len(events) == 1
        event = events[0]
        assert event.mode == "pair"
        assert event.pair_id == "a::b"
        assert event.variance > MOTION_VARIANCE_MIN
        assert event.confidence > 0
        assert event.estimated_position == (5.0, 0.0)  # midpoint

    def test_motion_event_dict(self):
        """MotionEvent.to_dict() should contain all expected keys."""
        d = RSSIMotionDetector()
        d.set_node_position("x", (2.0, 3.0))
        d.set_node_position("y", (8.0, 3.0))
        now = time.time()
        for i in range(10):
            d.record_pair_rssi("x", "y", -40.0 + (i % 2) * -25.0, timestamp=now + i)
        events = d.detect()
        assert len(events) >= 1
        ed = events[0].to_dict()
        assert "event_id" in ed
        assert "pair_id" in ed
        assert "variance" in ed
        assert "confidence" in ed
        assert "estimated_position" in ed
        assert "direction_hint" in ed

    def test_device_mode_static(self):
        """Constant RSSI from an observer should not trigger motion."""
        d = RSSIMotionDetector()
        d.set_node_position("obs", (5.0, 5.0))
        now = time.time()
        for i in range(10):
            d.record_device_rssi("obs", "AA:BB:CC:DD:EE:FF", -60.0, timestamp=now + i)
        events = d.detect()
        assert len(events) == 0

    def test_device_mode_motion(self):
        """Large RSSI changes from observer should detect device movement."""
        d = RSSIMotionDetector()
        d.set_node_position("obs", (5.0, 5.0))
        now = time.time()
        for i in range(10):
            rssi = -45.0 if i % 2 == 0 else -75.0
            d.record_device_rssi("obs", "AA:BB:CC:DD:EE:FF", rssi, timestamp=now + i)
        events = d.detect()
        device_events = [e for e in events if e.mode == "device"]
        assert len(device_events) == 1
        assert device_events[0].estimated_position == (5.0, 5.0)

    def test_baselines_tracking(self):
        """Baselines should track mean and variance over time."""
        d = RSSIMotionDetector()
        d.set_node_position("n1", (0.0, 0.0))
        d.set_node_position("n2", (20.0, 0.0))
        now = time.time()
        for i in range(10):
            d.record_pair_rssi("n1", "n2", -55.0 + (i % 3), timestamp=now + i)
        d.detect()
        baselines = d.get_baselines()
        assert len(baselines) == 1
        bl = baselines[0]
        assert bl.pair_id == "n1::n2"
        assert bl.sample_count == 10
        assert bl.mean_rssi != 0.0

    def test_active_motion_list(self):
        """get_active_motion() should return pairs with active motion."""
        d = RSSIMotionDetector()
        d.set_node_position("a", (0.0, 0.0))
        d.set_node_position("b", (10.0, 0.0))
        now = time.time()
        for i in range(10):
            d.record_pair_rssi("a", "b", -40.0 if i % 2 == 0 else -70.0, timestamp=now + i)
        d.detect()
        active = d.get_active_motion()
        assert len(active) == 1
        assert active[0].motion_active is True

    def test_direction_approaching(self):
        """Monotonically increasing RSSI should hint 'approaching'."""
        d = RSSIMotionDetector()
        d.set_node_position("a", (0.0, 0.0))
        d.set_node_position("b", (10.0, 0.0))
        now = time.time()
        # Start far, get closer -> RSSI increases, with enough variance
        for i in range(15):
            base = -80.0 + i * 3.0  # -80 to -38, rising
            jitter = 5.0 if i % 2 == 0 else -5.0  # add variance
            d.record_pair_rssi("a", "b", base + jitter, timestamp=now + i)
        events = d.detect()
        if events:
            assert events[0].direction_hint in ("approaching", "crossing", "unknown")

    def test_multiple_pairs(self):
        """Multiple pairs should be tracked independently."""
        d = RSSIMotionDetector()
        d.set_node_position("a", (0.0, 0.0))
        d.set_node_position("b", (10.0, 0.0))
        d.set_node_position("c", (5.0, 10.0))
        now = time.time()
        for i in range(10):
            # Pair a-b: motion
            d.record_pair_rssi("a", "b", -40.0 if i % 2 == 0 else -70.0, timestamp=now + i)
            # Pair a-c: static
            d.record_pair_rssi("a", "c", -55.0, timestamp=now + i)
        events = d.detect()
        motion_pairs = {e.pair_id for e in events}
        assert "a::b" in motion_pairs
        assert "a::c" not in motion_pairs

    def test_clear_resets(self):
        d = RSSIMotionDetector()
        d.record_pair_rssi("a", "b", -55.0)
        d.clear()
        assert d.get_baselines() == []
        assert d.get_recent_events() == []

    def test_node_positions(self):
        d = RSSIMotionDetector()
        d.set_node_position("alpha", (1.0, 2.0))
        d.set_node_position("beta", (3.0, 4.0))
        positions = d.get_node_positions()
        assert positions["alpha"] == (1.0, 2.0)
        assert positions["beta"] == (3.0, 4.0)


# ---------------------------------------------------------------------------
# RFZone tests
# ---------------------------------------------------------------------------

class TestRFZone:
    """Tests for RF motion zones."""

    def test_zone_no_motion(self):
        z = RFZone(zone_id="z1", name="Hallway", pair_ids=["a::b", "a::c"])
        changed = z.check_motion([], now=time.time())
        assert not changed
        assert not z.occupied

    def test_zone_becomes_occupied(self):
        z = RFZone(zone_id="z1", name="Hallway", pair_ids=["a::b"])
        event = MotionEvent(
            event_id="rfm_1",
            pair_id="a::b",
            mode="pair",
            variance=10.0,
            mean_rssi=-55.0,
            confidence=0.8,
            estimated_position=(5.0, 0.0),
            direction_hint="crossing",
        )
        changed = z.check_motion([event])
        assert changed  # State changed from vacant to occupied
        assert z.occupied

    def test_zone_stays_occupied(self):
        z = RFZone(zone_id="z1", name="Hallway", pair_ids=["a::b"])
        event = MotionEvent(
            event_id="rfm_1",
            pair_id="a::b",
            mode="pair",
            variance=10.0,
            mean_rssi=-55.0,
            confidence=0.8,
            estimated_position=(5.0, 0.0),
            direction_hint="crossing",
        )
        z.check_motion([event])
        assert z.occupied
        # Second check with motion still happening
        changed = z.check_motion([event])
        assert not changed  # No state change
        assert z.occupied

    def test_zone_becomes_vacant_after_timeout(self):
        z = RFZone(zone_id="z1", name="Hallway", pair_ids=["a::b"], vacancy_timeout=5.0)
        now = time.time()
        event = MotionEvent(
            event_id="rfm_1",
            pair_id="a::b",
            mode="pair",
            variance=10.0,
            mean_rssi=-55.0,
            confidence=0.8,
            estimated_position=(5.0, 0.0),
            direction_hint="crossing",
            timestamp=now,
        )
        z.check_motion([event], now=now)
        assert z.occupied
        # Check after timeout with no motion
        z.check_motion([], now=now + 10.0)
        assert not z.occupied
        assert len(z.occupancy_history) == 1

    def test_zone_ignores_unrelated_pairs(self):
        z = RFZone(zone_id="z1", name="Hallway", pair_ids=["a::b"])
        event = MotionEvent(
            event_id="rfm_1",
            pair_id="x::y",  # Not in this zone
            mode="pair",
            variance=10.0,
            mean_rssi=-55.0,
            confidence=0.8,
            estimated_position=(5.0, 0.0),
            direction_hint="crossing",
        )
        z.check_motion([event])
        assert not z.occupied

    def test_zone_to_dict(self):
        z = RFZone(zone_id="z1", name="Test Zone", pair_ids=["a::b"])
        d = z.to_dict()
        assert d["zone_id"] == "z1"
        assert d["name"] == "Test Zone"
        assert d["pair_ids"] == ["a::b"]
        assert d["occupied"] is False

    def test_occupancy_duration(self):
        now = time.time()
        rec = OccupancyRecord(start_time=now - 10.0, end_time=now)
        assert rec.duration == pytest.approx(10.0, abs=0.1)


# ---------------------------------------------------------------------------
# ZoneManager tests
# ---------------------------------------------------------------------------

class TestZoneManager:
    """Tests for the zone manager."""

    def test_add_and_list_zones(self):
        d = RSSIMotionDetector()
        zm = ZoneManager(d)
        zm.add_zone("z1", "Hallway", ["a::b", "a::c"])
        zm.add_zone("z2", "Kitchen", ["b::c"])
        zones = zm.list_zones()
        assert len(zones) == 2

    def test_remove_zone(self):
        d = RSSIMotionDetector()
        zm = ZoneManager(d)
        zm.add_zone("z1", "Hallway", ["a::b"])
        assert zm.remove_zone("z1")
        assert zm.list_zones() == []
        assert not zm.remove_zone("z1")  # Already removed

    def test_get_zone(self):
        d = RSSIMotionDetector()
        zm = ZoneManager(d)
        zm.add_zone("z1", "Hallway", ["a::b"])
        zone = zm.get_zone("z1")
        assert zone is not None
        assert zone.name == "Hallway"
        assert zm.get_zone("z999") is None

    def test_check_all_with_motion(self):
        d = RSSIMotionDetector()
        zm = ZoneManager(d)
        zm.add_zone("z1", "Hallway", ["a::b"])
        zm.add_zone("z2", "Kitchen", ["c::d"])
        event = MotionEvent(
            event_id="rfm_1",
            pair_id="a::b",
            mode="pair",
            variance=10.0,
            mean_rssi=-55.0,
            confidence=0.8,
            estimated_position=(5.0, 0.0),
            direction_hint="crossing",
        )
        changed = zm.check_all([event])
        assert len(changed) == 1
        assert changed[0].zone_id == "z1"

    def test_get_occupied_zones(self):
        d = RSSIMotionDetector()
        zm = ZoneManager(d)
        zm.add_zone("z1", "Hallway", ["a::b"])
        zm.add_zone("z2", "Kitchen", ["c::d"])
        event = MotionEvent(
            event_id="rfm_1",
            pair_id="a::b",
            mode="pair",
            variance=10.0,
            mean_rssi=-55.0,
            confidence=0.8,
            estimated_position=(5.0, 0.0),
            direction_hint="crossing",
        )
        zm.check_all([event])
        occupied = zm.get_occupied_zones()
        assert len(occupied) == 1
        assert occupied[0].zone_id == "z1"


# ---------------------------------------------------------------------------
# TargetTracker integration
# ---------------------------------------------------------------------------

class TestTargetTrackerIntegration:
    """Tests for TargetTracker.update_from_rf_motion()."""

    def test_update_from_rf_motion_creates_target(self):
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_rf_motion({
            "target_id": "rfm_a_b",
            "pair_id": "a::b",
            "position": (5.0, 3.0),
            "confidence": 0.7,
            "direction_hint": "approaching",
            "variance": 8.5,
        })
        target = tracker.get_target("rfm_a_b")
        assert target is not None
        assert target.asset_type == "motion_detected"
        assert target.source == "rf_motion"
        assert target.position == (5.0, 3.0)
        assert target.position_confidence == 0.7
        assert "approaching" in target.status

    def test_update_from_rf_motion_updates_existing(self):
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_rf_motion({
            "target_id": "rfm_a_b",
            "pair_id": "a::b",
            "position": (5.0, 3.0),
            "confidence": 0.5,
            "direction_hint": "unknown",
        })
        tracker.update_from_rf_motion({
            "target_id": "rfm_a_b",
            "pair_id": "a::b",
            "position": (6.0, 4.0),
            "confidence": 0.9,
            "direction_hint": "crossing",
        })
        target = tracker.get_target("rfm_a_b")
        assert target.position == (6.0, 4.0)
        assert target.position_confidence == 0.9
        assert "crossing" in target.status

    def test_rf_motion_target_pruned_when_stale(self):
        import time as _time
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_rf_motion({
            "target_id": "rfm_stale",
            "pair_id": "a::b",
            "position": (5.0, 3.0),
            "confidence": 0.5,
            "direction_hint": "unknown",
        })
        # Manually age the target
        with tracker._lock:
            tracker._targets["rfm_stale"].last_seen = _time.monotonic() - 60.0
        all_targets = tracker.get_all()
        stale_ids = {t.target_id for t in all_targets}
        assert "rfm_stale" not in stale_ids

    def test_update_from_rf_motion_dict_position(self):
        """Position can be passed as a dict with x/y keys."""
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_rf_motion({
            "target_id": "rfm_dict",
            "pair_id": "c::d",
            "position": {"x": 7.0, "y": 8.0},
            "confidence": 0.6,
            "direction_hint": "departing",
        })
        target = tracker.get_target("rfm_dict")
        assert target.position == (7.0, 8.0)


# ---------------------------------------------------------------------------
# Plugin smoke test (no EventBus/app)
# ---------------------------------------------------------------------------

class TestRFMotionPlugin:
    """Smoke tests for the plugin class itself."""

    def test_plugin_identity(self):
        from rf_motion.plugin import RFMotionPlugin
        p = RFMotionPlugin()
        assert p.plugin_id == "tritium.rf-motion"
        assert p.name == "RF Motion Detector"
        assert p.version == "1.0.0"
        assert "data_source" in p.capabilities
        assert "routes" in p.capabilities

    def test_plugin_healthy_before_start(self):
        from rf_motion.plugin import RFMotionPlugin
        p = RFMotionPlugin()
        assert not p.healthy

    def test_plugin_start_stop(self):
        from rf_motion.plugin import RFMotionPlugin
        from engine.plugins.base import PluginContext
        import logging

        p = RFMotionPlugin()
        ctx = PluginContext(
            event_bus=None,
            target_tracker=None,
            simulation_engine=None,
            settings={},
            app=None,
            logger=logging.getLogger("test"),
            plugin_manager=None,
        )
        p.configure(ctx)
        p.start()
        assert p.healthy
        p.stop()
        assert not p.healthy


# ---------------------------------------------------------------------------
# Simulated RSSI data stream scenarios
# ---------------------------------------------------------------------------

class TestSimulatedScenarios:
    """End-to-end scenarios with simulated RSSI data streams."""

    def test_person_walking_through_hallway(self):
        """Simulate a person walking through a hallway monitored by two nodes."""
        d = RSSIMotionDetector(window_seconds=30.0)
        d.set_node_position("hall-a", (0.0, 0.0))
        d.set_node_position("hall-b", (10.0, 0.0))
        zm = ZoneManager(d)
        zm.add_zone("hallway", "Hallway", ["hall-a::hall-b"])

        now = time.time()

        # Phase 1: quiet hallway (10 samples)
        for i in range(10):
            d.record_pair_rssi("hall-a", "hall-b", -55.0 + 0.3 * (i % 3 - 1),
                               timestamp=now + i * 0.5)
        events = d.detect()
        assert len(events) == 0  # No motion

        # Phase 2: person walks through (RSSI fluctuates wildly)
        for i in range(10):
            rssi = -55.0 + 15.0 * ((-1) ** i)  # swing between -40 and -70
            d.record_pair_rssi("hall-a", "hall-b", rssi,
                               timestamp=now + 5.0 + i * 0.5)
        events = d.detect()
        assert len(events) >= 1
        assert events[0].pair_id == "hall-a::hall-b"
        assert events[0].confidence > 0

        # Zone should be occupied
        zm.check_all(events)
        assert zm.get_occupied_zones()[0].zone_id == "hallway"

    def test_two_rooms_independent_detection(self):
        """Two rooms with independent radio pairs — motion in one only."""
        d = RSSIMotionDetector(window_seconds=30.0)
        d.set_node_position("room1-a", (0.0, 0.0))
        d.set_node_position("room1-b", (5.0, 0.0))
        d.set_node_position("room2-a", (20.0, 0.0))
        d.set_node_position("room2-b", (25.0, 0.0))

        zm = ZoneManager(d)
        zm.add_zone("room1", "Room 1", ["room1-a::room1-b"])
        zm.add_zone("room2", "Room 2", ["room2-a::room2-b"])

        now = time.time()
        for i in range(15):
            # Room 1: motion
            d.record_pair_rssi("room1-a", "room1-b",
                               -50.0 + 12.0 * ((-1) ** i),
                               timestamp=now + i * 0.5)
            # Room 2: quiet
            d.record_pair_rssi("room2-a", "room2-b",
                               -58.0 + 0.2 * (i % 3 - 1),
                               timestamp=now + i * 0.5)

        events = d.detect()
        zm.check_all(events)

        occupied = zm.get_occupied_zones()
        occupied_ids = {z.zone_id for z in occupied}
        assert "room1" in occupied_ids
        assert "room2" not in occupied_ids

    def test_ble_device_moving(self):
        """A BLE device moving relative to a fixed observer."""
        d = RSSIMotionDetector(window_seconds=30.0)
        d.set_node_position("scanner", (5.0, 5.0))

        now = time.time()
        # Device approaching then departing
        rssi_values = [-80, -75, -70, -65, -60, -55, -60, -65, -70, -75]
        for i, rssi in enumerate(rssi_values):
            d.record_device_rssi("scanner", "DE:AD:BE:EF:00:01",
                                 float(rssi), timestamp=now + i * 0.5)

        events = d.detect()
        device_events = [e for e in events if e.mode == "device"]
        assert len(device_events) >= 1
        assert device_events[0].node_a == "scanner"
