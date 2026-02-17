"""WarAnnouncer -- Smash TV / Unreal Tournament style war commentary.

Subscribes to game events via EventBus and generates contextual
announcements.  Can use TTS (Amy's speaker) or publish text events for
frontend display.

Priority scale (higher = more important, preempts lower):
    10  countdown
     9  victory / defeat
     7  kill streak
     6  wave start / complete
     4  kill
     3  tactical
"""

from __future__ import annotations

import random
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Phrase banks  (never repeat same line twice in a row per category)
# ---------------------------------------------------------------------------

ENGAGE_PHRASES: list[str] = [
    "ENGAGE! ENGAGE! ENGAGE!",
    "ALL UNITS -- WEAPONS FREE!",
    "THE WAR HAS BEGUN!",
    "DEFEND THE NEIGHBORHOOD!",
    "HOSTILES INCOMING -- LIGHT 'EM UP!",
]

KILL_PHRASES: list[str] = [
    "{killer} takes down {target}!",
    "{target} ELIMINATED by {killer}!",
    "Hostile down! {killer} scores the kill!",
    "{killer} neutralizes {target}!",
    "BOOM! {target} is out!",
    "Nice shot, {killer}!",
    "{target} didn't see that coming!",
    "{killer} sends {target} back to respawn!",
    "Clean kill by {killer}!",
]

STREAK_PHRASES: dict[int, list[str]] = {
    3:  ["{name} -- KILLING SPREE!", "{name} -- TRIPLE KILL!"],
    5:  ["RAMPAGE! {name} is unstoppable!", "{name} -- MEGA KILL!"],
    7:  ["DOMINATING! {name} owns the battlefield!", "ULTRA KILL -- {name}!"],
    10: ["GODLIKE! {name} IS A ONE-UNIT ARMY!", "MONSTER KILL -- {name}!"],
}

WAVE_START_PHRASES: list[str] = [
    "WAVE {num}: {name}! {count} hostiles incoming!",
    "Here they come! Wave {num} -- {name}!",
    "Alert! {count} contacts approaching! Wave {num}: {name}!",
    "Brace yourselves! Wave {num}: {name} -- {count} hostile targets!",
]

WAVE_COMPLETE_PHRASES: list[str] = [
    "Wave {num} CLEARED! {kills} hostiles eliminated!",
    "Area secured! Wave {num} neutralized -- {kills} kills!",
    "All hostiles down! Wave {num} complete -- {kills} eliminated!",
    "Outstanding! Wave {num} decimated -- {kills} kills! Next wave incoming...",
]

VICTORY_PHRASES: list[str] = [
    "VICTORY! NEIGHBORHOOD SECURED! {kills} hostiles eliminated across {waves} waves!",
    "ALL WAVES DEFEATED! The neighborhood is SAFE! {waves} waves, {kills} kills!",
    "MISSION ACCOMPLISHED! {waves} waves crushed! {kills} total kills!",
    "YOU WIN! {waves} waves cleared! {kills} eliminations!",
]

DEFEAT_PHRASES: list[str] = [
    "DEFEAT! The neighborhood has fallen! Survived {waves} waves with {kills} kills.",
    "GAME OVER! Hostiles have overrun the defenses! {kills} kills weren't enough!",
    "Mission failed! {waves} waves survived before being overwhelmed.",
]

THREAT_PHRASES: list[str] = [
    "Hostile confirmed! {name} is a threat!",
    "Target {name} classified hostile!",
    "We have a confirmed hostile -- {name}!",
]


# ---------------------------------------------------------------------------
# WarAnnouncer
# ---------------------------------------------------------------------------

