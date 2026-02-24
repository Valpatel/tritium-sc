"""Unit tests for DegradationSystem -- health-based performance degradation.

Tests cover:
  - Health fraction calculation
  - Degradation factor (linear below 50% health threshold)
  - No penalties above 50% health
  - Effective speed reduction below threshold
  - Effective cooldown increase below threshold
  - Cannot fire below 10% health
  - Tick and reset are safe no-ops
  - Integration: degraded stats affect gameplay
"""

from __future__ import annotations

import pytest

from engine.simulation.target import SimulationTarget
from engine.simulation.degradation import DegradationSystem


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    health: float = 100.0,
    max_health: float = 100.0,
    speed: float = 5.0,
    weapon_cooldown: float = 2.0,
    weapon_damage: float = 10.0,
    weapon_range: float = 15.0,
    alliance: str = "friendly",
    asset_type: str = "rover",
) -> SimulationTarget:
    """Create a SimulationTarget with specified combat stats."""
    t = SimulationTarget(
        target_id="test-1",
        name="Test Unit",
        alliance=alliance,
        asset_type=asset_type,
        position=(0.0, 0.0),
        speed=speed,
    )
    t.health = health
    t.max_health = max_health
    t.weapon_cooldown = weapon_cooldown
    t.weapon_damage = weapon_damage
    t.weapon_range = weapon_range
    return t


# ---------------------------------------------------------------------------
# Health fraction calculation
# ---------------------------------------------------------------------------

class TestHealthFraction:
    """get_health_fraction returns health / max_health clamped to 0.0-1.0."""

    def test_full_health(self):
        ds = DegradationSystem()
        t = _make_target(health=100.0, max_health=100.0)
        assert ds.get_health_fraction(t) == pytest.approx(1.0)

    def test_half_health(self):
        ds = DegradationSystem()
        t = _make_target(health=50.0, max_health=100.0)
        assert ds.get_health_fraction(t) == pytest.approx(0.5)

    def test_quarter_health(self):
        ds = DegradationSystem()
        t = _make_target(health=25.0, max_health=100.0)
        assert ds.get_health_fraction(t) == pytest.approx(0.25)

    def test_zero_health(self):
        ds = DegradationSystem()
        t = _make_target(health=0.0, max_health=100.0)
        assert ds.get_health_fraction(t) == pytest.approx(0.0)

    def test_zero_max_health(self):
        """Edge case: max_health=0 should return 0.0 (not divide by zero)."""
        ds = DegradationSystem()
        t = _make_target(health=0.0, max_health=0.0)
        assert ds.get_health_fraction(t) == pytest.approx(0.0)

    def test_90_percent_health(self):
        ds = DegradationSystem()
        t = _make_target(health=90.0, max_health=100.0)
        assert ds.get_health_fraction(t) == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Degradation factor -- linear below 50% threshold
# ---------------------------------------------------------------------------

class TestDegradationFactor:
    """Degradation factor is 1.0 above threshold, linear 0->1 below."""

    def test_full_health_no_degradation(self):
        ds = DegradationSystem()
        t = _make_target(health=100.0, max_health=100.0)
        assert ds.get_degradation_factor(t) == pytest.approx(1.0)

    def test_at_threshold_no_degradation(self):
        """At exactly 50% health, no degradation."""
        ds = DegradationSystem()
        t = _make_target(health=50.0, max_health=100.0)
        assert ds.get_degradation_factor(t) == pytest.approx(1.0)

    def test_above_threshold_no_degradation(self):
        ds = DegradationSystem()
        t = _make_target(health=75.0, max_health=100.0)
        assert ds.get_degradation_factor(t) == pytest.approx(1.0)

    def test_25_percent_health_half_degraded(self):
        """25% health is halfway between 0 and 50% threshold -> factor = 0.5."""
        ds = DegradationSystem()
        t = _make_target(health=25.0, max_health=100.0)
        assert ds.get_degradation_factor(t) == pytest.approx(0.5)

    def test_zero_health_fully_degraded(self):
        ds = DegradationSystem()
        t = _make_target(health=0.0, max_health=100.0)
        assert ds.get_degradation_factor(t) == pytest.approx(0.0)

    def test_10_percent_health(self):
        """10% health: factor = 0.10 / 0.50 = 0.2."""
        ds = DegradationSystem()
        t = _make_target(health=10.0, max_health=100.0)
        assert ds.get_degradation_factor(t) == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# No penalties above 50% health
