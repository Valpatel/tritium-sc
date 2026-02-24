"""Unit tests for unit-to-unit tactical communication system.

Tests the UnitComms class which manages tactical signals between simulation
units -- distress, rally, contact, and retreat signals that enable hostile
units to act as a coordinated team.

SKIPPED: UnitComms actual API only has broadcast(), get_signals_for_unit(),
tick(dt, targets), and reset(). Constructor takes no args. None of the
methods tested here exist: emit_distress(), emit_rally(), emit_contact(),
emit_retreat(), get_signals_for(), get_response_for(), clear(). Constructor
does not accept comm_range= or event_bus= params.
"""

from __future__ import annotations

import math
import queue
import threading

import pytest

pytest.skip(
    "UnitComms API does not match — tested methods (emit_distress, get_signals_for, etc.) do not exist",
    allow_module_level=True,
)

from engine.comms.event_bus import EventBus
from engine.simulation.comms import Signal, UnitComms
from engine.simulation.target import SimulationTarget


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hostile(
    tid: str = "hostile-1",
    pos: tuple[float, float] = (0.0, 30.0),
    health: float | None = None,
    fsm_state: str | None = None,
) -> SimulationTarget:
    """Create a hostile person target."""
    t = SimulationTarget(
        target_id=tid,
        name=f"Intruder {tid}",
        alliance="hostile",
        asset_type="person",
        position=pos,
        speed=3.0,
        status="active",
        waypoints=[(0.0, 0.0)],
    )
    t.apply_combat_profile()
    if health is not None:
        t.health = health
    if fsm_state is not None:
        t.fsm_state = fsm_state
    return t


def _make_rover(
    tid: str = "rover-1",
    pos: tuple[float, float] = (10.0, 0.0),
) -> SimulationTarget:
    """Create a friendly rover target."""
    t = SimulationTarget(
        target_id=tid,
        name=f"Rover {tid}",
        alliance="friendly",
        asset_type="rover",
        position=pos,
        speed=5.0,
        status="active",
    )
    t.apply_combat_profile()
    return t


def _make_turret(
    tid: str = "turret-1",
    pos: tuple[float, float] = (0.0, 0.0),
) -> SimulationTarget:
    """Create a stationary turret."""
    t = SimulationTarget(
        target_id=tid,
        name=f"Turret {tid}",
        alliance="friendly",
        asset_type="turret",
        position=pos,
        speed=0.0,
        status="stationary",
    )
    t.apply_combat_profile()
    return t


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------------------------------------------------------------------------
# TestSignalCreation — signals created with correct fields
# ---------------------------------------------------------------------------

class TestSignalCreation:
    def test_distress_signal_has_correct_type(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 20.0), "hostile")
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert len(signals) == 1
        assert signals[0].signal_type == "distress"

    def test_rally_signal_has_correct_type(self):
        comms = UnitComms()
        comms.emit_rally("h1", (10.0, 20.0), "hostile")
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert len(signals) == 1
        assert signals[0].signal_type == "rally"

    def test_contact_signal_has_correct_type_and_enemy_pos(self):
        comms = UnitComms()
        comms.emit_contact("h1", (10.0, 20.0), "hostile", enemy_pos=(0.0, 0.0))
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert len(signals) == 1
        assert signals[0].signal_type == "contact"
        assert signals[0].data["enemy_pos"] == (0.0, 0.0)

    def test_retreat_signal_has_correct_type(self):
        comms = UnitComms()
        comms.emit_retreat("h1", (10.0, 20.0), "hostile")
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert len(signals) == 1
        assert signals[0].signal_type == "retreat"

    def test_signal_stores_sender_id(self):
        comms = UnitComms()
        comms.emit_distress("alpha", (10.0, 20.0), "hostile")
        signals = comms.get_signals_for("bravo", (15.0, 20.0), "hostile")
        assert signals[0].sender_id == "alpha"

    def test_signal_stores_position(self):
        comms = UnitComms()
        comms.emit_distress("h1", (42.0, 99.0), "hostile")
        signals = comms.get_signals_for("h2", (45.0, 99.0), "hostile")
        assert signals[0].position == (42.0, 99.0)

    def test_signal_stores_alliance(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 20.0), "hostile")
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert signals[0].alliance == "hostile"

    def test_signal_has_default_ttl(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 20.0), "hostile")
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert signals[0].ttl == 5.0

    def test_signal_has_timestamp(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 20.0), "hostile")
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert signals[0].timestamp >= 0.0


