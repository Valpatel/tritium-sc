# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for ObjectiveTracker — bonus objective completion tracking.

Tests all objective evaluation logic:
- No casualties: friendly eliminated -> failed, no elimination -> completed at game end
- Speed run: game completes in < 300s -> completed, >= 300s -> failed
- Zero Collateral: no civilian harm events -> completed, any harm -> failed
- Quick Containment: no critical density -> completed, critical density -> failed
- Perfect Defense: infrastructure health > 800 at game end -> completed
- No Bombers Through: zero bomber detonations -> completed
- EMP Master: single EMP disables 10+ drones -> completed
- Ace Pilot: single drone eliminates 15+ hostiles -> completed
- Flawless AA: no friendly eliminated -> completed (drone_swarm variant)
- Master De-escalator: de-escalate 20+ rioters -> completed
- All Instigators Identified: all instigators identified -> completed
- Event bus integration: publishes bonus_objective_completed
- get_status() returns correct state
"""

from __future__ import annotations

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.objectives import ObjectiveTracker


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_objectives(*names: str) -> list[dict]:
    """Build a list of objective dicts from names."""
    _REWARDS = {
        "No casualties": 1000,
        "Speed run": 500,
        "Zero Collateral": 2000,
        "Master De-escalator": 1500,
        "All Instigators Identified": 1000,
        "Quick Containment": 1000,
        "Perfect Defense": 2000,
        "Ace Pilot": 1500,
        "No Bombers Through": 1000,
        "EMP Master": 500,
        "Flawless AA": 1000,
    }
    return [{"name": n, "description": f"Test {n}", "reward": _REWARDS.get(n, 100)} for n in names]


def _drain_events(sub, limit=100):
    """Drain all events from an EventBus subscriber queue."""
    events = []
    import queue
    for _ in range(limit):
        try:
            events.append(sub.get_nowait())
        except queue.Empty:
            break
    return events


# ===========================================================================
# Battle mode objectives
# ===========================================================================

class TestNoCasualties:
    """'No casualties' objective — fails if any friendly is eliminated."""

    def test_completed_when_no_friendly_eliminated(self):
        """No casualties completed at game end if no friendly was eliminated."""
        bus = EventBus()
        tracker = ObjectiveTracker(_make_objectives("No casualties"), "battle", bus)

        # Kill a hostile -- should NOT fail the objective
        bus.publish("target_eliminated", {
            "target_id": "hostile-1",
            "target_alliance": "hostile",
        })
        tracker.tick(0.1)

        # Game ends -- check all
        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "No casualties"][0]
        assert obj["completed"] is True

    def test_failed_when_friendly_eliminated(self):
        """No casualties fails if a friendly unit is eliminated."""
        bus = EventBus()
        tracker = ObjectiveTracker(_make_objectives("No casualties"), "battle", bus)

        # A friendly gets eliminated
        bus.publish("target_eliminated", {
            "target_id": "turret-1",
            "target_alliance": "friendly",
        })
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "No casualties"][0]
        assert obj["completed"] is False

    def test_hostile_elimination_does_not_affect(self):
        """Eliminating hostiles does not break the no casualties objective."""
        bus = EventBus()
        tracker = ObjectiveTracker(_make_objectives("No casualties"), "battle", bus)

        for i in range(5):
            bus.publish("target_eliminated", {
                "target_id": f"hostile-{i}",
                "target_alliance": "hostile",
            })
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)
        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "No casualties"][0]
        assert obj["completed"] is True


class TestSpeedRun:
    """'Speed run' objective — completed if game finishes in < 300s."""

    def test_completed_under_five_minutes(self):
        """Speed run completed when game finishes in 200s."""
        bus = EventBus()
        tracker = ObjectiveTracker(_make_objectives("Speed run"), "battle", bus)

        tracker.check_all(elapsed_time=200.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Speed run"][0]
        assert obj["completed"] is True

    def test_failed_over_five_minutes(self):
        """Speed run fails when game takes 400s."""
        bus = EventBus()
        tracker = ObjectiveTracker(_make_objectives("Speed run"), "battle", bus)

        tracker.check_all(elapsed_time=400.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Speed run"][0]
        assert obj["completed"] is False

    def test_exactly_five_minutes_fails(self):
        """Speed run fails at exactly 300s (must be under 5 minutes)."""
        bus = EventBus()
        tracker = ObjectiveTracker(_make_objectives("Speed run"), "battle", bus)

        tracker.check_all(elapsed_time=300.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Speed run"][0]
        assert obj["completed"] is False


# ===========================================================================
# Civil unrest objectives
# ===========================================================================

class TestZeroCollateral:
    """'Zero Collateral' — fails if any civilian_harmed event fires."""

    def test_completed_with_no_harm(self):
        """Zero Collateral completed when no civilian harm events occur."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Zero Collateral"), "civil_unrest", bus
        )

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Zero Collateral"][0]
        assert obj["completed"] is True

    def test_failed_with_one_harm(self):
        """Zero Collateral fails after a single civilian_harmed event."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Zero Collateral"), "civil_unrest", bus
        )

        bus.publish("civilian_harmed", {"harm_count": 1, "harm_limit": 5})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Zero Collateral"][0]
        assert obj["completed"] is False

    def test_failed_with_multiple_harms(self):
        """Zero Collateral still fails with multiple harm events."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Zero Collateral"), "civil_unrest", bus
        )

        for i in range(3):
            bus.publish("civilian_harmed", {"harm_count": i + 1, "harm_limit": 5})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Zero Collateral"][0]
        assert obj["completed"] is False


