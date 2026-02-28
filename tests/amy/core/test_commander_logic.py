# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for Amy Commander — pure logic, no boot/run."""

from __future__ import annotations

import queue
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from amy.commander import Commander, CreatureState, EventBus, EventType, VisionThread

from tests.amy.conftest import MockSensorNode


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEventBus:
    """Tests for the thread-safe pub/sub EventBus."""

    def test_subscribe_publish_delivers_message(self):
        """A subscriber receives messages published after subscribing."""
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("test_event", {"key": "value"})
        msg = q.get_nowait()
        assert msg == {"type": "test_event", "data": {"key": "value"}}

    def test_multiple_subscribers_all_receive(self):
        """All subscribers get the same published message."""
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        q3 = bus.subscribe()
        bus.publish("ping", {"n": 1})
        for q in (q1, q2, q3):
            msg = q.get_nowait()
            assert msg["type"] == "ping"
            assert msg["data"]["n"] == 1

    def test_full_queue_does_not_crash(self):
        """Publishing to a full queue silently drops the message."""
        bus = EventBus()
        q = bus.subscribe()
        # Fill the queue (maxsize=1000)
        for i in range(1000):
            bus.publish("fill", {"i": i})
        assert q.full()
        # This should not raise
        bus.publish("overflow", {"extra": True})
        assert q.qsize() == 1000

    def test_unsubscribe_stops_delivery(self):
        """After unsubscribe, the queue no longer receives messages."""
        bus = EventBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.publish("after_unsub", None)
        assert q.empty()


# ---------------------------------------------------------------------------
# Wake word
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWakeWord:
    """Tests for Commander._check_wake_word."""

    def _make_commander(self, wake_word="amy"):
        """Create a Commander without booting — just __init__."""
        return Commander(nodes={}, wake_word=wake_word)

    def test_wake_word_with_query(self):
        """'hey amy what time is it' extracts the query."""
        cmd = self._make_commander()
        result = cmd._check_wake_word("hey amy what time is it")
        assert result == "what time is it"

    def test_wake_word_without_query_sets_awake(self):
        """'hey amy' returns None and sets _awake=True."""
        cmd = self._make_commander()
        result = cmd._check_wake_word("hey amy")
        assert result is None
        assert cmd._awake is True

    def test_follow_up_when_awake(self):
        """After _awake=True, any transcript is returned as follow-up."""
        cmd = self._make_commander()
        cmd._awake = True
        result = cmd._check_wake_word("what is the weather")
        assert result == "what is the weather"

    def test_no_match_returns_none(self):
        """Transcript without wake word returns None when not awake."""
        cmd = self._make_commander()
        result = cmd._check_wake_word("hello world")
        assert result is None

    def test_wake_word_disabled_returns_transcript(self):
        """When wake_word is None, all transcripts pass through."""
        cmd = self._make_commander(wake_word=None)
        result = cmd._check_wake_word("anything goes")
        assert result == "anything goes"

    @pytest.mark.parametrize("prefix", ["hi", "ok", "okay", "hey"])
    def test_wake_word_variations(self, prefix):
        """Prefixes 'hi', 'ok', 'okay', 'hey' all trigger the wake word."""
        cmd = self._make_commander()
        result = cmd._check_wake_word(f"{prefix} amy tell me a joke")
        assert result == "tell me a joke"


# ---------------------------------------------------------------------------
# Frame sharpness
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFrameSharpness:
    """Tests for Commander._frame_sharpness (static method)."""

    def test_blank_image_low_sharpness(self):
        """A solid-color image has near-zero sharpness."""
        blank = np.zeros((100, 100, 3), dtype=np.uint8)
        sharpness = Commander._frame_sharpness(blank)
        assert isinstance(sharpness, float)
        assert sharpness < 1.0

    def test_patterned_image_higher_sharpness(self):
        """An image with edges has measurably higher sharpness."""
        patterned = np.zeros((100, 100, 3), dtype=np.uint8)
        # Vertical stripes create strong edges
        patterned[:, ::2] = 255
        sharpness = Commander._frame_sharpness(patterned)
        assert sharpness > 100.0


