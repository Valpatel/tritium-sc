# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for CrowdDensityTracker — crowd density grid for civil unrest mode."""

from __future__ import annotations

import queue

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.crowd_density import CrowdDensityTracker
from tritium_lib.sim_engine.core.entity import SimulationTarget

pytestmark = pytest.mark.unit


def _make_person(
    target_id: str,
    position: tuple[float, float],
    crowd_role: str | None = None,
    alliance: str = "neutral",
    asset_type: str = "person",
) -> SimulationTarget:
    """Create a minimal person target for crowd density tests."""
    return SimulationTarget(
        target_id=target_id,
        name=f"Person-{target_id}",
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=0.0,
        is_combatant=False,
        crowd_role=crowd_role,
    )


def _make_turret(
    target_id: str,
    position: tuple[float, float],
) -> SimulationTarget:
    """Create a turret target (should NOT count as crowd)."""
    return SimulationTarget(
        target_id=target_id,
        name=f"Turret-{target_id}",
        alliance="friendly",
        asset_type="turret",
        position=position,
        speed=0.0,
    )


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def tracker(event_bus: EventBus) -> CrowdDensityTracker:
    """100x100 meter map with 10m cells = 10x10 grid."""
    return CrowdDensityTracker(
        bounds=(0.0, 0.0, 100.0, 100.0),
        event_bus=event_bus,
        cell_size=10.0,
    )


# -- Spec test 24: Init -------------------------------------------------------


class TestDensityTrackerInit:
    """Spec test 24: CrowdDensityTracker initializes with 10m cell grid."""

    def test_creates_with_default_cell_size(self, event_bus: EventBus) -> None:
        t = CrowdDensityTracker(bounds=(0.0, 0.0, 50.0, 50.0), event_bus=event_bus)
        assert t.cell_size == 10.0

    def test_creates_with_custom_cell_size(self, event_bus: EventBus) -> None:
        t = CrowdDensityTracker(
            bounds=(0.0, 0.0, 50.0, 50.0), event_bus=event_bus, cell_size=5.0
        )
        assert t.cell_size == 5.0

    def test_stores_bounds(self, tracker: CrowdDensityTracker) -> None:
        assert tracker.bounds == (0.0, 0.0, 100.0, 100.0)


# -- Grid dimensions ----------------------------------------------------------


class TestGridDimensions:
    """Grid has correct row/col count for given bounds."""

    def test_10x10_grid_for_100m_map(self, tracker: CrowdDensityTracker) -> None:
        assert tracker.cols == 10
        assert tracker.rows == 10

    def test_5x5_grid_for_50m_map(self, event_bus: EventBus) -> None:
        t = CrowdDensityTracker(
            bounds=(0.0, 0.0, 50.0, 50.0), event_bus=event_bus, cell_size=10.0
        )
        assert t.cols == 5
        assert t.rows == 5

    def test_non_aligned_bounds_rounds_up(self, event_bus: EventBus) -> None:
        """A 95m map with 10m cells should still have 10 columns (ceil)."""
        t = CrowdDensityTracker(
            bounds=(0.0, 0.0, 95.0, 95.0), event_bus=event_bus, cell_size=10.0
        )
        assert t.cols == 10
        assert t.rows == 10


# -- Spec test 25: Density classification -------------------------------------


