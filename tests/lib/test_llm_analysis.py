# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for LLM-powered test result analysis in report generation.

Covers:
- Failure clustering by error message similarity
- Fleet generate() integration for root cause analysis
- Fleet chat() multimodal integration for vision analysis
- Analysis tab rendering in HTML reports
- Graceful degradation when no Ollama hosts are reachable
- Screenshot analysis sends image data via fleet.chat()
- CLI --fleet flag
"""
import base64
import json
import os
import struct
import tempfile
import zlib
from unittest.mock import MagicMock, patch

import pytest

from tests.lib.results_db import ResultsDB
from tests.lib.report_gen import ReportGenerator

pytestmark = pytest.mark.unit


def _make_tiny_png() -> bytes:
    """Create a valid 1x1 red PNG file (smallest possible)."""
    # IHDR: 1x1, 8-bit RGBA
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    # IDAT: single row, filter=0, R=255 G=0 B=0
    raw = b"\x00\xff\x00\x00"
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)

    # IEND
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


class TestFailureClustering:
    """Verify failure clustering groups errors by prefix similarity."""

    def _make_db_with_failures(self, db_path: str, failures: list[tuple[str, str]]):
        """Create a ResultsDB with specific failure patterns.

        Args:
            db_path: Path for the SQLite database.
            failures: List of (test_name, error_message) tuples.

        Returns:
            Tuple of (ResultsDB, run_id).
        """
        db = ResultsDB(db_path=db_path)
        run_id = db.record_run("analysis", "abc1234", "test-machine")
        for test_name, error_msg in failures:
            db.record_result(
                run_id, test_name, False, 100.0,
                {"error": error_msg},
            )
        # Add a passing test too
        db.record_result(run_id, "test_passing", True, 50.0, {})
        db.finish_run(run_id)
        return db, run_id

    def test_failure_clustering_groups_by_prefix(self):
        """10 failures with 3 unique error prefixes produce 3 clusters."""
        with tempfile.TemporaryDirectory() as d:
            # Error messages designed so first 50 chars match within each group
            failures = [
                ("test_auth_1", "AuthenticationError: invalid credentials received from the user admin endpoint"),
                ("test_auth_2", "AuthenticationError: invalid credentials received from the user guest endpoint"),
                ("test_auth_3", "AuthenticationError: invalid credentials received from the service api endpoint"),
                ("test_auth_4", "AuthenticationError: invalid credentials received from the token refresh endpoint"),
                ("test_db_1", "DatabaseConnectionError: connection pool exhausted for primary replica on host db01"),
                ("test_db_2", "DatabaseConnectionError: connection pool exhausted for primary replica on host db02"),
                ("test_db_3", "DatabaseConnectionError: connection pool exhausted for secondary replica on host db03"),
                ("test_timeout_1", "RequestTimeoutError: upstream service at gateway timed out waiting for response from auth"),
                ("test_timeout_2", "RequestTimeoutError: upstream service at gateway timed out waiting for response from data"),
                ("test_timeout_3", "RequestTimeoutError: upstream service at gateway timed out waiting for response from cache"),
            ]
            db, run_id = self._make_db_with_failures(
                os.path.join(d, "test.db"), failures,
            )
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            results = gen._get_all_results(run_id)
            failed = [r for r in results if not r.get("passed")]

            clusters = gen._analyze_failures(failed)

            assert "clusters" in clusters
            assert len(clusters["clusters"]) == 3

            # Each cluster should have a count and representative error
            for cluster in clusters["clusters"]:
                assert "count" in cluster
                assert "representative" in cluster
                assert "test_files" in cluster
                assert cluster["count"] >= 1

            # Verify the counts match: 4 auth + 3 db + 3 timeout = 10
            counts = sorted(c["count"] for c in clusters["clusters"])
            assert counts == [3, 3, 4]

    def test_failure_clustering_single_error(self):
        """A single failure produces 1 cluster."""
        with tempfile.TemporaryDirectory() as d:
            failures = [
                ("test_one", "SomeError: something went wrong entirely"),
            ]
            db, run_id = self._make_db_with_failures(
                os.path.join(d, "test.db"), failures,
            )
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            results = gen._get_all_results(run_id)
            failed = [r for r in results if not r.get("passed")]

            clusters = gen._analyze_failures(failed)
            assert len(clusters["clusters"]) == 1
            assert clusters["clusters"][0]["count"] == 1

    def test_failure_clustering_no_failures(self):
        """Zero failures produce empty clusters."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("clean", "abc", "machine")
            db.record_result(run_id, "test_ok", True, 50.0, {})
            db.finish_run(run_id)

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            clusters = gen._analyze_failures([])
            assert clusters["clusters"] == []


