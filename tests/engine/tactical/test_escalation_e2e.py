"""End-to-end test for the full escalation pipeline.

Hostile appears -> enters zone -> ThreatClassifier escalates ->
AutoDispatcher dispatches nearest friendly -> unit moves to intercept ->
events flow through EventBus.
"""

from __future__ import annotations

import queue
import time

import pytest

from engine.comms.event_bus import EventBus
from engine.tactical.escalation import AutoDispatcher, ThreatClassifier
from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget
from engine.tactical.target_tracker import TargetTracker, TrackedTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_events(sub: queue.Queue, timeout: float = 3.0) -> list[dict]:
    """Drain all events from a subscriber queue, waiting up to *timeout*."""
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            events.append(sub.get(timeout=0.1))
        except queue.Empty:
            # Keep polling until deadline; dispatcher thread may not have
            # reacted yet.
            continue
    return events


def _events_by_type(events: list[dict]) -> dict[str, list[dict]]:
    """Group collected events by their 'type' key."""
    grouped: dict[str, list[dict]] = {}
    for ev in events:
        grouped.setdefault(ev.get("type", ""), []).append(ev)
    return grouped


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEscalationPipelineE2E:
    """Verify the full escalation pipeline works end-to-end."""

    def test_hostile_in_zone_triggers_dispatch(self) -> None:
        """Hostile inside restricted zone -> escalation -> dispatch of nearest
        friendly rover -> rover waypoints updated to hostile position."""

        # ── 1. Create all subsystems ──────────────────────────────────────
        bus = EventBus()
        tracker = TargetTracker()
        engine = SimulationEngine(bus)

        # Restricted zone at origin, radius 10
        zones = [
            {
                "name": "HQ Perimeter",
                "type": "restricted",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0},
            }
        ]

        classifier = ThreatClassifier(bus, tracker, zones=zones)
        dispatcher = AutoDispatcher(bus, tracker, simulation_engine=engine)

        # Subscribe *before* starting subsystems so we capture all events
        test_sub = bus.subscribe()

        # ── 2. Populate the battlespace ───────────────────────────────────

        # Friendly rover at (20, 20) — outside the zone
        rover_id = "rover-alpha"
        rover_sim = SimulationTarget(
            target_id=rover_id,
            name="Rover Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(20.0, 20.0),
            speed=3.0,
            battery=0.95,
            status="active",
        )
        engine.add_target(rover_sim)
        tracker.update_from_simulation(rover_sim.to_dict())

        # Hostile person at (5, 5) — inside the restricted zone
        hostile_id = "hostile-001"
        hostile_data = {
            "target_id": hostile_id,
            "name": "Intruder Alpha",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 5.0, "y": 5.0},
            "heading": 0.0,
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        }
        tracker.update_from_simulation(hostile_data)

        # Verify targets are in the tracker
        assert tracker.get_target(rover_id) is not None, "Rover not in tracker"
        assert tracker.get_target(hostile_id) is not None, "Hostile not in tracker"
        assert len(tracker.get_friendlies()) == 1
        assert len(tracker.get_hostiles()) == 1

        # ── 3. Start the dispatcher (threaded listener) ───────────────────
        dispatcher.start()

        try:
            # ── 4. Run classifier tick manually ───────────────────────────
            classifier._classify_tick()

            # ── 5. Collect initial escalation events ─────────────────────
            events = _collect_events(test_sub, timeout=2.0)
            by_type = _events_by_type(events)

            # ── 6. Verify: first escalation to suspicious ────────────────
            assert "threat_escalation" in by_type, (
                f"Expected 'threat_escalation' event but got: {list(by_type.keys())}"
            )
            escalation_events = by_type["threat_escalation"]
            esc = escalation_events[0]["data"]
            assert esc["target_id"] == hostile_id
            assert esc["new_level"] == "suspicious", (
                f"Expected 'suspicious' for restricted zone entry, got '{esc['new_level']}'"
            )

            # AutoDispatcher only dispatches on 'hostile' level, not
            # 'suspicious'.  Manually escalate to hostile to trigger dispatch.
            classifier.set_threat_level(hostile_id, "hostile")

            # Collect dispatch events after the hostile escalation
            events2 = _collect_events(test_sub, timeout=2.0)
            by_type2 = _events_by_type(events2)
            # Merge for remaining assertions
            for k, v in by_type2.items():
                by_type.setdefault(k, []).extend(v)

            # ── 7. Verify: zone_violation event was published ─────────────
            assert "zone_violation" in by_type, (
                f"Expected 'zone_violation' event but got: {list(by_type.keys())}"
            )

            # ── 8. Verify: amy_dispatch event was published ───────────────
            assert "amy_dispatch" in by_type, (
                f"Expected 'amy_dispatch' event but got: {list(by_type.keys())}"
            )
            dispatch_ev = by_type["amy_dispatch"][0]["data"]
            assert dispatch_ev["target_id"] == rover_id
            assert dispatch_ev["threat_id"] == hostile_id
            dest = dispatch_ev["destination"]
            assert dest["x"] == pytest.approx(5.0, abs=0.1)
            assert dest["y"] == pytest.approx(5.0, abs=0.1)

            # ── 9. Verify: auto_dispatch_speech event was published ───────
            assert "auto_dispatch_speech" in by_type, (
                f"Expected 'auto_dispatch_speech' event but got: {list(by_type.keys())}"
            )
            speech = by_type["auto_dispatch_speech"][0]["data"]
            assert "Rover Alpha" in speech["text"]

            # ── 10. Verify: rover waypoints updated in sim engine ─────────
            sim_rover = engine.get_target(rover_id)
            assert sim_rover is not None, "Rover no longer in sim engine"
            assert len(sim_rover.waypoints) > 0, "Rover waypoints not set"
            wp = sim_rover.waypoints[0]
            assert wp == pytest.approx((5.0, 5.0), abs=0.1), (
                f"Rover waypoint {wp} does not point to hostile position (5.0, 5.0)"
            )

            # ── 11. Verify: dispatcher tracks the active dispatch ─────────
            dispatches = dispatcher.active_dispatches
            assert hostile_id in dispatches, (
                f"Expected hostile_id in active_dispatches, got {dispatches}"
            )
            assert dispatches[hostile_id] == rover_id

        finally:
            dispatcher.stop()

    def test_low_battery_unit_not_dispatched(self) -> None:
        """A friendly unit below MIN_BATTERY (20%) should NOT be dispatched."""

        bus = EventBus()
        tracker = TargetTracker()
        engine = SimulationEngine(bus)

        zones = [
            {
                "name": "Restricted Area",
                "type": "restricted",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0},
            }
        ]

        classifier = ThreatClassifier(bus, tracker, zones=zones)
        dispatcher = AutoDispatcher(bus, tracker, simulation_engine=engine)

        test_sub = bus.subscribe()

        # Friendly rover with nearly dead battery
        rover_sim = SimulationTarget(
            target_id="rover-dead",
            name="Rover Dead",
            alliance="friendly",
            asset_type="rover",
            position=(15.0, 15.0),
            speed=3.0,
            battery=0.10,
            status="active",
        )
        engine.add_target(rover_sim)
        tracker.update_from_simulation(rover_sim.to_dict())

        # Hostile inside the zone
        hostile_data = {
            "target_id": "hostile-002",
            "name": "Intruder Bravo",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 3.0, "y": 3.0},
            "speed": 1.0,
            "battery": 1.0,
            "status": "active",
        }
        tracker.update_from_simulation(hostile_data)

        dispatcher.start()

        try:
            classifier._classify_tick()

            events = _collect_events(test_sub, timeout=2.0)
            by_type = _events_by_type(events)

            # Escalation should still happen (to suspicious)
            assert "threat_escalation" in by_type

            # Escalate to hostile to trigger AutoDispatcher evaluation
            classifier.set_threat_level("hostile-002", "hostile")

            events2 = _collect_events(test_sub, timeout=2.0)
            by_type2 = _events_by_type(events2)

            # But no dispatch — rover battery too low
            assert "amy_dispatch" not in by_type2, (
                "Dispatch should NOT occur when only unit is below battery threshold"
            )
            assert len(dispatcher.active_dispatches) == 0

        finally:
            dispatcher.stop()

    def test_friendly_not_escalated(self) -> None:
        """Friendly targets inside a restricted zone should NOT be escalated."""

        bus = EventBus()
        tracker = TargetTracker()

        zones = [
            {
                "name": "Base",
                "type": "restricted",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0},
            }
        ]

        classifier = ThreatClassifier(bus, tracker, zones=zones)
        test_sub = bus.subscribe()

        # Friendly at origin — inside restricted zone
        friendly_data = {
            "target_id": "turret-01",
            "name": "Turret 01",
            "alliance": "friendly",
            "asset_type": "turret",
            "position": {"x": 0.0, "y": 0.0},
            "speed": 0.0,
            "battery": 1.0,
            "status": "active",
        }
        tracker.update_from_simulation(friendly_data)

        classifier._classify_tick()

        events = _collect_events(test_sub, timeout=1.0)
        by_type = _events_by_type(events)

        # No escalation for friendlies
        assert "threat_escalation" not in by_type, (
            "Friendly targets should never trigger escalation"
        )

    def test_hostile_outside_zone_stays_none(self) -> None:
        """A hostile target well outside all zones starts at 'none' threat level."""

        bus = EventBus()
        tracker = TargetTracker()

        zones = [
            {
                "name": "HQ",
                "type": "restricted",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0},
            }
        ]

        classifier = ThreatClassifier(bus, tracker, zones=zones)
        test_sub = bus.subscribe()

        # Hostile far outside all zones
        hostile_data = {
            "target_id": "hostile-far",
            "name": "Intruder Far",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 50.0, "y": 50.0},
            "speed": 1.0,
            "battery": 1.0,
            "status": "active",
        }
        tracker.update_from_simulation(hostile_data)

        classifier._classify_tick()

        events = _collect_events(test_sub, timeout=1.0)
        by_type = _events_by_type(events)

        # No escalation — target is outside all zones
        assert "threat_escalation" not in by_type, (
            "Target outside all zones should not trigger escalation"
        )

    def test_multiple_friendlies_nearest_dispatched(self) -> None:
        """When multiple friendlies are available, the nearest one is dispatched."""

        bus = EventBus()
        tracker = TargetTracker()
        engine = SimulationEngine(bus)

        zones = [
            {
                "name": "Restricted",
                "type": "restricted",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0},
            }
        ]

        classifier = ThreatClassifier(bus, tracker, zones=zones)
        dispatcher = AutoDispatcher(bus, tracker, simulation_engine=engine)

        test_sub = bus.subscribe()

        # Rover far away at (30, 30)
        far_rover = SimulationTarget(
            target_id="rover-far",
            name="Rover Far",
            alliance="friendly",
            asset_type="rover",
            position=(30.0, 30.0),
            speed=3.0,
            battery=0.90,
            status="active",
        )
        engine.add_target(far_rover)
        tracker.update_from_simulation(far_rover.to_dict())

        # Rover close at (12, 12)
        close_rover = SimulationTarget(
            target_id="rover-close",
            name="Rover Close",
            alliance="friendly",
            asset_type="rover",
            position=(12.0, 12.0),
            speed=3.0,
            battery=0.90,
            status="active",
        )
        engine.add_target(close_rover)
        tracker.update_from_simulation(close_rover.to_dict())

        # Hostile in zone
        hostile_data = {
            "target_id": "hostile-003",
            "name": "Intruder Charlie",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 4.0, "y": 4.0},
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        }
        tracker.update_from_simulation(hostile_data)

        dispatcher.start()

        try:
            classifier._classify_tick()

            # Classifier escalates to suspicious; escalate to hostile for dispatch
            classifier.set_threat_level("hostile-003", "hostile")

            events = _collect_events(test_sub, timeout=3.0)
            by_type = _events_by_type(events)

            assert "amy_dispatch" in by_type
            dispatch_ev = by_type["amy_dispatch"][0]["data"]
            # Nearest rover (12,12) should be dispatched, not the far one (30,30)
            assert dispatch_ev["target_id"] == "rover-close", (
                f"Expected rover-close to be dispatched, got {dispatch_ev['target_id']}"
            )

        finally:
            dispatcher.stop()