class TestQuickContainment:
    """'Quick Containment' — fails if any cell reaches critical density."""

    def test_completed_with_no_critical(self):
        """Quick Containment completed when no critical density events occur."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Quick Containment"), "civil_unrest", bus
        )

        # Normal density events (not critical) — uses actual CrowdDensityTracker payload
        bus.publish("crowd_density", {
            "grid": [["sparse", "moderate"]],
            "cell_size": 10,
            "bounds": [-100, -100, 100, 100],
            "max_density": "moderate",
            "critical_count": 0,
        })
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Quick Containment"][0]
        assert obj["completed"] is True

    def test_failed_with_critical_density(self):
        """Quick Containment fails when a critical density cell appears."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Quick Containment"), "civil_unrest", bus
        )

        bus.publish("crowd_density", {
            "grid": [["sparse", "critical"]],
            "cell_size": 10,
            "bounds": [-100, -100, 100, 100],
            "max_density": "critical",
            "critical_count": 1,
        })
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Quick Containment"][0]
        assert obj["completed"] is False

    def test_failed_with_critical_count_only(self):
        """Quick Containment fails even if max_density is not critical but critical_count > 0."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Quick Containment"), "civil_unrest", bus
        )

        bus.publish("crowd_density", {
            "grid": [["dense", "dense"]],
            "cell_size": 10,
            "bounds": [-100, -100, 100, 100],
            "max_density": "dense",
            "critical_count": 2,
        })
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Quick Containment"][0]
        assert obj["completed"] is False


class TestAllInstigatorsIdentified:
    """'All Instigators Identified' — all instigators must be identified."""

    def test_completed_when_all_identified(self):
        """Objective completed when instigator_identified count matches spawned."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("All Instigators Identified"), "civil_unrest", bus
        )

        # Spawn 3 instigators, then identify all 3
        tracker.set_instigator_count(3)
        for i in range(3):
            bus.publish("instigator_identified", {"unit_id": f"instigator-{i}"})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "All Instigators Identified"][0]
        assert obj["completed"] is True

    def test_failed_when_some_missing(self):
        """Objective fails when not all instigators are identified."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("All Instigators Identified"), "civil_unrest", bus
        )

        tracker.set_instigator_count(5)
        for i in range(3):
            bus.publish("instigator_identified", {"unit_id": f"instigator-{i}"})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "All Instigators Identified"][0]
        assert obj["completed"] is False


class TestMasterDeEscalator:
    """'Master De-escalator' — de-escalate 20+ rioters."""

    def test_completed_with_enough_de_escalations(self):
        """Completed when 20+ de-escalation events fire."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Master De-escalator"), "civil_unrest", bus
        )

        for i in range(20):
            bus.publish("de_escalation", {"unit_id": f"rioter-{i}"})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Master De-escalator"][0]
        assert obj["completed"] is True

    def test_failed_with_few_de_escalations(self):
        """Fails with only 10 de-escalation events."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Master De-escalator"), "civil_unrest", bus
        )

        for i in range(10):
            bus.publish("de_escalation", {"unit_id": f"rioter-{i}"})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Master De-escalator"][0]
        assert obj["completed"] is False


# ===========================================================================
# Drone swarm objectives
# ===========================================================================

class TestPerfectDefense:
    """'Perfect Defense' — infrastructure health > 800 at game end."""

    def test_completed_with_high_health(self):
        """Completed when infrastructure health is above 800."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Perfect Defense"), "drone_swarm", bus
        )

        tracker.check_all(elapsed_time=100.0, infrastructure_health=950.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Perfect Defense"][0]
        assert obj["completed"] is True

    def test_failed_with_low_health(self):
        """Fails when infrastructure health is below 800."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Perfect Defense"), "drone_swarm", bus
        )

        tracker.check_all(elapsed_time=100.0, infrastructure_health=600.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Perfect Defense"][0]
        assert obj["completed"] is False

    def test_exactly_800_not_enough(self):
        """Fails at exactly 800 (must be > 800)."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Perfect Defense"), "drone_swarm", bus
        )

        tracker.check_all(elapsed_time=100.0, infrastructure_health=800.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Perfect Defense"][0]
        assert obj["completed"] is False


class TestNoBombersThrough:
    """'No Bombers Through' — zero bomber detonation events."""

    def test_completed_with_no_detonations(self):
        """Completed when no bomber_detonation events occurred."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("No Bombers Through"), "drone_swarm", bus
        )

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "No Bombers Through"][0]
        assert obj["completed"] is True

    def test_failed_with_detonation(self):
        """Fails when a bomber_detonation event occurs."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("No Bombers Through"), "drone_swarm", bus
        )

        bus.publish("bomber_detonation", {"position": {"x": 0, "y": 0}, "damage": 50})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "No Bombers Through"][0]
        assert obj["completed"] is False


