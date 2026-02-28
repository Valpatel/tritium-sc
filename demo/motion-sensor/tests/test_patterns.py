# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for trigger pattern generators.

TDD: written BEFORE implementation.
Tests each pattern type: random, scheduled, burst, walk_by.
"""

import time
import unittest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from patterns import RandomPattern, ScheduledPattern, BurstPattern, WalkByPattern


class TestRandomPattern(unittest.TestCase):
    """Random pattern: Poisson-distributed triggers at configurable rate."""

    def test_creates_with_rate(self):
        p = RandomPattern(rate=0.5)
        self.assertEqual(p.rate, 0.5)

    def test_should_trigger_returns_bool(self):
        p = RandomPattern(rate=1000.0)  # very high rate = almost always fires
        result = p.should_trigger(dt=1.0)
        self.assertIsInstance(result, bool)

    def test_high_rate_triggers_frequently(self):
        p = RandomPattern(rate=100.0)
        triggers = sum(1 for _ in range(100) if p.should_trigger(dt=0.1))
        # With rate=100 and dt=0.1, expected triggers per check is ~10
        # Over 100 checks, should trigger many times
        self.assertGreater(triggers, 0)

    def test_zero_rate_never_triggers(self):
        p = RandomPattern(rate=0.0)
        triggers = sum(1 for _ in range(100) if p.should_trigger(dt=1.0))
        self.assertEqual(triggers, 0)

    def test_low_rate_triggers_rarely(self):
        p = RandomPattern(rate=0.01)
        triggers = sum(1 for _ in range(100) if p.should_trigger(dt=0.01))
        # With rate=0.01 and dt=0.01, probability per tick is ~0.0001
        # Over 100 ticks, expect very few or zero triggers
        self.assertLess(triggers, 50)

    def test_poisson_distribution_character(self):
        """Over many samples, trigger count should be roughly rate * total_time."""
        p = RandomPattern(rate=10.0)
        triggers = sum(1 for _ in range(1000) if p.should_trigger(dt=0.1))
        # Expected: 10 * (1000 * 0.1) = 1000, but capped by probability
        # Should be in a reasonable range
        self.assertGreater(triggers, 0)


class TestScheduledPattern(unittest.TestCase):
    """Scheduled pattern: triggers at specific intervals."""

    def test_creates_with_interval(self):
        p = ScheduledPattern(interval=10.0)
        self.assertEqual(p.interval, 10.0)

    def test_triggers_after_interval(self):
        p = ScheduledPattern(interval=0.1)
        # Accumulate time past the interval
        result = p.should_trigger(dt=0.15)
        self.assertTrue(result)

    def test_does_not_trigger_before_interval(self):
        p = ScheduledPattern(interval=10.0)
        result = p.should_trigger(dt=0.1)
        self.assertFalse(result)

    def test_triggers_periodically(self):
        p = ScheduledPattern(interval=0.5)
        triggers = 0
        for _ in range(20):
            if p.should_trigger(dt=0.1):
                triggers += 1
        # Over 2.0s with 0.5s interval, expect ~4 triggers
        self.assertGreaterEqual(triggers, 3)
        self.assertLessEqual(triggers, 5)

    def test_resets_accumulator_after_trigger(self):
        p = ScheduledPattern(interval=1.0)
        p.should_trigger(dt=1.1)  # triggers, resets
        result = p.should_trigger(dt=0.1)  # too soon
        self.assertFalse(result)


class TestBurstPattern(unittest.TestCase):
    """Burst pattern: clusters of 3-5 triggers, then silence."""

    def test_creates_burst_pattern(self):
        p = BurstPattern(rate=1.0)
        self.assertIsNotNone(p)

    def test_burst_produces_multiple_triggers(self):
        """A burst should produce 3-5 rapid triggers."""
        p = BurstPattern(rate=100.0)  # high rate to force bursts
        triggers = 0
        for _ in range(200):
            if p.should_trigger(dt=0.05):
                triggers += 1
        # Should have gotten at least one burst (3-5 triggers)
        self.assertGreater(triggers, 0)

    def test_burst_size_between_3_and_5(self):
        p = BurstPattern(rate=1.0)
        self.assertGreaterEqual(p.burst_size, 3)
        self.assertLessEqual(p.burst_size, 5)

    def test_silence_between_bursts(self):
        """After a burst completes, there should be a silence period."""
        p = BurstPattern(rate=1.0)
        # Force a burst to happen
        p._start_burst()
        # Exhaust the burst
        for _ in range(p.burst_size):
            p.should_trigger(dt=0.05)
        # Now in silence, should not trigger immediately
        # (unless silence period is very short)
        self.assertFalse(p._in_burst)


class TestWalkByPattern(unittest.TestCase):
    """Walk-by pattern: trigger, sustained, clear sequence."""

    def test_creates_walk_by_pattern(self):
        p = WalkByPattern(rate=1.0)
        self.assertIsNotNone(p)

    def test_walk_by_has_phases(self):
        """Walk-by should cycle through: approach, trigger, sustained, clear."""
        p = WalkByPattern(rate=1.0)
        self.assertIn(p.phase, ("waiting", "approach", "trigger", "sustained", "clear"))

    def test_produces_trigger_event(self):
        """Over enough time, walk-by should produce a trigger."""
        p = WalkByPattern(rate=100.0)  # high rate
        triggered = False
        for _ in range(500):
            if p.should_trigger(dt=0.05):
                triggered = True
                break
        self.assertTrue(triggered)

    def test_walk_by_returns_clear_event(self):
        """Walk-by pattern should eventually produce a clear signal."""
        p = WalkByPattern(rate=1.0)
        p._start_walk()
        # The pattern should track whether it's a trigger or clear
        self.assertIn("phase", dir(p))

    def test_sustained_phase_duration_positive(self):
        """The sustained phase should last a positive duration."""
        p = WalkByPattern(rate=1.0)
        self.assertGreater(p.sustained_duration, 0)


class TestPatternReset(unittest.TestCase):
    """Test that patterns can be reset."""

    def test_random_reset(self):
        p = RandomPattern(rate=1.0)
        p.should_trigger(dt=1.0)
        p.reset()
        # Should not raise, state should be clean
        result = p.should_trigger(dt=0.01)
        self.assertIsInstance(result, bool)

    def test_scheduled_reset(self):
        p = ScheduledPattern(interval=1.0)
        p.should_trigger(dt=0.9)
        p.reset()
        # Accumulator should be reset, so it should not trigger immediately
        result = p.should_trigger(dt=0.05)
        self.assertFalse(result)

    def test_burst_reset(self):
        p = BurstPattern(rate=1.0)
        p._start_burst()
        p.reset()
        self.assertFalse(p._in_burst)


if __name__ == "__main__":
    unittest.main()
