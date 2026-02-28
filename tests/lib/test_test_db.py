# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for ResultsDB — the SQLite test results store."""
import pytest
import tempfile
import os
from tests.lib.results_db import ResultsDB

pytestmark = pytest.mark.unit


class TestTestDB:
    def test_create_tables(self):
        """DB initializes without error, tables exist."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            import sqlite3
            conn = sqlite3.connect(os.path.join(d, "test.db"))
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            assert "runs" in tables
            assert "results" in tables
            assert "screenshots" in tables

    def test_record_and_retrieve_run(self):
        """Round-trip run data."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("visual", "abc1234", "gb10-01")
            summary = db.get_run_summary(run_id)
            assert summary["suite"] == "visual"
            assert summary["git_hash"] == "abc1234"
            assert summary["machine"] == "gb10-01"

    def test_record_results(self):
        """Insert + query results."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("unit", "def5678", "gb10-02")
            db.record_result(run_id, "test_foo", True, 123.4, {"detail": "ok"})
            db.record_result(run_id, "test_bar", False, 456.7, {"error": "boom"})
            failures = db.get_failures(run_id)
            assert len(failures) == 1
            assert failures[0]["test_name"] == "test_bar"

    def test_trend_calculation(self):
        """Multiple runs show trend."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            for i in range(5):
                rid = db.record_run("unit", f"hash{i}", "gb10-01")
                db.record_result(rid, "test_a", True, 100.0, {})
                db.record_result(rid, "test_b", i % 2 == 0, 200.0, {})
                db.finish_run(rid)
            trend = db.get_trend("unit", last_n=5)
            assert len(trend) == 5

    def test_screenshot_storage(self):
        """Screenshot metadata persists."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("visual", "xyz", "gb10-01")
            db.record_screenshot(run_id, "test_map", "initial",
                                 "/tmp/shot.png", {"green_pixels": 500},
                                 "I see a map", "gb10-01", 1234.5, {"state": "setup"})
            summary = db.get_run_summary(run_id)
            assert summary is not None

    def test_record_result_updates_counts(self):
        """Inserting results updates run pass/fail counts."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("unit", "aaa", "gb10-01")
            db.record_result(run_id, "test_a", True, 10.0, {})
            db.record_result(run_id, "test_b", True, 20.0, {})
            db.record_result(run_id, "test_c", False, 30.0, {})
            summary = db.get_run_summary(run_id)
            assert summary["total_tests"] == 3
            assert summary["passed"] == 2
            assert summary["failed"] == 1

    def test_finish_run_sets_timestamp(self):
        """finish_run sets finished_at."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("unit", "bbb", "gb10-01")
            db.finish_run(run_id)
            summary = db.get_run_summary(run_id)
            assert summary["finished_at"] is not None

    def test_get_failures_empty(self):
        """No failures returns empty list."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("unit", "ccc", "gb10-01")
            db.record_result(run_id, "test_ok", True, 10.0, {})
            failures = db.get_failures(run_id)
            assert failures == []

    def test_trend_ordering(self):
        """Trend returns most recent runs last (chronological)."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            for i in range(3):
                rid = db.record_run("unit", f"h{i}", "gb10-01")
                db.record_result(rid, "test_a", True, 100.0, {})
                db.finish_run(rid)
            trend = db.get_trend("unit", last_n=3)
            # IDs should be ascending (oldest first)
            ids = [t["id"] for t in trend]
            assert ids == sorted(ids)

    def test_get_run_summary_nonexistent(self):
        """Nonexistent run_id returns None."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            summary = db.get_run_summary(9999)
            assert summary is None

    def test_get_screenshots(self):
        """Can retrieve screenshots for a run."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("visual", "xyz", "gb10-01")
            db.record_screenshot(run_id, "test_map", "initial",
                                 "/tmp/a.png", {"px": 1}, "map", "gb10-01", 100.0, {})
            db.record_screenshot(run_id, "test_map", "final",
                                 "/tmp/b.png", {"px": 2}, "done", "gb10-02", 200.0, {})
            shots = db.get_screenshots(run_id)
            assert len(shots) == 2
            assert shots[0]["phase"] == "initial"
            assert shots[1]["phase"] == "final"
