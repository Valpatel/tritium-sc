# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""LLM fallback thought generator.

When Ollama is unavailable, produces context-aware scripted thoughts
so Amy always has an inner monologue. Thoughts are valid Lua function
calls parseable by parse_motor_output().

The system prefers gemma3:4b on localhost Ollama when available, and
falls back to this generator when the LLM is unreachable.
"""

from __future__ import annotations

import random
import urllib.request
from datetime import datetime


def check_ollama_available(host: str = "http://localhost:11434") -> bool:
    """Check if Ollama API is reachable."""
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


# -- Thought templates by category ------------------------------------------

_IDLE_THOUGHTS = [
    "All quiet on the perimeter. Sensors nominal.",
    "Nothing moving out there. Systems green.",
    "Monitoring the neighborhood. Everything looks calm.",
    "Quiet night. Running passive scans.",
    "All sectors clear. No contacts.",
    "Neighborhood is still. Keeping watch.",
    "Passive sensors active. No anomalies detected.",
    "Camera feeds nominal. No movement in any sector.",
    "Just watching. The streets are empty.",
    "All units standing by. Nothing to report.",
    "Scanning the perimeter. Clear on all fronts.",
    "The neighborhood sleeps. I keep vigil.",
]

_NIGHT_THOUGHTS = [
    "Deep night. Perfect conditions for an approach. Staying alert.",
    "Dark out there. Switching to enhanced sensitivity.",
    "Late hours. This is when they usually move.",
    "Night watch continues. Every shadow could be something.",
    "The darkness is both shield and threat. Maintaining vigilance.",
    "Night patrol sensors at maximum gain. Listening.",
]

_DAY_THOUGHTS = [
    "Daytime activity. Lots of pedestrians and vehicles. Filtering.",
    "Normal traffic patterns. Distinguishing civilians from threats.",
    "Busy morning. Lots of movement to track.",
    "Afternoon activity. Watching the usual patterns.",
    "Neighborhood is lively. Tracking all contacts.",
    "Standard daytime traffic. Nothing unusual yet.",
]

_COMBAT_THOUGHTS = [
    "Hostiles detected! Assessing threat vectors.",
    "Contact! Tracking {hostile_count} hostile targets.",
    "Multiple threats in the battlespace. Prioritizing targets.",
    "Engaging hostiles. Our defenders are in position.",
    "Enemy approaching from multiple vectors. Coordinating defense.",
    "Hostile activity increasing. Tightening the perimeter.",
    "Targets advancing. Our units are holding the line.",
    "Battle in progress. Monitoring all engagement zones.",
    "Threat level elevated. Deploying all available assets.",
    "Enemy contacts at {hostile_count}. Friendlies holding at {friendly_count}.",
]

_COMBAT_TACTICAL = [
    "Sector north showing enemy movement. Recommending repositioning.",
    "They are trying to flank us from the east. Adjusting coverage.",
    "Enemy concentration building. Need to spread our fire.",
    "Our turrets are covering the main approaches. Good position.",
    "The drones have eyes on the hostiles. Relaying positions.",
    "Rover is moving to intercept. Good hunting.",
    "Multiple waves incoming. Brace for sustained contact.",
    "The defenders are holding well. Keeping pressure on.",
]

_WAVE_THOUGHTS = [
    "Wave {wave} incoming. Stand ready.",
    "Wave {wave} engaged. Score: {score}.",
    "Defending against wave {wave}. Our units are performing well.",
    "Wave {wave} is testing our positions. Holding firm.",
]

_DISPATCH_TEMPLATES = [
    'dispatch("{unit_name}", {x:.1f}, {y:.1f})',
]


class FallbackThoughtGenerator:
    """Generates context-aware scripted thoughts when LLM is unavailable."""

    def __init__(self) -> None:
        self._last_thought: str = ""
        self._think_count: int = 0

    def generate(self, ctx: dict) -> str:
        """Generate a Lua function call based on context.

        Args:
            ctx: dict with optional keys:
                - hostile_count: int
                - friendly_count: int
                - game_active: bool
                - wave: int
                - score: int
                - hour: int (0-23)
                - friendlies: list[dict] with name, type, x, y
                - hostiles: list[dict] with name, x, y

        Returns:
            Valid Lua function call string (think/wait/dispatch).
        """
        hostile_count = ctx.get("hostile_count", 0)
        friendly_count = ctx.get("friendly_count", 0)
        game_active = ctx.get("game_active", False)
        wave = ctx.get("wave", 1)
        score = ctx.get("score", 0)
        hour = ctx.get("hour", datetime.now().hour)
        friendlies = ctx.get("friendlies", [])
        hostiles = ctx.get("hostiles", [])

        self._think_count += 1

        # During combat, sometimes produce dispatch actions
        if game_active and hostile_count > 0 and friendlies and hostiles:
            if random.random() < 0.15:
                return self._dispatch_action(friendlies, hostiles)

        # Idle wait (10% chance when nothing happening)
        if not game_active and hostile_count == 0 and random.random() < 0.10:
            return "wait(10)"

        # Select thought pool based on context
        thought = self._select_thought(
            hostile_count, friendly_count, game_active,
            wave, score, hour,
        )

        # Avoid repeating the exact same thought
        attempts = 0
        while thought == self._last_thought and attempts < 5:
            thought = self._select_thought(
                hostile_count, friendly_count, game_active,
                wave, score, hour,
            )
            attempts += 1

        self._last_thought = thought
        # Escape any quotes in the thought text
        escaped = thought.replace("\\", "\\\\").replace('"', '\\"')
        return f'think("{escaped}")'

    def _select_thought(
        self,
        hostile_count: int,
        friendly_count: int,
        game_active: bool,
        wave: int,
        score: int,
        hour: int,
    ) -> str:
        """Pick a thought from the appropriate pool."""
        if game_active and hostile_count > 0:
            # Active combat
            pool: list[str] = []
            if wave > 0:
                pool.extend(_WAVE_THOUGHTS)
            pool.extend(_COMBAT_THOUGHTS)
            if random.random() < 0.4:
                pool.extend(_COMBAT_TACTICAL)
            thought = random.choice(pool)
            return thought.format(
                hostile_count=hostile_count,
                friendly_count=friendly_count,
                wave=wave,
                score=score,
            )
        elif hostile_count > 0:
            # Hostiles present but not in game mode
            thought = random.choice(_COMBAT_THOUGHTS)
            return thought.format(
                hostile_count=hostile_count,
                friendly_count=friendly_count,
                wave=wave,
                score=score,
            )
        else:
            # Peaceful — time-of-day aware
            if 22 <= hour or hour < 6:
                pool = _NIGHT_THOUGHTS + _IDLE_THOUGHTS
            elif 6 <= hour < 10:
                pool = _DAY_THOUGHTS + _IDLE_THOUGHTS
            elif 10 <= hour < 17:
                pool = _DAY_THOUGHTS + _IDLE_THOUGHTS
            else:
                pool = _IDLE_THOUGHTS + _DAY_THOUGHTS
            return random.choice(pool)

    def _dispatch_action(
        self,
        friendlies: list[dict],
        hostiles: list[dict],
    ) -> str:
        """Generate a dispatch action toward the nearest hostile."""
        # Pick a mobile friendly
        mobile = [f for f in friendlies if f.get("type") in ("rover", "drone")]
        if not mobile:
            mobile = friendlies
        unit = random.choice(mobile)
        target = random.choice(hostiles)
        return f'dispatch("{unit["name"]}", {target["x"]:.1f}, {target["y"]:.1f})'
