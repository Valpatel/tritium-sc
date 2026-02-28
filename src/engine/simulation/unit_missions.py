# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""UnitMissionSystem — assigns backstories, goals, and active missions to all units.

Every unit gets:
1. A backstory/personality (LLM-generated async via Ollama, scripted fallback)
2. Starter mission assigned immediately at spawn (patrol, scout, hold, etc.)
3. Active mission loop — when a unit finishes its mission, it gets a new one

Friendly units NEVER sit idle. They are always patrolling, scouting, or
pursuing goals. The system also generates scenario context ("why is this
battle happening?") via LLM for loading screens and narrative.

Integration:
    engine._do_tick() calls unit_missions.tick(dt, targets_dict)
    engine.add_target() calls unit_missions.on_unit_added(target)
"""

from __future__ import annotations

import math
import random
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget


# -- Patrol route generators -----------------------------------------------

def _perimeter_patrol(center: tuple[float, float], radius: float = 40.0,
                      points: int = 6) -> list[tuple[float, float]]:
    """Generate a perimeter patrol route around a center point."""
    waypoints = []
    for i in range(points):
        angle = (i / points) * 2 * math.pi
        x = center[0] + radius * math.cos(angle)
        y = center[1] + radius * math.sin(angle)
        waypoints.append((x, y))
    return waypoints


def _grid_sweep(center: tuple[float, float], size: float = 30.0,
                step: float = 15.0) -> list[tuple[float, float]]:
    """Generate a grid sweep pattern for thorough area coverage."""
    waypoints = []
    half = size / 2
    y = center[1] - half
    row = 0
    while y <= center[1] + half:
        if row % 2 == 0:
            waypoints.append((center[0] - half, y))
            waypoints.append((center[0] + half, y))
        else:
            waypoints.append((center[0] + half, y))
            waypoints.append((center[0] - half, y))
        y += step
        row += 1
    return waypoints


def _random_patrol(bounds: float = 80.0, points: int = 4) -> list[tuple[float, float]]:
    """Generate random patrol waypoints within bounds."""
    return [
        (random.uniform(-bounds, bounds), random.uniform(-bounds, bounds))
        for _ in range(points)
    ]


def _sector_scout(position: tuple[float, float], direction: float,
                   range_: float = 50.0) -> list[tuple[float, float]]:
    """Generate a sector scout route in a given direction."""
    waypoints = []
    for d in [range_ * 0.3, range_ * 0.6, range_]:
        angle = math.radians(direction) + random.uniform(-0.3, 0.3)
        x = position[0] + d * math.cos(angle)
        y = position[1] + d * math.sin(angle)
        waypoints.append((x, y))
    # Return to start
    waypoints.append(position)
    return waypoints


# -- Backstory templates by alliance and type --------------------------------

_FRIENDLY_BACKSTORIES = {
    "turret": [
        "Automated defense turret, designation {name}. Installed during the initial security buildup. Has logged over 2,000 hours of continuous overwatch. Knows every approach vector by heart.",
        "Heavy sentry unit {name}. Third-generation targeting system. The last line of defense for the eastern approach. Never sleeps, never blinks.",
        "Rapid-fire turret {name}, mounted at a critical chokepoint. Upgraded last month with enhanced optics. Takes pride in a 94% first-round hit rate.",
    ],
    "rover": [
        "Ground patrol rover {name}. Ex-warehouse bot retrofitted for security. Methodical and thorough — checks every corner, every shadow. Favorite route: the south perimeter loop.",
        "Fast-response rover {name}. First unit dispatched to any alert. Built for speed over rough terrain. Has a dent from last week's engagement and wears it like a medal.",
        "Heavy rover {name}. Armored chassis, all-terrain treads. The unit everyone wants covering their flank. Slow but unstoppable once committed.",
    ],
    "drone": [
        "Aerial scout drone {name}. Eyes in the sky. Orbits at 30m altitude with a wide-angle camera. Can spot movement from 200m away. Hates wind.",
        "Fast-attack drone {name}. Modified racing frame with a weapon mount. Agile and aggressive. Prefers close-range strafing runs.",
        "Surveillance drone {name}. Quiet rotor design for covert observation. Maps the neighborhood daily. Knows which houses have dogs.",
    ],
    "scout_drone": [
        "Long-range scout {name}. Extended battery, minimal weapons. Built for endurance missions over hostile territory. Reports back everything.",
    ],
}

_HOSTILE_BACKSTORIES = {
    "person": [
        "Unknown intruder. Approached from the tree line under cover of darkness. Moves with military precision — likely trained.",
        "Hostile contact. Dressed in dark clothing, deliberate movement pattern. Testing our perimeter defenses systematically.",
        "Armed individual advancing through sector. No communication intercepted. Operating alone or maintaining radio silence.",
        "Infiltrator moving through the neighborhood. Using cover effectively. Has been observed scouting approach routes for the past hour.",
    ],
    "hostile_vehicle": [
        "Hostile technical. Modified civilian vehicle with improvised armor. Fast and dangerous. Carrying a mounted weapon.",
        "Enemy transport. Moving at high speed along main roads. Likely carrying reinforcements to the front.",
    ],
    "hostile_leader": [
        "Enemy commander. Coordinates other hostiles via hand signals. Higher priority target — eliminating this unit disrupts their coordination.",
    ],
}

_NEUTRAL_BACKSTORIES = {
    "person": [
        "{name} lives two blocks over. Takes this route every morning for coffee. Wears the same blue jacket year-round.",
        "{name} is a local delivery worker. Knows every address by heart. Has a friendly wave for the cameras.",
        "A jogger who runs the neighborhood loop at dawn. Keeps earbuds in. Oblivious to the security infrastructure around them.",
        "{name} is walking to the bus stop. Works the early shift downtown. Always running five minutes late.",
    ],
    "vehicle": [
        "A {name}. Part of the regular morning commute traffic. Same route, same time, five days a week.",
        "Delivery vehicle making rounds. Stops at three houses on this block. Nothing unusual about the route.",
    ],
    "animal": [
        "Neighborhood dog on its morning walk. Owner nearby but out of frame. Sniffs every bush.",
        "Stray cat prowling the yards. Known to the cameras. Usually appears around dusk.",
    ],
}

# -- LLM prompt templates ---------------------------------------------------

_BACKSTORY_PROMPT = """Generate a brief backstory (2-3 sentences) for a {alliance} {asset_type} unit named "{name}" in a neighborhood security simulation.

The unit is at position ({x:.0f}, {y:.0f}) on a 400x400 meter map.
{extra_context}

Be specific and colorful. Give them personality. What's their story? Why are they here?
Respond with ONLY the backstory text, no labels or formatting."""

_SCENARIO_PROMPT = """Generate a brief scenario briefing (3-4 sentences) for a neighborhood security battle.
Wave {wave} of {total_waves}. Current score: {score}.
{context}

Why is this battle happening? What's at stake? Who are the attackers?
Respond with ONLY the scenario text, no labels or formatting."""


class UnitMissionSystem:
    """Assigns backstories, goals, and missions to all simulation units."""

    # Check for idle units every N seconds
    IDLE_CHECK_INTERVAL = 2.0

    def __init__(self, map_bounds: float = 200.0) -> None:
        self._missions: dict[str, dict] = {}          # target_id -> mission dict
        self._backstories: dict[str, str] = {}         # target_id -> backstory text
        self._pending_backstories: set[str] = set()    # target_ids queued for LLM
        self._map_bounds = map_bounds
        self._last_idle_check: float = 0.0
        self._lock = threading.Lock()

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Called each engine tick. Checks for idle units and reassigns."""
        import time
        now = time.monotonic()
        if now - self._last_idle_check < self.IDLE_CHECK_INTERVAL:
            return
        self._last_idle_check = now

        for tid, t in targets.items():
            if t.status != "active":
                continue

            # Check if unit is idle (no waypoints, no active mission)
            is_idle = not t.waypoints or len(t.waypoints) == 0
            has_mission = tid in self._missions

            if is_idle and t.alliance == "friendly" and t.is_combatant:
                # Friendly combatant is idle — give it a mission
                if has_mission and self._missions[tid]["type"] == "patrol":
                    # Restart patrol loop
                    wps = self._missions[tid].get("waypoints", [])
                    if wps:
                        t.waypoints = list(wps)
                        t._waypoint_index = 0
                else:
                    mission = self.assign_starter_mission(t)
                    if mission and "waypoints" in mission:
                        t.waypoints = list(mission["waypoints"])
                        t._waypoint_index = 0

            elif is_idle and t.alliance == "neutral":
                # Neutral reached destination — let it despawn naturally
                pass

    def assign_starter_mission(self, target: SimulationTarget) -> dict:
        """Assign an immediate starter mission based on unit type and alliance."""
        if target.alliance == "friendly":
            return self._assign_friendly_mission(target)
        elif target.alliance == "hostile":
            return self._assign_hostile_mission(target)
        else:
            return self._assign_neutral_mission(target)

    def _assign_friendly_mission(self, target: SimulationTarget) -> dict:
        """Assign a mission to a friendly unit."""
        if target.speed == 0:
            # Stationary units: hold position with scanning
            mission = {
                "type": "hold",
                "position": target.position,
                "description": f"Hold position at ({target.position[0]:.0f}, {target.position[1]:.0f}). Scan all sectors.",
            }
        elif target.asset_type in ("drone", "scout_drone"):
            # Flying units: aerial scout or sweep
            roll = random.random()
            if roll < 0.4:
                wps = _perimeter_patrol(target.position, radius=60.0)
                mission = {
                    "type": "scout",
                    "waypoints": wps,
                    "description": "Aerial reconnaissance sweep of the perimeter.",
                }
            elif roll < 0.7:
                wps = _grid_sweep(target.position, size=50.0, step=20.0)
                mission = {
                    "type": "sweep",
                    "waypoints": wps,
                    "description": "Systematic grid sweep of the area.",
                }
            else:
                direction = random.uniform(0, 360)
                wps = _sector_scout(target.position, direction, range_=60.0)
                mission = {
                    "type": "scout",
                    "waypoints": wps,
                    "description": f"Sector scout, bearing {direction:.0f} degrees.",
                }
        else:
            # Ground mobile units: patrol
            roll = random.random()
            if roll < 0.5:
                wps = _perimeter_patrol(
                    (0, 0), radius=self._map_bounds * 0.3, points=6
                )
                mission = {
                    "type": "patrol",
                    "waypoints": wps,
                    "description": "Perimeter patrol. Keep eyes open.",
                }
            elif roll < 0.8:
                wps = _random_patrol(bounds=self._map_bounds * 0.4, points=5)
                mission = {
                    "type": "patrol",
                    "waypoints": wps,
                    "description": "Random area patrol. Cover ground.",
                }
            else:
                direction = random.uniform(0, 360)
                wps = _sector_scout(target.position, direction, range_=40.0)
                mission = {
                    "type": "escort",
                    "waypoints": wps,
                    "description": "Forward escort route.",
                }

        self._missions[target.target_id] = mission
        return mission

    def _assign_hostile_mission(self, target: SimulationTarget) -> dict:
        """Assign a mission to a hostile unit."""
        roll = random.random()
        if roll < 0.4:
            mission = {
                "type": "assault",
                "description": "Advance on objective. Engage all targets.",
            }
        elif roll < 0.7:
            mission = {
                "type": "infiltrate",
                "description": "Move through cover. Avoid detection until in range.",
            }
        elif roll < 0.9:
            direction = random.uniform(0, 360)
            wps = _sector_scout(target.position, direction, range_=30.0)
            mission = {
                "type": "scout",
                "waypoints": wps,
                "description": "Recon the enemy positions before committing.",
            }
        else:
            mission = {
                "type": "advance",
                "description": "Push forward toward the center.",
            }

        self._missions[target.target_id] = mission
        return mission

    def _assign_neutral_mission(self, target: SimulationTarget) -> dict:
        """Assign a civilian mission to a neutral unit."""
        roll = random.random()
        if target.asset_type == "vehicle":
            mission_type = "commute" if roll < 0.7 else "errand"
        elif target.asset_type == "animal":
            mission_type = "wander"
        else:
            if roll < 0.4:
                mission_type = "commute"
            elif roll < 0.7:
                mission_type = "walk"
            elif roll < 0.9:
                mission_type = "errand"
            else:
                mission_type = "wander"

        mission = {
            "type": mission_type,
            "description": f"Civilian {mission_type} through the neighborhood.",
        }
        self._missions[target.target_id] = mission
        return mission

    # -- Backstory generation -----------------------------------------------

    def generate_backstory_scripted(self, target: SimulationTarget) -> str:
        """Generate a scripted backstory (immediate, no LLM needed)."""
        alliance = target.alliance
        atype = target.asset_type

        if alliance == "friendly":
            pool = _FRIENDLY_BACKSTORIES.get(atype, _FRIENDLY_BACKSTORIES.get("rover", []))
        elif alliance == "hostile":
            pool = _HOSTILE_BACKSTORIES.get(atype, _HOSTILE_BACKSTORIES.get("person", []))
        else:
            pool = _NEUTRAL_BACKSTORIES.get(atype, _NEUTRAL_BACKSTORIES.get("person", []))

        if not pool:
            return f"Unit {target.name}. Alliance: {alliance}. Type: {atype}."

        template = random.choice(pool)
        story = template.format(name=target.name)
        self._backstories[target.target_id] = story
        return story

    def build_backstory_prompt(self, target: SimulationTarget) -> str:
        """Build an LLM prompt for generating a backstory."""
        extra = ""
        if target.alliance == "friendly":
            extra = "This is a defensive security unit protecting the neighborhood."
        elif target.alliance == "hostile":
            extra = "This is an intruder/attacker. Make the backstory ominous."
        else:
            extra = "This is a civilian going about their daily life."

        return _BACKSTORY_PROMPT.format(
            alliance=target.alliance,
            asset_type=target.asset_type,
            name=target.name,
            x=target.position[0],
            y=target.position[1],
            extra_context=extra,
        )

    def build_scenario_prompt(
        self, wave: int = 1, total_waves: int = 10, score: int = 0,
        context: str = "",
    ) -> str:
        """Build an LLM prompt for generating battle scenario context."""
        return _SCENARIO_PROMPT.format(
            wave=wave, total_waves=total_waves, score=score,
            context=context or "A residential neighborhood under siege.",
        )

    def request_llm_backstory(self, target: SimulationTarget) -> None:
        """Queue a target for LLM backstory generation.

        The actual LLM call happens in a background thread (not blocking tick).
        Until the LLM responds, the unit uses its scripted backstory.
        """
        # Assign scripted backstory immediately as fallback
        if target.target_id not in self._backstories:
            self.generate_backstory_scripted(target)
        self._pending_backstories.add(target.target_id)

    def get_backstory(self, target_id: str) -> str | None:
        """Get a unit's backstory."""
        return self._backstories.get(target_id)

    def get_mission(self, target_id: str) -> dict | None:
        """Get a unit's current mission."""
        return self._missions.get(target_id)

    def reset(self) -> None:
        """Clear all missions and backstories."""
        self._missions.clear()
        self._backstories.clear()
        self._pending_backstories.clear()
