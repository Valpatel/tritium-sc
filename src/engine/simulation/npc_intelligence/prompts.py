# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""NPC prompt generation and LLM response parsing.

Builds context prompts for NPC thinking and extracts action words
from LLM responses. Used by the LLMThinkScheduler.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .brain import NPCBrain
    from .world_model import WorldModel


# Valid action words that can be returned by the parser
VALID_ACTIONS = frozenset({
    "WALK", "PAUSE", "OBSERVE", "FLEE", "HIDE", "APPROACH", "IGNORE",
})

# Synonym map: lowercased word -> canonical action
_SYNONYMS: dict[str, str] = {
    "run": "FLEE",
    "sprint": "FLEE",
    "duck": "HIDE",
    "cover": "HIDE",
    "shelter": "HIDE",
    "look": "OBSERVE",
    "watch": "OBSERVE",
    "investigate": "OBSERVE",
    "go": "WALK",
    "move": "WALK",
    "walk": "WALK",
    "continue": "WALK",
    "stop": "PAUSE",
    "wait": "PAUSE",
    "approach": "APPROACH",
    "check": "APPROACH",
    "flee": "FLEE",
    "hide": "HIDE",
    "observe": "OBSERVE",
    "pause": "PAUSE",
    "ignore": "IGNORE",
}

DEFAULT_ACTION = "WALK"


NPC_THINKING_PROMPT = """\
You are {name}, a {asset_type} in a neighborhood. You are a neutral civilian.

PERSONALITY:
  curiosity: {curiosity:.2f}
  caution: {caution:.2f}
  sociability: {sociability:.2f}
  aggression: {aggression:.2f}

CURRENT STATE: {state}
POSITION: ({pos_x:.1f}, {pos_y:.1f})

RECENT EVENTS:
{events}

NEARBY:
{entities}

Choose ONE action word from: WALK, PAUSE, OBSERVE, FLEE, HIDE, APPROACH, IGNORE
Respond with a single word — your chosen action.
"""


def build_spatial_context(world: WorldModel, x: float, y: float) -> str:
    """Build a spatial context string describing what an NPC can see around them.

    Queries the WorldModel for the NPC's location type (sidewalk, road,
    inside building), nearby buildings, nearest crosswalk, and road type.

    Args:
        world: The WorldModel providing spatial queries.
        x: NPC x position.
        y: NPC y position.

    Returns:
        A multi-line string describing the NPC's spatial surroundings.
    """
    lines: list[str] = []

    # --- Location type ---
    if world.is_inside_building(x, y):
        bld = world.nearest_building(x, y)
        if bld:
            lines.append(f"You are inside a {bld.building_type} building.")
        else:
            lines.append("You are inside a building.")
    elif world.is_on_sidewalk(x, y):
        road_type = world.road_type_at(x, y)
        if road_type:
            lines.append(f"You are on a sidewalk along a {road_type} road.")
        else:
            lines.append("You are on a sidewalk.")
    elif world.is_on_road(x, y):
        road_type = world.road_type_at(x, y)
        if road_type:
            lines.append(f"You are on a {road_type} road.")
        else:
            lines.append("You are on a road.")
    else:
        lines.append("You are in an open area.")

    # --- Nearby buildings ---
    nearby = world.buildings_in_radius(x, y, 50.0)
    if nearby:
        # Sort by distance and take closest 3
        nearby.sort(key=lambda b: math.hypot(x - b.center[0], y - b.center[1]))
        bld_lines = []
        for b in nearby[:3]:
            d = math.hypot(x - b.center[0], y - b.center[1])
            bld_lines.append(f"  - {b.building_type.title()} ({d:.0f}m away)")
        lines.append("Nearby buildings:")
        lines.extend(bld_lines)

    # --- Nearest crosswalk ---
    cw = world.nearest_crosswalk(x, y)
    if cw is not None:
        cw_dist = math.hypot(x - cw.position[0], y - cw.position[1])
        if cw_dist <= 30.0:
            lines.append(f"There is a crosswalk {cw_dist:.0f}m away.")

    # --- Road type detail (if not already mentioned) ---
    road_type = world.road_type_at(x, y)
    if road_type and not any("road" in ln.lower() and road_type in ln.lower() for ln in lines):
        lines.append(f"The nearest road is a {road_type} road.")

    if not lines:
        lines.append("You are in an open area with no notable features nearby.")

    return "\n".join(lines)


def build_npc_prompt(
    brain: NPCBrain,
    nearby_entities: list[dict] | None = None,
    spatial_context: str | None = None,
) -> str:
    """Generate a thinking prompt for an NPC brain.

    Args:
        brain: The NPC brain to generate a prompt for.
        nearby_entities: Up to 5 nearby entities with name, alliance, type, distance.
        spatial_context: Optional spatial context string from build_spatial_context().

    Returns:
        The formatted prompt string.
    """
    personality = brain.personality

    # Format memory events
    events_text = brain.memory.format_for_prompt()

    # Format nearby entities (max 5)
    if nearby_entities:
        limited = nearby_entities[:5]
        entity_lines = []
        for ent in limited:
            name = ent.get("name", "Unknown")
            alliance = ent.get("alliance", "unknown")
            etype = ent.get("type", "unknown")
            dist = ent.get("distance", 0.0)
            entity_lines.append(f"- {name} [{alliance}] ({etype}) at {dist:.0f}m")
        entities_text = "\n".join(entity_lines)
    else:
        entities_text = "(none nearby)"

    # Get position from brain if available — default to 0,0
    pos_x = 0.0
    pos_y = 0.0

    prompt = NPC_THINKING_PROMPT.format(
        name=brain.target_id,
        asset_type=brain.asset_type,
        curiosity=personality.curiosity,
        caution=personality.caution,
        sociability=personality.sociability,
        aggression=personality.aggression,
        state=brain.fsm_state or "unknown",
        pos_x=pos_x,
        pos_y=pos_y,
        events=events_text,
        entities=entities_text,
    )

    # Append spatial context if provided
    if spatial_context:
        prompt += f"\nSURROUNDINGS:\n{spatial_context}\n"

    return prompt


def parse_npc_response(response_text: str) -> str:
    """Extract a single action word from an LLM response.

    Parsing strategy:
    1. Check if the first word is a valid action or synonym
    2. Scan keywords in the first line
    3. Scan the full response for action words or synonyms
    4. Default to "WALK"

    Args:
        response_text: Raw LLM response text.

    Returns:
        One of: WALK, PAUSE, OBSERVE, FLEE, HIDE, APPROACH, IGNORE
    """
    text = response_text.strip()
    if not text:
        return DEFAULT_ACTION

    # Strategy 1: Check first word
    first_word = text.split()[0].strip(".,!?;:").lower()
    if first_word.upper() in VALID_ACTIONS:
        return first_word.upper()
    if first_word in _SYNONYMS:
        return _SYNONYMS[first_word]

    # Strategy 2: Scan keywords in first line
    first_line = text.split("\n")[0].lower()
    action = _scan_for_action(first_line)
    if action is not None:
        return action

    # Strategy 3: Scan full response
    action = _scan_for_action(text.lower())
    if action is not None:
        return action

    return DEFAULT_ACTION


def _scan_for_action(text: str) -> str | None:
    """Scan text for action words or synonyms. Returns first match or None."""
    words = text.split()
    for word in words:
        cleaned = word.strip(".,!?;:\"'()[]")
        if cleaned.upper() in VALID_ACTIONS:
            return cleaned.upper()
        if cleaned in _SYNONYMS:
            return _SYNONYMS[cleaned]
    return None