# ---------------------------------------------------------------------------

class TestNoPenaltiesAboveThreshold:
    """Above 50% health, effective stats are unchanged."""

    def test_effective_cooldown_unchanged_at_full(self):
        ds = DegradationSystem()
        t = _make_target(health=100.0, max_health=100.0, weapon_cooldown=2.0)
        assert ds.get_effective_cooldown(t) == pytest.approx(2.0)

    def test_effective_speed_unchanged_at_full(self):
        ds = DegradationSystem()
        t = _make_target(health=100.0, max_health=100.0, speed=5.0)
        assert ds.get_effective_speed(t) == pytest.approx(5.0)

    def test_effective_cooldown_unchanged_at_75_percent(self):
        ds = DegradationSystem()
        t = _make_target(health=75.0, max_health=100.0, weapon_cooldown=2.0)
        assert ds.get_effective_cooldown(t) == pytest.approx(2.0)

    def test_effective_speed_unchanged_at_75_percent(self):
        ds = DegradationSystem()
        t = _make_target(health=75.0, max_health=100.0, speed=5.0)
        assert ds.get_effective_speed(t) == pytest.approx(5.0)

    def test_can_fire_at_full_health(self):
        ds = DegradationSystem()
        t = _make_target(health=100.0, max_health=100.0)
        assert ds.can_fire_degraded(t) is True

    def test_can_fire_at_50_percent(self):
        ds = DegradationSystem()
        t = _make_target(health=50.0, max_health=100.0)
        assert ds.can_fire_degraded(t) is True


# ---------------------------------------------------------------------------
# Effective cooldown increases below threshold
# ---------------------------------------------------------------------------

class TestEffectiveCooldown:
    """Cooldown increases as health drops below 50%."""

    def test_cooldown_at_25_percent_health(self):
        """At 25% health, factor=0.5, cooldown_mult = 1.0 + 1.0*0.5 = 1.5."""
        ds = DegradationSystem()
        t = _make_target(health=25.0, max_health=100.0, weapon_cooldown=2.0)
        effective = ds.get_effective_cooldown(t)
        assert effective == pytest.approx(3.0)

    def test_cooldown_at_zero_health(self):
        """At 0% health, factor=0.0, cooldown_mult = 1.0 + 1.0*1.0 = 2.0."""
        ds = DegradationSystem()
        t = _make_target(health=0.0, max_health=100.0, weapon_cooldown=2.0)
        effective = ds.get_effective_cooldown(t)
        assert effective == pytest.approx(4.0)

    def test_cooldown_with_different_base(self):
        ds = DegradationSystem()
        t = _make_target(health=25.0, max_health=100.0, weapon_cooldown=4.0)
        effective = ds.get_effective_cooldown(t)
        # factor=0.5, mult=1.5, effective = 4.0 * 1.5 = 6.0
        assert effective == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# Effective speed reduction below threshold
# ---------------------------------------------------------------------------

class TestEffectiveSpeed:
    """Speed decreases as health drops below 50%."""

    def test_speed_at_25_percent_health(self):
        """At 25% health, factor=0.5, speed_factor = 0.4 + 0.6*0.5 = 0.7."""
        ds = DegradationSystem()
        t = _make_target(health=25.0, max_health=100.0, speed=10.0)
        effective = ds.get_effective_speed(t)
        assert effective == pytest.approx(7.0)

    def test_speed_at_zero_health(self):
        """At 0% health, factor=0.0, speed_factor = 0.4."""
        ds = DegradationSystem()
        t = _make_target(health=0.0, max_health=100.0, speed=10.0)
        effective = ds.get_effective_speed(t)
        assert effective == pytest.approx(4.0)

    def test_speed_at_50_percent(self):
        """At exactly 50% health (threshold), no degradation."""
        ds = DegradationSystem()
        t = _make_target(health=50.0, max_health=100.0, speed=10.0)
        effective = ds.get_effective_speed(t)
        assert effective == pytest.approx(10.0)

    def test_speed_with_different_base(self):
        ds = DegradationSystem()
        t = _make_target(health=25.0, max_health=100.0, speed=5.0)
        effective = ds.get_effective_speed(t)
        assert effective == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Cannot fire below 10% health
# ---------------------------------------------------------------------------

