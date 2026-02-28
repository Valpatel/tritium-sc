# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Smoke tests for ReportGenerator — validates HTML report generation."""
import os
import tempfile

import pytest

from tests.lib.results_db import ResultsDB
from tests.lib.report_gen import ReportGenerator

pytestmark = pytest.mark.unit


class TestReportGeneratorSmoke:
    """Verify ReportGenerator produces valid HTML from mock data."""

    def _make_db(self, db_path: str) -> ResultsDB:
        """Create a ResultsDB with sample data."""
        db = ResultsDB(db_path=db_path)
        run_id = db.record_run("smoke", "abc1234", "test-machine")
        db.record_result(run_id, "test_pass_1", True, 100.0, {"detail": "ok"})
        db.record_result(run_id, "test_pass_2", True, 200.0, {"detail": "ok"})
        db.record_result(run_id, "test_fail_1", False, 300.0, {"error": "boom"})
        db.record_screenshot(
            run_id, "test_pass_1", "initial", "/tmp/nonexistent.png",
            {"green_pixels": 500}, "I see a map", "localhost", 1234.5,
            {"state": "setup"},
        )
        db.finish_run(run_id)
        return db, run_id

    def test_generate_produces_html(self):
        """ReportGenerator.generate() returns a Path to a valid HTML file."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)

            assert path.exists(), f"Report file not created: {path}"
            assert path.suffix == ".html"

            content = path.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content
            assert "</html>" in content

    def test_html_contains_summary_stats(self):
        """Generated HTML includes pass/fail counts and pass rate."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            # Should contain total, passed, failed counts
            assert "3" in content  # total_tests
            assert "2" in content  # passed
            assert "1" in content  # failed
            assert "test-machine" in content
            assert "abc1234" in content

    def test_html_contains_test_names(self):
        """Generated HTML includes individual test result names."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            assert "test_pass_1" in content
            assert "test_pass_2" in content
            assert "test_fail_1" in content

    def test_html_contains_pass_fail_badges(self):
        """Generated HTML includes PASS and FAIL badge markup."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            assert "result-badge pass" in content
            assert "result-badge fail" in content
            assert "PASS" in content
            assert "FAIL" in content

    def test_html_contains_screenshot_section(self):
        """Generated HTML includes screenshots section with metadata."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            assert "Screenshots" in content
            assert "test_pass_1" in content
            assert "initial" in content

    def test_nonexistent_run_raises(self):
        """generate() raises ValueError for unknown run_id."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            with pytest.raises(ValueError, match="Run 9999 not found"):
                gen.generate(9999)

    def test_trend_svg_with_multiple_runs(self):
        """Trend SVG renders when multiple runs exist."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            for i in range(5):
                rid = db.record_run("trend_test", f"hash{i}", "machine")
                db.record_result(rid, "test_a", True, 100.0, {})
                db.record_result(rid, "test_b", i % 2 == 0, 200.0, {})
                db.finish_run(rid)

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            # Generate report for the last run
            path = gen.generate(5)
            content = path.read_text(encoding="utf-8")

            assert "<svg" in content
            assert "Trend" in content

    def test_export_json_produces_valid_json(self):
        """export_json() creates a JSON file with run data."""
        import json
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.export_json(run_id)

            assert path.exists()
            assert path.suffix == ".json"

            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["run"]["total_tests"] == 3
            assert data["run"]["passed"] == 2
            assert data["run"]["failed"] == 1
            assert len(data["results"]) == 3
            assert len(data["screenshots"]) == 1
            assert "generated_at" in data

    def test_export_json_nonexistent_run_raises(self):
        """export_json() raises ValueError for unknown run_id."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            with pytest.raises(ValueError, match="Run 9999 not found"):
                gen.export_json(9999)

    def test_html_has_tab_navigation(self):
        """Generated HTML includes tab bar with Results and Screenshots."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            assert "tab-bar" in content
            assert "tab-btn" in content
            assert 'data-tab="results"' in content
            assert 'data-tab="screenshots"' in content

    def test_html_has_lightbox(self):
        """Generated HTML includes lightbox for screenshot fullscreen."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            assert 'id="lightbox"' in content
            assert 'id="lightbox-img"' in content

    def test_html_has_collapsible_details(self):
        """Generated HTML includes collapsible result cards with chevrons."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            assert "result-header" in content
            assert "result-chevron" in content
            assert "result-details" in content

    def test_html_has_cybercore_styling(self):
        """Generated HTML uses Cybercore v2 CSS variables and fonts."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            assert "--cyan: #00f0ff" in content
            assert "--void: #0a0a0f" in content
            assert "Inter" in content
            assert "JetBrains Mono" in content
            assert "scanline" in content.lower() or "Scanline" in content

    def test_empty_run_generates(self):
        """A run with zero results still produces valid HTML."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("empty", "000", "machine")
            db.finish_run(run_id)

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)

            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content
            assert "0" in content  # total tests = 0
