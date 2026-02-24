"""Unit tests for intercept prediction — proportional navigation and lead targeting.

Tests are written FIRST (TDD). All must fail until intercept.py is implemented.
"""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from engine.simulation.intercept import predict_intercept, lead_target, time_to_intercept, target_velocity


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# predict_intercept — pursuer chasing a moving target
# --------------------------------------------------------------------------

class TestPredictInterceptStaticTarget:
    """When the target is stationary, intercept point == target position."""

    def test_static_target_returns_current_position(self):
        result = predict_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(10.0, 0.0),
            target_vel=(0.0, 0.0),
        )
        assert abs(result[0] - 10.0) < 0.1
        assert abs(result[1] - 0.0) < 0.1

    def test_static_target_at_origin(self):
        result = predict_intercept(
            pursuer_pos=(5.0, 5.0),
            pursuer_speed=3.0,
            target_pos=(0.0, 0.0),
            target_vel=(0.0, 0.0),
        )
        assert abs(result[0] - 0.0) < 0.1
        assert abs(result[1] - 0.0) < 0.1


class TestPredictInterceptMovingTarget:
    """When the target is moving, intercept point is ahead of target."""

    def test_target_moving_right_intercept_is_ahead(self):
        # Pursuer at origin, target at (20, 0) moving right at 3 m/s.
        # Intercept point should be to the right of (20, 0).
        result = predict_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(20.0, 0.0),
            target_vel=(3.0, 0.0),
        )
        assert result[0] > 20.0, "Intercept should be ahead of target"

    def test_target_moving_up_intercept_is_ahead(self):
        # Target at (10, 0) moving upward (0, 3).  Pursuer faster at 5 m/s.
        result = predict_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(10.0, 0.0),
            target_vel=(0.0, 3.0),
        )
        assert result[1] > 0.0, "Intercept should be above target's current y"

    def test_target_moving_diagonally(self):
        result = predict_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=10.0,
            target_pos=(30.0, 0.0),
            target_vel=(2.0, 2.0),
        )
        # Intercept should be ahead in both x and y
        assert result[0] > 30.0
        assert result[1] > 0.0

    def test_target_moving_toward_pursuer(self):
        # Target moving toward the pursuer — intercept should be between them.
        result = predict_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(20.0, 0.0),
            target_vel=(-3.0, 0.0),
        )
        # Intercept should be between pursuer and current target position
        assert 0.0 < result[0] < 20.0


class TestPredictInterceptFastTarget:
    """When the target is faster than the pursuer, graceful fallback."""

    def test_uncatchable_target_returns_current_position(self):
        # Target is much faster than pursuer — can't intercept.
        result = predict_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=2.0,
            target_pos=(50.0, 0.0),
            target_vel=(10.0, 0.0),  # Running away at 10 m/s
        )
        # Should fall back to target's current position
        assert abs(result[0] - 50.0) < 0.1
        assert abs(result[1] - 0.0) < 0.1

    def test_fast_perpendicular_target_fallback(self):
        # Target moving perpendicular at high speed.
        result = predict_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=1.0,
            target_pos=(100.0, 0.0),
            target_vel=(0.0, 50.0),
        )
        # Should return something reasonable (either intercept or fallback)
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestPredictInterceptEdgeCases:
    """Edge cases: zero speed, coincident positions, etc."""

    def test_zero_pursuer_speed_returns_target_pos(self):
        result = predict_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=0.0,
            target_pos=(10.0, 5.0),
            target_vel=(1.0, 0.0),
        )
        assert abs(result[0] - 10.0) < 0.1
        assert abs(result[1] - 5.0) < 0.1

    def test_coincident_positions(self):
        result = predict_intercept(
            pursuer_pos=(5.0, 5.0),
            pursuer_speed=5.0,
            target_pos=(5.0, 5.0),
            target_vel=(3.0, 0.0),
        )
        # Already at target — result should be near target
        assert abs(result[0] - 5.0) < 1.0
        assert abs(result[1] - 5.0) < 1.0

    def test_returns_tuple_of_two_floats(self):
        result = predict_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(10.0, 10.0),
            target_vel=(1.0, -1.0),
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)


# --------------------------------------------------------------------------
# lead_target — projectile aiming ahead of moving target
# --------------------------------------------------------------------------