class TestEmpMaster:
    """'EMP Master' — a single EMP disables 10+ drones."""

    def test_completed_with_big_emp(self):
        """Completed when an emp_activated event reports 10+ disabled drones."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("EMP Master"), "drone_swarm", bus
        )

        bus.publish("emp_activated", {"drones_disabled": 12, "unit_id": "turret-1"})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "EMP Master"][0]
        assert obj["completed"] is True

    def test_failed_with_small_emp(self):
        """Fails when emp events only disable fewer than 10 drones."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("EMP Master"), "drone_swarm", bus
        )

        bus.publish("emp_activated", {"drones_disabled": 5, "unit_id": "turret-1"})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "EMP Master"][0]
        assert obj["completed"] is False


class TestAcePilot:
    """'Ace Pilot' — single drone eliminates 15+ hostile drones."""

    def test_completed_with_ace(self):
        """Completed when a single friendly drone scores 15+ eliminations."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Ace Pilot"), "drone_swarm", bus
        )

        # Same drone kills 15 hostiles
        for i in range(15):
            bus.publish("target_eliminated", {
                "target_id": f"swarm-drone-{i}",
                "target_alliance": "hostile",
                "interceptor_id": "drone-1",
                "interceptor_alliance": "friendly",
            })
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Ace Pilot"][0]
        assert obj["completed"] is True

    def test_failed_with_spread_kills(self):
        """Fails when kills are spread across multiple drones."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Ace Pilot"), "drone_swarm", bus
        )

        # 3 drones each kill 5 hostiles = 15 total but no single ace
        for d in range(3):
            for i in range(5):
                bus.publish("target_eliminated", {
                    "target_id": f"swarm-drone-{d}-{i}",
                    "target_alliance": "hostile",
                    "interceptor_id": f"drone-{d}",
                    "interceptor_alliance": "friendly",
                })
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Ace Pilot"][0]
        assert obj["completed"] is False


class TestFlawlessAA:
    """'Flawless AA' — no friendly units lost (drone_swarm variant)."""

    def test_completed_no_losses(self):
        """Completed when no friendly was eliminated."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Flawless AA"), "drone_swarm", bus
        )

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Flawless AA"][0]
        assert obj["completed"] is True

    def test_failed_with_friendly_loss(self):
        """Fails when a friendly is eliminated."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Flawless AA"), "drone_swarm", bus
        )

        bus.publish("target_eliminated", {
            "target_id": "turret-1",
            "target_alliance": "friendly",
        })
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Flawless AA"][0]
        assert obj["completed"] is False


# ===========================================================================
# EventBus integration
# ===========================================================================

