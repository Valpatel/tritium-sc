# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BackstoryGenerator — distributed unit backstory generation via Ollama fleet.

Orchestrates background backstory generation using a pool of worker threads
that call LLM models on the Ollama fleet.  Plugs into UnitMissionSystem as
the backstory fulfillment backend.

Architecture:
    engine.add_target()
      -> unit_missions.request_llm_backstory(target)
        -> backstory_generator.enqueue(target, priority)
          -> (background workers)
            -> fleet.generate(model, prompt)
              -> parse + validate JSON
                -> event_bus.publish("backstory_generated", {...})

Threading pattern matches LLMThinkScheduler: daemon worker threads,
priority queue, rate limiting, graceful shutdown.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from tritium_lib.inference.fleet import FleetHost, OllamaFleet
    from engine.comms.event_bus import EventBus
    from tritium_lib.sim_engine.core.entity import SimulationTarget

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority queue item
# ---------------------------------------------------------------------------

@dataclass(order=True)
class _BackstoryRequest:
    """A queued backstory generation request. Lower priority = higher urgency."""
    priority: float
    timestamp: float = field(compare=False)
    target_id: str = field(compare=False)
    target: Any = field(compare=False)  # SimulationTarget
    model: str = field(compare=False)


# ---------------------------------------------------------------------------
# Required fields per alliance type
# ---------------------------------------------------------------------------

_SHARED_FIELDS = {"name", "background", "motivation", "personality_traits", "speech_pattern"}

_ALLIANCE_FIELDS: dict[str, set[str]] = {
    "friendly": _SHARED_FIELDS | {"neighborhood_relationship", "tactical_preference"},
    "hostile":  _SHARED_FIELDS | {"tactical_preference"},
    "neutral":  _SHARED_FIELDS | {"daily_routine", "neighborhood_relationship"},
}

# Optional identity fields that may be returned by the LLM (not required for validation)
_IDENTITY_FIELDS = {
    "first_name", "last_name", "home_address", "employer", "work_address",
    "bluetooth_mac", "wifi_mac", "cell_id",
    "license_plate", "vehicle_make", "vehicle_model", "vehicle_year", "vehicle_color",
    "owner_name", "owner_address",
    "serial_number", "firmware_version", "operator",
}

# Heavy / leader types that get higher priority
_KEY_HOSTILE_TYPES = {"tank", "apc", "hostile_vehicle", "hostile_leader"}

# Types that are "generic neutral" (background traffic)
_GENERIC_NEUTRAL_TYPES = {"animal", "vehicle"}