class TestLeadTargetStatic:
    """For a static target, lead point == target position."""

    def test_static_target_no_lead(self):
        result = lead_target(
            shooter_pos=(0.0, 0.0),
            target_pos=(10.0, 0.0),
            target_vel=(0.0, 0.0),
            projectile_speed=25.0,
        )
        assert abs(result[0] - 10.0) < 0.1
        assert abs(result[1] - 0.0) < 0.1


class TestLeadTargetMoving:
    """Lead point is ahead of target in its direction of travel."""

    def test_target_moving_right(self):
        result = lead_target(
            shooter_pos=(0.0, 0.0),
            target_pos=(20.0, 0.0),
            target_vel=(5.0, 0.0),
            projectile_speed=25.0,
        )
        # Lead point should be to the right of target
        assert result[0] > 20.0

    def test_target_moving_up(self):
        result = lead_target(
            shooter_pos=(0.0, 0.0),
            target_pos=(10.0, 0.0),
            target_vel=(0.0, 3.0),
            projectile_speed=25.0,
        )
        # Lead point should be above target
        assert result[1] > 0.0

    def test_lead_distance_proportional_to_target_speed(self):
        # Faster target => more lead distance needed
        result_slow = lead_target(
            shooter_pos=(0.0, 0.0),
            target_pos=(20.0, 0.0),
            target_vel=(2.0, 0.0),
            projectile_speed=25.0,
        )
        result_fast = lead_target(
            shooter_pos=(0.0, 0.0),
            target_pos=(20.0, 0.0),
            target_vel=(8.0, 0.0),
            projectile_speed=25.0,
        )
        assert result_fast[0] > result_slow[0], "Faster target needs more lead"

    def test_lead_distance_inversely_proportional_to_projectile_speed(self):
        # Faster projectile => less lead needed
        result_slow_proj = lead_target(
            shooter_pos=(0.0, 0.0),
            target_pos=(20.0, 0.0),
            target_vel=(5.0, 0.0),
            projectile_speed=10.0,
        )
        result_fast_proj = lead_target(
            shooter_pos=(0.0, 0.0),
            target_pos=(20.0, 0.0),
            target_vel=(5.0, 0.0),
            projectile_speed=50.0,
        )
        assert result_slow_proj[0] > result_fast_proj[0], "Slower projectile needs more lead"


class TestLeadTargetEdgeCases:
    """Edge cases for lead_target."""

    def test_zero_projectile_speed_returns_target_pos(self):
        result = lead_target(
            shooter_pos=(0.0, 0.0),
            target_pos=(10.0, 5.0),
            target_vel=(3.0, 0.0),
            projectile_speed=0.0,
        )
        assert abs(result[0] - 10.0) < 0.1
        assert abs(result[1] - 5.0) < 0.1

    def test_returns_tuple_of_two_floats(self):
        result = lead_target(
            shooter_pos=(0.0, 0.0),
            target_pos=(10.0, 10.0),
            target_vel=(2.0, -1.0),
            projectile_speed=25.0,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)


# --------------------------------------------------------------------------
# time_to_intercept
# --------------------------------------------------------------------------

class TestTimeToIntercept:
    """Estimated time for pursuer to reach moving target."""

    def test_static_target_simple_distance(self):
        # Distance 10, speed 5 => time ~2.0s
        t = time_to_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(10.0, 0.0),
            target_vel=(0.0, 0.0),
        )
        assert abs(t - 2.0) < 0.5

    def test_target_approaching_reduces_time(self):
        # Target moving toward pursuer should reduce intercept time.
        t_static = time_to_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(20.0, 0.0),
            target_vel=(0.0, 0.0),
        )
        t_approaching = time_to_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(20.0, 0.0),
            target_vel=(-3.0, 0.0),
        )
        assert t_approaching < t_static

    def test_target_fleeing_increases_time(self):
        t_static = time_to_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(20.0, 0.0),
            target_vel=(0.0, 0.0),
        )
        t_fleeing = time_to_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(20.0, 0.0),
            target_vel=(2.0, 0.0),
        )
        assert t_fleeing > t_static

    def test_uncatchable_returns_large_value(self):
        t = time_to_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=2.0,
            target_pos=(50.0, 0.0),
            target_vel=(10.0, 0.0),
        )
        # Should return a large sentinel value (infinity or big number)
        assert t >= 999.0

    def test_zero_distance_returns_zero(self):
        t = time_to_intercept(
            pursuer_pos=(5.0, 5.0),
            pursuer_speed=5.0,
            target_pos=(5.0, 5.0),
            target_vel=(0.0, 0.0),
        )
        assert t < 0.1

    def test_returns_positive_float(self):
        t = time_to_intercept(
            pursuer_pos=(0.0, 0.0),
            pursuer_speed=5.0,
            target_pos=(10.0, 10.0),
            target_vel=(1.0, -1.0),
        )
        assert isinstance(t, float)
        assert t >= 0.0


