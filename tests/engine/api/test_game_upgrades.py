# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the upgrade/ability API routes (/api/game/upgrade*).

Tests all endpoints: list upgrades, apply upgrade, list abilities, use ability.
Uses FastAPI TestClient with a mocked simulation engine.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, PropertyMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.game import router


def _make_app(engine=None, amy=None):
    """Create a minimal FastAPI app with game router and optional engine/amy."""
    app = FastAPI()
    app.include_router(router)
    app.state.simulation_engine = engine
    app.state.amy = amy
    return app


def _mock_engine(state="setup"):
    """Create a mock SimulationEngine with upgrade_system and game_mode."""
    engine = MagicMock()
    engine.game_mode.state = state
    engine.get_game_state.return_value = {"state": state}
    engine.combat.get_active_projectiles.return_value = []
    return engine


# =========================================================================
# GET /api/game/upgrades
# =========================================================================

@pytest.mark.unit
class TestListUpgrades:
    """GET /api/game/upgrades"""

    def test_returns_upgrade_list(self):
        engine = _mock_engine()
        from engine.simulation.upgrades import Upgrade
        engine.upgrade_system.list_upgrades.return_value = [
            Upgrade("armor_plating", "Armor Plating", "Increase max health by 25%",
                    {"max_health": 1.25}, cost=0, max_stacks=1),
            Upgrade("turbo_motor", "Turbo Motor", "Increase speed by 20%",
                    {"speed": 1.2}, cost=0, max_stacks=1),
        ]
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/upgrades")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["upgrade_id"] == "armor_plating"
        assert data[0]["name"] == "Armor Plating"
        assert data[0]["description"] == "Increase max health by 25%"

    def test_upgrade_has_cost(self):
        engine = _mock_engine()
        from engine.simulation.upgrades import Upgrade
        engine.upgrade_system.list_upgrades.return_value = [
            Upgrade("armor_plating", "Armor Plating", "desc",
                    {"max_health": 1.25}, cost=100),
        ]
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/upgrades")
        data = resp.json()
        assert data[0]["cost"] == 100

    def test_upgrade_has_stat_modifiers(self):
        engine = _mock_engine()
        from engine.simulation.upgrades import Upgrade
        engine.upgrade_system.list_upgrades.return_value = [
            Upgrade("rapid_fire", "Rapid Fire", "desc",
                    {"weapon_cooldown": 0.7}),
        ]
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/upgrades")
        data = resp.json()
        assert data[0]["stat_modifiers"]["weapon_cooldown"] == 0.7

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.get("/api/game/upgrades")
        assert resp.status_code == 503


# =========================================================================
# POST /api/game/upgrade
# =========================================================================

