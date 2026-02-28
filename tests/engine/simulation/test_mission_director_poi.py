"""Tests for POI data wired into MissionDirector.

Validates that MissionDirector uses real POI data (buildings, streets,
addresses) from poi_data module to generate building-centric missions
instead of polar-coordinate random placements.

All tests mock fetch_pois -- NO real network calls.
"""

import math
import pytest
from unittest.mock import MagicMock, patch

from engine.simulation.poi_data import POI, MissionArea


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

DUBLIN_CENTER = (37.7159, -121.8960)

# Fake POI data representing Dublin, CA neighborhood
FAKE_POIS = [
    POI(
        name="Dublin Library",
        poi_type="library",
        category="amenity",
        address="200 Civic Plaza",
        lat=37.7155,
        lng=-121.8955,
        local_x=-44.2,
        local_y=-44.5,
        osm_id=1001,
    ),
    POI(
        name="Circle K",
        poi_type="convenience",
        category="shop",
        address="7850 Amador Valley Blvd",
        lat=37.7162,
        lng=-121.8948,
        local_x=106.1,
        local_y=33.4,
        osm_id=1002,
    ),
    POI(
        name="Dublin Elementary",
        poi_type="school",
        category="amenity",
        address="600 Donlon Way",
        lat=37.7170,
        lng=-121.8970,
        local_x=-88.5,
        local_y=122.3,
        osm_id=1003,
    ),
    POI(
        name="7-Eleven",
        poi_type="convenience",
        category="shop",
        address="7200 San Ramon Rd",
        lat=37.7145,
        lng=-121.8940,
        local_x=176.8,
        local_y=-155.7,
        osm_id=1004,
    ),
    POI(
        name="Amador Valley Blvd",
        poi_type="residential",
        category="street",
        address="",
        lat=37.7160,
        lng=-121.8950,
        local_x=88.5,
        local_y=11.1,
        osm_id=2001,
    ),
    POI(
        name="San Ramon Rd",
        poi_type="tertiary",
        category="street",
        address="",
        lat=37.7155,
        lng=-121.8945,
        local_x=132.7,
        local_y=-44.5,
        osm_id=2002,
    ),
]


def _make_bus():
    return MagicMock()


def _make_director(**kwargs):
    from engine.simulation.mission_director import MissionDirector
    defaults = {"event_bus": _make_bus()}
    defaults.update(kwargs)
    return defaults.pop("event_bus"), __import__(
        "engine.simulation.mission_director", fromlist=["MissionDirector"]
    ).MissionDirector(event_bus=defaults.get("event_bus_override", _make_bus()), **kwargs)


# ---------------------------------------------------------------------------
# TestMissionDirectorInit
# ---------------------------------------------------------------------------

class TestMissionDirectorInit:
    """MissionDirector accepts and stores map_center."""

    def test_accepts_map_center(self):
        from engine.simulation.mission_director import MissionDirector
        bus = _make_bus()
        md = MissionDirector(event_bus=bus, map_center=(37.7159, -121.8960))
        assert md._map_center == (37.7159, -121.8960)

    def test_defaults_to_dublin(self):
        from engine.simulation.mission_director import MissionDirector
        bus = _make_bus()
        md = MissionDirector(event_bus=bus)
        assert md._map_center == (37.7159, -121.8960)

    def test_map_center_none_uses_default(self):
        from engine.simulation.mission_director import MissionDirector
        bus = _make_bus()
        md = MissionDirector(event_bus=bus, map_center=None)
        assert md._map_center == (37.7159, -121.8960)

    def test_mission_area_initially_none(self):
        from engine.simulation.mission_director import MissionDirector
        bus = _make_bus()
        md = MissionDirector(event_bus=bus)
        assert md._mission_area is None

    def test_custom_map_center(self):
        from engine.simulation.mission_director import MissionDirector
        bus = _make_bus()
        md = MissionDirector(event_bus=bus, map_center=(40.0, -74.0))
        assert md._map_center == (40.0, -74.0)


# ---------------------------------------------------------------------------
# TestPrepareMissionArea
# ---------------------------------------------------------------------------

