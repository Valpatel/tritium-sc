# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MissionDirector — unified LLM-driven scenario orchestrator.

Generates complete game scenarios via structured prompts to Ollama:
1. Selects game mode (battle, defense, patrol, custom)
2. Generates scenario context (why, who, stakes, weather)
3. Determines unit composition and placement
4. Assigns motives and objectives to all units
5. Sets win/loss conditions
6. Streams generation progress events for frontend modal

Each step sends a structured JSON prompt to the LLM and parses the response.
Falls back to scripted defaults when Ollama is unavailable.
All progress is emitted as EventBus events so the frontend modal can display
real-time generation status, prompts, and LLM responses.
"""

from __future__ import annotations

import json
import math
import random
import re
import threading
from typing import TYPE_CHECKING, Any, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore

from .poi_data import (
    POI,
    MissionArea,
    fetch_pois,
    pick_mission_center,
    build_mission_area,
    get_poi_context_text,
    place_defenders_around_buildings,
)

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

# Default map center: West Dublin, California
_DEFAULT_MAP_CENTER = (37.7159, -121.8960)

# Radius per game mode (meters)
_MODE_RADIUS = {
    "battle": 200,
    "defense": 150,
    "patrol": 300,
    "escort": 400,
    "civil_unrest": 200,
    "drone_swarm": 250,
}


# -- Game mode definitions ---------------------------------------------------

GAME_MODES = {
    "battle": {
        "description": "10-wave combat defense against hostile forces",
        "prompt": (
            "Design a 10-wave neighborhood defense battle scenario. "
            "Include the reason for the attack, the attacking force, and stakes. "
            "Respond in JSON format: "
            '{"reason": "...", "attacker": "...", "stakes": "...", '
            '"waves": 10, "difficulty": "normal", "theme": "..."}'
        ),
        "default_waves": 10,
        "default_defenders": [
            {"type": "turret", "count": 2},
            {"type": "rover", "count": 2},
            {"type": "drone", "count": 1},
        ],
        "default_hostiles_per_wave": 4,
    },
    "defense": {
        "description": "Hold position against sustained assault",
        "prompt": (
            "Design a sustained defense scenario for a neighborhood security system. "
            "The defenders must hold a critical position against waves of attackers. "
            "Respond in JSON format: "
            '{"objective": "...", "location": "...", "threat_level": "high", '
            '"waves": 5, "reinforcements": true, "theme": "..."}'
        ),
        "default_waves": 5,
        "default_defenders": [
            {"type": "turret", "count": 3},
            {"type": "heavy_turret", "count": 1},
            {"type": "rover", "count": 1},
        ],
        "default_hostiles_per_wave": 6,
    },
    "patrol": {
        "description": "Patrol and secure the neighborhood perimeter",
        "prompt": (
            "Design a patrol and security scenario for a neighborhood. "
            "Units must patrol routes and respond to intrusions. "
            "Respond in JSON format: "
            '{"patrol_routes": 3, "threat_type": "...", "time_of_day": "...", '
            '"duration_minutes": 10, "incident_chance": 0.3, "theme": "..."}'
        ),
        "default_waves": 3,
        "default_defenders": [
            {"type": "rover", "count": 3},
            {"type": "drone", "count": 2},
            {"type": "scout_drone", "count": 1},
        ],
        "default_hostiles_per_wave": 2,
    },
    "escort": {
        "description": "Escort VIP through hostile territory",
        "prompt": (
            "Design an escort mission through a hostile neighborhood. "
            "A VIP must be escorted safely from point A to point B. "
            "Respond in JSON format: "
            '{"vip_name": "...", "start": [0,0], "end": [100,100], '
            '"ambush_points": 3, "escort_size": 4, "theme": "..."}'
        ),
        "default_waves": 4,
        "default_defenders": [
            {"type": "rover", "count": 3},
            {"type": "drone", "count": 1},
            {"type": "tank", "count": 1},
        ],
        "default_hostiles_per_wave": 5,
    },
    "civil_unrest": {
        "description": "Crowd control and de-escalation scenario",
        "prompt": (
            "Design a crowd control and de-escalation scenario for a neighborhood security system. "
            "A large crowd has gathered, with hidden instigators trying to incite violence. "
            "The security system must identify instigators, protect civilians, and restore order "
            "WITHOUT lethal force. Only rovers, drones, and scout drones are available. "
            "Respond in JSON format: "
            '{"trigger_event": "...", "crowd_size": 100, "instigator_count": 10, '
            '"escalation_phases": 8, "civilian_sentiment": "angry|scared|mixed", '
            '"time_of_day": "...", "theme": "..."}'
        ),
        "default_waves": 8,
        "default_defenders": [
            {"type": "rover", "count": 3},
            {"type": "drone", "count": 2},
            {"type": "scout_drone", "count": 2},
        ],
        "default_hostiles_per_wave": 15,
    },
    "drone_swarm": {
        "description": "Mass drone attack defense with AA priority",
        "prompt": (
            "Design a mass drone attack defense scenario for a neighborhood security system. "
            "Waves of hostile drones (scout, attack, bomber types) assault critical infrastructure. "
            "Defenders use missile turrets, counter-drones, and EMP to protect a key building. "
            "Respond in JSON format: "
            '{"target_building": "...", "drone_origin": "north|south|east|west|multi", '
            '"total_drones": 150, "attack_waves": 10, "bomber_waves": [7, 8, 9, 10], '
            '"emp_available": true, "theme": "..."}'
        ),
        "default_waves": 10,
        "default_defenders": [
            {"type": "missile_turret", "count": 2},
            {"type": "drone", "count": 3},
            {"type": "turret", "count": 1},
            {"type": "scout_drone", "count": 1},
            {"type": "rover", "count": 1},
        ],
        "default_hostiles_per_wave": 10,
    },
}


# -- Generation step pipeline -----------------------------------------------

GENERATION_STEPS = [
    {
        "id": "scenario_context",
        "label": "Generating scenario context...",
        "prompt_template": (
            "Generate the backstory for a {game_mode} scenario in a neighborhood security simulation. "
            "Why is this happening? Who are the attackers? What's at stake? "
            "Time of day: {time_of_day}. Season: {season}. "
            "Respond in JSON: "
            '{{"reason": "...", "attacker_name": "...", "attacker_motivation": "...", '
            '"stakes": "...", "urgency": "low|medium|high|critical", "atmosphere": "..."}}'
        ),
    },
    {
        "id": "unit_composition",
        "label": "Planning force composition...",
        "prompt_template": (
            "Design the defending force for a {game_mode} scenario. "
            "Available unit types: turret, heavy_turret, missile_turret, rover, tank, apc, "
            "drone, scout_drone. Map is 400x400 meters centered at (0,0). "
            "Respond in JSON: "
            '{{"defenders": [{{"type": "...", "position": [x, y], "name": "..."}}], '
            '"wave_hostiles": [{{"wave": 1, "count": 3, "types": ["person"]}}]}}'
        ),
    },
    {
        "id": "unit_motives",
        "label": "Assigning unit objectives...",
        "prompt_template": (
            "Assign tactical objectives to each defending unit in a {game_mode} scenario. "
            "Units: {unit_list}. "
            "Respond in JSON: "
            '{{"objectives": [{{"unit_name": "...", "primary": "...", "standing_orders": "...", '
            '"rules_of_engagement": "..."}}]}}'
        ),
    },
    {
        "id": "win_conditions",
        "label": "Setting victory conditions...",
        "prompt_template": (
            "Define win and loss conditions for a {game_mode} scenario. "
            "Context: {context_summary}. "
            "Respond in JSON: "
            '{{"victory": {{"condition": "...", "description": "..."}}, '
            '"defeat": {{"condition": "...", "description": "..."}}, '
            '"bonus_objectives": [{{"name": "...", "description": "...", "reward": 500}}]}}'
        ),
    },
    {
        "id": "weather_atmosphere",
        "label": "Setting weather and atmosphere...",
        "prompt_template": (
            "Generate weather and atmospheric conditions for a {game_mode} battle scenario. "
            "Time: {time_of_day}. Season: {season}. Mood: {atmosphere}. "
            "Respond in JSON: "
            '{{"weather": "...", "visibility": "good|fair|poor", "temperature": "...", '
            '"wind": "...", "special_conditions": "...", "mood_description": "..."}}'
        ),
    },
    {
        "id": "loading_messages",
        "label": "Generating briefing messages...",
        "prompt_template": (
            "Generate 8 loading screen messages for a {game_mode} scenario. "
            "Context: {context_summary}. "
            "Messages should be short system-style status lines (like 'Calibrating targeting systems...'). "
            "Respond in JSON: "
            '{{"messages": ["...", "...", "..."]}}'
        ),
    },
    {
        "id": "wave_briefings",
        "label": "Planning wave tactics...",
        "prompt_template": (
            "Generate tactical briefings for {wave_count} waves in a {game_mode} scenario. "
            "Escalate intensity across waves. "
            "Respond in JSON: "
            '{{"waves": [{{"wave": 1, "briefing": "...", "threat_level": "...", '
            '"enemy_tactic": "...", "intel": "..."}}]}}'
        ),
    },
    {
        "id": "wave_composition",
        "label": "Determining hostile force composition...",
        "prompt_template": (
            "Determine the exact hostile force composition for {wave_count} waves in a {game_mode} scenario. "
            "Available hostile types: person (speed 1.5, health 80), hostile_vehicle (speed 2.5, health 200), "
            "hostile_leader (speed 1.2, health 150). "
            "Early waves should be light (mostly person). Later waves add vehicles and leaders. "
            "Respond in JSON: "
            '{{"waves": [{{"wave": 1, "groups": [{{"type": "person", "count": 4, "speed": 1.5, "health": 80}}], '
            '"speed_mult": 1.0, "health_mult": 1.0}}]}}'
        ),
    },
]


# -- Scripted fallback data -------------------------------------------------

_SCRIPTED_CONTEXT_TEMPLATES = [
    {
        "reason": "A coordinated assault on {center_name}. Multiple contacts approaching via {streets}.",
        "attacker_name": "Shadow Cell",
        "attacker_motivation": "Territory expansion",
        "stakes": "The safety of 47 families near {center_address}",
        "urgency": "high",
        "atmosphere": "Tense calm before the storm",
    },
    {
        "reason": "Intelligence suggests a probe-in-force targeting {center_name}. They want to map our defensive positions.",
        "attacker_name": "Ghost Network",
        "attacker_motivation": "Intelligence gathering",
        "stakes": "Proving the AI defense concept works in West Dublin",
        "urgency": "medium",
        "atmosphere": "Fog rolling in from the west",
    },
    {
        "reason": "Retaliation strike on {center_name} following last night's incident. They're coming via {streets}.",
        "attacker_name": "Red Dawn Crew",
        "attacker_motivation": "Revenge",
        "stakes": "Protecting critical infrastructure at {center_address}",
        "urgency": "critical",
        "atmosphere": "Electric tension in the air",
    },
]

# Fallback contexts (no POI data available)
_SCRIPTED_CONTEXTS_FALLBACK = [
    {
        "reason": "A coordinated assault from the east. Multiple contacts approaching under cover.",
        "attacker_name": "Shadow Cell",
        "attacker_motivation": "Territory expansion",
        "stakes": "The safety of 47 families",
        "urgency": "high",
        "atmosphere": "Tense calm before the storm",
    },
    {
        "reason": "Intelligence suggests a probe-in-force. They want to map our defensive positions.",
        "attacker_name": "Ghost Network",
        "attacker_motivation": "Intelligence gathering",
        "stakes": "Proving the AI defense concept works",
        "urgency": "medium",
        "atmosphere": "Fog rolling in from the west",
    },
    {
        "reason": "Retaliation strike following last night's incident. They're coming in force.",
        "attacker_name": "Red Dawn Crew",
        "attacker_motivation": "Revenge",
        "stakes": "Protecting critical infrastructure",
        "urgency": "critical",
        "atmosphere": "Electric tension in the air",
    },
]

_SCRIPTED_WEATHER = [
    {"weather": "Clear night, full moon", "visibility": "good", "temperature": "Cool",
     "wind": "Light breeze", "special_conditions": "None", "mood_description": "Eerie calm"},
    {"weather": "Light rain, overcast", "visibility": "fair", "temperature": "Mild",
     "wind": "Gusty", "special_conditions": "Wet surfaces", "mood_description": "Tense and damp"},
    {"weather": "Foggy, low visibility", "visibility": "poor", "temperature": "Cold",
     "wind": "Still", "special_conditions": "Sound carries further", "mood_description": "Claustrophobic"},
]

_SCRIPTED_LOADING = [
    "Initializing defensive perimeter...",
    "Calibrating turret targeting systems...",
    "Loading satellite imagery of West Dublin neighborhood...",
    "Analyzing threat vectors along street approaches...",
    "Waking up the drones...",
    "Establishing communication links...",
    "Checking ammunition reserves...",
    "Reviewing neighborhood patrol routes...",
    "Scanning for electromagnetic signatures...",
    "Building threat assessment model...",
    "Mapping building shadows for cover analysis...",
    "Generating hostile approach vectors...",
    "Synchronizing unit clocks...",
    "Warming up the neural network...",
    "Querying intelligence database...",
    "Estimating hostile force composition...",
]


# -- Civil Unrest scripted data ---------------------------------------------

_CIVIL_UNREST_CONTEXT_TEMPLATES = [
    {
        "reason": "A contentious zoning decision has drawn hundreds of protesters to {center_name}. "
                  "Agitators are embedded in the crowd, turning a legal assembly into a flashpoint.",
        "attacker_name": "Embedded Agitators",
        "attacker_motivation": "Provoke overreaction from security forces",
        "stakes": "Protecting both the crowd and {center_address} without a PR disaster",
        "urgency": "high",
        "atmosphere": "Chanting echoes off the buildings, punctuated by breaking glass",
    },
    {
        "reason": "A viral social media post has mobilized a flash mob at {center_name}. "
                  "What started as a peaceful vigil is being hijacked by outside agitators arriving via {streets}.",
        "attacker_name": "Outside Agitators Network",
        "attacker_motivation": "Create chaos for media attention",
        "stakes": "De-escalate before the situation becomes national news",
        "urgency": "medium",
        "atmosphere": "Phone flashlights flicker like a sea of stars, but the mood is shifting",
    },
    {
        "reason": "A power outage has triggered looting near {center_name}. Opportunistic criminals are "
                  "using the blackout as cover. Most people on the street are scared residents, not looters.",
        "attacker_name": "Opportunistic Looters",
        "attacker_motivation": "Theft under cover of darkness",
        "stakes": "Restoring order near {center_address} while protecting displaced residents",
        "urgency": "critical",
        "atmosphere": "Emergency lights cast red shadows. Car alarms compete with distant sirens",
    },
    {
        "reason": "A labor dispute at {center_name} has escalated. Striking workers have blocked {streets} "
                  "and unknown provocateurs are inciting violence to discredit the movement.",
        "attacker_name": "Unidentified Provocateurs",
        "attacker_motivation": "Sabotage legitimate labor action through violence",
        "stakes": "Identify provocateurs without suppressing the legal protest at {center_address}",
        "urgency": "medium",
        "atmosphere": "Bullhorns and chanting mix with the smell of smoke from burning tires",
    },
]

_CIVIL_UNREST_CONTEXTS_FALLBACK = [
    {
        "reason": "A contentious public decision has drawn hundreds of protesters. "
                  "Agitators are embedded in the crowd, turning a legal assembly into a flashpoint.",
        "attacker_name": "Embedded Agitators",
        "attacker_motivation": "Provoke overreaction from security forces",
        "stakes": "Protecting the crowd and infrastructure without escalating",
        "urgency": "high",
        "atmosphere": "Chanting echoes off the buildings, punctuated by breaking glass",
    },
    {
        "reason": "A viral social media post has mobilized a flash mob. "
                  "What started as a peaceful vigil is being hijacked by outside agitators.",
        "attacker_name": "Outside Agitators Network",
        "attacker_motivation": "Create chaos for media attention",
        "stakes": "De-escalate before the situation becomes national news",
        "urgency": "medium",
        "atmosphere": "Phone flashlights flicker like a sea of stars, but the mood is shifting",
    },
    {
        "reason": "A power outage has triggered looting in the area. Opportunistic criminals are "
                  "using the blackout as cover. Most people on the street are scared residents, not looters.",
        "attacker_name": "Opportunistic Looters",
        "attacker_motivation": "Theft under cover of darkness",
        "stakes": "Restoring order while protecting displaced residents",
        "urgency": "critical",
        "atmosphere": "Emergency lights cast red shadows. Car alarms compete with distant sirens",
    },
    {
        "reason": "A labor dispute has escalated. Striking workers have blocked key roads "
                  "and unknown provocateurs are inciting violence to discredit the movement.",
        "attacker_name": "Unidentified Provocateurs",
        "attacker_motivation": "Sabotage legitimate labor action through violence",
        "stakes": "Identify provocateurs without suppressing the legal protest",
        "urgency": "medium",
        "atmosphere": "Bullhorns and chanting mix with the smell of smoke from burning tires",
    },
]

_CIVIL_UNREST_LOADING = [
    "Activating crowd monitoring sensors...",
    "Calibrating non-lethal response protocols...",
    "Loading facial recognition watchlist...",
    "Mapping crowd density zones...",
    "Establishing communication cordons...",
    "Deploying overwatch drones...",
    "Analyzing social media feeds for flash mob indicators...",
    "Loading de-escalation playbook...",
    "Reviewing rules of engagement: RESTRICTIVE...",
    "Identifying critical infrastructure in area...",
    "Scanning for known agitator signatures...",
    "Establishing safe corridors for civilian egress...",
]

_CIVIL_UNREST_WEATHER = [
    {"weather": "Warm evening, streetlights on", "visibility": "good", "temperature": "Warm",
     "wind": "Still", "special_conditions": "Urban heat island", "mood_description": "Charged atmosphere"},
    {"weather": "Overcast afternoon, drizzle", "visibility": "fair", "temperature": "Cool",
     "wind": "Light", "special_conditions": "Slick sidewalks", "mood_description": "Tension building under gray skies"},
    {"weather": "Hot midday sun", "visibility": "good", "temperature": "Hot",
     "wind": "None", "special_conditions": "Heat stress on crowd", "mood_description": "Tempers rising with the heat"},
]

# Civil unrest wave composition — 8 waves matching spec section 2.2 table
# Keys: wave, name, civilians, instigators, vehicles, speed_mult, health_mult
_CIVIL_UNREST_WAVES = [
    {"wave": 1, "name": "Peaceful Assembly",  "civilians": 12, "instigators":  0, "vehicles": 0, "speed_mult": 0.5, "health_mult": 0.8},
    {"wave": 2, "name": "Heated Protest",      "civilians": 15, "instigators":  2, "vehicles": 0, "speed_mult": 0.6, "health_mult": 0.8},
    {"wave": 3, "name": "Isolated Scuffles",   "civilians": 18, "instigators":  4, "vehicles": 0, "speed_mult": 0.7, "health_mult": 1.0},
    {"wave": 4, "name": "Coordinated Riot",    "civilians": 20, "instigators":  6, "vehicles": 1, "speed_mult": 0.8, "health_mult": 1.0},
    {"wave": 5, "name": "Vehicular Chaos",     "civilians": 15, "instigators":  5, "vehicles": 3, "speed_mult": 1.0, "health_mult": 1.2},
    {"wave": 6, "name": "Looting Surge",       "civilians": 25, "instigators":  8, "vehicles": 2, "speed_mult": 1.1, "health_mult": 1.0},
    {"wave": 7, "name": "Armed Standoff",      "civilians": 10, "instigators":  8, "vehicles": 2, "speed_mult": 0.6, "health_mult": 1.5},
    {"wave": 8, "name": "Final Escalation",    "civilians": 20, "instigators": 10, "vehicles": 4, "speed_mult": 1.2, "health_mult": 1.5},
]


# -- Drone Swarm scripted data ----------------------------------------------

_DRONE_SWARM_CONTEXT_TEMPLATES = [
    {
        "reason": "Unidentified drone swarms detected on approach vectors toward {center_name}. "
                  "SIGINT suggests a coordinated attack on rooftop infrastructure. ETA 2 minutes.",
        "attacker_name": "Unknown Drone Operator",
        "attacker_motivation": "Destroy communications infrastructure",
        "stakes": "The communications relay at {center_address} serves 12,000 residents",
        "urgency": "critical",
        "atmosphere": "A low buzzing grows louder from the east. Shadows cross the streetlights",
    },
    {
        "reason": "A rogue drone fleet has been spotted assembling 2km north of {center_name}. "
                  "Pattern analysis indicates a multi-wave saturation attack incoming via {streets}.",
        "attacker_name": "Phantom Swarm",
        "attacker_motivation": "Test neighborhood defenses for future operations",
        "stakes": "Proving the AA defense grid can protect {center_address}",
        "urgency": "high",
        "atmosphere": "Stars disappear behind a moving cloud of blinking red lights",
    },
    {
        "reason": "Commercial delivery drones near {center_name} have been hijacked remotely. "
                  "Their payload bays have been weaponized. Friendly drones are scrambling to intercept.",
        "attacker_name": "Hijacked Commercial Fleet",
        "attacker_motivation": "Weaponized commercial infrastructure",
        "stakes": "Neutralize the hijacked fleet before they reach {center_address}",
        "urgency": "critical",
        "atmosphere": "The familiar hum of delivery drones takes on a menacing tone",
    },
    {
        "reason": "An underground drone racing league has been repurposed for an attack on {center_name}. "
                  "Racing drones modified with improvised weapons are approaching from {streets}.",
        "attacker_name": "Modded Racing Swarm",
        "attacker_motivation": "Proving ground for weaponized hobby drones",
        "stakes": "Protecting the solar array and HVAC systems at {center_address}",
        "urgency": "high",
        "atmosphere": "High-pitched whines of racing motors echo through the streets",
    },
]

_DRONE_SWARM_CONTEXTS_FALLBACK = [
    {
        "reason": "Unidentified drone swarms detected on multiple approach vectors. "
                  "SIGINT suggests a coordinated attack on critical infrastructure.",
        "attacker_name": "Unknown Drone Operator",
        "attacker_motivation": "Destroy communications infrastructure",
        "stakes": "The communications relay serves 12,000 residents",
        "urgency": "critical",
        "atmosphere": "A low buzzing grows louder from the east",
    },
    {
        "reason": "A rogue drone fleet has been spotted assembling nearby. "
                  "Pattern analysis indicates a multi-wave saturation attack incoming.",
        "attacker_name": "Phantom Swarm",
        "attacker_motivation": "Test neighborhood defenses for future operations",
        "stakes": "Proving the AA defense grid can hold",
        "urgency": "high",
        "atmosphere": "Stars disappear behind a moving cloud of blinking red lights",
    },
    {
        "reason": "Commercial delivery drones in the area have been hijacked remotely. "
                  "Their payload bays have been weaponized. Friendly drones are scrambling.",
        "attacker_name": "Hijacked Commercial Fleet",
        "attacker_motivation": "Weaponized commercial infrastructure",
        "stakes": "Neutralize the hijacked fleet before they reach the objective",
        "urgency": "critical",
        "atmosphere": "The familiar hum of delivery drones takes on a menacing tone",
    },
    {
        "reason": "An underground drone racing league has been repurposed for an attack. "
                  "Racing drones modified with improvised weapons are approaching.",
        "attacker_name": "Modded Racing Swarm",
        "attacker_motivation": "Proving ground for weaponized hobby drones",
        "stakes": "Protecting rooftop infrastructure from precision strikes",
        "urgency": "high",
        "atmosphere": "High-pitched whines of racing motors echo through the streets",
    },
]

_DRONE_SWARM_LOADING = [
    "Activating anti-air tracking radar...",
    "Loading missile turret targeting firmware...",
    "Calibrating drone intercept algorithms...",
    "Scanning airspace for hostile signatures...",
    "Arming missile tubes (20 rounds per launcher)...",
    "Launching counter-drone interceptors...",
    "Establishing aerial deconfliction zones...",
    "Warming up EMP capacitor banks...",
    "Mapping 3D threat envelope...",
    "Loading hostile drone recognition profiles...",
    "Synchronizing AA fire control network...",
    "Calculating intercept trajectories...",
]

_DRONE_SWARM_WEATHER = [
    {"weather": "Clear sky, high visibility", "visibility": "good", "temperature": "Cool",
     "wind": "Light crosswind", "special_conditions": "Good radar conditions",
     "mood_description": "Perfect hunting weather for anti-air"},
    {"weather": "Low clouds at 200m", "visibility": "fair", "temperature": "Mild",
     "wind": "Moderate gusts", "special_conditions": "Drones may use cloud cover",
     "mood_description": "They could be hiding above the cloud layer"},
    {"weather": "Night, clear, new moon", "visibility": "poor", "temperature": "Cold",
     "wind": "Still", "special_conditions": "Thermal signatures only",
     "mood_description": "Darkness favors the swarm. Rely on sensors, not eyes"},
]

# Drone swarm wave composition — 10 waves matching spec section 3.2 table
# Keys: wave, name, scout, attack, bomber, speed_mult, health_mult
_DRONE_SWARM_WAVES = [
    {"wave":  1, "name": "Probing Flight",       "scout": 5, "attack":  0, "bomber": 0, "speed_mult": 0.8, "health_mult": 0.7},
    {"wave":  2, "name": "First Strike",          "scout": 3, "attack":  4, "bomber": 0, "speed_mult": 1.0, "health_mult": 1.0},
    {"wave":  3, "name": "Harassment Run",         "scout": 4, "attack":  6, "bomber": 1, "speed_mult": 1.0, "health_mult": 1.0},
    {"wave":  4, "name": "Coordinated Assault",    "scout": 3, "attack":  8, "bomber": 2, "speed_mult": 1.1, "health_mult": 1.2},
    {"wave":  5, "name": "Saturation Attack",      "scout": 2, "attack": 12, "bomber": 3, "speed_mult": 1.2, "health_mult": 1.0},
    {"wave":  6, "name": "Electronic Probe",       "scout": 8, "attack":  5, "bomber": 0, "speed_mult": 1.3, "health_mult": 1.0},
    {"wave":  7, "name": "Bomber Wave",            "scout": 0, "attack":  6, "bomber": 8, "speed_mult": 0.9, "health_mult": 1.5},
    {"wave":  8, "name": "Adaptive Swarm",         "scout": 4, "attack": 10, "bomber": 4, "speed_mult": 1.3, "health_mult": 1.3},
    {"wave":  9, "name": "Overwhelming Force",     "scout": 6, "attack": 15, "bomber": 6, "speed_mult": 1.4, "health_mult": 1.2},
    {"wave": 10, "name": "FINAL SWARM",            "scout": 8, "attack": 20, "bomber": 8, "speed_mult": 1.5, "health_mult": 1.5},
]


# -- Unit placement helpers --------------------------------------------------

def _place_defenders(game_mode: str, map_bounds: float = 200.0) -> list[dict]:
    """Generate scripted defender placements for a game mode."""
    mode = GAME_MODES.get(game_mode, GAME_MODES["battle"])
    units = []
    unit_num = 1

    for spec in mode["default_defenders"]:
        for i in range(spec["count"]):
            angle = (unit_num / 8) * 2 * math.pi + random.uniform(-0.3, 0.3)
            radius = map_bounds * 0.3 + random.uniform(-20, 20)
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            units.append({
                "type": spec["type"],
                "alliance": "friendly",
                "position": [round(x, 1), round(y, 1)],
                "name": f"{spec['type'].title().replace('_', '-')}-{unit_num:02d}",
            })
            unit_num += 1

    return units


# -- MissionDirector --------------------------------------------------------

class MissionDirector:
    """Unified LLM-driven scenario orchestrator.

    Generates complete game scenarios via structured prompts to Ollama.
    Falls back to scripted defaults when LLM is unavailable.
    Emits progress events for the frontend modal.
    """

    def __init__(
        self,
        event_bus: EventBus,
        model: str = "gemma3:4b",
        ollama_host: str = "http://localhost:8081",
        map_center: tuple[float, float] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self.model = model
        self._ollama_host = ollama_host
        self._map_center = map_center if map_center is not None else _DEFAULT_MAP_CENTER
        self._mission_area: MissionArea | None = None
        self._current_scenario: dict | None = None
        self._lock = threading.Lock()

    # -- Model discovery ----------------------------------------------------

    def list_available_models(self) -> list[str]:
        """List available Ollama models."""
        if requests is None:
            return []
        try:
            # Try llama-server /v1/models first, then ollama /api/tags
            is_llama = any(p in self._ollama_host for p in [":8081", ":8082", ":8083"])
            endpoint = "/v1/models" if is_llama else "/api/tags"
            resp = requests.get(f"{self._ollama_host}{endpoint}", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if is_llama:
                    return [m.get("id", "") for m in data.get("data", [])]
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    # -- POI-driven mission area --------------------------------------------

    def _prepare_mission_area(self, game_mode: str) -> None:
        """Fetch POIs, pick center, build MissionArea.

        Sets self._mission_area on success; leaves it None if POIs
        are unavailable or empty.
        """
        lat, lng = self._map_center
        radius = _MODE_RADIUS.get(game_mode, 200)

        try:
            pois = fetch_pois(lat, lng, radius_m=500)
        except Exception:
            pois = []

        if not pois:
            self._mission_area = None
            return

        center = pick_mission_center(pois)
        if center is None:
            self._mission_area = None
            return

        self._mission_area = build_mission_area(center, pois, radius_m=radius)

    def _resolve_context_template(
        self,
        template: dict,
        fallback_list: list[dict] | None = None,
    ) -> dict:
        """Fill {center_name}, {center_address}, {streets} in a context template."""
        if self._mission_area is None:
            # Strip template placeholders, use clean fallback
            fb = fallback_list if fallback_list is not None else _SCRIPTED_CONTEXTS_FALLBACK
            return random.choice(fb)

        area = self._mission_area
        center_name = area.center_poi.name or "the objective"
        center_address = area.center_poi.address or center_name
        streets = ", ".join(area.streets[:3]) if area.streets else "multiple approaches"

        result = {}
        for key, value in template.items():
            if isinstance(value, str):
                result[key] = value.format(
                    center_name=center_name,
                    center_address=center_address,
                    streets=streets,
                )
            else:
                result[key] = value
        return result

    # -- Prompt building ----------------------------------------------------

    def build_prompt(self, step_id: str, **ctx) -> str:
        """Build a prompt for a given generation step."""
        from datetime import datetime

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

        defaults = {
            "game_mode": "battle",
            "time_of_day": tod,
            "season": season,
            "unit_list": "",
            "context_summary": "",
            "atmosphere": "",
            "wave_count": 10,
        }
        defaults.update(ctx)

        # Inject POI context into prompt when available
        poi_context = ""
        if self._mission_area is not None:
            poi_context = get_poi_context_text(self._mission_area)

        for step in GENERATION_STEPS:
            if step["id"] == step_id:
                try:
                    base_prompt = step["prompt_template"].format(**defaults)
                except KeyError:
                    base_prompt = step["prompt_template"].format_map(defaults)
                if poi_context:
                    base_prompt = f"{poi_context}\n\n{base_prompt}"
                return base_prompt

        # Fallback to game mode prompt
        mode = GAME_MODES.get(ctx.get("game_mode", "battle"), GAME_MODES["battle"])
        return mode["prompt"]

    # -- Response parsing ---------------------------------------------------

    def parse_llm_response(self, raw: str, step_id: str = "") -> dict | None:
        """Parse structured JSON from LLM response text.

        Handles common LLM quirks:
        - JSON wrapped in markdown code blocks
        - Extra whitespace/newlines
        - Trailing commas (attempt)
        """
        text = raw.strip()

        # Strip markdown code blocks
        md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if md_match:
            text = md_match.group(1).strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try finding JSON object in text
        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except json.JSONDecodeError:
                pass

        return None

    # -- Scripted generation ------------------------------------------------

    def generate_scripted(self, game_mode: str = "battle") -> dict:
        """Generate a complete scenario using scripted fallbacks.

        Emits progress events for each step.  When POI data is available,
        uses real building placements and location-aware contexts.
        """
        mode = GAME_MODES.get(game_mode, GAME_MODES["battle"])

        # Load POI data for building-centric generation
        self._prepare_mission_area(game_mode)

        # Emit start event
        self._emit_progress({
            "status": "started",
            "game_mode": game_mode,
            "total_steps": len(GENERATION_STEPS),
            "source": "scripted",
        })

        scenario: dict[str, Any] = {
            "game_mode": game_mode,
            "generated_by": "scripted",
        }

        # Step 1: Scenario context (uses real names when POIs available)
        if game_mode == "civil_unrest":
            template = random.choice(_CIVIL_UNREST_CONTEXT_TEMPLATES)
            ctx = self._resolve_context_template(template, _CIVIL_UNREST_CONTEXTS_FALLBACK)
        elif game_mode == "drone_swarm":
            template = random.choice(_DRONE_SWARM_CONTEXT_TEMPLATES)
            ctx = self._resolve_context_template(template, _DRONE_SWARM_CONTEXTS_FALLBACK)
        else:
            template = random.choice(_SCRIPTED_CONTEXT_TEMPLATES)
            ctx = self._resolve_context_template(template)
        scenario["scenario_context"] = ctx
        self._emit_progress({
            "status": "step_complete",
            "step": 1,
            "step_id": "scenario_context",
            "label": "Generating scenario context...",
            "result": ctx,
            "source": "scripted",
        })

        # Step 2: Unit composition — use building placements when POIs available
        if self._mission_area is not None:
            placements = place_defenders_around_buildings(
                self._mission_area,
                mode["default_defenders"],
            )
            defenders = [
                {
                    "type": p["asset_type"],
                    "alliance": "friendly",
                    "position": p["position"],
                    "name": p["name"],
                }
                for p in placements
            ]
        else:
            defenders = _place_defenders(game_mode)
        scenario["units"] = defenders
        self._emit_progress({
            "status": "step_complete",
            "step": 2,
            "step_id": "unit_composition",
            "label": "Planning force composition...",
            "result": {"defender_count": len(defenders)},
            "source": "scripted",
        })

        # Step 3: Unit motives
        objectives = []
        for unit in defenders:
            objectives.append({
                "unit_name": unit["name"],
                "primary": "Defend sector",
                "standing_orders": "Engage hostiles on sight",
                "rules_of_engagement": "Weapons free",
            })
        scenario["objectives"] = objectives
        self._emit_progress({
            "status": "step_complete",
            "step": 3,
            "step_id": "unit_motives",
            "label": "Assigning unit objectives...",
            "result": {"objectives_assigned": len(objectives)},
            "source": "scripted",
        })

        # Step 4: Win conditions (mode-specific)
        if game_mode == "civil_unrest":
            wc = {
                "victory": {
                    "condition": "Survive all 8 escalation phases with fewer than 5 civilian casualties",
                    "description": "De-escalate the situation and restore order to the neighborhood.",
                },
                "defeat": {
                    "condition": "5+ civilian casualties OR infrastructure overwhelmed OR all defenders eliminated",
                    "description": "Excessive force, unchecked destruction, or total defensive failure.",
                },
                "bonus_objectives": [
                    {"name": "Zero Collateral", "description": "Complete with 0 civilian casualties", "reward": 2000},
                    {"name": "Master De-escalator", "description": "De-escalate 20+ rioters back to civilian", "reward": 1500},
                    {"name": "All Instigators Identified", "description": "Neutralize every instigator per wave", "reward": 1000},
                    {"name": "Quick Containment", "description": "No critical density zones form", "reward": 1000},
                ],
            }
        elif game_mode == "drone_swarm":
            wc = {
                "victory": {
                    "condition": "Survive all 10 waves with infrastructure intact",
                    "description": "Eliminate or repel all hostile drones. Protect the defended building.",
                },
                "defeat": {
                    "condition": "Infrastructure destroyed OR all defenders eliminated",
                    "description": "Critical building systems destroyed by drone strikes or defensive collapse.",
                },
                "bonus_objectives": [
                    {"name": "Perfect Defense", "description": "Complete with infrastructure health > 800", "reward": 2000},
                    {"name": "Ace Pilot", "description": "Single drone eliminates 15+ hostile drones", "reward": 1500},
                    {"name": "No Bombers Through", "description": "Zero bomber detonations on infrastructure", "reward": 1000},
                    {"name": "EMP Master", "description": "Disable 10+ drones with a single EMP burst", "reward": 500},
                    {"name": "Flawless AA", "description": "No friendly units lost", "reward": 1000},
                ],
            }
        else:
            wc = {
                "victory": {
                    "condition": f"Survive all {mode['default_waves']} waves",
                    "description": f"Eliminate all hostiles across {mode['default_waves']} waves to secure the neighborhood.",
                },
                "defeat": {
                    "condition": "All defenders eliminated",
                    "description": "If all friendly units are destroyed, the neighborhood falls.",
                },
                "bonus_objectives": [
                    {"name": "No casualties", "description": "Complete without losing any defenders", "reward": 1000},
                    {"name": "Speed run", "description": "Complete in under 5 minutes", "reward": 500},
                ],
            }
        scenario["win_conditions"] = wc
        self._emit_progress({
            "status": "step_complete",
            "step": 4,
            "step_id": "win_conditions",
            "label": "Setting victory conditions...",
            "result": wc,
            "source": "scripted",
        })

        # Step 5: Weather (mode-specific)
        if game_mode == "civil_unrest":
            weather = random.choice(_CIVIL_UNREST_WEATHER)
        elif game_mode == "drone_swarm":
            weather = random.choice(_DRONE_SWARM_WEATHER)
        else:
            weather = random.choice(_SCRIPTED_WEATHER)
        scenario["weather"] = weather
        self._emit_progress({
            "status": "step_complete",
            "step": 5,
            "step_id": "weather_atmosphere",
            "label": "Setting weather and atmosphere...",
            "result": weather,
            "source": "scripted",
        })

        # Step 6: Loading messages (mode-specific)
        if game_mode == "civil_unrest":
            loading_pool = _CIVIL_UNREST_LOADING
        elif game_mode == "drone_swarm":
            loading_pool = _DRONE_SWARM_LOADING
        else:
            loading_pool = _SCRIPTED_LOADING
        msgs = random.sample(loading_pool, min(8, len(loading_pool)))
        scenario["loading_messages"] = msgs
        self._emit_progress({
            "status": "step_complete",
            "step": 6,
            "step_id": "loading_messages",
            "label": "Generating briefing messages...",
            "result": {"messages": msgs},
            "source": "scripted",
        })

        # Step 7: Wave briefings
        waves = []
        for w in range(1, mode["default_waves"] + 1):
            intensity = w / mode["default_waves"]
            if intensity < 0.3:
                threat = "light"
            elif intensity < 0.7:
                threat = "moderate"
            else:
                threat = "heavy"
            waves.append({
                "wave": w,
                "briefing": f"Wave {w}: {threat.title()} contact expected.",
                "threat_level": threat,
                "enemy_tactic": "standard assault",
                "intel": f"Estimated {mode['default_hostiles_per_wave'] + w} hostiles.",
            })
        scenario["wave_briefings"] = waves
        self._emit_progress({
            "status": "step_complete",
            "step": 7,
            "step_id": "wave_briefings",
            "label": "Planning wave tactics...",
            "result": {"wave_count": len(waves)},
            "source": "scripted",
        })

        # Step 8: Wave composition (concrete spawn data from briefings)
        wave_comp = self._briefings_to_composition(waves, mode, game_mode=game_mode)
        scenario["wave_composition"] = wave_comp
        self._emit_progress({
            "status": "step_complete",
            "step": 8,
            "step_id": "wave_composition",
            "label": "Determining hostile force composition...",
            "result": {"waves_configured": len(wave_comp)},
            "source": "scripted",
        })

        # Cache result
        with self._lock:
            self._current_scenario = scenario

        # Emit completion
        self._emit_progress({
            "status": "complete",
            "game_mode": game_mode,
            "scenario": scenario,
            "source": "scripted",
        })

        return scenario

    # -- LLM generation (async) ---------------------------------------------

    def generate_via_llm(
        self,
        game_mode: str = "battle",
        model: str | None = None,
    ) -> dict | None:
        """Generate scenario via Ollama LLM (blocking call).

        Returns parsed scenario dict, or None on failure.
        Each step emits progress events for the frontend modal.
        """
        use_model = model or self.model

        # Load POI data so prompts include real building names
        self._prepare_mission_area(game_mode)

        self._emit_progress({
            "status": "started",
            "game_mode": game_mode,
            "total_steps": len(GENERATION_STEPS),
            "source": "llm",
            "model": use_model,
        })

        scenario: dict[str, Any] = {
            "game_mode": game_mode,
            "generated_by": "llm",
            "model": use_model,
        }

        accumulated_context = ""

        for i, step in enumerate(GENERATION_STEPS):
            step_id = step["id"]
            label = step["label"]

            # Build prompt with accumulated context
            prompt = self.build_prompt(
                step_id,
                game_mode=game_mode,
                context_summary=accumulated_context[:500],
                unit_list=json.dumps(scenario.get("units", []))[:300],
                atmosphere=scenario.get("scenario_context", {}).get("atmosphere", ""),
                wave_count=GAME_MODES.get(game_mode, GAME_MODES["battle"])["default_waves"],
            )

            self._emit_progress({
                "status": "step_started",
                "step": i + 1,
                "step_id": step_id,
                "label": label,
                "prompt": prompt,
                "source": "llm",
                "model": use_model,
            })

            # Call LLM
            try:
                result = self._call_ollama(prompt, use_model)
                parsed = self.parse_llm_response(result, step_id)

                if parsed:
                    scenario[step_id] = parsed
                    accumulated_context += f" {step_id}: {json.dumps(parsed)[:200]}"

                    self._emit_progress({
                        "status": "step_complete",
                        "step": i + 1,
                        "step_id": step_id,
                        "label": label,
                        "result": parsed,
                        "raw_response": result[:500],
                        "source": "llm",
                        "model": use_model,
                    })
                else:
                    self._emit_progress({
                        "status": "step_failed",
                        "step": i + 1,
                        "step_id": step_id,
                        "label": label,
                        "error": "Failed to parse LLM response",
                        "raw_response": result[:500] if result else "",
                        "source": "llm",
                    })

            except Exception as e:
                self._emit_progress({
                    "status": "step_failed",
                    "step": i + 1,
                    "step_id": step_id,
                    "label": label,
                    "error": str(e),
                    "source": "llm",
                })

        # Ensure required fields exist (fill from scripted if LLM missed them)
        mode = GAME_MODES.get(game_mode, GAME_MODES["battle"])
        if "scenario_context" not in scenario:
            scenario["scenario_context"] = random.choice(_SCRIPTED_CONTEXTS_FALLBACK)
        if "units" not in scenario:
            # Check if unit_composition has defenders
            uc = scenario.get("unit_composition", {})
            if "defenders" in uc:
                scenario["units"] = [
                    {
                        "type": d.get("type", "rover"),
                        "alliance": "friendly",
                        "position": d.get("position", [0, 0]),
                        "name": d.get("name", f"Unit-{i}"),
                    }
                    for i, d in enumerate(uc["defenders"])
                ]
            else:
                scenario["units"] = _place_defenders(game_mode)
        if "win_conditions" not in scenario:
            scenario["win_conditions"] = {
                "victory": {"condition": f"Survive all {mode['default_waves']} waves"},
                "defeat": {"condition": "All defenders eliminated"},
            }

        # Ensure wave_composition exists (derive from briefings if LLM missed it)
        if "wave_composition" not in scenario:
            briefings = scenario.get("wave_briefings", [])
            if briefings:
                scenario["wave_composition"] = self._briefings_to_composition(briefings, mode, game_mode=game_mode)
        else:
            # LLM may return composition under a "waves" key — normalize
            wc = scenario["wave_composition"]
            if isinstance(wc, dict) and "waves" in wc:
                scenario["wave_composition"] = wc["waves"]

        with self._lock:
            self._current_scenario = scenario

        self._emit_progress({
            "status": "complete",
            "game_mode": game_mode,
            "scenario": scenario,
            "source": "llm",
            "model": use_model,
        })

        return scenario

    # -- Ollama API call -----------------------------------------------------

    def _call_ollama(self, prompt: str, model: str) -> str:
        """Call LLM chat API and return response text.

        Uses llama-server (OpenAI-compatible) or ollama (legacy).
        """
        if requests is None:
            raise RuntimeError("requests library not available")

        is_llama = any(p in self._ollama_host for p in [":8081", ":8082", ":8083"])
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a game scenario designer for a neighborhood security simulation "
                    "set in West Dublin, California. The battlespace is a real residential "
                    "neighborhood with actual buildings, streets, and landmarks. "
                    "Always respond with valid JSON only. No extra text."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        if is_llama:
            endpoint = "/v1/chat/completions"
            body = {"model": model, "messages": messages, "max_tokens": 512, "temperature": 0.8}
        else:
            endpoint = "/api/chat"
            body = {"model": model, "messages": messages, "stream": False,
                    "options": {"temperature": 0.8, "num_predict": 512}}

        resp = requests.post(f"{self._ollama_host}{endpoint}", json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if is_llama:
            choices = data.get("choices", [])
            return choices[0]["message"]["content"] if choices else ""
        return data.get("message", {}).get("content", "")

    # -- Convert scenario to engine targets ----------------------------------

    def scenario_to_targets(self, scenario: dict) -> list[dict]:
        """Convert a generated scenario into target dicts for the engine.

        Returns list of dicts with: type, alliance, position, name, motive.
        """
        targets = []
        for unit in scenario.get("units", []):
            pos = unit.get("position", [0, 0])
            if isinstance(pos, dict):
                pos = [pos.get("x", 0), pos.get("y", 0)]
            targets.append({
                "type": unit.get("type", "rover"),
                "alliance": unit.get("alliance", "friendly"),
                "position": list(pos)[:2],
                "name": unit.get("name", "Unit"),
            })
        return targets

    def _briefings_to_composition(
        self,
        briefings: list[dict],
        mode: dict,
        game_mode: str = "battle",
    ) -> list[dict]:
        """Convert narrative wave briefings to concrete spawn composition data.

        Dispatches to mode-specific methods for civil_unrest and drone_swarm.
        Returns list of dicts: [{wave, groups: [{type, count, speed, health}],
        speed_mult, health_mult}]
        """
        if game_mode == "civil_unrest":
            return self._briefings_to_composition_civil_unrest()
        elif game_mode == "drone_swarm":
            return self._briefings_to_composition_drone_swarm()

        base_hostiles = mode.get("default_hostiles_per_wave", 4)
        total_waves = max(len(briefings), 1)
        result = []

        for brief in briefings:
            wave_num = brief.get("wave", len(result) + 1)
            threat = brief.get("threat_level", "moderate")
            intensity = wave_num / total_waves

            # Scale hostile count by threat level
            if threat == "light":
                count = base_hostiles + max(0, wave_num - 1)
                speed_mult = 1.0
                health_mult = 1.0
            elif threat == "moderate":
                count = base_hostiles + wave_num + 1
                speed_mult = 1.0 + intensity * 0.15
                health_mult = 1.0 + intensity * 0.25
            else:  # heavy
                count = base_hostiles + wave_num + 3
                speed_mult = 1.0 + intensity * 0.3
                health_mult = 1.0 + intensity * 0.5

            # Determine composition based on threat
            groups = [{"type": "person", "count": count, "speed": 1.5, "health": 80.0}]
            if threat == "moderate" and wave_num > 3:
                vehicle_count = max(1, count // 5)
                groups = [
                    {"type": "person", "count": count - vehicle_count, "speed": 1.5, "health": 80.0},
                    {"type": "hostile_vehicle", "count": vehicle_count, "speed": 2.5, "health": 200.0},
                ]
            elif threat == "heavy":
                infantry = max(1, count - 3)
                groups = [
                    {"type": "person", "count": infantry, "speed": 1.5, "health": 80.0},
                    {"type": "hostile_vehicle", "count": 2, "speed": 2.5, "health": 200.0},
                    {"type": "hostile_leader", "count": 1, "speed": 1.2, "health": 150.0},
                ]

            result.append({
                "wave": wave_num,
                "groups": groups,
                "speed_mult": speed_mult,
                "health_mult": health_mult,
                "briefing": brief.get("briefing", f"Wave {wave_num}"),
            })

        return result

    def _briefings_to_composition_civil_unrest(self) -> list[dict]:
        """Build civil unrest wave composition from the spec table data."""
        result = []
        for w in _CIVIL_UNREST_WAVES:
            groups = []
            if w["civilians"] > 0:
                groups.append({
                    "type": "person",
                    "count": w["civilians"],
                    "speed": 1.0,
                    "health": 50.0,
                    "crowd_role": "civilian",
                })
            if w["instigators"] > 0:
                groups.append({
                    "type": "person",
                    "count": w["instigators"],
                    "speed": 1.2,
                    "health": 60.0,
                    "crowd_role": "instigator",
                })
            if w["vehicles"] > 0:
                groups.append({
                    "type": "hostile_vehicle",
                    "count": w["vehicles"],
                    "speed": 0.5,
                    "health": 250.0,
                })
            result.append({
                "wave": w["wave"],
                "groups": groups,
                "speed_mult": w["speed_mult"],
                "health_mult": w["health_mult"],
                "briefing": f"Wave {w['wave']}: {w['name']}",
            })
        return result

    def _briefings_to_composition_drone_swarm(self) -> list[dict]:
        """Build drone swarm wave composition from the spec table data."""
        result = []
        for w in _DRONE_SWARM_WAVES:
            groups = []
            if w["scout"] > 0:
                groups.append({
                    "type": "swarm_drone",
                    "count": w["scout"],
                    "speed": 4.0,
                    "health": 15.0,
                    "drone_variant": "scout_swarm",
                })
            if w["attack"] > 0:
                groups.append({
                    "type": "swarm_drone",
                    "count": w["attack"],
                    "speed": 3.0,
                    "health": 30.0,
                    "drone_variant": "attack_swarm",
                })
            if w["bomber"] > 0:
                groups.append({
                    "type": "swarm_drone",
                    "count": w["bomber"],
                    "speed": 1.5,
                    "health": 50.0,
                    "drone_variant": "bomber_swarm",
                })
            result.append({
                "wave": w["wave"],
                "groups": groups,
                "speed_mult": w["speed_mult"],
                "health_mult": w["health_mult"],
                "briefing": f"Wave {w['wave']}: {w['name']}",
            })
        return result

    def scenario_to_battle_scenario(self, scenario: dict):
        """Convert a MissionDirector scenario dict into a BattleScenario.

        Uses wave_composition when available (concrete spawn data from LLM or
        scripted). Falls back to deriving from wave_briefings.
        """
        from .scenario import BattleScenario, WaveDefinition, SpawnGroup, DefenderConfig

        game_mode = scenario.get("game_mode", "battle")
        mode = GAME_MODES.get(game_mode, GAME_MODES["battle"])
        ctx = scenario.get("scenario_context", {})

        # Build defenders from unit list
        defenders = []
        for unit in scenario.get("units", []):
            if unit.get("alliance", "friendly") != "friendly":
                continue
            pos = unit.get("position", [0, 0])
            if isinstance(pos, dict):
                pos = [pos.get("x", 0), pos.get("y", 0)]
            defenders.append(DefenderConfig(
                asset_type=unit.get("type", "rover"),
                position=(float(pos[0]), float(pos[1])),
                name=unit.get("name"),
            ))

        # Prefer wave_composition (concrete data), fall back to briefings
        wave_comp = scenario.get("wave_composition")
        if not wave_comp:
            briefings = scenario.get("wave_briefings", [])
            wave_comp = self._briefings_to_composition(briefings, mode, game_mode=game_mode)

        # Build lookup for wave briefings (narrative data: threat_level, intel)
        briefing_lookup = {}
        for brief in scenario.get("wave_briefings", []):
            briefing_lookup[brief.get("wave", 0)] = brief

        # Convert composition dicts to WaveDefinition objects
        waves = []
        for wc in wave_comp:
            wave_num = wc.get("wave", len(waves) + 1)
            brief = briefing_lookup.get(wave_num, {})
            groups = []
            for g in wc.get("groups", []):
                groups.append(SpawnGroup(
                    asset_type=g.get("type", "person"),
                    count=g.get("count", 3),
                    speed=g.get("speed", 1.5),
                    health=g.get("health", 80.0),
                    drone_variant=g.get("drone_variant"),
                ))
            waves.append(WaveDefinition(
                name=wc.get("briefing", brief.get("briefing", f"Wave {wave_num}")),
                groups=groups,
                speed_mult=wc.get("speed_mult", 1.0),
                health_mult=wc.get("health_mult", 1.0),
                briefing=wc.get("briefing", brief.get("briefing")),
                threat_level=brief.get("threat_level"),
                intel=brief.get("intel"),
            ))

        # Use mission_area radius when available
        if self._mission_area is not None:
            map_bounds = self._mission_area.radius_m
        else:
            map_bounds = 200.0

        # Build mode-specific config so GameMode.load_scenario() can apply settings
        mode_config = None
        if game_mode == "civil_unrest":
            mode_config = {
                "civilian_harm_limit": scenario.get("civilian_harm_limit", 5),
            }
        elif game_mode == "drone_swarm":
            mode_config = {
                "infrastructure_max": scenario.get("infrastructure_max", 1000.0),
            }

        return BattleScenario(
            scenario_id=f"mission-{game_mode}",
            name=ctx.get("reason", f"Generated {game_mode.title()} Mission"),
            description=ctx.get("stakes", ""),
            map_bounds=map_bounds,
            waves=waves,
            defenders=defenders,
            max_hostiles=200,
            mode_config=mode_config,
        )

    # -- State management ---------------------------------------------------

    def get_current_scenario(self) -> dict | None:
        """Get the current cached scenario."""
        with self._lock:
            return self._current_scenario

    def reset(self) -> None:
        """Clear the cached scenario."""
        with self._lock:
            self._current_scenario = None

    # -- Event helpers -------------------------------------------------------

    def _emit_progress(self, data: dict) -> None:
        """Emit a mission_progress event."""
        try:
            self._event_bus.publish("mission_progress", data)
        except Exception:
            pass
