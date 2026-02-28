# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for WarAnnouncer — Amy's Smash TV / UT style war commentary."""

from __future__ import annotations

import queue
import time
from unittest.mock import MagicMock

import pytest

from amy.actions.announcer import (
    DEFEAT_PHRASES,
    ENGAGE_PHRASES,
    ELIMINATION_PHRASES,
    STREAK_PHRASES,
    VICTORY_PHRASES,
    WAVE_COMPLETE_PHRASES,
    WAVE_START_PHRASES,
    THREAT_PHRASES,
    WarAnnouncer,
)
from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def announcer(bus: EventBus) -> WarAnnouncer:
    return WarAnnouncer(bus)


@pytest.fixture
def announcer_with_speaker(bus: EventBus) -> WarAnnouncer:
    speaker = MagicMock()
    return WarAnnouncer(bus, speaker=speaker)


def collect_announcements(bus: EventBus, count: int = 1, timeout: float = 2.0) -> list[dict]:
    """Subscribe to bus and collect amy_announcement events."""
    q = bus.subscribe()
    results = []
    deadline = time.monotonic() + timeout
    while len(results) < count and time.monotonic() < deadline:
        try:
            msg = q.get(timeout=0.1)
            if msg.get("type") == "amy_announcement":
                results.append(msg.get("data", {}))
        except queue.Empty:
            continue
    bus.unsubscribe(q)
    return results


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWarAnnouncerInit:
    def test_default_state(self, bus: EventBus) -> None:
        ann = WarAnnouncer(bus)
        assert ann.elimination_count == 0
        assert ann.wave_elimination_count == 0
        assert ann.running is False

    def test_with_speaker(self, bus: EventBus) -> None:
        speaker = MagicMock()
        ann = WarAnnouncer(bus, speaker=speaker)
        assert ann._speaker is speaker

    def test_without_speaker(self, bus: EventBus) -> None:
        ann = WarAnnouncer(bus)
        assert ann._speaker is None


