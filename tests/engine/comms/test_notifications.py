# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for NotificationManager — cross-plugin notification system.

Tests add/get/mark_read operations, EventBus auto-subscription, WebSocket
broadcast callback, and thread safety.
"""
from __future__ import annotations

import time
import threading

import pytest

from engine.comms.notifications import NotificationManager, Notification
from engine.comms.event_bus import EventBus


@pytest.mark.unit
class TestNotificationBasics:
    """Core CRUD operations."""

    def test_add_returns_id(self):
        mgr = NotificationManager()
        nid = mgr.add("Test", "Hello", severity="info", source="test")
        assert isinstance(nid, str)
        assert len(nid) == 12

    def test_add_and_get_all(self):
        mgr = NotificationManager()
        mgr.add("Title1", "Msg1", severity="info", source="s1")
        mgr.add("Title2", "Msg2", severity="warning", source="s2")
        all_notifs = mgr.get_all()
        assert len(all_notifs) == 2
        # Newest first
        assert all_notifs[0]["title"] == "Title2"
        assert all_notifs[1]["title"] == "Title1"

    def test_get_unread(self):
        mgr = NotificationManager()
        mgr.add("A", "a", source="x")
        nid = mgr.add("B", "b", source="x")
        mgr.mark_read(nid)
        unread = mgr.get_unread()
        assert len(unread) == 1
        assert unread[0]["title"] == "A"

    def test_mark_read(self):
        mgr = NotificationManager()
        nid = mgr.add("Test", "msg", source="x")
        assert mgr.mark_read(nid) is True
        assert mgr.count_unread() == 0

    def test_mark_read_nonexistent(self):
        mgr = NotificationManager()
        assert mgr.mark_read("nonexistent") is False

    def test_mark_all_read(self):
        mgr = NotificationManager()
        mgr.add("A", "a", source="x")
        mgr.add("B", "b", source="x")
        mgr.add("C", "c", source="x")
        count = mgr.mark_all_read()
        assert count == 3
        assert mgr.count_unread() == 0

    def test_count_unread(self):
        mgr = NotificationManager()
        assert mgr.count_unread() == 0
        mgr.add("A", "a", source="x")
        mgr.add("B", "b", source="x")
        assert mgr.count_unread() == 2

    def test_severity_defaults_to_info(self):
        mgr = NotificationManager()
        mgr.add("T", "m", severity="bogus", source="x")
        notifs = mgr.get_all()
        assert notifs[0]["severity"] == "info"

    def test_entity_id(self):
        mgr = NotificationManager()
        mgr.add("T", "m", source="x", entity_id="target-42")
        notifs = mgr.get_all()
        assert notifs[0]["entity_id"] == "target-42"

    def test_get_all_with_limit(self):
        mgr = NotificationManager()
        for i in range(10):
            mgr.add(f"T{i}", f"m{i}", source="x")
        assert len(mgr.get_all(limit=5)) == 5

    def test_get_all_with_since(self):
        mgr = NotificationManager()
        mgr.add("Old", "old", source="x")
        cutoff = time.time() + 0.01
        time.sleep(0.02)
        mgr.add("New", "new", source="x")
        result = mgr.get_all(since=cutoff)
        assert len(result) == 1
        assert result[0]["title"] == "New"

    def test_max_notifications_cap(self):
        mgr = NotificationManager(max_notifications=5)
        for i in range(10):
            mgr.add(f"T{i}", f"m{i}", source="x")
        assert len(mgr.get_all(limit=100)) == 5


@pytest.mark.unit
class TestNotificationDataclass:
    """Notification dataclass tests."""

    def test_to_dict(self):
        n = Notification(
            id="abc123",
            title="Test",
            message="Hello",
            severity="info",
            source="unit-test",
            timestamp=1234567890.0,
        )
        d = n.to_dict()
        assert d["id"] == "abc123"
        assert d["title"] == "Test"
        assert d["read"] is False
        assert d["entity_id"] is None

    def test_to_dict_with_entity(self):
        n = Notification(
            id="abc123",
            title="Test",
            message="Hello",
            severity="warning",
            source="geofence",
            timestamp=1234567890.0,
            entity_id="target-99",
        )
        d = n.to_dict()
        assert d["entity_id"] == "target-99"
        assert d["severity"] == "warning"


@pytest.mark.unit
class TestNotificationEventBus:
    """Auto-subscription to EventBus events."""

    def test_auto_creates_from_threat_escalation(self):
        bus = EventBus()
        mgr = NotificationManager(event_bus=bus)
        try:
            bus.publish("threat_escalation", {
                "message": "Target approaching restricted zone",
                "target_id": "t-42",
            })
            # Give the listener thread time to process
            time.sleep(0.1)
            notifs = mgr.get_all()
            assert len(notifs) == 1
            assert notifs[0]["severity"] == "critical"
            assert notifs[0]["entity_id"] == "t-42"
        finally:
            mgr.stop()

    def test_auto_creates_from_geofence_enter(self):
        bus = EventBus()
        mgr = NotificationManager(event_bus=bus)
        try:
            bus.publish("geofence:enter", {
                "message": "Vehicle entered perimeter",
                "entity_id": "v-10",
            })
            time.sleep(0.1)
            notifs = mgr.get_all()
            assert len(notifs) == 1
            assert notifs[0]["severity"] == "warning"
            assert notifs[0]["entity_id"] == "v-10"
        finally:
            mgr.stop()

    def test_auto_creates_from_ble_suspicious(self):
        bus = EventBus()
        mgr = NotificationManager(event_bus=bus)
        try:
            bus.publish("ble:suspicious_device", {
                "message": "Unknown BLE device detected",
            })
            time.sleep(0.1)
            notifs = mgr.get_all()
            assert len(notifs) == 1
            assert notifs[0]["severity"] == "warning"
        finally:
            mgr.stop()

    def test_auto_creates_from_automation_alert(self):
        bus = EventBus()
        mgr = NotificationManager(event_bus=bus)
        try:
            bus.publish("automation:alert", {
                "title": "Motion detected",
                "message": "Front door motion at 03:00",
            })
            time.sleep(0.1)
            notifs = mgr.get_all()
            assert len(notifs) == 1
            assert notifs[0]["title"] == "Motion detected"
            assert notifs[0]["severity"] == "info"
        finally:
            mgr.stop()

    def test_ignores_unrelated_events(self):
        bus = EventBus()
        mgr = NotificationManager(event_bus=bus)
        try:
            bus.publish("sim_telemetry", {"x": 1, "y": 2})
            bus.publish("game_state_change", {"phase": "active"})
            time.sleep(0.1)
            assert len(mgr.get_all()) == 0
        finally:
            mgr.stop()


@pytest.mark.unit
class TestNotificationBroadcast:
    """WebSocket broadcast callback."""

    def test_broadcast_called_on_add(self):
        received = []
        mgr = NotificationManager(ws_broadcast=lambda msg: received.append(msg))
        mgr.add("Test", "Hello", source="unit-test")
        assert len(received) == 1
        assert received[0]["type"] == "notification:new"
        assert received[0]["data"]["title"] == "Test"

    def test_broadcast_error_does_not_crash(self):
        def bad_broadcast(msg):
            raise RuntimeError("WebSocket down")

        mgr = NotificationManager(ws_broadcast=bad_broadcast)
        # Should not raise
        nid = mgr.add("Test", "Hello", source="unit-test")
        assert nid is not None
        assert len(mgr.get_all()) == 1


@pytest.mark.unit
class TestNotificationThreadSafety:
    """Concurrent access to NotificationManager."""

    def test_concurrent_adds(self):
        mgr = NotificationManager()
        errors = []

        def add_many(thread_id):
            try:
                for i in range(50):
                    mgr.add(f"T{thread_id}-{i}", f"msg", source="thread")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_many, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert mgr.count_unread() == 200

    def test_concurrent_read_write(self):
        mgr = NotificationManager()
        errors = []

        def writer():
            try:
                for i in range(50):
                    mgr.add(f"W{i}", "msg", source="w")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    mgr.get_all()
                    mgr.get_unread()
                    mgr.count_unread()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
