"""Unit tests for search router Pydantic models and pure functions.

Tests: MergeRequest, LabelRequest, FeedbackRequest, SuspiciousFlagRequest,
       load_json, save_json, calculate_suspicion_score.
No server, no VectorStore, no CLIP required.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.routers.search import (
    MergeRequest,
    LabelRequest,
    FeedbackRequest,
    SuspiciousFlagRequest,
    load_json,
    save_json,
    calculate_suspicion_score,
)


# ===========================================================================
# MergeRequest
# ===========================================================================

@pytest.mark.unit
class TestMergeRequest:
    """MergeRequest — merge multiple detections."""

    def test_valid(self):
        r = MergeRequest(primary_id="abc", duplicate_ids=["def", "ghi"])
        assert r.primary_id == "abc"
        assert len(r.duplicate_ids) == 2

    def test_empty_duplicates(self):
        r = MergeRequest(primary_id="abc", duplicate_ids=[])
        assert r.duplicate_ids == []

    def test_missing_primary_raises(self):
        with pytest.raises(ValidationError):
            MergeRequest(duplicate_ids=["x"])

    def test_missing_duplicates_raises(self):
        with pytest.raises(ValidationError):
            MergeRequest(primary_id="abc")


# ===========================================================================
# LabelRequest
# ===========================================================================

@pytest.mark.unit
class TestLabelRequest:
    """LabelRequest — label a detected object."""

    def test_minimal(self):
        r = LabelRequest(thumbnail_id="thumb-001", label="mailman")
        assert r.thumbnail_id == "thumb-001"
        assert r.label == "mailman"
        assert r.notes is None

    def test_with_notes(self):
        r = LabelRequest(thumbnail_id="t1", label="neighbor bob", notes="Lives next door")
        assert r.notes == "Lives next door"

    def test_missing_thumbnail_raises(self):
        with pytest.raises(ValidationError):
            LabelRequest(label="test")

    def test_missing_label_raises(self):
        with pytest.raises(ValidationError):
            LabelRequest(thumbnail_id="t1")


# ===========================================================================
# FeedbackRequest
# ===========================================================================

@pytest.mark.unit
class TestFeedbackRequest:
    """FeedbackRequest — user feedback for a detection."""

    def test_minimal(self):
        r = FeedbackRequest(thumbnail_id="t1", feedback_type="correct")
        assert r.feedback_type == "correct"
        assert r.correct_type is None
        assert r.notes is None

    def test_wrong_type(self):
        r = FeedbackRequest(
            thumbnail_id="t1", feedback_type="wrong_type",
            correct_type="truck", notes="It's a truck not a car",
        )
        assert r.correct_type == "truck"
        assert r.notes == "It's a truck not a car"

    def test_missing_fields_raises(self):
        with pytest.raises(ValidationError):
            FeedbackRequest()


# ===========================================================================
# SuspiciousFlagRequest
# ===========================================================================

@pytest.mark.unit
class TestSuspiciousFlagRequest:
    """SuspiciousFlagRequest — flag individual as suspicious."""

    def test_minimal(self):
        r = SuspiciousFlagRequest(thumbnail_id="t1")
        assert r.thumbnail_id == "t1"
        assert r.reason is None
        assert r.alert_on_return is True

    def test_with_reason(self):
        r = SuspiciousFlagRequest(
            thumbnail_id="t1", reason="Loitering near fence",
            alert_on_return=False,
        )
        assert r.reason == "Loitering near fence"
        assert r.alert_on_return is False

    def test_missing_thumbnail_raises(self):
        with pytest.raises(ValidationError):
            SuspiciousFlagRequest()


# ===========================================================================
# JSON Helpers
# ===========================================================================

@pytest.mark.unit
class TestLoadJson:
    """load_json — file reading with defaults."""

    def test_missing_file_returns_default(self, tmp_path):
        result = load_json(tmp_path / "missing.json")
        assert result == {}

    def test_missing_file_custom_default(self, tmp_path):
        result = load_json(tmp_path / "missing.json", {"items": []})
        assert result == {"items": []}

    def test_valid_file(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_text(json.dumps({"key": "value"}))
        result = load_json(path)
        assert result == {"key": "value"}

    def test_list_file(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text(json.dumps([1, 2, 3]))
        result = load_json(path)
        assert result == [1, 2, 3]


@pytest.mark.unit
class TestSaveJson:
    """save_json — file writing with directory creation."""

    def test_creates_file(self, tmp_path):
        path = tmp_path / "output.json"
        save_json(path, {"test": True})
        assert path.exists()
        data = json.loads(path.read_text())
        assert data == {"test": True}

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "output.json"
        save_json(path, {"nested": True})
        assert path.exists()

    def test_overwrites_existing(self, tmp_path):
        path = tmp_path / "data.json"
        save_json(path, {"v": 1})
        save_json(path, {"v": 2})
        data = json.loads(path.read_text())
        assert data == {"v": 2}

    def test_handles_datetime(self, tmp_path):
        """datetime objects should be serialized via default=str."""
        path = tmp_path / "dt.json"
        save_json(path, {"ts": datetime(2026, 2, 20, 14, 0)})
        assert path.exists()
        data = json.loads(path.read_text())
        assert "2026" in data["ts"]

    def test_round_trip(self, tmp_path):
        path = tmp_path / "rt.json"
        original = {"merged_into": {"a": "b"}, "groups": {"b": ["a", "c"]}}
        save_json(path, original)
        loaded = load_json(path)
        assert loaded == original


# ===========================================================================
# calculate_suspicion_score
# ===========================================================================

def _make_sightings(count, base_time=None, time_spread_mins=15, day_spread=7, channels=None):
    """Helper to generate sighting dicts for suspicion scoring."""
    if base_time is None:
        base_time = datetime(2026, 2, 20, 14, 0)
    if channels is None:
        channels = [1]
    sightings = []
    for i in range(count):
        # Spread across days
        day_offset = timedelta(days=(i % day_spread))
        # Add time variance within the spread
        minute_offset = timedelta(minutes=(i % 3) * time_spread_mins)
        ts = base_time + day_offset + minute_offset
        sightings.append({
            "timestamp": ts,
            "channel": channels[i % len(channels)],
            "thumbnail_id": f"thumb-{i:03d}",
            "confidence": 0.9,
        })
    return sightings


@pytest.mark.unit
class TestCalculateSuspicionScore:
    """calculate_suspicion_score — pattern analysis."""

    def test_returns_score_and_pattern(self):
        sightings = _make_sightings(3)
        score, pattern = calculate_suspicion_score(sightings)
        assert isinstance(score, int)
        assert isinstance(pattern, dict)
        assert "factors" in pattern

    def test_score_bounded_0_100(self):
        sightings = _make_sightings(20, time_spread_mins=5, day_spread=14, channels=[1, 2, 3])
        score, _ = calculate_suspicion_score(sightings)
        assert 0 <= score <= 100

    def test_low_count_low_score(self):
        sightings = _make_sightings(3, time_spread_mins=180, day_spread=1)
        score, _ = calculate_suspicion_score(sightings)
        assert score < 60

    def test_high_count_higher_score(self):
        sightings_few = _make_sightings(3, time_spread_mins=60, day_spread=1)
        sightings_many = _make_sightings(12, time_spread_mins=60, day_spread=7)
        score_few, _ = calculate_suspicion_score(sightings_few)
        score_many, _ = calculate_suspicion_score(sightings_many)
        assert score_many > score_few

    def test_regular_time_highest_score(self):
        """Same time each day (variance < 30 min) gives max time points."""
        base = datetime(2026, 2, 10, 22, 0)
        sightings = []
        for i in range(5):
            sightings.append({
                "timestamp": base + timedelta(days=i, minutes=i * 3),
                "channel": 1,
                "thumbnail_id": f"t{i}",
                "confidence": 0.9,
            })
        score, pattern = calculate_suspicion_score(sightings)
        assert score >= 60
        assert any("REGULAR TIME" in f for f in pattern["factors"])

    def test_irregular_time_lower_score(self):
        """Random times of day should not trigger regular time pattern."""
        base = datetime(2026, 2, 10, 0, 0)
        hours = [2, 10, 16, 23, 7]
        sightings = []
        for i, h in enumerate(hours):
            sightings.append({
                "timestamp": base + timedelta(days=i, hours=h),
                "channel": 1,
                "thumbnail_id": f"t{i}",
                "confidence": 0.9,
            })
        score, pattern = calculate_suspicion_score(sightings)
        assert not any("REGULAR TIME" in f for f in pattern["factors"])

    def test_multi_channel_bonus(self):
        sightings_1ch = _make_sightings(5, channels=[1])
        sightings_3ch = _make_sightings(5, channels=[1, 2, 3])
        score_1, _ = calculate_suspicion_score(sightings_1ch)
        score_3, _ = calculate_suspicion_score(sightings_3ch)
        assert score_3 >= score_1

    def test_long_duration_bonus(self):
        """Appearances over 7+ days should score higher than 1 day."""
        base = datetime(2026, 2, 1, 14, 0)
        short = [{"timestamp": base + timedelta(hours=i), "channel": 1,
                  "thumbnail_id": f"t{i}", "confidence": 0.9} for i in range(5)]
        long = [{"timestamp": base + timedelta(days=i * 3), "channel": 1,
                 "thumbnail_id": f"t{i}", "confidence": 0.9} for i in range(5)]
        score_short, _ = calculate_suspicion_score(short)
        score_long, _ = calculate_suspicion_score(long)
        assert score_long > score_short

    def test_pattern_has_factors(self):
        sightings = _make_sightings(5)
        _, pattern = calculate_suspicion_score(sightings)
        assert len(pattern["factors"]) >= 1

    def test_typical_time_in_pattern(self):
        """Regular-time sightings should have typical_time in pattern."""
        base = datetime(2026, 2, 10, 8, 30)
        sightings = [
            {"timestamp": base + timedelta(days=i, minutes=i * 2),
             "channel": 1, "thumbnail_id": f"t{i}", "confidence": 0.9}
            for i in range(5)
        ]
        _, pattern = calculate_suspicion_score(sightings)
        assert "typical_time" in pattern
        assert pattern["typical_time"].startswith("08:")
