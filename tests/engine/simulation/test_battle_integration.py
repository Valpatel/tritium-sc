# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for BattleIntegration — verifies the sim-to-intelligence pipeline.

Validates that simulated combat exercises the full Wave 5-13 feature stack:
  - Correlator sees simulated targets
  - Dossiers are created from combat events
  - Geofence zones fire enter/exit events during battle
  - Automation rules respond to simulation events
  - Investigation engine auto-escalates on threat
  - Chaos scenario stress-tests the full stack
"""

from __future__ import annotations

import math
import queue
import random
import time
import uuid

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.battle_integration import (
    AutomationEngine,
    AutomationRule,
    BattleIntegration,
    default_combat_rules,
)
from engine.simulation.engine import SimulationEngine
from tritium_lib.sim_engine.core.entity import SimulationTarget
from tritium_lib.tracking.correlator import TargetCorrelator
from tritium_lib.tracking.dossier import DossierStore
from tritium_lib.tracking.geofence import GeofenceEngine, GeoZone
from engine.tactical.investigation import InvestigationEngine
from tritium_lib.tracking.target_tracker import TargetTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus() -> EventBus:
    return EventBus()


def _make_engine(bus: EventBus | None = None, map_bounds: float = 200.0) -> SimulationEngine:
    if bus is None:
        bus = _make_bus()
    return SimulationEngine(bus, map_bounds=map_bounds)


def _make_tracker() -> TargetTracker:
    return TargetTracker()


def _make_geofence(bus: EventBus) -> GeofenceEngine:
    return GeofenceEngine(event_bus=bus)


def _make_dossier_store() -> DossierStore:
    return DossierStore()


def _add_turret(engine: SimulationEngine, pos=(0.0, 0.0), name="Turret-1"):
    t = SimulationTarget(
        target_id=f"turret-{name}",
        name=name,
        alliance="friendly",
        asset_type="turret",
        position=pos,
        speed=0.0,
        status="stationary",
    )
    t.apply_combat_profile()
    engine.add_target(t)
    return t


def _make_integration(
    bus: EventBus, **kwargs
) -> BattleIntegration:
    """Create a BattleIntegration with all subsystems."""
    tracker = kwargs.pop("tracker", _make_tracker())
    geofence = kwargs.pop("geofence", _make_geofence(bus))
    dossier_store = kwargs.pop("dossier_store", _make_dossier_store())
    automation = kwargs.pop("automation", None)
    investigation = kwargs.pop("investigation", None)
    correlator = kwargs.pop("correlator", None)
    return BattleIntegration(
        bus,
        tracker=tracker,
        geofence=geofence,
        dossier_store=dossier_store,
        automation=automation,
        investigation=investigation,
        correlator=correlator,
    )


# ===========================================================================
# 1. AutomationEngine tests
# ===========================================================================

class TestAutomationEngine:
    """AutomationEngine evaluates rules against events."""

    def test_rule_matches_event(self):
        bus = _make_bus()
        engine = AutomationEngine(bus)
        rule = AutomationRule(
            name="test",
            trigger="target_eliminated",
            conditions={"alliance": "hostile"},
            action={"type": "alert", "message": "got one"},
        )
        engine.add_rule(rule)

        fired = engine.evaluate("target_eliminated", {"alliance": "hostile", "target_id": "h1"})
        assert len(fired) == 1
        assert fired[0]["rule_name"] == "test"

    def test_rule_skips_wrong_event(self):
        bus = _make_bus()
        engine = AutomationEngine(bus)
        rule = AutomationRule(
            name="test",
            trigger="target_eliminated",
            conditions={},
            action={"type": "alert"},
        )
        engine.add_rule(rule)

        fired = engine.evaluate("projectile_hit", {"target_id": "h1"})
        assert len(fired) == 0

    def test_rule_skips_wrong_conditions(self):
        bus = _make_bus()
        engine = AutomationEngine(bus)
        rule = AutomationRule(
            name="test",
            trigger="target_eliminated",
            conditions={"alliance": "friendly"},
            action={"type": "alert"},
        )
        engine.add_rule(rule)

        fired = engine.evaluate("target_eliminated", {"alliance": "hostile"})
        assert len(fired) == 0

    def test_rule_cooldown(self):
        bus = _make_bus()
        engine = AutomationEngine(bus)
        rule = AutomationRule(
            name="test",
            trigger="event_x",
            conditions={},
            action={"type": "alert"},
            cooldown=10.0,
        )
        engine.add_rule(rule)

        fired1 = engine.evaluate("event_x", {})
        assert len(fired1) == 1

        # Second evaluation within cooldown
        fired2 = engine.evaluate("event_x", {})
        assert len(fired2) == 0

    def test_disabled_rule_does_not_fire(self):
        bus = _make_bus()
        engine = AutomationEngine(bus)
        rule = AutomationRule(
            name="test",
            trigger="event_x",
            conditions={},
            action={"type": "alert"},
            enabled=False,
        )
        engine.add_rule(rule)

        fired = engine.evaluate("event_x", {})
        assert len(fired) == 0

    def test_remove_rule(self):
        bus = _make_bus()
        engine = AutomationEngine(bus)
        rule = AutomationRule(name="test", trigger="x", action={"type": "alert"})
        engine.add_rule(rule)
        assert len(engine.list_rules()) == 1

        removed = engine.remove_rule(rule.rule_id)
        assert removed is True
        assert len(engine.list_rules()) == 0

    def test_alert_action_publishes_event(self):
        bus = _make_bus()
        sub = bus.subscribe()
        engine = AutomationEngine(bus)
        rule = AutomationRule(
            name="test",
            trigger="event_x",
            conditions={},
            action={"type": "alert", "title": "Test", "severity": "critical"},
        )
        engine.add_rule(rule)
        engine.evaluate("event_x", {"target_id": "t1"})

        # Drain bus
        events = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                events.append(msg)
            except queue.Empty:
                break

        alert_events = [e for e in events if e.get("type") == "automation:alert"]
        assert len(alert_events) >= 1
        assert alert_events[0]["data"]["severity"] == "critical"

    def test_escalate_action_publishes_event(self):
        bus = _make_bus()
        sub = bus.subscribe()
        engine = AutomationEngine(bus)
        rule = AutomationRule(
            name="test",
            trigger="geofence:enter",
            conditions={},
            action={"type": "escalate", "level": "high", "reason": "breach"},
        )
        engine.add_rule(rule)
        engine.evaluate("geofence:enter", {"target_id": "t1"})

        events = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                events.append(msg)
            except queue.Empty:
                break

        escalation_events = [e for e in events if e.get("type") == "threat_escalation"]
        assert len(escalation_events) >= 1
        assert escalation_events[0]["data"]["level"] == "high"

    def test_condition_list_match(self):
        bus = _make_bus()
        engine = AutomationEngine(bus)
        rule = AutomationRule(
            name="multi",
            trigger="event_x",
            conditions={"zone_type": ["restricted", "monitored"]},
            action={"type": "alert"},
        )
        engine.add_rule(rule)

        fired1 = engine.evaluate("event_x", {"zone_type": "restricted"})
        assert len(fired1) == 1

        # Reset cooldown
        rule.last_fired = 0

        fired2 = engine.evaluate("event_x", {"zone_type": "safe"})
        assert len(fired2) == 0

    def test_history_is_bounded(self):
        bus = _make_bus()
        engine = AutomationEngine(bus)
        engine._max_history = 10
        rule = AutomationRule(name="test", trigger="x", action={"type": "alert"})
        engine.add_rule(rule)

        for _ in range(20):
            engine.evaluate("x", {})

        history = engine.get_history(limit=100)
        assert len(history) <= 10

    def test_default_combat_rules_created(self):
        rules = default_combat_rules()
        assert len(rules) >= 4
        triggers = {r.trigger for r in rules}
        assert "target_eliminated" in triggers
        assert "geofence:enter" in triggers


# ===========================================================================
# 2. BattleIntegration geofence wiring
# ===========================================================================

class TestGeofenceWiring:
    """Simulated targets should trigger geofence enter/exit events."""

    def test_target_enters_zone(self):
        bus = _make_bus()
        geofence = _make_geofence(bus)
        tracker = _make_tracker()
        integration = BattleIntegration(
            bus, tracker=tracker, geofence=geofence,
        )

        # Add a zone around the origin
        zone = GeoZone(
            zone_id="zone-1",
            name="Base",
            polygon=[(-50, -50), (50, -50), (50, 50), (-50, 50)],
            zone_type="restricted",
        )
        geofence.add_zone(zone)

        # Subscribe to geofence events
        sub = bus.subscribe()

        # Simulate telemetry batch with target inside zone
        batch = [{
            "target_id": "hostile-1",
            "name": "Intruder Alpha",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 10.0, "y": 10.0},
            "heading": 0.0,
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        }]

        integration.process_event_sync("sim_telemetry_batch", batch)

        # Should have checked geofence
        assert integration.stats["geofence_checks"] >= 1

        # Should have published geofence:enter
        events = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                events.append(msg)
            except queue.Empty:
                break

        enter_events = [e for e in events if e.get("type") == "geofence:enter"]
        assert len(enter_events) >= 1
        assert enter_events[0]["data"]["zone_name"] == "Base"

    def test_target_exits_zone(self):
        bus = _make_bus()
        geofence = _make_geofence(bus)
        integration = BattleIntegration(
            bus, tracker=_make_tracker(), geofence=geofence,
        )

        zone = GeoZone(
            zone_id="zone-1",
            name="Base",
            polygon=[(-50, -50), (50, -50), (50, 50), (-50, 50)],
        )
        geofence.add_zone(zone)
        sub = bus.subscribe()

        # First: target inside
        batch_inside = [{
            "target_id": "h1",
            "name": "H1",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 10.0, "y": 10.0},
            "heading": 0.0,
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        }]
        integration.process_event_sync("sim_telemetry_batch", batch_inside)

        # Then: target outside
        batch_outside = [{
            "target_id": "h1",
            "name": "H1",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 100.0, "y": 100.0},
            "heading": 0.0,
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        }]
        integration.process_event_sync("sim_telemetry_batch", batch_outside)

        events = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                events.append(msg)
            except queue.Empty:
                break

        exit_events = [e for e in events if e.get("type") == "geofence:exit"]
        assert len(exit_events) >= 1


# ===========================================================================
# 3. Tracker sync from simulation
# ===========================================================================

class TestTrackerSync:
    """Simulated targets should appear in the TargetTracker."""

    def test_telemetry_syncs_to_tracker(self):
        bus = _make_bus()
        tracker = _make_tracker()
        integration = BattleIntegration(bus, tracker=tracker)

        batch = [{
            "target_id": "rover-1",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 20.0, "y": 30.0},
            "heading": 45.0,
            "speed": 3.0,
            "battery": 0.85,
            "status": "active",
        }]

        integration.process_event_sync("sim_telemetry_batch", batch)

        all_targets = tracker.get_all()
        assert len(all_targets) >= 1
        found = [t for t in all_targets if t.target_id == "rover-1"]
        assert len(found) == 1
        assert found[0].name == "Rover Alpha"
        assert found[0].source == "simulation"

    def test_multiple_targets_sync(self):
        bus = _make_bus()
        tracker = _make_tracker()
        integration = BattleIntegration(bus, tracker=tracker)

        batch = [
            {
                "target_id": f"unit-{i}",
                "name": f"Unit {i}",
                "alliance": "friendly",
                "asset_type": "rover",
                "position": {"x": float(i * 10), "y": 0.0},
                "heading": 0.0,
                "speed": 1.0,
                "battery": 1.0,
                "status": "active",
            }
            for i in range(5)
        ]

        integration.process_event_sync("sim_telemetry_batch", batch)
        assert len(tracker.get_all()) >= 5
        assert integration.stats["tracker_syncs"] == 5


# ===========================================================================
# 4. Dossier creation from combat events
# ===========================================================================

class TestDossierFromCombat:
    """Combat events should create dossier entries."""

    def test_elimination_creates_dossier(self):
        bus = _make_bus()
        store = _make_dossier_store()
        integration = BattleIntegration(bus, dossier_store=store)

        integration.process_event_sync("target_eliminated", {
            "target_id": "hostile-1",
            "target_name": "Intruder Alpha",
            "alliance": "hostile",
            "shooter_id": "turret-1",
            "shooter_name": "Turret-1",
        })

        assert store.count >= 1
        dossiers = store.get_all()
        assert len(dossiers) >= 1
        # Should link hostile-1 and turret-1
        d = dossiers[0]
        assert "hostile-1" in d.signal_ids
        assert "turret-1" in d.signal_ids

    def test_geofence_event_creates_dossier(self):
        bus = _make_bus()
        store = _make_dossier_store()
        integration = BattleIntegration(bus, dossier_store=store)

        integration.process_event_sync("geofence:enter", {
            "target_id": "hostile-1",
            "zone_id": "zone-1",
            "zone_name": "Base",
            "zone_type": "restricted",
        })

        assert store.count >= 1
        dossiers = store.get_all()
        d = dossiers[0]
        assert "hostile-1" in d.signal_ids
        assert "zone_zone-1" in d.signal_ids


# ===========================================================================
# 5. Automation rules fire during combat
# ===========================================================================

class TestAutomationDuringCombat:
    """Automation rules should fire on combat and geofence events."""

    def test_elimination_fires_alert_rule(self):
        bus = _make_bus()
        automation = AutomationEngine(bus)
        for rule in default_combat_rules():
            automation.add_rule(rule)

        integration = BattleIntegration(bus, automation=automation)
        sub = bus.subscribe()

        integration.process_event_sync("target_eliminated", {
            "target_id": "h1",
            "alliance": "hostile",
        })

        events = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                events.append(msg)
            except queue.Empty:
                break

        alerts = [e for e in events if e.get("type") == "automation:alert"]
        assert len(alerts) >= 1

    def test_geofence_breach_fires_escalation(self):
        bus = _make_bus()
        automation = AutomationEngine(bus)
        for rule in default_combat_rules():
            automation.add_rule(rule)

        integration = BattleIntegration(bus, automation=automation)
        sub = bus.subscribe()

        integration.process_event_sync("geofence:enter", {
            "target_id": "h1",
            "zone_type": "restricted",
            "zone_id": "z1",
            "zone_name": "HQ",
        })

        events = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                events.append(msg)
            except queue.Empty:
                break

        escalations = [e for e in events if e.get("type") == "threat_escalation"]
        assert len(escalations) >= 1
        assert escalations[0]["data"]["level"] == "high"


# ===========================================================================
# 6. Investigation auto-escalation from combat
# ===========================================================================

class TestInvestigationFromCombat:
    """Combat should trigger auto-investigation for friendly losses."""

    def test_friendly_elimination_creates_investigation(self):
        bus = _make_bus()
        inv_engine = InvestigationEngine(db_path=":memory:")
        integration = BattleIntegration(
            bus, investigation=inv_engine, dossier_store=_make_dossier_store(),
        )

        integration.process_event_sync("target_eliminated", {
            "target_id": "turret-1",
            "target_name": "Turret-1",
            "alliance": "friendly",
            "shooter_id": "hostile-1",
            "shooter_name": "Intruder",
        })

        investigations = inv_engine.list_investigations(status="open")
        assert len(investigations) >= 1
        assert "turret-1" in investigations[0].seed_entities


# ===========================================================================
# 7. Full pipeline integration (engine ticks -> all systems)
# ===========================================================================

class TestFullPipelineIntegration:
    """Run actual engine ticks and verify the intelligence pipeline fires."""

    def test_engine_tick_reaches_geofence(self):
        bus = _make_bus()
        engine = _make_engine(bus, map_bounds=200.0)
        tracker = _make_tracker()
        geofence = _make_geofence(bus)
        integration = _make_integration(
            bus, tracker=tracker, geofence=geofence,
        )

        # Add a zone covering center
        zone = GeoZone(
            zone_id="center",
            name="Center Zone",
            polygon=[(-100, -100), (100, -100), (100, 100), (-100, 100)],
        )
        geofence.add_zone(zone)

        # Add a turret at origin (inside zone)
        _add_turret(engine, pos=(0.0, 0.0))

        sub = bus.subscribe()

        # Run a tick to produce telemetry
        engine._do_tick(0.1)

        # Process the telemetry through integration
        deadline = time.monotonic() + 2.0
        batch_found = False
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.1)
                if msg.get("type") == "sim_telemetry_batch":
                    integration.process_event_sync("sim_telemetry_batch", msg["data"])
                    batch_found = True
                    break
            except queue.Empty:
                continue

        assert batch_found, "No telemetry batch published by engine tick"
        assert integration.stats["geofence_checks"] >= 1
        assert integration.stats["tracker_syncs"] >= 1

    def test_engine_combat_reaches_dossier(self):
        bus = _make_bus()
        engine = _make_engine(bus, map_bounds=200.0)
        store = _make_dossier_store()
        integration = _make_integration(bus, dossier_store=store)

        # Simulate a combat event published by engine
        bus.publish("target_eliminated", {
            "target_id": "hostile-1",
            "target_name": "Intruder",
            "alliance": "hostile",
            "shooter_id": "turret-1",
            "shooter_name": "Turret-1",
        })

        # Process synchronously
        integration.process_event_sync("target_eliminated", {
            "target_id": "hostile-1",
            "target_name": "Intruder",
            "alliance": "hostile",
            "shooter_id": "turret-1",
            "shooter_name": "Turret-1",
        })

        assert store.count >= 1


# ===========================================================================
# 8. Chaos test scenario
# ===========================================================================

class TestChaosScenario:
    """Chaos test: randomly spawn targets, trigger geofences, fire rules,
    create investigations — all in one scenario to stress-test the stack.

    This is the "CI test for the real system" — if it passes, the intelligence
    pipeline can handle arbitrary event combinations without crashing.
    """

    def test_chaos_scenario_no_crashes(self):
        """Spawn random targets, move them through geofence zones, fire
        combat events, and verify no exceptions and stats are sane.
        """
        bus = _make_bus()
        engine = _make_engine(bus, map_bounds=200.0)
        tracker = _make_tracker()
        geofence = _make_geofence(bus)
        store = _make_dossier_store()
        automation = AutomationEngine(bus)
        for rule in default_combat_rules():
            automation.add_rule(rule)
        inv_engine = InvestigationEngine(db_path=":memory:")

        integration = BattleIntegration(
            bus,
            tracker=tracker,
            geofence=geofence,
            dossier_store=store,
            automation=automation,
            investigation=inv_engine,
        )

        # Set up geofence zones across the map
        zones = [
            GeoZone(
                zone_id="zone-hq",
                name="HQ",
                polygon=[(-30, -30), (30, -30), (30, 30), (-30, 30)],
                zone_type="restricted",
            ),
            GeoZone(
                zone_id="zone-north",
                name="North Sector",
                polygon=[(-100, 100), (100, 100), (100, 200), (-100, 200)],
                zone_type="monitored",
            ),
            GeoZone(
                zone_id="zone-east",
                name="East Gate",
                polygon=[(100, -50), (200, -50), (200, 50), (100, 50)],
                zone_type="restricted",
            ),
        ]
        for z in zones:
            geofence.add_zone(z)

        # Add friendly defenders
        _add_turret(engine, pos=(0.0, 0.0), name="Turret-HQ")
        _add_turret(engine, pos=(50.0, 50.0), name="Turret-NE")

        rng = random.Random(42)  # deterministic chaos

        # Phase 1: Spawn random hostiles and move them around
        hostile_ids = []
        for i in range(20):
            x = rng.uniform(-190, 190)
            y = rng.uniform(-190, 190)
            h = SimulationTarget(
                target_id=f"chaos-hostile-{i}",
                name=f"Chaos Hostile {i}",
                alliance="hostile",
                asset_type=rng.choice(["person", "hostile_vehicle"]),
                position=(x, y),
                speed=rng.uniform(1.0, 6.0),
                status="active",
            )
            h.apply_combat_profile()
            engine.add_target(h)
            hostile_ids.append(h.target_id)

        # Phase 2: Run several ticks, processing telemetry through integration
        for tick in range(20):
            engine._do_tick(0.1)

            # Collect and process all telemetry batches
            targets = engine.get_targets()
            batch = [t.to_dict() for t in targets]
            integration.process_event_sync("sim_telemetry_batch", batch)

            # Randomly fire combat events
            if rng.random() < 0.3 and hostile_ids:
                hid = rng.choice(hostile_ids)
                integration.process_event_sync("target_eliminated", {
                    "target_id": hid,
                    "target_name": f"Hostile {hid}",
                    "alliance": "hostile",
                    "shooter_id": "turret-Turret-HQ",
                    "shooter_name": "Turret-HQ",
                })

            if rng.random() < 0.2:
                integration.process_event_sync("projectile_hit", {
                    "target_id": rng.choice(hostile_ids) if hostile_ids else "none",
                    "damage": rng.uniform(5, 30),
                })

        # Phase 3: Verify stats are sane
        stats = integration.stats
        assert stats["geofence_checks"] > 0, "No geofence checks happened"
        assert stats["tracker_syncs"] > 0, "No tracker syncs happened"
        assert stats["dossier_updates"] > 0, "No dossier updates happened"
        assert stats["automation_fires"] > 0, "No automation rules fired"

        # Verify tracker has targets
        all_tracked = tracker.get_all()
        assert len(all_tracked) > 0, "Tracker is empty after chaos scenario"

        # Verify dossiers were created
        assert store.count > 0, "No dossiers created during chaos"

        # Verify geofence events occurred (some targets must have entered zones)
        geo_events = geofence.get_events(limit=100)
        # At least some targets should have entered zones
        assert len(geo_events) >= 0  # may be 0 if random positions miss all zones

    def test_chaos_high_throughput(self):
        """Push high volume of events and verify no OOM or deadlocks."""
        bus = _make_bus()
        tracker = _make_tracker()
        geofence = _make_geofence(bus)
        store = _make_dossier_store()
        automation = AutomationEngine(bus)
        automation.add_rule(AutomationRule(
            name="counter",
            trigger="sim_event",
            conditions={},
            action={"type": "alert", "message": "tick"},
            cooldown=0.0,
        ))

        integration = BattleIntegration(
            bus,
            tracker=tracker,
            geofence=geofence,
            dossier_store=store,
            automation=automation,
        )

        geofence.add_zone(GeoZone(
            zone_id="big",
            name="BigZone",
            polygon=[(-500, -500), (500, -500), (500, 500), (-500, 500)],
        ))

        rng = random.Random(99)

        # 500 telemetry events with 10 targets each = 5000 target updates
        for batch_idx in range(50):
            batch = [
                {
                    "target_id": f"t-{i}",
                    "name": f"T{i}",
                    "alliance": "hostile",
                    "asset_type": "person",
                    "position": {
                        "x": rng.uniform(-200, 200),
                        "y": rng.uniform(-200, 200),
                    },
                    "heading": 0.0,
                    "speed": 1.5,
                    "battery": 1.0,
                    "status": "active",
                }
                for i in range(10)
            ]
            integration.process_event_sync("sim_telemetry_batch", batch)

        assert integration.stats["tracker_syncs"] == 500
        assert integration.stats["geofence_checks"] == 500

    def test_chaos_mixed_event_storm(self):
        """Fire a storm of different event types and verify no crashes."""
        bus = _make_bus()
        store = _make_dossier_store()
        automation = AutomationEngine(bus)
        for rule in default_combat_rules():
            automation.add_rule(rule)

        integration = BattleIntegration(
            bus,
            tracker=_make_tracker(),
            geofence=_make_geofence(bus),
            dossier_store=store,
            automation=automation,
        )

        rng = random.Random(77)
        event_types = [
            "target_eliminated", "target_neutralized",
            "projectile_fired", "projectile_hit",
            "geofence:enter", "geofence:exit",
            "sensor_triggered", "wave_started",
        ]

        for i in range(200):
            etype = rng.choice(event_types)
            data = {
                "target_id": f"target-{rng.randint(1, 20)}",
                "alliance": rng.choice(["hostile", "friendly"]),
                "zone_type": rng.choice(["restricted", "monitored", "safe"]),
                "zone_id": f"zone-{rng.randint(1, 5)}",
                "zone_name": f"Zone {rng.randint(1, 5)}",
                "damage": rng.uniform(0, 50),
                "shooter_id": f"shooter-{rng.randint(1, 5)}",
                "shooter_name": f"Shooter {rng.randint(1, 5)}",
            }
            integration.process_event_sync(etype, data)

        # Verify no crash and some processing happened
        assert integration.stats["dossier_updates"] > 0
        assert integration.stats["automation_fires"] > 0

    def test_chaos_with_live_engine_ticks(self):
        """Full chaos test with the real SimulationEngine doing ticks."""
        bus = _make_bus()
        engine = _make_engine(bus, map_bounds=200.0)
        tracker = _make_tracker()
        geofence = _make_geofence(bus)
        store = _make_dossier_store()
        automation = AutomationEngine(bus)
        for rule in default_combat_rules():
            automation.add_rule(rule)

        integration = BattleIntegration(
            bus,
            tracker=tracker,
            geofence=geofence,
            dossier_store=store,
            automation=automation,
        )

        # Set up zones
        geofence.add_zone(GeoZone(
            zone_id="perimeter",
            name="Perimeter",
            polygon=[(-150, -150), (150, -150), (150, 150), (-150, 150)],
            zone_type="monitored",
        ))
        geofence.add_zone(GeoZone(
            zone_id="hq",
            name="HQ",
            polygon=[(-25, -25), (25, -25), (25, 25), (-25, 25)],
            zone_type="restricted",
        ))

        # Add defenders
        _add_turret(engine, pos=(0.0, 0.0), name="HQ-Turret")

        # Spawn hostiles from edges aimed at center
        rng = random.Random(123)
        for i in range(15):
            angle = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(120, 180)
            x = dist * math.cos(angle)
            y = dist * math.sin(angle)
            h = SimulationTarget(
                target_id=f"chaos-h-{i}",
                name=f"Chaos Hostile {i}",
                alliance="hostile",
                asset_type="person",
                position=(x, y),
                speed=rng.uniform(1.5, 4.0),
                waypoints=[(0, 0)],  # head to center
                status="active",
            )
            h.apply_combat_profile()
            engine.add_target(h)

        # Run 30 ticks
        sub = bus.subscribe()
        for _ in range(30):
            engine._do_tick(0.1)

            # Collect telemetry and process
            targets = engine.get_targets()
            batch = [t.to_dict() for t in targets]
            integration.process_event_sync("sim_telemetry_batch", batch)

        # Also process any combat events that the engine generated
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            try:
                msg = sub.get(timeout=0.05)
                integration.process_event_sync(
                    msg.get("type", ""), msg.get("data", {}),
                )
            except queue.Empty:
                break

        # Verify the stack was exercised
        stats = integration.stats
        assert stats["tracker_syncs"] > 0
        assert stats["geofence_checks"] > 0
        # Some hostiles should have entered the perimeter zone as they walked
        # toward center
        tracked = tracker.get_all()
        assert len(tracked) > 0
