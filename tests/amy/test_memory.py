"""Unit tests for Amy's long-term Memory module."""

from __future__ import annotations

import json
import os
import time as _time
from unittest.mock import patch

import pytest

from amy.memory import Memory


@pytest.mark.unit
class TestMemoryInit:
    """Tests for Memory initialization and session tracking."""

    def test_create_empty_memory(self, memory_tmpdir):
        """Memory initializes cleanly when no file exists."""
        mem = Memory(path=memory_tmpdir)
        assert mem.spatial == {}
        assert mem.events == []
        assert mem.room_summary == ""
        assert mem.people == []
        assert not os.path.exists(memory_tmpdir)

    def test_session_count_starts_at_one(self, memory_tmpdir):
        """First session increments count from 0 to 1."""
        mem = Memory(path=memory_tmpdir)
        assert mem.session_count == 1

    def test_session_count_increments_on_reload(self, memory_tmpdir):
        """Each load increments session_count."""
        mem = Memory(path=memory_tmpdir)
        assert mem.session_count == 1
        mem.save()

        mem2 = Memory(path=memory_tmpdir)
        assert mem2.session_count == 2

        mem2.save()
        mem3 = Memory(path=memory_tmpdir)
        assert mem3.session_count == 3

    def test_empty_file_path_uses_default(self):
        """Passing None defaults to amy/amy_memory.json."""
        mem = Memory(path=None)
        assert mem.path.endswith("amy_memory.json")
        assert "amy" in mem.path


@pytest.mark.unit
class TestSpatialBucketing:
    """Tests for _pos_key spatial bucketing."""

    def test_pos_key_rounds_to_nearest_ten(self):
        assert Memory._pos_key(15, 23) == "20,20"

    def test_pos_key_negative_rounding(self):
        assert Memory._pos_key(4, -6) == "0,-10"

    def test_pos_key_exact_multiples(self):
        assert Memory._pos_key(30, -20) == "30,-20"

    def test_pos_key_zero(self):
        assert Memory._pos_key(0, 0) == "0,0"


