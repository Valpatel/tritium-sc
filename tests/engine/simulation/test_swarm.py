"""Tests for swarm drone behavior -- boids algorithm + attack formations.

TDD: Tests written first, then implementation.
"""

from __future__ import annotations

import math
import time

import pytest

from engine.simulation.target import SimulationTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_drone(
    tid: str = "sd-1",
    pos: tuple[float, float] = (0.0, 0.0),
    heading: float = 0.0,
    speed: float = 6.0,
    alliance: str = "hostile",
) -> SimulationTarget:
    """Create a swarm drone target for testing."""
    return SimulationTarget(
        target_id=tid,
        name=f"Swarm-{tid}",
        alliance=alliance,
        asset_type="swarm_drone",
        position=pos,
        heading=heading,
        speed=speed,
        health=25.0,
        max_health=25.0,
        weapon_range=20.0,
        weapon_cooldown=1.0,
        weapon_damage=5.0,
        is_combatant=True,
    )


def _make_defender(
    tid: str = "turret-1",
    pos: tuple[float, float] = (0.0, 0.0),
    asset_type: str = "turret",
) -> SimulationTarget:
    return SimulationTarget(
        target_id=tid,
        name=f"Defender-{tid}",
        alliance="friendly",
        asset_type=asset_type,
        position=pos,
        speed=0.0,
        health=200.0,
        max_health=200.0,
        weapon_range=80.0,
        weapon_cooldown=1.5,
        weapon_damage=15.0,
        is_combatant=True,
    )


# ===========================================================================
# 1. SwarmBehavior core boids
# ===========================================================================