class TestEventBusIntegration:
    """ObjectiveTracker publishes bonus_objective_completed events."""

    def test_publishes_on_completion(self):
        """bonus_objective_completed event published when objective is met."""
        bus = EventBus()
        sub = bus.subscribe()
        tracker = ObjectiveTracker(_make_objectives("No casualties"), "battle", bus)

        # Complete game with no friendly eliminated
        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        events = _drain_events(sub)
        completion_events = [
            e for e in events
            if e.get("type") == "bonus_objective_completed"
        ]
        assert len(completion_events) == 1
        assert completion_events[0]["data"]["name"] == "No casualties"
        assert completion_events[0]["data"]["reward"] == 1000

    def test_no_event_on_failure(self):
        """No bonus_objective_completed event when objective fails."""
        bus = EventBus()
        sub = bus.subscribe()
        tracker = ObjectiveTracker(_make_objectives("Speed run"), "battle", bus)

        tracker.check_all(elapsed_time=400.0, infrastructure_health=1000.0)

        events = _drain_events(sub)
        completion_events = [
            e for e in events
            if e.get("type") == "bonus_objective_completed"
        ]
        assert len(completion_events) == 0

    def test_immediate_completion_on_emp(self):
        """EMP Master publishes bonus_objective_completed immediately on big EMP."""
        bus = EventBus()
        sub = bus.subscribe()
        tracker = ObjectiveTracker(_make_objectives("EMP Master"), "drone_swarm", bus)

        bus.publish("emp_activated", {"drones_disabled": 12, "unit_id": "turret-1"})
        tracker.tick(0.1)

        events = _drain_events(sub)
        completion_events = [
            e for e in events
            if e.get("type") == "bonus_objective_completed"
        ]
        assert len(completion_events) == 1
        assert completion_events[0]["data"]["name"] == "EMP Master"


class TestGetStatus:
    """get_status() returns correct objective states."""

    def test_returns_all_objectives(self):
        """get_status returns an entry for each objective."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("No casualties", "Speed run"), "battle", bus
        )

        status = tracker.get_status()
        assert len(status) == 2
        names = {s["name"] for s in status}
        assert names == {"No casualties", "Speed run"}

    def test_returns_correct_rewards(self):
        """get_status includes correct reward values."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("No casualties", "Speed run"), "battle", bus
        )

        status = tracker.get_status()
        by_name = {s["name"]: s for s in status}
        assert by_name["No casualties"]["reward"] == 1000
        assert by_name["Speed run"]["reward"] == 500

    def test_initial_state_not_completed(self):
        """Objectives start as not completed."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("No casualties"), "battle", bus
        )

        status = tracker.get_status()
        assert all(not s["completed"] for s in status)

    def test_mixed_completion(self):
        """Some objectives complete, some fail."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("No casualties", "Speed run"), "battle", bus
        )

        # No friendly eliminated but game takes 400s
        tracker.check_all(elapsed_time=400.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        by_name = {s["name"]: s for s in status}
        assert by_name["No casualties"]["completed"] is True
        assert by_name["Speed run"]["completed"] is False


class TestTickProcessing:
    """tick() processes buffered events from EventBus."""

    def test_tick_processes_events(self):
        """tick() reads from the EventBus subscription and updates state."""
        bus = EventBus()
        tracker = ObjectiveTracker(_make_objectives("No casualties"), "battle", bus)

        bus.publish("target_eliminated", {
            "target_id": "turret-1",
            "target_alliance": "friendly",
        })

        # Before tick — event is in queue but not processed
        status_before = tracker.get_status()
        # objective not yet failed because tick hasn't run
        # (but it's also not completed since check_all hasn't been called)

        tracker.tick(0.1)

        # Now check_all should report failed
        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)
        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "No casualties"][0]
        assert obj["completed"] is False

    def test_multiple_ticks_accumulate(self):
        """Multiple tick() calls accumulate event data correctly."""
        bus = EventBus()
        tracker = ObjectiveTracker(
            _make_objectives("Master De-escalator"), "civil_unrest", bus
        )

        for i in range(10):
            bus.publish("de_escalation", {"unit_id": f"rioter-{i}"})
        tracker.tick(0.1)

        for i in range(10, 20):
            bus.publish("de_escalation", {"unit_id": f"rioter-{i}"})
        tracker.tick(0.1)

        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        obj = [s for s in status if s["name"] == "Master De-escalator"][0]
        assert obj["completed"] is True


class TestEmptyObjectives:
    """Edge case: no bonus objectives provided."""

    def test_empty_list(self):
        """ObjectiveTracker works with empty objective list."""
        bus = EventBus()
        tracker = ObjectiveTracker([], "battle", bus)

        tracker.tick(0.1)
        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        assert status == []

    def test_none_objectives(self):
        """ObjectiveTracker handles None gracefully."""
        bus = EventBus()
        tracker = ObjectiveTracker(None, "battle", bus)

        tracker.tick(0.1)
        tracker.check_all(elapsed_time=100.0, infrastructure_health=1000.0)

        status = tracker.get_status()
        assert status == []
