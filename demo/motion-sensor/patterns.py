# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Trigger pattern generators for the demo motion sensor.

Patterns:
  random:    Poisson-distributed triggers at configurable rate
  scheduled: Triggers at specific intervals (e.g., every 10s)
  burst:     Clusters of 3-5 triggers, then silence
  walk_by:   Simulates person walking past (trigger, sustained, clear)
"""

import math
import random


class RandomPattern:
    """Poisson-distributed triggers at a configurable rate (events/sec)."""

    def __init__(self, rate: float = 0.5):
        self.rate = rate

    def should_trigger(self, dt: float) -> bool:
        """Check if a trigger should fire given elapsed time dt.

        Uses Poisson probability: P(trigger) = 1 - e^(-rate * dt).
        """
        if self.rate <= 0:
            return False
        probability = 1.0 - math.exp(-self.rate * dt)
        return random.random() < probability

    def reset(self) -> None:
        """Reset pattern state (no-op for random)."""
        pass


class ScheduledPattern:
    """Triggers at fixed intervals."""

    def __init__(self, interval: float = 10.0):
        self.interval = interval
        self._accumulated: float = 0.0

    def should_trigger(self, dt: float) -> bool:
        """Check if interval has elapsed."""
        self._accumulated += dt
        if self._accumulated >= self.interval:
            self._accumulated -= self.interval
            return True
        return False

    def reset(self) -> None:
        """Reset the accumulator."""
        self._accumulated = 0.0


class BurstPattern:
    """Clusters of 3-5 rapid triggers, then silence.

    When a burst begins, rapid triggers fire with short inter-trigger
    delays. After the burst completes, a silence period passes before
    the next burst can begin.
    """

    def __init__(self, rate: float = 1.0):
        self.rate = rate
        self.burst_size = random.randint(3, 5)
        self._in_burst = False
        self._burst_remaining = 0
        self._accumulated: float = 0.0
        self._silence_duration: float = 0.0
        self._burst_interval: float = 0.05  # time between triggers in a burst

    def should_trigger(self, dt: float) -> bool:
        """Check if a trigger should fire."""
        self._accumulated += dt

        if self._in_burst:
            # Inside a burst: fire rapidly
            if self._accumulated >= self._burst_interval:
                self._accumulated -= self._burst_interval
                self._burst_remaining -= 1
                if self._burst_remaining <= 0:
                    self._in_burst = False
                    self._silence_duration = random.uniform(2.0, 8.0) / max(self.rate, 0.01)
                    self._accumulated = 0.0
                return True
            return False
        else:
            # Outside burst: wait for silence then start next burst
            trigger_interval = 1.0 / max(self.rate, 0.001)
            wait_time = max(self._silence_duration, trigger_interval)
            if self._accumulated >= wait_time:
                self._start_burst()
                self._accumulated = 0.0
                self._burst_remaining -= 1
                if self._burst_remaining <= 0:
                    self._in_burst = False
                return True
            return False

    def _start_burst(self) -> None:
        """Begin a new burst sequence."""
        self.burst_size = random.randint(3, 5)
        self._burst_remaining = self.burst_size
        self._in_burst = True

    def reset(self) -> None:
        """Reset burst state."""
        self._in_burst = False
        self._burst_remaining = 0
        self._accumulated = 0.0
        self._silence_duration = 0.0


class WalkByPattern:
    """Simulates a person walking past the sensor.

    Phases: waiting -> approach -> trigger -> sustained -> clear
    The trigger and clear events are the detection points.
    """

    def __init__(self, rate: float = 1.0):
        self.rate = rate
        self.phase = "waiting"
        self.sustained_duration = random.uniform(1.0, 4.0)
        self._accumulated: float = 0.0
        self._phase_duration: float = 0.0
        self._set_wait_duration()

    def _set_wait_duration(self) -> None:
        """Set the waiting period before next walk-by event."""
        self._phase_duration = max(0.1, random.expovariate(max(self.rate, 0.001)))
        self._accumulated = 0.0

    def _start_walk(self) -> None:
        """Begin a walk-by sequence."""
        self.phase = "approach"
        self._accumulated = 0.0
        self._phase_duration = random.uniform(0.5, 2.0)

    def should_trigger(self, dt: float) -> bool:
        """Advance the walk-by simulation.

        Returns True at the trigger and clear events.
        """
        self._accumulated += dt

        if self.phase == "waiting":
            if self._accumulated >= self._phase_duration:
                self._start_walk()
            return False

        elif self.phase == "approach":
            if self._accumulated >= self._phase_duration:
                self.phase = "trigger"
                self._accumulated = 0.0
                self._phase_duration = 0.0
                return True
            return False

        elif self.phase == "trigger":
            # Immediately move to sustained
            self.phase = "sustained"
            self._accumulated = 0.0
            self.sustained_duration = random.uniform(1.0, 4.0)
            self._phase_duration = self.sustained_duration
            return False

        elif self.phase == "sustained":
            if self._accumulated >= self._phase_duration:
                self.phase = "clear"
                self._accumulated = 0.0
                self._phase_duration = 0.0
                return True
            return False

        elif self.phase == "clear":
            # Reset to waiting
            self.phase = "waiting"
            self._set_wait_duration()
            return False

        return False

    def reset(self) -> None:
        """Reset to waiting."""
        self.phase = "waiting"
        self._accumulated = 0.0
        self._set_wait_duration()