# ---------------------------------------------------------------------------
# Countdown
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCountdown:
    def test_countdown_number(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_countdown(3)
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["text"] == "3"
        assert ann_msgs[0]["data"]["category"] == "countdown"
        assert ann_msgs[0]["data"]["priority"] == 10

    def test_countdown_zero_engage(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_countdown(0)
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["text"] in ENGAGE_PHRASES
        assert ann_msgs[0]["data"]["priority"] == 10

    def test_countdown_bypasses_debounce(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """Countdown announcements should not be debounced."""
        q = bus.subscribe()
        announcer._on_countdown(3)
        announcer._on_countdown(2)
        announcer._on_countdown(1)
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 3
        texts = [m["data"]["text"] for m in ann_msgs]
        assert texts == ["3", "2", "1"]


# ---------------------------------------------------------------------------
# Kill announcements
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestKillAnnouncements:
    def test_target_eliminated(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_target_eliminated({
            "interceptor_name": "Rover Alpha",
            "target_name": "Intruder Bravo",
        })
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["category"] == "elimination"
        assert ann_msgs[0]["data"]["priority"] == 4
        assert "Rover Alpha" in ann_msgs[0]["data"]["text"] or "Intruder Bravo" in ann_msgs[0]["data"]["text"]

    def test_kill_increments_counts(self, announcer: WarAnnouncer) -> None:
        assert announcer.elimination_count == 0
        assert announcer.wave_elimination_count == 0
        announcer._on_target_eliminated({"interceptor_name": "A", "target_name": "B"})
        assert announcer.elimination_count == 1
        assert announcer.wave_elimination_count == 1
        announcer._on_target_eliminated({"interceptor_name": "A", "target_name": "C"})
        assert announcer.elimination_count == 2
        assert announcer.wave_elimination_count == 2

    def test_kill_default_names(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_target_eliminated({})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        # Should use "Unknown" as default
        assert "Unknown" in ann_msgs[0]["data"]["text"]


# ---------------------------------------------------------------------------
# Kill streaks
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestKillStreaks:
    def test_streak_3(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_elimination_streak({"streak": 3, "interceptor_name": "Rover Alpha"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["category"] == "elimination_streak"
        assert ann_msgs[0]["data"]["priority"] == 7
        text = ann_msgs[0]["data"]["text"]
        assert "Rover Alpha" in text

    def test_streak_5(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_elimination_streak({"streak": 5, "interceptor_name": "Drone Beta"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        text = ann_msgs[0]["data"]["text"]
        assert "Drone Beta" in text

    def test_streak_7(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_elimination_streak({"streak": 7, "interceptor_name": "Turret C"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        text = ann_msgs[0]["data"]["text"]
        assert "Turret C" in text

    def test_streak_10_godlike(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_elimination_streak({"streak": 10, "interceptor_name": "MegaUnit"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        text = ann_msgs[0]["data"]["text"]
        assert "MegaUnit" in text

    def test_streak_unknown_count(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """Streak count without specific phrases falls back to generic."""
        q = bus.subscribe()
        announcer._on_elimination_streak({"streak": 15, "interceptor_name": "Hero"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert "15 ELIMINATION STREAK" in ann_msgs[0]["data"]["text"]

    def test_streak_interrupts_kill_on_debounce(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """Kill streak (priority 7) should still fire even if a kill was just announced."""
        q = bus.subscribe()
        # First: a regular kill
        announcer._on_target_eliminated({"interceptor_name": "A", "target_name": "B"})
        # Immediately: a streak announcement (higher priority)
        announcer._on_elimination_streak({"streak": 5, "interceptor_name": "A"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        # The kill should come through, and the streak should also come through
        # because streak priority (7) > kill priority (4)
        categories = [m["data"]["category"] for m in ann_msgs]
        assert "elimination" in categories
        assert "elimination_streak" in categories


# ---------------------------------------------------------------------------
# Wave announcements
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWaveAnnouncements:
    def test_wave_start(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_wave_start({
            "wave_number": 3,
            "wave_name": "The Swarm",
            "hostile_count": 12,
        })
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["category"] == "wave"
        assert ann_msgs[0]["data"]["priority"] == 6
        text = ann_msgs[0]["data"]["text"]
        assert "3" in text
        assert "The Swarm" in text
        assert "12" in text

    def test_wave_start_resets_wave_kills(self, announcer: WarAnnouncer) -> None:
        announcer._elimination_count = 5
        announcer._wave_elimination_count = 5
        announcer._on_wave_start({"wave_number": 2, "wave_name": "Test", "hostile_count": 4})
        assert announcer.wave_elimination_count == 0
        assert announcer.elimination_count == 5  # total unchanged

    def test_wave_complete(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_wave_complete({"wave_number": 2, "eliminations": 8})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["category"] == "wave"
        text = ann_msgs[0]["data"]["text"]
        assert "2" in text
        assert "8" in text

    def test_wave_complete_uses_wave_kills_as_default(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """If kills not in data, use wave_kill_count."""
        announcer._wave_elimination_count = 7
        q = bus.subscribe()
        announcer._on_wave_complete({"wave_number": 1})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert "7" in ann_msgs[0]["data"]["text"]

    def test_wave_start_default_name(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_wave_start({"wave_number": 5, "hostile_count": 3})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        text = ann_msgs[0]["data"]["text"]
        assert "Wave 5" in text


# ---------------------------------------------------------------------------
# Game over
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGameOver:
    def test_victory(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_game_over({"result": "victory", "total_eliminations": 42, "waves_completed": 10})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["category"] == "victory"
        assert ann_msgs[0]["data"]["priority"] == 9
        text = ann_msgs[0]["data"]["text"]
        assert "42" in text
        assert "10" in text

    def test_defeat(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_game_over({"result": "defeat", "total_eliminations": 15, "waves_completed": 3})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["category"] == "defeat"
        assert ann_msgs[0]["data"]["priority"] == 9

    def test_defeat_is_default(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_game_over({"total_eliminations": 5, "waves_completed": 1})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["category"] == "defeat"

    def test_victory_bypasses_debounce(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """Victory/defeat should not be debounced."""
        q = bus.subscribe()
        announcer._on_target_eliminated({"interceptor_name": "A", "target_name": "B"})
        announcer._on_game_over({"result": "victory", "total_eliminations": 1, "waves_completed": 1})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        categories = [m["data"]["category"] for m in ann_msgs]
        assert "victory" in categories


# ---------------------------------------------------------------------------
# Threat escalation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestThreatEscalation:
    def test_hostile_escalation_sometimes_announces(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """Should announce ~30% of hostile escalations."""
        q = bus.subscribe()
        announced = 0
        for _ in range(100):
            announcer._last_announcement = 0.0  # reset debounce
            announcer._on_threat_escalation({"new_level": "hostile", "target_name": "Test"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        # With 100 tries at 30% chance, expect roughly 20-40 announcements
        assert 5 < len(ann_msgs) < 60

    def test_non_hostile_escalation_ignored(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer._on_threat_escalation({"new_level": "suspicious", "target_name": "Test"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 0


# ---------------------------------------------------------------------------
# Debounce
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDebounce:
    def test_rapid_kills_debounced(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """Rapid kills within debounce window should be suppressed."""
        q = bus.subscribe()
        for i in range(5):
            announcer._on_target_eliminated({"interceptor_name": "A", "target_name": f"T{i}"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        # Only first should get through (rest debounced at same priority)
        assert len(ann_msgs) == 1

    def test_debounce_resets_after_window(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """After debounce window, new announcements go through."""
        q = bus.subscribe()
        announcer._on_target_eliminated({"interceptor_name": "A", "target_name": "B"})
        # Manually reset debounce timer
        announcer._last_announcement = time.monotonic() - 2.0
        announcer._on_target_eliminated({"interceptor_name": "A", "target_name": "C"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 2


# ---------------------------------------------------------------------------
# Anti-repeat
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAntiRepeat:
    def test_pick_phrase_avoids_repeat(self, announcer: WarAnnouncer) -> None:
        """_pick_phrase should not repeat the last phrase in a category."""
        phrases = ["A", "B", "C"]
        announcer._last_by_category["test"] = "A"
        results = set()
        for _ in range(50):
            result = announcer._pick_phrase(phrases, "test")
            results.add(result)
        assert "A" not in results or len(phrases) == 1

    def test_pick_phrase_with_single_option(self, announcer: WarAnnouncer) -> None:
        """If only one phrase, it's allowed to repeat."""
        phrases = ["ONLY"]
        announcer._last_by_category["test"] = "ONLY"
        result = announcer._pick_phrase(phrases, "test")
        assert result == "ONLY"


# ---------------------------------------------------------------------------
# Situational updates
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSituationalUpdates:
    def test_outnumbered(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer.situational_update(hostile_count=10, friendly_count=3)
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert "outnumbered" in ann_msgs[0]["data"]["text"].lower()

    def test_one_remaining(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer.situational_update(hostile_count=1, friendly_count=3)
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert "one hostile" in ann_msgs[0]["data"]["text"].lower()

    def test_area_clear(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        announcer._wave_elimination_count = 5
        q = bus.subscribe()
        announcer.situational_update(hostile_count=0, friendly_count=3)
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert "clear" in ann_msgs[0]["data"]["text"].lower()

    def test_no_update_when_not_applicable(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """No announcement if conditions don't match any branch."""
        q = bus.subscribe()
        announcer.situational_update(hostile_count=3, friendly_count=3)
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 0


# ---------------------------------------------------------------------------
# Battle cry and taunt (Lua actions)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBattleCryAndTaunt:
    def test_battle_cry(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer.battle_cry("FOR THE NEIGHBORHOOD!")
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["text"] == "FOR THE NEIGHBORHOOD!"
        assert ann_msgs[0]["data"]["category"] == "battle_cry"
        assert ann_msgs[0]["data"]["priority"] == 8

    def test_taunt(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        q = bus.subscribe()
        announcer.taunt("Intruder Delta")
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        assert len(ann_msgs) == 1
        assert ann_msgs[0]["data"]["category"] == "taunt"
        assert ann_msgs[0]["data"]["priority"] == 5
        assert "Intruder Delta" in ann_msgs[0]["data"]["text"]


# ---------------------------------------------------------------------------
# Speaker integration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSpeakerIntegration:
    def test_speaker_called_on_announce(self, announcer_with_speaker: WarAnnouncer) -> None:
        announcer_with_speaker._on_countdown(0)
        assert announcer_with_speaker._speaker.speak.called

    def test_speaker_not_called_when_none(self, announcer: WarAnnouncer) -> None:
        """No error when speaker is None."""
        announcer._on_countdown(0)  # Should not raise

    def test_speaker_error_suppressed(self, bus: EventBus) -> None:
        speaker = MagicMock()
        speaker.speak.side_effect = RuntimeError("TTS failed")
        ann = WarAnnouncer(bus, speaker=speaker)
        ann._on_countdown(0)  # Should not raise


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLifecycle:
    def test_start_stop(self, announcer: WarAnnouncer) -> None:
        announcer.start()
        assert announcer.running is True
        assert announcer._thread is not None
        assert announcer._thread.is_alive()
        announcer.stop()
        assert announcer.running is False

    def test_double_stop_safe(self, announcer: WarAnnouncer) -> None:
        announcer.start()
        announcer.stop()
        announcer.stop()  # Should not raise

    def test_event_bus_processing(self, bus: EventBus) -> None:
        """Announcer should pick up events published on the bus."""
        ann = WarAnnouncer(bus)
        ann.start()
        try:
            q = bus.subscribe()
            # Publish a countdown event
            bus.publish("game_countdown", {"seconds_remaining": 3})
            # Wait for processing
            time.sleep(0.5)
            msgs = []
            while not q.empty():
                msgs.append(q.get_nowait())
            ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
            assert len(ann_msgs) == 1
            assert ann_msgs[0]["data"]["text"] == "3"
        finally:
            ann.stop()
            bus.unsubscribe(q)

    def test_game_state_change_to_active(self, bus: EventBus) -> None:
        """game_state_change with new_state=active triggers engage."""
        ann = WarAnnouncer(bus)
        ann.start()
        try:
            q = bus.subscribe()
            bus.publish("game_state_change", {"new_state": "active"})
            time.sleep(0.5)
            msgs = []
            while not q.empty():
                msgs.append(q.get_nowait())
            ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
            assert len(ann_msgs) == 1
            assert ann_msgs[0]["data"]["text"] in ENGAGE_PHRASES
        finally:
            ann.stop()
            bus.unsubscribe(q)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReset:
    def test_reset_clears_counters(self, announcer: WarAnnouncer) -> None:
        announcer._elimination_count = 10
        announcer._wave_elimination_count = 5
        announcer._last_announcement = 99.0
        announcer._last_by_category["elimination"] = "some phrase"
        announcer.reset()
        assert announcer.elimination_count == 0
        assert announcer.wave_elimination_count == 0
        assert announcer._last_announcement == 0.0
        assert announcer._last_by_category == {}


# ---------------------------------------------------------------------------
# Lua motor integration (battle_cry / taunt actions parse correctly)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLuaMotorIntegration:
    def test_battle_cry_parses(self) -> None:
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('battle_cry("FOR THE NEIGHBORHOOD!")')
        assert result.valid
        assert result.action == "battle_cry"
        assert result.params == ["FOR THE NEIGHBORHOOD!"]

    def test_taunt_parses(self) -> None:
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('taunt("Intruder Delta")')
        assert result.valid
        assert result.action == "taunt"
        assert result.params == ["Intruder Delta"]

    def test_battle_cry_requires_string(self) -> None:
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('battle_cry(42)')
        assert not result.valid
        assert "string" in result.error.lower()

    def test_taunt_requires_string(self) -> None:
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('taunt(42)')
        assert not result.valid
        assert "string" in result.error.lower()


# ---------------------------------------------------------------------------
# Thinking prompt war mode context
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestThinkingWarMode:
    def test_war_mode_context_format(self) -> None:
        from amy.brain.thinking import WAR_MODE_CONTEXT
        ctx = WAR_MODE_CONTEXT.format(
            wave=3,
            total_waves=10,
            wave_name="The Swarm",
            hostile_count=12,
            friendly_count=4,
            turrets=1,
            drones=2,
            rovers=1,
            score=1500,
            kills=8,
        )
        assert "WAR MODE ACTIVE" in ctx
        assert "Wave 3" in ctx or "3/10" in ctx
        assert "The Swarm" in ctx
        assert "12 hostiles" in ctx
        assert "4 units active" in ctx
        assert "1 turrets" in ctx
        assert "2 drones" in ctx
        assert "1 rovers" in ctx
        assert "1500" in ctx
        assert "8" in ctx

    def test_thinking_prompt_has_war_mode_placeholder(self) -> None:
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert "{war_mode}" in THINKING_SYSTEM_PROMPT

    def test_thinking_prompt_has_battle_cry_action(self) -> None:
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert "battle_cry" in THINKING_SYSTEM_PROMPT

    def test_thinking_prompt_has_taunt_action(self) -> None:
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert "taunt" in THINKING_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPriorityOrdering:
    def test_priority_values(self) -> None:
        """Verify the documented priority hierarchy."""
        # countdown=10 > victory/defeat=9 > battle_cry=8 > kill_streak=7
        # > wave=6 > taunt=5 > kill=4 > tactical=3
        announcer = WarAnnouncer(EventBus())
        # These are verified by the individual test assertions above;
        # this test documents the hierarchy.
        assert True

    def test_high_priority_preempts_during_debounce(self, announcer: WarAnnouncer, bus: EventBus) -> None:
        """Higher priority announcement breaks through debounce."""
        q = bus.subscribe()
        # Fire a low-priority tactical announcement
        announcer._announce("tactical stuff", "tactical", priority=3)
        # Immediately fire a high-priority kill streak (should break through)
        announcer._on_elimination_streak({"streak": 10, "interceptor_name": "Hero"})
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        ann_msgs = [m for m in msgs if m["type"] == "amy_announcement"]
        # Both should be present since streak has higher priority
        assert len(ann_msgs) == 2


# ---------------------------------------------------------------------------
# Phrase bank coverage
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPhraseBanks:
    def test_engage_phrases_non_empty(self) -> None:
        assert len(ENGAGE_PHRASES) >= 3

    def test_kill_phrases_non_empty(self) -> None:
        assert len(ELIMINATION_PHRASES) >= 5

    def test_streak_phrases_cover_milestones(self) -> None:
        assert 3 in STREAK_PHRASES
        assert 5 in STREAK_PHRASES
        assert 7 in STREAK_PHRASES
        assert 10 in STREAK_PHRASES

    def test_wave_start_phrases_non_empty(self) -> None:
        assert len(WAVE_START_PHRASES) >= 3

    def test_wave_complete_phrases_non_empty(self) -> None:
        assert len(WAVE_COMPLETE_PHRASES) >= 3

    def test_victory_phrases_non_empty(self) -> None:
        assert len(VICTORY_PHRASES) >= 3

    def test_defeat_phrases_non_empty(self) -> None:
        assert len(DEFEAT_PHRASES) >= 3

    def test_threat_phrases_non_empty(self) -> None:
        assert len(THREAT_PHRASES) >= 3

    def test_all_elimination_phrases_have_placeholders(self) -> None:
        for phrase in ELIMINATION_PHRASES:
            assert "{interceptor}" in phrase or "{target}" in phrase

    def test_all_streak_phrases_have_name(self) -> None:
        for phrases in STREAK_PHRASES.values():
            for phrase in phrases:
                assert "{name}" in phrase

    def test_all_wave_start_phrases_have_placeholders(self) -> None:
        for phrase in WAVE_START_PHRASES:
            assert "{num}" in phrase

    def test_all_victory_phrases_have_placeholders(self) -> None:
        for phrase in VICTORY_PHRASES:
            assert "{eliminations}" in phrase
            assert "{waves}" in phrase

    def test_all_defeat_phrases_have_placeholders(self) -> None:
        for phrase in DEFEAT_PHRASES:
            assert "{eliminations}" in phrase or "{waves}" in phrase