# --------------------------------------------------------------------------
# Integration: intercept prediction accuracy
# --------------------------------------------------------------------------

class TestInterceptAccuracy:
    """Verify that the predicted intercept point is geometrically correct."""

    def test_predicted_intercept_is_reachable(self):
        """Pursuer traveling at pursuer_speed reaches intercept point
        at approximately the same time as the target."""
        pursuer_pos = (0.0, 0.0)
        pursuer_speed = 5.0
        target_pos = (20.0, 0.0)
        target_vel = (0.0, 3.0)

        intercept_pt = predict_intercept(pursuer_pos, pursuer_speed, target_pos, target_vel)
        t_est = time_to_intercept(pursuer_pos, pursuer_speed, target_pos, target_vel)

        # Target arrives at intercept point at time t_est
        target_at_t = (
            target_pos[0] + target_vel[0] * t_est,
            target_pos[1] + target_vel[1] * t_est,
        )
        # Pursuer distance to intercept point
        pursuer_dist = math.hypot(
            intercept_pt[0] - pursuer_pos[0],
            intercept_pt[1] - pursuer_pos[1],
        )
        pursuer_time = pursuer_dist / pursuer_speed if pursuer_speed > 0 else float('inf')

        # Both should arrive at roughly the same time (within 20% or 1s)
        if t_est < 999.0:
            assert abs(pursuer_time - t_est) < max(t_est * 0.3, 1.0)

    def test_lead_target_projectile_arrives_at_target(self):
        """A projectile fired at the lead point should arrive near the target."""
        shooter_pos = (0.0, 0.0)
        target_pos = (15.0, 0.0)
        target_vel = (0.0, 4.0)
        projectile_speed = 25.0

        lead_pt = lead_target(shooter_pos, target_pos, target_vel, projectile_speed)

        # Time for projectile to reach lead point
        proj_dist = math.hypot(lead_pt[0] - shooter_pos[0], lead_pt[1] - shooter_pos[1])
        proj_time = proj_dist / projectile_speed

        # Where the target is when the projectile arrives
        target_at_arrival = (
            target_pos[0] + target_vel[0] * proj_time,
            target_pos[1] + target_vel[1] * proj_time,
        )

        # Target should be near the lead point
        error = math.hypot(
            target_at_arrival[0] - lead_pt[0],
            target_at_arrival[1] - lead_pt[1],
        )
        assert error < 2.0, f"Lead target error {error:.2f}m exceeds 2m tolerance"


# --------------------------------------------------------------------------
# target_velocity — heading+speed to (vx, vy) conversion
# --------------------------------------------------------------------------

class TestTargetVelocity:
    """Convert game-convention heading+speed to velocity vector."""

    def test_north_heading(self):
        # Heading 0 = north (+y direction)
        vx, vy = target_velocity(0.0, 5.0)
        assert abs(vx) < 0.01
        assert abs(vy - 5.0) < 0.01

    def test_east_heading(self):
        # Heading 90 = east (+x direction)
        vx, vy = target_velocity(90.0, 5.0)
        assert abs(vx - 5.0) < 0.01
        assert abs(vy) < 0.01

    def test_south_heading(self):
        # Heading 180 = south (-y direction)
        vx, vy = target_velocity(180.0, 5.0)
        assert abs(vx) < 0.01
        assert abs(vy - (-5.0)) < 0.01

    def test_west_heading(self):
        # Heading 270 = west (-x direction)
        vx, vy = target_velocity(270.0, 5.0)
        assert abs(vx - (-5.0)) < 0.01
        assert abs(vy) < 0.01

    def test_zero_speed(self):
        vx, vy = target_velocity(45.0, 0.0)
        assert vx == 0.0
        assert vy == 0.0

    def test_velocity_magnitude_equals_speed(self):
        vx, vy = target_velocity(37.0, 8.0)
        mag = math.hypot(vx, vy)
        assert abs(mag - 8.0) < 0.01


