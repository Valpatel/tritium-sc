# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ScenarioGenerator — LLM-based battle scenario context generation.

At the start of each battle round, generates rich narrative context via Ollama:
- Why is this battle happening?
- Who are the attackers?
- What's at stake?
- Weather/atmosphere
- Wave-specific briefings
- Loading screen messages

Each prompt requests structured JSON back from the LLM, which gets parsed
into scenario state. Uses gemma3:4b by default with scripted fallbacks.

The prompts are templates — each scenario is unique because the LLM generates
different content each time based on wave number, score, and context.
"""

from __future__ import annotations

import json
import random
import threading
from datetime import datetime
from typing import Optional


# -- Prompt templates (each requests structured JSON back) -------------------

SCENARIO_PROMPTS = {
    "battle_reason": (
        "Generate a brief reason why a neighborhood security battle is happening. "
        "Wave {wave} of {total_waves}. Score: {score}. Time: {time_of_day}. "
        "Respond in JSON format: {{\"reason\": \"...\", \"urgency\": \"low|medium|high|critical\"}}"
    ),
    "attacker_background": (
        "Generate a background for the attacking force in a neighborhood security scenario. "
        "Wave {wave}. They have sent {hostile_count} hostiles so far. "
        "Respond in JSON format: {{\"group_name\": \"...\", \"motivation\": \"...\", "
        "\"tactics\": \"...\", \"threat_level\": \"...\"}}"
    ),
    "neighborhood_history": (
        "Generate a brief history of a residential neighborhood that is now being defended "
        "by an AI security system. Wave {wave} of {total_waves}. "
        "Respond in JSON format: {{\"history\": \"...\", \"notable_features\": [\"...\"], "
        "\"residents_feel\": \"...\"}}"
    ),
    "stakes": (
        "What's at stake in this neighborhood defense scenario? Wave {wave} of {total_waves}. "
        "Score: {score}. Defenders have {friendly_count} units. "
        "Respond in JSON format: {{\"stakes\": \"...\", \"consequence_of_failure\": \"...\", "
        "\"reward_of_success\": \"...\"}}"
    ),
    "weather_atmosphere": (
        "Generate weather and atmospheric conditions for a neighborhood battle. "
        "Time: {time_of_day}. Season: {season}. "
        "Respond in JSON format: {{\"weather\": \"...\", \"visibility\": \"good|fair|poor\", "
        "\"temperature\": \"...\", \"mood\": \"...\"}}"
    ),
    "wave_briefing": (
        "Generate a tactical briefing for wave {wave} of {total_waves}. "
        "Current score: {score}. Previous wave had {prev_hostile_count} hostiles. "
        "Our forces: {friendly_count} defenders. "
        "Respond in JSON format: {{\"briefing\": \"...\", \"expected_threat\": \"...\", "
        "\"tactical_advice\": \"...\", \"morale\": \"...\"}}"
    ),
    "unit_orders": (
        "Generate standing orders for a {unit_type} unit named '{unit_name}' "
        "defending position ({x:.0f}, {y:.0f}). Wave {wave}. "
        "Respond in JSON format: {{\"primary_order\": \"...\", \"rules_of_engagement\": \"...\", "
        "\"backup_plan\": \"...\"}}"
    ),
    "aftermath": (
        "Generate an after-action summary for wave {wave}. "
        "Score: {score}. Kills: {kills}. Friendlies lost: {friendlies_lost}. "
        "Respond in JSON format: {{\"summary\": \"...\", \"lessons_learned\": \"...\", "
        "\"commendations\": \"...\", \"next_wave_warning\": \"...\"}}"
    ),
}


# -- Scripted fallback scenarios --------------------------------------------

_BATTLE_REASONS = [
    "A coordinated intrusion from the east side. Multiple contacts approaching under cover.",
    "Local gang activity escalating. They're testing our perimeter defenses.",
    "Unknown hostiles breaching the neighborhood's outer ring. Motives unclear.",
    "Intelligence suggests a probe-in-force. They want to map our defensive positions.",
    "Rival faction moving into the area. This is a territorial assertion.",
    "Retaliation strike following last night's incident. They're coming in force.",
    "Opportunistic raid during a power outage. Multiple entry points compromised.",
    "The neighborhood's been under surveillance for days. Tonight they make their move.",
]

_ATTACKER_BACKGROUNDS = [
    {"group_name": "Shadow Cell", "motivation": "Territory expansion", "tactics": "Probe and flank"},
    {"group_name": "Red Dawn Crew", "motivation": "Resource acquisition", "tactics": "Coordinated rush"},
    {"group_name": "The Outsiders", "motivation": "Reputation", "tactics": "Overwhelming force"},
    {"group_name": "Ghost Network", "motivation": "Intelligence gathering", "tactics": "Stealth infiltration"},
    {"group_name": "North Side Collective", "motivation": "Territorial dispute", "tactics": "Multi-prong assault"},
]

_NEIGHBORHOOD_HISTORIES = [
    "A quiet suburban cul-de-sac that's seen better days. The AI defense system was installed after a string of break-ins last summer.",
    "Former military housing, now civilian. The security infrastructure repurposed from base defenses. Residents sleep soundly knowing Amy watches.",
    "An upscale gated community where the homeowners association invested in state-of-the-art security. Best decision they ever made.",
]

_STAKES = [
    {"stakes": "The safety of 47 families", "consequence": "Breach of the perimeter", "reward": "Another peaceful night"},
    {"stakes": "Proving the AI defense concept works", "consequence": "Loss of community trust", "reward": "Expanded deployment"},
    {"stakes": "Protecting critical infrastructure", "consequence": "Service disruption", "reward": "Deterrence established"},
]

_WEATHER = [
    {"weather": "Clear night, full moon", "visibility": "good", "mood": "Eerie calm"},
    {"weather": "Light rain, overcast", "visibility": "fair", "mood": "Tense and damp"},
    {"weather": "Foggy, low visibility", "visibility": "poor", "mood": "Claustrophobic"},
    {"weather": "Clear afternoon, warm", "visibility": "good", "mood": "Deceptively peaceful"},
    {"weather": "Windy, scattered clouds", "visibility": "fair", "mood": "Restless"},
]

_LOADING_MESSAGES = [
    "Initializing defensive perimeter...",
    "Calibrating turret targeting systems...",
    "Loading satellite imagery...",
    "Analyzing threat vectors...",
    "Waking up the drones...",
    "Establishing communication links...",
    "Checking ammunition reserves...",
    "Reviewing patrol routes...",
    "Amy is thinking about the situation...",
    "Scanning for electromagnetic signatures...",
    "Building threat assessment model...",
    "Mapping building shadows for cover analysis...",
    "Loading NPC behavioral profiles...",
    "Generating hostile approach vectors...",
    "Synchronizing unit clocks...",
    "Warming up the neural network...",
]


class ScenarioGenerator:
    """Generates rich battle scenario context, optionally via LLM."""

    def __init__(self, model: str = "gemma3:4b") -> None:
        self._model = model
        self._current_scenario: dict | None = None
        self._lock = threading.Lock()

    def generate_scripted(
        self,
        wave: int = 1,
        total_waves: int = 10,
        score: int = 0,
        hostile_count: int = 0,
        friendly_count: int = 0,
    ) -> dict:
        """Generate a complete scenario using scripted templates."""
        # Scale scenario intensity by wave number
        intensity = wave / total_waves  # 0.1 to 1.0

        # Select appropriate content
        reason_idx = min(wave - 1, len(_BATTLE_REASONS) - 1)
        reason = _BATTLE_REASONS[reason_idx % len(_BATTLE_REASONS)]

        attacker = random.choice(_ATTACKER_BACKGROUNDS)
        neighborhood = random.choice(_NEIGHBORHOOD_HISTORIES)
        stakes = random.choice(_STAKES)
        weather = random.choice(_WEATHER)

        # Loading messages (3-6 per scenario)
        n_msgs = random.randint(3, 6)
        loading = random.sample(_LOADING_MESSAGES, min(n_msgs, len(_LOADING_MESSAGES)))

        # Wave briefing
        if wave <= 3:
            briefing = f"Wave {wave}: Light contact expected. Standard defensive posture."
        elif wave <= 6:
            briefing = f"Wave {wave}: Increasing hostile activity. Tighten the perimeter."
        elif wave <= 9:
            briefing = f"Wave {wave}: Heavy assault imminent. All units to battle stations."
        else:
            briefing = f"Wave {wave}: FINAL STAND. Everything they've got is coming. Hold the line."

        scenario = {
            "battle_reason": reason,
            "attacker_background": attacker,
            "neighborhood_history": neighborhood,
            "stakes": stakes["stakes"],
            "consequence_of_failure": stakes["consequence"],
            "reward_of_success": stakes["reward"],
            "weather": weather,
            "wave_briefing": briefing,
            "loading_messages": loading,
            "wave": wave,
            "total_waves": total_waves,
            "score": score,
            "intensity": intensity,
            "generated_by": "scripted",
        }

        with self._lock:
            self._current_scenario = scenario
        return scenario

    def build_prompts(
        self,
        wave: int = 1,
        total_waves: int = 10,
        score: int = 0,
        hostile_count: int = 0,
        friendly_count: int = 0,
        prev_hostile_count: int = 0,
    ) -> dict[str, str]:
        """Build all LLM prompts for scenario generation.

        Returns dict[prompt_key, formatted_prompt_string].
        Each prompt is designed to return structured JSON.
        """
        now = datetime.now()
        hour = now.hour
        if hour < 6:
            tod = "late night"
        elif hour < 12:
            tod = "morning"
        elif hour < 17:
            tod = "afternoon"
        elif hour < 21:
            tod = "evening"
        else:
            tod = "night"

        month = now.month
        if month in (3, 4, 5):
            season = "spring"
        elif month in (6, 7, 8):
            season = "summer"
        elif month in (9, 10, 11):
            season = "autumn"
        else:
            season = "winter"

        ctx = {
            "wave": wave,
            "total_waves": total_waves,
            "score": score,
            "hostile_count": hostile_count,
            "friendly_count": friendly_count,
            "prev_hostile_count": prev_hostile_count,
            "time_of_day": tod,
            "season": season,
        }

        prompts = {}
        for key, template in SCENARIO_PROMPTS.items():
            if key == "unit_orders":
                continue  # Unit-specific, not batch
            try:
                prompts[key] = template.format(**ctx)
            except KeyError:
                # Template uses keys not in ctx — use what we have
                prompts[key] = template.format_map({**ctx, "unit_type": "", "unit_name": "", "x": 0, "y": 0, "kills": 0, "friendlies_lost": 0})

        return prompts

    def generate_via_llm(
        self,
        wave: int = 1,
        total_waves: int = 10,
        score: int = 0,
    ) -> dict | None:
        """Generate scenario via Ollama LLM (blocking call).

        Returns parsed scenario dict, or None on failure.
        Falls back to scripted on any error.
        """
        try:
            from engine.perception.vision import ollama_chat
        except ImportError:
            return None

        prompts = self.build_prompts(wave=wave, total_waves=total_waves, score=score)
        scenario = {}

        for key, prompt in prompts.items():
            try:
                response = ollama_chat(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": "You generate structured JSON for a neighborhood security game. Always respond with valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                )
                text = response.get("message", {}).get("content", "").strip()
                # Try to parse JSON
                parsed = json.loads(text)
                scenario[key] = parsed
            except Exception:
                # Fall back to scripted for this field
                pass

        if not scenario:
            return None

        scenario["wave"] = wave
        scenario["total_waves"] = total_waves
        scenario["score"] = score
        scenario["generated_by"] = "llm"
        scenario["loading_messages"] = random.sample(
            _LOADING_MESSAGES, min(5, len(_LOADING_MESSAGES))
        )

        with self._lock:
            self._current_scenario = scenario
        return scenario

    def get_current_scenario(self) -> dict | None:
        """Get the current cached scenario."""
        with self._lock:
            return self._current_scenario

    def reset(self) -> None:
        """Clear the cached scenario."""
        with self._lock:
            self._current_scenario = None