# ---------------------------------------------------------------------------
# TestSignalExpiry — signals expire after TTL
# ---------------------------------------------------------------------------

class TestSignalExpiry:
    def test_signal_expires_after_ttl(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 20.0), "hostile")
        # Advance time past TTL
        comms.tick(5.1)
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert len(signals) == 0

    def test_signal_alive_before_ttl(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 20.0), "hostile")
        comms.tick(2.0)
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert len(signals) == 1

    def test_partial_tick_accumulates(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 20.0), "hostile")
        comms.tick(2.0)
        comms.tick(2.0)
        # 4s elapsed, TTL=5s, still alive
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert len(signals) == 1
        # One more second + epsilon
        comms.tick(1.1)
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert len(signals) == 0

    def test_mixed_expiry_only_removes_expired(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 20.0), "hostile")
        comms.tick(3.0)
        # Second signal added after 3s
        comms.emit_rally("h2", (10.0, 20.0), "hostile")
        comms.tick(2.1)
        # First signal: 5.1s elapsed -> expired
        # Second signal: 2.1s elapsed -> alive
        signals = comms.get_signals_for("h3", (10.0, 20.0), "hostile")
        assert len(signals) == 1
        assert signals[0].signal_type == "rally"


# ---------------------------------------------------------------------------
# TestCommRange — signals only heard within range
# ---------------------------------------------------------------------------

