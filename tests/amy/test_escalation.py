"""Tests for amy.escalation — ThreatClassifier and AutoDispatcher."""

from __future__ import annotations

import math
import time

import pytest

from amy.escalation import (
    THREAT_LEVELS,
    AutoDispatcher,
    ThreatClassifier,
    ThreatRecord,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEventBus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict) -> None:
        self.published.append((event_type, data))

    def subscribe(self):
        import queue
        q = queue.Queue()
        return q

    def unsubscribe(self, q) -> None:
        pass


class MockTrackedTarget:
    def __init__(
        self,
        target_id: str,
        alliance: str = "hostile",
        position: tuple[float, float] = (5.0, 5.0),
        battery: float = 1.0,
        status: str = "active",
        name: str = "Target",
        asset_type: str = "rover",
    ):
        self.target_id = target_id
        self.alliance = alliance
        self.position = position
        self.battery = battery
        self.status = status
        self.name = name
        self.asset_type = asset_type


class MockTargetTracker:
    def __init__(self, targets: list | None = None):
        self._targets: list[MockTrackedTarget] = targets or []

    def get_all(self) -> list[MockTrackedTarget]:
        return list(self._targets)

    def get_target(self, target_id: str) -> MockTrackedTarget | None:
        for t in self._targets:
            if t.target_id == target_id:
                return t
        return None

    def get_friendlies(self) -> list[MockTrackedTarget]:
        return [t for t in self._targets if t.alliance == "friendly"]


# ---------------------------------------------------------------------------
# Zone fixtures
# ---------------------------------------------------------------------------


def _perimeter_zone(x: float = 5.0, z: float = 5.0, radius: float = 10.0) -> dict:
    return {
        "name": "front_yard",
        "type": "perimeter",
        "position": {"x": x, "z": z},
        "properties": {"radius": radius},
    }


def _restricted_zone(x: float = 0.0, z: float = 0.0, radius: float = 5.0) -> dict:
    return {
        "name": "backyard",
        "type": "restricted",
        "position": {"x": x, "z": z},
        "properties": {"radius": radius},
    }


# ===================================================================
# ThreatClassifier tests
# ===================================================================


class TestThreatClassifierInit:
    @pytest.mark.unit
    def test_init_creates_empty_records(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)
        assert tc.get_records() == {}
        assert tc.get_active_threats() == []

    @pytest.mark.unit
    def test_init_accepts_zones(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zones = [_perimeter_zone()]
        tc = ThreatClassifier(bus, tracker, zones=zones)
        assert tc.zones == zones


class TestThreatClassifierFriendlySkip:
    @pytest.mark.unit
    def test_friendly_targets_are_skipped(self):
        bus = MockEventBus()
        tracker = MockTargetTracker(
            [MockTrackedTarget("f1", alliance="friendly", position=(5.0, 5.0))]
        )
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])
        tc._classify_tick()
        assert tc.get_records() == {}


class TestThreatClassifierNeutralSkip:
    @pytest.mark.unit
    def test_neutral_targets_are_skipped(self):
        """Neutral targets (neighbors, cars, animals from AmbientSpawner)
        should not be classified or trigger zone violations."""
        bus = MockEventBus()
        tracker = MockTargetTracker(
            [MockTrackedTarget("n1", alliance="neutral", position=(5.0, 5.0))]
        )
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])
        tc._classify_tick()
        assert tc.get_records() == {}
        # No zone_violation events should be published
        violations = [e for e in bus.published if e[0] == "zone_violation"]
        assert len(violations) == 0

    @pytest.mark.unit
    def test_neutral_in_restricted_zone_is_skipped(self):
        """Neutral targets inside restricted zones should not escalate."""
        bus = MockEventBus()
        tracker = MockTargetTracker(
            [MockTrackedTarget("n1", alliance="neutral", position=(1.0, 1.0))]
        )
        tc = ThreatClassifier(bus, tracker, zones=[_restricted_zone()])
        tc._classify_tick()
        assert tc.get_records() == {}
        esc_events = [e for e in bus.published if e[0] == "threat_escalation"]
        assert len(esc_events) == 0