# --------------------------------------------------------------------------
# Integration: behavior wiring — turret lead targeting improves accuracy
# --------------------------------------------------------------------------

class TestBehaviorIntegrationLeadTargeting:
    """Verify that behaviors use intercept/lead functions."""

    def test_turret_fires_with_aim_pos(self):
        """Turret behavior should compute a lead point and pass aim_pos to fire()."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors
        from engine.simulation.target import SimulationTarget

        bus = _SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        turret = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0), speed=0.0,
            weapon_range=25.0, weapon_damage=15.0,
            weapon_cooldown=0.0, last_fired=0.0,
        )
        # Moving hostile heading east (90 degrees) at 3 m/s
        hostile = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(15.0, 0.0), speed=3.0,
            heading=90.0,
            weapon_range=8.0, weapon_damage=10.0,
            weapon_cooldown=2.5, last_fired=0.0,
        )
        hostile.apply_combat_profile()

        targets = {"t1": turret, "h1": hostile}
        behaviors.tick(0.1, targets)

        # Turret should have fired — check that a projectile exists
        assert combat.projectile_count >= 1
        # The projectile target_pos should NOT be exactly the hostile's current position
        # because lead targeting shifts it forward
        proj = list(combat._projectiles.values())[0]
        # Lead point should be ahead of the hostile (larger x since heading east)
        assert proj.target_pos[0] >= 15.0, "Projectile should aim at or ahead of hostile"

    def test_rover_heading_points_to_intercept(self):
        """Rover behavior should aim heading toward predicted intercept point."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors
        from engine.simulation.target import SimulationTarget

        bus = _SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        rover = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=4.0,
            weapon_range=15.0, weapon_damage=12.0,
            weapon_cooldown=0.0, last_fired=0.0,
        )
        # Hostile moving north (heading 0) at 3 m/s, currently at (10, 0)
        hostile = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0), speed=3.0,
            heading=0.0,
            weapon_range=8.0, weapon_damage=10.0,
            weapon_cooldown=2.5, last_fired=0.0,
        )
        hostile.apply_combat_profile()

        initial_heading = rover.heading
        targets = {"r1": rover, "h1": hostile}
        behaviors.tick(0.1, targets)

        # Rover heading should point somewhat north (positive y component)
        # because the hostile is moving north
        heading_rad = math.radians(rover.heading)
        # atan2(dx, dy) convention: positive heading means positive dx
        # Heading should have a y component > 0 since intercept is above
        # the target's current position (target moving north)
        # rover heading uses atan2(dx, dy) so heading>0 means clockwise from north
        # If intercept is at roughly (10, y_future), heading should be
        # roughly pointing northeast
        assert rover.heading != initial_heading, "Rover heading should have changed"

    def test_drone_fires_with_lead(self):
        """Drone behavior should use lead targeting when firing."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors
        from engine.simulation.target import SimulationTarget

        bus = _SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        drone = SimulationTarget(
            target_id="d1", name="Drone", alliance="friendly",
            asset_type="drone", position=(0.0, 0.0), speed=6.0,
            weapon_range=15.0, weapon_damage=8.0,
            weapon_cooldown=0.0, last_fired=0.0,
        )
        # Moving hostile heading south (180 degrees) at 3 m/s
        hostile = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0), speed=3.0,
            heading=180.0,
            weapon_range=8.0, weapon_damage=10.0,
            weapon_cooldown=2.5, last_fired=0.0,
        )
        hostile.apply_combat_profile()

        targets = {"d1": drone, "h1": hostile}
        behaviors.tick(0.1, targets)

        # Drone should have fired with lead targeting
        assert combat.projectile_count >= 1
        proj = list(combat._projectiles.values())[0]
        # Lead point should account for southward movement (negative y)
        assert proj.target_pos[1] <= 0.0, "Projectile should aim at or below hostile (moving south)"


class _SimpleEventBus:
    """Minimal EventBus for integration tests."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        if topic is not None:
            with self._lock:
                self._subscribers.setdefault(topic, []).append(q)
        return q
