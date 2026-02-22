"""Unit tests for Amy's daily transcript."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from amy.comms.transcript import Transcript

pytestmark = pytest.mark.unit


class TestTranscript:
    def test_append_creates_file(self, tmp_path):
        t = Transcript(base_dir=str(tmp_path))
        t.append("amy", "Hello world", "speech")
        t.close()

        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        content = files[0].read_text().strip()
        entry = json.loads(content)
        assert entry["speaker"] == "amy"
        assert entry["text"] == "Hello world"
        assert entry["type"] == "speech"
        assert "ts" in entry

    def test_append_multiple(self, tmp_path):
        t = Transcript(base_dir=str(tmp_path))
        t.append("user", "Hey Amy", "speech")
        t.append("amy", "Hi there!", "speech")
        t.append("amy", "Thinking...", "thought")
        t.close()

        files = list(tmp_path.glob("*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 3

    def test_get_recent(self, tmp_path):
        t = Transcript(base_dir=str(tmp_path))
        for i in range(20):
            t.append("user", f"Message {i}", "speech")
        recent = t.get_recent(count=5)
        assert len(recent) == 5
        assert recent[0]["text"] == "Message 15"
        assert recent[4]["text"] == "Message 19"
        t.close()

    def test_get_recent_with_type_filter(self, tmp_path):
        t = Transcript(base_dir=str(tmp_path))
        t.append("amy", "Hello", "speech")
        t.append("amy", "Thinking...", "thought")
        t.append("user", "Hey", "speech")
        recent = t.get_recent(count=10, entry_type="speech")
        assert len(recent) == 2
        assert all(e["type"] == "speech" for e in recent)
        t.close()

    def test_search(self, tmp_path):
        t = Transcript(base_dir=str(tmp_path))
        t.append("user", "I like pizza", "speech")
        t.append("amy", "Pizza is great!", "speech")
        t.append("user", "What about tacos?", "speech")
        results = t.search("pizza")
        assert len(results) == 2
        assert "pizza" in results[0]["text"].lower()
        t.close()

    def test_search_no_results(self, tmp_path):
        t = Transcript(base_dir=str(tmp_path))
        t.append("user", "Hello", "speech")
        results = t.search("nonexistent")
        assert len(results) == 0
        t.close()

    def test_search_limit(self, tmp_path):
        t = Transcript(base_dir=str(tmp_path))
        for i in range(20):
            t.append("user", f"test message {i}", "speech")
        results = t.search("test", limit=3)
        assert len(results) == 3
        t.close()

    def test_close_idempotent(self, tmp_path):
        t = Transcript(base_dir=str(tmp_path))
        t.append("amy", "Hello", "speech")
        t.close()
        t.close()  # Should not raise

    def test_empty_transcript(self, tmp_path):
        t = Transcript(base_dir=str(tmp_path))
        recent = t.get_recent(count=5)
        assert recent == []
        results = t.search("anything")
        assert results == []
        t.close()
