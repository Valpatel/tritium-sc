# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for ThoughtCollector — observable thought stream.

Tests the local ThoughtCollector class from graphlings.thought_stream.
No SDK dependency — this is a standalone component.
"""
from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock

import pytest

from graphlings.thought_stream import ThoughtCollector


# ── ThoughtCollector basics ──────────────────────────────────────


class TestThoughtCollector:
    """ThoughtCollector accumulates thoughts and supports filtering."""

    def test_create_empty(self):
        tc = ThoughtCollector(max_history=10)
        assert tc.get_recent() == []

    def test_record_thought(self):
        tc = ThoughtCollector(max_history=10)
        tc.record(
            soul_id="soul-1",
            thought="I see a tree.",
            action="observe",
            emotion="curious",
            layer=3,
            model="qwen2.5:1.5b",
        )
        recent = tc.get_recent()
        assert len(recent) == 1
        assert recent[0]["soul_id"] == "soul-1"
        assert recent[0]["thought"] == "I see a tree."
        assert recent[0]["action"] == "observe"
        assert recent[0]["emotion"] == "curious"
        assert recent[0]["layer"] == 3
        assert recent[0]["model"] == "qwen2.5:1.5b"
        assert "timestamp" in recent[0]

    def test_max_history_enforced(self):
        tc = ThoughtCollector(max_history=3)
        for i in range(5):
            tc.record(soul_id=f"s-{i}", thought=f"thought {i}")
        recent = tc.get_recent()
        assert len(recent) == 3
        # Should keep the 3 most recent
        assert recent[0]["soul_id"] == "s-2"
        assert recent[2]["soul_id"] == "s-4"

    def test_get_recent_for_soul(self):
        tc = ThoughtCollector(max_history=20)
        tc.record(soul_id="soul-1", thought="hello")
        tc.record(soul_id="soul-2", thought="world")
        tc.record(soul_id="soul-1", thought="again")
        recent = tc.get_recent(soul_id="soul-1")
        assert len(recent) == 2
        assert all(r["soul_id"] == "soul-1" for r in recent)

    def test_get_recent_limit(self):
        tc = ThoughtCollector(max_history=100)
        for i in range(10):
            tc.record(soul_id="s", thought=f"t-{i}")
        recent = tc.get_recent(limit=3)
        assert len(recent) == 3


# ── EventBus integration ────────────────────────────────────────


class TestEventBusPublishing:
    """Thoughts are published to the EventBus when recorded."""

    def test_publish_on_record(self):
        event_bus = MagicMock()
        tc = ThoughtCollector(max_history=10, event_bus=event_bus)
        tc.record(soul_id="soul-1", thought="thinking", action="observe")

        event_bus.publish.assert_called_once()
        call_args = event_bus.publish.call_args
        assert call_args[0][0] == "graphling_thought"
        data = call_args[1]["data"]
        assert data["soul_id"] == "soul-1"
        assert data["thought"] == "thinking"

    def test_no_publish_without_event_bus(self):
        # No event_bus -> should not raise
        tc = ThoughtCollector(max_history=10)
        tc.record(soul_id="soul-1", thought="no crash")
        assert len(tc.get_recent()) == 1


# ── Status builder ───────────────────────────────────────────────


class TestStatusBuilder:
    """Per-graphling status endpoint returns rich observable data."""

    def test_build_status(self):
        tc = ThoughtCollector(max_history=20)
        tc.record(soul_id="soul-1", thought="hello", emotion="happy")
        tc.record(soul_id="soul-1", thought="world", action="say")

        status = tc.build_status(
            soul_id="soul-1",
            deployed_info={"role_name": "Scout", "position": (100, 200)},
            compute_stats={"think_count": 5, "total_latency": 2.5},
        )
        assert status["soul_id"] == "soul-1"
        assert status["role_name"] == "Scout"
        assert len(status["recent_thoughts"]) == 2
        assert status["compute_stats"]["think_count"] == 5

    def test_build_status_unknown_soul(self):
        tc = ThoughtCollector(max_history=20)
        status = tc.build_status(
            soul_id="unknown",
            deployed_info=None,
            compute_stats={},
        )
        assert status["soul_id"] == "unknown"
        assert status["recent_thoughts"] == []
        assert status["deployed"] is False


# ── Thread safety ────────────────────────────────────────────────


class TestThoughtCollectorThreadSafety:
    """ThoughtCollector is thread-safe for concurrent recording."""

    def test_concurrent_records(self):
        tc = ThoughtCollector(max_history=200)
        errors = []

        def record_batch(prefix: str, count: int):
            try:
                for i in range(count):
                    tc.record(soul_id=f"{prefix}-{i}", thought=f"t-{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_batch, args=(f"t{i}", 20))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(tc.get_recent()) == 100