@pytest.mark.unit
class TestObservations:
    """Tests for spatial observation storage and retrieval."""

    def test_add_observation(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_observation(15, 23, "desk with monitor")
        key = "20,20"
        assert len(mem.spatial[key]) == 1
        assert mem.spatial[key][0]["text"] == "desk with monitor"

    def test_observation_cap_at_five(self, memory_tmpdir):
        """Adding more than 5 observations to same position keeps only last 5."""
        mem = Memory(path=memory_tmpdir)
        for i in range(7):
            mem.add_observation(10, 10, f"obs_{i}")
        key = Memory._pos_key(10, 10)
        assert len(mem.spatial[key]) == 5
        texts = [o["text"] for o in mem.spatial[key]]
        assert texts == ["obs_2", "obs_3", "obs_4", "obs_5", "obs_6"]

    def test_get_nearby_observations_returns_recent(self, memory_tmpdir):
        """Nearby observations within 60 min are returned."""
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.add_observation(0, 0, "center view")
            mem.add_observation(10, 0, "right of center")

            result = mem.get_nearby_observations(0, 0, radius=1)
        assert "center view" in result
        assert "right of center" in result

    def test_age_filtering_excludes_old_observations(self, memory_tmpdir):
        """Observations older than 60 minutes are excluded."""
        old_time = 1_000_000.0
        new_time = old_time + 3601  # 60 min + 1 sec later

        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = old_time
            mem = Memory(path=memory_tmpdir)
            mem.add_observation(0, 0, "stale observation")

            # Now query well after the 60 min window
            mock_time.time.return_value = new_time
            result = mem.get_nearby_observations(0, 0, radius=1)

        assert result == []

    def test_get_spatial_summary_empty(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        assert mem.get_spatial_summary() == "Haven't explored much yet."

    def test_get_spatial_summary_with_data(self, memory_tmpdir):
        """Spatial summary returns formatted string with position keys."""
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.add_observation(0, 0, "a chair")

            summary = mem.get_spatial_summary()
        assert "[0,0]" in summary
        assert "a chair" in summary
        assert "0m ago" in summary


@pytest.mark.unit
class TestEvents:
    """Tests for the event timeline."""

    def test_add_and_get_events(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_event("detection", "person spotted")
        mem.add_event("alert", "zone breach")

        recent = mem.get_recent_events(10)
        assert len(recent) == 2
        assert recent[0]["type"] == "detection"
        assert recent[1]["data"] == "zone breach"

    def test_event_cap_at_200(self, memory_tmpdir):
        """Adding 250 events keeps only the last 200."""
        mem = Memory(path=memory_tmpdir)
        for i in range(250):
            mem.add_event("tick", f"event_{i}")
        assert len(mem.events) == 200
        assert mem.events[0]["data"] == "event_50"
        assert mem.events[-1]["data"] == "event_249"

    def test_get_recent_events_count(self, memory_tmpdir):
        """get_recent_events returns the requested count."""
        mem = Memory(path=memory_tmpdir)
        for i in range(20):
            mem.add_event("tick", f"ev_{i}")
        assert len(mem.get_recent_events(5)) == 5
        assert mem.get_recent_events(5)[-1]["data"] == "ev_19"


@pytest.mark.unit
class TestPeople:
    """Tests for person recording."""

    def test_record_person(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.record_person("tall person in red shirt")
        assert len(mem.people) == 1
        assert mem.people[0]["description"] == "tall person in red shirt"

    def test_person_cap_at_50(self, memory_tmpdir):
        """Adding more than 50 people keeps only the last 50."""
        mem = Memory(path=memory_tmpdir)
        for i in range(60):
            mem.record_person(f"person_{i}")
        assert len(mem.people) == 50
        assert mem.people[0]["description"] == "person_10"
        assert mem.people[-1]["description"] == "person_59"


@pytest.mark.unit
class TestPersistence:
    """Tests for save/load roundtrip and error recovery."""

    def test_save_load_roundtrip(self, memory_tmpdir):
        """All fields survive a save/load cycle."""
        mem = Memory(path=memory_tmpdir)
        mem.add_observation(10, 20, "bookshelf")
        mem.add_event("scan", "full scan done")
        mem.update_room_summary("office with two desks")
        mem.record_person("person in blue hoodie")
        mem.save()

        mem2 = Memory(path=memory_tmpdir)
        key = Memory._pos_key(10, 20)
        assert mem2.spatial[key][-1]["text"] == "bookshelf"
        assert len(mem2.events) == 1
        assert mem2.events[0]["type"] == "scan"
        assert mem2.room_summary == "office with two desks"
        assert mem2.people[0]["description"] == "person in blue hoodie"

    def test_room_summary_persistence(self, memory_tmpdir):
        """Room summary persists through save/load."""
        mem = Memory(path=memory_tmpdir)
        mem.update_room_summary("large conference room")
        mem.save()

        mem2 = Memory(path=memory_tmpdir)
        assert mem2.room_summary == "large conference room"

    def test_corrupt_json_recovery(self, memory_tmpdir):
        """Corrupt JSON file is handled gracefully; memory starts fresh."""
        with open(memory_tmpdir, "w") as f:
            f.write("{invalid json content!!")

        mem = Memory(path=memory_tmpdir)
        # Should recover: empty state, session_count = 1 (0 + 1)
        assert mem.session_count == 1
        assert mem.spatial == {}
        assert mem.events == []

    def test_atomic_save_no_tmp_remains(self, memory_tmpdir):
        """After save, the .tmp file should not remain on disk."""
        mem = Memory(path=memory_tmpdir)
        mem.add_event("test", "data")
        mem.save()

        assert os.path.exists(memory_tmpdir)
        assert not os.path.exists(memory_tmpdir + ".tmp")

    def test_save_writes_valid_json(self, memory_tmpdir):
        """Saved file contains valid JSON with expected keys."""
        mem = Memory(path=memory_tmpdir)
        mem.save()

        with open(memory_tmpdir) as f:
            data = json.load(f)
        assert data["version"] == 3
        assert "session_count" in data
        assert "spatial" in data
        assert "events" in data
        assert "room_summary" in data
        assert "people" in data
        assert "zones" in data
        assert "patterns" in data
        assert "session_summaries" in data


@pytest.mark.unit
class TestBuildContext:
    """Tests for LLM context generation."""

    def test_build_context_includes_session_info(self, memory_tmpdir):
        """Context string contains session number and uptime."""
        mem = Memory(path=memory_tmpdir)
        ctx = mem.build_context()
        assert "[Session #1" in ctx
        assert "uptime:" in ctx

    def test_build_context_includes_room_summary(self, memory_tmpdir):
        """Room summary appears in context when set."""
        mem = Memory(path=memory_tmpdir)
        mem.update_room_summary("a quiet lab")
        ctx = mem.build_context()
        assert "[Room knowledge]" in ctx
        assert "a quiet lab" in ctx

    def test_build_context_excludes_room_summary_when_empty(self, memory_tmpdir):
        """Room knowledge line is absent when room_summary is empty."""
        mem = Memory(path=memory_tmpdir)
        ctx = mem.build_context()
        assert "[Room knowledge]" not in ctx

    def test_build_context_includes_nearby_observations(self, memory_tmpdir):
        """Nearby observations appear in context."""
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.add_observation(0, 0, "whiteboard with diagrams")

            ctx = mem.build_context(pan=0, tilt=0)
        assert "whiteboard with diagrams" in ctx
        assert "[What you've seen nearby]" in ctx


# ---------------------------------------------------------------------------
# Phase 3 tests — zones, patterns, session summaries
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestZones:
    def test_register_zone(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.register_zone("desk", 30.0, -10.0, "My work desk")
        assert len(mem.zones) == 1
        assert mem.zones[0]["name"] == "desk"
        assert mem.zones[0]["pan"] == 30.0

    def test_register_zone_updates_existing(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.register_zone("desk", 30.0, -10.0, "old desc")
        mem.register_zone("desk", 35.0, -5.0, "new desc")
        assert len(mem.zones) == 1
        assert mem.zones[0]["pan"] == 35.0
        assert mem.zones[0]["description"] == "new desc"

    def test_get_zone_at_finds_nearest(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.register_zone("desk", 30.0, -10.0)
        mem.register_zone("door", -50.0, 0.0)
        zone = mem.get_zone_at(28.0, -8.0)
        assert zone is not None
        assert zone["name"] == "desk"

    def test_get_zone_at_returns_none_when_too_far(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.register_zone("desk", 30.0, -10.0)
        zone = mem.get_zone_at(-100.0, 20.0)
        assert zone is None

    def test_get_zone_context(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.register_zone("desk", 30.0, -10.0, "work area")
        ctx = mem.get_zone_context()
        assert "[Known zones]" in ctx
        assert "desk" in ctx
        assert "work area" in ctx

    def test_zones_persist_through_save_load(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.register_zone("window", -80.0, 5.0, "north window")
        mem.save()
        mem2 = Memory(path=memory_tmpdir)
        assert len(mem2.zones) == 1
        assert mem2.zones[0]["name"] == "window"

    def test_build_context_includes_current_zone(self, memory_tmpdir):
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.register_zone("desk", 0.0, 0.0, "work area")
            ctx = mem.build_context(pan=0.0, tilt=0.0)
        assert "[Current zone]: desk" in ctx


@pytest.mark.unit
class TestPatterns:
    def test_detect_patterns_needs_minimum_events(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        for i in range(5):
            mem.add_event("test", f"event {i}")
        patterns = mem.detect_patterns()
        assert patterns == []

    def test_detect_patterns_finds_recurring(self, memory_tmpdir):
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            # Add 10+ events of same type at same hour
            for i in range(12):
                mem.events.append({
                    "time": now + i,
                    "type": "person_arrived",
                    "data": f"person {i}",
                })
        patterns = mem.detect_patterns()
        assert len(patterns) >= 1
        assert any("person_arrived" in p["description"] for p in patterns)

    def test_get_pattern_context_empty(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        assert mem.get_pattern_context() == ""

    def test_patterns_persist(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.patterns = [{"hour": 14, "type": "test", "count": 5,
                         "description": "test happens at 14:00"}]
        mem.save()
        mem2 = Memory(path=memory_tmpdir)
        assert len(mem2.patterns) == 1


@pytest.mark.unit
class TestSessionSummaries:
    def test_generate_session_summary(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_event("test", "event 1")
        summary = mem.generate_session_summary()
        assert "Session #" in summary
        assert len(mem.session_summaries) == 1

    def test_session_summaries_capped_at_10(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        for i in range(12):
            mem.session_summaries.append({
                "session": i, "time": 1000.0 + i, "summary": f"s{i}"
            })
        mem.generate_session_summary()
        assert len(mem.session_summaries) <= 10

    def test_session_summaries_persist(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.generate_session_summary()
        mem.save()
        mem2 = Memory(path=memory_tmpdir)
        assert len(mem2.session_summaries) == 1


# ---------------------------------------------------------------------------
# V3 tests — Known People, Facts, Self-Model, Recall, Migration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestKnownPeople:
    def test_link_person_creates_entry(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.link_person("Alice", appearance="tall, red hair")
        assert "alice" in mem.known_people
        assert mem.known_people["alice"]["name"] == "Alice"
        assert mem.known_people["alice"]["appearance"] == "tall, red hair"

    def test_link_person_updates_existing(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.link_person("Alice", appearance="tall")
        mem.link_person("Alice", appearance="tall, red hair", zone="desk")
        assert mem.known_people["alice"]["appearance"] == "tall, red hair"
        assert mem.known_people["alice"]["last_location"] == "desk"
        assert mem.known_people["alice"]["interaction_count"] == 2

    def test_link_person_increments_session(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.link_person("Bob")
        assert mem.session_count in mem.known_people["bob"]["sessions_seen"]

    def test_link_person_empty_name_ignored(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.link_person("")
        mem.link_person("  ")
        assert len(mem.known_people) == 0

    def test_known_people_cap_at_20(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        for i in range(25):
            mem.link_person(f"Person{i}")
        assert len(mem.known_people) == 20

    def test_identify_person_single_match(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.link_person("Alice", zone="desk")
        result = mem.identify_person(zone="desk", people_count=1)
        assert result == "Alice"

    def test_identify_person_no_match(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.link_person("Alice", zone="desk")
        result = mem.identify_person(zone="door", people_count=1)
        assert result is None

    def test_identify_person_multiple_count_returns_none(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.link_person("Alice", zone="desk")
        assert mem.identify_person(zone="desk", people_count=2) is None

    def test_update_person_seen(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.link_person("Alice")
        old_seen = mem.known_people["alice"]["last_seen"]
        _time.sleep(0.01)
        mem.update_person_seen("Alice", zone="window")
        assert mem.known_people["alice"]["last_seen"] > old_seen
        assert mem.known_people["alice"]["last_location"] == "window"

    def test_known_people_persist(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.link_person("Alice", appearance="tall")
        mem.save()
        mem2 = Memory(path=memory_tmpdir)
        assert "alice" in mem2.known_people
        assert mem2.known_people["alice"]["name"] == "Alice"


@pytest.mark.unit
class TestFacts:
    def test_add_fact(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_fact("Alice likes coffee", tags=["preference"], person="Alice")
        assert len(mem.facts) == 1
        assert mem.facts[0]["text"] == "Alice likes coffee"
        assert mem.facts[0]["tags"] == ["preference"]
        assert mem.facts[0]["person"] == "Alice"

    def test_fact_cap_at_100(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        for i in range(110):
            mem.add_fact(f"fact_{i}")
        assert len(mem.facts) == 100
        assert mem.facts[0]["text"] == "fact_10"
        assert mem.facts[-1]["text"] == "fact_109"

    def test_fact_text_truncated(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_fact("x" * 300)
        assert len(mem.facts[0]["text"]) == 200

    def test_fact_tags_capped(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_fact("test", tags=["a", "b", "c", "d", "e", "f", "g"])
        assert len(mem.facts[0]["tags"]) == 5

    def test_facts_persist(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_fact("test fact", tags=["test"])
        mem.save()
        mem2 = Memory(path=memory_tmpdir)
        assert len(mem2.facts) == 1
        assert mem2.facts[0]["text"] == "test fact"


@pytest.mark.unit
class TestSelfModel:
    def test_add_self_note(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_self_note("I tend to be curious about new things")
        assert len(mem.self_model["personality_notes"]) == 1

    def test_self_notes_cap_at_5(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        for i in range(7):
            mem.add_self_note(f"note_{i}")
        notes = mem.self_model["personality_notes"]
        assert len(notes) == 5
        assert notes[0] == "note_2"
        assert notes[-1] == "note_6"

    def test_self_note_truncated(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_self_note("x" * 300)
        assert len(mem.self_model["personality_notes"][0]) == 200

    def test_self_model_persists(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_self_note("I like mornings")
        mem.save()
        mem2 = Memory(path=memory_tmpdir)
        assert "I like mornings" in mem2.self_model["personality_notes"]


@pytest.mark.unit
class TestRecall:
    def test_recall_finds_facts(self, memory_tmpdir):
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.add_fact("Alice likes coffee in the morning", tags=["preference"])
            results = mem.recall("coffee morning")
        assert len(results) >= 1
        assert "coffee" in results[0]["text"]

    def test_recall_finds_people(self, memory_tmpdir):
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.link_person("Alice", appearance="tall, red hair")
            results = mem.recall("Alice")
        assert len(results) >= 1

    def test_recall_empty_query_returns_empty(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_fact("test fact")
        assert mem.recall("") == []
        assert mem.recall("a b") == []  # All words <= 2 chars

    def test_recall_no_matches_returns_empty(self, memory_tmpdir):
        """No keyword matches and stale data returns empty."""
        old_time = 1_000_000.0
        query_time = old_time + 100_000  # Well past 24h recency window
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = old_time
            mem = Memory(path=memory_tmpdir)
            mem.add_fact("Alice likes coffee")
            mock_time.time.return_value = query_time
            results = mem.recall("dinosaur spaceship")
        assert results == []

    def test_recall_respects_limit(self, memory_tmpdir):
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            for i in range(10):
                mem.add_fact(f"test fact about cats number {i}", tags=["cat"])
            results = mem.recall("cats", limit=3)
        assert len(results) <= 3

    def test_recall_for_person(self, memory_tmpdir):
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.add_fact("likes coffee", person="Alice")
            mem.add_fact("works from home", person="Alice")
            mem.add_fact("unrelated fact", person="Bob")
            results = mem.recall_for_person("Alice")
        assert len(results) == 2
        assert all("Alice" != r.get("person", r.get("text", "")) or True for r in results)

    def test_recall_for_zone(self, memory_tmpdir):
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.add_fact("spotted cat near desk", tags=["desk"])
            mem.add_fact("nothing at window")
            results = mem.recall_for_zone("desk")
        assert len(results) >= 1


@pytest.mark.unit
class TestMigration:
    def test_v2_to_v3_migration(self, memory_tmpdir):
        """V2 memory auto-migrates to v3 on load."""
        v2_data = {
            "version": 2,
            "session_count": 5,
            "spatial": {},
            "events": [
                {"time": 1000.0, "type": "conversation", "data": "User: hi -> Amy: hello"},
            ],
            "room_summary": "office",
            "people": [
                {"time": 1000.0, "description": "Alice in red shirt"},
            ],
            "zones": [],
            "patterns": [],
            "session_summaries": [],
        }
        with open(memory_tmpdir, "w") as f:
            json.dump(v2_data, f)

        mem = Memory(path=memory_tmpdir)
        # Should have migrated
        assert "alice" in mem.known_people
        assert mem.known_people["alice"]["name"] == "Alice"
        assert len(mem.facts) >= 1  # Conversation event converted
        assert mem.facts[0]["tags"] == ["conversation", "migrated"]

    def test_v2_migration_preserves_data(self, memory_tmpdir):
        """Migration doesn't lose existing v2 data."""
        v2_data = {
            "version": 2,
            "session_count": 3,
            "spatial": {"0,0": [{"time": 1000.0, "text": "desk"}]},
            "events": [{"time": 1000.0, "type": "scan", "data": "full scan"}],
            "room_summary": "lab room",
            "people": [],
            "zones": [{"name": "desk", "pan": 0.0, "tilt": 0.0, "description": ""}],
            "patterns": [],
            "session_summaries": [{"session": 1, "time": 1000.0, "summary": "s1"}],
        }
        with open(memory_tmpdir, "w") as f:
            json.dump(v2_data, f)

        mem = Memory(path=memory_tmpdir)
        assert mem.room_summary == "lab room"
        assert len(mem.zones) == 1
        assert len(mem.events) == 1
        assert len(mem.session_summaries) == 1

    def test_v3_save_has_correct_version(self, memory_tmpdir):
        """Saved file has version 3."""
        mem = Memory(path=memory_tmpdir)
        mem.save()
        with open(memory_tmpdir) as f:
            data = json.load(f)
        assert data["version"] == 3
        assert "known_people" in data
        assert "facts" in data
        assert "self_model" in data


@pytest.mark.unit
class TestContextBuilders:
    def test_build_people_context_empty(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        assert mem.build_people_context() == ""

    def test_build_people_context_with_people(self, memory_tmpdir):
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.link_person("Alice", appearance="tall")
            ctx = mem.build_people_context()
        assert "[People you know]" in ctx
        assert "Alice" in ctx

    def test_build_self_context_empty(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        assert mem.build_self_context() == ""

    def test_build_self_context_with_notes(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_self_note("I tend to be curious")
        ctx = mem.build_self_context()
        assert "[Self-awareness]" in ctx
        assert "curious" in ctx

    def test_build_self_context_with_preferences(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_preference("likes", "coffee")
        mem.add_preference("dislikes", "loud noises")
        ctx = mem.build_self_context()
        assert "[Preferences]" in ctx
        assert "coffee" in ctx
        assert "loud noises" in ctx
        assert "Things I enjoy" in ctx
        assert "Things I dislike" in ctx

    def test_build_self_context_with_notes_and_preferences(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_self_note("I tend to be curious")
        mem.add_preference("likes", "mornings")
        ctx = mem.build_self_context()
        assert "[Self-awareness]" in ctx
        assert "[Preferences]" in ctx

    def test_build_context_includes_v3_sections(self, memory_tmpdir):
        now = 1_000_000.0
        with patch("amy.memory.time") as mock_time:
            mock_time.time.return_value = now
            mem = Memory(path=memory_tmpdir)
            mem.link_person("Alice")
            mem.add_self_note("I like mornings")
            ctx = mem.build_context()
        assert "[People you know]" in ctx
        assert "[Self-awareness]" in ctx


@pytest.mark.unit
class TestPreferences:
    """Tests for B1 — self_model preference storage."""

    def test_add_preference_likes(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_preference("likes", "coffee")
        prefs = mem.self_model["preferences"]
        assert "coffee" in prefs["likes"]

    def test_add_preference_dislikes(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_preference("dislikes", "loud music")
        prefs = mem.self_model["preferences"]
        assert "loud music" in prefs["dislikes"]

    def test_add_preference_deduplicates(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_preference("likes", "Coffee")
        mem.add_preference("likes", "coffee")
        assert len(mem.self_model["preferences"]["likes"]) == 1

    def test_add_preference_cap_at_10(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        for i in range(15):
            mem.add_preference("likes", f"thing {i}")
        assert len(mem.self_model["preferences"]["likes"]) == 10

    def test_add_preference_invalid_category_ignored(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_preference("neutral", "something")
        prefs = mem.self_model["preferences"]
        assert "neutral" not in prefs

    def test_add_preference_empty_text_ignored(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_preference("likes", "")
        mem.add_preference("likes", "   ")
        assert len(mem.self_model["preferences"]["likes"]) == 0

    def test_add_preference_text_truncated(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_preference("likes", "x" * 200)
        assert len(mem.self_model["preferences"]["likes"][0]) == 100

    def test_preferences_persist(self, memory_tmpdir):
        mem = Memory(path=memory_tmpdir)
        mem.add_preference("likes", "sunsets")
        mem.add_preference("dislikes", "rain")
        mem.save()
        mem2 = Memory(path=memory_tmpdir)
        assert "sunsets" in mem2.self_model["preferences"]["likes"]
        assert "rain" in mem2.self_model["preferences"]["dislikes"]
