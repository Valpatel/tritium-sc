"""Unit tests for the search router — people/vehicle lookup, merge/label,
recurring individual detection, and suspicion scoring.

SAFETY-CRITICAL: Tests the stalker detection and recurring person flagging
logic without requiring a running VectorStore or filesystem.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.routers.search import (
    MergeRequest,
    LabelRequest,
    FeedbackRequest,
    SuspiciousFlagRequest,
    calculate_suspicion_score,
    load_json,
    save_json,
    router,
)


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _mock_vector_store(items=None):
    """Create a mock VectorStore that returns given items."""
    store = MagicMock()
    store.get_all.return_value = items or []
    store.search_by_thumbnail.return_value = []
    store.stats.return_value = {"total": len(items or []), "by_type": {}}
    store.search.return_value = []
    return store


# ---------------------------------------------------------------------------
# Pydantic Model Validation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPydanticModels:
    """Validate request models for search endpoints."""

    def test_merge_request_required_fields(self):
        m = MergeRequest(primary_id="P1", duplicate_ids=["P2", "P3"])
        assert m.primary_id == "P1"
        assert len(m.duplicate_ids) == 2

    def test_merge_request_missing_primary(self):
        with pytest.raises(ValidationError):
            MergeRequest(duplicate_ids=["P2"])

    def test_label_request(self):
        lr = LabelRequest(thumbnail_id="T1", label="mailman")
        assert lr.label == "mailman"
        assert lr.notes is None

    def test_label_request_with_notes(self):
        lr = LabelRequest(thumbnail_id="T1", label="neighbor", notes="Lives next door")
        assert lr.notes == "Lives next door"

    def test_label_request_missing_label(self):
        with pytest.raises(ValidationError):
            LabelRequest(thumbnail_id="T1")

    def test_feedback_request(self):
        fr = FeedbackRequest(thumbnail_id="T1", feedback_type="correct")
        assert fr.correct_type is None
        assert fr.notes is None

    def test_feedback_request_wrong_type(self):
        fr = FeedbackRequest(
            thumbnail_id="T1", feedback_type="wrong_type",
            correct_type="car", notes="It's actually a car",
        )
        assert fr.correct_type == "car"

    def test_suspicious_flag_request(self):
        sr = SuspiciousFlagRequest(thumbnail_id="T1")
        assert sr.alert_on_return is True
        assert sr.reason is None

    def test_suspicious_flag_with_reason(self):
        sr = SuspiciousFlagRequest(
            thumbnail_id="T1", reason="Seen 5 times this week",
            alert_on_return=False,
        )
        assert sr.reason == "Seen 5 times this week"
        assert sr.alert_on_return is False


# ---------------------------------------------------------------------------
# JSON Utility Functions
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestJsonUtils:
    """load_json / save_json with temp files."""

    def test_load_nonexistent_returns_default(self):
        result = load_json(Path("/tmp/nonexistent_test_file_xyz.json"))
        assert result == {}

    def test_load_nonexistent_custom_default(self):
        result = load_json(Path("/tmp/nonexistent_test_file_xyz.json"), {"key": "val"})
        assert result == {"key": "val"}

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.json"
            data = {"key": "value", "count": 42}
            save_json(path, data)
            loaded = load_json(path)
            assert loaded == data

    def test_save_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nested" / "deep" / "test.json"
            save_json(path, {"ok": True})
            assert path.exists()
            loaded = load_json(path)
            assert loaded["ok"] is True

    def test_save_datetime_serialization(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dates.json"
            data = {"ts": datetime(2026, 1, 15, 12, 0)}
            save_json(path, data)
            loaded = load_json(path)
            assert "2026" in loaded["ts"]


# ---------------------------------------------------------------------------
# Suspicion Score Calculation (SAFETY-CRITICAL)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSuspicionScore:
    """calculate_suspicion_score — the core stalker detection heuristic."""

    def _make_sightings(self, count, time_variance_mins=10, span_days=7, channels=None):
        """Create sightings with controllable patterns.

        time_variance_mins: spread of appearance times around 14:00.
        0 = exactly the same time, 180 = spread over 3 hours.
        """
        base = datetime(2026, 2, 1, 14, 0)
        sightings = []
        for i in range(count):
            # Spread over days
            day_offset = int(i * span_days / max(1, count - 1)) if count > 1 else 0
            # Spread time: each sighting offset by i * variance / count minutes
            if time_variance_mins > 0 and count > 1:
                minute_offset = int(i * time_variance_mins / (count - 1))
            else:
                minute_offset = 0
            ts = base + timedelta(days=day_offset, minutes=minute_offset)
            sightings.append({
                "timestamp": ts,
                "channel": (channels or [1])[i % len(channels or [1])],
                "thumbnail_id": f"thumb-{i}",
                "confidence": 0.95,
            })
        return sightings

    def test_few_appearances_low_score(self):
        sightings = self._make_sightings(3, time_variance_mins=300, span_days=1)
        score, pattern = calculate_suspicion_score(sightings)
        assert score >= 10  # At least the frequency base
        # With 300-min variance, short span, no multi-channel → moderate at most
        assert score < 70

    def test_many_appearances_higher_score(self):
        sightings = self._make_sightings(10, time_variance_mins=60, span_days=10)
        score, pattern = calculate_suspicion_score(sightings)
        assert score >= 30  # High frequency bonus

    def test_regular_time_pattern_highest_score(self):
        """Same time every day is the most suspicious pattern."""
        sightings = self._make_sightings(5, time_variance_mins=0, span_days=10)
        score, pattern = calculate_suspicion_score(sightings)
        assert score >= 70  # High: regular time + frequency + duration
        assert "REGULAR TIME PATTERN" in str(pattern["factors"])
        assert "typical_time" in pattern

    def test_irregular_time_lower_score(self):
        sightings = self._make_sightings(5, time_variance_mins=300, span_days=10)
        score_irregular, _ = calculate_suspicion_score(sightings)

        sightings_regular = self._make_sightings(5, time_variance_mins=0, span_days=10)
        score_regular, _ = calculate_suspicion_score(sightings_regular)

        assert score_regular > score_irregular

    def test_multi_channel_bonus(self):
        sightings = self._make_sightings(5, time_variance_mins=60, span_days=7, channels=[1, 2, 3])
        score, pattern = calculate_suspicion_score(sightings)
        assert "different cameras" in str(pattern["factors"])

    def test_long_duration_bonus(self):
        sightings = self._make_sightings(5, time_variance_mins=60, span_days=14)
        score_long, _ = calculate_suspicion_score(sightings)

        sightings_short = self._make_sightings(5, time_variance_mins=60, span_days=1)
        score_short, _ = calculate_suspicion_score(sightings_short)

        assert score_long > score_short

    def test_score_capped_at_100(self):
        # Maximum possible: 10+ appearances, regular time, long duration, multi-channel
        sightings = self._make_sightings(15, time_variance_mins=0, span_days=14, channels=[1, 2, 3, 4])
        score, _ = calculate_suspicion_score(sightings)
        assert score <= 100

    def test_pattern_has_factors(self):
        sightings = self._make_sightings(4, time_variance_mins=30, span_days=5)
        _, pattern = calculate_suspicion_score(sightings)
        assert "factors" in pattern
        assert isinstance(pattern["factors"], list)
        assert len(pattern["factors"]) > 0

    def test_score_breakdown_present(self):
        sightings = self._make_sightings(5, time_variance_mins=10, span_days=7)
        _, pattern = calculate_suspicion_score(sightings)
        assert "score_breakdown" in pattern
        assert "frequency" in pattern["score_breakdown"]


# ---------------------------------------------------------------------------
# API Endpoints — Label & Feedback
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLabelEndpoints:
    """POST /api/search/label, DELETE /api/search/label/{id}."""

    def test_label_object(self):
        with tempfile.TemporaryDirectory() as td:
            labels_path = Path(td) / "labels.json"
            feedback_path = Path(td) / "feedback.json"
            with patch("app.routers.search.LABELS_PATH", labels_path), \
                 patch("app.routers.search.FEEDBACK_PATH", feedback_path):
                client = TestClient(_make_app())
                resp = client.post("/api/search/label", json={
                    "thumbnail_id": "thumb-42",
                    "label": "mailman",
                    "notes": "Comes every morning",
                })
                assert resp.status_code == 200
                assert resp.json()["status"] == "success"

                # Verify persisted
                labels = load_json(labels_path)
                assert "thumb-42" in labels
                assert labels["thumb-42"]["label"] == "mailman"

    def test_remove_label(self):
        with tempfile.TemporaryDirectory() as td:
            labels_path = Path(td) / "labels.json"
            save_json(labels_path, {"thumb-42": {"label": "mailman"}})
            with patch("app.routers.search.LABELS_PATH", labels_path):
                client = TestClient(_make_app())
                resp = client.delete("/api/search/label/thumb-42")
                assert resp.status_code == 200

    def test_remove_nonexistent_label_404(self):
        with tempfile.TemporaryDirectory() as td:
            labels_path = Path(td) / "labels.json"
            save_json(labels_path, {})
            with patch("app.routers.search.LABELS_PATH", labels_path):
                client = TestClient(_make_app())
                resp = client.delete("/api/search/label/nonexistent")
                assert resp.status_code == 404


@pytest.mark.unit
class TestFeedbackEndpoints:
    """POST /api/search/feedback, GET /api/search/feedback/stats."""

    def test_submit_feedback(self):
        with tempfile.TemporaryDirectory() as td:
            feedback_path = Path(td) / "feedback.json"
            with patch("app.routers.search.FEEDBACK_PATH", feedback_path):
                client = TestClient(_make_app())
                resp = client.post("/api/search/feedback", json={
                    "thumbnail_id": "thumb-1",
                    "feedback_type": "correct",
                })
                assert resp.status_code == 200
                assert resp.json()["status"] == "success"

    def test_feedback_stats(self):
        with tempfile.TemporaryDirectory() as td:
            feedback_path = Path(td) / "feedback.json"
            labels_path = Path(td) / "labels.json"
            merges_path = Path(td) / "merges.json"
            save_json(feedback_path, {"items": [
                {"type": "label", "thumbnail_id": "t1"},
                {"type": "label", "thumbnail_id": "t2"},
                {"type": "merge", "primary_id": "t1"},
            ]})
            save_json(labels_path, {"t1": {"label": "Bob"}, "t2": {"label": "Car"}})
            save_json(merges_path, {"merged_into": {"t3": "t1"}, "groups": {"t1": ["t3"]}})
            with patch("app.routers.search.FEEDBACK_PATH", feedback_path), \
                 patch("app.routers.search.LABELS_PATH", labels_path), \
                 patch("app.routers.search.MERGES_PATH", merges_path):
                client = TestClient(_make_app())
                resp = client.get("/api/search/feedback/stats")
                assert resp.status_code == 200
                data = resp.json()
                assert data["total_feedback"] == 3
                assert data["total_labels"] == 2
                assert data["total_merge_groups"] == 1
                assert data["total_merged_items"] == 1


# ---------------------------------------------------------------------------
# Merge / Unmerge
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMergeEndpoints:
    """POST /api/search/merge, POST /api/search/unmerge/{id}."""

    def test_merge_detections(self):
        with tempfile.TemporaryDirectory() as td:
            merges_path = Path(td) / "merges.json"
            feedback_path = Path(td) / "feedback.json"
            with patch("app.routers.search.MERGES_PATH", merges_path), \
                 patch("app.routers.search.FEEDBACK_PATH", feedback_path):
                client = TestClient(_make_app())
                resp = client.post("/api/search/merge", json={
                    "primary_id": "P1",
                    "duplicate_ids": ["P2", "P3"],
                })
                assert resp.status_code == 200
                data = resp.json()
                assert data["merged_count"] == 2

                # Verify persisted
                merges = load_json(merges_path)
                assert merges["merged_into"]["P2"] == "P1"
                assert merges["merged_into"]["P3"] == "P1"
                assert "P2" in merges["groups"]["P1"]
                assert "P3" in merges["groups"]["P1"]

    def test_unmerge_detection(self):
        with tempfile.TemporaryDirectory() as td:
            merges_path = Path(td) / "merges.json"
            save_json(merges_path, {
                "merged_into": {"P2": "P1"},
                "groups": {"P1": ["P2"]},
            })
            with patch("app.routers.search.MERGES_PATH", merges_path):
                client = TestClient(_make_app())
                resp = client.post("/api/search/unmerge/P2")
                assert resp.status_code == 200
                assert resp.json()["unmerged"] == "P2"

                # Verify removed
                merges = load_json(merges_path)
                assert "P2" not in merges["merged_into"]

    def test_unmerge_nonexistent_404(self):
        with tempfile.TemporaryDirectory() as td:
            merges_path = Path(td) / "merges.json"
            save_json(merges_path, {"merged_into": {}, "groups": {}})
            with patch("app.routers.search.MERGES_PATH", merges_path):
                client = TestClient(_make_app())
                resp = client.post("/api/search/unmerge/nonexistent")
                assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Suspicious Flag (SAFETY-CRITICAL)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSuspiciousFlag:
    """POST /api/search/flag-suspicious, DELETE, GET /api/search/flagged."""

    def test_flag_suspicious(self):
        with tempfile.TemporaryDirectory() as td:
            suspicious_path = Path(td) / "suspicious.json"
            feedback_path = Path(td) / "feedback.json"
            with patch("app.routers.search.SUSPICIOUS_PATH", suspicious_path), \
                 patch("app.routers.search.FEEDBACK_PATH", feedback_path):
                client = TestClient(_make_app())
                resp = client.post("/api/search/flag-suspicious", json={
                    "thumbnail_id": "thumb-99",
                    "reason": "Same person seen 5 days in a row",
                    "alert_on_return": True,
                })
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "flagged"
                assert data["alert_on_return"] is True

    def test_unflag_suspicious(self):
        with tempfile.TemporaryDirectory() as td:
            suspicious_path = Path(td) / "suspicious.json"
            save_json(suspicious_path, {"flagged": {
                "thumb-99": {"reason": "test", "alert_on_return": True},
            }})
            with patch("app.routers.search.SUSPICIOUS_PATH", suspicious_path):
                client = TestClient(_make_app())
                resp = client.delete("/api/search/flag-suspicious/thumb-99")
                assert resp.status_code == 200
                assert resp.json()["status"] == "unflagged"

    def test_unflag_nonexistent_404(self):
        with tempfile.TemporaryDirectory() as td:
            suspicious_path = Path(td) / "suspicious.json"
            save_json(suspicious_path, {"flagged": {}})
            with patch("app.routers.search.SUSPICIOUS_PATH", suspicious_path):
                client = TestClient(_make_app())
                resp = client.delete("/api/search/flag-suspicious/nonexistent")
                assert resp.status_code == 404

    def test_get_flagged_individuals(self):
        with tempfile.TemporaryDirectory() as td:
            suspicious_path = Path(td) / "suspicious.json"
            labels_path = Path(td) / "labels.json"
            save_json(suspicious_path, {"flagged": {
                "thumb-1": {"reason": "stalker", "alert_on_return": True, "flagged_at": "2026-02-01T10:00:00"},
                "thumb-2": {"reason": "loiterer", "alert_on_return": False, "flagged_at": "2026-02-02T10:00:00"},
            }})
            save_json(labels_path, {"thumb-1": {"label": "Unknown Male"}})
            with patch("app.routers.search.SUSPICIOUS_PATH", suspicious_path), \
                 patch("app.routers.search.LABELS_PATH", labels_path):
                client = TestClient(_make_app())
                resp = client.get("/api/search/flagged")
                assert resp.status_code == 200
                data = resp.json()
                assert data["total_flagged"] == 2
                # Most recent first
                assert data["individuals"][0]["thumbnail_id"] == "thumb-2"
                assert data["individuals"][1]["label"] == "Unknown Male"


# ---------------------------------------------------------------------------
# People / Vehicles Listing
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestListEndpoints:
    """GET /api/search/people, GET /api/search/vehicles."""

    def test_list_people_empty(self):
        store = _mock_vector_store([])
        with patch("app.routers.search.get_vector_store", return_value=store), \
             patch("app.routers.search.load_json", return_value={}):
            client = TestClient(_make_app())
            resp = client.get("/api/search/people")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["items"] == []

    def test_list_people_with_items(self):
        items = [
            {"thumbnail_id": "t1", "target_type": "person", "timestamp": "2026-02-01T10:00:00"},
            {"thumbnail_id": "t2", "target_type": "person", "timestamp": "2026-02-01T11:00:00"},
        ]
        store = _mock_vector_store(items)
        with tempfile.TemporaryDirectory() as td:
            labels_path = Path(td) / "labels.json"
            merges_path = Path(td) / "merges.json"
            save_json(labels_path, {})
            save_json(merges_path, {"merged_into": {}, "groups": {}})
            with patch("app.routers.search.get_vector_store", return_value=store), \
                 patch("app.routers.search.LABELS_PATH", labels_path), \
                 patch("app.routers.search.MERGES_PATH", merges_path):
                client = TestClient(_make_app())
                resp = client.get("/api/search/people")
                assert resp.status_code == 200
                data = resp.json()
                assert data["total"] == 2
                assert data["items"][0]["thumbnail_url"].startswith("/api/search/thumbnail/")

    def test_list_vehicles_empty(self):
        store = _mock_vector_store([])
        with patch("app.routers.search.get_vector_store", return_value=store), \
             patch("app.routers.search.load_json", return_value={}):
            client = TestClient(_make_app())
            resp = client.get("/api/search/vehicles")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0


# ---------------------------------------------------------------------------
# Thumbnail Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestThumbnailEndpoint:
    """GET /api/search/thumbnail/{thumbnail_id}."""

    def test_thumbnail_not_found(self):
        with patch("app.routers.search.THUMBNAILS_DIR", Path("/tmp/nonexistent_thumb_dir")):
            client = TestClient(_make_app())
            resp = client.get("/api/search/thumbnail/nonexistent")
            assert resp.status_code == 404

    def test_thumbnail_found(self):
        with tempfile.TemporaryDirectory() as td:
            thumb_dir = Path(td)
            person_dir = thumb_dir / "person"
            person_dir.mkdir()
            thumb_file = person_dir / "test-thumb.jpg"
            thumb_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # Fake JPEG
            with patch("app.routers.search.THUMBNAILS_DIR", thumb_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/search/thumbnail/test-thumb")
                assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Similar Search
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSimilarSearch:
    """GET /api/search/similar/{thumbnail_id}."""

    def test_similar_returns_results(self):
        store = _mock_vector_store()
        store.search_by_thumbnail.return_value = [
            ({"thumbnail_id": "t2", "target_type": "person"}, 0.87),
            ({"thumbnail_id": "t3", "target_type": "person"}, 0.65),
        ]
        with patch("app.routers.search.get_vector_store", return_value=store):
            client = TestClient(_make_app())
            resp = client.get("/api/search/similar/t1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["query_id"] == "t1"
            assert len(data["similar"]) == 2
            assert data["similar"][0]["similarity"] == 0.87