class TestPrepareMissionArea:
    """_prepare_mission_area calls fetch_pois, pick_mission_center, build_mission_area."""

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_loads_pois_from_map_center(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("battle")
        mock_fetch.assert_called_once()
        args, kwargs = mock_fetch.call_args
        assert args[0] == pytest.approx(37.7159, abs=0.01)
        assert args[1] == pytest.approx(-121.896, abs=0.01)

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_sets_mission_area(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("battle")
        assert md._mission_area is not None
        assert isinstance(md._mission_area, MissionArea)

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_mission_area_has_center_poi(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("battle")
        assert md._mission_area.center_poi is not None
        assert md._mission_area.center_poi.name != ""

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_battle_radius_200(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("battle")
        assert md._mission_area.radius_m == 200

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_defense_radius_150(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("defense")
        assert md._mission_area.radius_m == 150

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_patrol_radius_300(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("patrol")
        assert md._mission_area.radius_m == 300

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_escort_radius_400(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("escort")
        assert md._mission_area.radius_m == 400


# ---------------------------------------------------------------------------
# TestScriptedWithRealBuildings
# ---------------------------------------------------------------------------

class TestScriptedWithRealBuildings:
    """Scripted generation uses place_defenders_around_buildings when POIs available."""

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_scripted_generates_with_poi(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        assert "units" in scenario
        assert len(scenario["units"]) >= 1

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_scripted_units_have_positions(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        for unit in scenario["units"]:
            assert "position" in unit
            pos = unit["position"]
            assert len(pos) == 2
            assert isinstance(pos[0], (int, float))
            assert isinstance(pos[1], (int, float))

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_scripted_units_have_alliance(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        for unit in scenario["units"]:
            assert unit.get("alliance") == "friendly"


# ---------------------------------------------------------------------------
# TestDefenderNaming
# ---------------------------------------------------------------------------

class TestDefenderNaming:
    """Defender names reference building or street names when POIs available."""

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_defender_names_not_generic(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        names = [u["name"] for u in scenario["units"]]
        # At least some names should contain a real POI name or street name
        poi_names = {p.name for p in FAKE_POIS}
        has_real_name = any(
            any(pn in name for pn in poi_names)
            for name in names
        )
        assert has_real_name, f"Expected real POI names in unit names, got: {names}"

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_defender_names_are_strings(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        for unit in scenario["units"]:
            assert isinstance(unit["name"], str)
            assert len(unit["name"]) > 0


# ---------------------------------------------------------------------------
# TestDefendersWithinRadius
# ---------------------------------------------------------------------------

class TestDefendersWithinRadius:
    """All placed defenders should be within the combat radius."""

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_all_defenders_within_radius(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        # After generation, mission_area should be set
        assert md._mission_area is not None
        radius = md._mission_area.radius_m
        cx = md._mission_area.center_poi.local_x
        cy = md._mission_area.center_poi.local_y
        for unit in scenario["units"]:
            pos = unit["position"]
            dist = math.hypot(pos[0] - cx, pos[1] - cy)
            # Allow 10% tolerance (placement jitter + snapping)
            assert dist <= radius * 1.1 + 20, \
                f"Unit {unit['name']} at ({pos[0]:.1f}, {pos[1]:.1f}) " \
                f"is {dist:.1f}m from center, radius={radius}m"


# ---------------------------------------------------------------------------
# TestLLMPromptsIncludePOI
# ---------------------------------------------------------------------------

class TestLLMPromptsIncludePOI:
    """LLM prompts contain building names when POI data is available."""

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_llm_prompt_includes_poi_context(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("battle")
        # build_prompt should include POI context
        prompt = md.build_prompt("scenario_context", game_mode="battle")
        # The prompt should contain at least some POI info
        # (center building name or "West Dublin" or similar)
        center_name = md._mission_area.center_poi.name
        assert center_name in prompt or "Dublin" in prompt or "MISSION CENTER" in prompt, \
            f"Expected POI context in prompt, got: {prompt[:300]}"

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_unit_composition_prompt_includes_poi(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("battle")
        prompt = md.build_prompt("unit_composition", game_mode="battle")
        # Should mention buildings or addresses
        has_poi = any(
            p.name in prompt for p in FAKE_POIS if p.category != "street"
        ) or "building" in prompt.lower() or "MISSION CENTER" in prompt
        assert has_poi, f"Expected building names in unit_composition prompt: {prompt[:300]}"


# ---------------------------------------------------------------------------
# TestScriptedContextTemplates
# ---------------------------------------------------------------------------

class TestScriptedContextTemplates:
    """Scripted context narratives reference real center building."""

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_context_includes_center_name(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        ctx = scenario.get("scenario_context", {})
        # Context should reference real location somehow
        ctx_text = str(ctx)
        center_name = md._mission_area.center_poi.name
        has_location = center_name in ctx_text or "Dublin" in ctx_text
        assert has_location, \
            f"Expected real location in context, got: {ctx_text[:200]}"

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_context_includes_streets(self, mock_fetch):
        """At least one of the templates references streets; run multiple times to hit it."""
        from engine.simulation.mission_director import MissionDirector
        street_names = [p.name for p in FAKE_POIS if p.category == "street"]
        found_street = False
        for _ in range(20):
            md = MissionDirector(event_bus=_make_bus())
            scenario = md.generate_scripted(game_mode="battle")
            ctx = scenario.get("scenario_context", {})
            ctx_text = str(ctx)
            if any(s in ctx_text for s in street_names) or "Blvd" in ctx_text or "Rd" in ctx_text:
                found_street = True
                break
        assert found_street, \
            f"Expected at least one template to reference streets after 20 tries"


# ---------------------------------------------------------------------------
# TestFallbackWithoutPOIs
# ---------------------------------------------------------------------------

class TestFallbackWithoutPOIs:
    """When fetch_pois fails/returns empty, scripted still works with polar fallback."""

    @patch("engine.simulation.mission_director.fetch_pois", return_value=[])
    def test_scripted_works_with_empty_pois(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        assert "units" in scenario
        assert len(scenario["units"]) >= 3

    @patch("engine.simulation.mission_director.fetch_pois", side_effect=Exception("network down"))
    def test_scripted_works_when_fetch_raises(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        assert "units" in scenario
        assert len(scenario["units"]) >= 3
        assert "scenario_context" in scenario

    @patch("engine.simulation.mission_director.fetch_pois", return_value=[])
    def test_fallback_uses_polar_positions(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        # When no POIs, positions should still be numeric
        for unit in scenario["units"]:
            pos = unit["position"]
            assert isinstance(pos[0], (int, float))
            assert isinstance(pos[1], (int, float))

    @patch("engine.simulation.mission_director.fetch_pois", return_value=[])
    def test_fallback_still_has_win_conditions(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        assert "win_conditions" in scenario

    @patch("engine.simulation.mission_director.fetch_pois", return_value=[])
    def test_mission_area_none_after_empty_pois(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        md._prepare_mission_area("battle")
        # With empty POIs, mission_area should remain None (no center to pick)
        assert md._mission_area is None


# ---------------------------------------------------------------------------
# TestOllamaSystemPromptDublin
# ---------------------------------------------------------------------------

class TestOllamaSystemPromptDublin:
    """_call_ollama system prompt should mention West Dublin, California."""

    def test_system_prompt_mentions_dublin(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        # We cannot easily inspect the system prompt without calling _call_ollama,
        # but we can mock requests and capture the payload
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": '{"test": true}'}}
        mock_resp.raise_for_status = MagicMock()
        with patch("engine.simulation.mission_director.requests") as mock_req:
            mock_req.post.return_value = mock_resp
            try:
                md._call_ollama("test prompt", "gemma3:4b")
            except Exception:
                pass
            if mock_req.post.called:
                call_kwargs = mock_req.post.call_args
                payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
                messages = payload.get("messages", [])
                system_msg = next((m for m in messages if m["role"] == "system"), None)
                assert system_msg is not None
                assert "Dublin" in system_msg["content"] or "dublin" in system_msg["content"].lower(), \
                    f"System prompt should mention Dublin: {system_msg['content'][:200]}"


# ---------------------------------------------------------------------------
# TestScenarioToBattleScenarioWithPOI
# ---------------------------------------------------------------------------

class TestScenarioToBattleScenarioWithPOI:
    """scenario_to_battle_scenario uses mission_area radius for map_bounds."""

    @patch("engine.simulation.mission_director.fetch_pois", return_value=FAKE_POIS)
    def test_map_bounds_from_mission_area(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        # map_bounds should match the mission_area radius
        assert bs.map_bounds == md._mission_area.radius_m

    @patch("engine.simulation.mission_director.fetch_pois", return_value=[])
    def test_map_bounds_default_without_poi(self, mock_fetch):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=_make_bus())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        # Without POIs, should use default 200.0
        assert bs.map_bounds == 200.0


# ---------------------------------------------------------------------------
# TestLoadingMessagesDublin
# ---------------------------------------------------------------------------

class TestLoadingMessagesDublin:
    """Loading messages should reference Dublin/neighborhood."""

    def test_loading_messages_have_dublin_references(self):
        from engine.simulation.mission_director import _SCRIPTED_LOADING
        loading_text = " ".join(_SCRIPTED_LOADING)
        # After wiring, loading messages should reference the neighborhood
        has_neighborhood = (
            "neighborhood" in loading_text.lower()
            or "dublin" in loading_text.lower()
            or "perimeter" in loading_text.lower()
            or "street" in loading_text.lower()
            or "satellite" in loading_text.lower()
        )
        assert has_neighborhood, \
            f"Loading messages should reference neighborhood: {loading_text[:200]}"
