# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for /api/game/mission/apply response enrichment.

Verifies that the apply endpoint returns a mission_center field
derived from the MissionDirector's _mission_area when available.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_app():
    """Create a test FastAPI app with game router and mock engine."""
    from app.routers.game import router

    app = FastAPI()
    app.include_router(router)

    mock_bus = MagicMock()
    mock_bus.publish = MagicMock()
    mock_bus.subscribe = MagicMock(return_value=MagicMock())

    mock_game_mode = MagicMock()
    mock_game_mode.state = "setup"

    class FreshEngine:
        def __init__(self):
            self.game_mode = mock_game_mode
            self._event_bus = mock_bus
            self.combat = MagicMock()
            self.combat.get_active_projectiles = MagicMock(return_value=[])
            self.add_target = MagicMock()
            self.reset_game = MagicMock()
            self.begin_war = MagicMock()

        def get_game_state(self):
            return {"state": "setup"}

    mock_engine = FreshEngine()
    app.state.simulation_engine = mock_engine
    return app, mock_engine


class TestMissionApplyMissionCenter:
    """Tests that /api/game/mission/apply returns mission_center field."""

    def test_apply_response_has_mission_center_field(self):
        """Apply response should include mission_center (even if null)."""
        app, engine = _create_test_app()
        client = TestClient(app)

        # Generate a scripted scenario first
        client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": False,
        })

        resp = client.post("/api/game/mission/apply")
        assert resp.status_code == 200
        data = resp.json()
        assert "mission_center" in data, "Response must include mission_center field"

    def test_apply_mission_center_null_when_no_area(self):
        """mission_center should be null when MissionDirector has no _mission_area."""
        app, engine = _create_test_app()
        client = TestClient(app)

        # Generate scripted scenario first
        client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": False,
        })

        # Force _mission_area to None (simulates no POI data available)
        engine._mission_director._mission_area = None

        resp = client.post("/api/game/mission/apply")
        data = resp.json()
        assert data["mission_center"] is None, \
            "mission_center should be null when no mission area"

    def test_apply_mission_center_populated_with_area(self):
        """mission_center should contain x, y, lat, lng, radius_m when area exists."""
        from engine.simulation.poi_data import POI, MissionArea

        app, engine = _create_test_app()
        client = TestClient(app)

        # Generate scenario first (creates _mission_director)
        client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": False,
        })

        # Now inject a mock _mission_area onto the cached MissionDirector
        mock_poi = POI(
            name="Test Building",
            poi_type="shop",
            category="shop",
            address="123 Test St",
            lat=37.703,
            lng=-121.934,
            local_x=150.5,
            local_y=-230.2,
        )
        mock_area = MissionArea(
            center_poi=mock_poi,
            radius_m=200.0,
            buildings=[mock_poi],
            streets=["Test Ave"],
            defensive_positions=[(150, -230)],
            approach_routes=["Test Ave"],
        )
        engine._mission_director._mission_area = mock_area

        resp = client.post("/api/game/mission/apply")
        data = resp.json()
        mc = data["mission_center"]

        assert mc is not None, "mission_center should not be null when area exists"
        assert mc["x"] == 150.5, "mission_center x matches center_poi.local_x"
        assert mc["y"] == -230.2, "mission_center y matches center_poi.local_y"
        assert mc["lat"] == 37.703, "mission_center lat matches center_poi.lat"
        assert mc["lng"] == -121.934, "mission_center lng matches center_poi.lng"
        assert mc["radius_m"] == 200.0, "mission_center radius_m matches area.radius_m"

    def test_reset_clears_mission_director_scenario(self):
        """After POST /api/game/reset, the MissionDirector's scenario should be cleared.

        Bug: reset_game() never calls MissionDirector.reset(), so a stale
        scenario persists and can be re-applied after reset.
        """
        app, engine = _create_test_app()
        client = TestClient(app)

        # Generate a scenario
        resp = client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": False,
        })
        assert resp.status_code == 200

        # Verify scenario exists
        resp = client.get("/api/game/mission/current")
        assert resp.json()["status"] == "ready"

        # Reset game
        client.post("/api/game/reset")

        # After reset, scenario should be cleared
        resp = client.get("/api/game/mission/current")
        assert resp.json()["status"] == "none", \
            "MissionDirector scenario should be cleared after game reset"

    def test_apply_after_reset_fails(self):
        """After reset, applying a mission should fail (no scenario)."""
        app, engine = _create_test_app()
        client = TestClient(app)

        # Generate and verify
        client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": False,
        })

        # Apply succeeds
        resp = client.post("/api/game/mission/apply")
        assert resp.status_code == 200

        # Reset
        client.post("/api/game/reset")

        # Apply should now fail
        resp = client.post("/api/game/mission/apply")
        assert resp.status_code == 400, \
            "Should get 400 when applying after reset (no scenario)"

    def test_apply_still_returns_existing_fields(self):
        """Ensure adding mission_center doesn't break existing response fields."""
        app, engine = _create_test_app()
        client = TestClient(app)

        client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": False,
        })

        resp = client.post("/api/game/mission/apply")
        data = resp.json()

        # All existing fields must still be present
        assert data["status"] == "scenario_applied"
        assert "game_mode" in data
        assert "wave_count" in data
        assert "defender_count" in data
        assert "source" in data
        # Plus the new one
        assert "mission_center" in data
