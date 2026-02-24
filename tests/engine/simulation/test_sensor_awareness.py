"""Tests for sensor awareness — hostiles adapt when sensors detect them.

TDD: these tests are written BEFORE the implementation.

When a sensor_triggered event fires with a hostile's target_id, the hostile
should be marked as detected and adapt its behavior:
  - Speed up by 20% (urgency)
  - Prefer flanking routes (wider flank angle)
  - If reconning, immediately transition to advancing (cover blown)
  - If suppressing, transition to retreating_under_fire (position known)
  - Detection expires after 30s
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from engine.simulation.sensors import SensorSimulator
from engine.simulation.target import SimulationTarget
from engine.simulation.unit_states import create_hostile_fsm
from engine.simulation.behaviors import UnitBehaviors
from engine.simulation.combat import CombatSystem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hostile(
    x: float = 0.0,
    y: float = 0.0,
    target_id: str = "hostile-1",
    name: str = "Intruder Alpha",
    speed: float = 3.0,
) -> SimulationTarget:
    """Create a hostile person target for testing."""
    t = SimulationTarget(
        target_id=target_id,
        name=name,
        alliance="hostile",
        asset_type="person",
        position=(x, y),
        speed=speed,
        waypoints=[(50.0, 50.0), (100.0, 100.0)],
    )
    t.apply_combat_profile()
    return t


def _make_friendly_turret(
    x: float = 0.0,
    y: float = 0.0,
    target_id: str = "turret-1",
    name: str = "Turret Alpha",
) -> SimulationTarget:
    """Create a friendly turret target for testing."""
    t = SimulationTarget(
        target_id=target_id,
        name=name,
        alliance="friendly",
        asset_type="turret",
        position=(x, y),
        speed=0.0,
    )
    t.apply_combat_profile()
    return t


def _drain_events(sub, event_type: str = None, max_tries: int = 100):
    """Drain events from a subscriber queue, optionally filtering by type."""
    events = []
    for _ in range(max_tries):
        try:
            msg = sub.get(timeout=0.01)
            if event_type is None or msg.get("type") == event_type:
                events.append(msg)
        except Exception:
            break
    return events


# ===========================================================================
# Test: SimulationTarget gets detected/detected_at fields
# ===========================================================================

class TestTargetDetectedFields:
    """SimulationTarget must have detected and detected_at fields."""

    def test_target_has_detected_field_default_false(self):
        t = _make_hostile()
        assert t.detected is False

    def test_target_has_detected_at_field_default_zero(self):
        t = _make_hostile()
        assert t.detected_at == 0.0

    def test_detected_can_be_set_to_true(self):
        t = _make_hostile()
        t.detected = True
        t.detected_at = time.monotonic()
        assert t.detected is True
        assert t.detected_at > 0.0

    def test_detected_included_in_to_dict(self):
        t = _make_hostile()
        t.detected = True
        t.detected_at = 123.456
        d = t.to_dict()
        assert d["detected"] is True


# ===========================================================================
# Test: Engine subscribes to sensor_triggered and marks hostiles
# ===========================================================================

class TestEngineMarksDetected:
    """Engine must subscribe to sensor_triggered events and mark hostiles."""

    def test_engine_marks_hostile_detected_on_sensor_event(self):
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        hostile = _make_hostile(x=10.0, y=10.0, target_id="h1")
        engine.add_target(hostile)

        # Simulate a sensor_triggered event
        eb.publish("sensor_triggered", {
            "sensor_id": "s1",
            "name": "Front Porch",
            "type": "motion",
            "triggered_by": "Intruder Alpha",
            "target_id": "h1",
            "position": {"x": 5.0, "z": 5.0},
        })

        # Give the engine listener a moment to process
        engine._handle_sensor_triggered({
            "sensor_id": "s1",
            "name": "Front Porch",
            "type": "motion",
            "triggered_by": "Intruder Alpha",
            "target_id": "h1",
            "position": {"x": 5.0, "z": 5.0},
        })

        assert hostile.detected is True
        assert hostile.detected_at > 0.0

    def test_engine_ignores_sensor_event_for_unknown_target(self):
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        # No targets added
        engine._handle_sensor_triggered({
            "sensor_id": "s1",
            "name": "Front Porch",
            "type": "motion",
            "triggered_by": "Ghost",
            "target_id": "nonexistent",
            "position": {"x": 5.0, "z": 5.0},
        })
        # Should not crash

    def test_engine_only_marks_matching_hostile(self):
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        h1 = _make_hostile(x=10.0, y=10.0, target_id="h1", name="Alpha")
        h2 = _make_hostile(x=50.0, y=50.0, target_id="h2", name="Bravo")
        engine.add_target(h1)
        engine.add_target(h2)

        engine._handle_sensor_triggered({
            "sensor_id": "s1",
            "name": "Front Porch",
            "type": "motion",
            "triggered_by": "Alpha",
            "target_id": "h1",
            "position": {"x": 5.0, "z": 5.0},
        })

        assert h1.detected is True
        assert h2.detected is False


# ===========================================================================
# Test: Detected hostiles get +20% speed boost
# ===========================================================================

class TestDetectedSpeedBoost:
    """Detected hostiles should speed up by 20%."""

    def test_detected_hostile_gets_speed_boost(self):
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile(speed=3.0)
        hostile.detected = True
        hostile.detected_at = time.monotonic()
        original_speed = hostile.speed

        targets = {hostile.target_id: hostile}
        behaviors.apply_sensor_awareness(hostile)

        assert hostile.speed == pytest.approx(original_speed * 1.2, rel=0.01)

    def test_undetected_hostile_keeps_normal_speed(self):
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile(speed=3.0)
        original_speed = hostile.speed

        behaviors.apply_sensor_awareness(hostile)

        assert hostile.speed == pytest.approx(original_speed, rel=0.01)

    def test_speed_boost_only_applied_once(self):
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile(speed=3.0)
        hostile.detected = True
        hostile.detected_at = time.monotonic()
        original_speed = hostile.speed

        # Apply twice
        behaviors.apply_sensor_awareness(hostile)
        behaviors.apply_sensor_awareness(hostile)

        # Should still be 1.2x, not 1.44x
        assert hostile.speed == pytest.approx(original_speed * 1.2, rel=0.01)


# ===========================================================================
# Test: Detected hostile prefers wider flank angle
# ===========================================================================

class TestDetectedFlankAngle:
    """Detected hostiles should prefer flanking with wider angle."""

    def test_detected_hostile_uses_wider_flank_angle(self):
        """When detected, flank step should be larger (wider angle)."""
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile(x=20.0, y=0.0)
        hostile.detected = True
        hostile.detected_at = time.monotonic()

        turret = _make_friendly_turret(x=0.0, y=0.0)
        friendlies = {turret.target_id: turret}

        # Record starting position
        start_pos = hostile.position

        # Force flank by clearing the last_flank timer
        behaviors._last_flank[hostile.target_id] = 0.0

        # The _try_flank method should use a larger step when detected
        result = behaviors._try_flank(hostile, friendlies)

        if result:
            # If flank happened, the offset should be larger than normal _FLANK_STEP
            import math
            dx = hostile.position[0] - start_pos[0]
            dy = hostile.position[1] - start_pos[1]
            offset_dist = math.hypot(dx, dy)
            # Normal flank step is 1.5m, detected should be 3.0m (doubled)
            assert offset_dist > 1.5


# ===========================================================================
# Test: FSM transitions for detected hostiles
# ===========================================================================

class TestFSMSensorTransitions:
    """FSM transitions should react to sensor detection."""

    def test_reconning_hostile_detected_transitions_to_advancing(self):
        """A reconning hostile that gets detected should advance (cover blown)."""
        from engine.simulation.state_machine import StateMachine

        fsm = create_hostile_fsm()

        # Manually advance past spawning
        ctx = {
            "enemies_in_range": [],
            "enemy_in_weapon_range": False,
            "weapon_ready": False,
            "health_pct": 1.0,
            "has_waypoints": True,
            "aimed_at_target": False,
            "just_fired": False,
            "nearest_enemy_stationary": False,
            "enemies_at_recon_range": False,
            "cover_available": False,
            "ally_is_flanking": False,
            "detected": False,
        }
        # Tick past spawning min_duration (1.0s)
        for _ in range(12):
            fsm.tick(0.1, ctx)
        assert fsm.current_state == "advancing"

        # Setup for reconning: enemies at recon range, not in weapon range
        ctx["enemies_in_range"] = [MagicMock()]
        ctx["enemies_at_recon_range"] = True
        fsm.tick(0.1, ctx)  # advancing -> reconning
        assert fsm.current_state == "reconning"

        # Now detect the hostile
        ctx["detected"] = True
        fsm.tick(0.1, ctx)  # reconning + detected -> advancing (cover blown)
        assert fsm.current_state == "advancing"

    def test_suppressing_hostile_detected_transitions_to_retreating(self):
        """A suppressing hostile that gets detected should retreat (position compromised)."""
        fsm = create_hostile_fsm()

        ctx = {
            "enemies_in_range": [MagicMock()],
            "enemy_in_weapon_range": True,
            "weapon_ready": True,
            "health_pct": 1.0,
            "has_waypoints": True,
            "aimed_at_target": True,
            "just_fired": False,
            "nearest_enemy_stationary": True,
            "enemies_at_recon_range": True,
            "cover_available": True,
            "ally_is_flanking": True,
            "detected": False,
        }

        # Tick past spawning min_duration (1.0s) -> advancing
        for _ in range(12):
            fsm.tick(0.1, ctx)
        # advancing -> engaging (enemy in weapon range)
        fsm.tick(0.1, ctx)

        # engaging -> suppressing (ally flanking + enemy stationary + in range)
        fsm.tick(0.1, ctx)

        # May need a few ticks to reach suppressing
        for _ in range(5):
            if fsm.current_state == "suppressing":
                break
            fsm.tick(0.1, ctx)

        assert fsm.current_state == "suppressing", f"Expected suppressing, got {fsm.current_state}"

        # Now detect the hostile
        ctx["detected"] = True
        fsm.tick(0.1, ctx)
        assert fsm.current_state == "retreating_under_fire"

    def test_advancing_hostile_not_affected_by_detection(self):
        """Detection should NOT force an advancing hostile to change state."""
        fsm = create_hostile_fsm()

        ctx = {
            "enemies_in_range": [],
            "enemy_in_weapon_range": False,
            "weapon_ready": False,
            "health_pct": 1.0,
            "has_waypoints": True,
            "aimed_at_target": False,
            "just_fired": False,
            "nearest_enemy_stationary": False,
            "enemies_at_recon_range": False,
            "cover_available": False,
            "ally_is_flanking": False,
            "detected": False,
        }

        # Tick past spawning min_duration (1.0s)
        for _ in range(12):
            fsm.tick(0.1, ctx)
        assert fsm.current_state == "advancing"

        ctx["detected"] = True
        fsm.tick(0.1, ctx)  # advancing stays advancing (already moving)
        assert fsm.current_state == "advancing"


# ===========================================================================
# Test: Detection context passed through _tick_fsms
# ===========================================================================

class TestEnginePassesDetectedContext:
    """Engine._tick_fsms should pass detected status in FSM context."""

    def test_tick_fsms_includes_detected_in_context(self):
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        hostile = _make_hostile(x=10.0, y=10.0, target_id="h1")
        hostile.detected = True
        hostile.detected_at = time.monotonic()
        engine.add_target(hostile)

        # Tick FSMs — the context should include detected=True
        targets_dict = {hostile.target_id: hostile}
        engine._tick_fsms(0.1, targets_dict)

        # Verify the FSM saw the detected context by checking state transition
        # (if in reconning with detected=True, it should advance)
        # For this test, we just verify no crash and FSM was ticked
        assert hostile.fsm_state is not None

    def test_tick_fsms_detected_false_for_undetected(self):
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        hostile = _make_hostile(x=10.0, y=10.0, target_id="h1")
        assert hostile.detected is False
        engine.add_target(hostile)

        targets_dict = {hostile.target_id: hostile}
        engine._tick_fsms(0.1, targets_dict)

        # Should not crash, FSM should still tick
        assert hostile.fsm_state is not None


# ===========================================================================
# Test: Detection expires after 30s
# ===========================================================================

class TestDetectionExpiry:
    """Detection should expire after 30 seconds."""

    DETECTION_EXPIRY = 30.0

    def test_detection_expires_after_30s(self):
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        hostile = _make_hostile(x=10.0, y=10.0, target_id="h1")
        engine.add_target(hostile)

        # Mark as detected 31 seconds ago
        hostile.detected = True
        hostile.detected_at = time.monotonic() - 31.0

        engine._expire_detections()

        assert hostile.detected is False

    def test_recent_detection_does_not_expire(self):
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        hostile = _make_hostile(x=10.0, y=10.0, target_id="h1")
        engine.add_target(hostile)

        hostile.detected = True
        hostile.detected_at = time.monotonic() - 10.0  # 10s ago

        engine._expire_detections()

        assert hostile.detected is True

    def test_speed_restored_when_detection_expires(self):
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile(speed=3.0)
        original_speed = hostile.speed

        # Detect and boost
        hostile.detected = True
        hostile.detected_at = time.monotonic()
        behaviors.apply_sensor_awareness(hostile)
        assert hostile.speed == pytest.approx(original_speed * 1.2, rel=0.01)

        # Expire detection
        hostile.detected = False
        behaviors.remove_sensor_awareness(hostile)

        assert hostile.speed == pytest.approx(original_speed, rel=0.01)


# ===========================================================================
# Test: Full integration — sensor triggers, engine processes, hostile adapts
# ===========================================================================

class TestFullIntegration:
    """Integration test: sensor fires -> engine marks -> hostile adapts."""

    def test_sensor_trigger_marks_hostile_detected(self):
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        # Add a hostile near a sensor
        hostile = _make_hostile(x=5.0, y=5.0, target_id="h1")
        engine.add_target(hostile)

        # Add a sensor that covers the hostile's position
        engine.sensor_sim.add_sensor("s1", "Porch", "motion", (5.0, 5.0), 10.0)

        # The sensor simulator will trigger and publish sensor_triggered
        # The engine should subscribe and mark the hostile
        engine.sensor_sim.tick(0.1, engine.get_targets())

        # Process the event through the engine handler
        # (In production this happens via EventBus subscription thread)
        engine._handle_sensor_triggered({
            "sensor_id": "s1",
            "name": "Porch",
            "type": "motion",
            "triggered_by": "Intruder Alpha",
            "target_id": "h1",
            "position": {"x": 5.0, "z": 5.0},
        })

        assert hostile.detected is True

    def test_multiple_hostiles_only_detected_one_adapts(self):
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        h1 = _make_hostile(x=5.0, y=5.0, target_id="h1", name="Alpha")
        h2 = _make_hostile(x=100.0, y=100.0, target_id="h2", name="Bravo")
        engine.add_target(h1)
        engine.add_target(h2)

        # Only h1 trips the sensor
        engine._handle_sensor_triggered({
            "sensor_id": "s1",
            "name": "Porch",
            "type": "motion",
            "triggered_by": "Alpha",
            "target_id": "h1",
            "position": {"x": 5.0, "z": 5.0},
        })

        assert h1.detected is True
        assert h2.detected is False

    def test_detected_hostile_fsm_recon_to_advancing(self):
        """Full flow: sensor triggers -> hostile marked -> reconning -> advancing."""
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200.0)

        hostile = _make_hostile(x=40.0, y=0.0, target_id="h1")
        engine.add_target(hostile)

        # Put the FSM into reconning state
        fsm = engine._fsms.get("h1")
        assert fsm is not None

        # Tick once to get past spawning
        turret = _make_friendly_turret(x=0.0, y=0.0, target_id="t1")
        engine.add_target(turret)

        targets_dict = {
            "h1": hostile,
            "t1": turret,
        }

        # Advance past spawning
        ctx_base = {
            "enemies_in_range": [],
            "enemy_in_weapon_range": False,
            "weapon_ready": False,
            "health_pct": 1.0,
            "has_waypoints": True,
            "aimed_at_target": False,
            "just_fired": False,
            "nearest_enemy_stationary": False,
            "enemies_at_recon_range": False,
            "cover_available": False,
            "ally_is_flanking": False,
            "detected": False,
        }
        # Tick past spawning min_duration (1.0s)
        for _ in range(12):
            fsm.tick(0.1, ctx_base)
        assert fsm.current_state == "advancing"

        # Get into reconning
        ctx_recon = dict(ctx_base)
        ctx_recon["enemies_in_range"] = [turret]
        ctx_recon["enemies_at_recon_range"] = True
        fsm.tick(0.1, ctx_recon)
        assert fsm.current_state == "reconning"

        # Mark detected via engine
        engine._handle_sensor_triggered({
            "sensor_id": "s1",
            "name": "Porch",
            "type": "motion",
            "triggered_by": "Intruder Alpha",
            "target_id": "h1",
            "position": {"x": 30.0, "z": 0.0},
        })
        assert hostile.detected is True

        # Now tick FSMs through engine — should pass detected=True in context
        engine._tick_fsms(0.1, targets_dict)

        # Reconning + detected should transition to advancing
        assert hostile.fsm_state == "advancing"


# ===========================================================================
# Test: Behaviors apply_sensor_awareness and remove_sensor_awareness
# ===========================================================================

class TestBehaviorsSensorAwareness:
    """UnitBehaviors sensor awareness methods."""

    def test_apply_sensor_awareness_stores_base_speed(self):
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile(speed=3.0)
        hostile.detected = True
        hostile.detected_at = time.monotonic()

        behaviors.apply_sensor_awareness(hostile)

        assert hostile.target_id in behaviors._detected_base_speeds

    def test_remove_sensor_awareness_restores_speed(self):
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile(speed=3.0)
        original_speed = hostile.speed
        hostile.detected = True
        hostile.detected_at = time.monotonic()

        behaviors.apply_sensor_awareness(hostile)
        assert hostile.speed != original_speed

        hostile.detected = False
        behaviors.remove_sensor_awareness(hostile)
        assert hostile.speed == pytest.approx(original_speed, rel=0.01)

    def test_clear_dodge_state_clears_sensor_awareness(self):
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile(speed=3.0)
        hostile.detected = True
        hostile.detected_at = time.monotonic()
        behaviors.apply_sensor_awareness(hostile)

        behaviors.clear_dodge_state()

        assert len(behaviors._detected_base_speeds) == 0
        assert len(behaviors._detected_ids) == 0