class TestFleetGenerate:
    """Verify OllamaFleet.generate() method."""

    def test_generate_calls_fleet(self):
        """generate() calls the best host with the correct model."""
        with tempfile.TemporaryDirectory() as d:
            failures = [
                ("test_a", "ValueError: bad input data in parser"),
                ("test_b", "ValueError: bad input data in validator"),
            ]
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("analysis", "abc1234", "machine")
            for name, err in failures:
                db.record_result(run_id, name, False, 100.0, {"error": err})
            db.finish_run(run_id)

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            results = gen._get_all_results(run_id)
            failed = [r for r in results if not r.get("passed")]

            # Mock fleet
            mock_fleet = MagicMock()
            mock_fleet.generate.return_value = "Root cause: input validation is broken"

            clusters = gen._analyze_failures(failed, fleet=mock_fleet)

            # Fleet.generate should have been called with qwen2.5:7b
            mock_fleet.generate.assert_called_once()
            call_args = mock_fleet.generate.call_args
            assert call_args[1]["model"] == "qwen2.5:7b" or call_args[0][0] == "qwen2.5:7b"
            assert "llm_analysis" in clusters

    def test_generate_method_on_fleet(self):
        """OllamaFleet.generate() sends POST to /api/generate endpoint."""
        from engine.inference.fleet import OllamaFleet, FleetHost

        fleet = OllamaFleet(auto_discover=False)
        # Manually add a fake host
        fleet._hosts = [
            FleetHost(
                url="http://localhost:11434",
                name="localhost",
                models=["qwen2.5:7b"],
                latency_ms=10.0,
            )
        ]

        # Mock the urllib request
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"response": "test analysis"}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = fleet.generate(model="qwen2.5:7b", prompt="test prompt")

            assert result == "test analysis"
            mock_urlopen.assert_called_once()

    def test_generate_no_host_returns_empty(self):
        """generate() returns empty string when no host has the model."""
        from engine.inference.fleet import OllamaFleet

        fleet = OllamaFleet(auto_discover=False)
        fleet._hosts = []  # No hosts

        result = fleet.generate(model="qwen2.5:7b", prompt="test")
        assert result == ""


class TestAnalysisTab:
    """Verify Analysis tab appears in generated HTML reports."""

    def _make_db_with_failures(self, db_path: str):
        """Create a ResultsDB with some failures for analysis."""
        db = ResultsDB(db_path=db_path)
        run_id = db.record_run("analysis", "abc1234", "test-machine")
        db.record_result(run_id, "test_pass_1", True, 100.0, {})
        db.record_result(
            run_id, "test_fail_1", False, 200.0,
            {"error": "AssertionError: expected 5 got 3"},
        )
        db.record_result(
            run_id, "test_fail_2", False, 150.0,
            {"error": "AssertionError: expected 5 got 4"},
        )
        db.finish_run(run_id)
        return db, run_id

    def test_analysis_tab_in_report(self):
        """Generated HTML contains an Analysis tab when failures exist."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db_with_failures(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            assert 'data-tab="analysis"' in content
            assert 'id="tab-analysis"' in content
            assert "Failure Clusters" in content

    def test_analysis_tab_absent_when_all_pass(self):
        """Analysis tab is NOT present when all tests pass."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("clean", "abc", "machine")
            db.record_result(run_id, "test_ok_1", True, 50.0, {})
            db.record_result(run_id, "test_ok_2", True, 50.0, {})
            db.finish_run(run_id)

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            assert 'data-tab="analysis"' not in content

    def test_analysis_shows_cluster_table(self):
        """Analysis tab renders cluster count and representative errors."""
        with tempfile.TemporaryDirectory() as d:
            db, run_id = self._make_db_with_failures(os.path.join(d, "test.db"))
            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id)
            content = path.read_text(encoding="utf-8")

            # Should show the cluster representative error text
            assert "AssertionError" in content


class TestGracefulDegradation:
    """Verify report works when no Ollama fleet is available."""

    def test_graceful_no_fleet(self):
        """When fleet.generate() fails, analysis says 'LLM analysis unavailable'."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("analysis", "abc", "machine")
            db.record_result(
                run_id, "test_fail", False, 100.0,
                {"error": "SomeError: broken"},
            )
            db.finish_run(run_id)

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            results = gen._get_all_results(run_id)
            failed = [r for r in results if not r.get("passed")]

            # Mock fleet that raises on generate
            mock_fleet = MagicMock()
            mock_fleet.generate.side_effect = Exception("Connection refused")

            clusters = gen._analyze_failures(failed, fleet=mock_fleet)

            assert "llm_analysis" in clusters
            assert "unavailable" in clusters["llm_analysis"].lower()

    def test_report_with_unreachable_fleet(self):
        """Full report generation with a broken fleet still produces valid HTML."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("analysis", "abc", "machine")
            db.record_result(
                run_id, "test_fail", False, 100.0,
                {"error": "SomeError: broken"},
            )
            db.finish_run(run_id)

            mock_fleet = MagicMock()
            mock_fleet.generate.side_effect = Exception("Connection refused")

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            path = gen.generate(run_id, fleet=mock_fleet)
            content = path.read_text(encoding="utf-8")

            assert "<!DOCTYPE html>" in content
            assert "LLM analysis unavailable" in content