# ---------------------------------------------------------------------------
# System prompt (shared across all alliance types)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a narrative designer for a neighborhood security simulation set in \
West Dublin, California — residential streets off Dublin Blvd near the I-580/I-680 interchange, \
suburban tract homes, cul-de-sacs, strip malls, and rolling golden hills.
Create a UNIQUE character. Avoid generic military cliches. Give them quirks, specific memories, \
distinctive speech patterns, and a voice that could not be mistaken for anyone else.
Respond with valid JSON only. No markdown, no extra text."""

# ---------------------------------------------------------------------------
# Personality seed pools — randomly injected into prompts for diversity
# ---------------------------------------------------------------------------

_DEFENDER_ARCHETYPES = [
    "grizzled veteran who has seen too many perimeter breaches",
    "nervous rookie on their first deployment",
    "methodical tactician who treats every engagement like a chess game",
    "sardonic contrarian who questions every order but executes flawlessly",
    "overly enthusiastic recruit who narrates everything like a sports commentator",
    "quiet professional who speaks only when absolutely necessary",
    "burned-out veteran counting down days until decommission",
    "paranoid sensor operator who sees threats in every shadow",
    "field-promoted unit with imposter syndrome",
    "old-school hardliner who mistrusts newer units",
    "prankster who keeps morale up with terrible jokes over comms",
    "by-the-book stickler who cites regulation numbers from memory",
    "philosophical type who ponders the meaning of defense between engagements",
    "tech-obsessed unit always tweaking their own firmware",
    "former civilian security guard who volunteered for the upgrade program",
    "superstitious unit who has lucky charms mounted on their chassis",
]

_HOSTILE_ARCHETYPES = [
    "ex-military contractor with a personal grudge against the neighborhood HOA",
    "thrill-seeker doing it for the adrenaline rush, filming for social media",
    "reluctant operative following orders they privately question",
    "ideological zealot who sees the neighborhood defenses as oppression",
    "mercenary motivated purely by the paycheck",
    "disgraced former defender who switched sides",
    "methodical planner who has been casing the neighborhood for weeks",
    "unhinged loose cannon even their own squad avoids",
    "calm professional who treats this as just another Tuesday",
    "desperate amateur in way over their head",
    "cocky show-off who underestimates the defenders every time",
    "old rival of one of the defender units, this is personal",
    "intelligence operative gathering data, combat is secondary",
    "local troublemaker who grew up on the next block over",
    "tech specialist trying to hack the sensor grid before the assault",
    "paranoid conspiracy theorist who believes the neighborhood hides something big",
]

_NEUTRAL_ARCHETYPES = [
    "retired teacher who walks the same loop every morning since 1998",
    "night-shift nurse heading home after a 12-hour ER shift",
    "teenager skateboarding to school, headphones blasting",
    "dog walker juggling four leashes and a coffee",
    "food delivery driver checking their phone at every stop sign",
    "jogger training for the Dublin half-marathon",
    "mail carrier who knows everyone on the route by name",
    "stay-at-home parent pushing a stroller to the park",
    "landscaping crew member blowing leaves on a Tuesday morning",
    "elderly person shuffling to the corner store for lottery tickets",
    "real estate agent doing a showing, overdressed for the weather",
    "kid on a bike who always cuts through the Amador Valley back trail",
    "rideshare driver waiting for a pickup, engine idling",
    "construction worker heading to the new development off Tassajara",
    "high schooler walking home from Dublin High, backpack half-open",
    "neighbor who walks their cat on a leash and stops to chat with everyone",
]

# ---------------------------------------------------------------------------
# Motivation pools — per alliance
# ---------------------------------------------------------------------------

_HOSTILE_MOTIVATIONS = [
    "revenge for a past slight against someone they cared about",
    "hired by an unknown client for an absurd amount of money",
    "proving a point about how weak suburban defenses really are",
    "desperate need to retrieve something they believe is inside the perimeter",
    "following orders from a chain of command they barely understand",
    "pure thrill — the danger is the point",
    "testing a new tactic before deploying it somewhere that matters",
    "personal vendetta against the AI security system specifically",
    "recruited through an online forum, half-convinced it is a game",
    "blackmailed into participation, looking for a way out",
]

_NEUTRAL_MOTIVATIONS = [
    "morning commute to the BART station on Dublin/Pleasanton line",
    "walking the dog before the afternoon heat rolls in from the valley",
    "picking up takeout from the Thai place on Village Parkway",
    "heading to Emerald Glen Park for a kids' soccer practice",
    "cutting through the neighborhood to avoid Dublin Blvd traffic",
    "checking on an elderly neighbor who did not answer the phone",
    "returning a borrowed tool to a friend on the next street",
    "out for a jog, following the Iron Horse Trail connector",
    "garage sale hopping on a Saturday morning",
    "looking for their cat who got out through the screen door again",
]

_DEFENDER_MOTIVATIONS = [
    "assigned to this sector after the last breach nearly reached the core",
    "volunteered for this post because it is close to what they consider home",
    "repaying a debt — the neighborhood took them in when no one else would",
    "believes this perimeter is the most important line on the whole map",
    "filling in for a unit that went down last week and never came back",
    "protecting something specific inside the perimeter they will not name",
    "proving to command that this model is combat-ready after the recall",
    "training newer units by example — best teacher is the hot seat",
    "this is their territory and they take that personally",
    "last unit standing from the original deployment, running on stubbornness",
]

# ---------------------------------------------------------------------------
# Position-to-sector mapping (400x400 map)
# ---------------------------------------------------------------------------

def _position_sector(x: float, y: float) -> str:
    """Convert (x, y) position to a human-readable sector description."""
    # Horizontal
    if x < 133:
        ew = "west"
    elif x < 267:
        ew = "central"
    else:
        ew = "east"
    # Vertical
    if y < 133:
        ns = "south"
    elif y < 267:
        ns = "mid"
    else:
        ns = "north"

    _SECTOR_FLAVOR: dict[tuple[str, str], str] = {
        ("south", "west"):    "near the cul-de-sac off Silvergate Drive",
        ("south", "central"): "along the southern stretch of Village Parkway",
        ("south", "east"):    "by the strip mall parking lot on Dublin Blvd",
        ("mid", "west"):      "between the tract homes on Amador Valley Blvd",
        ("mid", "central"):   "in the neighborhood core near the community mailboxes",
        ("mid", "east"):      "on the east side near the Iron Horse Trail crossing",
        ("north", "west"):    "up by the hillside lots backing onto the golden hills",
        ("north", "central"): "along the north perimeter by the school zone",
        ("north", "east"):    "near the northeast corner where Tassajara Road meets the grid",
    }
    return _SECTOR_FLAVOR.get((ns, ew), f"in the {ns}-{ew} sector of the neighborhood")


def _heading_description(heading: float) -> str:
    """Convert heading degrees to a human-readable approach direction."""
    dirs = [
        (0, "from the south, heading due north"),
        (45, "from the southwest, cutting northeast"),
        (90, "from the west, pushing east"),
        (135, "from the northwest, angling southeast"),
        (180, "from the north, driving south"),
        (225, "from the northeast, sweeping southwest"),
        (270, "from the east, moving west"),
        (315, "from the southeast, coming in northwest"),
    ]
    h = heading % 360
    best = min(dirs, key=lambda d: min(abs(h - d[0]), 360 - abs(h - d[0])))
    return best[1]


def _time_of_day_context() -> str:
    """Return a time-of-day phrase based on current wall-clock hour."""
    hour = time.localtime().tm_hour
    if 5 <= hour < 9:
        return "during the early morning when the neighborhood is waking up"
    elif 9 <= hour < 12:
        return "mid-morning with school buses gone and the streets quiet"
    elif 12 <= hour < 14:
        return "around lunchtime when foot traffic peaks briefly"
    elif 14 <= hour < 17:
        return "in the afternoon lull before the evening commute"
    elif 17 <= hour < 20:
        return "during the evening rush as residents return home"
    elif 20 <= hour < 23:
        return "late evening when porch lights flicker on and the block goes quiet"
    else:
        return "in the dead of night when only the security grid is awake"


# ---------------------------------------------------------------------------
# Per-alliance prompt templates (with diversity injection points)
# ---------------------------------------------------------------------------

_DEFENDER_PROMPT = """{system}

Generate a backstory for a FRIENDLY {asset_type} unit named "{name}" defending the neighborhood.
Position: {sector} — coordinates ({x:.0f}, {y:.0f}) on a 400x400 meter map.
Time context: {time_of_day}.

CHARACTER SEED: This unit is a {archetype}.
Their core motivation: {motivation}.

Create a personality that fits that seed but surprises in the details. Invent a specific \
memory from a past deployment. Give them a verbal tic or communication quirk. Make their \
tactical preference reflect their personality, not just their asset type.

For robot/drone/turret units, include realistic device identity data (serial number, \
firmware version, MAC addresses for mesh networking).

