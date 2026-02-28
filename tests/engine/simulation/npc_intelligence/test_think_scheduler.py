"""Tests for LLMThinkScheduler — rate-limited NPC thinking.

TDD: These tests are written first, before the implementation.
All LLM calls are mocked — no real Ollama calls.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.simulation.npc_intelligence.brain import NPCBrain, NPCPersonality
from engine.simulation.npc_intelligence.think_scheduler import LLMThinkScheduler


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def scheduler():
    """A scheduler with default settings."""
    s = LLMThinkScheduler(model="gemma3:4b", max_concurrent=2)
    yield s
    s.stop()


@pytest.fixture
def fast_scheduler():
    """A scheduler with very short rate limit for fast tests."""
    s = LLMThinkScheduler(model="test-model", max_concurrent=2)
    s._min_interval = 0.01  # Override for speed
    yield s
    s.stop()


@pytest.fixture
def brain():
    """A pedestrian brain for testing."""
    return NPCBrain(
        target_id="npc_test_01",
        asset_type="person",
        alliance="neutral",
        personality=NPCPersonality(curiosity=0.5, caution=0.5, sociability=0.5, aggression=0.1),
    )


@pytest.fixture
def danger_brain():
    """A brain that is in danger (for priority testing)."""
    b = NPCBrain(
        target_id="npc_danger_01",
        asset_type="person",
        alliance="neutral",
        personality=NPCPersonality(curiosity=0.5, caution=0.5, sociability=0.5, aggression=0.1),
    )
    b.set_danger(distance=5.0)
    b.memory.add_event("weapon_fired", {"distance": 5.0})
    return b


def _mock_ollama_response(action="WALK"):
    """Create a mock ollama_chat response."""
    return {
        "message": {
            "content": action,
        }
    }


# ============================================================================
# Construction tests
# ============================================================================

class TestSchedulerConstruction:

    def test_create_default(self):
        s = LLMThinkScheduler()
        assert s.pending_count == 0
        assert s.healthy is True
        s.stop()

    def test_create_with_model(self):
        s = LLMThinkScheduler(model="llama3:8b")
        assert s._model == "llama3:8b"
        s.stop()

    def test_create_with_max_concurrent(self):
        s = LLMThinkScheduler(max_concurrent=4)
        assert s._max_concurrent == 4
        s.stop()


# ============================================================================
# Lifecycle tests
# ============================================================================

class TestSchedulerLifecycle:

    def test_start_stop(self, scheduler):
        scheduler.start()
        assert scheduler._running is True
        scheduler.stop()
        assert scheduler._running is False

    def test_double_start(self, scheduler):
        scheduler.start()
        scheduler.start()  # Should not crash
        assert scheduler._running is True

    def test_double_stop(self, scheduler):
        scheduler.start()
        scheduler.stop()
        scheduler.stop()  # Should not crash
        assert scheduler._running is False

    def test_stop_without_start(self, scheduler):
        scheduler.stop()  # Should not crash


# ============================================================================
# Schedule tests
# ============================================================================

class TestScheduleEnqueue:

    def test_schedule_increments_pending(self, scheduler, brain):
        callback = MagicMock()
        scheduler.schedule(brain, None, callback)
        assert scheduler.pending_count == 1

    def test_schedule_multiple(self, scheduler, brain):
        callback = MagicMock()
        scheduler.schedule(brain, None, callback)
        scheduler.schedule(brain, None, callback)
        scheduler.schedule(brain, None, callback)
        assert scheduler.pending_count == 3

    def test_schedule_with_entities(self, scheduler, brain):
        entities = [{"name": "E1", "alliance": "hostile", "type": "person", "distance": 10.0}]
        callback = MagicMock()
        scheduler.schedule(brain, entities, callback)
        assert scheduler.pending_count == 1


# ============================================================================
# Callback tests
# ============================================================================

class TestSchedulerCallback:

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_callback_called_on_success(self, mock_chat, fast_scheduler, brain):
        mock_chat.return_value = _mock_ollama_response("OBSERVE")
        callback = MagicMock()
        done = threading.Event()
        callback.side_effect = lambda tid, action: done.set()

        fast_scheduler.start()
        fast_scheduler.schedule(brain, None, callback)
        done.wait(timeout=5.0)

        callback.assert_called_once_with("npc_test_01", "OBSERVE")

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_callback_receives_parsed_action(self, mock_chat, fast_scheduler, brain):
        mock_chat.return_value = _mock_ollama_response("FLEE")
        callback = MagicMock()
        done = threading.Event()
        callback.side_effect = lambda tid, action: done.set()

        fast_scheduler.start()
        fast_scheduler.schedule(brain, None, callback)
        done.wait(timeout=5.0)

        callback.assert_called_once_with("npc_test_01", "FLEE")

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_multiple_callbacks(self, mock_chat, fast_scheduler):
        mock_chat.return_value = _mock_ollama_response("WALK")
        results = []
        done = threading.Event()

        def cb(tid, action):
            results.append((tid, action))
            if len(results) >= 3:
                done.set()

        brains = [
            NPCBrain(f"npc_{i}", "person", "neutral",
                     NPCPersonality(0.5, 0.5, 0.5, 0.1))
            for i in range(3)
        ]

        fast_scheduler.start()
        for b in brains:
            fast_scheduler.schedule(b, None, cb)
        done.wait(timeout=10.0)

        assert len(results) == 3
        target_ids = {r[0] for r in results}
        assert target_ids == {"npc_0", "npc_1", "npc_2"}


# ============================================================================
# Error handling tests
# ============================================================================

class TestSchedulerErrorHandling:

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_llm_failure_does_not_crash(self, mock_chat, fast_scheduler, brain):
        mock_chat.side_effect = ConnectionError("LLM down")
        callback = MagicMock()
        done = threading.Event()

        # Use a timeout to detect that the item was processed
        fast_scheduler.start()
        fast_scheduler.schedule(brain, None, callback)

        # Wait for processing
        time.sleep(1.0)
        # Should not have called callback with success
        callback.assert_not_called()
        # Scheduler should still be running
        assert fast_scheduler._running is True

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_llm_failure_marks_fallback(self, mock_chat, fast_scheduler, brain):
        mock_chat.side_effect = ConnectionError("LLM down")
        done = threading.Event()

        fast_scheduler.start()
        fast_scheduler.schedule(brain, None, lambda tid, action: None)

        # Wait for processing
        time.sleep(1.0)
        # Brain should be marked as needing fallback
        assert brain._needs_fallback is True

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_callback_exception_does_not_crash(self, mock_chat, fast_scheduler, brain):
        mock_chat.return_value = _mock_ollama_response("WALK")

        def bad_callback(tid, action):
            raise ValueError("callback bug")

        fast_scheduler.start()
        fast_scheduler.schedule(brain, None, bad_callback)

        # Wait for processing
        time.sleep(1.0)
        # Scheduler should still be running
        assert fast_scheduler._running is True


# ============================================================================
# Rate limiting tests
# ============================================================================

class TestSchedulerRateLimit:

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_min_interval_between_calls(self, mock_chat, brain):
        mock_chat.return_value = _mock_ollama_response("WALK")
        call_times = []
        original_side_effect = mock_chat.side_effect

        def track_time(*args, **kwargs):
            call_times.append(time.monotonic())
            return _mock_ollama_response("WALK")

        mock_chat.side_effect = track_time

        s = LLMThinkScheduler(model="test", max_concurrent=1)
        s._min_interval = 0.1  # 100ms for fast test
        done = threading.Event()

        count = [0]

        def cb(tid, action):
            count[0] += 1
            if count[0] >= 3:
                done.set()

        s.start()
        brains = [
            NPCBrain(f"npc_{i}", "person", "neutral",
                     NPCPersonality(0.5, 0.5, 0.5, 0.1))
            for i in range(3)
        ]
        for b in brains:
            s.schedule(b, None, cb)

        done.wait(timeout=10.0)
        s.stop()

        # Check that calls were spaced by at least min_interval
        assert len(call_times) >= 3
        for i in range(1, len(call_times)):
            gap = call_times[i] - call_times[i - 1]
            # Allow small tolerance (10ms)
            assert gap >= 0.08, f"Gap {gap:.3f}s too small (min 0.1s)"


# ============================================================================
# Concurrency tests
# ============================================================================

class TestSchedulerConcurrency:

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_max_concurrent_workers(self, mock_chat):
        concurrent_count = [0]
        max_seen = [0]
        lock = threading.Lock()
        all_done = threading.Event()
        completed = [0]

        def slow_llm(*args, **kwargs):
            with lock:
                concurrent_count[0] += 1
                max_seen[0] = max(max_seen[0], concurrent_count[0])
            time.sleep(0.1)
            with lock:
                concurrent_count[0] -= 1
            return _mock_ollama_response("WALK")

        mock_chat.side_effect = slow_llm

        s = LLMThinkScheduler(model="test", max_concurrent=2)
        s._min_interval = 0.0  # No rate limit for concurrency test

        def cb(tid, action):
            completed[0] += 1
            if completed[0] >= 6:
                all_done.set()

        s.start()
        brains = [
            NPCBrain(f"npc_{i}", "person", "neutral",
                     NPCPersonality(0.5, 0.5, 0.5, 0.1))
            for i in range(6)
        ]
        for b in brains:
            s.schedule(b, None, cb)

        all_done.wait(timeout=10.0)
        s.stop()

        assert max_seen[0] <= 2, f"Max concurrent was {max_seen[0]}, expected <= 2"


# ============================================================================
# Priority tests
# ============================================================================

class TestSchedulerPriority:

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_danger_npcs_processed_first(self, mock_chat, fast_scheduler, brain, danger_brain):
        mock_chat.return_value = _mock_ollama_response("WALK")
        order = []
        done = threading.Event()

        def cb(tid, action):
            order.append(tid)
            if len(order) >= 2:
                done.set()

        # Schedule calm brain first, then danger brain
        fast_scheduler.schedule(brain, None, cb)
        fast_scheduler.schedule(danger_brain, None, cb)
        fast_scheduler.start()

        done.wait(timeout=5.0)

        # Danger brain should be processed first despite being enqueued second
        assert order[0] == "npc_danger_01"


# ============================================================================
# Queue management tests
# ============================================================================

class TestSchedulerQueue:

    def test_pending_count(self, scheduler, brain):
        assert scheduler.pending_count == 0
        scheduler.schedule(brain, None, lambda tid, act: None)
        assert scheduler.pending_count == 1

    def test_queue_max_size(self, scheduler):
        callback = MagicMock()
        # Queue max is 50 — fill beyond that
        for i in range(60):
            b = NPCBrain(f"npc_{i}", "person", "neutral",
                         NPCPersonality(0.5, 0.5, 0.5, 0.1))
            scheduler.schedule(b, None, callback)

        assert scheduler.pending_count <= 50

    def test_queue_drops_oldest(self, scheduler):
        callback = MagicMock()
        # Fill with 50 items
        for i in range(50):
            b = NPCBrain(f"old_{i}", "person", "neutral",
                         NPCPersonality(0.5, 0.5, 0.5, 0.1))
            scheduler.schedule(b, None, callback)

        # Add 5 more — oldest 5 should be dropped
        for i in range(5):
            b = NPCBrain(f"new_{i}", "person", "neutral",
                         NPCPersonality(0.5, 0.5, 0.5, 0.1))
            scheduler.schedule(b, None, callback)

        assert scheduler.pending_count == 50

    def test_healthy_when_small_queue(self, scheduler):
        assert scheduler.healthy is True

    def test_healthy_when_queue_not_overflowing(self, scheduler, brain):
        for i in range(10):
            b = NPCBrain(f"npc_{i}", "person", "neutral",
                         NPCPersonality(0.5, 0.5, 0.5, 0.1))
            scheduler.schedule(b, None, lambda tid, act: None)
        assert scheduler.healthy is True

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_pending_decreases_after_processing(self, mock_chat, fast_scheduler, brain):
        mock_chat.return_value = _mock_ollama_response("WALK")
        done = threading.Event()

        fast_scheduler.schedule(brain, None, lambda tid, act: done.set())
        assert fast_scheduler.pending_count == 1

        fast_scheduler.start()
        done.wait(timeout=5.0)

        # Small delay for queue item to be removed
        time.sleep(0.1)
        assert fast_scheduler.pending_count == 0


# ============================================================================
# Mark thought tests
# ============================================================================

class TestSchedulerMarkThought:

    @patch("engine.simulation.npc_intelligence.think_scheduler.ollama_chat")
    def test_brain_mark_thought_called(self, mock_chat, fast_scheduler, brain):
        mock_chat.return_value = _mock_ollama_response("WALK")
        done = threading.Event()

        old_think_time = brain._last_think_time

        fast_scheduler.start()
        fast_scheduler.schedule(brain, None, lambda tid, act: done.set())
        done.wait(timeout=5.0)

        # mark_thought should have been called
        assert brain._last_think_time > old_think_time