class WarAnnouncer:
    """Smash TV / Unreal Tournament style war commentary.

    Subscribes to game events via EventBus and generates
    contextual announcements.  Can optionally use TTS (Amy's speaker)
    or publishes text events for frontend display.
    """

    # Minimum gap between announcements (seconds), except countdown
    DEBOUNCE_SECONDS: float = 1.5

    def __init__(self, event_bus: EventBus, speaker: object | None = None) -> None:
        self._event_bus = event_bus
        self._speaker = speaker  # Amy's TTS speaker, or None for text-only
        self._kill_count: int = 0
        self._wave_kill_count: int = 0
        self._last_announcement: float = 0.0
        self._last_priority: int = 0
        self._running: bool = False
        self._last_by_category: dict[str, str] = {}
        self._sub_queue = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to game events and start announcement processing."""
        self._running = True
        self._sub_queue = self._event_bus.subscribe()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop processing and unsubscribe."""
        self._running = False
        if self._sub_queue is not None:
            self._event_bus.unsubscribe(self._sub_queue)
            self._sub_queue = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def kill_count(self) -> int:
        return self._kill_count

    @property
    def wave_kill_count(self) -> int:
        return self._wave_kill_count

    # ------------------------------------------------------------------
    # Event processing loop
    # ------------------------------------------------------------------

    def _process_loop(self) -> None:
        """Background thread: read events from bus, route to handlers."""
        import queue as _queue

        while self._running:
            try:
                msg = self._sub_queue.get(timeout=0.25)
            except _queue.Empty:
                continue

            etype = msg.get("type", "")
            data = msg.get("data") or {}

            try:
                if etype == "game_countdown":
                    self._on_countdown(data.get("seconds_remaining", 0))
                elif etype == "game_state_change":
                    if data.get("new_state") == "active":
                        self._on_countdown(0)
                elif etype == "target_eliminated":
                    self._on_target_eliminated(data)
                elif etype == "kill_streak":
                    self._on_kill_streak(data)
                elif etype == "wave_start":
                    self._on_wave_start(data)
                elif etype == "wave_complete":
                    self._on_wave_complete(data)
                elif etype == "game_over":
                    self._on_game_over(data)
                elif etype == "threat_escalation":
                    self._on_threat_escalation(data)
            except Exception as e:
                print(f"  [announcer error: {e}]")

    # ------------------------------------------------------------------
    # Announce helper
    # ------------------------------------------------------------------

    def _announce(self, text: str, category: str, priority: int = 5) -> None:
        """Deliver an announcement immediately.

        Higher priority preempts lower.  Debounce prevents spam
        (1.5 s minimum gap), except countdown/victory/defeat which
        always go through.  A higher-priority announcement can also
        break through the debounce window.
        """
        now = time.monotonic()

        # Debounce: skip if too soon, unless exempt category or higher priority
        if category not in ("countdown", "victory", "defeat"):
            elapsed = now - self._last_announcement
            if elapsed < self.DEBOUNCE_SECONDS:
                if priority <= self._last_priority:
                    return

        self._last_announcement = now
        self._last_priority = priority

        # Publish on EventBus so frontend / other systems can react
        self._event_bus.publish("amy_announcement", {
            "text": text,
            "category": category,
            "priority": priority,
            "timestamp": now,
        })

        # Track last announcement per category (for anti-repeat)
        self._last_by_category[category] = text

        # TTS if speaker available
        if self._speaker is not None:
            try:
                self._speaker.speak(text)
            except Exception:
                pass  # Best-effort TTS

    def _pick_phrase(self, phrases: list[str], category: str, **fmt: str) -> str:
        """Pick a random phrase, avoiding the last one used in this category."""
        last = self._last_by_category.get(category, "")
        candidates = [p for p in phrases if p != last] or phrases
        template = random.choice(candidates)
        return template.format(**fmt)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_countdown(self, seconds_remaining: int) -> None:
        """Called each countdown tick."""
        if seconds_remaining > 0:
            self._announce(str(seconds_remaining), "countdown", priority=10)
        else:
            text = self._pick_phrase(ENGAGE_PHRASES, "countdown")
            self._announce(text, "countdown", priority=10)

    def _on_target_eliminated(self, data: dict) -> None:
        """Called when any target is eliminated."""
        killer = data.get("killer_name", "Unknown")
        target = data.get("target_name", "Unknown")
        self._kill_count += 1
        self._wave_kill_count += 1

        text = self._pick_phrase(KILL_PHRASES, "kill", killer=killer, target=target)
        self._announce(text, "kill", priority=4)

    def _on_kill_streak(self, data: dict) -> None:
        """Called on kill streaks (3, 5, 7, 10)."""
        streak = data.get("streak", 0)
        name = data.get("killer_name", "Unknown")

        phrases = STREAK_PHRASES.get(streak)
        if phrases:
            text = self._pick_phrase(phrases, "kill_streak", name=name)
        else:
            text = f"{name} -- {streak} KILL STREAK!"
        self._announce(text, "kill_streak", priority=7)

    def _on_wave_start(self, data: dict) -> None:
        """Called when a new wave begins."""
        wave_num = data.get("wave_number", 1)
        wave_name = data.get("wave_name", f"Wave {wave_num}")
        count = data.get("hostile_count", 0)
        self._wave_kill_count = 0

        text = self._pick_phrase(
            WAVE_START_PHRASES, "wave",
            num=str(wave_num), name=wave_name, count=str(count),
        )
        self._announce(text, "wave", priority=6)

    def _on_wave_complete(self, data: dict) -> None:
        """Called when a wave is cleared."""
        wave_num = data.get("wave_number", 1)
        kills = data.get("kills", self._wave_kill_count)

        text = self._pick_phrase(
            WAVE_COMPLETE_PHRASES, "wave",
            num=str(wave_num), kills=str(kills),
        )
        self._announce(text, "wave", priority=6)

    def _on_threat_escalation(self, data: dict) -> None:
        """Tactical awareness callouts (30% chance to announce)."""
        if data.get("new_level") != "hostile":
            return
        if random.random() >= 0.3:
            return

        name = data.get("target_name", "Unknown contact")
        text = self._pick_phrase(THREAT_PHRASES, "tactical", name=name)
        self._announce(text, "tactical", priority=3)

    def _on_game_over(self, data: dict) -> None:
        """Called when the game ends."""
        result = data.get("result", "defeat")
        kills = data.get("total_kills", self._kill_count)
        waves = data.get("waves_completed", 0)

        if result == "victory":
            text = self._pick_phrase(
                VICTORY_PHRASES, "victory",
                kills=str(kills), waves=str(waves),
            )
            self._announce(text, "victory", priority=9)
        else:
            text = self._pick_phrase(
                DEFEAT_PHRASES, "defeat",
                kills=str(kills), waves=str(waves),
            )
            self._announce(text, "defeat", priority=9)

    # ------------------------------------------------------------------
    # Situational awareness (called externally by game loop)
    # ------------------------------------------------------------------

    def situational_update(self, hostile_count: int, friendly_count: int) -> None:
        """Periodic situational callout during battle."""
        if hostile_count > friendly_count * 2:
            self._announce("We're outnumbered! Hold the line!", "tactical", priority=3)
        elif hostile_count == 1:
            self._announce("One hostile remaining! Finish them!", "tactical", priority=4)
        elif hostile_count == 0 and self._wave_kill_count > 0:
            self._announce("Area clear! Regroup!", "tactical", priority=3)

    # ------------------------------------------------------------------
    # Direct announcement (for Lua actions: battle_cry, taunt)
    # ------------------------------------------------------------------

    def battle_cry(self, text: str) -> None:
        """High-priority announcement from Amy (Lua action)."""
        self._announce(text, "battle_cry", priority=8)

    def taunt(self, target_name: str) -> None:
        """Taunt a specific hostile target (Lua action)."""
        taunt_phrases = [
            f"Is that all you've got, {target_name}?",
            f"You call that an attack, {target_name}?",
            f"Come get some, {target_name}!",
            f"{target_name}! You're in MY neighborhood now!",
            f"Run while you can, {target_name}!",
            f"{target_name} -- you just made the biggest mistake of your life!",
        ]
        text = self._pick_phrase(taunt_phrases, "taunt", name=target_name)
        self._announce(text, "taunt", priority=5)

    # ------------------------------------------------------------------
    # Reset (between games)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset counters for a new game."""
        self._kill_count = 0
        self._wave_kill_count = 0
        self._last_announcement = 0.0
        self._last_priority = 0
        self._last_by_category.clear()