class TestScreenshotAnalysis:
    """Verify screenshot analysis only runs for failed tests."""

    def test_screenshot_analysis_skipped_for_passing_tests(self):
        """Only screenshots from failed tests are analyzed via fleet.chat()."""
        with tempfile.TemporaryDirectory() as d:
            png_bytes = _make_tiny_png()
            pass_img = os.path.join(d, "pass.png")
            fail_img = os.path.join(d, "fail.png")
            for p in (pass_img, fail_img):
                with open(p, "wb") as f:
                    f.write(png_bytes)

            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("screenshots", "abc", "machine")

            # One passing test with screenshot
            db.record_result(run_id, "test_pass", True, 100.0, {})
            db.record_screenshot(
                run_id, "test_pass", "initial", pass_img,
                {}, "", "", 0.0, {},
            )

            # One failing test with screenshot
            db.record_result(
                run_id, "test_fail", False, 100.0,
                {"error": "visual mismatch"},
            )
            db.record_screenshot(
                run_id, "test_fail", "initial", fail_img,
                {}, "", "", 0.0, {},
            )
            db.finish_run(run_id)

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))

            mock_fleet = MagicMock()
            mock_fleet.chat.return_value = "Screenshot shows broken layout"

            results = gen._get_all_results(run_id)
            screenshots = db.get_screenshots(run_id)
            failed_names = {
                r["test_name"] for r in results if not r.get("passed")
            }

            annotations = gen._analyze_screenshots(
                screenshots, failed_names, fleet=mock_fleet,
            )

            # Should only have annotation for the failed test
            assert "test_fail" in annotations
            assert "test_pass" not in annotations
            # Must use chat() not generate() for vision
            mock_fleet.chat.assert_called_once()
            mock_fleet.generate.assert_not_called()

    def test_screenshot_sends_image_data(self):
        """Verify base64 image data is actually sent to fleet.chat()."""
        with tempfile.TemporaryDirectory() as d:
            png_bytes = _make_tiny_png()
            fail_img = os.path.join(d, "fail.png")
            with open(fail_img, "wb") as f:
                f.write(png_bytes)

            expected_b64 = base64.b64encode(png_bytes).decode()

            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("screenshots", "abc", "machine")
            db.record_result(
                run_id, "test_fail", False, 100.0,
                {"error": "visual mismatch"},
            )
            db.record_screenshot(
                run_id, "test_fail", "initial", fail_img,
                {}, "", "", 0.0, {},
            )
            db.finish_run(run_id)

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))

            mock_fleet = MagicMock()
            mock_fleet.chat.return_value = "Broken layout detected"

            screenshots = db.get_screenshots(run_id)
            annotations = gen._analyze_screenshots(
                screenshots, {"test_fail"}, fleet=mock_fleet,
            )

            assert annotations["test_fail"] == "Broken layout detected"

            # Verify fleet.chat() was called with the image data
            call_kwargs = mock_fleet.chat.call_args
            assert call_kwargs is not None
            # Check images kwarg contains the base64 data
            if call_kwargs.kwargs:
                assert "images" in call_kwargs.kwargs
                assert call_kwargs.kwargs["images"] == [expected_b64]
                assert call_kwargs.kwargs["model"] == "llava:7b"
            else:
                # positional: chat(model, prompt, images, timeout)
                assert expected_b64 in call_kwargs.args[2]

    def test_screenshot_analysis_no_fleet(self):
        """Without a fleet, screenshot analysis returns empty dict."""
        with tempfile.TemporaryDirectory() as d:
            db = ResultsDB(db_path=os.path.join(d, "test.db"))
            run_id = db.record_run("screenshots", "abc", "machine")
            db.record_result(
                run_id, "test_fail", False, 100.0,
                {"error": "visual mismatch"},
            )
            db.record_screenshot(
                run_id, "test_fail", "initial", "/tmp/fail.png",
                {}, "", "", 0.0, {},
            )
            db.finish_run(run_id)

            gen = ReportGenerator(db, output_dir=os.path.join(d, "reports"))
            screenshots = db.get_screenshots(run_id)

            annotations = gen._analyze_screenshots(
                screenshots, {"test_fail"}, fleet=None,
            )
            assert annotations == {}


