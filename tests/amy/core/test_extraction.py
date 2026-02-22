"""Unit tests for fact extraction from conversations."""

from __future__ import annotations

import pytest

from amy.brain.extraction import extract_facts, extract_person_name


@pytest.mark.unit
class TestExtractPersonName:
    """Tests for extract_person_name regex patterns."""

    def test_im_pattern(self):
        """'I'm Alice' extracts 'Alice'."""
        assert extract_person_name("I'm Alice") == "Alice"

    def test_my_name_is_pattern(self):
        """'my name is Bob' extracts 'Bob'."""
        assert extract_person_name("my name is Bob") == "Bob"

    def test_call_me_pattern(self):
        """'call me Charlie' extracts 'Charlie'."""
        assert extract_person_name("call me Charlie") == "Charlie"

    def test_name_here_pattern(self):
        """'Alice here' at start of string extracts 'Alice'."""
        assert extract_person_name("Alice here") == "Alice"

    def test_this_is_pattern(self):
        """'this is David' extracts 'David'."""
        assert extract_person_name("this is David") == "David"

    def test_random_noise_returns_none(self):
        """Random text with no name pattern returns None."""
        assert extract_person_name("the weather is nice today") is None

    def test_stop_word_im_good(self):
        """'I'm Good' is filtered as a stop word, returns None."""
        assert extract_person_name("I'm Good") is None

    def test_stop_word_im_the(self):
        """'I'm The' is filtered as a stop word, returns None."""
        assert extract_person_name("I'm Here") is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        assert extract_person_name("") is None

    def test_none_input_returns_none(self):
        """None input returns None."""
        assert extract_person_name(None) is None


@pytest.mark.unit
class TestExtractFacts:
    """Tests for extract_facts regex patterns."""

    def test_preference_likes(self):
        """'I like pizza' extracts a preference fact with 'likes' tag."""
        facts = extract_facts("I like pizza")
        assert len(facts) >= 1
        pref = [f for f in facts if "preference" in f["tags"]]
        assert len(pref) == 1
        assert "likes" in pref[0]["tags"]
        assert "pizza" in pref[0]["text"]
        assert pref[0]["source"] == "conversation"

    def test_schedule_extraction(self):
        """'at 3pm I have a meeting' extracts a schedule fact."""
        facts = extract_facts("at 3pm I have a meeting")
        schedule = [f for f in facts if "schedule" in f["tags"]]
        assert len(schedule) == 1
        assert "3pm" in schedule[0]["text"]

    def test_identity_extraction(self):
        """'I'm a software engineer' extracts an identity fact."""
        facts = extract_facts("I'm a software engineer")
        identity = [f for f in facts if "identity" in f["tags"]]
        assert len(identity) == 1
        assert "software engineer" in identity[0]["text"]

    def test_empty_transcript_returns_empty(self):
        """Empty transcript returns no facts."""
        assert extract_facts("") == []

    def test_possession_extraction(self):
        """'I have a cat' extracts a possession fact."""
        facts = extract_facts("I have a cat named Whiskers")
        poss = [f for f in facts if "possession" in f["tags"]]
        assert len(poss) == 1
        assert "cat" in poss[0]["text"]

    def test_person_propagated_to_facts(self):
        """Person argument is propagated into each fact dict."""
        facts = extract_facts("I like chess", person="Alice")
        assert all(f["person"] == "Alice" for f in facts)

    def test_fact_has_time_field(self):
        """Each extracted fact has a numeric timestamp."""
        facts = extract_facts("I love hiking")
        assert len(facts) >= 1
        assert isinstance(facts[0]["time"], float)
