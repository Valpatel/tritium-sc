# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TargetReappearanceMonitor."""

import time
from unittest.mock import MagicMock

import pytest

from tritium_lib.tracking.target_reappearance import (
    TargetReappearanceMonitor,
    DepartureRecord,
    ReappearanceEvent,
    _format_duration,
)


class TestFormatDuration:
    def test_seconds(self):
        assert _format_duration(30) == "30s"

    def test_minutes(self):
        assert _format_duration(120) == "2m"

    def test_minutes_and_seconds(self):
        assert _format_duration(90) == "1m 30s"

    def test_hours(self):
        assert _format_duration(7200) == "2h"

    def test_hours_and_minutes(self):
        assert _format_duration(3900) == "1h 5m"


class TestReappearanceEvent:
    def test_to_dict(self):
        event = ReappearanceEvent(
            target_id="ble_aabbccddeeff",
            name="Matt's Phone",
            source="ble",
            asset_type="phone",
            absence_seconds=900.0,
            last_position=(10.0, 20.0),
            return_position=(30.0, 40.0),
        )
        d = event.to_dict()
        assert d["target_id"] == "ble_aabbccddeeff"
        assert d["absence_seconds"] == 900.0
        assert "15m" in d["absence_human"]
        assert "returned after" in d["message"]
        assert d["last_position"]["x"] == 10.0
        assert d["return_position"]["x"] == 30.0


class TestTargetReappearanceMonitor:
    def test_no_reappearance_without_departure(self):
        monitor = TargetReappearanceMonitor()
        result = monitor.check_reappearance("ble_123")
        assert result is None

    def test_reappearance_after_departure(self):
        monitor = TargetReappearanceMonitor(min_absence_seconds=0.01)

        # Record departure
        monitor.record_departure(
            target_id="ble_aabbcc",
            name="Test Phone",
            source="ble",
            asset_type="phone",
            last_position=(10.0, 20.0),
        )

        # Wait a bit for absence
        time.sleep(0.02)

        # Check reappearance
        event = monitor.check_reappearance(
            target_id="ble_aabbcc",
            name="Test Phone",
            source="ble",
            position=(30.0, 40.0),
        )
        assert event is not None
        assert event.target_id == "ble_aabbcc"
        assert event.absence_seconds >= 0.01

    def test_no_reappearance_if_too_brief(self):
        monitor = TargetReappearanceMonitor(min_absence_seconds=1000.0)

        monitor.record_departure(target_id="ble_brief")
        event = monitor.check_reappearance(target_id="ble_brief")
        assert event is None

    def test_departure_only_once(self):
        monitor = TargetReappearanceMonitor(min_absence_seconds=0.01)
        monitor.record_departure(target_id="ble_once")
        time.sleep(0.02)

        event1 = monitor.check_reappearance(target_id="ble_once")
        assert event1 is not None

        # Second check should find nothing (departure consumed)
        event2 = monitor.check_reappearance(target_id="ble_once")
        assert event2 is None

    def test_event_bus_publish(self):
        bus = MagicMock()
        monitor = TargetReappearanceMonitor(
            event_bus=bus,
            min_absence_seconds=0.01,
        )
        monitor.record_departure(target_id="ble_pub")
        time.sleep(0.02)

        monitor.check_reappearance(target_id="ble_pub")
        bus.publish.assert_called_once()
        args = bus.publish.call_args
        assert args[0][0] == "target:reappearance"

    def test_get_recent_events(self):
        monitor = TargetReappearanceMonitor(min_absence_seconds=0.01)
        monitor.record_departure(target_id="ble_recent")
        time.sleep(0.02)
        monitor.check_reappearance(target_id="ble_recent")

        events = monitor.get_recent_events()
        assert len(events) == 1
        assert events[0]["target_id"] == "ble_recent"

    def test_get_departed(self):
        monitor = TargetReappearanceMonitor()
        monitor.record_departure(target_id="ble_dep1", name="Phone1")
        monitor.record_departure(target_id="ble_dep2", name="Phone2")

        departed = monitor.get_departed()
        assert len(departed) == 2

    def test_stats(self):
        monitor = TargetReappearanceMonitor(min_absence_seconds=0.01)
        monitor.record_departure(target_id="ble_stats")
        time.sleep(0.02)
        monitor.check_reappearance(target_id="ble_stats")

        stats = monitor.stats
        assert stats["total_departures"] == 1
        assert stats["total_reappearances"] == 1
        assert stats["currently_departed"] == 0

    def test_max_departures_eviction(self):
        monitor = TargetReappearanceMonitor(max_tracked_departures=3)
        for i in range(5):
            monitor.record_departure(target_id=f"ble_{i}")
        assert len(monitor._departed) <= 3