@pytest.mark.unit
class TestApplyUpgrade:
    """POST /api/game/upgrade"""

    def test_apply_upgrade_success(self):
        engine = _mock_engine()
        target = MagicMock()
        target.target_id = "turret-abc"
        target.alliance = "friendly"
        engine.get_target.return_value = target
        engine.upgrade_system.apply_upgrade.return_value = True
        engine.upgrade_system.get_upgrades.return_value = ["armor_plating"]

        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/upgrade", json={
            "unit_id": "turret-abc",
            "upgrade_id": "armor_plating",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "applied"
        assert data["unit_id"] == "turret-abc"
        assert data["upgrade_id"] == "armor_plating"
        engine.upgrade_system.apply_upgrade.assert_called_once()

    def test_apply_upgrade_unknown_unit(self):
        engine = _mock_engine()
        engine.get_target.return_value = None

        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/upgrade", json={
            "unit_id": "nonexistent",
            "upgrade_id": "armor_plating",
        })
        assert resp.status_code == 404

    def test_apply_upgrade_fails(self):
        engine = _mock_engine()
        target = MagicMock()
        target.target_id = "turret-abc"
        target.alliance = "friendly"
        engine.get_target.return_value = target
        engine.upgrade_system.apply_upgrade.return_value = False

        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/upgrade", json={
            "unit_id": "turret-abc",
            "upgrade_id": "armor_plating",
        })
        assert resp.status_code == 400

    def test_422_missing_fields(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/upgrade", json={"unit_id": "turret-abc"})
        assert resp.status_code == 422

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.post("/api/game/upgrade", json={
            "unit_id": "turret-abc",
            "upgrade_id": "armor_plating",
        })
        assert resp.status_code == 503


# =========================================================================
# GET /api/game/abilities
# =========================================================================

@pytest.mark.unit
class TestListAbilities:
    """GET /api/game/abilities"""

    def test_returns_ability_list(self):
        engine = _mock_engine()
        from engine.simulation.upgrades import Ability
        engine.upgrade_system.list_abilities.return_value = [
            Ability("speed_boost", "Speed Boost", "Double speed for 5s",
                    cooldown=30.0, duration=5.0, effect="speed_boost",
                    magnitude=2.0, eligible_types=["rover", "drone"]),
            Ability("emergency_repair", "Emergency Repair", "Restore 30% health",
                    cooldown=60.0, duration=0.0, effect="repair",
                    magnitude=0.3, eligible_types=["rover", "turret"]),
        ]
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/abilities")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["ability_id"] == "speed_boost"
        assert data[0]["cooldown"] == 30.0
        assert data[0]["duration"] == 5.0

    def test_ability_has_eligible_types(self):
        engine = _mock_engine()
        from engine.simulation.upgrades import Ability
        engine.upgrade_system.list_abilities.return_value = [
            Ability("shield", "Energy Shield", "Block 50% damage for 8s",
                    cooldown=45.0, duration=8.0, effect="shield",
                    magnitude=0.5, eligible_types=["turret", "tank"]),
        ]
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/abilities")
        data = resp.json()
        assert data[0]["eligible_types"] == ["turret", "tank"]

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.get("/api/game/abilities")
        assert resp.status_code == 503


# =========================================================================
# POST /api/game/ability
# =========================================================================

@pytest.mark.unit
class TestUseAbility:
    """POST /api/game/ability"""

    def test_use_ability_success(self):
        engine = _mock_engine(state="active")
        target = MagicMock()
        target.target_id = "rover-abc"
        target.alliance = "friendly"
        engine.get_target.return_value = target
        engine.upgrade_system.use_ability.return_value = True
        engine._targets = {"rover-abc": target}

        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/ability", json={
            "unit_id": "rover-abc",
            "ability_id": "speed_boost",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "activated"
        assert data["unit_id"] == "rover-abc"
        assert data["ability_id"] == "speed_boost"

    def test_use_ability_unknown_unit(self):
        engine = _mock_engine(state="active")
        engine.get_target.return_value = None

        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/ability", json={
            "unit_id": "nonexistent",
            "ability_id": "speed_boost",
        })
        assert resp.status_code == 404

    def test_use_ability_fails(self):
        engine = _mock_engine(state="active")
        target = MagicMock()
        target.target_id = "rover-abc"
        target.alliance = "friendly"
        engine.get_target.return_value = target
        engine.upgrade_system.use_ability.return_value = False
        engine._targets = {"rover-abc": target}

        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/ability", json={
            "unit_id": "rover-abc",
            "ability_id": "speed_boost",
        })
        assert resp.status_code == 400

    def test_422_missing_fields(self):
        engine = _mock_engine(state="active")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/ability", json={"unit_id": "rover-abc"})
        assert resp.status_code == 422

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.post("/api/game/ability", json={
            "unit_id": "rover-abc",
            "ability_id": "speed_boost",
        })
        assert resp.status_code == 503


# =========================================================================
# GET /api/game/unit/{unit_id}/upgrades
# =========================================================================

@pytest.mark.unit
class TestGetUnitUpgrades:
    """GET /api/game/unit/{unit_id}/upgrades"""

    def test_returns_unit_upgrades(self):
        engine = _mock_engine()
        target = MagicMock()
        target.target_id = "turret-abc"
        engine.get_target.return_value = target
        engine.upgrade_system.get_upgrades.return_value = ["armor_plating", "rapid_fire"]
        engine.upgrade_system.get_abilities.return_value = ["shield"]
        engine.upgrade_system.get_active_effects.return_value = []
        engine.upgrade_system._ability_cooldowns = {}

        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/unit/turret-abc/upgrades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["unit_id"] == "turret-abc"
        assert "armor_plating" in data["upgrades"]
        assert "rapid_fire" in data["upgrades"]
        assert "shield" in data["abilities"]

    def test_404_unknown_unit(self):
        engine = _mock_engine()
        engine.get_target.return_value = None

        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/unit/nonexistent/upgrades")
        assert resp.status_code == 404