class TestDensityClassification:
    """Spec test 25: 0-2=sparse, 3-5=moderate, 6-10=dense, 11+=critical."""

    def test_empty_cell_is_sparse(self, tracker: CrowdDensityTracker) -> None:
        targets: dict[str, SimulationTarget] = {}
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "sparse"

    def test_one_person_is_sparse(self, tracker: CrowdDensityTracker) -> None:
        p1 = _make_person("p1", (5.0, 5.0))
        targets = {"p1": p1}
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "sparse"

    def test_two_persons_is_sparse(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(2)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "sparse"

    def test_three_persons_is_moderate(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(3)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "moderate"

    def test_five_persons_is_moderate(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(5)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "moderate"

    def test_six_persons_is_dense(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(6)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "dense"

    def test_ten_persons_is_dense(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(10)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "dense"

    def test_eleven_persons_is_critical(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(11)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "critical"

    def test_twenty_persons_is_critical(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(20)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "critical"


# -- Spec test 26: Event published every 1s -----------------------------------


class TestDensityEventPublished:
    """Spec test 26: EventBus receives crowd_density event every 1s."""

    def test_no_event_before_1s(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        targets: dict[str, SimulationTarget] = {}
        # Tick 0.5s total — not enough for event
        for _ in range(5):
            tracker.tick(targets, 0.1)
        # Drain queue — should have no crowd_density events
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        crowd_events = [e for e in events if e["type"] == "crowd_density"]
        assert len(crowd_events) == 0

    def test_event_after_1s(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        targets: dict[str, SimulationTarget] = {}
        # Tick 1.1s total — should trigger one event
        for _ in range(11):
            tracker.tick(targets, 0.1)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        crowd_events = [e for e in events if e["type"] == "crowd_density"]
        assert len(crowd_events) == 1

    def test_event_payload_structure(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        p1 = _make_person("p1", (5.0, 5.0))
        targets = {"p1": p1}
        # Tick past 1s
        for _ in range(11):
            tracker.tick(targets, 0.1)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        crowd_events = [e for e in events if e["type"] == "crowd_density"]
        assert len(crowd_events) == 1
        data = crowd_events[0]["data"]
        assert "grid" in data
        assert "cell_size" in data
        assert data["cell_size"] == 10
        assert "bounds" in data
        assert "max_density" in data
        assert "critical_count" in data

    def test_two_events_after_2s(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        targets: dict[str, SimulationTarget] = {}
        # Tick 2.1s total — should trigger two events
        for _ in range(21):
            tracker.tick(targets, 0.1)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        crowd_events = [e for e in events if e["type"] == "crowd_density"]
        assert len(crowd_events) == 2


# -- Spec test 27: Critical density POI timer ----------------------------------


class TestCriticalDensityPoiTimer:
    """Spec test 27: Critical density on POI for 60s triggers defeat."""

    def test_poi_defeat_after_timeout(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        tracker.add_poi_building((5.0, 5.0), "Town Hall")
        # Place 12 people near POI (same cell) => critical
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(12)
        }
        # Tick for 60s at 0.5s intervals
        for _ in range(120):
            tracker.tick(targets, 0.5)
        assert tracker.check_poi_defeat(timeout=60.0) is True

    def test_poi_no_defeat_before_timeout(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        tracker.add_poi_building((5.0, 5.0), "Town Hall")
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(12)
        }
        # Tick for 30s — less than 60s timeout
        for _ in range(60):
            tracker.tick(targets, 0.5)
        assert tracker.check_poi_defeat(timeout=60.0) is False

    def test_poi_no_defeat_without_critical(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        tracker.add_poi_building((5.0, 5.0), "Town Hall")
        # Only 2 people = sparse, not critical
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(2)
        }
        for _ in range(200):
            tracker.tick(targets, 0.5)
        assert tracker.check_poi_defeat(timeout=60.0) is False

    def test_poi_defeat_publishes_event(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        tracker.add_poi_building((5.0, 5.0), "Town Hall")
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(12)
        }
        for _ in range(120):
            tracker.tick(targets, 0.5)
        tracker.check_poi_defeat(timeout=60.0)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        overwhelmed = [e for e in events if e["type"] == "infrastructure_overwhelmed"]
        assert len(overwhelmed) >= 1


# -- Spec test 28: Density affects conversion rate -----------------------------


class TestDensityAffectsConversionRate:
    """Spec test 28: Dense zones double civilian-to-rioter conversion rate."""

    def test_sparse_multiplier(self, tracker: CrowdDensityTracker) -> None:
        targets: dict[str, SimulationTarget] = {}
        tracker.tick(targets, 0.1)
        assert tracker.get_conversion_multiplier((5.0, 5.0)) == 1.0

    def test_moderate_multiplier(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(4)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_conversion_multiplier((5.0, 5.0)) == 1.0

    def test_dense_multiplier(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(8)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_conversion_multiplier((5.0, 5.0)) == 2.0

    def test_critical_multiplier(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(15)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_conversion_multiplier((5.0, 5.0)) == 3.0


# -- Spec test 29: Density affects identification -----------------------------


class TestDensityAffectsIdentification:
    """Spec test 29: Dense zones prevent instigator identification."""

    def test_sparse_can_identify(self, tracker: CrowdDensityTracker) -> None:
        targets: dict[str, SimulationTarget] = {}
        tracker.tick(targets, 0.1)
        assert tracker.can_identify_instigator((5.0, 5.0)) is True

    def test_moderate_can_identify(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(4)
        }
        tracker.tick(targets, 0.1)
        assert tracker.can_identify_instigator((5.0, 5.0)) is True

    def test_dense_cannot_identify(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(8)
        }
        tracker.tick(targets, 0.1)
        assert tracker.can_identify_instigator((5.0, 5.0)) is False

    def test_critical_cannot_identify(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(15)
        }
        tracker.tick(targets, 0.1)
        assert tracker.can_identify_instigator((5.0, 5.0)) is False


# -- Additional tests ----------------------------------------------------------


class TestEmptyTargets:
    """No targets = all cells sparse."""

    def test_all_sparse_when_empty(self, tracker: CrowdDensityTracker) -> None:
        targets: dict[str, SimulationTarget] = {}
        tracker.tick(targets, 0.1)
        for x in range(0, 100, 15):
            for y in range(0, 100, 15):
                assert tracker.get_density_at((float(x), float(y))) == "sparse"


class TestNonPersonEntitiesIgnored:
    """Turrets, drones don't count as crowd."""

    def test_turret_not_counted(self, tracker: CrowdDensityTracker) -> None:
        turret = _make_turret("t1", (5.0, 5.0))
        targets = {"t1": turret}
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "sparse"

    def test_drone_not_counted(self, tracker: CrowdDensityTracker) -> None:
        drone = SimulationTarget(
            target_id="d1",
            name="Drone-1",
            alliance="friendly",
            asset_type="drone",
            position=(5.0, 5.0),
            speed=5.0,
        )
        targets = {"d1": drone}
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "sparse"

    def test_mix_of_persons_and_turrets(self, tracker: CrowdDensityTracker) -> None:
        """Only person-type entities count; turrets added should not change density."""
        targets: dict[str, SimulationTarget] = {}
        # 2 persons = sparse
        for i in range(2):
            targets[f"p{i}"] = _make_person(f"p{i}", (5.0, 5.0))
        # 5 turrets should NOT bump density
        for i in range(5):
            targets[f"t{i}"] = _make_turret(f"t{i}", (5.0, 5.0))
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((5.0, 5.0)) == "sparse"


class TestPersonAtBoundary:
    """Person at exact boundary maps to correct cell."""

    def test_person_at_origin(self, tracker: CrowdDensityTracker) -> None:
        p = _make_person("p1", (0.0, 0.0))
        targets = {"p1": p}
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((0.0, 0.0)) == "sparse"

    def test_person_at_max_boundary(self, tracker: CrowdDensityTracker) -> None:
        """Person at (99.9, 99.9) should map to the last cell, not overflow."""
        p = _make_person("p1", (99.9, 99.9))
        targets = {"p1": p}
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((99.9, 99.9)) == "sparse"

    def test_person_outside_bounds_clamped(self, tracker: CrowdDensityTracker) -> None:
        """Person outside bounds should be clamped to nearest edge cell."""
        p = _make_person("p1", (150.0, 150.0))
        targets = {"p1": p}
        # Should not raise
        tracker.tick(targets, 0.1)


class TestMultiplePersonsModerate:
    """4 persons in same cell = moderate."""

    def test_four_persons_moderate(self, tracker: CrowdDensityTracker) -> None:
        targets = {
            f"p{i}": _make_person(f"p{i}", (15.0, 15.0))
            for i in range(4)
        }
        tracker.tick(targets, 0.1)
        assert tracker.get_density_at((15.0, 15.0)) == "moderate"


class TestPoiBuildingNoCritical:
    """No critical density near POI = check_poi_defeat returns False."""

    def test_no_defeat_when_sparse(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        tracker.add_poi_building((50.0, 50.0), "Library")
        targets: dict[str, SimulationTarget] = {}
        for _ in range(200):
            tracker.tick(targets, 0.5)
        assert tracker.check_poi_defeat(timeout=60.0) is False


class TestPoiBuildingCriticalBelowTimeout:
    """Critical for 30s < 60s = no defeat."""

    def test_no_defeat_at_30s(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        tracker.add_poi_building((5.0, 5.0), "City Hall")
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(12)
        }
        # Tick for exactly 30s
        for _ in range(60):
            tracker.tick(targets, 0.5)
        assert tracker.check_poi_defeat(timeout=60.0) is False


class TestPoiBuildingCriticalAtTimeout:
    """Critical for 60s = defeat triggered."""

    def test_defeat_at_60s(
        self, tracker: CrowdDensityTracker, event_bus: EventBus
    ) -> None:
        tracker.add_poi_building((5.0, 5.0), "City Hall")
        targets = {
            f"p{i}": _make_person(f"p{i}", (5.0, 5.0))
            for i in range(12)
        }
        # Tick for exactly 60s
        for _ in range(120):
            tracker.tick(targets, 0.5)
        assert tracker.check_poi_defeat(timeout=60.0) is True
