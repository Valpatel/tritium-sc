"""Tests for NPC prompt generation and response parsing.

TDD: These tests are written first, before the implementation.
"""

import pytest

from engine.simulation.npc_intelligence.brain import NPCBrain, NPCPersonality, NPCMemory
from engine.simulation.npc_intelligence.prompts import build_npc_prompt, parse_npc_response


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def pedestrian_brain():
    """A pedestrian NPC brain with known personality."""
    brain = NPCBrain(
        target_id="npc_ped_01",
        asset_type="person",
        alliance="neutral",
        personality=NPCPersonality(
            curiosity=0.7,
            caution=0.3,
            sociability=0.6,
            aggression=0.1,
        ),
    )
    return brain


@pytest.fixture
def vehicle_brain():
    """A vehicle NPC brain."""
    return NPCBrain(
        target_id="npc_veh_01",
        asset_type="vehicle",
        alliance="neutral",
        personality=NPCPersonality(
            curiosity=0.2,
            caution=0.8,
            sociability=0.1,
            aggression=0.0,
        ),
    )


@pytest.fixture
def brain_with_memory(pedestrian_brain):
    """A pedestrian brain that has some events in memory."""
    pedestrian_brain.memory.add_event("weapon_fired", {"distance": 30.0})
    pedestrian_brain.memory.add_event("wave_start", {})
    pedestrian_brain.memory.add_event("target_eliminated", {"distance": 50.0})
    return pedestrian_brain


@pytest.fixture
def sample_entities():
    """Nearby entities for prompt context."""
    return [
        {"name": "Turret-Alpha", "alliance": "friendly", "type": "turret", "distance": 15.0},
        {"name": "Hostile-1", "alliance": "hostile", "type": "person", "distance": 25.0},
        {"name": "Dog", "alliance": "neutral", "type": "animal", "distance": 8.0},
    ]


# ============================================================================
# build_npc_prompt tests
# ============================================================================

class TestBuildNpcPrompt:
    """Tests for build_npc_prompt()."""

    def test_prompt_contains_npc_name(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain)
        assert "npc_ped_01" in prompt

    def test_prompt_contains_personality_traits(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain)
        assert "curiosity" in prompt.lower()
        assert "caution" in prompt.lower()
        assert "sociability" in prompt.lower()
        assert "aggression" in prompt.lower()

    def test_prompt_contains_trait_values(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain)
        # Personality values should appear as floats
        assert "0.7" in prompt  # curiosity
        assert "0.3" in prompt  # caution
        assert "0.6" in prompt  # sociability
        assert "0.1" in prompt  # aggression

    def test_prompt_contains_fsm_state(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain)
        # Default state for pedestrian is "walking"
        assert "walking" in prompt.lower()

    def test_prompt_contains_asset_type(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain)
        assert "person" in prompt.lower()

    def test_prompt_no_entities(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain, nearby_entities=None)
        # Should still generate valid prompt
        assert "npc_ped_01" in prompt

    def test_prompt_with_entities(self, pedestrian_brain, sample_entities):
        prompt = build_npc_prompt(pedestrian_brain, nearby_entities=sample_entities)
        assert "Turret-Alpha" in prompt
        assert "Hostile-1" in prompt
        assert "Dog" in prompt

    def test_prompt_entity_alliance(self, pedestrian_brain, sample_entities):
        prompt = build_npc_prompt(pedestrian_brain, nearby_entities=sample_entities)
        assert "friendly" in prompt.lower()
        assert "hostile" in prompt.lower()
        assert "neutral" in prompt.lower()

    def test_prompt_entity_distance(self, pedestrian_brain, sample_entities):
        prompt = build_npc_prompt(pedestrian_brain, nearby_entities=sample_entities)
        assert "15" in prompt  # turret distance
        assert "25" in prompt  # hostile distance

    def test_prompt_max_five_entities(self, pedestrian_brain):
        entities = [
            {"name": f"Entity-{i}", "alliance": "neutral", "type": "person", "distance": float(i * 10)}
            for i in range(8)
        ]
        prompt = build_npc_prompt(pedestrian_brain, nearby_entities=entities)
        # Only first 5 should appear
        assert "Entity-4" in prompt
        assert "Entity-5" not in prompt

    def test_prompt_contains_memory_events(self, brain_with_memory):
        prompt = build_npc_prompt(brain_with_memory)
        assert "weapon_fired" in prompt
        assert "wave_start" in prompt
        assert "target_eliminated" in prompt

    def test_prompt_empty_memory(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain)
        # Should show "(none)" or similar for empty memory
        assert "(none)" in prompt.lower() or "no recent" in prompt.lower()

    def test_prompt_asks_for_action_word(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain)
        prompt_upper = prompt.upper()
        # Should mention the valid action words
        assert "WALK" in prompt_upper
        assert "PAUSE" in prompt_upper
        assert "FLEE" in prompt_upper
        assert "HIDE" in prompt_upper
        assert "OBSERVE" in prompt_upper
        assert "APPROACH" in prompt_upper
        assert "IGNORE" in prompt_upper

    def test_prompt_asks_for_one_action(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain)
        assert "one" in prompt.lower() or "ONE" in prompt or "single" in prompt.lower()

    def test_prompt_vehicle_type(self, vehicle_brain):
        prompt = build_npc_prompt(vehicle_brain)
        assert "vehicle" in prompt.lower()
        assert "npc_veh_01" in prompt

    def test_prompt_returns_string(self, pedestrian_brain):
        prompt = build_npc_prompt(pedestrian_brain)
        assert isinstance(prompt, str)
        assert len(prompt) > 50  # Minimum reasonable length


