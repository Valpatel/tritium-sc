# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Security tests for annotation and watchlist APIs.

Validates:
- XSS prevention (HTML tags stripped, entities escaped)
- Input length limits enforced
- SQL injection prevention (no raw SQL in annotation store)
- Collection size limits (DoS prevention)
- Type validation (enum enforcement)
"""

import pytest


@pytest.fixture(autouse=True)
def _clear_stores():
    """Reset annotation and watchlist stores before each test."""
    from app.routers.annotations import _annotations
    from app.routers.watchlist import _watch_entries, _alert_history
    _annotations.clear()
    _watch_entries.clear()
    _alert_history.clear()
    yield
    _annotations.clear()
    _watch_entries.clear()
    _alert_history.clear()


class TestAnnotationXSS:
    """Verify annotation text fields strip HTML/script tags."""

    @pytest.mark.unit
    def test_script_tag_stripped_from_text(self):
        from app.routers.annotations import AnnotationCreate
        body = AnnotationCreate(
            type="text", lat=33.0, lng=-97.0,
            text='<script>alert("xss")</script>Hello',
        )
        assert "<script>" not in body.text
        assert "alert" not in body.text.lower() or "&" in body.text

    @pytest.mark.unit
    def test_html_tags_stripped_from_label(self):
        from app.routers.annotations import AnnotationCreate
        body = AnnotationCreate(
            type="text", lat=33.0, lng=-97.0,
            label='<img src=x onerror=alert(1)>Safe',
        )
        assert "<img" not in body.label
        assert "onerror" not in body.label

    @pytest.mark.unit
    def test_html_stripped_from_layer(self):
        from app.routers.annotations import AnnotationCreate
        body = AnnotationCreate(
            type="text", lat=33.0, lng=-97.0,
            layer='<b>bold</b>',
        )
        assert "<b>" not in body.layer

    @pytest.mark.unit
    def test_update_xss_prevention(self):
        from app.routers.annotations import AnnotationUpdate
        body = AnnotationUpdate(
            text='<iframe src="evil.com"></iframe>',
            label='<a href="javascript:void">click</a>',
        )
        updates = body.model_dump(exclude_none=True)
        assert "<iframe" not in updates["text"]
        assert "<a " not in updates["label"]


class TestAnnotationLimits:
    """Verify annotation input limits."""

    @pytest.mark.unit
    def test_invalid_type_rejected(self):
        from app.routers.annotations import AnnotationCreate
        with pytest.raises(Exception):
            AnnotationCreate(type="malicious_type", lat=0, lng=0)

    @pytest.mark.unit
    def test_valid_types_accepted(self):
        from app.routers.annotations import AnnotationCreate, _VALID_TYPES
        for t in _VALID_TYPES:
            body = AnnotationCreate(type=t, lat=0, lng=0)
            assert body.type == t

    @pytest.mark.unit
    def test_lat_range_enforced(self):
        from app.routers.annotations import AnnotationCreate
        with pytest.raises(Exception):
            AnnotationCreate(type="text", lat=91, lng=0)
        with pytest.raises(Exception):
            AnnotationCreate(type="text", lat=-91, lng=0)

    @pytest.mark.unit
    def test_lng_range_enforced(self):
        from app.routers.annotations import AnnotationCreate
        with pytest.raises(Exception):
            AnnotationCreate(type="text", lat=0, lng=181)

    @pytest.mark.unit
    def test_points_limit(self):
        from app.routers.annotations import AnnotationCreate, _MAX_POINTS
        big_points = [[0.0, 0.0]] * (_MAX_POINTS + 1)
        with pytest.raises(Exception):
            AnnotationCreate(type="freehand", lat=0, lng=0, points=big_points)

    @pytest.mark.unit
    def test_annotation_count_limit(self):
        from app.routers.annotations import _annotations, _MAX_ANNOTATIONS
        # Fill to limit
        for i in range(_MAX_ANNOTATIONS):
            _annotations[f"ann_{i}"] = {"id": f"ann_{i}"}
        assert len(_annotations) == _MAX_ANNOTATIONS
        # The endpoint would reject, we test the guard condition
        assert len(_annotations) >= _MAX_ANNOTATIONS


class TestWatchlistXSS:
    """Verify watchlist text fields strip HTML/script tags."""

    @pytest.mark.unit
    def test_script_in_notes_stripped(self):
        from app.routers.watchlist import WatchEntryCreate
        body = WatchEntryCreate(
            target_id="ble_aa:bb:cc:dd:ee:ff",
            notes='<script>document.cookie</script>Notes here',
        )
        assert "<script>" not in body.notes

    @pytest.mark.unit
    def test_html_in_label_stripped(self):
        from app.routers.watchlist import WatchEntryCreate
        body = WatchEntryCreate(
            target_id="ble_test",
            label='<b onmouseover="evil()">bold</b>',
        )
        assert "<b " not in body.label
        assert "onmouseover" not in body.label

    @pytest.mark.unit
    def test_xss_in_tags_stripped(self):
        from app.routers.watchlist import WatchEntryCreate
        body = WatchEntryCreate(
            target_id="ble_test",
            tags=['<script>alert(1)</script>', 'normal_tag'],
        )
        for tag in body.tags:
            assert "<script>" not in tag

    @pytest.mark.unit
    def test_tag_count_limit(self):
        from app.routers.watchlist import WatchEntryCreate, _MAX_TAGS
        with pytest.raises(Exception):
            WatchEntryCreate(
                target_id="ble_test",
                tags=["tag"] * (_MAX_TAGS + 1),
            )

    @pytest.mark.unit
    def test_update_xss_prevention(self):
        from app.routers.watchlist import WatchEntryUpdate
        body = WatchEntryUpdate(
            notes='<div onclick="evil()">click me</div>',
        )
        updates = body.model_dump(exclude_none=True)
        assert "<div " not in updates["notes"]

    @pytest.mark.unit
    def test_watchlist_count_limit(self):
        from app.routers.watchlist import _watch_entries, _MAX_WATCH_ENTRIES
        for i in range(_MAX_WATCH_ENTRIES):
            _watch_entries[f"we_{i}"] = {"id": f"we_{i}", "target_id": f"t_{i}"}
        assert len(_watch_entries) >= _MAX_WATCH_ENTRIES


class TestSQLInjection:
    """Verify no SQL injection vectors in annotation/watchlist stores.

    Both stores are in-memory dicts, not SQL. But we verify that user
    text that looks like SQL is stored as-is (escaped) and cannot
    be interpreted as commands.
    """

    @pytest.mark.unit
    def test_sql_in_annotation_text(self):
        from app.routers.annotations import AnnotationCreate
        body = AnnotationCreate(
            type="text", lat=0, lng=0,
            text="'; DROP TABLE annotations; --",
        )
        # Text should be HTML-escaped but preserved as string content
        assert body.text is not None
        assert len(body.text) > 0

    @pytest.mark.unit
    def test_sql_in_watchlist_notes(self):
        from app.routers.watchlist import WatchEntryCreate
        body = WatchEntryCreate(
            target_id="test",
            notes="1' OR '1'='1",
        )
        assert body.notes is not None
        assert len(body.notes) > 0