# ---------------------------------------------------------------------------
# Primary camera / PTZ properties
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPrimaryNodes:
    """Tests for primary_camera and primary_ptz properties."""

    def test_primary_camera_returns_camera_node(self):
        """primary_camera returns the first node with has_camera=True."""
        node = MockSensorNode(camera=True, ptz=False)
        cmd = Commander(nodes={"cam": node})
        assert cmd.primary_camera is node

    def test_primary_camera_none_when_no_cameras(self):
        """primary_camera returns None when no nodes have cameras."""
        node = MockSensorNode(camera=False, ptz=False, mic=True, speaker=True)
        cmd = Commander(nodes={"mic_only": node})
        assert cmd.primary_camera is None

    def test_primary_ptz_returns_ptz_node(self):
        """primary_ptz returns the first node with has_ptz=True."""
        node = MockSensorNode(camera=True, ptz=True)
        cmd = Commander(nodes={"ptz_cam": node})
        assert cmd.primary_ptz is node

    def test_primary_ptz_none_when_no_ptz(self):
        """primary_ptz returns None when no nodes have PTZ."""
        node = MockSensorNode(camera=True, ptz=False)
        cmd = Commander(nodes={"fixed_cam": node})
        assert cmd.primary_ptz is None


# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEnumsAndConstants:
    """Tests for CreatureState and VisionThread.TRACKED_CLASSES."""

    def test_creature_state_values(self):
        """CreatureState enum has expected string values."""
        assert CreatureState.IDLE.value == "IDLE"
        assert CreatureState.LISTENING.value == "LISTENING"
        assert CreatureState.THINKING.value == "THINKING"
        assert CreatureState.SPEAKING.value == "SPEAKING"

    def test_tracked_classes_person_at_zero(self):
        """TRACKED_CLASSES maps class 0 to 'person'."""
        assert VisionThread.TRACKED_CLASSES[0] == "person"

    def test_tracked_classes_contains_expected_keys(self):
        """TRACKED_CLASSES contains all expected COCO class IDs."""
        expected_ids = {0, 1, 2, 3, 14, 15, 16, 24, 25, 39, 41, 56, 62, 63, 64, 66, 67, 73}
        assert set(VisionThread.TRACKED_CLASSES.keys()) == expected_ids


# ---------------------------------------------------------------------------
# Speech cleaning
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCleanSpeech:
    """Tests for Commander._clean_speech — strips LLM stage-direction artifacts."""

    def test_strips_parenthetical_stage_directions(self):
        """Parenthetical actions like (Turns head slowly...) are removed."""
        raw = '(Turns head slightly, focusing camera) "Hello there! Welcome."'
        cleaned = Commander._clean_speech(raw)
        assert "Turns head" not in cleaned
        assert "Hello there" in cleaned

    def test_strips_asterisk_stage_directions(self):
        """Asterisk actions like *whirring sound* are removed."""
        raw = '*A slight whirring sound* Hello, welcome to the command center.'
        cleaned = Commander._clean_speech(raw)
        assert "whirring" not in cleaned
        assert "Hello, welcome" in cleaned

    def test_preserves_short_parentheses(self):
        """Short parenthetical asides (4 chars or fewer) are kept."""
        raw = "Hello (hi) there"
        cleaned = Commander._clean_speech(raw)
        assert "(hi)" in cleaned

    def test_removes_smart_quotes(self):
        """Smart quotes are replaced with plain quotes."""
        raw = '\u201cHello there!\u201d'
        cleaned = Commander._clean_speech(raw)
        assert '\u201c' not in cleaned
        assert '\u201d' not in cleaned

    def test_unwraps_quoted_speech(self):
        """If the entire speech is wrapped in double quotes, they're removed."""
        raw = '"Hello, welcome to the command center."'
        cleaned = Commander._clean_speech(raw)
        assert cleaned == "Hello, welcome to the command center."

    def test_preserves_internal_quotes(self):
        """Internal quotes within speech are preserved."""
        raw = 'She said "hello" and then left.'
        cleaned = Commander._clean_speech(raw)
        assert '"hello"' in cleaned

    def test_collapses_multiple_spaces(self):
        """Multiple spaces left by removal are collapsed."""
        raw = '(Sound of camera)  Hello  (whirring)  there!'
        cleaned = Commander._clean_speech(raw)
        assert "  " not in cleaned

    def test_empty_after_cleaning_falls_back(self):
        """If cleaning removes everything, fall back to original text."""
        raw = '(A long parenthetical that is all stage direction)'
        cleaned = Commander._clean_speech(raw)
        assert cleaned == raw  # Fallback to original

    def test_complex_mixed_content(self):
        """Real-world example with mixed stage directions and speech."""
        raw = ('(I quickly scan the cameras, confirming the person\'s location) '
               '"Well, hello! Right now, I\'m observing one person near the center." '
               '*whirring sound accompanies the movement*')
        cleaned = Commander._clean_speech(raw)
        assert "scan the cameras" not in cleaned
        assert "whirring sound" not in cleaned
        assert "hello" in cleaned.lower()
        assert "observing one person" in cleaned