# ============================================================================
# parse_npc_response tests
# ============================================================================

class TestParseNpcResponse:
    """Tests for parse_npc_response()."""

    def test_parse_single_action_word(self):
        assert parse_npc_response("WALK") == "WALK"

    def test_parse_single_word_lowercase(self):
        assert parse_npc_response("walk") == "WALK"

    def test_parse_single_word_mixed_case(self):
        assert parse_npc_response("Walk") == "WALK"

    def test_parse_flee(self):
        assert parse_npc_response("FLEE") == "FLEE"

    def test_parse_hide(self):
        assert parse_npc_response("HIDE") == "HIDE"

    def test_parse_observe(self):
        assert parse_npc_response("OBSERVE") == "OBSERVE"

    def test_parse_approach(self):
        assert parse_npc_response("APPROACH") == "APPROACH"

    def test_parse_pause(self):
        assert parse_npc_response("PAUSE") == "PAUSE"

    def test_parse_ignore(self):
        assert parse_npc_response("IGNORE") == "IGNORE"

    def test_parse_action_with_period(self):
        assert parse_npc_response("WALK.") == "WALK"

    def test_parse_action_in_sentence_first_line(self):
        assert parse_npc_response("I think I should FLEE from here") == "FLEE"

    def test_parse_action_multiline_first_word(self):
        resp = "OBSERVE\nBecause there is something interesting"
        assert parse_npc_response(resp) == "OBSERVE"

    def test_parse_synonym_run(self):
        assert parse_npc_response("run") == "FLEE"

    def test_parse_synonym_sprint(self):
        assert parse_npc_response("sprint") == "FLEE"

    def test_parse_synonym_duck(self):
        assert parse_npc_response("duck") == "HIDE"

    def test_parse_synonym_cover(self):
        assert parse_npc_response("cover") == "HIDE"

    def test_parse_synonym_shelter(self):
        assert parse_npc_response("shelter") == "HIDE"

    def test_parse_synonym_look(self):
        assert parse_npc_response("look") == "OBSERVE"

    def test_parse_synonym_watch(self):
        assert parse_npc_response("watch") == "OBSERVE"

    def test_parse_synonym_investigate(self):
        assert parse_npc_response("investigate") == "OBSERVE"

    def test_parse_synonym_go(self):
        assert parse_npc_response("go") == "WALK"

    def test_parse_synonym_move(self):
        assert parse_npc_response("move") == "WALK"

    def test_parse_synonym_continue(self):
        assert parse_npc_response("continue") == "WALK"

    def test_parse_synonym_stop(self):
        assert parse_npc_response("stop") == "PAUSE"

    def test_parse_synonym_wait(self):
        assert parse_npc_response("wait") == "PAUSE"

    def test_parse_synonym_check(self):
        assert parse_npc_response("check") == "APPROACH"

    def test_parse_empty_response(self):
        assert parse_npc_response("") == "WALK"

    def test_parse_gibberish(self):
        assert parse_npc_response("asdfghjkl") == "WALK"

    def test_parse_whitespace_only(self):
        assert parse_npc_response("   ") == "WALK"

    def test_parse_action_deep_in_response(self):
        resp = "Thinking about this...\nThe situation looks scary.\nI should probably HIDE behind something."
        assert parse_npc_response(resp) == "HIDE"

    def test_parse_action_with_leading_whitespace(self):
        assert parse_npc_response("  FLEE  ") == "FLEE"

    def test_parse_synonym_embedded_in_sentence(self):
        resp = "I need to run away from the danger"
        assert parse_npc_response(resp) == "FLEE"

    def test_parse_first_valid_action_wins(self):
        # When multiple actions appear, the first matching one wins
        resp = "OBSERVE the area then WALK away"
        assert parse_npc_response(resp) == "OBSERVE"