class TestThreatClassifierEscalation:
    @pytest.mark.unit
    def test_perimeter_zone_entry_escalates_none_to_unknown(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()

        records = tc.get_records()
        assert "t1" in records
        assert records["t1"].threat_level == "unknown"

    @pytest.mark.unit
    def test_restricted_zone_entry_escalates_to_suspicious(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(1.0, 1.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_restricted_zone()])

        tc._classify_tick()

        records = tc.get_records()
        assert records["t1"].threat_level == "suspicious"

    @pytest.mark.unit
    def test_restricted_zone_skips_unknown_goes_straight_to_suspicious(self):
        """A target entering a restricted zone should go from none directly
        to suspicious, not stopping at unknown."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(1.0, 1.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_restricted_zone()])

        tc._classify_tick()

        records = tc.get_records()
        assert records["t1"].threat_level == "suspicious"
        # Only one escalation event, none->suspicious
        esc_events = [
            e for e in bus.published if e[0] == "threat_escalation"
        ]
        assert len(esc_events) == 1
        assert esc_events[0][1]["old_level"] == "none"
        assert esc_events[0][1]["new_level"] == "suspicious"

    @pytest.mark.unit
    def test_linger_escalates_to_hostile(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        # First tick — creates record, escalates to unknown
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "unknown"

        # Simulate time passing beyond linger threshold
        with tc._lock:
            tc._records["t1"].zone_enter_time = time.monotonic() - 31.0

        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "hostile"

    @pytest.mark.unit
    def test_linger_in_restricted_zone_escalates_suspicious_to_hostile(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(1.0, 1.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_restricted_zone()])

        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "suspicious"

        # Simulate lingering
        with tc._lock:
            tc._records["t1"].zone_enter_time = time.monotonic() - 31.0

        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "hostile"


class TestThreatClassifierDeescalation:
    @pytest.mark.unit
    def test_target_leaving_zones_deescalates_one_step(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        zone = _perimeter_zone()
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        # Escalate to unknown
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "unknown"

        # Move target outside all zones
        target.position = (100.0, 100.0)
        tc._classify_tick()

        # Still unknown — need to wait 30s
        assert tc.get_records()["t1"].threat_level == "unknown"

        # Simulate 30s passing since zone exit
        tc._zone_exit_times["t1"] = time.monotonic() - 31.0
        tc._classify_tick()

        assert tc.get_records()["t1"].threat_level == "none"

    @pytest.mark.unit
    def test_deescalation_cascades_over_time(self):
        """hostile -> suspicious -> unknown -> none, each step after 30s."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(100.0, 100.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        # Manually set up a hostile record that is outside zones
        with tc._lock:
            tc._records["t1"] = ThreatRecord(
                target_id="t1", threat_level="hostile"
            )
            tc._zone_exit_times["t1"] = time.monotonic() - 31.0

        # Step 1: hostile -> suspicious
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "suspicious"

        # Simulate another 30s
        tc._zone_exit_times["t1"] = time.monotonic() - 31.0
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "unknown"

        # Another 30s
        tc._zone_exit_times["t1"] = time.monotonic() - 31.0
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "none"

    @pytest.mark.unit
    def test_deescalation_resets_timer_on_step_down(self):
        """After a de-escalation step, the exit timer should reset so the
        next step requires another 30s wait."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(100.0, 100.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        with tc._lock:
            tc._records["t1"] = ThreatRecord(
                target_id="t1", threat_level="hostile"
            )
            tc._zone_exit_times["t1"] = time.monotonic() - 31.0

        # First de-escalation: hostile -> suspicious
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "suspicious"

        # Immediately tick again — should NOT de-escalate yet (timer was reset)
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "suspicious"


class TestThreatClassifierEvents:
    @pytest.mark.unit
    def test_escalation_publishes_threat_escalation_event(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()

        esc_events = [e for e in bus.published if e[0] == "threat_escalation"]
        assert len(esc_events) == 1
        data = esc_events[0][1]
        assert data["target_id"] == "t1"
        assert data["old_level"] == "none"
        assert data["new_level"] == "unknown"
        assert "reason" in data

    @pytest.mark.unit
    def test_deescalation_publishes_threat_deescalation_event(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(100.0, 100.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        with tc._lock:
            tc._records["t1"] = ThreatRecord(
                target_id="t1", threat_level="unknown"
            )
            tc._zone_exit_times["t1"] = time.monotonic() - 31.0

        tc._classify_tick()

        deesc_events = [e for e in bus.published if e[0] == "threat_deescalation"]
        assert len(deesc_events) == 1
        data = deesc_events[0][1]
        assert data["target_id"] == "t1"
        assert data["old_level"] == "unknown"
        assert data["new_level"] == "none"
        assert data["reason"] == "de-escalation"

    @pytest.mark.unit
    def test_no_event_when_level_unchanged(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        bus.published.clear()

        # Tick again — target still in zone, still unknown, no new event
        tc._classify_tick()
        assert len(bus.published) == 0


class TestThreatClassifierManualOverride:
    @pytest.mark.unit
    def test_manual_override_changes_level(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "unknown"

        tc.set_threat_level("t1", "hostile")
        assert tc.get_records()["t1"].threat_level == "hostile"

    @pytest.mark.unit
    def test_manual_override_publishes_event(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        bus.published.clear()

        tc.set_threat_level("t1", "hostile")

        esc_events = [e for e in bus.published if e[0] == "threat_escalation"]
        assert len(esc_events) == 1
        assert esc_events[0][1]["reason"] == "manual_override"

    @pytest.mark.unit
    def test_manual_override_ignores_invalid_level(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        tc.set_threat_level("t1", "bogus_level")
        assert tc.get_records()["t1"].threat_level == "unknown"

    @pytest.mark.unit
    def test_manual_override_ignores_unknown_target(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)

        # Should not raise
        tc.set_threat_level("nonexistent", "hostile")
        assert tc.get_records() == {}

    @pytest.mark.unit
    def test_manual_override_no_event_if_same_level(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        bus.published.clear()

        tc.set_threat_level("t1", "unknown")  # same level
        assert len(bus.published) == 0


class TestThreatClassifierPruning:
    @pytest.mark.unit
    def test_stale_records_pruned_when_target_disappears(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        assert "t1" in tc.get_records()

        # Remove target from tracker
        tracker._targets.clear()
        tc._classify_tick()

        assert "t1" not in tc.get_records()

    @pytest.mark.unit
    def test_zone_exit_times_cleaned_on_prune(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        # Simulate zone exit tracking
        tc._zone_exit_times["t1"] = time.monotonic()

        tracker._targets.clear()
        tc._classify_tick()

        assert "t1" not in tc._zone_exit_times


class TestThreatClassifierFindZone:
    @pytest.mark.unit
    def test_find_zone_returns_zone_for_position_inside(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = _perimeter_zone(x=5.0, z=5.0, radius=10.0)
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        result = tc._find_zone((5.0, 5.0))
        assert result is not None
        assert result["name"] == "front_yard"

    @pytest.mark.unit
    def test_find_zone_returns_none_for_position_outside(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = _perimeter_zone(x=5.0, z=5.0, radius=10.0)
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        result = tc._find_zone((100.0, 100.0))
        assert result is None

    @pytest.mark.unit
    def test_find_zone_uses_z_coordinate(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = {"name": "z_zone", "type": "perimeter",
                "position": {"x": 0.0, "z": 10.0},
                "properties": {"radius": 3.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        assert tc._find_zone((0.0, 10.0)) is not None
        assert tc._find_zone((0.0, 0.0)) is None

    @pytest.mark.unit
    def test_find_zone_falls_back_to_y_coordinate(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = {"name": "y_zone", "type": "perimeter",
                "position": {"x": 0.0, "y": 10.0},
                "properties": {"radius": 3.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        assert tc._find_zone((0.0, 10.0)) is not None

    @pytest.mark.unit
    def test_find_zone_prefers_restricted_over_perimeter(self):
        """If a point is inside both a perimeter and restricted zone,
        the restricted zone should be returned regardless of list order."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        # Perimeter is listed first but restricted should win
        perimeter = _perimeter_zone(x=0.0, z=0.0, radius=20.0)
        restricted = _restricted_zone(x=0.0, z=0.0, radius=5.0)
        tc = ThreatClassifier(bus, tracker, zones=[perimeter, restricted])

        result = tc._find_zone((1.0, 1.0))
        assert result is not None
        assert result["name"] == "backyard"
        assert "restricted" in result["type"]

    @pytest.mark.unit
    def test_find_zone_boundary_exact_radius(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = _perimeter_zone(x=0.0, z=0.0, radius=5.0)
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        # Exactly at radius boundary (5 units away)
        assert tc._find_zone((5.0, 0.0)) is not None
        # Just outside
        assert tc._find_zone((5.1, 0.0)) is None


class TestThreatClassifierGetActiveThreats:
    @pytest.mark.unit
    def test_get_active_threats_returns_non_none_records(self):
        bus = MockEventBus()
        t1 = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        t2 = MockTrackedTarget("t2", alliance="hostile", position=(100.0, 100.0))
        tracker = MockTargetTracker([t1, t2])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()

        active = tc.get_active_threats()
        # t1 is in zone (unknown), t2 is outside (none)
        assert len(active) == 1
        assert active[0].target_id == "t1"
        assert active[0].threat_level == "unknown"

    @pytest.mark.unit
    def test_get_active_threats_empty_when_all_none(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(100.0, 100.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        assert tc.get_active_threats() == []


class TestThreatClassifierZonesSetter:
    @pytest.mark.unit
    def test_zones_can_be_updated_via_property(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)
        assert tc.zones == []

        new_zones = [_perimeter_zone(), _restricted_zone()]
        tc.zones = new_zones
        assert tc.zones == new_zones
        assert len(tc.zones) == 2


# ===================================================================
# AutoDispatcher tests
# ===================================================================


class TestAutoDispatcherInit:
    @pytest.mark.unit
    def test_init_stores_references(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker)
        assert ad._event_bus is bus
        assert ad._tracker is tracker
        assert ad._engine is None
        assert ad._mqtt is None
        assert ad.active_dispatches == {}

    @pytest.mark.unit
    def test_init_with_engine_and_mqtt(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        engine = object()
        mqtt = object()
        ad = AutoDispatcher(bus, tracker, simulation_engine=engine, mqtt_bridge=mqtt)
        assert ad._engine is engine
        assert ad._mqtt is mqtt


class TestAutoDispatcherTryDispatch:
    @pytest.mark.unit
    def test_finds_nearest_available_friendly(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        far_unit = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Far Unit"
        )
        near_unit = MockTrackedTarget(
            "f2", alliance="friendly", position=(8.0, 8.0),
            battery=1.0, status="active", name="Near Unit"
        )
        tracker = MockTargetTracker([hostile, far_unit, near_unit])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")

        assert ad.active_dispatches == {"h1": "f2"}
        dispatch_events = [e for e in bus.published if e[0] == "amy_dispatch"]
        assert len(dispatch_events) == 1
        assert dispatch_events[0][1]["target_id"] == "f2"
        assert dispatch_events[0][1]["name"] == "Near Unit"

    @pytest.mark.unit
    def test_skips_low_battery_units(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        low_bat = MockTrackedTarget(
            "f1", alliance="friendly", position=(8.0, 8.0),
            battery=0.10, status="active", name="Low Battery"
        )
        ok_bat = MockTrackedTarget(
            "f2", alliance="friendly", position=(0.0, 0.0),
            battery=0.50, status="active", name="Good Battery"
        )
        tracker = MockTargetTracker([hostile, low_bat, ok_bat])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")

        # Should dispatch f2 (good battery) even though f1 is closer
        assert ad.active_dispatches == {"h1": "f2"}

    @pytest.mark.unit
    def test_skips_already_dispatched_units(self):
        bus = MockEventBus()
        h1 = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        h2 = MockTrackedTarget("h2", alliance="hostile", position=(20.0, 20.0))
        f1 = MockTrackedTarget(
            "f1", alliance="friendly", position=(8.0, 8.0),
            battery=1.0, status="active", name="Unit 1"
        )
        f2 = MockTrackedTarget(
            "f2", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit 2"
        )
        tracker = MockTargetTracker([h1, h2, f1, f2])
        ad = AutoDispatcher(bus, tracker)

        # Dispatch f1 to h1
        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches["h1"] == "f1"

        # Now dispatch for h2 — f1 is taken, should use f2
        ad._try_dispatch("h2", "hostile")
        assert ad.active_dispatches["h2"] == "f2"

    @pytest.mark.unit
    def test_does_nothing_when_no_units_available(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        tracker = MockTargetTracker([hostile])  # no friendlies
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")

        assert ad.active_dispatches == {}
        assert len(bus.published) == 0

    @pytest.mark.unit
    def test_does_nothing_when_all_units_low_battery(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        f1 = MockTrackedTarget(
            "f1", alliance="friendly", position=(8.0, 8.0),
            battery=0.05, status="active", name="Empty"
        )
        tracker = MockTargetTracker([hostile, f1])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")

        assert ad.active_dispatches == {}

    @pytest.mark.unit
    def test_does_nothing_when_threat_not_in_tracker(self):
        bus = MockEventBus()
        f1 = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit"
        )
        tracker = MockTargetTracker([f1])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("nonexistent", "hostile")
        assert ad.active_dispatches == {}

    @pytest.mark.unit
    def test_publishes_amy_dispatch_event(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Rover Alpha"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")

        dispatch_events = [e for e in bus.published if e[0] == "amy_dispatch"]
        assert len(dispatch_events) == 1
        data = dispatch_events[0][1]
        assert data["target_id"] == "f1"
        assert data["name"] == "Rover Alpha"
        assert data["destination"]["x"] == 10.0
        assert data["destination"]["y"] == 10.0
        assert data["reason"] == "intercept_hostile"
        assert data["threat_id"] == "h1"

    @pytest.mark.unit
    def test_publishes_auto_dispatch_speech_event(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Rover Alpha"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")

        speech_events = [e for e in bus.published if e[0] == "auto_dispatch_speech"]
        assert len(speech_events) == 1
        text = speech_events[0][1]["text"]
        assert "Rover Alpha" in text
        assert "intercept" in text.lower()
        assert "bearing" in text.lower()

    @pytest.mark.unit
    def test_double_dispatch_prevention(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        f1 = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit 1"
        )
        f2 = MockTrackedTarget(
            "f2", alliance="friendly", position=(5.0, 5.0),
            battery=1.0, status="active", name="Unit 2"
        )
        tracker = MockTargetTracker([hostile, f1, f2])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        dispatched_unit = ad.active_dispatches["h1"]

        bus.published.clear()
        ad._try_dispatch("h1", "hostile")

        # Should not dispatch again
        assert ad.active_dispatches == {"h1": dispatched_unit}
        assert len(bus.published) == 0


class TestAutoDispatcherClearDispatch:
    @pytest.mark.unit
    def test_clear_dispatch_removes_from_active(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert "h1" in ad.active_dispatches

        ad.clear_dispatch("h1")
        assert "h1" not in ad.active_dispatches

    @pytest.mark.unit
    def test_clear_dispatch_nonexistent_is_safe(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker)

        # Should not raise
        ad.clear_dispatch("nonexistent")
        assert ad.active_dispatches == {}


class TestAutoDispatcherActiveDispatches:
    @pytest.mark.unit
    def test_active_dispatches_returns_copy(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker)

        with ad._lock:
            ad._active_dispatches["h1"] = "f1"

        result = ad.active_dispatches
        result["h2"] = "f2"  # modify the copy

        # Original should be unchanged
        assert "h2" not in ad.active_dispatches

    @pytest.mark.unit
    def test_skips_non_active_idle_units(self):
        """Units with status other than 'active' or 'idle' should be skipped."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        f1 = MockTrackedTarget(
            "f1", alliance="friendly", position=(8.0, 8.0),
            battery=1.0, status="disabled", name="Disabled Unit"
        )
        f2 = MockTrackedTarget(
            "f2", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="idle", name="Idle Unit"
        )
        tracker = MockTargetTracker([hostile, f1, f2])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")

        # Should skip disabled f1, dispatch idle f2
        assert ad.active_dispatches == {"h1": "f2"}


class TestAutoDispatcherMqtt:
    @pytest.mark.unit
    def test_publishes_to_mqtt_when_bridge_available(self):
        bus = MockEventBus()

        class MockMqtt:
            def __init__(self):
                self.dispatches = []
                self.alerts = []
            def publish_dispatch(self, unit_id, x, y):
                self.dispatches.append((unit_id, x, y))
            def publish_alert(self, data):
                self.alerts.append(data)

        mqtt = MockMqtt()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker, mqtt_bridge=mqtt)

        ad._try_dispatch("h1", "hostile")

        assert len(mqtt.dispatches) == 1
        assert mqtt.dispatches[0] == ("f1", 10.0, 10.0)
        assert len(mqtt.alerts) == 1
        assert mqtt.alerts[0]["level"] == "hostile"

    @pytest.mark.unit
    def test_no_mqtt_when_bridge_is_none(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker, mqtt_bridge=None)

        # Should not raise even without mqtt
        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches == {"h1": "f1"}


# ===================================================================
# Edge Case Tests — Zone Boundary & Oscillation
# ===================================================================


class TestZoneBoundaryOscillation:
    """Tests for targets at or near the exact zone radius distance."""

    @pytest.mark.unit
    def test_target_at_exact_radius_is_inside_zone(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = _perimeter_zone(x=0.0, z=0.0, radius=10.0)
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        # Distance is exactly 10.0
        assert tc._find_zone((10.0, 0.0)) is not None
        assert tc._find_zone((0.0, 10.0)) is not None

    @pytest.mark.unit
    def test_target_just_outside_radius_is_outside_zone(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = _perimeter_zone(x=0.0, z=0.0, radius=10.0)
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        # Slightly beyond radius
        assert tc._find_zone((10.001, 0.0)) is None

    @pytest.mark.unit
    def test_boundary_oscillation_causes_reentry_event(self):
        """Target at exact boundary that moves just outside then back in
        should produce a new zone_violation event on re-entry."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(10.0, 0.0))
        tracker = MockTargetTracker([target])
        zone = _perimeter_zone(x=0.0, z=0.0, radius=10.0)
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        # Enter zone
        tc._classify_tick()
        violation_count_1 = sum(1 for e in bus.published if e[0] == "zone_violation")
        assert violation_count_1 == 1

        # Move outside
        target.position = (10.1, 0.0)
        tc._classify_tick()

        # Move back in
        target.position = (10.0, 0.0)
        tc._classify_tick()
        violation_count_2 = sum(1 for e in bus.published if e[0] == "zone_violation")
        assert violation_count_2 == 2  # second entry event

    @pytest.mark.unit
    def test_diagonal_at_exact_radius(self):
        """Diagonal position where hypot equals radius exactly."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = _perimeter_zone(x=0.0, z=0.0, radius=5.0)
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        # 3-4-5 triangle: distance = 5.0 exactly
        result = tc._find_zone((3.0, 4.0))
        assert result is not None


# ===================================================================
# Edge Case Tests — Overlapping Zones
# ===================================================================


class TestOverlappingZones:
    @pytest.mark.unit
    def test_two_restricted_zones_first_wins(self):
        """When a target is in two overlapping restricted zones,
        the first restricted zone in the list is returned."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        r1 = {"name": "zone_a", "type": "restricted",
               "position": {"x": 0.0, "z": 0.0},
               "properties": {"radius": 10.0}}
        r2 = {"name": "zone_b", "type": "restricted",
               "position": {"x": 0.0, "z": 0.0},
               "properties": {"radius": 10.0}}
        tc = ThreatClassifier(bus, tracker, zones=[r1, r2])

        result = tc._find_zone((0.0, 0.0))
        assert result["name"] == "zone_a"

    @pytest.mark.unit
    def test_two_restricted_zones_reversed_order(self):
        """Reversed list order — second restricted zone becomes first."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        r1 = {"name": "zone_a", "type": "restricted",
               "position": {"x": 0.0, "z": 0.0},
               "properties": {"radius": 10.0}}
        r2 = {"name": "zone_b", "type": "restricted",
               "position": {"x": 0.0, "z": 0.0},
               "properties": {"radius": 10.0}}
        tc = ThreatClassifier(bus, tracker, zones=[r2, r1])

        result = tc._find_zone((0.0, 0.0))
        assert result["name"] == "zone_b"

    @pytest.mark.unit
    def test_perimeter_inside_restricted_prefers_restricted(self):
        """Perimeter zone listed first, target in both — restricted wins."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        perim = _perimeter_zone(x=0.0, z=0.0, radius=20.0)
        restr = _restricted_zone(x=0.0, z=0.0, radius=5.0)
        tc = ThreatClassifier(bus, tracker, zones=[perim, restr])

        result = tc._find_zone((2.0, 2.0))
        assert "restricted" in result["type"]

    @pytest.mark.unit
    def test_two_perimeter_zones_first_wins(self):
        """Two non-restricted zones overlapping — first match wins."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        p1 = {"name": "zone_a", "type": "perimeter",
              "position": {"x": 0.0, "z": 0.0},
              "properties": {"radius": 10.0}}
        p2 = {"name": "zone_b", "type": "perimeter",
              "position": {"x": 0.0, "z": 0.0},
              "properties": {"radius": 10.0}}
        tc = ThreatClassifier(bus, tracker, zones=[p1, p2])

        result = tc._find_zone((0.0, 0.0))
        assert result["name"] == "zone_a"


# ===================================================================
# Edge Case Tests — Zone with Radius 0
# ===================================================================


class TestZoneRadiusZero:
    @pytest.mark.unit
    def test_radius_zero_matches_exact_center_only(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = {"name": "pinpoint", "type": "perimeter",
                "position": {"x": 5.0, "z": 5.0},
                "properties": {"radius": 0.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        assert tc._find_zone((5.0, 5.0)) is not None
        assert tc._find_zone((5.0, 5.001)) is None
        assert tc._find_zone((5.001, 5.0)) is None

    @pytest.mark.unit
    def test_radius_zero_escalates_target_at_center(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        zone = {"name": "pinpoint", "type": "perimeter",
                "position": {"x": 5.0, "z": 5.0},
                "properties": {"radius": 0.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "unknown"


# ===================================================================
# Edge Case Tests — Zone with Missing Fields
# ===================================================================


class TestZoneMissingFields:
    @pytest.mark.unit
    def test_zone_missing_position_defaults_to_origin(self):
        """Zone without a 'position' key treats center as (0, 0)."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = {"name": "no_pos", "type": "perimeter",
                "properties": {"radius": 5.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        # Target at origin should match
        assert tc._find_zone((0.0, 0.0)) is not None
        # Target far away should not
        assert tc._find_zone((100.0, 100.0)) is None

    @pytest.mark.unit
    def test_zone_missing_properties_uses_default_radius(self):
        """Zone without 'properties' key uses default radius of 10.0."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = {"name": "no_props", "type": "perimeter",
                "position": {"x": 0.0, "z": 0.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        # Within default radius of 10
        assert tc._find_zone((5.0, 5.0)) is not None
        # Outside default radius of 10
        assert tc._find_zone((8.0, 8.0)) is None  # hypot(8,8) = 11.3

    @pytest.mark.unit
    def test_zone_missing_type_defaults_to_empty(self):
        """Zone without 'type' key — 'restricted' not in '' so treated as perimeter."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(0.0, 0.0))
        tracker = MockTargetTracker([target])
        zone = {"name": "no_type",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        tc._classify_tick()
        # Without "restricted" in type, goes to unknown (not suspicious)
        assert tc.get_records()["t1"].threat_level == "unknown"

    @pytest.mark.unit
    def test_zone_missing_name_uses_type_for_tracking(self):
        """Zone without 'name' — in_zone should use zone_type as fallback."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(0.0, 0.0))
        tracker = MockTargetTracker([target])
        zone = {"type": "perimeter",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        tc._classify_tick()
        record = tc.get_records()["t1"]
        assert record.in_zone == "perimeter"

    @pytest.mark.unit
    def test_completely_empty_zone_dict(self):
        """An empty dict zone should not crash — all fields use defaults."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker, zones=[{}])

        # Center (0,0) with default radius 10 — should match
        result = tc._find_zone((0.0, 0.0))
        assert result is not None

    @pytest.mark.unit
    def test_empty_zone_does_not_crash_classify(self):
        """A completely empty zone dict should not crash _classify_tick.
        Zone name falls back to '<unnamed>' to avoid collision with
        the initial in_zone='' state."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(0.0, 0.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[{}])

        # Should not raise
        tc._classify_tick()
        record = tc.get_records()["t1"]
        # Escalates to unknown (perimeter-type zone, just entered)
        assert record.threat_level == "unknown"
        assert record.in_zone == "<unnamed>"


# ===================================================================
# Edge Case Tests — Target at (0,0) on Zone at (0,0)
# ===================================================================


class TestTargetAtOrigin:
    @pytest.mark.unit
    def test_target_and_zone_both_at_origin(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = _perimeter_zone(x=0.0, z=0.0, radius=5.0)
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        result = tc._find_zone((0.0, 0.0))
        assert result is not None  # dist=0.0 <= 5.0

    @pytest.mark.unit
    def test_target_and_zone_both_at_origin_radius_zero(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        zone = {"name": "origin", "type": "perimeter",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 0.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        result = tc._find_zone((0.0, 0.0))
        assert result is not None  # dist=0.0 <= 0.0


# ===================================================================
# Edge Case Tests — De-escalation Edge Cases
# ===================================================================


class TestDeescalationEdgeCases:
    @pytest.mark.unit
    def test_deescalation_to_none_record_persists(self):
        """After de-escalating to 'none', the record should remain in
        _records (but excluded from get_active_threats)."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(100.0, 100.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        with tc._lock:
            tc._records["t1"] = ThreatRecord(
                target_id="t1", threat_level="unknown"
            )
            tc._zone_exit_times["t1"] = time.monotonic() - 31.0

        tc._classify_tick()

        records = tc.get_records()
        assert "t1" in records
        assert records["t1"].threat_level == "none"
        assert tc.get_active_threats() == []

    @pytest.mark.unit
    def test_deescalation_to_none_does_not_go_below_none(self):
        """A target already at 'none' should not de-escalate further."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(100.0, 100.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        with tc._lock:
            tc._records["t1"] = ThreatRecord(
                target_id="t1", threat_level="none"
            )
            tc._zone_exit_times["t1"] = time.monotonic() - 31.0

        bus.published.clear()
        tc._classify_tick()

        # Level should stay at none
        assert tc.get_records()["t1"].threat_level == "none"
        # No de-escalation event published
        deesc = [e for e in bus.published if e[0] == "threat_deescalation"]
        assert len(deesc) == 0

    @pytest.mark.unit
    def test_multiple_targets_deescalate_simultaneously(self):
        """Multiple targets de-escalating in the same tick."""
        bus = MockEventBus()
        t1 = MockTrackedTarget("t1", alliance="hostile", position=(100.0, 100.0))
        t2 = MockTrackedTarget("t2", alliance="hostile", position=(200.0, 200.0))
        t3 = MockTrackedTarget("t3", alliance="hostile", position=(300.0, 300.0))
        tracker = MockTargetTracker([t1, t2, t3])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        now = time.monotonic()
        with tc._lock:
            tc._records["t1"] = ThreatRecord(target_id="t1", threat_level="hostile")
            tc._records["t2"] = ThreatRecord(target_id="t2", threat_level="suspicious")
            tc._records["t3"] = ThreatRecord(target_id="t3", threat_level="unknown")
            tc._zone_exit_times["t1"] = now - 31.0
            tc._zone_exit_times["t2"] = now - 31.0
            tc._zone_exit_times["t3"] = now - 31.0

        tc._classify_tick()

        records = tc.get_records()
        assert records["t1"].threat_level == "suspicious"
        assert records["t2"].threat_level == "unknown"
        assert records["t3"].threat_level == "none"

    @pytest.mark.unit
    def test_target_leaves_zone_reenters_before_deescalation(self):
        """Target leaves zone, then re-enters before 30s de-escalation
        window. De-escalation timer should be cleared on re-entry."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        zone = _perimeter_zone()
        tc = ThreatClassifier(bus, tracker, zones=[zone])

        # Enter zone, escalate to unknown
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "unknown"

        # Leave zone
        target.position = (100.0, 100.0)
        tc._classify_tick()
        assert "t1" in tc._zone_exit_times

        # Re-enter zone before 30s
        target.position = (5.0, 5.0)
        tc._classify_tick()

        # Exit time should be cleared
        assert "t1" not in tc._zone_exit_times
        # Level should still be unknown (not de-escalated)
        assert tc.get_records()["t1"].threat_level == "unknown"

    @pytest.mark.unit
    def test_target_never_in_zone_has_no_exit_time(self):
        """Target that was never in any zone should have exit_time 0
        and not de-escalate (since the condition exit_time > 0 fails)."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(100.0, 100.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        # Manually give it a threat level without ever entering a zone
        with tc._lock:
            tc._records["t1"] = ThreatRecord(
                target_id="t1", threat_level="unknown"
            )

        # No exit time set — should not de-escalate
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "unknown"


# ===================================================================
# Edge Case Tests — Battery Boundary
# ===================================================================


class TestDispatcherBatteryBoundary:
    @pytest.mark.unit
    def test_battery_at_exactly_min_is_dispatched(self):
        """Battery at exactly MIN_BATTERY (0.20) should be dispatched
        because the check is >= not >."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=0.20, status="active", name="Min Battery"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches == {"h1": "f1"}

    @pytest.mark.unit
    def test_battery_just_below_min_is_skipped(self):
        """Battery at 0.199 (below MIN_BATTERY) should be skipped."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=0.199, status="active", name="Low Battery"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches == {}


# ===================================================================
# Edge Case Tests — Dispatch with Missing Engine Target
# ===================================================================


class TestDispatchEngineTargetMissing:
    @pytest.mark.unit
    def test_dispatch_proceeds_when_engine_target_is_none(self):
        """If the friendly unit exists in tracker but not in the
        simulation engine, dispatch should still proceed (event
        published, MQTT sent, speech generated)."""
        bus = MockEventBus()

        class MockEngine:
            def get_target(self, target_id):
                return None  # target not found in engine

        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Phantom Unit"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker, simulation_engine=MockEngine())

        ad._try_dispatch("h1", "hostile")

        # Dispatch should still be recorded
        assert ad.active_dispatches == {"h1": "f1"}
        dispatch_events = [e for e in bus.published if e[0] == "amy_dispatch"]
        assert len(dispatch_events) == 1

    @pytest.mark.unit
    def test_dispatch_sets_waypoints_on_engine_target(self):
        """When engine.get_target returns a valid sim target, its
        waypoints should be set to the threat position."""
        bus = MockEventBus()

        class MockSimTarget:
            def __init__(self):
                self.waypoints = []
                self._waypoint_index = 99
                self.status = "idle"

        class MockEngine:
            def __init__(self):
                self.sim_target = MockSimTarget()

            def get_target(self, target_id):
                return self.sim_target if target_id == "f1" else None

        engine = MockEngine()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker, simulation_engine=engine)

        ad._try_dispatch("h1", "hostile")

        assert engine.sim_target.waypoints == [(10.0, 10.0)]
        assert engine.sim_target._waypoint_index == 0
        assert engine.sim_target.status == "active"


# ===================================================================
# Edge Case Tests — Unknown Alliance Targets
# ===================================================================


class TestUnknownAllianceTargets:
    @pytest.mark.unit
    def test_unknown_alliance_is_classified(self):
        """Targets with alliance='unknown' should be classified
        (not skipped like friendlies)."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="unknown", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        assert "t1" in tc.get_records()
        assert tc.get_records()["t1"].threat_level == "unknown"

    @pytest.mark.unit
    def test_hostile_alliance_is_classified(self):
        """Targets with alliance='hostile' should be classified."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        assert "t1" in tc.get_records()


# ===================================================================
# Edge Case Tests — Thread Start/Stop Lifecycle
# ===================================================================


class TestThreatClassifierStartStop:
    @pytest.mark.unit
    def test_start_sets_running_flag(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)

        tc.start()
        assert tc._running is True
        assert tc._thread is not None
        assert tc._thread.is_alive()
        tc.stop()

    @pytest.mark.unit
    def test_stop_clears_running_and_thread(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)

        tc.start()
        tc.stop()
        assert tc._running is False
        assert tc._thread is None

    @pytest.mark.unit
    def test_double_start_is_noop(self):
        """Calling start() twice should not create a second thread."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)

        tc.start()
        thread1 = tc._thread
        tc.start()
        thread2 = tc._thread
        assert thread1 is thread2
        tc.stop()

    @pytest.mark.unit
    def test_double_stop_is_safe(self):
        """Calling stop() twice should not raise."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)

        tc.start()
        tc.stop()
        tc.stop()  # second call should be safe
        assert tc._running is False
        assert tc._thread is None

    @pytest.mark.unit
    def test_stop_without_start_is_safe(self):
        """Calling stop() without ever starting should not raise."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)

        tc.stop()
        assert tc._running is False


class TestAutoDispatcherStartStop:
    @pytest.mark.unit
    def test_start_subscribes_to_event_bus(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker)

        ad.start()
        assert ad._running is True
        assert ad._sub is not None
        assert ad._thread is not None
        ad.stop()

    @pytest.mark.unit
    def test_stop_unsubscribes_and_clears(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker)

        ad.start()
        ad.stop()
        assert ad._running is False
        assert ad._sub is None
        assert ad._thread is None

    @pytest.mark.unit
    def test_double_start_is_noop(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker)

        ad.start()
        thread1 = ad._thread
        ad.start()
        assert ad._thread is thread1
        ad.stop()

    @pytest.mark.unit
    def test_double_stop_is_safe(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker)

        ad.start()
        ad.stop()
        ad.stop()
        assert ad._running is False
        assert ad._sub is None

    @pytest.mark.unit
    def test_stop_without_start_is_safe(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker)

        ad.stop()
        assert ad._running is False


# ===================================================================
# Edge Case Tests — Zone Violation Events
# ===================================================================


class TestZoneViolationEvents:
    @pytest.mark.unit
    def test_zone_entry_publishes_zone_violation(self):
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()

        violations = [e for e in bus.published if e[0] == "zone_violation"]
        assert len(violations) == 1
        data = violations[0][1]
        assert data["target_id"] == "t1"
        assert data["zone_name"] == "front_yard"
        assert data["zone_type"] == "perimeter"

    @pytest.mark.unit
    def test_staying_in_same_zone_no_duplicate_violation(self):
        """Target staying in the same zone should not produce
        repeated zone_violation events."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        tc._classify_tick()
        tc._classify_tick()

        violations = [e for e in bus.published if e[0] == "zone_violation"]
        assert len(violations) == 1

    @pytest.mark.unit
    def test_moving_between_zones_produces_new_violation(self):
        """Target moving from one zone to another should produce a new
        zone_violation event for the new zone."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        zone_a = _perimeter_zone(x=5.0, z=5.0, radius=3.0)
        zone_b = {"name": "zone_b", "type": "perimeter",
                  "position": {"x": 20.0, "z": 20.0},
                  "properties": {"radius": 3.0}}
        tc = ThreatClassifier(bus, tracker, zones=[zone_a, zone_b])

        # Enter zone_a
        tc._classify_tick()
        violations_1 = [e for e in bus.published if e[0] == "zone_violation"]
        assert len(violations_1) == 1
        assert violations_1[0][1]["zone_name"] == "front_yard"

        # Move to zone_b
        target.position = (20.0, 20.0)
        tc._classify_tick()
        violations_2 = [e for e in bus.published if e[0] == "zone_violation"]
        assert len(violations_2) == 2
        assert violations_2[1][1]["zone_name"] == "zone_b"


# ===================================================================
# Edge Case Tests — Classify Tick Exception Safety
# ===================================================================


class TestClassifyTickExceptionSafety:
    @pytest.mark.unit
    def test_exception_in_classify_tick_does_not_leak_lock(self):
        """If _classify_tick raises, the lock should still be released
        (guaranteed by 'with' statement)."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        # Monkey-patch tracker to raise
        def exploding_get_all():
            raise RuntimeError("boom")

        tracker.get_all = exploding_get_all

        # _classify_tick should raise but lock should not be held
        with pytest.raises(RuntimeError, match="boom"):
            tc._classify_tick()

        # Lock should be acquirable (not held)
        assert tc._lock.acquire(timeout=0.1)
        tc._lock.release()

    @pytest.mark.unit
    def test_exception_mid_tick_does_not_corrupt_records(self):
        """If an exception occurs partway through processing targets,
        records that were already processed should be intact."""
        bus = MockEventBus()
        t1 = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        # t2 has a position that will cause an exception
        t2 = MockTrackedTarget("t2", alliance="hostile", position=None)
        tracker = MockTargetTracker([t1, t2])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        # The tick will crash when it tries to unpack t2.position
        with pytest.raises(TypeError):
            tc._classify_tick()

        # t1 should have been processed before the crash
        # (depends on iteration order, but records should not be corrupt)
        # Lock should not be held
        assert tc._lock.acquire(timeout=0.1)
        tc._lock.release()

    @pytest.mark.unit
    def test_classify_loop_catches_exceptions(self):
        """The _classify_loop catches Exception, so one bad tick
        should not kill the thread."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        call_count = 0
        original_tick = tc._classify_tick

        def counting_tick():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            # Stop after second tick
            tc._running = False

        tc._classify_tick = counting_tick
        tc.TICK_INTERVAL = 0.01  # speed up for test

        tc._running = True
        tc._classify_loop()

        # Should have called tick at least twice (survived the exception)
        assert call_count >= 2


# ===================================================================
# Edge Case Tests — Stale Record Pruning
# ===================================================================


class TestStaleRecordPruning:
    @pytest.mark.unit
    def test_multiple_targets_pruned_simultaneously(self):
        bus = MockEventBus()
        t1 = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        t2 = MockTrackedTarget("t2", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([t1, t2])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        assert len(tc.get_records()) == 2

        # Remove both
        tracker._targets.clear()
        tc._classify_tick()
        assert len(tc.get_records()) == 0

    @pytest.mark.unit
    def test_prune_one_keep_another(self):
        bus = MockEventBus()
        t1 = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        t2 = MockTrackedTarget("t2", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([t1, t2])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        assert len(tc.get_records()) == 2

        # Remove only t1
        tracker._targets = [t2]
        tc._classify_tick()
        records = tc.get_records()
        assert "t1" not in records
        assert "t2" in records


# ===================================================================
# Edge Case Tests — Dispatch Speech Content
# ===================================================================


class TestDispatchSpeechContent:
    @pytest.mark.unit
    def test_suspicious_threat_level_in_speech(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit Alpha"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "suspicious")

        speech_events = [e for e in bus.published if e[0] == "auto_dispatch_speech"]
        assert len(speech_events) == 1
        text = speech_events[0][1]["text"]
        assert "Unit Alpha" in text
        assert "intercept" in text.lower()
        assert "bearing" in text.lower()

    @pytest.mark.unit
    def test_dispatch_reason_matches_threat_level(self):
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "suspicious")

        dispatch_events = [e for e in bus.published if e[0] == "amy_dispatch"]
        assert dispatch_events[0][1]["reason"] == "intercept_suspicious"


# ===================================================================
# Edge Case Tests — Clear Dispatch Allows Re-dispatch
# ===================================================================


class TestClearDispatchRedispatch:
    @pytest.mark.unit
    def test_clear_dispatch_allows_re_dispatch_to_same_threat(self):
        """After clearing a dispatch, a new dispatch for the same
        threat should be allowed."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        f1 = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit 1"
        )
        tracker = MockTargetTracker([hostile, f1])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches == {"h1": "f1"}

        ad.clear_dispatch("h1")
        assert ad.active_dispatches == {}

        bus.published.clear()
        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches == {"h1": "f1"}
        dispatch_events = [e for e in bus.published if e[0] == "amy_dispatch"]
        assert len(dispatch_events) == 1


# ===================================================================
# Edge Case Tests — Dispatch Distance Calculation
# ===================================================================


class TestDispatchDistanceCalculation:
    @pytest.mark.unit
    def test_dispatch_to_same_position(self):
        """Friendly and threat at the same position — distance 0."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(5.0, 5.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(5.0, 5.0),
            battery=1.0, status="active", name="Overlapping Unit"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")

        speech_events = [e for e in bus.published if e[0] == "auto_dispatch_speech"]
        assert "0 meters" in speech_events[0][1]["text"]

    @pytest.mark.unit
    def test_dispatch_distance_accuracy(self):
        """Verify the distance in speech matches expected calculation."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(3.0, 4.0))
        friendly = MockTrackedTarget(
            "f1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Unit"
        )
        tracker = MockTargetTracker([hostile, friendly])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")

        speech_events = [e for e in bus.published if e[0] == "auto_dispatch_speech"]
        # distance = hypot(3, 4) = 5.0
        assert "5 meters" in speech_events[0][1]["text"]


# ===================================================================
# Edge Case Tests — Escalation from Restricted Already at Higher Level
# ===================================================================


class TestEscalationFromHigherLevel:
    @pytest.mark.unit
    def test_already_hostile_entering_restricted_stays_hostile(self):
        """A hostile target entering a restricted zone should stay hostile
        (not be downgraded to suspicious)."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(1.0, 1.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_restricted_zone()])

        # Manually set to hostile
        with tc._lock:
            tc._records["t1"] = ThreatRecord(
                target_id="t1", threat_level="hostile"
            )

        bus.published.clear()
        tc._classify_tick()

        # Should stay hostile, not downgrade to suspicious
        assert tc.get_records()["t1"].threat_level == "hostile"
        # No escalation/de-escalation events
        level_events = [e for e in bus.published
                       if e[0] in ("threat_escalation", "threat_deescalation")]
        assert len(level_events) == 0

    @pytest.mark.unit
    def test_suspicious_in_perimeter_stays_suspicious(self):
        """A suspicious target in a perimeter zone should not be
        downgraded to unknown."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        with tc._lock:
            tc._records["t1"] = ThreatRecord(
                target_id="t1", threat_level="suspicious"
            )

        bus.published.clear()
        tc._classify_tick()

        # Should stay suspicious (perimeter only escalates from none to unknown)
        assert tc.get_records()["t1"].threat_level == "suspicious"

    @pytest.mark.unit
    def test_none_level_outside_all_zones_stays_none(self):
        """Target at none level outside zones should not generate events."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(100.0, 100.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()

        records = tc.get_records()
        assert records["t1"].threat_level == "none"
        # No escalation events
        esc = [e for e in bus.published if e[0] in ("threat_escalation", "threat_deescalation")]
        assert len(esc) == 0


# ===================================================================
# Prior Hostile Behavioral Memory Tests
# ===================================================================


class TestPriorHostileMemory:
    @pytest.mark.unit
    def test_linger_sets_prior_hostile_flag(self):
        """When a target escalates to hostile via lingering, prior_hostile
        should be set to True."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        assert tc.get_records()["t1"].prior_hostile is False

        with tc._lock:
            tc._records["t1"].zone_enter_time = time.monotonic() - 31.0

        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "hostile"
        assert tc.get_records()["t1"].prior_hostile is True

    @pytest.mark.unit
    def test_manual_override_to_hostile_sets_prior_hostile(self):
        """Manual escalation to hostile should set prior_hostile."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        tc.set_threat_level("t1", "hostile")
        assert tc.get_records()["t1"].prior_hostile is True

    @pytest.mark.unit
    def test_manual_override_to_suspicious_does_not_set_prior_hostile(self):
        """Manual escalation to suspicious should NOT set prior_hostile."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        tc.set_threat_level("t1", "suspicious")
        assert tc.get_records()["t1"].prior_hostile is False

    @pytest.mark.unit
    def test_prior_hostile_reentry_skips_unknown_goes_to_suspicious(self):
        """A target with prior_hostile=True re-entering a perimeter zone
        should skip 'unknown' and go directly to 'suspicious'."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        # Escalate to hostile via linger
        tc._classify_tick()
        with tc._lock:
            tc._records["t1"].zone_enter_time = time.monotonic() - 31.0
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "hostile"
        assert tc.get_records()["t1"].prior_hostile is True

        # Move outside, de-escalate fully
        target.position = (100.0, 100.0)
        tc._classify_tick()
        for _ in range(3):
            tc._zone_exit_times["t1"] = time.monotonic() - 31.0
            tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "none"
        # prior_hostile should still be True
        assert tc.get_records()["t1"].prior_hostile is True

        # Re-enter perimeter zone
        bus.published.clear()
        target.position = (5.0, 5.0)
        tc._classify_tick()

        # Should skip unknown, go straight to suspicious
        assert tc.get_records()["t1"].threat_level == "suspicious"
        esc_events = [e for e in bus.published if e[0] == "threat_escalation"]
        assert len(esc_events) == 1
        assert esc_events[0][1]["old_level"] == "none"
        assert esc_events[0][1]["new_level"] == "suspicious"

    @pytest.mark.unit
    def test_non_prior_hostile_enters_perimeter_at_unknown(self):
        """A fresh target without prior_hostile should enter at 'unknown',
        confirming the default behavior is unchanged."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(5.0, 5.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_perimeter_zone()])

        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "unknown"
        assert tc.get_records()["t1"].prior_hostile is False

    @pytest.mark.unit
    def test_prior_hostile_entering_restricted_still_goes_to_suspicious(self):
        """Prior-hostile entering a restricted zone should be suspicious
        (same as non-prior-hostile — restricted already skips to suspicious)."""
        bus = MockEventBus()
        target = MockTrackedTarget("t1", alliance="hostile", position=(1.0, 1.0))
        tracker = MockTargetTracker([target])
        tc = ThreatClassifier(bus, tracker, zones=[_restricted_zone()])

        # Pre-mark as prior hostile
        tc._classify_tick()
        with tc._lock:
            tc._records["t1"].prior_hostile = True
            tc._records["t1"].threat_level = "none"
            tc._records["t1"].in_zone = ""

        bus.published.clear()
        tc._classify_tick()
        assert tc.get_records()["t1"].threat_level == "suspicious"


# ===================================================================
# Turret Dispatch Exclusion Tests
# ===================================================================


class TestTurretDispatchExclusion:
    @pytest.mark.unit
    def test_turrets_are_never_dispatched(self):
        """Turrets (speed=0, stationary) should never be dispatched
        even if they are the nearest friendly unit."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(5.0, 5.0))
        turret = MockTrackedTarget(
            "t1", alliance="friendly", position=(3.0, 3.0),
            battery=1.0, status="active", name="Turret Alpha"
        )
        turret.asset_type = "turret"
        tracker = MockTargetTracker([hostile, turret])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches == {}

    @pytest.mark.unit
    def test_turret_skipped_rover_dispatched(self):
        """When a turret is nearest but a rover is available,
        the rover should be dispatched."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(5.0, 5.0))
        turret = MockTrackedTarget(
            "t1", alliance="friendly", position=(3.0, 3.0),
            battery=1.0, status="active", name="Turret Alpha"
        )
        turret.asset_type = "turret"
        rover = MockTrackedTarget(
            "r1", alliance="friendly", position=(20.0, 20.0),
            battery=1.0, status="active", name="Rover Bravo"
        )
        rover.asset_type = "rover"
        tracker = MockTargetTracker([hostile, turret, rover])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches == {"h1": "r1"}

    @pytest.mark.unit
    def test_drone_is_dispatched(self):
        """Drones should be eligible for dispatch."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(5.0, 5.0))
        drone = MockTrackedTarget(
            "d1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Drone Charlie"
        )
        drone.asset_type = "drone"
        tracker = MockTargetTracker([hostile, drone])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches == {"h1": "d1"}

    @pytest.mark.unit
    def test_person_friendly_not_dispatched(self):
        """Friendly persons should not be dispatched — they are not
        in the MOBILE_TYPES set."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(5.0, 5.0))
        person = MockTrackedTarget(
            "p1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Guard"
        )
        person.asset_type = "person"
        tracker = MockTargetTracker([hostile, person])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert ad.active_dispatches == {}


# ===================================================================
# Stale Dispatch Cleanup Tests
# ===================================================================


class TestStaleDispatchCleanup:
    @pytest.mark.unit
    def test_dispatch_cleared_when_threat_disappears(self):
        """Dispatch should be cleaned up when the threat is no longer
        in the target tracker."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        rover = MockTrackedTarget(
            "r1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Rover"
        )
        rover.asset_type = "rover"
        tracker = MockTargetTracker([hostile, rover])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert "h1" in ad.active_dispatches

        # Remove threat from tracker
        tracker._targets = [rover]
        ad._cleanup_stale_dispatches()
        assert "h1" not in ad.active_dispatches

    @pytest.mark.unit
    def test_dispatch_cleared_when_unit_destroyed(self):
        """Dispatch should be cleaned up when the dispatched unit
        is destroyed."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        rover = MockTrackedTarget(
            "r1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Rover"
        )
        rover.asset_type = "rover"
        tracker = MockTargetTracker([hostile, rover])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert "h1" in ad.active_dispatches

        # Unit gets destroyed
        rover.status = "destroyed"
        ad._cleanup_stale_dispatches()
        assert "h1" not in ad.active_dispatches

    @pytest.mark.unit
    def test_dispatch_cleared_when_threat_neutralized(self):
        """Dispatch should be cleaned up when the threat is neutralized."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        rover = MockTrackedTarget(
            "r1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Rover"
        )
        rover.asset_type = "rover"
        tracker = MockTargetTracker([hostile, rover])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        hostile.status = "neutralized"
        ad._cleanup_stale_dispatches()
        assert "h1" not in ad.active_dispatches

    @pytest.mark.unit
    def test_dispatch_cleared_when_threat_escaped(self):
        """Dispatch should be cleaned up when the threat escapes."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        rover = MockTrackedTarget(
            "r1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Rover"
        )
        rover.asset_type = "rover"
        tracker = MockTargetTracker([hostile, rover])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        hostile.status = "escaped"
        ad._cleanup_stale_dispatches()
        assert "h1" not in ad.active_dispatches

    @pytest.mark.unit
    def test_active_dispatch_not_cleared(self):
        """Dispatch with active threat and unit should NOT be cleaned up."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        rover = MockTrackedTarget(
            "r1", alliance="friendly", position=(5.0, 5.0),
            battery=0.8, status="active", name="Rover"
        )
        rover.asset_type = "rover"
        tracker = MockTargetTracker([hostile, rover])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        ad._cleanup_stale_dispatches()
        assert "h1" in ad.active_dispatches

    @pytest.mark.unit
    def test_deescalation_to_none_clears_dispatch(self):
        """When the dispatcher receives a threat_deescalation event where
        new_level is 'none', it should clear the dispatch for that target."""
        bus = MockEventBus()
        hostile = MockTrackedTarget("h1", alliance="hostile", position=(10.0, 10.0))
        rover = MockTrackedTarget(
            "r1", alliance="friendly", position=(0.0, 0.0),
            battery=1.0, status="active", name="Rover"
        )
        rover.asset_type = "rover"
        tracker = MockTargetTracker([hostile, rover])
        ad = AutoDispatcher(bus, tracker)

        ad._try_dispatch("h1", "hostile")
        assert "h1" in ad.active_dispatches

        # Simulate deescalation to none (the _dispatch_loop would handle this)
        ad.clear_dispatch("h1")
        assert "h1" not in ad.active_dispatches
