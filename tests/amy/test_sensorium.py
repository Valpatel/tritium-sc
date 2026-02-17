"""Unit tests for the Sensorium — Amy's L3 awareness layer."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from amy.sensorium import SceneEvent, Sensorium


# ---------------------------------------------------------------------------
# SceneEvent dataclass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSceneEvent:
    """Tests for the SceneEvent dataclass."""

    def test_age_property(self):
        """age returns seconds elapsed since the event timestamp."""
        with patch("amy.sensorium.time.monotonic", return_value=100.0):
            event = SceneEvent(timestamp=95.0, source="yolo", text="person")
            assert event.age == pytest.approx(5.0)

    def test_defaults(self):
        """SceneEvent has sensible defaults for importance and source_node."""
        event = SceneEvent(timestamp=0.0, source="audio", text="silence")
        assert event.importance == 0.5
        assert event.source_node == ""


# ---------------------------------------------------------------------------
# Sensorium initialisation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSensoriumInit:
    """Tests for Sensorium construction."""

    def test_defaults(self, sensorium: Sensorium):
        """A fresh Sensorium starts empty with correct defaults."""
        assert sensorium.event_count == 0
        assert sensorium.people_present is False
        assert sensorium.seconds_since_speech == float("inf")
        assert sensorium.mood == "neutral"

    def test_custom_max_events(self):
        """max_events caps the internal deque."""
        s = Sensorium(max_events=3)
        for i in range(5):
            s.push("yolo", f"event {i}")
        assert s.event_count == 3


# ---------------------------------------------------------------------------
# push() behaviour
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPush:
    """Tests for Sensorium.push()."""

    def test_basic_push(self, sensorium: Sensorium):
        """push() adds an event and increments event_count."""
        sensorium.push("yolo", "1 person detected")
        assert sensorium.event_count == 1

    def test_push_with_source_node(self, sensorium: Sensorium):
        """source_node is stored on the event."""
        sensorium.push("yolo", "person", source_node="cam-1")
        # Verify via narrative (it stores the event)
        assert sensorium.event_count == 1

    def test_dedup_same_source_same_text_within_5s(self, sensorium: Sensorium):
        """Consecutive identical events from the same source within 5s are deduplicated."""
        base = 1000.0
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("yolo", "1 person detected")

        # Second push 2s later — same source+text, should be skipped
        with patch("amy.sensorium.time.monotonic", return_value=base + 2.0):
            sensorium.push("yolo", "1 person detected")

        assert sensorium.event_count == 1

    def test_no_dedup_after_5s(self, sensorium: Sensorium):
        """Same source+text after 5s gap is NOT deduplicated."""
        base = 1000.0
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("yolo", "1 person detected")

        with patch("amy.sensorium.time.monotonic", return_value=base + 6.0):
            sensorium.push("yolo", "1 person detected")

        assert sensorium.event_count == 2

    def test_no_dedup_different_source(self, sensorium: Sensorium):
        """Events from different sources are never deduplicated."""
        base = 1000.0
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("yolo", "person")

        with patch("amy.sensorium.time.monotonic", return_value=base + 1.0):
            sensorium.push("deep", "person")

        assert sensorium.event_count == 2

    def test_silence_debounce(self, sensorium: Sensorium):
        """Audio silence events are debounced to at most once per 30s."""
        base = 1000.0
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("audio", "Silence detected")
        assert sensorium.event_count == 1

        # 10s later — still within 30s debounce window
        with patch("amy.sensorium.time.monotonic", return_value=base + 10.0):
            sensorium.push("audio", "Silence again")
        assert sensorium.event_count == 1  # dropped

        # 31s later — past debounce window
        with patch("amy.sensorium.time.monotonic", return_value=base + 31.0):
            sensorium.push("audio", "Silence resumed")
        assert sensorium.event_count == 2  # accepted


# ---------------------------------------------------------------------------
# People-tracking logic
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPeopleTracking:
    """Tests for YOLO-driven people presence tracking."""

    def test_person_entered(self, sensorium: Sensorium):
        """'person' in a yolo event sets people_present=True."""
        sensorium.push("yolo", "1 person detected")
        assert sensorium.people_present is True

    def test_person_left(self, sensorium: Sensorium):
        """'left' without 'entered' clears people_present."""
        sensorium.push("yolo", "1 person detected")
        assert sensorium.people_present is True

        base = 1000.0
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("yolo", "person left the frame")
        assert sensorium.people_present is False

    def test_everyone_left(self, sensorium: Sensorium):
        """'everyone left' clears people_present."""
        sensorium.push("yolo", "2 people detected")
        assert sensorium.people_present is True

        base = 1000.0
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("yolo", "everyone left")
        assert sensorium.people_present is False

    def test_empty_scene(self, sensorium: Sensorium):
        """'empty' in yolo text clears people_present."""
        sensorium.push("yolo", "1 person detected")
        base = 1000.0
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("yolo", "scene is empty")
        assert sensorium.people_present is False

    def test_person_left_bag_no_false_positive(self, sensorium: Sensorium):
        """'A person left their bag' should NOT clear people_present.

        Fixed: uses specific departure phrases instead of loose 'left' match.
        """
        sensorium.push("yolo", "1 person detected")
        assert sensorium.people_present is True

        base = 1000.0
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("yolo", "A person left their bag on the table")

        # Person is still present — they left their bag, not the scene
        assert sensorium.people_present is True

    def test_non_yolo_source_does_not_track_people(self, sensorium: Sensorium):
        """People tracking only applies to source=='yolo'."""
        sensorium.push("deep", "1 person in the room")
        assert sensorium.people_present is False


# ---------------------------------------------------------------------------
# Speech timing
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSpeechTiming:
    """Tests for speech/audio timing tracking."""

    def test_speech_timing_tracked(self, sensorium: Sensorium):
        """'said' in audio events updates last_speech_time."""
        base = 1000.0
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("audio", 'User said "hello"')

        with patch("amy.sensorium.time.monotonic", return_value=base + 10.0):
            assert sensorium.seconds_since_speech == pytest.approx(10.0)

    def test_no_speech_returns_inf(self, sensorium: Sensorium):
        """seconds_since_speech is inf when no speech has been detected."""
        sensorium.push("audio", "Silence detected")
        assert sensorium.seconds_since_speech == float("inf")


# ---------------------------------------------------------------------------
# narrative()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNarrative:
    """Tests for the temporal narrative builder."""

    def test_empty_narrative(self, sensorium: Sensorium):
        """Empty sensorium returns a default string."""
        assert sensorium.narrative() == "No recent observations."

    def test_narrative_time_formatting(self, sensorium: Sensorium):
        """Narrative formats event ages as Now / Xs ago / Xm ago."""
        base = 1000.0

        # Event at base (will be 90s old at read time -> "1m ago")
        with patch("amy.sensorium.time.monotonic", return_value=base):
            sensorium.push("yolo", "1 person detected")

        # Event 60s later (will be 30s old at read time -> "30s ago")
        with patch("amy.sensorium.time.monotonic", return_value=base + 60.0):
            sensorium.push("audio", "User spoke")

        # Event 88s later (will be 2s old at read time -> "Now")
        with patch("amy.sensorium.time.monotonic", return_value=base + 88.0):
            sensorium.push("deep", "Room is bright")

        # Read narrative at base + 90 (ages: 90s, 30s, 2s — all within 120s window)
        with patch("amy.sensorium.time.monotonic", return_value=base + 90.0):
            text = sensorium.narrative()

        lines = text.strip().split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("1m ago:")       # 90s -> 1m ago
        assert lines[1].startswith("30s ago:")      # 30s -> 30s ago
        assert lines[2].startswith("Now:")          # 2s -> Now

    def test_narrative_excludes_old_events(self):
        """Events older than window_seconds are excluded from narrative."""
        s = Sensorium(window_seconds=60.0)
        base = 1000.0

        with patch("amy.sensorium.time.monotonic", return_value=base):
            s.push("yolo", "old event")

        # 61s later — outside the 60s window
        with patch("amy.sensorium.time.monotonic", return_value=base + 61.0):
            assert s.narrative() == "No recent observations."


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSummary:
    """Tests for the one-line summary."""

    def test_empty_summary(self, sensorium: Sensorium):
        """Empty sensorium returns a quiet message."""
        assert sensorium.summary() == "Quiet. No observations yet."

    def test_summary_joins_sources(self, sensorium: Sensorium):
        """Summary joins the latest event per source with ' | '."""
        sensorium.push("yolo", "2 people detected")
        sensorium.push("audio", "Background music")
        text = sensorium.summary()
        assert "2 people detected" in text
        assert "Background music" in text
        assert " | " in text


# ---------------------------------------------------------------------------
# mood property
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMood:
    """Tests for the dimensional mood model."""

    def test_mood_neutral_at_init(self, sensorium: Sensorium):
        """Fresh sensorium has 'neutral' mood."""
        assert sensorium.mood == "neutral"

    def test_mood_engaged_on_speech(self, sensorium: Sensorium):
        """Mood is 'engaged' when recent events mention speech/said."""
        sensorium.push("audio", 'User said "hi"')
        assert sensorium.mood == "engaged"

    def test_mood_attentive_with_people(self, sensorium: Sensorium):
        """Mood is 'attentive' when people are present (no speech)."""
        sensorium.push("yolo", "1 person detected")
        assert sensorium.mood == "attentive"

    def test_mood_contemplative_with_thoughts(self, sensorium: Sensorium):
        """Mood is 'contemplative' with >2 thought events."""
        base = 1000.0
        for i in range(4):
            with patch("amy.sensorium.time.monotonic", return_value=base + i):
                sensorium.push("thought", f"thought {i}")

        with patch("amy.sensorium.time.monotonic", return_value=base + 10.0):
            assert sensorium.mood == "contemplative"

    def test_mood_calm_on_silence(self, sensorium: Sensorium):
        """Mood is 'calm' after silence events reduce arousal."""
        base = 1000.0
        # Multiple silence events to push arousal low
        for i in range(3):
            with patch("amy.sensorium.time.monotonic", return_value=base + i * 31):
                sensorium.push("audio", f"Silence detected {i}")
        assert sensorium.mood == "calm"

    def test_mood_curious_on_entered(self, sensorium: Sensorium):
        """Mood is 'curious' when someone entered/appeared."""
        sensorium.push("deep", "A figure appeared in the doorway")
        assert sensorium.mood == "curious"

    def test_mood_neutral_default(self, sensorium: Sensorium):
        """Mood falls back to 'neutral' if no keywords match."""
        # Motor events don't shift mood dimensions much
        assert sensorium.mood == "neutral"

    def test_mood_excited_on_strong_positive(self, sensorium: Sensorium):
        """Multiple speech events push toward 'excited'."""
        base = 1000.0
        for i in range(5):
            with patch("amy.sensorium.time.monotonic", return_value=base + i):
                sensorium.push("audio", f'Person said "hello {i}"')
        assert sensorium.mood == "excited"

    def test_mood_content_on_mild_positive(self, sensorium: Sensorium):
        """Mild positive valence with low arousal produces 'content'."""
        sensorium._mood_valence = 0.1
        sensorium._mood_arousal = 0.2
        assert sensorium.mood == "content"

    def test_mood_uneasy_on_negative_high_arousal(self, sensorium: Sensorium):
        """Negative valence with high arousal produces 'uneasy'."""
        sensorium._mood_valence = -0.2
        sensorium._mood_arousal = 0.5
        assert sensorium.mood == "uneasy"

    def test_mood_melancholy_on_negative_low_arousal(self, sensorium: Sensorium):
        """Negative valence with low arousal produces 'melancholy'."""
        sensorium._mood_valence = -0.1
        sensorium._mood_arousal = 0.2
        assert sensorium.mood == "melancholy"

    def test_mood_valence_clamped(self, sensorium: Sensorium):
        """Valence stays within [-1, 1] bounds."""
        sensorium._mood_valence = 0.95
        sensorium._mood_arousal = 0.3
        # Push more positive events
        for i in range(10):
            sensorium.push("audio", f'Said "wow {i}"')
        assert -1.0 <= sensorium._mood_valence <= 1.0

    def test_mood_arousal_clamped(self, sensorium: Sensorium):
        """Arousal stays within [0, 1] bounds."""
        sensorium._mood_arousal = 0.95
        for i in range(10):
            sensorium.push("deep", f"Person appeared {i}")
        assert 0.0 <= sensorium._mood_arousal <= 1.0

    def test_mood_decays_toward_baseline(self, sensorium: Sensorium):
        """Mood dimensions decay toward baseline (0, 0.3) via 0.95 factor."""
        sensorium._mood_valence = 0.5
        sensorium._mood_arousal = 0.8
        # Push a neutral event to trigger decay
        sensorium.push("motor", "PTZ movement")
        assert sensorium._mood_valence < 0.5
        assert sensorium._mood_arousal < 0.8


@pytest.mark.unit
class TestMoodDescription:
    """Tests for the mood_description property."""

    def test_mood_description_includes_mood_name(self, sensorium: Sensorium):
        """mood_description contains the current mood name."""
        mood = sensorium.mood
        desc = sensorium.mood_description
        assert mood in desc

    def test_mood_description_has_intensity(self, sensorium: Sensorium):
        """mood_description has an intensity prefix."""
        desc = sensorium.mood_description
        assert any(w in desc for w in ("slightly", "mildly", "strongly"))

    def test_mood_description_strongly_when_extreme(self, sensorium: Sensorium):
        """Extreme mood values produce 'strongly' prefix."""
        sensorium._mood_valence = 0.8
        sensorium._mood_arousal = 0.9
        desc = sensorium.mood_description
        assert "strongly" in desc


# ---------------------------------------------------------------------------
# recent_thoughts property
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRecentThoughts:
    """Tests for recent_thoughts property."""

    def test_returns_last_eight(self, sensorium: Sensorium):
        """recent_thoughts returns at most the last 8 thought events."""
        s = Sensorium(max_events=30)
        base = 1000.0
        for i in range(12):
            with patch("amy.sensorium.time.monotonic", return_value=base + i):
                s.push("thought", f"idea {i}")

        with patch("amy.sensorium.time.monotonic", return_value=base + 20.0):
            thoughts = s.recent_thoughts

        assert len(thoughts) == 8
        assert thoughts == [f"idea {i}" for i in range(4, 12)]

    def test_returns_fewer_when_under_eight(self, sensorium: Sensorium):
        """When fewer than 8 thoughts exist, return all of them."""
        base = 1000.0
        for i in range(3):
            with patch("amy.sensorium.time.monotonic", return_value=base + i):
                sensorium.push("thought", f"idea {i}")

        with patch("amy.sensorium.time.monotonic", return_value=base + 10.0):
            thoughts = sensorium.recent_thoughts

        assert len(thoughts) == 3
        assert thoughts == ["idea 0", "idea 1", "idea 2"]

    def test_excludes_non_thought_sources(self, sensorium: Sensorium):
        """Only source=='thought' events appear in recent_thoughts."""
        sensorium.push("yolo", "1 person")
        sensorium.push("thought", "interesting")
        sensorium.push("audio", "music playing")
        assert sensorium.recent_thoughts == ["interesting"]
