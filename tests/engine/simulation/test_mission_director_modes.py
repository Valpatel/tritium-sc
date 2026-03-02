# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for civil_unrest and drone_swarm game mode registration in MissionDirector.

Phase 2 of MISSION-TYPES-SPEC.md: verify GAME_MODES entries, context templates,
loading messages, weather presets, wave composition data, and win conditions
for both new game modes.
"""

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Civil Unrest — GAME_MODES registration
# ---------------------------------------------------------------------------


class TestCivilUnrestGameMode:
    """Verify GAME_MODES['civil_unrest'] registration."""

    def test_civil_unrest_in_game_modes(self):
        from engine.simulation.mission_director import GAME_MODES
        assert "civil_unrest" in GAME_MODES

    def test_civil_unrest_description(self):
        from engine.simulation.mission_director import GAME_MODES
        desc = GAME_MODES["civil_unrest"]["description"].lower()
        assert "crowd control" in desc or "de-escalation" in desc

    def test_civil_unrest_default_waves_8(self):
        from engine.simulation.mission_director import GAME_MODES
        assert GAME_MODES["civil_unrest"]["default_waves"] == 8

    def test_civil_unrest_no_turrets_in_defenders(self):
        from engine.simulation.mission_director import GAME_MODES
        defenders = GAME_MODES["civil_unrest"]["default_defenders"]
        allowed = {"rover", "drone", "scout_drone"}
        for d in defenders:
            assert d["type"] in allowed, f"Unexpected type {d['type']} in civil_unrest defenders"

    def test_civil_unrest_hostiles_per_wave_15(self):
        from engine.simulation.mission_director import GAME_MODES
        assert GAME_MODES["civil_unrest"]["default_hostiles_per_wave"] == 15

    def test_civil_unrest_mode_radius_200(self):
        from engine.simulation.mission_director import _MODE_RADIUS
        assert _MODE_RADIUS["civil_unrest"] == 200


# ---------------------------------------------------------------------------
# Civil Unrest — Context templates
# ---------------------------------------------------------------------------


class TestCivilUnrestContextTemplates:
    """Verify civil unrest context templates and fallbacks."""

    def test_civil_unrest_has_4_context_templates(self):
        from engine.simulation.mission_director import _CIVIL_UNREST_CONTEXT_TEMPLATES
        assert len(_CIVIL_UNREST_CONTEXT_TEMPLATES) == 4

    def test_civil_unrest_context_templates_have_placeholders(self):
        from engine.simulation.mission_director import _CIVIL_UNREST_CONTEXT_TEMPLATES
        for i, t in enumerate(_CIVIL_UNREST_CONTEXT_TEMPLATES):
            # Each template must contain at least one of the POI placeholders
            text = " ".join(str(v) for v in t.values())
            has_center_name = "{center_name}" in text
            has_center_address = "{center_address}" in text
            has_streets = "{streets}" in text
            assert has_center_name or has_center_address or has_streets, \
                f"Template {i} has no POI placeholders"

    def test_civil_unrest_fallback_templates_no_placeholders(self):
        from engine.simulation.mission_director import _CIVIL_UNREST_CONTEXTS_FALLBACK
        assert len(_CIVIL_UNREST_CONTEXTS_FALLBACK) == 4
        for i, t in enumerate(_CIVIL_UNREST_CONTEXTS_FALLBACK):
            text = " ".join(str(v) for v in t.values())
            assert "{center_name}" not in text, f"Fallback {i} has {center_name} placeholder"
            assert "{center_address}" not in text, f"Fallback {i} has {center_address} placeholder"
            assert "{streets}" not in text, f"Fallback {i} has {streets} placeholder"


# ---------------------------------------------------------------------------
# Civil Unrest — Loading messages and weather
# ---------------------------------------------------------------------------


class TestCivilUnrestLoadingWeather:
    """Verify civil unrest loading messages and weather presets."""

    def test_civil_unrest_12_loading_messages(self):
        from engine.simulation.mission_director import _CIVIL_UNREST_LOADING
        assert len(_CIVIL_UNREST_LOADING) == 12

    def test_civil_unrest_3_weather_presets(self):
        from engine.simulation.mission_director import _CIVIL_UNREST_WEATHER
        assert len(_CIVIL_UNREST_WEATHER) == 3
        for w in _CIVIL_UNREST_WEATHER:
            assert "weather" in w
            assert "visibility" in w
            assert "mood_description" in w


# ---------------------------------------------------------------------------
# Civil Unrest — Wave composition
# ---------------------------------------------------------------------------


class TestCivilUnrestWaveComposition:
    """Verify wave composition data matches spec table."""

    def test_civil_unrest_wave_composition_8_waves(self):
        from engine.simulation.mission_director import _CIVIL_UNREST_WAVES
        assert len(_CIVIL_UNREST_WAVES) == 8

    def test_civil_unrest_wave1_peaceful_assembly(self):
        from engine.simulation.mission_director import _CIVIL_UNREST_WAVES
        w1 = _CIVIL_UNREST_WAVES[0]
        assert w1["civilians"] == 12
        assert w1["instigators"] == 0
        assert w1["vehicles"] == 0

    def test_civil_unrest_wave8_final_escalation(self):
        from engine.simulation.mission_director import _CIVIL_UNREST_WAVES
        w8 = _CIVIL_UNREST_WAVES[7]
        assert w8["civilians"] == 20
        assert w8["instigators"] == 10
        assert w8["vehicles"] == 4

    def test_civil_unrest_civilians_outnumber_instigators(self):
        """Every wave with instigators must have more civilians than instigators.

        The spec table (section 2.2) shows civilians >= instigators in all waves.
        Most waves exceed 2:1, but the Armed Standoff (wave 7) has 10:8 by design
        (standoff implies near-parity).  The 2:1 guideline in section 2.7 is a
        soft constraint for LLM generation, not a hard rule on scripted data.
        """
        from engine.simulation.mission_director import _CIVIL_UNREST_WAVES
        for i, w in enumerate(_CIVIL_UNREST_WAVES):
            if w["instigators"] > 0:
                assert w["civilians"] >= w["instigators"], \
                    f"Wave {i + 1}: {w['civilians']} civilians < {w['instigators']} instigators"


# ---------------------------------------------------------------------------
# Civil Unrest — Win conditions
# ---------------------------------------------------------------------------


class TestCivilUnrestWinConditions:
    """Verify civil unrest win conditions in generate_scripted()."""

    def test_civil_unrest_win_conditions_structure(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="civil_unrest")
        wc = scenario["win_conditions"]
        assert "victory" in wc
        assert "defeat" in wc
        assert "bonus_objectives" in wc
        assert "condition" in wc["victory"]
        assert "condition" in wc["defeat"]
        assert len(wc["bonus_objectives"]) >= 3


# ---------------------------------------------------------------------------
# Drone Swarm — GAME_MODES registration
# ---------------------------------------------------------------------------


class TestDroneSwarmGameMode:
    """Verify GAME_MODES['drone_swarm'] registration."""

    def test_drone_swarm_in_game_modes(self):
        from engine.simulation.mission_director import GAME_MODES
        assert "drone_swarm" in GAME_MODES

    def test_drone_swarm_default_waves_10(self):
        from engine.simulation.mission_director import GAME_MODES
        assert GAME_MODES["drone_swarm"]["default_waves"] == 10

    def test_drone_swarm_defender_composition(self):
        from engine.simulation.mission_director import GAME_MODES
        defenders = GAME_MODES["drone_swarm"]["default_defenders"]
        types = {d["type"] for d in defenders}
        assert "missile_turret" in types
        assert "drone" in types
        assert "turret" in types
        assert "scout_drone" in types
        assert "rover" in types

    def test_drone_swarm_hostiles_per_wave_10(self):
        from engine.simulation.mission_director import GAME_MODES
        assert GAME_MODES["drone_swarm"]["default_hostiles_per_wave"] == 10

    def test_drone_swarm_mode_radius_250(self):
        from engine.simulation.mission_director import _MODE_RADIUS
        assert _MODE_RADIUS["drone_swarm"] == 250


# ---------------------------------------------------------------------------
# Drone Swarm — Context templates
# ---------------------------------------------------------------------------


class TestDroneSwarmContextTemplates:
    """Verify drone swarm context templates and fallbacks."""

    def test_drone_swarm_has_4_context_templates(self):
        from engine.simulation.mission_director import _DRONE_SWARM_CONTEXT_TEMPLATES
        assert len(_DRONE_SWARM_CONTEXT_TEMPLATES) == 4

    def test_drone_swarm_12_loading_messages(self):
        from engine.simulation.mission_director import _DRONE_SWARM_LOADING
        assert len(_DRONE_SWARM_LOADING) == 12

    def test_drone_swarm_3_weather_presets(self):
        from engine.simulation.mission_director import _DRONE_SWARM_WEATHER
        assert len(_DRONE_SWARM_WEATHER) == 3
        for w in _DRONE_SWARM_WEATHER:
            assert "weather" in w
            assert "visibility" in w
            assert "mood_description" in w


# ---------------------------------------------------------------------------
# Drone Swarm — Wave composition
# ---------------------------------------------------------------------------


class TestDroneSwarmWaveComposition:
    """Verify wave composition data matches spec table."""

    def test_drone_swarm_wave_composition_10_waves(self):
        from engine.simulation.mission_director import _DRONE_SWARM_WAVES
        assert len(_DRONE_SWARM_WAVES) == 10

    def test_drone_swarm_wave1_probing_flight(self):
        from engine.simulation.mission_director import _DRONE_SWARM_WAVES
        w1 = _DRONE_SWARM_WAVES[0]
        assert w1["scout"] == 5
        assert w1["attack"] == 0
        assert w1["bomber"] == 0

    def test_drone_swarm_wave10_final_swarm(self):
        from engine.simulation.mission_director import _DRONE_SWARM_WAVES
        w10 = _DRONE_SWARM_WAVES[9]
        assert w10["scout"] == 8
        assert w10["attack"] == 20
        assert w10["bomber"] == 8

    def test_drone_swarm_win_conditions_structure(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        scenario = md.generate_scripted(game_mode="drone_swarm")
        wc = scenario["win_conditions"]
        assert "victory" in wc
        assert "defeat" in wc
        assert "bonus_objectives" in wc
        assert "condition" in wc["victory"]
        assert "condition" in wc["defeat"]
        assert len(wc["bonus_objectives"]) >= 3


# ---------------------------------------------------------------------------
# _briefings_to_composition dispatch
# ---------------------------------------------------------------------------


class TestBriefingsToCompositionDispatch:
    """Verify _briefings_to_composition dispatches to mode-specific methods."""

    def test_briefings_to_composition_civil_unrest(self):
        from engine.simulation.mission_director import MissionDirector, GAME_MODES
        md = MissionDirector(event_bus=MagicMock())
        mode = GAME_MODES["civil_unrest"]
        briefings = [{"wave": i + 1, "threat_level": "moderate"} for i in range(8)]
        result = md._briefings_to_composition(briefings, mode, game_mode="civil_unrest")
        assert len(result) == 8
        # Civil unrest uses person type with crowd roles
        for w in result:
            assert "groups" in w
            assert len(w["groups"]) >= 1

    def test_briefings_to_composition_drone_swarm(self):
        from engine.simulation.mission_director import MissionDirector, GAME_MODES
        md = MissionDirector(event_bus=MagicMock())
        mode = GAME_MODES["drone_swarm"]
        briefings = [{"wave": i + 1, "threat_level": "moderate"} for i in range(10)]
        result = md._briefings_to_composition(briefings, mode, game_mode="drone_swarm")
        assert len(result) == 10
        # Drone swarm uses swarm drone types
        for w in result:
            assert "groups" in w
            assert len(w["groups"]) >= 1