class TestCannotFireLowHealth:
    """Units below 10% health cannot fire."""

    def test_cannot_fire_at_5_percent(self):
        ds = DegradationSystem()
        t = _make_target(health=5.0, max_health=100.0)
        assert ds.can_fire_degraded(t) is False

    def test_cannot_fire_at_zero_health(self):
        ds = DegradationSystem()
        t = _make_target(health=0.0, max_health=100.0)
        assert ds.can_fire_degraded(t) is False

    def test_can_fire_at_10_percent(self):
        """At exactly 10%, can fire (threshold is >=)."""
        ds = DegradationSystem()
        t = _make_target(health=10.0, max_health=100.0)
        assert ds.can_fire_degraded(t) is True

    def test_can_fire_at_11_percent(self):
        ds = DegradationSystem()
        t = _make_target(health=11.0, max_health=100.0)
        assert ds.can_fire_degraded(t) is True

    def test_cannot_fire_at_9_percent(self):
        ds = DegradationSystem()
        t = _make_target(health=9.0, max_health=100.0)
        assert ds.can_fire_degraded(t) is False


# ---------------------------------------------------------------------------
# Tick and reset -- safe no-ops
# ---------------------------------------------------------------------------

class TestTickAndReset:
    """tick() and reset() are safe no-ops."""

    def test_tick_no_error(self):
        ds = DegradationSystem()
        t = _make_target(health=50.0, max_health=100.0)
        # tick takes dt and targets dict
        ds.tick(0.1, {"test-1": t})

    def test_tick_with_empty_targets(self):
        ds = DegradationSystem()
        ds.tick(0.1, {})

    def test_reset_no_error(self):
        ds = DegradationSystem()
        ds.reset()


# ---------------------------------------------------------------------------
# Integration: degraded stats affect gameplay
# ---------------------------------------------------------------------------

class TestIntegration:
    """Verify that degradation mechanics interact correctly."""

    def test_damaged_turret_has_higher_cooldown(self):
        """A turret at 25% health has increased cooldown."""
        ds = DegradationSystem()
        t = _make_target(
            health=25.0, max_health=100.0,
            weapon_cooldown=2.0, asset_type="turret", speed=0.0,
        )
        effective_cd = ds.get_effective_cooldown(t)
        assert effective_cd > 2.0

    def test_damaged_rover_moves_slower(self):
        """A rover at 25% health has reduced speed."""
        ds = DegradationSystem()
        t = _make_target(
            health=25.0, max_health=100.0,
            speed=8.0, asset_type="rover",
        )
        effective_spd = ds.get_effective_speed(t)
        assert effective_spd < 8.0
        assert effective_spd == pytest.approx(5.6)

    def test_critically_damaged_unit_crippled(self):
        """Below 10% health: can't fire, severely reduced speed."""
        ds = DegradationSystem()
        t = _make_target(health=5.0, max_health=100.0, speed=10.0)
        assert ds.can_fire_degraded(t) is False
        # health_frac=0.05, factor=0.1, speed_factor=0.4+0.6*0.1=0.46
        assert ds.get_effective_speed(t) == pytest.approx(4.6)

    def test_gradual_degradation_progression(self):
        """Verify degradation gets worse as health drops below threshold."""
        ds = DegradationSystem()
        t = _make_target(max_health=100.0, weapon_cooldown=2.0, speed=10.0)

        # 100% health: no effects
        t.health = 100.0
        assert ds.get_effective_cooldown(t) == pytest.approx(2.0)
        assert ds.get_effective_speed(t) == pytest.approx(10.0)
        assert ds.can_fire_degraded(t) is True

        # 75% health: still above threshold, no effects
        t.health = 75.0
        assert ds.get_effective_cooldown(t) == pytest.approx(2.0)
        assert ds.get_effective_speed(t) == pytest.approx(10.0)

        # 50% health: at threshold, no effects yet
        t.health = 50.0
        assert ds.get_effective_cooldown(t) == pytest.approx(2.0)
        assert ds.get_effective_speed(t) == pytest.approx(10.0)

        # 25% health: below threshold, degradation kicks in
        t.health = 25.0
        assert ds.get_effective_cooldown(t) > 2.0
        assert ds.get_effective_speed(t) < 10.0

        # 5% health: severe degradation, can't fire
        t.health = 5.0
        assert ds.can_fire_degraded(t) is False
        # health_frac=0.05, factor=0.1, speed_factor=0.4+0.6*0.1=0.46
        assert ds.get_effective_speed(t) == pytest.approx(4.6)
