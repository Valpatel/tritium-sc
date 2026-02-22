"""Unit tests for EventBus — thread-safe pub/sub messaging.

Tests subscribe/unsubscribe, publish/receive, queue overflow (drop oldest),
thread safety, and filter parameter compatibility.
"""
from __future__ import annotations

import queue
import threading
import time

import pytest

from amy.comms.event_bus import EventBus


@pytest.mark.unit
class TestEventBusBasics:
    """Core subscribe/publish/unsubscribe functionality."""

    def test_subscribe_returns_queue(self):
        bus = EventBus()
        q = bus.subscribe()
        assert isinstance(q, queue.Queue)

    def test_publish_delivers_to_subscriber(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("test_event", {"key": "value"})
        msg = q.get_nowait()
        assert msg["type"] == "test_event"
        assert msg["data"]["key"] == "value"

    def test_publish_without_data(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("ping")
        msg = q.get_nowait()
        assert msg["type"] == "ping"
        assert "data" not in msg

    def test_multiple_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.publish("broadcast", {"msg": "hello"})
        assert q1.get_nowait()["type"] == "broadcast"
        assert q2.get_nowait()["type"] == "broadcast"

    def test_unsubscribe_stops_delivery(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.publish("after_unsub")
        assert q.empty()

    def test_unsubscribe_nonexistent_is_safe(self):
        bus = EventBus()
        q = queue.Queue()
        bus.unsubscribe(q)  # Should not raise

    def test_subscribe_with_filter_param(self):
        """subscribe() accepts optional _filter for API compatibility."""
        bus = EventBus()
        q = bus.subscribe(_filter="sim_telemetry")
        bus.publish("sim_telemetry", {"x": 1})
        bus.publish("other_event", {"x": 2})
        # Filter is ignored — both events delivered
        assert q.qsize() == 2


@pytest.mark.unit
class TestEventBusOverflow:
    """Queue overflow behavior — drop oldest message when full."""

    def test_queue_maxsize_is_100(self):
        bus = EventBus()
        q = bus.subscribe()
        assert q.maxsize == 100

    def test_overflow_drops_oldest(self):
        bus = EventBus()
        q = bus.subscribe()
        # Fill the queue
        for i in range(100):
            bus.publish("fill", {"seq": i})
        assert q.full()

        # Publish one more — should drop oldest and add new
        bus.publish("overflow", {"seq": 100})

        # Oldest should be seq=1 (seq=0 was dropped)
        first = q.get_nowait()
        assert first["data"]["seq"] == 1

    def test_overflow_does_not_lose_new_event(self):
        bus = EventBus()
        q = bus.subscribe()
        for i in range(100):
            bus.publish("fill", {"seq": i})

        bus.publish("important", {"critical": True})

        # Drain all and check last
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        assert msgs[-1]["type"] == "important"
        assert msgs[-1]["data"]["critical"] is True


@pytest.mark.unit
class TestEventBusThreadSafety:
    """Concurrent publish from multiple threads."""

    def test_concurrent_publish(self):
        bus = EventBus()
        q = bus.subscribe()
        count = 50
        errors = []

        def publisher(thread_id: int):
            try:
                for i in range(count):
                    bus.publish("thread_event", {"tid": thread_id, "seq": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=publisher, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Some may have been dropped due to overflow, but no crashes
        received = 0
        while not q.empty():
            q.get_nowait()
            received += 1
        assert received > 0

    def test_concurrent_subscribe_unsubscribe(self):
        bus = EventBus()
        errors = []

        def churn():
            try:
                for _ in range(20):
                    q = bus.subscribe()
                    bus.publish("churn")
                    bus.unsubscribe(q)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=churn) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_publish_while_subscribing(self):
        """Publish and subscribe concurrently without deadlock."""
        bus = EventBus()
        done = threading.Event()
        errors = []

        def publisher():
            try:
                for _ in range(100):
                    bus.publish("concurrent", {"val": 42})
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)
            finally:
                done.set()

        def subscriber():
            queues = []
            try:
                for _ in range(20):
                    q = bus.subscribe()
                    queues.append(q)
                    time.sleep(0.005)
                for q in queues:
                    bus.unsubscribe(q)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=publisher)
        t2 = threading.Thread(target=subscriber)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors


@pytest.mark.unit
class TestEventBusMessageFormat:
    """Verify message structure."""

    def test_message_has_type(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("some_event")
        msg = q.get_nowait()
        assert "type" in msg
        assert msg["type"] == "some_event"

    def test_message_data_optional(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("no_data")
        msg = q.get_nowait()
        assert "data" not in msg

    def test_message_data_dict(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("with_data", {"nested": {"deep": True}})
        msg = q.get_nowait()
        assert msg["data"]["nested"]["deep"] is True

    def test_empty_data_dict(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("empty_data", {})
        msg = q.get_nowait()
        assert msg["data"] == {}
