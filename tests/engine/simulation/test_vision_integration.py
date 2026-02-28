# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for VisionSystem wired into engine, behaviors, combat, and API."""

import math
import pytest

from engine.simulation.target import SimulationTarget
from engine.simulation.terrain import TerrainMap
from engine.simulation.spatial import SpatialGrid
from engine.simulation.combat import CombatSystem
from engine.simulation.behaviors import UnitBehaviors
from engine.simulation.vision import SightingReport, VisibilityState, VisionSystem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str,
    alliance: str = "friendly",
    asset_type: str = "turret",
    position: tuple[float, float] = (0.0, 0.0),
    heading: float = 0.0,
    **kwargs,
) -> SimulationTarget:
    return SimulationTarget(
        target_id=target_id,
        name=target_id,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        heading=heading,
        speed=0.0 if asset_type == "turret" else 2.0,
        is_combatant=alliance != "neutral",
        **kwargs,
    )


def _build_grid(targets: list[SimulationTarget]) -> SpatialGrid:
    grid = SpatialGrid()
    grid.rebuild(targets)
    return grid


def _targets_dict(targets: list[SimulationTarget]) -> dict[str, SimulationTarget]:
    return {t.target_id: t for t in targets}


# ===========================================================================
# TestBehaviorVisionFiltering
# ===========================================================================


class TestBehaviorVisionFiltering:
    """Behaviors should only target visible enemies when vision_state is provided."""

    def test_invisible_enemy_not_targeted(self):
        """Enemy behind turret (not visible) should not be found by _nearest_in_range."""
        # turret heading=0(north), cone_angle=90 => +-45 from north
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        # Enemy directly south at 30m -- outside cone, outside ambient
        enemy = _make_target("h1", "hostile", "person", (0, -30))
        targets = [turret, enemy]
        grid = _build_grid(targets)

        vs = VisionSystem()
        vision_state = vs.tick(0.1, _targets_dict(targets), grid)

        # With vision filtering
        from engine.comms.event_bus import EventBus
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)
        behaviors.set_spatial_grid(grid)

        hostiles = {"h1": enemy}
        result = behaviors._nearest_in_range(turret, hostiles, vision_state=vision_state)
        assert result is None

    def test_visible_enemy_targeted(self):
        """Enemy in front of turret (visible) should be found by _nearest_in_range."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0, weapon_range=50)
        enemy = _make_target("h1", "hostile", "person", (0, 30))  # north, in cone, within weapon_range
        targets = [turret, enemy]
        grid = _build_grid(targets)

        vs = VisionSystem()
        vision_state = vs.tick(0.1, _targets_dict(targets), grid)

        from engine.comms.event_bus import EventBus
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)
        behaviors.set_spatial_grid(grid)

        hostiles = {"h1": enemy}
        result = behaviors._nearest_in_range(turret, hostiles, vision_state=vision_state)
        assert result is not None
        assert result.target_id == "h1"

    def test_fallback_without_vision(self):
        """When vision_state is None, all enemies in range are valid targets (backward compat)."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0, weapon_range=50)
        # Enemy behind turret at 30m -- would be invisible with vision, but visible without
        enemy = _make_target("h1", "hostile", "person", (0, -30))
        targets = [turret, enemy]
        grid = _build_grid(targets)

        from engine.comms.event_bus import EventBus
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)
        behaviors.set_spatial_grid(grid)

        hostiles = {"h1": enemy}
        result = behaviors._nearest_in_range(turret, hostiles, vision_state=None)
        assert result is not None, "Without vision, all in-range enemies should be targetable"

    def test_behavior_tick_with_vision_state(self):
        """Full behaviors.tick() with vision_state filters targeting."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0, weapon_range=50)
        # visible enemy in cone
        e_visible = _make_target("h1", "hostile", "person", (0, 30))
        # invisible enemy behind
        e_invisible = _make_target("h2", "hostile", "person", (0, -30))
        targets = [turret, e_visible, e_invisible]
        grid = _build_grid(targets)

        vs = VisionSystem()
        vision_state = vs.tick(0.1, _targets_dict(targets), grid)

        from engine.comms.event_bus import EventBus
        eb = EventBus()
        combat = CombatSystem(eb)
        behaviors = UnitBehaviors(combat)
        behaviors.set_spatial_grid(grid)

        # Should not crash and should only target visible enemies
        behaviors.tick(0.1, _targets_dict(targets), vision_state=vision_state)


# ===========================================================================
# TestCombatLOSCheck
# ===========================================================================


class TestCombatLOSCheck:
    """Combat.fire() should check LOS when terrain_map is provided."""

    def test_fire_blocked_by_building(self):
        """Projectile is not created when building blocks LOS."""
        terrain = TerrainMap(200.0)
        terrain.set_cell(0, 15, "building")

        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0,
                              weapon_range=50, weapon_cooldown=0.0, last_fired=0.0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))

        from engine.comms.event_bus import EventBus
        eb = EventBus()
        combat = CombatSystem(eb)
        result = combat.fire(turret, enemy, terrain_map=terrain)
        assert result is None, "Shot should be blocked by building"

    def test_clear_los_fire_succeeds(self):
        """Projectile is created when LOS is clear."""
        terrain = TerrainMap(200.0)

        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0,
                              weapon_range=50, weapon_cooldown=0.0, last_fired=0.0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))

        from engine.comms.event_bus import EventBus
        eb = EventBus()
        combat = CombatSystem(eb)
        result = combat.fire(turret, enemy, terrain_map=terrain)
        assert result is not None, "Shot should succeed with clear LOS"

    def test_fire_without_terrain_backward_compat(self):
        """Without terrain_map param, fire() works as before."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0,
                              weapon_range=50, weapon_cooldown=0.0, last_fired=0.0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))

        from engine.comms.event_bus import EventBus
        eb = EventBus()
        combat = CombatSystem(eb)
        result = combat.fire(turret, enemy)
        assert result is not None