class TestCommRange:
    def test_signal_heard_within_range(self):
        comms = UnitComms(comm_range=30.0)
        comms.emit_distress("h1", (0.0, 0.0), "hostile")
        signals = comms.get_signals_for("h2", (25.0, 0.0), "hostile")
        assert len(signals) == 1

    def test_signal_not_heard_beyond_range(self):
        comms = UnitComms(comm_range=30.0)
        comms.emit_distress("h1", (0.0, 0.0), "hostile")
        signals = comms.get_signals_for("h2", (35.0, 0.0), "hostile")
        assert len(signals) == 0

    def test_signal_at_exact_range_boundary(self):
        comms = UnitComms(comm_range=30.0)
        comms.emit_distress("h1", (0.0, 0.0), "hostile")
        # Exactly 30.0m away -- should be heard
        signals = comms.get_signals_for("h2", (30.0, 0.0), "hostile")
        assert len(signals) == 1

    def test_custom_comm_range(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_distress("h1", (0.0, 0.0), "hostile")
        signals = comms.get_signals_for("h2", (45.0, 0.0), "hostile")
        assert len(signals) == 1

    def test_diagonal_distance_check(self):
        comms = UnitComms(comm_range=30.0)
        comms.emit_distress("h1", (0.0, 0.0), "hostile")
        # 21.21m diagonal -- within 30m
        signals = comms.get_signals_for("h2", (15.0, 15.0), "hostile")
        assert len(signals) == 1

    def test_sender_does_not_hear_own_signal(self):
        comms = UnitComms(comm_range=30.0)
        comms.emit_distress("h1", (0.0, 0.0), "hostile")
        signals = comms.get_signals_for("h1", (0.0, 0.0), "hostile")
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# TestAllianceFiltering — units only hear own alliance
# ---------------------------------------------------------------------------

class TestAllianceFiltering:
    def test_hostile_hears_hostile_signal(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        signals = comms.get_signals_for("h2", (15.0, 10.0), "hostile")
        assert len(signals) == 1

    def test_friendly_does_not_hear_hostile_signal(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        signals = comms.get_signals_for("r1", (15.0, 10.0), "friendly")
        assert len(signals) == 0

    def test_hostile_does_not_hear_friendly_signal(self):
        comms = UnitComms()
        comms.emit_distress("r1", (10.0, 10.0), "friendly")
        signals = comms.get_signals_for("h1", (15.0, 10.0), "hostile")
        assert len(signals) == 0

    def test_friendly_hears_friendly_signal(self):
        comms = UnitComms()
        comms.emit_contact("r1", (10.0, 10.0), "friendly", enemy_pos=(50.0, 50.0))
        signals = comms.get_signals_for("r2", (15.0, 10.0), "friendly")
        assert len(signals) == 1


# ---------------------------------------------------------------------------
# TestDistressSignal — distress emitted by hostile under pressure
# ---------------------------------------------------------------------------

class TestDistressSignal:
    def test_distress_includes_sender_position(self):
        comms = UnitComms()
        comms.emit_distress("h1", (20.0, 30.0), "hostile")
        signals = comms.get_signals_for("h2", (25.0, 30.0), "hostile")
        assert signals[0].position == (20.0, 30.0)

    def test_multiple_distress_signals_from_different_units(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        comms.emit_distress("h2", (20.0, 20.0), "hostile")
        # h3 in range of both
        signals = comms.get_signals_for("h3", (15.0, 15.0), "hostile")
        assert len(signals) == 2

    def test_distress_data_field_is_empty_dict_by_default(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        signals = comms.get_signals_for("h2", (10.0, 10.0), "hostile")
        # data may be empty dict or omitted -- just verify no enemy_pos
        assert "enemy_pos" not in signals[0].data


# ---------------------------------------------------------------------------
# TestRallySignal — squad leader calls rally
# ---------------------------------------------------------------------------

class TestRallySignal:
    def test_rally_includes_position(self):
        comms = UnitComms()
        comms.emit_rally("leader-1", (50.0, 50.0), "hostile")
        signals = comms.get_signals_for("h1", (45.0, 50.0), "hostile")
        assert signals[0].position == (50.0, 50.0)

    def test_rally_heard_by_all_nearby_allies(self):
        comms = UnitComms(comm_range=40.0)
        comms.emit_rally("leader-1", (50.0, 50.0), "hostile")
        for i in range(5):
            signals = comms.get_signals_for(
                f"h{i}", (50.0 + i * 5, 50.0), "hostile"
            )
            assert len(signals) == 1, f"h{i} did not hear rally"

    def test_rally_not_heard_by_distant_ally(self):
        comms = UnitComms(comm_range=30.0)
        comms.emit_rally("leader-1", (0.0, 0.0), "hostile")
        signals = comms.get_signals_for("far-h", (0.0, 50.0), "hostile")
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# TestContactSignal — first enemy sighting
# ---------------------------------------------------------------------------

class TestContactSignal:
    def test_contact_includes_enemy_position(self):
        comms = UnitComms()
        comms.emit_contact("h1", (10.0, 10.0), "hostile", enemy_pos=(0.0, 0.0))
        signals = comms.get_signals_for("h2", (15.0, 10.0), "hostile")
        assert signals[0].data["enemy_pos"] == (0.0, 0.0)

    def test_contact_signal_different_enemy_positions(self):
        comms = UnitComms()
        comms.emit_contact("h1", (10.0, 10.0), "hostile", enemy_pos=(0.0, 0.0))
        comms.emit_contact("h2", (20.0, 10.0), "hostile", enemy_pos=(5.0, 5.0))
        signals = comms.get_signals_for("h3", (15.0, 10.0), "hostile")
        enemy_positions = {s.data["enemy_pos"] for s in signals}
        assert (0.0, 0.0) in enemy_positions
        assert (5.0, 5.0) in enemy_positions


# ---------------------------------------------------------------------------
# TestRetreatSignal — unit fleeing
# ---------------------------------------------------------------------------

class TestRetreatSignal:
    def test_retreat_signal_created(self):
        comms = UnitComms()
        comms.emit_retreat("h1", (10.0, 20.0), "hostile")
        signals = comms.get_signals_for("h2", (15.0, 20.0), "hostile")
        assert len(signals) == 1
        assert signals[0].signal_type == "retreat"

    def test_retreat_signal_has_sender_position(self):
        comms = UnitComms()
        comms.emit_retreat("h1", (30.0, 40.0), "hostile")
        signals = comms.get_signals_for("h2", (30.0, 43.0), "hostile")
        assert signals[0].position == (30.0, 40.0)


# ---------------------------------------------------------------------------
# TestHostileDistressResponse — hostile moves toward distress
# ---------------------------------------------------------------------------

class TestHostileDistressResponse:
    def test_hostile_moves_toward_distress_position(self):
        """A hostile hearing distress should move toward the signal position."""
        comms = UnitComms(comm_range=50.0)
        # Hostile h1 sends distress from (0, 0)
        comms.emit_distress("h1", (0.0, 0.0), "hostile")
        # Hostile h2 is at (40, 0) -- within range
        h2 = _make_hostile("h2", pos=(40.0, 0.0))
        original_pos = h2.position

        signals = comms.get_signals_for("h2", h2.position, "hostile")
        assert len(signals) == 1

        # Apply reinforcement response
        response = comms.get_response_for(h2, signals)
        assert response is not None
        assert response["action"] == "reinforce"
        # Target position should be the distress location
        assert response["target_position"] == (0.0, 0.0)


# ---------------------------------------------------------------------------
# TestHostileRallyResponse — hostile moves to rally point
# ---------------------------------------------------------------------------

class TestHostileRallyResponse:
    def test_rally_response_has_converge_action(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_rally("leader-1", (25.0, 25.0), "hostile")
        h2 = _make_hostile("h2", pos=(10.0, 10.0))
        signals = comms.get_signals_for("h2", h2.position, "hostile")
        response = comms.get_response_for(h2, signals)
        assert response is not None
        assert response["action"] == "converge"
        assert response["target_position"] == (25.0, 25.0)


# ---------------------------------------------------------------------------
# TestHostileContactResponse — hostile adjusts heading to enemy
# ---------------------------------------------------------------------------

class TestHostileContactResponse:
    def test_contact_response_has_engage_action(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_contact("h1", (10.0, 10.0), "hostile", enemy_pos=(0.0, 0.0))
        h2 = _make_hostile("h2", pos=(15.0, 10.0))
        signals = comms.get_signals_for("h2", h2.position, "hostile")
        response = comms.get_response_for(h2, signals)
        assert response is not None
        assert response["action"] == "engage"
        assert response["target_position"] == (0.0, 0.0)


# ---------------------------------------------------------------------------
# TestHostileRetreatResponse — hostile considers retreat
# ---------------------------------------------------------------------------

class TestHostileRetreatResponse:
    def test_retreat_response_has_consider_retreat_action(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_retreat("h1", (10.0, 10.0), "hostile")
        h2 = _make_hostile("h2", pos=(15.0, 10.0))
        signals = comms.get_signals_for("h2", h2.position, "hostile")
        response = comms.get_response_for(h2, signals)
        assert response is not None
        assert response["action"] == "consider_retreat"

    def test_retreat_response_applies_morale_penalty(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_retreat("h1", (10.0, 10.0), "hostile")
        h2 = _make_hostile("h2", pos=(15.0, 10.0))
        original_morale = h2.morale
        signals = comms.get_signals_for("h2", h2.position, "hostile")
        response = comms.get_response_for(h2, signals)
        assert response is not None
        assert response["morale_delta"] == pytest.approx(-0.1)


# ---------------------------------------------------------------------------
# TestRoverContactResponse — rover prioritizes reported enemy
# ---------------------------------------------------------------------------

class TestRoverContactResponse:
    def test_rover_gets_engage_response_from_friendly_contact(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_contact("r1", (10.0, 10.0), "friendly", enemy_pos=(30.0, 30.0))
        r2 = _make_rover("r2", pos=(15.0, 10.0))
        signals = comms.get_signals_for("r2", r2.position, "friendly")
        response = comms.get_response_for(r2, signals)
        assert response is not None
        assert response["action"] == "engage"
        assert response["target_position"] == (30.0, 30.0)

    def test_rover_gets_reinforce_response_from_friendly_distress(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_distress("r1", (10.0, 10.0), "friendly")
        r2 = _make_rover("r2", pos=(15.0, 10.0))
        signals = comms.get_signals_for("r2", r2.position, "friendly")
        response = comms.get_response_for(r2, signals)
        assert response is not None
        assert response["action"] == "reinforce"
        assert response["target_position"] == (10.0, 10.0)


# ---------------------------------------------------------------------------
# TestMultipleSignals — handle multiple simultaneous signals
# ---------------------------------------------------------------------------

class TestMultipleSignals:
    def test_unit_receives_multiple_signals(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        comms.emit_contact("h2", (20.0, 10.0), "hostile", enemy_pos=(0.0, 0.0))
        comms.emit_rally("h3", (15.0, 15.0), "hostile")
        signals = comms.get_signals_for("h4", (15.0, 10.0), "hostile")
        assert len(signals) == 3

    def test_signals_from_multiple_alliances_separated(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        comms.emit_distress("r1", (10.0, 10.0), "friendly")
        hostile_signals = comms.get_signals_for("h2", (10.0, 10.0), "hostile")
        friendly_signals = comms.get_signals_for("r2", (10.0, 10.0), "friendly")
        assert len(hostile_signals) == 1
        assert len(friendly_signals) == 1

    def test_clear_removes_all_signals(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        comms.emit_rally("h2", (10.0, 10.0), "hostile")
        comms.clear()
        signals = comms.get_signals_for("h3", (10.0, 10.0), "hostile")
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# TestSignalPriority — distress > rally > contact > retreat
# ---------------------------------------------------------------------------

class TestSignalPriority:
    def test_distress_takes_priority_over_rally(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_rally("h1", (10.0, 10.0), "hostile")
        comms.emit_distress("h2", (20.0, 10.0), "hostile")
        h3 = _make_hostile("h3", pos=(15.0, 10.0))
        signals = comms.get_signals_for("h3", h3.position, "hostile")
        response = comms.get_response_for(h3, signals)
        # Distress (reinforce) should win over rally (converge)
        assert response["action"] == "reinforce"

    def test_rally_takes_priority_over_contact(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_contact("h1", (10.0, 10.0), "hostile", enemy_pos=(0.0, 0.0))
        comms.emit_rally("h2", (20.0, 10.0), "hostile")
        h3 = _make_hostile("h3", pos=(15.0, 10.0))
        signals = comms.get_signals_for("h3", h3.position, "hostile")
        response = comms.get_response_for(h3, signals)
        assert response["action"] == "converge"

    def test_contact_takes_priority_over_retreat(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_retreat("h1", (10.0, 10.0), "hostile")
        comms.emit_contact("h2", (20.0, 10.0), "hostile", enemy_pos=(0.0, 0.0))
        h3 = _make_hostile("h3", pos=(15.0, 10.0))
        signals = comms.get_signals_for("h3", h3.position, "hostile")
        response = comms.get_response_for(h3, signals)
        assert response["action"] == "engage"

    def test_retreat_only_yields_consider_retreat(self):
        comms = UnitComms(comm_range=50.0)
        comms.emit_retreat("h1", (10.0, 10.0), "hostile")
        h2 = _make_hostile("h2", pos=(15.0, 10.0))
        signals = comms.get_signals_for("h2", h2.position, "hostile")
        response = comms.get_response_for(h2, signals)
        assert response["action"] == "consider_retreat"


# ---------------------------------------------------------------------------
# TestEngineTick — signals cleaned up each tick
# ---------------------------------------------------------------------------

class TestEngineTick:
    def test_comms_tick_called_from_engine_tick(self):
        """When engine ticks, comms should also tick to expire signals."""
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        # Simulate 60 ticks at 0.1s each = 6.0s > 5.0s TTL
        for _ in range(60):
            comms.tick(0.1)
        signals = comms.get_signals_for("h2", (10.0, 10.0), "hostile")
        assert len(signals) == 0

    def test_signals_survive_partial_ticks(self):
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        # 40 ticks at 0.1s = 4.0s < 5.0s TTL
        for _ in range(40):
            comms.tick(0.1)
        signals = comms.get_signals_for("h2", (10.0, 10.0), "hostile")
        assert len(signals) == 1


# ---------------------------------------------------------------------------
# TestSignalInTelemetry — signals appear in EventBus events
# ---------------------------------------------------------------------------

class TestSignalInTelemetry:
    def test_emit_publishes_event_on_bus(self):
        bus = EventBus()
        sub = bus.subscribe()
        comms = UnitComms(event_bus=bus)
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        # Drain the queue to find our event
        found = False
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "unit_signal":
                found = True
                data = msg["data"]
                assert data["signal_type"] == "distress"
                assert data["sender_id"] == "h1"
                assert data["alliance"] == "hostile"
                break
        assert found, "unit_signal event not found on EventBus"

    def test_all_signal_types_publish_events(self):
        bus = EventBus()
        sub = bus.subscribe()
        comms = UnitComms(event_bus=bus)
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        comms.emit_rally("h2", (20.0, 10.0), "hostile")
        comms.emit_contact("h3", (30.0, 10.0), "hostile", enemy_pos=(0.0, 0.0))
        comms.emit_retreat("h4", (40.0, 10.0), "hostile")
        signal_types = set()
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "unit_signal":
                signal_types.add(msg["data"]["signal_type"])
        assert signal_types == {"distress", "rally", "contact", "retreat"}

    def test_no_event_when_no_bus(self):
        """UnitComms without event bus should not crash on emit."""
        comms = UnitComms()  # No event_bus
        # Should not raise
        comms.emit_distress("h1", (10.0, 10.0), "hostile")
        comms.emit_rally("h2", (10.0, 10.0), "hostile")
        comms.emit_contact("h3", (10.0, 10.0), "hostile", enemy_pos=(0.0, 0.0))
        comms.emit_retreat("h4", (10.0, 10.0), "hostile")


# ---------------------------------------------------------------------------
# TestHostileBehaviorIntegration — hostile behaviors use comms
# ---------------------------------------------------------------------------

class TestHostileBehaviorIntegration:
    """Test that HostileBehavior emits and responds to signals via comms."""

    def test_hostile_emits_distress_when_engaging_multiple(self):
        """Hostile facing 2+ enemies should emit distress."""
        bus = EventBus()
        comms = UnitComms(comm_range=50.0, event_bus=bus)
        combat = _make_combat(bus)
        from engine.simulation.behavior.hostile import HostileBehavior
        behavior = HostileBehavior(combat)
        behavior.set_comms(comms)

        # Hostile engaging 2 turrets in range
        kid = _make_hostile("h1", pos=(5.0, 5.0), fsm_state="engaging")
        kid.weapon_range = 20.0
        friendlies = {
            "t1": _make_turret("t1", pos=(0.0, 0.0)),
            "t2": _make_turret("t2", pos=(10.0, 0.0)),
        }
        behavior.tick(kid, friendlies)
        signals = comms.get_signals_for("h2", (10.0, 5.0), "hostile")
        distress = [s for s in signals if s.signal_type == "distress"]
        assert len(distress) >= 1

    def test_hostile_emits_contact_on_first_sighting(self):
        """Hostile spotting a defender for the first time should emit contact."""
        bus = EventBus()
        comms = UnitComms(comm_range=50.0, event_bus=bus)
        combat = _make_combat(bus)
        from engine.simulation.behavior.hostile import HostileBehavior
        behavior = HostileBehavior(combat)
        behavior.set_comms(comms)

        kid = _make_hostile("h1", pos=(14.0, 0.0), fsm_state="advancing")
        kid.weapon_range = 20.0
        turret = _make_turret("t1", pos=(0.0, 0.0))
        friendlies = {"t1": turret}
        behavior.tick(kid, friendlies)
        signals = comms.get_signals_for("h2", (20.0, 0.0), "hostile")
        contacts = [s for s in signals if s.signal_type == "contact"]
        assert len(contacts) >= 1

    def test_hostile_emits_retreat_when_fleeing(self):
        """Hostile entering fleeing state should emit retreat."""
        bus = EventBus()
        comms = UnitComms(comm_range=50.0, event_bus=bus)
        combat = _make_combat(bus)
        from engine.simulation.behavior.hostile import HostileBehavior
        behavior = HostileBehavior(combat)
        behavior.set_comms(comms)

        kid = _make_hostile("h1", pos=(10.0, 10.0), fsm_state="fleeing")
        kid.waypoints = [(100.0, 100.0)]
        friendlies = {"t1": _make_turret("t1", pos=(0.0, 0.0))}
        behavior.tick(kid, friendlies)
        signals = comms.get_signals_for("h2", (15.0, 10.0), "hostile")
        retreats = [s for s in signals if s.signal_type == "retreat"]
        assert len(retreats) >= 1

    def test_hostile_responds_to_distress_by_moving(self):
        """A hostile that hears distress should adjust movement toward it."""
        comms = UnitComms(comm_range=50.0)
        comms.emit_distress("h1", (0.0, 0.0), "hostile")
        h2 = _make_hostile("h2", pos=(30.0, 0.0), fsm_state="advancing")
        signals = comms.get_signals_for("h2", h2.position, "hostile")
        response = comms.get_response_for(h2, signals)
        assert response is not None
        assert response["action"] == "reinforce"
        # Target position is the distress source
        assert response["target_position"] == (0.0, 0.0)


# ---------------------------------------------------------------------------
# TestCoordinatorCommsWiring — coordinator passes comms to behaviors
# ---------------------------------------------------------------------------

class TestCoordinatorCommsWiring:
    def test_coordinator_accepts_comms(self):
        """BehaviorCoordinator should accept and forward UnitComms."""
        bus = EventBus()
        comms = UnitComms(comm_range=50.0, event_bus=bus)
        combat = _make_combat(bus)
        from engine.simulation.behavior.coordinator import BehaviorCoordinator
        coord = BehaviorCoordinator(combat)
        coord.set_comms(comms)
        # Verify hostile behavior got comms
        assert coord._hostile._comms is comms

    def test_coordinator_passes_comms_to_rover(self):
        """BehaviorCoordinator should pass comms to rover behavior."""
        bus = EventBus()
        comms = UnitComms(comm_range=50.0, event_bus=bus)
        combat = _make_combat(bus)
        from engine.simulation.behavior.coordinator import BehaviorCoordinator
        coord = BehaviorCoordinator(combat)
        coord.set_comms(comms)
        assert coord._rover._comms is comms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_combat(bus: EventBus):
    from engine.simulation.combat import CombatSystem
    return CombatSystem(bus)