# ============================================================================
# Spatial awareness in prompts
# ============================================================================


try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False

from engine.simulation.npc_intelligence.prompts import build_spatial_context
from engine.simulation.npc_intelligence.world_model import WorldModel


def _make_world_with_buildings_and_roads():
    """Create a WorldModel with buildings, roads, and sidewalks for testing.

    Layout:
    - Building at center (50,50) — a small home (~80 m2 polygon)
    - Road (residential) running horizontally: nodes 0=(0,40) — 1=(100,40)
    - Sidewalk (footway) running parallel: nodes 2=(0,45) — 3=(100,45)
    - Crosswalk where footway meets road at node 4=(50,42)
    """
    building_poly = [
        (45.0, 45.0), (55.0, 45.0), (55.0, 55.0), (45.0, 55.0),
    ]

    if not _HAS_NX:
        return WorldModel.from_raw([building_poly])

    G = nx.Graph()
    # Road edge
    G.add_edge(0, 1, road_class="residential", weight=100.0)
    # Sidewalk edge
    G.add_edge(2, 3, road_class="footway", weight=100.0)
    # Crosswalk connector: footway node to road node
    G.add_edge(3, 1, road_class="footway", weight=10.0)
    # Another road for intersection crosswalk (3-way intersection at node 1)
    G.add_edge(1, 5, road_class="residential", weight=50.0)
    G.add_edge(1, 6, road_class="tertiary", weight=50.0)

    positions = {
        0: (0.0, 40.0),
        1: (100.0, 40.0),
        2: (0.0, 45.0),
        3: (100.0, 45.0),
        5: (100.0, 0.0),
        6: (120.0, 40.0),
    }

    return WorldModel.from_raw([building_poly], G, positions)


def _make_empty_world():
    """WorldModel with no buildings and no streets."""
    return WorldModel.from_raw([], None, None)