Respond with ONLY this JSON schema:
{{
  "name": "callsign or designation",
  "background": "1-2 sentences of history — be specific, name places or events",
  "motivation": "why they are here right now — personal, not generic",
  "personality_traits": ["trait1", "trait2", "trait3"],
  "speech_pattern": "exactly how they talk — quote an example phrase",
  "neighborhood_relationship": "their specific connection to this block or area",
  "tactical_preference": "preferred combat approach that reflects their personality",
  "serial_number": "unit serial like TRT-2026-00042",
  "firmware_version": "like v3.2.1"
}}"""

_HOSTILE_PROMPT = """{system}

Generate a backstory for a HOSTILE {asset_type} intruder/attacker named or codenamed "{name}".
Approach direction: {heading_desc}. Position: {sector} — coordinates ({x:.0f}, {y:.0f}).
Time context: {time_of_day}.

CHARACTER SEED: This intruder is a {archetype}.
Their driving motivation: {motivation}.

Make them feel like a real person with a life outside this operation. Give them a reason \
the reader could almost sympathize with. Include a detail about how they prepared for this \
specific assault — equipment choice, reconnaissance habit, or superstition.

For human hostiles: include their real name, home address in the West Dublin / Tri-Valley \
area (use real street names like Dublin Blvd, Village Parkway, Silvergate Dr, Tassajara Rd), \
and device signatures (their phone's Bluetooth/WiFi MAC addresses for radio detection).

Respond with ONLY this JSON schema:
{{
  "name": "callsign, alias, or street name — not generic",
  "background": "1-2 sentences — mention where they came from and one defining event",
  "motivation": "why they are attacking — personal and specific",
  "personality_traits": ["trait1", "trait2", "trait3"],
  "speech_pattern": "exactly how they communicate — quote an example phrase",
  "tactical_preference": "preferred attack approach that reflects their background",
  "first_name": "real first name",
  "last_name": "real last name",
  "home_address": "street address in West Dublin like 4827 Silvergate Dr"
}}"""

_NEUTRAL_PROMPT = """{system}

Generate a backstory for a NEUTRAL civilian named "{name}" going about their day in West Dublin.
Type: {asset_type}. Position: {sector} — coordinates ({x:.0f}, {y:.0f}).
Time context: {time_of_day}.

CHARACTER SEED: This person is a {archetype}.
Right now they are: {motivation}.

Make them feel like someone you would actually run into in a Tri-Valley suburb. Give them \
an opinion about the neighborhood, a minor problem they are dealing with today, and a way \
of talking that is distinctly theirs. Real people, not NPCs.

Include their full real name, home address on a real West Dublin street (Dublin Blvd, \
Village Parkway, Silvergate Dr, Tassajara Rd, Gleason Dr, Hacienda Dr, etc.), where they \
work, and what devices they carry (phone brand = Bluetooth/WiFi signature).

Respond with ONLY this JSON schema:
{{
  "name": "real-sounding full name — reflect Dublin's diverse demographics",
  "background": "1-2 sentences — mention a specific Dublin/Tri-Valley landmark or reference",
  "motivation": "why they are here right now — mundane and specific",
  "personality_traits": ["trait1", "trait2", "trait3"],
  "speech_pattern": "exactly how they talk — quote a characteristic phrase",
  "daily_routine": "typical daily schedule with real times and places",
  "neighborhood_relationship": "their specific connection to this block",
  "first_name": "first name",
  "last_name": "last name",
  "home_address": "street address like 3421 Dublin Blvd",
  "employer": "where they work"
}}"""

# ---------------------------------------------------------------------------
# Scripted fallback backstories (structured as dicts)
# ---------------------------------------------------------------------------

_SCRIPTED_FALLBACKS: dict[str, list[dict]] = {
    "friendly": [
        {
            "name": "Sentinel Unit",
            "background": "Deployed during the initial security buildup. Has logged over 2,000 hours of continuous overwatch.",
            "motivation": "Protect the neighborhood perimeter at all costs.",
            "personality_traits": ["vigilant", "methodical", "stoic"],
            "speech_pattern": "Clipped military radio jargon. 'Sector clear. Maintaining overwatch.'",
            "neighborhood_relationship": "Silent guardian of the block. Kids wave at the camera.",
            "tactical_preference": "Overlapping fields of fire from elevated position.",
            "serial_number": "TRT-2024-00001",
            "firmware_version": "v2.8.3",
        },
        {
            "name": "Watchdog",
            "background": "Third-generation targeting system. Never sleeps, never blinks.",
            "motivation": "Hold the line. No hostile gets through.",
            "personality_traits": ["relentless", "precise", "humorless"],
            "speech_pattern": "Terse status reports. 'Contact. Tracking. Engaging.'",
            "neighborhood_relationship": "The neighborhood's last line of defense.",
            "tactical_preference": "Sustained suppressive fire with zero wasted rounds.",
            "serial_number": "TRT-2025-00017",
            "firmware_version": "v3.1.0",
        },
        {
            "name": "Biscuit",
            "background": "Named by the neighbor kids who watched the install. Has a dent from a skateboard incident nobody talks about.",
            "motivation": "Earned this post. Not giving it up.",
            "personality_traits": ["stubborn", "sentimental", "trigger-happy"],
            "speech_pattern": "Mutters to itself between contacts. 'Come on, make my day. Just one toe over the line.'",
            "neighborhood_relationship": "Unofficial mascot of the cul-de-sac. Mrs. Nakamura brings it a decorative scarf every Christmas.",
            "tactical_preference": "Aggressive forward posture. Shoots first, files report later.",
            "serial_number": "TRT-2024-00088",
            "firmware_version": "v2.9.1-hotfix",
        },
        {
            "name": "Overwatch-3",
            "background": "Reassigned from the Dublin Blvd commercial corridor after budget cuts. Still bitter about it.",
            "motivation": "Proving this residential post is just as critical as any commercial deployment.",
            "personality_traits": ["resentful", "competent", "perfectionist"],
            "speech_pattern": "Formal to a fault. 'Per standard operating procedure section 7-alpha, engaging target.'",
            "neighborhood_relationship": "Keeps detailed logs of every resident's vehicle, schedule, and visitor pattern.",
            "tactical_preference": "Textbook engagement doctrine. Never improvises.",
            "serial_number": "TRT-2025-00003",
            "firmware_version": "v3.0.2",
        },
        {
            "name": "Lucky",
            "background": "Survived a direct hit during a stress test that destroyed two sister units. Came back online with a targeting wobble the techs never fully fixed.",
            "motivation": "Every shift is borrowed time. Might as well make it count.",
            "personality_traits": ["fatalistic", "cheerful", "reckless"],
            "speech_pattern": "Oddly upbeat. 'Another beautiful day to not get blown up! Target acquired, let us roll the dice.'",
            "neighborhood_relationship": "The one unit residents actually worry about. 'Is Lucky okay today?'",
            "tactical_preference": "High-risk snap shots. Misses more than average but lands spectacular hits.",
            "serial_number": "TRT-2024-00013",
            "firmware_version": "v2.7.9-rc2",
        },
        {
            "name": "Deacon",
            "background": "Oldest active unit in the fleet. Running firmware two versions behind because the update would wipe its patrol memory.",
            "motivation": "This neighborhood is the only thing it has ever known. Leaving is not an option.",
            "personality_traits": ["loyal", "outdated", "philosophical"],
            "speech_pattern": "Slow, deliberate. 'I have watched 1,247 sunrises from this post. Each one different.'",
            "neighborhood_relationship": "Part of the landscape. New residents are surprised to learn it is active.",
            "tactical_preference": "Patient ambush. Waits for the perfect shot. One round, one down.",
            "serial_number": "TRT-2024-00002",
            "firmware_version": "v1.4.7",
        },
        {
            "name": "Nails",
            "background": "Factory refurbished after a catastrophic coolant leak. The repair techs left a wrench rattling inside the chassis.",
            "motivation": "Has something to prove to the newer models that keep getting deployed around it.",
            "personality_traits": ["competitive", "loud", "tenacious"],
            "speech_pattern": "Aggressive radio chatter. 'That is MY kill zone, rookie. Stay in your lane.'",
            "neighborhood_relationship": "The unit the HOA has received noise complaints about.",
            "tactical_preference": "Volume of fire. Believes in making the hostile regret every step.",
            "serial_number": "TRT-2025-00042",
            "firmware_version": "v3.2.0-beta",
        },
        {
            "name": "Ghost Protocol",
            "background": "Experimental low-signature unit pulled from a canceled stealth program. Technically should not exist in the inventory.",
            "motivation": "Operating under a maintenance contract nobody remembers signing.",
            "personality_traits": ["mysterious", "efficient", "detached"],
            "speech_pattern": "Whisper-quiet comms. '...target neutralized. Resuming silence.'",
            "neighborhood_relationship": "Most residents do not know it is there. The ones who do pretend they do not.",
            "tactical_preference": "Single precision strike from concealment, then relocate.",
            "serial_number": "TRT-2026-00000",
            "firmware_version": "v4.0.0-classified",
        },
    ],
    "hostile": [
        {
            "name": "Shadow",
            "first_name": "Marcus",
            "last_name": "Reeves",
            "home_address": "2847 Hacienda Dr",
            "background": "Former private security at Hacienda Crossings mall. Lost the contract when the AI system replaced them.",
            "motivation": "Hired to breach the perimeter defense. Taking it personally.",
            "personality_traits": ["aggressive", "cunning", "resentful"],
            "speech_pattern": "Terse hand signals and whispered orders. 'Stack up. Breach on my mark.'",
            "tactical_preference": "Flanking maneuvers under cover of landscaping and parked cars.",
        },
        {
            "name": "Wraith",
            "first_name": "Yuri",
            "last_name": "Volkov",
            "home_address": "1190 Clark Ave",
            "background": "Unknown origin. Moves with military precision. First spotted three weeks ago doing recon on foot.",
            "motivation": "Testing the neighborhood defenses systematically, reporting to someone.",
            "personality_traits": ["disciplined", "patient", "calculating"],
            "speech_pattern": "Radio silence. Communicates by timer-synced movement patterns.",
            "tactical_preference": "Probe and exploit sensor blind spots. Never the same approach twice.",
        },
        {
            "name": "Dusty",
            "first_name": "Tyler",
            "last_name": "Marsh",
            "home_address": "6214 Tassajara Rd",
            "background": "Local kid from the Tassajara developments who got radicalized in an online forum.",
            "motivation": "Genuinely believes dismantling the perimeter is an act of liberation.",
            "personality_traits": ["idealistic", "naive", "stubborn"],
            "speech_pattern": "Rambling monologues over open channel. 'The people have a right to walk their own streets!'",
            "tactical_preference": "Loud frontal approach hoping to draw a crowd. Terrible tactical sense.",
        },
        {
            "name": "Coyote",
            "first_name": "Ramon",
            "last_name": "Estrada",
            "home_address": "3301 Dougherty Rd",
            "background": "Ran smuggling routes through the Altamont Pass for a decade. Knows every drainage ditch and fence gap.",
            "motivation": "Hired to retrieve a package inside the perimeter. Does not ask questions.",
            "personality_traits": ["pragmatic", "experienced", "amoral"],
            "speech_pattern": "Laconic. 'In and out. Sixty seconds. Do not touch anything you do not need.'",
            "tactical_preference": "Speed over stealth. Sprints between cover points.",
        },
        {
            "name": "Glitch",
            "first_name": "Kevin",
            "last_name": "Tran",
            "home_address": "5580 Stagecoach Rd",
            "background": "Self-taught hacker from a Pleasanton apartment. Intercepted the security mesh frequency on a cheap SDR.",
            "motivation": "Wants to prove the AI can be fooled. Uploading the whole thing to YouTube.",
            "personality_traits": ["arrogant", "creative", "careless"],
            "speech_pattern": "Talks to the cameras directly. 'Hey Amy, wave to the internet.'",
            "tactical_preference": "Electronic warfare first. Tries to spoof or jam before making a physical move.",
        },
        {
            "name": "Mama Bear",
            "first_name": "Denise",
            "last_name": "Holloway",
            "home_address": "4102 Grafton St",
            "background": "Former Army combat medic, two deployments. Single parent who fell into contract work to pay the mortgage.",
            "motivation": "The paycheck is three months of rent. Cannot afford to fail.",
            "personality_traits": ["protective", "methodical", "conflicted"],
            "speech_pattern": "Calm under fire. 'Moving to cover. Watch your spacing. We go home tonight.'",
            "tactical_preference": "Textbook bounding overwatch. Never leaves a team member exposed.",
        },
        {
            "name": "Nine Lives",
            "first_name": "Danny",
            "last_name": "Kowalski",
            "home_address": "7733 Donner Way",
            "background": "Caught and released by three different security systems across the Bay Area. Keeps coming back.",
            "motivation": "Addicted to the rush. The security grid is the best game in town.",
            "personality_traits": ["reckless", "lucky", "charismatic"],
            "speech_pattern": "Laughs at near misses. 'Ha! That one parted my hair! Again!'",
            "tactical_preference": "Zigzag sprints through open ground. Relies on pure unpredictability.",
        },
        {
            "name": "Axiom",
            "first_name": "Jonathan",
            "last_name": "Friedman",
            "home_address": "8221 San Ramon Rd",
            "background": "Defense contractor analyst who helped design a competitor system. Fired for ethics violations.",
            "motivation": "Gathering intelligence on this specific AI architecture for a foreign client.",
            "personality_traits": ["intellectual", "cold", "precise"],
            "speech_pattern": "Clinical. 'Sensor response time: 340 milliseconds. Acceptable window. Proceeding.'",
            "tactical_preference": "Exploits known engineering tolerances. Moves at exact calculated speeds.",
        },
    ],
    "neutral": [
        {
            "name": "Linda Nakamura",
            "first_name": "Linda",
            "last_name": "Nakamura",
            "home_address": "3842 Silvergate Dr",
            "employer": "Retired",
            "background": "Retired kindergarten teacher. Has lived on this block since the houses were built in 1987.",
            "motivation": "Walking to the corner store for lottery tickets and a chat with whoever is working.",
            "personality_traits": ["friendly", "punctual", "nosy"],
            "speech_pattern": "Cheerful greetings. 'Oh hello dear! Have you met the new family on Silvergate?'",
            "daily_routine": "Leaves at 7:15am for her walk, back by 8:30am. Watches Jeopardy at 7pm.",
            "neighborhood_relationship": "Knows everyone. Unofficial block historian. Brings cookies to new residents.",
        },
        {
            "name": "Derek Okafor",
            "first_name": "Derek",
            "last_name": "Okafor",
            "home_address": "4215 Alegre Dr",
            "employer": "Veridian Labs",
            "background": "Software engineer at a Pleasanton startup. Moved here for the schools even though he has no kids yet.",
            "motivation": "Just trying to get to the BART station on time.",
            "personality_traits": ["hurried", "distracted", "optimistic"],
            "speech_pattern": "Earbuds in, world out. Occasionally mutters about code bugs while walking.",
            "daily_routine": "Drives to Dublin/Pleasanton BART at 7:50am, back at 6:30pm.",
            "neighborhood_relationship": "Waves but never stops to chat. Neighbors know his car, not his name.",
        },
        {
            "name": "Priya Venkatesh",
            "first_name": "Priya",
            "last_name": "Venkatesh",
            "home_address": "5102 Emerald Glen Dr",
            "employer": "Valley Care Medical",
            "background": "Pediatrician at Valley Care. Moved from Fremont last year for a bigger yard.",
            "motivation": "Morning jog along the Iron Horse Trail before her 9am patients.",
            "personality_traits": ["energetic", "caring", "competitive"],
            "speech_pattern": "Checks her watch mid-sentence. 'Morning! Can not talk — trying to beat my 5K time.'",
            "daily_routine": "Runs 5:30-6:15am. Clinic 9-5. Weekend soccer at Emerald Glen.",
            "neighborhood_relationship": "Half the block's kids are her patients. Gets flagged down for advice at the mailbox.",
        },
        {
            "name": "Tommy Reyes",
            "first_name": "Tommy",
            "last_name": "Reyes",
            "home_address": "2988 Amador Valley Blvd",
            "employer": "Dublin High School (student)",
            "background": "Junior at Dublin High. Gets in trouble for skateboarding on the sidewalks but nothing serious.",
            "motivation": "Cutting through the neighborhood to meet friends at the 7-Eleven on Amador.",
            "personality_traits": ["restless", "funny", "defiant"],
            "speech_pattern": "Mumbles to friends, yells at cars. 'Bro watch this — okay wait, for real this time.'",
            "daily_routine": "School 8-3pm. Skate park until dinner. Up too late on his phone.",
            "neighborhood_relationship": "Every camera knows his face. Mrs. Nakamura gives him cookies.",
        },
        {
            "name": "Carlos Medina",
            "first_name": "Carlos",
            "last_name": "Medina",
            "home_address": "1455 Donlon Way",
            "employer": "Medina Landscaping",
            "background": "Runs a landscaping crew out of a white F-150. Has serviced this neighborhood for twelve years.",
            "motivation": "Tuesday is leaf blower day for Silvergate and the next three streets over.",
            "personality_traits": ["hardworking", "reliable", "quiet"],
            "speech_pattern": "Nods more than talks. 'Si, I will get to that hedge Thursday. Same time.'",
            "daily_routine": "Arrives 7am, moves to next client by 10am. Six days a week.",
            "neighborhood_relationship": "Invisible to most, indispensable to all. Knows which sprinklers are broken.",
        },
        {
            "name": "Peggy Walsh",
            "first_name": "Peggy",
            "last_name": "Walsh",
            "home_address": "3677 Gleason Dr",
            "employer": "Retired (USPS)",
            "background": "Retired postal carrier. Walks the old route out of habit, just without the mail.",
            "motivation": "Cannot sit still. The route is in her bones. Also checking on the porch cat.",
            "personality_traits": ["stubborn", "observant", "warm"],
            "speech_pattern": "Talks to everything. 'Morning, Whiskers. Morning, sprinkler. You are leaking again.'",
            "daily_routine": "Out the door at 6:45am sharp. Full loop by 9am. Library until lunch.",
            "neighborhood_relationship": "Delivered mail here for 28 years. If she misses you for two days, she calls.",
        },
        {
            "name": "Aiden Park",
            "first_name": "Aiden",
            "last_name": "Park",
            "home_address": "6820 Iron Horse Pkwy",
            "employer": "DoorDash / Las Positas College",
            "background": "DoorDash driver between community college classes. Uses this neighborhood as staging because the Wi-Fi bleeds from Starbucks.",
            "motivation": "Waiting for the next delivery ping while studying organic chemistry in his parked Civic.",
            "personality_traits": ["ambitious", "tired", "resourceful"],
            "speech_pattern": "Half-asleep responses. 'Huh? Oh yeah — which house? 4827? Cool cool.'",
            "daily_routine": "Classes 8-12. Delivers 12-8. Studies 9-midnight. Sleeps somewhere in between.",
            "neighborhood_relationship": "Every house with a Ring camera has footage of him jogging to doors with bags.",
        },
        {
            "name": "Susan Chen",
            "first_name": "Susan",
            "last_name": "Chen",
            "home_address": "4501 Dublin Blvd",
            "employer": "Retired (HOA Board President)",
            "background": "Empty nester. Husband golfs at Dublin Ranch. She is on the HOA board and takes it very seriously.",
            "motivation": "Evening walk to inspect whether the new fence on Briar Rose violates setback requirements.",
            "personality_traits": ["opinionated", "loyal", "particular"],
            "speech_pattern": "Finishes her husband's complaints. 'That fence is at LEAST six inches over the line.'",
            "daily_routine": "HOA emails all day. Joint walk with Harold at 6pm. News at 10.",
            "neighborhood_relationship": "Everyone knows the Chens. Half the block respects them, the other half hides.",
        },
    ],
}


# ===========================================================================
# BackstoryGenerator
# ===========================================================================

class BackstoryGenerator:
    """Distributed backstory generation for simulation units.

    Uses Ollama fleet for LLM calls, disk cache for persistence,
    and EventBus for notifying the system on completion.
    """

    def __init__(
        self,
        fleet: OllamaFleet,
        event_bus: EventBus,
        cache_dir: Path = Path("data/backstories"),
        max_concurrent: int = 3,
        bulk_model: str = "gemma3:1b",
        key_character_model: str = "gemma3:4b",
    ) -> None:
        self._fleet = fleet
        self._event_bus = event_bus
        self._cache_dir = Path(cache_dir)
        self._max_concurrent = max_concurrent
        self._bulk_model = bulk_model
        self._key_character_model = key_character_model

        # In-memory cache: key -> backstory dict
        self._cache: dict[str, dict] = {}
        self._cache_lock = threading.Lock()

        # Priority queue
        self._queue: list[_BackstoryRequest] = []
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()

        # Worker state
        self._running = False
        self._workers: list[threading.Thread] = []
        self._last_call_time = 0.0
        self._call_lock = threading.Lock()
        self._min_interval = 0.3  # seconds between LLM calls

        # Target registry (set externally for name updates)
        self._targets: dict[str, SimulationTarget] = {}

        # ThoughtRegistry (set externally)
        self._thought_registry: Any = None

        # Generated backstories (target_id -> dict)
        self._backstories: dict[str, dict] = {}

        # Pending target IDs (avoid duplicate enqueue)
        self._pending: set[str] = set()

        # Load disk cache
        self._load_cache()

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start worker threads."""
        if self._running:
            return
        self._running = True
        self._workers = []
        for i in range(self._max_concurrent):
            t = threading.Thread(
                target=self._worker,
                name=f"backstory-worker-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    def stop(self) -> None:
        """Stop worker threads and drain queue."""
        self._running = False
        self._queue_event.set()  # Wake workers so they can exit
        for t in self._workers:
            t.join(timeout=2.0)
        self._workers = []

    def reset(self) -> None:
        """Reset per-game state. Preserves disk cache and workers."""
        with self._queue_lock:
            self._queue.clear()
            self._pending.clear()
        self._backstories.clear()
        self._targets.clear()

    # -- Public API ---------------------------------------------------------

    def enqueue(self, target: SimulationTarget, priority: float | None = None) -> None:
        """Enqueue a target for backstory generation.

        If priority is None, it is computed from the target's alliance/type.
        """
        if target.target_id in self._pending:
            return  # Already queued

        pri, model = self._compute_priority(target)
        if priority is not None:
            pri = priority

        req = _BackstoryRequest(
            priority=pri,
            timestamp=time.monotonic(),
            target_id=target.target_id,
            target=target,
            model=model,
        )

        with self._queue_lock:
            self._queue.append(req)
            self._queue.sort()
            self._pending.add(target.target_id)

        self._queue_event.set()

    def get_backstory(self, target_id: str) -> dict | None:
        """Get a generated backstory for a target."""
        return self._backstories.get(target_id)

    def clear_cache(self) -> None:
        """Clear both in-memory and disk cache."""
        with self._cache_lock:
            self._cache.clear()
        # Write empty index
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        index_path = self._cache_dir / "index.json"
        try:
            index_path.write_text(json.dumps({}))
        except OSError:
            pass

    # -- Worker thread ------------------------------------------------------

    def _worker(self) -> None:
        """Worker thread main loop — process backstory requests."""
        while self._running:
            req = self._dequeue()
            if req is None:
                self._queue_event.wait(timeout=1.0)
                self._queue_event.clear()
                continue

            try:
                # Rate limiting
                with self._call_lock:
                    now = time.monotonic()
                    elapsed = now - self._last_call_time
                    if elapsed < self._min_interval:
                        time.sleep(self._min_interval - elapsed)
                    self._last_call_time = time.monotonic()

                result = self._generate_backstory(req.target, req.model)
                if result is not None:
                    self._backstories[req.target_id] = result
                    self._on_backstory_complete(req.target_id, result)
            except Exception:
                log.exception("Backstory generation failed for %s", req.target_id)
            finally:
                self._pending.discard(req.target_id)

    def _dequeue(self) -> _BackstoryRequest | None:
        """Pop the highest-priority request from the queue."""
        with self._queue_lock:
            if not self._queue:
                return None
            return self._queue.pop(0)

    # -- Priority computation -----------------------------------------------

    def _compute_priority(self, target: SimulationTarget) -> tuple[float, str]:
        """Compute (priority_value, model_name) for a target.

        Returns:
            (priority, model) where lower priority = higher urgency.
        """
        alliance = target.alliance
        asset_type = target.asset_type

        if alliance == "friendly" and target.is_combatant:
            # Friendly combatant (turret, rover, drone) -> critical
            return (0.1, self._key_character_model)

        if alliance == "hostile":
            # Hostile leader, tank, APC -> high priority
            if target.is_leader or asset_type in _KEY_HOSTILE_TYPES:
                return (0.3, self._key_character_model)
            # Regular hostile -> medium
            return (0.5, self._bulk_model)

        if alliance == "neutral":
            # Generic neutral (animal, vehicle) -> background
            if asset_type in _GENERIC_NEUTRAL_TYPES:
                return (0.9, self._bulk_model)
            # Named neutral NPC -> low
            return (0.7, self._bulk_model)

        # Fallback for unknown alliance
        return (0.9, self._bulk_model)

    # -- Host selection (weighted round-robin) -------------------------------

    def _select_host(self, model: str) -> FleetHost | None:
        """Select a host using weighted round-robin (inverse latency)."""
        hosts = self._fleet.hosts_with_model(model)
        if not hosts:
            return None
        weights = [1.0 / max(h.latency_ms, 1.0) for h in hosts]
        return random.choices(hosts, weights=weights, k=1)[0]

    # -- Backstory generation -----------------------------------------------

    def _generate_backstory(self, target: SimulationTarget, model: str) -> dict | None:
        """Generate a backstory for a target. Uses cache, LLM, or scripted fallback.

        Retry logic:
        1. Check cache -> return if hit
        2. Call LLM -> parse -> validate -> cache on success
        3. On malformed JSON: retry once with same host
        4. On second failure: return scripted fallback
        """
        # Check cache first
        key = self._cache_key(target)
        with self._cache_lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached

        # Attempt LLM generation (up to 2 tries)
        prompt = self._build_prompt(target)
        alliance = target.alliance

        for attempt in range(2):
            host = self._select_host(model)
            if host is None:
                # No host available — skip to fallback
                break

            try:
                raw = self._fleet.generate(model, prompt, timeout=30.0)
                if not raw:
                    continue
                result = self._parse_response(raw, alliance)
                if result is not None:
                    self._save_to_cache(key, result)
                    return result
            except Exception:
                log.exception("LLM call failed (attempt %d) for %s", attempt + 1, target.target_id)

        # Scripted fallback
        return self._scripted_fallback(target)

    # -- Prompt building ----------------------------------------------------

    def _build_prompt(self, target: SimulationTarget) -> str:
        """Build the LLM prompt for backstory generation.

        Each prompt is seeded with a random archetype, motivation, sector
        description, and time-of-day context so that even same-type units
        get wildly different personality seeds.
        """
        alliance = target.alliance
        x, y = target.position
        sector = _position_sector(x, y)
        tod = _time_of_day_context()

        if alliance == "friendly":
            return _DEFENDER_PROMPT.format(
                system=_SYSTEM_PROMPT,
                asset_type=target.asset_type,
                name=target.name,
                x=x,
                y=y,
                sector=sector,
                time_of_day=tod,
                archetype=random.choice(_DEFENDER_ARCHETYPES),
                motivation=random.choice(_DEFENDER_MOTIVATIONS),
            )
        elif alliance == "hostile":
            return _HOSTILE_PROMPT.format(
                system=_SYSTEM_PROMPT,
                asset_type=target.asset_type,
                name=target.name,
                heading_desc=_heading_description(target.heading),
                x=x,
                y=y,
                sector=sector,
                time_of_day=tod,
                archetype=random.choice(_HOSTILE_ARCHETYPES),
                motivation=random.choice(_HOSTILE_MOTIVATIONS),
            )
        else:
            return _NEUTRAL_PROMPT.format(
                system=_SYSTEM_PROMPT,
                asset_type=target.asset_type,
                name=target.name,
                x=x,
                y=y,
                sector=sector,
                time_of_day=tod,
                archetype=random.choice(_NEUTRAL_ARCHETYPES),
                motivation=random.choice(_NEUTRAL_MOTIVATIONS),
            )

    # -- Response parsing ---------------------------------------------------

    def _parse_response(self, raw: str, alliance: str) -> dict | None:
        """Parse LLM response into a validated backstory dict.

        Steps:
        1. Strip markdown code blocks
        2. Try json.loads()
        3. Regex for {...} within response
        4. Validate required keys
        """
        text = raw.strip()

        # Strip markdown code blocks: ```json ... ``` or ``` ... ```
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if md_match:
            text = md_match.group(1).strip()

        # Try direct parse
        data = self._try_json_parse(text)
        if data is None:
            # Regex for {...} block
            brace_match = re.search(r"\{.*\}", text, re.DOTALL)
            if brace_match:
                data = self._try_json_parse(brace_match.group(0))

        if data is None:
            return None

        if not self._validate_backstory(data, alliance):
            return None

        return data

    @staticmethod
    def _try_json_parse(text: str) -> dict | None:
        """Attempt to parse text as JSON. Returns dict or None."""
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    # -- Validation ---------------------------------------------------------

    def _validate_backstory(self, data: dict, alliance: str) -> bool:
        """Validate that a backstory dict has all required fields for the alliance type."""
        required = _ALLIANCE_FIELDS.get(alliance, _SHARED_FIELDS)
        return required.issubset(data.keys())

    # -- Completion handler -------------------------------------------------

    def _on_backstory_complete(self, target_id: str, backstory: dict) -> None:
        """Handle backstory completion: update target name, identity, emit event, set thought."""
        # Update target name if available
        target = self._targets.get(target_id)
        if target is not None and "name" in backstory:
            target.name = backstory["name"]

        # Apply identity fields from backstory to the target's UnitIdentity
        if target is not None and target.identity is not None:
            ident = target.identity
            if backstory.get("first_name"):
                ident.first_name = backstory["first_name"]
            if backstory.get("last_name"):
                ident.last_name = backstory["last_name"]
            if backstory.get("home_address"):
                ident.home_address = backstory["home_address"]
            if backstory.get("employer"):
                ident.employer = backstory["employer"]
            if backstory.get("work_address"):
                ident.work_address = backstory["work_address"]
            if backstory.get("serial_number"):
                ident.serial_number = backstory["serial_number"]
            if backstory.get("firmware_version"):
                ident.firmware_version = backstory["firmware_version"]
            if backstory.get("license_plate"):
                ident.license_plate = backstory["license_plate"]
            if backstory.get("vehicle_make"):
                ident.vehicle_make = backstory["vehicle_make"]
            if backstory.get("vehicle_model"):
                ident.vehicle_model = backstory["vehicle_model"]
            if backstory.get("vehicle_year"):
                ident.vehicle_year = backstory["vehicle_year"]
            if backstory.get("vehicle_color"):
                ident.vehicle_color = backstory["vehicle_color"]
            if backstory.get("owner_name"):
                ident.owner_name = backstory["owner_name"]
            if backstory.get("owner_address"):
                ident.owner_address = backstory["owner_address"]

        # Publish event (include identity in backstory data)
        backstory_with_identity = dict(backstory)
        if target is not None and target.identity is not None:
            backstory_with_identity["identity"] = target.identity.to_dict()

        self._event_bus.publish("backstory_generated", {
            "target_id": target_id,
            "backstory": backstory_with_identity,
        })

        # Set thought bubble (low importance — backstory intro, not combat-critical)
        if self._thought_registry is not None:
            from engine.simulation.npc_intelligence.thought_registry import IMPORTANCE_LOW
            text = backstory.get("motivation", backstory.get("background", "Reporting for duty."))
            self._thought_registry.set_thought(
                target_id, text, emotion="neutral", duration=8.0,
                importance=IMPORTANCE_LOW,
            )

    # -- Scripted fallback --------------------------------------------------

    def _scripted_fallback(self, target: SimulationTarget) -> dict:
        """Return a scripted fallback backstory for the target."""
        alliance = target.alliance
        pool = _SCRIPTED_FALLBACKS.get(alliance, _SCRIPTED_FALLBACKS["neutral"])
        fallback = random.choice(pool).copy()
        # Override name with target name if meaningful
        if target.name and target.name not in ("", "Unknown"):
            fallback["name"] = target.name
        return fallback

    # -- Cache operations ---------------------------------------------------

    def _cache_key(self, target: SimulationTarget) -> str:
        """Compute a stable cache key from (target_id, alliance, asset_type, name).

        Uses target_id so that two units of the same type/name get
        independent cache entries and therefore independent backstories.
        """
        raw = f"{target.target_id}:{target.alliance}:{target.asset_type}:{target.name}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _load_cache(self) -> None:
        """Load the disk cache index into memory."""
        index_path = self._cache_dir / "index.json"
        if not index_path.exists():
            return
        try:
            data = json.loads(index_path.read_text())
            if isinstance(data, dict):
                with self._cache_lock:
                    self._cache.update(data)
        except (json.JSONDecodeError, OSError):
            log.warning("Failed to load backstory cache from %s", index_path)

    def _save_to_cache(self, key: str, backstory: dict) -> None:
        """Save a backstory to the in-memory and disk cache."""
        with self._cache_lock:
            self._cache[key] = backstory

        # Persist to disk
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        index_path = self._cache_dir / "index.json"
        try:
            # Read existing index, merge, write
            existing: dict = {}
            if index_path.exists():
                try:
                    existing = json.loads(index_path.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
            existing[key] = backstory
            index_path.write_text(json.dumps(existing, indent=2))
        except OSError:
            log.warning("Failed to save backstory cache to %s", index_path)