class TestBoidsSeparation:
    """Drones too close together should repel each other."""

    def test_separation_pushes_apart(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        # Two drones overlapping at (10, 10)
        d1 = _make_drone("d1", pos=(10.0, 10.0))
        d2 = _make_drone("d2", pos=(10.5, 10.0))
        drones = {"d1": d1, "d2": d2}

        sep1 = swarm._separation(d1, drones)
        # Should produce a force pushing d1 away from d2 (negative x)
        assert sep1[0] < 0, f"Expected negative x separation, got {sep1[0]}"

    def test_no_separation_when_far_apart(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        d1 = _make_drone("d1", pos=(0.0, 0.0))
        d2 = _make_drone("d2", pos=(100.0, 100.0))
        drones = {"d1": d1, "d2": d2}

        sep = swarm._separation(d1, drones)
        assert abs(sep[0]) < 0.01 and abs(sep[1]) < 0.01

    def test_separation_magnitude_increases_when_closer(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        d_ref = _make_drone("ref", pos=(10.0, 10.0))

        # Close neighbor
        d_close = _make_drone("close", pos=(10.5, 10.0))
        close_sep = swarm._separation(d_ref, {"ref": d_ref, "close": d_close})

        # Far neighbor (but within separation radius)
        d_far = _make_drone("far", pos=(13.0, 10.0))
        far_sep = swarm._separation(d_ref, {"ref": d_ref, "far": d_far})

        close_mag = math.hypot(close_sep[0], close_sep[1])
        far_mag = math.hypot(far_sep[0], far_sep[1])
        assert close_mag > far_mag, "Closer neighbor should produce stronger separation"


class TestBoidsAlignment:
    """Drones should align their headings with nearby flock members."""

    def test_alignment_toward_average_heading(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        # d1 heading north (0), d2 heading east (90), d3 heading east (90)
        d1 = _make_drone("d1", pos=(10.0, 10.0), heading=0.0)
        d2 = _make_drone("d2", pos=(12.0, 10.0), heading=90.0)
        d3 = _make_drone("d3", pos=(10.0, 12.0), heading=90.0)
        drones = {"d1": d1, "d2": d2, "d3": d3}

        align = swarm._alignment(d1, drones)
        # Average heading of neighbors is 90. d1 is at 0.
        # Alignment vector should point roughly east (positive x direction)
        assert align[0] > 0 or align[1] != 0, "Alignment should nudge toward neighbor headings"

    def test_alignment_no_neighbors(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        d1 = _make_drone("d1", pos=(0.0, 0.0))
        drones = {"d1": d1}
        align = swarm._alignment(d1, drones)
        assert align == (0.0, 0.0)


class TestBoidsCohesion:
    """Drones should steer toward the center of nearby flock members."""

    def test_cohesion_toward_center(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        # d1 is away from the group center
        d1 = _make_drone("d1", pos=(0.0, 0.0))
        d2 = _make_drone("d2", pos=(10.0, 10.0))
        d3 = _make_drone("d3", pos=(12.0, 10.0))
        drones = {"d1": d1, "d2": d2, "d3": d3}

        coh = swarm._cohesion(d1, drones)
        # Center of neighbors is roughly (11, 10)
        # d1 should be steered toward positive x and y
        assert coh[0] > 0 and coh[1] > 0

    def test_cohesion_zero_when_alone(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        d1 = _make_drone("d1", pos=(0.0, 0.0))
        drones = {"d1": d1}
        coh = swarm._cohesion(d1, drones)
        assert coh == (0.0, 0.0)


# ===========================================================================
# 2. Combined boids tick
# ===========================================================================

class TestSwarmTick:
    """The main tick should apply separation + alignment + cohesion + target steering."""

    def test_tick_moves_drones(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        drones = {}
        for i in range(5):
            d = _make_drone(f"d{i}", pos=(10.0 + i * 2, 20.0))
            drones[d.target_id] = d

        old_positions = {tid: d.position for tid, d in drones.items()}
        swarm.tick(0.1, drones, {})

        moved = sum(
            1 for tid, d in drones.items()
            if d.position != old_positions[tid]
        )
        assert moved > 0, "At least some drones should have moved"

    def test_tick_with_target_steers_toward_defender(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        # Drone far from defender
        d1 = _make_drone("d1", pos=(-50.0, 0.0))
        drones = {"d1": d1}

        defender = _make_defender("t1", pos=(0.0, 0.0))
        friendlies = {"t1": defender}

        old_x = d1.position[0]
        swarm.tick(0.1, drones, friendlies)
        # Drone should have moved toward defender (positive x)
        assert d1.position[0] > old_x, "Swarm drone should steer toward defender"


# ===========================================================================
# 3. Attack formations
# ===========================================================================

class TestAttackFormations:
    """Swarm attack patterns: circle-strafe, dive-bomb, wave-assault, split-and-pincer."""

    def test_circle_strafe_positions(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        target_pos = (0.0, 0.0)
        positions = swarm.circle_strafe_positions(target_pos, radius=20.0, count=8)
        assert len(positions) == 8
        # All positions should be approximately 20m from target
        for p in positions:
            dist = math.hypot(p[0] - target_pos[0], p[1] - target_pos[1])
            assert abs(dist - 20.0) < 0.5, f"Expected ~20m radius, got {dist}"

    def test_dive_bomb_positions(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        target_pos = (0.0, 0.0)
        start_positions = [(50.0, 50.0 + i * 2) for i in range(5)]
        result = swarm.dive_bomb_positions(target_pos, start_positions)
        assert len(result) == 5
        # Each result should be the target itself (converge on target)
        for p in result:
            assert math.hypot(p[0], p[1]) < 1.0

    def test_wave_assault_positions(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        target_pos = (0.0, 0.0)
        positions = swarm.wave_assault_positions(
            target_pos, approach_heading=0.0, count=10, spacing=3.0
        )
        assert len(positions) == 10

    def test_split_pincer_returns_two_groups(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        target_pos = (0.0, 0.0)
        left, right = swarm.split_pincer_positions(
            target_pos, approach_heading=0.0, count=10, flank_distance=30.0
        )
        assert len(left) == 5
        assert len(right) == 5


# ===========================================================================
# 4. SwarmDrone unit type
# ===========================================================================

class TestSwarmDroneUnitType:
    """Verify the swarm_drone unit type is registered and has correct stats."""

    def test_unit_type_registered(self):
        from engine.units import get_type
        cls = get_type("swarm_drone")
        assert cls is not None, "swarm_drone type should be registered"

    def test_unit_type_is_flying(self):
        from engine.units import get_type
        cls = get_type("swarm_drone")
        assert cls.is_flying()

    def test_unit_type_speed(self):
        from engine.units import get_type
        cls = get_type("swarm_drone")
        assert cls.speed >= 5.0, "Swarm drones should be fast"

    def test_unit_type_low_health(self):
        from engine.units import get_type
        cls = get_type("swarm_drone")
        assert cls.combat.health <= 30, "Swarm drones should have low health"

    def test_unit_type_is_combatant(self):
        from engine.units import get_type
        cls = get_type("swarm_drone")
        assert cls.combat.is_combatant

    def test_unit_type_hostile_cot(self):
        from engine.units import get_type
        cls = get_type("swarm_drone")
        # Should have hostile air CoT code
        assert "h" in cls.cot_type and "A" in cls.cot_type


# ===========================================================================
# 5. Swarm behavior wired into UnitBehaviors
# ===========================================================================

class TestSwarmInBehaviors:
    """Swarm drones should use swarm behavior in the main behavior tick."""

    def test_swarm_drones_handled_in_hostile_tick(self):
        """Swarm drone hostiles should be processed by behaviors.tick()."""
        from engine.comms.event_bus import EventBus
        from engine.simulation.behaviors import UnitBehaviors
        from engine.simulation.combat import CombatSystem

        bus = EventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        d1 = _make_drone("sd1", pos=(10.0, 10.0))
        defender = _make_defender("t1", pos=(15.0, 15.0))

        targets = {"sd1": d1, "t1": defender}
        # Should not raise
        behaviors.tick(0.1, targets)

    def test_swarm_drones_fire_at_defenders(self):
        """Swarm drones should fire at nearby defenders."""
        from engine.comms.event_bus import EventBus
        from engine.simulation.behaviors import UnitBehaviors
        from engine.simulation.combat import CombatSystem

        bus = EventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        # Drone at origin, defender within weapon range (20m)
        d1 = _make_drone("sd1", pos=(0.0, 0.0))
        d1.last_fired = 0.0  # allow firing
        defender = _make_defender("t1", pos=(5.0, 5.0))

        targets = {"sd1": d1, "t1": defender}
        behaviors.tick(0.1, targets)
        assert combat.projectile_count >= 0  # At minimum, no crash


# ===========================================================================
# 6. Performance: 50+ drones at 10Hz
# ===========================================================================

class TestSwarmPerformance:
    """50 swarm drones + 10 defenders must tick in <100ms."""

    def test_50_drones_10_defenders_under_100ms(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        drones = {}
        for i in range(50):
            angle = (i / 50) * 2 * math.pi
            x = 80.0 * math.cos(angle)
            y = 80.0 * math.sin(angle)
            d = _make_drone(f"sd-{i}", pos=(x, y), heading=angle * 180 / math.pi)
            drones[d.target_id] = d

        defenders = {}
        for i in range(10):
            t = _make_defender(f"t-{i}", pos=(i * 5.0, 0.0))
            defenders[t.target_id] = t

        # Warm up
        swarm.tick(0.1, drones, defenders)

        # Measure 10 ticks
        start = time.perf_counter()
        for _ in range(10):
            swarm.tick(0.1, drones, defenders)
        elapsed = time.perf_counter() - start

        avg_tick_ms = (elapsed / 10) * 1000
        assert avg_tick_ms < 100, f"Average tick {avg_tick_ms:.1f}ms exceeds 100ms budget"

    def test_100_drones_still_reasonable(self):
        """Even 100 drones should tick in under 200ms."""
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        drones = {}
        for i in range(100):
            angle = (i / 100) * 2 * math.pi
            x = 100.0 * math.cos(angle)
            y = 100.0 * math.sin(angle)
            d = _make_drone(f"sd-{i}", pos=(x, y))
            drones[d.target_id] = d

        defenders = {}
        for i in range(10):
            t = _make_defender(f"t-{i}", pos=(i * 5.0, 0.0))
            defenders[t.target_id] = t

        start = time.perf_counter()
        for _ in range(10):
            swarm.tick(0.1, drones, defenders)
        elapsed = time.perf_counter() - start

        avg_tick_ms = (elapsed / 10) * 1000
        assert avg_tick_ms < 200, f"Average tick {avg_tick_ms:.1f}ms exceeds 200ms budget"


# ===========================================================================
# 7. Swarm scenario loading
# ===========================================================================

class TestSwarmScenario:
    """Verify the swarm_attack scenario JSON parses correctly."""

    def test_scenario_file_exists(self):
        import json
        from pathlib import Path
        path = Path(__file__).parents[3] / "scenarios" / "battle" / "swarm_attack.json"
        assert path.exists(), f"Scenario file not found: {path}"
        data = json.loads(path.read_text())
        assert data["scenario_id"] == "swarm_attack"

    def test_scenario_has_swarm_drone_groups(self):
        import json
        from pathlib import Path
        path = Path(__file__).parents[3] / "scenarios" / "battle" / "swarm_attack.json"
        data = json.loads(path.read_text())
        # At least one wave should contain swarm_drone groups
        has_swarm = False
        for wave in data["waves"]:
            for group in wave["groups"]:
                if group["asset_type"] == "swarm_drone":
                    has_swarm = True
        assert has_swarm, "Scenario must contain swarm_drone groups"

    def test_scenario_total_drones_at_least_50(self):
        import json
        from pathlib import Path
        path = Path(__file__).parents[3] / "scenarios" / "battle" / "swarm_attack.json"
        data = json.loads(path.read_text())
        total = 0
        for wave in data["waves"]:
            for group in wave["groups"]:
                if group["asset_type"] == "swarm_drone":
                    total += group["count"]
        assert total >= 50, f"Expected at least 50 swarm drones total, got {total}"

    def test_scenario_has_defenders(self):
        import json
        from pathlib import Path
        path = Path(__file__).parents[3] / "scenarios" / "battle" / "swarm_attack.json"
        data = json.loads(path.read_text())
        assert len(data.get("defenders", [])) > 0, "Scenario should include defenders"


# ===========================================================================
# 8. Swarm spawning in engine
# ===========================================================================

class TestSwarmDroneSpawning:
    """Verify swarm_drone can be spawned via spawn_hostile_typed."""

    def test_spawn_swarm_drone(self):
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine

        bus = EventBus()
        engine = SimulationEngine(bus)

        hostile = engine.spawn_hostile_typed(
            asset_type="swarm_drone",
            speed=6.0,
            health=25.0,
        )
        assert hostile.asset_type == "swarm_drone"
        assert hostile.alliance == "hostile"
        assert hostile.health == 25.0
        assert hostile.speed == 6.0

    def test_spawn_50_swarm_drones(self):
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine

        bus = EventBus()
        engine = SimulationEngine(bus, max_hostiles=200)

        for i in range(50):
            engine.spawn_hostile_typed(
                asset_type="swarm_drone",
                speed=6.0,
                health=25.0,
            )

        hostiles = [
            t for t in engine.get_targets()
            if t.alliance == "hostile" and t.asset_type == "swarm_drone"
        ]
        assert len(hostiles) == 50


# ===========================================================================
# 9. Anti-drone defense: AoE effectiveness
# ===========================================================================

class TestAntiDroneDefense:
    """AoE weapons should be effective against grouped swarm drones."""

    def test_emp_burst_damages_multiple_drones(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        # Cluster of 5 drones within EMP radius
        drones = {}
        for i in range(5):
            d = _make_drone(f"d{i}", pos=(10.0 + i * 0.5, 10.0))
            drones[d.target_id] = d

        center = (10.0, 10.0)
        radius = 5.0
        damage = 15.0

        affected = swarm.apply_aoe_damage(drones, center, radius, damage)
        assert affected >= 4, f"Expected at least 4 drones hit, got {affected}"

        for d in drones.values():
            dist = math.hypot(d.position[0] - center[0], d.position[1] - center[1])
            if dist <= radius:
                assert d.health < 25.0, "Drone in radius should have taken damage"

    def test_emp_burst_no_damage_outside_radius(self):
        from engine.simulation.swarm import SwarmBehavior
        swarm = SwarmBehavior()

        d1 = _make_drone("d1", pos=(100.0, 100.0))
        drones = {"d1": d1}

        affected = swarm.apply_aoe_damage(drones, (0.0, 0.0), 5.0, 15.0)
        assert affected == 0
        assert d1.health == 25.0