class TestSpatialPrompts:
    """Tests for build_spatial_context() and spatial awareness in prompts."""

    def test_spatial_context_includes_location_type_sidewalk(self):
        """NPC on a sidewalk should get a context saying so."""
        world = _make_world_with_buildings_and_roads()
        # Position near the footway edge at y=45, but x=10 (outside building polygon)
        ctx = build_spatial_context(world, 10.0, 45.0)
        assert "sidewalk" in ctx.lower() or "footway" in ctx.lower()

    def test_spatial_context_includes_location_type_road(self):
        """NPC on a road should be told they're on a road."""
        world = _make_world_with_buildings_and_roads()
        # Position near the road edge (y=40)
        ctx = build_spatial_context(world, 50.0, 40.0)
        assert "road" in ctx.lower()

    def test_spatial_context_includes_location_type_inside_building(self):
        """NPC inside a building should be told they're inside."""
        world = _make_world_with_buildings_and_roads()
        # Position inside the building polygon (50,50)
        ctx = build_spatial_context(world, 50.0, 50.0)
        assert "inside" in ctx.lower() or "building" in ctx.lower()

    def test_spatial_context_includes_nearby_buildings(self):
        """Context should mention nearby buildings."""
        world = _make_world_with_buildings_and_roads()
        ctx = build_spatial_context(world, 50.0, 40.0)
        # Should mention the home building nearby
        assert "home" in ctx.lower() or "building" in ctx.lower()

    @pytest.mark.skipif(not _HAS_NX, reason="networkx required")
    def test_spatial_context_includes_nearest_crosswalk(self):
        """Context should mention crosswalk if close enough."""
        world = _make_world_with_buildings_and_roads()
        # Node 1 at (100, 40) is a 3-way road intersection => crosswalk
        ctx = build_spatial_context(world, 100.0, 40.0)
        assert "crosswalk" in ctx.lower() or "crossing" in ctx.lower()

    @pytest.mark.skipif(not _HAS_NX, reason="networkx required")
    def test_spatial_context_includes_road_type(self):
        """Context should mention the type of road nearby."""
        world = _make_world_with_buildings_and_roads()
        # Near the residential road at y=40
        ctx = build_spatial_context(world, 50.0, 40.0)
        assert "residential" in ctx.lower()

    def test_spatial_context_empty_world(self):
        """An empty world should still return a valid string."""
        world = _make_empty_world()
        ctx = build_spatial_context(world, 50.0, 50.0)
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_prompt_with_spatial_context(self, pedestrian_brain):
        """Full prompt with spatial context should include the LOCATION section."""
        world = _make_world_with_buildings_and_roads()
        spatial = build_spatial_context(world, 50.0, 40.0)
        prompt = build_npc_prompt(pedestrian_brain, spatial_context=spatial)
        assert "LOCATION" in prompt.upper() or "SURROUNDINGS" in prompt.upper()
        # The spatial text should appear in the prompt
        assert spatial in prompt

    def test_prompt_without_spatial_context_unchanged(self, pedestrian_brain):
        """Existing prompts without spatial_context should still work unchanged."""
        prompt_without = build_npc_prompt(pedestrian_brain)
        # Should not crash, should still have the basic sections
        assert "npc_ped_01" in prompt_without
        assert "curiosity" in prompt_without.lower()
        assert "WALK" in prompt_without.upper()
        # Should NOT have a SURROUNDINGS section when no spatial_context given
        assert "SURROUNDINGS:" not in prompt_without

    def test_spatial_context_returns_string(self):
        """build_spatial_context always returns a string."""
        world = _make_world_with_buildings_and_roads()
        result = build_spatial_context(world, 0.0, 0.0)
        assert isinstance(result, str)

    @pytest.mark.skipif(not _HAS_NX, reason="networkx required")
    def test_spatial_context_no_crosswalk_when_far(self):
        """No crosswalk mentioned when NPC is far from any crosswalk."""
        world = _make_world_with_buildings_and_roads()
        # Position far from crosswalk node (0, 0) — far from all nodes
        ctx = build_spatial_context(world, 0.0, 0.0)
        assert "crosswalk" not in ctx.lower()

    def test_spatial_context_building_distance(self):
        """Nearby buildings section should show distance."""
        world = _make_world_with_buildings_and_roads()
        ctx = build_spatial_context(world, 50.0, 40.0)
        # Should contain a distance in meters
        assert "m" in ctx.lower()
