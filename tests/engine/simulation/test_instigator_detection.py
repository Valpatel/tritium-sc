# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for instigator detection in civil_unrest game mode.

Instigator detection works as follows:
  - Friendly scout units (rover, drone, scout_drone) can identify instigators
  - Identification requires sustained proximity (within detection range) for 3+ seconds
  - On identification: publishes instigator_identified event, marks target identified,
    awards 50 de-escalation score points
  - If the identifier moves away, the timer resets
  - Already-identified instigators are not re-identified
  - Turrets (stationary) cannot identify instigators
"""

from __future__ import annotations

import math
import queue
import threading

import pytest

from tritium_lib.sim_engine.core.entity import SimulationTarget
from engine.simulation.game_mode import GameMode, InstigatorDetector
from tritium_lib.sim_engine.combat.combat import CombatSystem
from engine.simulation.engine import SimulationEngine

pytestmark = pytest.mark.unit


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put({"type": topic, "data": data})

    def subscribe(self, topic: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(topic, []).append(q)
        return q


def _make_target(
    target_id: str,
    alliance: str,
    asset_type: str,
    position: tuple[float, float],
    crowd_role: str | None = None,
    speed: float = 1.0,
) -> SimulationTarget:
    """Create a minimal SimulationTarget for testing."""
    return SimulationTarget(
        target_id=target_id,
        name=target_id,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=speed,
        crowd_role=crowd_role,
        is_combatant=(alliance == "hostile"),
    )


class TestInstigatorDetectionBasic:
    """Test that proximity tracking identifies instigators after 3 seconds."""

    def test_identifies_instigator_after_3_seconds(self):
        """A scout_drone within range for 3+ seconds identifies the instigator."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"scout-1": scout, "ins-1": instigator}
        game_mode_type = "civil_unrest"

        # Tick 30 times at 0.1s = 3.0s -- should trigger identification
        for _ in range(30):
            detector.tick(0.1, targets, game_mode_type)

        assert instigator.identified is True

    def test_no_identification_before_3_seconds(self):
        """Instigator is NOT identified before 3 seconds of sustained proximity."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"scout-1": scout, "ins-1": instigator}

        # Tick 20 times at 0.1s = 2.0s -- not enough
        for _ in range(20):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is False


class TestInstigatorDetectionEvent:
    """Test that instigator_identified event is published on the EventBus."""

    def test_publishes_instigator_identified_event(self):
        """On identification, an instigator_identified event is published."""
        bus = SimpleEventBus()
        q = bus.subscribe("instigator_identified")
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        rover = _make_target("rover-1", "friendly", "rover", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"rover-1": rover, "ins-1": instigator}

        for _ in range(31):
            detector.tick(0.1, targets, "civil_unrest")

        assert not q.empty()
        event = q.get_nowait()
        assert event["type"] == "instigator_identified"
        assert event["data"]["target_id"] == "ins-1"
        assert event["data"]["identifier_id"] == "rover-1"
        assert "position" in event["data"]


class TestInstigatorDetectionScoring:
    """Test that de-escalation score increases on identification."""

    def test_de_escalation_score_awarded(self):
        """GameMode.de_escalation_score increases by 50 per identification."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=100.0)
        game_mode = engine.game_mode
        game_mode.game_mode_type = "civil_unrest"

        # Create the detector integrated with game_mode
        detector = InstigatorDetector(
            event_bus=bus,
            detection_range=50.0,
            detection_time=3.0,
            game_mode=game_mode,
        )

        drone = _make_target("drone-1", "friendly", "drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"drone-1": drone, "ins-1": instigator}

        assert game_mode.de_escalation_score == 0

        for _ in range(31):
            detector.tick(0.1, targets, "civil_unrest")

        assert game_mode.de_escalation_score == 50


class TestInstigatorDetectionProximityReset:
    """Test that identification timer resets when unit moves away."""

    def test_timer_resets_on_leaving_range(self):
        """If identifier leaves detection range, the timer resets to 0."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"scout-1": scout, "ins-1": instigator}

        # Tick 2 seconds in range
        for _ in range(20):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is False

        # Move scout out of range (>50m away)
        scout.position = (200.0, 200.0)

        # Tick once to reset
        detector.tick(0.1, targets, "civil_unrest")

        # Move scout back in range
        scout.position = (10.0, 10.0)

        # Tick 2 more seconds -- total in-range is 2s again, not 4s
        for _ in range(20):
            detector.tick(0.1, targets, "civil_unrest")

        # Should NOT be identified yet (only 2s since reset)
        assert instigator.identified is False

        # Tick 1 more second to reach 3s total
        for _ in range(10):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is True


class TestInstigatorDetectionNoReidentify:
    """Test that already-identified instigators are not re-identified."""

    def test_already_identified_skipped(self):
        """An instigator that is already identified does not trigger a second event."""
        bus = SimpleEventBus()
        q = bus.subscribe("instigator_identified")
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"scout-1": scout, "ins-1": instigator}

        # First identification cycle (3+ seconds)
        for _ in range(31):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is True
        event_count_1 = 0
        while not q.empty():
            q.get_nowait()
            event_count_1 += 1
        assert event_count_1 == 1

        # Continue ticking for another 3+ seconds -- should NOT re-identify
        for _ in range(31):
            detector.tick(0.1, targets, "civil_unrest")

        event_count_2 = 0
        while not q.empty():
            q.get_nowait()
            event_count_2 += 1
        assert event_count_2 == 0


class TestInstigatorDetectionUnitTypes:
    """Test that only scout_drone, drone, and rover can identify instigators."""

    @pytest.mark.parametrize("asset_type,should_identify", [
        ("scout_drone", True),
        ("drone", True),
        ("rover", True),
        ("turret", False),
        ("heavy_turret", False),
        ("missile_turret", False),
        ("tank", False),
        ("apc", False),
    ])
    def test_only_scout_types_can_identify(self, asset_type: str, should_identify: bool):
        """Only scout_drone, drone, and rover can identify instigators."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        unit = _make_target("unit-1", "friendly", asset_type, (10.0, 10.0), speed=0.0)
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"unit-1": unit, "ins-1": instigator}

        # Tick 4 seconds (well past the 3s requirement)
        for _ in range(40):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is should_identify

    def test_non_civil_unrest_mode_does_nothing(self):
        """InstigatorDetector does nothing when game_mode_type is not civil_unrest."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"scout-1": scout, "ins-1": instigator}

        # Tick 4 seconds in "battle" mode
        for _ in range(40):
            detector.tick(0.1, targets, "battle")

        assert instigator.identified is False

    def test_dead_instigator_not_identified(self):
        """Eliminated instigators should not be identified."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")
        instigator.status = "eliminated"

        targets = {"scout-1": scout, "ins-1": instigator}

        for _ in range(40):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is False

    def test_dead_identifier_cannot_identify(self):
        """Eliminated friendlies should not be able to identify."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        scout.status = "eliminated"
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"scout-1": scout, "ins-1": instigator}

        for _ in range(40):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is False


class TestInstigatorDetectionCrowdDensity:
    """Identification should be blocked when crowd density is dense/critical."""

    def test_dense_crowd_blocks_identification(self):
        """Instigator identification is blocked when crowd is dense at instigator position."""
        bus = SimpleEventBus()

        # Create a mock crowd density tracker that always says "blocked"
        class DenseCrowdTracker:
            def can_identify_instigator(self, position):
                return False  # dense/critical

        detector = InstigatorDetector(
            event_bus=bus, detection_range=50.0, detection_time=3.0,
            crowd_density_tracker=DenseCrowdTracker(),
        )

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")
        targets = {"scout-1": scout, "ins-1": instigator}

        # Tick well past detection_time
        for _ in range(40):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is False

    def test_sparse_crowd_allows_identification(self):
        """Instigator identification succeeds when crowd is sparse at instigator position."""
        bus = SimpleEventBus()

        class SparseCrowdTracker:
            def can_identify_instigator(self, position):
                return True  # sparse/moderate

        detector = InstigatorDetector(
            event_bus=bus, detection_range=50.0, detection_time=3.0,
            crowd_density_tracker=SparseCrowdTracker(),
        )

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")
        targets = {"scout-1": scout, "ins-1": instigator}

        for _ in range(40):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is True

    def test_no_tracker_allows_identification(self):
        """Without a crowd density tracker, identification proceeds normally."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(
            event_bus=bus, detection_range=50.0, detection_time=3.0,
        )  # No crowd_density_tracker

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")
        targets = {"scout-1": scout, "ins-1": instigator}

        for _ in range(40):
            detector.tick(0.1, targets, "civil_unrest")

        assert instigator.identified is True


