"""Tests for unified LLM-driven mission director.

The MissionDirector orchestrates scenario generation via Ollama LLM:
1. Selects game mode (battle, defense, patrol, custom)
2. Generates scenario context (why, who, stakes, weather)
3. Determines unit composition and placement
4. Assigns motives and objectives to all units
5. Sets win/loss conditions
6. Streams generation progress events

Each step uses structured JSON prompts to the LLM with scripted fallbacks.
The entire flow is observable via EventBus events for the frontend modal.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, call


# -- Import tests ----------------------------------------------------------

class TestMissionDirectorImport:
    def test_import(self):
        from engine.simulation.mission_director import MissionDirector
        assert MissionDirector is not None

    def test_create(self):
        from engine.simulation.mission_director import MissionDirector
        bus = MagicMock()
        md = MissionDirector(event_bus=bus)
        assert md is not None

    def test_default_model(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        assert md.model == "gemma3:4b"

    def test_custom_model(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock(), model="qwen2.5:7b")
        assert md.model == "qwen2.5:7b"


# -- Game mode prompts -----------------------------------------------------

class TestGameModePrompts:
    """Test that game mode prompt templates exist and are valid."""

    def test_game_modes_defined(self):
        from engine.simulation.mission_director import GAME_MODES
        assert "battle" in GAME_MODES
        assert "defense" in GAME_MODES
        assert "patrol" in GAME_MODES

    def test_game_mode_has_required_fields(self):
        from engine.simulation.mission_director import GAME_MODES
        for name, mode in GAME_MODES.items():
            assert "description" in mode, f"{name} missing description"
            assert "prompt" in mode, f"{name} missing prompt"
            assert "default_waves" in mode, f"{name} missing default_waves"

    def test_game_mode_prompts_request_json(self):
        from engine.simulation.mission_director import GAME_MODES
        for name, mode in GAME_MODES.items():
            assert "json" in mode["prompt"].lower() or "JSON" in mode["prompt"], \
                f"{name} prompt does not request JSON output"


# -- Generation steps -------------------------------------------------------

class TestGenerationSteps:
    """Test the step-by-step generation pipeline."""

    def test_steps_defined(self):
        from engine.simulation.mission_director import GENERATION_STEPS
        assert len(GENERATION_STEPS) >= 5
        for step in GENERATION_STEPS:
            assert "id" in step
            assert "prompt_template" in step
            assert "label" in step

    def test_step_ids_unique(self):
        from engine.simulation.mission_director import GENERATION_STEPS
        ids = [s["id"] for s in GENERATION_STEPS]
        assert len(ids) == len(set(ids))


# -- Scripted fallback generation -------------------------------------------

class TestScriptedGeneration:
    """Test that scripted fallback produces a complete scenario."""

    def test_generate_scripted_scenario(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        assert isinstance(scenario, dict)
        assert "game_mode" in scenario
        assert "scenario_context" in scenario
        assert "units" in scenario
        assert "win_conditions" in scenario

    def test_scripted_has_units(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        units = scenario["units"]
        assert isinstance(units, list)
        assert len(units) >= 3  # At least some defenders

    def test_scripted_units_have_required_fields(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        for unit in scenario["units"]:
            assert "type" in unit
            assert "alliance" in unit
            assert "position" in unit

    def test_scripted_has_win_conditions(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        wc = scenario["win_conditions"]
        assert "victory" in wc
        assert "defeat" in wc

    def test_scripted_defense_mode(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="defense")
        assert scenario["game_mode"] == "defense"
        assert len(scenario["units"]) >= 2

    def test_scripted_patrol_mode(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="patrol")
        assert scenario["game_mode"] == "patrol"

    def test_scripted_different_modes_different_units(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        battle = md.generate_scripted(game_mode="battle")
        patrol = md.generate_scripted(game_mode="patrol")
        # Different modes produce different unit counts
        assert battle["units"] != patrol["units"] or \
            battle["win_conditions"] != patrol["win_conditions"]


# -- Progress events ---------------------------------------------------------

class TestProgressEvents:
    """Test that generation emits progress events for the frontend modal."""

    def test_scripted_emits_progress(self):
        from engine.simulation.mission_director import MissionDirector
        bus = MagicMock()
        md = MissionDirector(event_bus=bus)
        md.generate_scripted(game_mode="battle")
        # Should have published progress events
        calls = [c for c in bus.publish.call_args_list
                 if c[0][0] == "mission_progress"]
        assert len(calls) >= 3  # At least start, steps, complete

    def test_progress_has_step_info(self):
        from engine.simulation.mission_director import MissionDirector
        bus = MagicMock()
        md = MissionDirector(event_bus=bus)
        md.generate_scripted(game_mode="battle")
        calls = [c for c in bus.publish.call_args_list
                 if c[0][0] == "mission_progress"]
        # First call should be start event
        first = calls[0][0][1]
        assert "step" in first or "status" in first

    def test_progress_includes_prompts_and_responses(self):
        """Progress events should include what was prompted and what came back."""
        from engine.simulation.mission_director import MissionDirector
        bus = MagicMock()
        md = MissionDirector(event_bus=bus)
        md.generate_scripted(game_mode="battle")
        calls = [c for c in bus.publish.call_args_list
                 if c[0][0] == "mission_progress"]
        # At least one step should have prompt/response info
        step_events = [c[0][1] for c in calls if c[0][1].get("status") == "step_complete"]
        assert len(step_events) >= 1
        for ev in step_events:
            assert "label" in ev
            assert "result" in ev

    def test_final_event_has_scenario(self):
        from engine.simulation.mission_director import MissionDirector
        bus = MagicMock()
        md = MissionDirector(event_bus=bus)
        md.generate_scripted(game_mode="battle")
        calls = [c for c in bus.publish.call_args_list
                 if c[0][0] == "mission_progress"]
        last = calls[-1][0][1]
        assert last.get("status") == "complete"
        assert "scenario" in last


# -- LLM prompt building ---------------------------------------------------

class TestLLMPromptBuilding:
    """Test building prompts for the LLM."""

    def test_build_scenario_prompt(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        prompt = md.build_prompt("scenario_context", game_mode="battle")
        assert isinstance(prompt, str)
        assert len(prompt) > 20
        assert "json" in prompt.lower() or "JSON" in prompt

    def test_build_unit_composition_prompt(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        prompt = md.build_prompt("unit_composition", game_mode="battle")
        assert isinstance(prompt, str)
        assert len(prompt) > 20

    def test_build_win_conditions_prompt(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        prompt = md.build_prompt("win_conditions", game_mode="battle")
        assert isinstance(prompt, str)


# -- LLM response parsing ---------------------------------------------------

class TestLLMResponseParsing:
    """Test parsing structured JSON from LLM responses."""

    def test_parse_valid_json(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        raw = '{"reason": "Gang turf war", "urgency": "high"}'
        result = md.parse_llm_response(raw, step_id="scenario_context")
        assert result is not None
        assert result["reason"] == "Gang turf war"

    def test_parse_json_with_markdown(self):
        """LLMs often wrap JSON in markdown code blocks."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        raw = '```json\n{"reason": "Retaliation strike"}\n```'
        result = md.parse_llm_response(raw, step_id="scenario_context")
        assert result is not None
        assert result["reason"] == "Retaliation strike"

    def test_parse_invalid_json_returns_none(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        raw = "This is not valid JSON at all"
        result = md.parse_llm_response(raw, step_id="scenario_context")
        assert result is None

    def test_parse_unit_list(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        raw = json.dumps({
            "defenders": [
                {"type": "turret", "position": [10, 20], "name": "Alpha"},
                {"type": "rover", "position": [30, 40], "name": "Bravo"},
            ],
            "hostiles": [
                {"type": "person", "position": [80, 80], "count": 3},
            ]
        })
        result = md.parse_llm_response(raw, step_id="unit_composition")
        assert result is not None
        assert "defenders" in result


# -- Unit placement from scenario -------------------------------------------

class TestUnitPlacement:
    """Test converting a scenario into engine targets."""

    def test_scenario_to_targets(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        targets = md.scenario_to_targets(scenario)
        assert isinstance(targets, list)
        assert len(targets) >= 3

    def test_targets_have_positions(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        targets = md.scenario_to_targets(scenario)
        for t in targets:
            assert "position" in t
            assert len(t["position"]) == 2

    def test_targets_have_alliance(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        targets = md.scenario_to_targets(scenario)
        alliances = {t["alliance"] for t in targets}
        assert "friendly" in alliances


# -- get_current / reset ---------------------------------------------------

class TestState:
    def test_get_current_none_initially(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        assert md.get_current_scenario() is None

    def test_get_current_after_generate(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        md.generate_scripted(game_mode="battle")
        assert md.get_current_scenario() is not None

    def test_reset_clears(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        md.generate_scripted(game_mode="battle")
        md.reset()
        assert md.get_current_scenario() is None


# -- Available models -------------------------------------------------------

class TestModelDiscovery:
    """Test discovering available Ollama models."""

    def test_list_available_models_offline(self):
        """When Ollama is unavailable, return empty list."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        with patch("engine.simulation.mission_director.requests") as mock_req:
            mock_req.get.side_effect = Exception("Connection refused")
            models = md.list_available_models()
            assert models == []

    def test_list_available_models_online(self):
        """When Ollama is available, return model names."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "gemma3:4b", "size": 3300000000},
                {"name": "qwen2.5:7b", "size": 4700000000},
            ]
        }
        mock_response.status_code = 200
        with patch("engine.simulation.mission_director.requests") as mock_req:
            mock_req.get.return_value = mock_response
            models = md.list_available_models()
            assert "gemma3:4b" in models
            assert "qwen2.5:7b" in models


# -- scenario_to_battle_scenario -------------------------------------------

class TestScenarioToBattleScenario:
    """Test converting MissionDirector scenario dict to BattleScenario."""

    def test_returns_battle_scenario(self):
        from engine.simulation.mission_director import MissionDirector
        from engine.simulation.scenario import BattleScenario
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        assert isinstance(bs, BattleScenario)

    def test_has_waves(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        assert len(bs.waves) == 10  # battle mode default

    def test_has_defenders(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        assert len(bs.defenders) >= 3

    def test_wave_has_groups(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        for wave in bs.waves:
            assert len(wave.groups) > 0

    def test_wave_count_matches_briefings(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        assert len(bs.waves) == len(scenario["wave_briefings"])

    def test_threat_level_affects_hostile_count(self):
        """Heavy waves should have more hostiles than light waves."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        light_count = bs.waves[0].total_count   # Wave 1 = light
        heavy_count = bs.waves[-1].total_count   # Wave 10 = heavy
        assert heavy_count > light_count

    def test_heavy_waves_have_mixed_types(self):
        """Heavy waves should include hostile_vehicle or hostile_leader."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        last_wave = bs.waves[-1]
        types = {g.asset_type for g in last_wave.groups}
        # Heavy waves should have more than just "person"
        assert len(types) > 1

    def test_defense_mode_waves(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="defense")
        bs = md.scenario_to_battle_scenario(scenario)
        assert len(bs.waves) == 5  # defense mode default

    def test_defenders_have_positions(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        for d in bs.defenders:
            assert isinstance(d.position, tuple)
            assert len(d.position) == 2

    def test_scenario_name_from_context(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        assert len(bs.name) > 0

    def test_patrol_mode_lower_hostiles(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        battle = md.generate_scripted(game_mode="battle")
        md.reset()
        patrol = md.generate_scripted(game_mode="patrol")
        bs_battle = md.scenario_to_battle_scenario(battle)
        bs_patrol = md.scenario_to_battle_scenario(patrol)
        battle_total = sum(w.total_count for w in bs_battle.waves)
        patrol_total = sum(w.total_count for w in bs_patrol.waves)
        assert battle_total > patrol_total

    def test_wave_health_multiplier_scales(self):
        """Later waves should have health multipliers > 1.0."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        assert bs.waves[-1].health_mult > bs.waves[0].health_mult

    def test_to_dict_roundtrip(self):
        """BattleScenario should survive to_dict → from_dict roundtrip."""
        from engine.simulation.mission_director import MissionDirector
        from engine.simulation.scenario import BattleScenario
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        bs = md.scenario_to_battle_scenario(scenario)
        d = bs.to_dict()
        bs2 = BattleScenario.from_dict(d)
        assert len(bs2.waves) == len(bs.waves)
        assert len(bs2.defenders) == len(bs.defenders)

    def test_scripted_includes_wave_composition(self):
        """Scripted generation should include wave_composition field."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        assert "wave_composition" in scenario
        assert len(scenario["wave_composition"]) == 10

    def test_wave_composition_groups_format(self):
        """Each wave composition entry should have groups with type/count."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="battle")
        for wc in scenario["wave_composition"]:
            assert "groups" in wc
            for g in wc["groups"]:
                assert "type" in g
                assert "count" in g
                assert g["count"] > 0

    def test_wave_composition_used_over_briefings(self):
        """When wave_composition is present, it should be used directly."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = {
            "game_mode": "battle",
            "units": [],
            "wave_briefings": [
                {"wave": 1, "threat_level": "light", "briefing": "Wave 1"},
            ],
            "wave_composition": [
                {
                    "wave": 1,
                    "groups": [{"type": "hostile_vehicle", "count": 99, "speed": 5.0, "health": 500.0}],
                    "speed_mult": 2.0,
                    "health_mult": 3.0,
                    "briefing": "Custom wave",
                },
            ],
        }
        bs = md.scenario_to_battle_scenario(scenario)
        assert len(bs.waves) == 1
        assert bs.waves[0].groups[0].asset_type == "hostile_vehicle"
        assert bs.waves[0].groups[0].count == 99
        assert bs.waves[0].speed_mult == 2.0

    def test_step_count_includes_wave_composition(self):
        """GENERATION_STEPS should include wave_composition."""
        from engine.simulation.mission_director import GENERATION_STEPS
        step_ids = [s["id"] for s in GENERATION_STEPS]
        assert "wave_composition" in step_ids
        assert len(step_ids) == 8