# ===========================================================================
# TestTargetFields
# ===========================================================================


class TestTargetFields:
    """SimulationTarget gains visible and detected_by fields."""

    def test_visible_defaults_true(self):
        """New targets are visible by default."""
        t = _make_target("t1", "hostile", "person")
        assert t.visible is True

    def test_detected_by_defaults_empty(self):
        """New targets have empty detected_by."""
        t = _make_target("t1", "hostile", "person")
        assert t.detected_by == []

    def test_to_dict_includes_visible(self):
        """to_dict() includes visible field."""
        t = _make_target("t1", "hostile", "person")
        d = t.to_dict()
        assert "visible" in d
        assert d["visible"] is True

    def test_to_dict_includes_detected_by(self):
        """to_dict() includes detected_by field."""
        t = _make_target("t1", "hostile", "person")
        t.detected_by = ["turret-1", "drone-2"]
        d = t.to_dict()
        assert "detected_by" in d
        assert d["detected_by"] == ["turret-1", "drone-2"]

    def test_visible_can_be_set_false(self):
        """visible flag can be set to False."""
        t = _make_target("t1", "hostile", "person")
        t.visible = False
        assert t.visible is False
        d = t.to_dict()
        assert d["visible"] is False


# ===========================================================================
# TestEngineVisionWiring
# ===========================================================================


class TestEngineVisionWiring:
    """VisionSystem is wired into SimulationEngine tick loop."""

    def test_engine_has_vision_system(self):
        """Engine creates VisionSystem on init."""
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=100)
        assert hasattr(engine, "vision_system")
        assert isinstance(engine.vision_system, VisionSystem)

    def test_engine_vision_ticked_during_game(self):
        """During game_active, engine ticks VisionSystem and updates targets."""
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=100)

        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        engine.add_target(turret)

        # Hostile behind turret -- should be invisible during game
        enemy = _make_target("h1", "hostile", "person", (0, -30))
        engine.add_target(enemy)

        # Set game mode to active
        engine.game_mode.state = "active"

        # Run a tick
        engine._do_tick(0.1)

        # The enemy behind the turret should have visible=False
        t = engine.get_target("h1")
        assert t is not None
        assert t.visible is False

    def test_engine_visible_enemy_stays_visible(self):
        """Hostile in front of turret stays visible during game."""
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=100)

        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        engine.add_target(turret)

        enemy = _make_target("h1", "hostile", "person", (0, 5))  # within ambient range
        engine.add_target(enemy)

        engine.game_mode.state = "active"
        engine._do_tick(0.1)

        t = engine.get_target("h1")
        assert t is not None
        assert t.visible is True


# ===========================================================================
# TestDroneRelayIntegration
# ===========================================================================


class TestDroneRelayIntegration:
    """Drone relay makes relayed targets visible in engine tick."""

    def test_drone_relay_sets_visible(self):
        """Target seen only by drone is visible=True via relay."""
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=200)

        drone = _make_target("d1", "friendly", "drone", (0, 0), heading=0)
        engine.add_target(drone)

        # Turret far away, can't see the enemy
        turret = _make_target("t1", "friendly", "turret", (150, 150), heading=0)
        engine.add_target(turret)

        # Enemy near drone
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        engine.add_target(enemy)

        engine.game_mode.state = "active"
        engine._do_tick(0.1)

        t = engine.get_target("h1")
        assert t is not None
        assert t.visible is True
        assert len(t.detected_by) > 0


# ===========================================================================
# TestSightingEndpoint
# ===========================================================================


class TestSightingEndpoint:
    """POST /api/sighting endpoint integration."""

    @pytest.mark.anyio
    async def test_sighting_endpoint_accepted(self):
        """Sighting report is accepted and forwarded to VisionSystem."""
        from fastapi.testclient import TestClient
        from app.routers.targets_unified import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        # Create a mock simulation engine with vision system
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        eb = EventBus()
        engine = SimulationEngine(eb, map_bounds=100)
        app.state.simulation_engine = engine

        client = TestClient(app)
        response = client.post("/api/sighting", json={
            "observer_id": "cam-front",
            "target_id": "hostile-42",
            "observer_type": "camera",
            "confidence": 0.95,
            "position": [50, 60],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"

    @pytest.mark.anyio
    async def test_sighting_endpoint_no_engine(self):
        """Sighting returns error when no simulation engine."""
        from fastapi.testclient import TestClient
        from app.routers.targets_unified import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/api/sighting", json={
            "observer_id": "cam1",
            "target_id": "h1",
            "observer_type": "camera",
        })
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
