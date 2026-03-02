# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 -- see LICENSE for details.
"""Tests that _tick_loop survives unhandled exceptions in _do_tick."""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import patch

import pytest

from engine.simulation.engine import SimulationEngine


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(topic, []).append(q)
        return q


pytestmark = pytest.mark.unit


class TestTickLoopResilience:
    """Verify that the tick loop continues after _do_tick raises."""

    def test_engine_survives_tick_exception(self):
        """If _do_tick raises on the first call, subsequent ticks still run."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)

        call_count = 0
        tick_success = threading.Event()

        original_do_tick = engine._do_tick

        def flaky_do_tick(dt: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated tick failure")
            # Signal that a post-error tick succeeded
            tick_success.set()
            original_do_tick(dt)

        with patch.object(engine, "_do_tick", side_effect=flaky_do_tick):
            engine._running = True
            thread = threading.Thread(target=engine._tick_loop, daemon=True)
            thread.start()
            try:
                # Wait up to 5s for a successful tick after the error
                assert tick_success.wait(timeout=5.0), (
                    "Engine did not continue ticking after exception"
                )
                assert call_count >= 2, (
                    f"Expected at least 2 calls to _do_tick, got {call_count}"
                )
            finally:
                engine._running = False
                thread.join(timeout=2.0)

    def test_error_is_logged(self, capfd):
        """The exception raised in _do_tick is logged via loguru."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)

        call_count = 0
        tick_after_error = threading.Event()
        original_do_tick = engine._do_tick
        logged_messages: list[str] = []

        def flaky_do_tick(dt: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("kaboom in tick")
            tick_after_error.set()
            original_do_tick(dt)

        from loguru import logger
        import sys

        # Add a loguru sink that captures messages
        sink_id = logger.add(
            lambda msg: logged_messages.append(str(msg)),
            level="ERROR",
            format="{message}",
        )

        try:
            with patch.object(engine, "_do_tick", side_effect=flaky_do_tick):
                engine._running = True
                thread = threading.Thread(target=engine._tick_loop, daemon=True)
                thread.start()
                try:
                    assert tick_after_error.wait(timeout=5.0)
                finally:
                    engine._running = False
                    thread.join(timeout=2.0)

            # Check that the error was logged
            combined = "\n".join(logged_messages)
            assert "Unhandled exception in simulation tick loop" in combined, (
                f"Expected error log not found. Logged: {combined}"
            )
            assert "kaboom in tick" in combined, (
                f"Expected exception message not in logs. Logged: {combined}"
            )
        finally:
            logger.remove(sink_id)

    def test_multiple_errors_dont_kill_loop(self):
        """Even multiple consecutive errors don't stop the loop."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)

        call_count = 0
        success_event = threading.Event()
        original_do_tick = engine._do_tick

        def multi_fail_do_tick(dt: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise ValueError(f"error #{call_count}")
            success_event.set()
            original_do_tick(dt)

        with patch.object(engine, "_do_tick", side_effect=multi_fail_do_tick):
            engine._running = True
            thread = threading.Thread(target=engine._tick_loop, daemon=True)
            thread.start()
            try:
                assert success_event.wait(timeout=10.0), (
                    "Engine did not recover after multiple exceptions"
                )
                assert call_count >= 4
            finally:
                engine._running = False
                thread.join(timeout=2.0)