class TestInstigatorDetectionTimerCleanup:
    """Test that remove_unit() cleans up stale timers to prevent memory leaks."""

    def test_remove_instigator_clears_timers(self):
        """Removing an instigator clears all timer entries referencing it."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"scout-1": scout, "ins-1": instigator}

        # Tick a few times to accumulate timers
        for _ in range(10):
            detector.tick(0.1, targets, "civil_unrest")

        assert len(detector._timers) > 0

        # Remove instigator
        detector.remove_unit("ins-1")

        assert len(detector._timers) == 0

    def test_remove_friendly_clears_timers(self):
        """Removing a friendly clears all timer entries referencing it."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"scout-1": scout, "ins-1": instigator}

        for _ in range(10):
            detector.tick(0.1, targets, "civil_unrest")

        assert len(detector._timers) > 0

        # Remove the friendly scout
        detector.remove_unit("scout-1")

        assert len(detector._timers) == 0

    def test_remove_unrelated_unit_preserves_timers(self):
        """Removing a unit not in any timer pair leaves timers untouched."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        scout = _make_target("scout-1", "friendly", "scout_drone", (10.0, 10.0))
        instigator = _make_target("ins-1", "hostile", "person", (15.0, 10.0), crowd_role="instigator")

        targets = {"scout-1": scout, "ins-1": instigator}

        for _ in range(10):
            detector.tick(0.1, targets, "civil_unrest")

        timer_count = len(detector._timers)
        assert timer_count > 0

        # Remove a unit not involved in any timer
        detector.remove_unit("turret-99")

        assert len(detector._timers) == timer_count

    def test_remove_unit_with_no_timers(self):
        """remove_unit on empty timers dict does not error."""
        bus = SimpleEventBus()
        detector = InstigatorDetector(event_bus=bus, detection_range=50.0, detection_time=3.0)

        # No timers accumulated
        assert len(detector._timers) == 0

        # Should not raise
        detector.remove_unit("any-id")
        assert len(detector._timers) == 0