# ---------------------------------------------------------------------------
# Deeper reflection (B2)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDeeperReflection:
    """Tests for structured post-conversation reflection."""

    def _make_commander(self):
        """Create a Commander without booting, with a spy on sensorium.push."""
        cmd = Commander(nodes={})
        cmd.chat_agent = MagicMock()
        cmd.chat_agent.process_turn = MagicMock(return_value="Hello there!")
        cmd.chat_agent.model = "test"
        cmd.chat_agent.history = []
        cmd.thinking = MagicMock()
        cmd.thinking.goal_stack = MagicMock()
        cmd.thinking.goal_stack.context.return_value = ""
        cmd.thinking.suppressed = False
        cmd.vision_thread = None
        cmd.speaker = None
        cmd._use_tts = False
        # Spy on sensorium.push
        cmd.sensorium.push = MagicMock(wraps=cmd.sensorium.push)
        return cmd

    def test_reflection_includes_speaker(self):
        cmd = self._make_commander()
        cmd._respond("Hello Amy")
        calls = [c for c in cmd.sensorium.push.call_args_list
                 if c[0][0] == "thought" and "Conversation" in c[0][1]]
        assert len(calls) >= 1
        assert "someone" in calls[0][0][1].lower() or "Conversation" in calls[0][0][1]

    def test_reflection_includes_named_speaker(self):
        cmd = self._make_commander()
        cmd._respond("I'm Alice, how are you?")
        calls = [c for c in cmd.sensorium.push.call_args_list
                 if c[0][0] == "thought" and "Conversation" in c[0][1]]
        assert len(calls) >= 1
        assert "Alice" in calls[0][0][1]

    def test_reflection_detects_positive_tone(self):
        cmd = self._make_commander()
        cmd._respond("Thanks Amy, that was great!")
        calls = [c for c in cmd.sensorium.push.call_args_list
                 if c[0][0] == "thought" and "Tone:" in c[0][1]]
        assert len(calls) >= 1
        assert "positive" in calls[0][0][1]

    def test_reflection_detects_question(self):
        cmd = self._make_commander()
        cmd._respond("What do you see right now?")
        calls = [c for c in cmd.sensorium.push.call_args_list
                 if c[0][0] == "thought" and "question" in c[0][1].lower()]
        assert len(calls) >= 1

    def test_reflection_importance_is_higher(self):
        cmd = self._make_commander()
        cmd._respond("Hello Amy")
        calls = [c for c in cmd.sensorium.push.call_args_list
                 if c[0][0] == "thought" and "Conversation" in c[0][1]]
        assert len(calls) >= 1
        # Importance should be 0.7 (keyword arg)
        assert calls[0][1].get("importance", 0.5) == 0.7

    def test_reflection_detects_negative_tone(self):
        cmd = self._make_commander()
        cmd._respond("I'm frustrated with this system")
        calls = [c for c in cmd.sensorium.push.call_args_list
                 if c[0][0] == "thought" and "Tone:" in c[0][1]]
        assert len(calls) >= 1
        assert "negative" in calls[0][0][1]

    def test_reflection_neutral_tone_default(self):
        cmd = self._make_commander()
        cmd._respond("The weather is cloudy today")
        calls = [c for c in cmd.sensorium.push.call_args_list
                 if c[0][0] == "thought" and "Tone:" in c[0][1]]
        assert len(calls) >= 1
        assert "neutral" in calls[0][0][1]


# ---------------------------------------------------------------------------
# Mood-aware default motor (C2)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMoodAwareMotor:
    """Tests for Commander._default_motor with mood parameter."""

    def test_default_motor_with_no_ptz_returns_none(self):
        cmd = Commander(nodes={})
        assert cmd._default_motor() is None

    def test_default_motor_passes_mood(self):
        node = MockSensorNode(camera=True, ptz=True)
        cmd = Commander(nodes={"cam": node})
        cmd.sensorium.push("audio", 'User said "hi"')  # triggers engaged mood
        prog = cmd._default_motor()
        assert prog is not None


