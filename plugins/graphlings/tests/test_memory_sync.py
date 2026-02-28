# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MemorySync — experience recording and batch sync.

TDD: Written before implementation.
"""
from __future__ import annotations

import threading
import pytest
from unittest.mock import MagicMock


def _make_mock_bridge():
    """Create a mock AgentBridge."""
    bridge = MagicMock()
    bridge.record_experiences = MagicMock(return_value=3)
    return bridge


class TestMemorySync:
    """MemorySync queues experiences and flushes to AgentBridge."""

    def test_record_event_queues_experience(self):
        from graphlings.memory_sync import MemorySync

        bridge = _make_mock_bridge()
        sync = MemorySync(bridge)
        sync.record_event("soul_1", "explosion_nearby", "Big explosion in sector 7", 0.8)

        assert sync.pending_count("soul_1") == 1

    def test_flush_sends_batch_to_bridge(self):
        from graphlings.memory_sync import MemorySync

        bridge = _make_mock_bridge()
        sync = MemorySync(bridge)
        sync.record_event("soul_1", "explosion_nearby", "Explosion", 0.8)
        sync.record_event("soul_1", "saw_drone", "Drone overhead", 0.6)
        sync.flush("soul_1")

        bridge.record_experiences.assert_called_once()
        call_args = bridge.record_experiences.call_args
        assert call_args[0][0] == "soul_1"
        experiences = call_args[0][1]
        assert len(experiences) == 2

    def test_flush_returns_count(self):
        from graphlings.memory_sync import MemorySync

        bridge = _make_mock_bridge()
        bridge.record_experiences.return_value = 2
        sync = MemorySync(bridge)
        sync.record_event("soul_1", "explosion_nearby", "Explosion", 0.8)
        sync.record_event("soul_1", "saw_drone", "Drone", 0.6)
        count = sync.flush("soul_1")

        assert count == 2

    def test_empty_flush_returns_zero(self):
        from graphlings.memory_sync import MemorySync

        bridge = _make_mock_bridge()
        sync = MemorySync(bridge)
        count = sync.flush("soul_1")

        assert count == 0
        bridge.record_experiences.assert_not_called()

    def test_flush_clears_queue(self):
        from graphlings.memory_sync import MemorySync

        bridge = _make_mock_bridge()
        sync = MemorySync(bridge)
        sync.record_event("soul_1", "event1", "desc", 0.5)
        sync.flush("soul_1")

        assert sync.pending_count("soul_1") == 0

    def test_event_type_maps_to_experience_category(self):
        from graphlings.memory_sync import MemorySync

        bridge = _make_mock_bridge()
        sync = MemorySync(bridge)
        sync.record_event("soul_1", "projectile_fired", "Shot fired nearby", 0.9)
        sync.flush("soul_1")

        experiences = bridge.record_experiences.call_args[0][1]
        assert experiences[0]["category"] == "COMBAT_WITNESS"

    def test_npc_thought_maps_to_social(self):
        from graphlings.memory_sync import MemorySync

        bridge = _make_mock_bridge()
        sync = MemorySync(bridge)
        sync.record_event("soul_1", "npc_thought", "Someone said hello", 0.5)
        sync.flush("soul_1")

        experiences = bridge.record_experiences.call_args[0][1]
        assert experiences[0]["category"] == "SOCIAL_INTERACTION"

    def test_thread_safety_concurrent_records(self):
        """Multiple threads can record events without data loss."""
        from graphlings.memory_sync import MemorySync

        bridge = _make_mock_bridge()
        sync = MemorySync(bridge)

        errors = []
        def record_many(soul_id, count):
            try:
                for i in range(count):
                    sync.record_event(soul_id, f"event_{i}", f"desc_{i}", 0.5)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_many, args=("soul_1", 50)),
            threading.Thread(target=record_many, args=("soul_1", 50)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert sync.pending_count("soul_1") == 100

    def test_bridge_error_doesnt_lose_experiences(self):
        """If bridge fails, experiences are kept in queue for retry."""
        from graphlings.memory_sync import MemorySync

        bridge = _make_mock_bridge()
        bridge.record_experiences.return_value = 0  # failure

        sync = MemorySync(bridge)
        sync.record_event("soul_1", "event1", "desc", 0.5)
        sync.record_event("soul_1", "event2", "desc", 0.5)
        count = sync.flush("soul_1")

        assert count == 0
        # Experiences should still be in queue after failed flush
        assert sync.pending_count("soul_1") == 2