class TestFleetChat:
    """Verify OllamaFleet.chat() multimodal method."""

    def test_chat_sends_multimodal_request(self):
        """fleet.chat() sends correct payload to /api/chat with images."""
        from engine.inference.fleet import OllamaFleet, FleetHost

        fleet = OllamaFleet(auto_discover=False)
        fleet._hosts = [
            FleetHost(
                url="http://localhost:11434",
                name="localhost",
                models=["llava:7b"],
                latency_ms=10.0,
            )
        ]

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({
                "message": {"content": "I see a broken layout"}
            }).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = fleet.chat(
                model="llava:7b",
                prompt="What is wrong?",
                images=["abc123base64data"],
            )

            assert result == "I see a broken layout"
            mock_urlopen.assert_called_once()

            # Verify the request payload sent to /api/chat
            req_obj = mock_urlopen.call_args[0][0]
            payload = json.loads(req_obj.data.decode())
            assert payload["model"] == "llava:7b"
            assert payload["stream"] is False
            assert len(payload["messages"]) == 1
            assert payload["messages"][0]["role"] == "user"
            assert payload["messages"][0]["content"] == "What is wrong?"
            assert payload["messages"][0]["images"] == ["abc123base64data"]
            assert "/api/chat" in req_obj.full_url

    def test_chat_without_images(self):
        """fleet.chat() works without images (text-only chat)."""
        from engine.inference.fleet import OllamaFleet, FleetHost

        fleet = OllamaFleet(auto_discover=False)
        fleet._hosts = [
            FleetHost(
                url="http://localhost:11434",
                name="localhost",
                models=["qwen2.5:7b"],
                latency_ms=10.0,
            )
        ]

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({
                "message": {"content": "Analysis complete"}
            }).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = fleet.chat(model="qwen2.5:7b", prompt="Analyze this")

            assert result == "Analysis complete"
            req_obj = mock_urlopen.call_args[0][0]
            payload = json.loads(req_obj.data.decode())
            # No images key when none provided
            assert "images" not in payload["messages"][0]

    def test_chat_no_host_returns_empty(self):
        """chat() returns empty string when no host has the model."""
        from engine.inference.fleet import OllamaFleet

        fleet = OllamaFleet(auto_discover=False)
        fleet._hosts = []

        result = fleet.chat(model="llava:7b", prompt="test")
        assert result == ""

    def test_chat_handles_error_gracefully(self):
        """chat() returns empty string on network error."""
        from engine.inference.fleet import OllamaFleet, FleetHost

        fleet = OllamaFleet(auto_discover=False)
        fleet._hosts = [
            FleetHost(
                url="http://localhost:11434",
                name="localhost",
                models=["llava:7b"],
                latency_ms=10.0,
            )
        ]

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Connection refused")

            result = fleet.chat(model="llava:7b", prompt="test", images=["abc"])
            assert result == ""


class TestCLIFleetFlag:
    """Verify --fleet CLI flag creates OllamaFleet."""

    def test_cli_fleet_flag_creates_fleet(self):
        """--fleet flag causes OllamaFleet to be created and passed to generate()."""
        with tempfile.TemporaryDirectory() as d:
            # Create a DB with a run
            db_path = os.path.join(d, "test.db")
            db = ResultsDB(db_path=db_path)
            run_id = db.record_run("unit", "abc", "machine")
            db.record_result(run_id, "test_ok", True, 50.0, {})
            db.finish_run(run_id)

            with patch("tests.lib.report_gen.OllamaFleet") as MockFleet, \
                 patch("sys.argv", [
                     "report_gen.py", "--latest", "--suite", "unit",
                     "--db", db_path,
                     "--output-dir", os.path.join(d, "reports"),
                     "--fleet",
                 ]):
                mock_fleet_instance = MagicMock()
                MockFleet.return_value = mock_fleet_instance

                from tests.lib.report_gen import _cli
                _cli()

                MockFleet.assert_called_once_with(auto_discover=True)

    def test_cli_no_fleet_flag(self):
        """Without --fleet, no OllamaFleet is created."""
        with tempfile.TemporaryDirectory() as d:
            db_path = os.path.join(d, "test.db")
            db = ResultsDB(db_path=db_path)
            run_id = db.record_run("unit", "abc", "machine")
            db.record_result(run_id, "test_ok", True, 50.0, {})
            db.finish_run(run_id)

            with patch("tests.lib.report_gen.OllamaFleet") as MockFleet, \
                 patch("sys.argv", [
                     "report_gen.py", "--latest", "--suite", "unit",
                     "--db", db_path,
                     "--output-dir", os.path.join(d, "reports"),
                 ]):
                from tests.lib.report_gen import _cli
                _cli()

                MockFleet.assert_not_called()
