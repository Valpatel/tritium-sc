# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Hostile Agent -- autonomous enemy with LLM-driven decision-making.

A standalone process that connects to the TRITIUM simulation via MQTT.
Uses a small local LLM (qwen2.5:7b via Ollama) to decide what to do next.
Has its own FSM independent of the main codebase.

States: SPAWNING -> ADVANCING -> FLANKING -> HIDING -> ATTACKING -> FLEEING -> DEAD
"""

import enum
import math
import random
import time
from datetime import datetime, timezone


class HostileState(enum.Enum):
    SPAWNING = "spawning"
    ADVANCING = "advancing"
    FLANKING = "flanking"
    HIDING = "hiding"
    ATTACKING = "attacking"
    FLEEING = "fleeing"
    DEAD = "dead"


# Actions the LLM can choose from
VALID_ACTIONS = {"advance", "flank", "hide", "attack", "flee"}

# Keywords mapped to actions for LLM response parsing
ACTION_KEYWORDS = {
    "advance": "advance",
    "push": "advance",
    "move": "advance",
    "forward": "advance",
    "flank": "flank",
    "circle": "flank",
    "side": "flank",
    "hide": "hide",
    "cover": "hide",
    "wait": "hide",
    "attack": "attack",
    "fire": "attack",
    "shoot": "attack",
    "engage": "attack",
    "flee": "flee",
    "run": "flee",
    "retreat": "flee",
    "escape": "flee",
}

# State -> action mapping
ACTION_TO_STATE = {
    "advance": HostileState.ADVANCING,
    "flank": HostileState.FLANKING,
    "hide": HostileState.HIDING,
    "attack": HostileState.ATTACKING,
    "flee": HostileState.FLEEING,
}


class HostileAgent:
    """A single hostile entity with LLM-driven decision-making."""

    def __init__(self, hostile_id: str, start_x: float, start_y: float,
                 speed: float = 1.5, health: int = 100, name: str = ""):
        self.hostile_id = hostile_id
        self.x = float(start_x)
        self.y = float(start_y)
        self.heading = random.uniform(0, 360)
        self.speed = speed
        self.health = health
        self.max_health = health
        self.name = name or f"Hostile {hostile_id}"
        self.state = HostileState.SPAWNING
        self.alive = True

        # Movement target
        self.target_x = 0.0
        self.target_y = 0.0

        # Spawning timer
        self._spawn_timer = 0.0
        self._spawn_delay = 2.0  # seconds before advancing

        # Flanking offset
        self._flank_angle = random.choice([-1, 1]) * random.uniform(30, 60)

        # Decision timing
        self.decision_interval = 5.0  # seconds between LLM decisions
        self._decision_timer = 0.0

        # Situation awareness (updated externally)
        self.nearby_defenders = []
        self.nearby_hostiles = []
        self.under_fire = False

        # Personality traits (vary per agent for diversity)
        self.aggression = random.uniform(0.3, 0.9)
        self.caution = random.uniform(0.2, 0.8)

        # Last thought (for MQTT thoughts topic)
        self.last_thought = ""

    @property
    def is_hidden(self) -> bool:
        return self.state == HostileState.HIDING

    def tick(self, dt: float):
        """Advance simulation by dt seconds."""
        if not self.alive or self.state == HostileState.DEAD:
            return

        # Spawning delay
        if self.state == HostileState.SPAWNING:
            self._spawn_timer += dt
            if self._spawn_timer >= self._spawn_delay:
                self.state = HostileState.ADVANCING
            return

        # Decision timer
        self._decision_timer += dt

        # Movement based on state
        if self.state == HostileState.ADVANCING:
            self._move_toward_target(dt)
        elif self.state == HostileState.FLANKING:
            self._move_flanking(dt)
        elif self.state == HostileState.HIDING:
            pass  # stay put
        elif self.state == HostileState.ATTACKING:
            self._move_toward_target(dt * 0.3)  # slow advance while attacking
        elif self.state == HostileState.FLEEING:
            self._move_away_from_target(dt * 1.5)  # faster retreat

    def _move_toward_target(self, dt: float):
        """Move directly toward target position."""
        dx = self.target_x - self.x
        dy = self.target_y - self.y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.5:
            return
        nx, ny = dx / dist, dy / dist
        step = self.speed * dt
        if step > dist:
            step = dist
        self.x += nx * step
        self.y += ny * step
        self.heading = math.degrees(math.atan2(ny, nx))

    def _move_flanking(self, dt: float):
        """Move at an angle to the target (not straight at it)."""
        dx = self.target_x - self.x
        dy = self.target_y - self.y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.5:
            return
        # Rotate direction by flank angle
        base_angle = math.atan2(dy, dx)
        flank_rad = math.radians(self._flank_angle)
        angle = base_angle + flank_rad
        nx = math.cos(angle)
        ny = math.sin(angle)
        step = self.speed * dt
        self.x += nx * step
        self.y += ny * step
        self.heading = math.degrees(angle)

    def _move_away_from_target(self, dt: float):
        """Move away from target (flee)."""
        dx = self.x - self.target_x
        dy = self.y - self.target_y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.1:
            # Pick random direction
            angle = random.uniform(0, 2 * math.pi)
            dx, dy = math.cos(angle), math.sin(angle)
            dist = 1.0
        nx, ny = dx / dist, dy / dist
        step = self.speed * dt
        self.x += nx * step
        self.y += ny * step
        self.heading = math.degrees(math.atan2(ny, nx))

    def take_damage(self, amount: int):
        """Apply damage. May trigger state change."""
        self.health = max(0, self.health - amount)
        if self.health <= 0:
            self.alive = False
            self.state = HostileState.DEAD
        elif self.health < 25 and self.state != HostileState.FLEEING:
            self.state = HostileState.FLEEING

    def update_situation(self, situation: dict):
        """Update awareness of nearby units."""
        self.nearby_defenders = situation.get('nearby_defenders', [])
        self.nearby_hostiles = situation.get('nearby_hostiles', [])
        self.under_fire = situation.get('under_fire', False)

    def needs_decision(self) -> bool:
        """Check if it's time for a new LLM decision."""
        return self._decision_timer >= self.decision_interval

    def reset_decision_timer(self):
        """Reset after making a decision."""
        self._decision_timer = 0.0

    def build_decision_prompt(self) -> str:
        """Build the prompt to send to the LLM for decision-making."""
        defenders_desc = "none nearby"
        if self.nearby_defenders:
            parts = []
            for d in self.nearby_defenders[:3]:
                parts.append(f"  - {d.get('type', 'unknown')} at distance {d.get('distance', '?')}m")
            defenders_desc = "\n".join(parts)

        allies_desc = f"{len(self.nearby_hostiles)} allies nearby" if self.nearby_hostiles else "alone"

        return f"""You are {self.hostile_id}, a hostile combatant in a tactical simulation.

Current state: {self.state.value}
Health: {self.health}/{self.max_health}
Position: ({self.x:.1f}, {self.y:.1f})
Target: ({self.target_x:.1f}, {self.target_y:.1f})
Under fire: {"YES" if self.under_fire else "no"}
Aggression: {self.aggression:.1f}/1.0
Caution: {self.caution:.1f}/1.0

Nearby defenders:
{defenders_desc}

Allies: {allies_desc}

Choose ONE action. Reply with a single word on the first line:
ADVANCE - move directly toward target
FLANK - approach from the side
HIDE - take cover and wait
ATTACK - engage nearest defender
FLEE - retreat from danger

Then briefly explain your reasoning (1 sentence)."""

    def parse_llm_response(self, response: str) -> str:
        """Parse LLM response into a valid action string."""
        if not response:
            return "advance"

        # Check first word of first line for direct action match
        first_line = response.strip().split('\n')[0].strip().lower()
        first_word = first_line.split()[0] if first_line.split() else ""
        if first_word in VALID_ACTIONS:
            return first_word
        for keyword, action in ACTION_KEYWORDS.items():
            if first_word == keyword:
                return action

        # Check first line for keyword substring (prefer longer matches)
        sorted_keywords = sorted(ACTION_KEYWORDS.keys(), key=len, reverse=True)
        for keyword in sorted_keywords:
            if keyword in first_line:
                return ACTION_KEYWORDS[keyword]

        # Scan full response
        lower = response.lower()
        for keyword in sorted_keywords:
            if keyword in lower:
                return ACTION_KEYWORDS[keyword]

        # Default
        return "advance"

    def apply_action(self, action: str):
        """Apply a parsed action to change FSM state."""
        if action in ACTION_TO_STATE:
            self.state = ACTION_TO_STATE[action]
            # Refresh flank angle on new flank
            if action == "flank":
                self._flank_angle = random.choice([-1, 1]) * random.uniform(30, 60)

    def get_telemetry(self) -> dict:
        """Get current telemetry as a JSON-serializable dict."""
        return {
            'robot_id': self.hostile_id,
            'name': self.name,
            'asset_type': 'person',
            'position': {'x': round(self.x, 2), 'y': round(self.y, 2)},
            'heading': round(self.heading % 360, 1),
            'health': self.health,
            'max_health': self.max_health,
            'status': 'active' if self.alive else 'eliminated',
            'fsm_state': self.state.value,
            'alliance': 'hostile',
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