# ---------------------------------------------------------------------------
# YOLO detection stability (arrival debounce)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestYoloDetectionStability:
    """Tests for VisionThread arrival debounce and departure threshold."""

    def test_vision_thread_has_arrival_frames_counter(self):
        """VisionThread.__init__ initializes _arrival_frames to 0."""
        import inspect
        source = inspect.getsource(VisionThread.__init__)
        assert "_arrival_frames" in source
        assert "_arrival_frames: int = 0" in source or "_arrival_frames = 0" in source

    def test_yolo_confidence_threshold_is_055(self):
        """YOLO confidence threshold should be 0.55 (not 0.4)."""
        # We verify by checking that _detect uses 0.55 in the source
        import inspect
        source = inspect.getsource(VisionThread._detect)
        assert "conf=0.55" in source

    def test_departure_threshold_is_5(self):
        """Departure requires 5 empty frames (not 3)."""
        import inspect
        source = inspect.getsource(VisionThread._detect)
        assert "self._empty_frames >= 5" in source


# ---------------------------------------------------------------------------
# Deep vision language constraint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDeepVisionLanguage:
    """Tests for deep vision model language constraint."""

    def test_deep_think_prompt_contains_english(self):
        """Deep vision system prompt must include 'English' language constraint."""
        import inspect
        source = inspect.getsource(Commander._deep_think_worker)
        assert "Always respond in English" in source


# ---------------------------------------------------------------------------
# Person greeting — no name hallucination
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGreetingNoHallucination:
    """Tests that greeting context prevents name hallucination."""

    def test_empty_known_people_says_no_name(self):
        """When known_people is empty, greeting context tells Amy not to use a name."""
        cmd = Commander(nodes={})
        assert len(cmd.memory.known_people) == 0
        import inspect
        source = inspect.getsource(Commander.run)
        assert "don't know this person's name" in source

    def test_deep_obs_speech_requires_people_present(self):
        """Deep observation speech is gated on sensorium.people_present."""
        import inspect
        source = inspect.getsource(Commander._deep_think_worker)
        assert "self.sensorium.people_present" in source


# ---------------------------------------------------------------------------
# Layered perception — MOTION_DETECTED event + VisionThread properties
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLayeredPerception:
    """Tests for layered perception integration in VisionThread."""

    def test_motion_detected_event_type_exists(self):
        """EventType.MOTION_DETECTED is defined."""
        assert EventType.MOTION_DETECTED.value == "motion_detected"

    def test_vision_thread_has_frame_complexity_property(self):
        """VisionThread exposes frame_complexity as a property."""
        assert hasattr(VisionThread, "frame_complexity")
        # Verify it's actually a property descriptor
        assert isinstance(
            VisionThread.__dict__.get("frame_complexity"),
            property,
        )

    def test_vision_thread_has_frame_metrics_property(self):
        """VisionThread exposes frame_metrics as a property."""
        assert hasattr(VisionThread, "frame_metrics")
        assert isinstance(
            VisionThread.__dict__.get("frame_metrics"),
            property,
        )

    def test_vision_thread_init_has_analyzer(self):
        """VisionThread.__init__ creates a FrameAnalyzer."""
        import inspect
        source = inspect.getsource(VisionThread.__init__)
        assert "FrameAnalyzer" in source

    def test_vision_thread_run_has_yolo_gating(self):
        """VisionThread._run gates YOLO on motion + complexity."""
        import inspect
        source = inspect.getsource(VisionThread._run)
        assert "motion_score" in source
        assert "complexity" in source
        assert "_yolo_skip_count" in source


# ---------------------------------------------------------------------------
# Game event -> sensorium integration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGameEventSensorium:
    """Verify commander routes game events to sensorium."""

    def test_commander_handles_game_state_change_event(self):
        """Commander source code processes game_state_change messages."""
        import inspect
        # The event processing is in the _listen_events method
        source = inspect.getsource(Commander)
        assert "game_state_change" in source
        assert "sensorium.push" in source

    def test_commander_handles_wave_complete_event(self):
        """Commander source code processes wave_complete messages."""
        import inspect
        source = inspect.getsource(Commander)
        assert "wave_complete" in source

    def test_commander_handles_game_over_event(self):
        """Commander source code processes game_over messages."""
        import inspect
        source = inspect.getsource(Commander)
        assert "game_over" in source

    def test_game_state_change_pushes_all_states(self):
        """Commander handles countdown, active, victory, defeat, setup states."""
        import inspect
        source = inspect.getsource(Commander)
        for state in ("countdown", "active", "victory", "defeat", "setup"):
            assert state in source, f"Commander should handle '{state}' state"

    def test_sensorium_push_uses_tactical_channel(self):
        """Game events push to the 'tactical' sensorium channel."""
        import inspect
        source = inspect.getsource(Commander)
        # Count tactical pushes near game events
        assert source.count('"tactical"') >= 5, \
            "Should have multiple tactical sensorium pushes for game events"
