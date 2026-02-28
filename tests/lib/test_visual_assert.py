# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for VisualAssert — three-layer visual verification."""
import numpy as np
import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path

pytestmark = pytest.mark.unit


class TestOpenCVAssertions:
    """Layer 1: OpenCV pixel-level assertions."""

    def test_color_present_green(self):
        """Synthetic image with green pixels detected."""
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        # Create 100x100 image with green rectangle (BGR: 161, 255, 5 = #05ffa1)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[20:40, 20:40] = (161, 255, 5)  # green in BGR
        assert va.assert_color_present(img, (161, 255, 5), tolerance=40, min_pixels=50)

    def test_color_present_missing(self):
        """All-black image has no green."""
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        assert not va.assert_color_present(img, (161, 255, 5), tolerance=40, min_pixels=50)

    def test_count_blobs_three_circles(self):
        """Image with 3 red circles -> count = 3."""
        import cv2
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        # Draw 3 red circles (BGR: 109, 42, 255 = #ff2a6d) well separated
        cv2.circle(img, (40, 40), 15, (109, 42, 255), -1)
        cv2.circle(img, (100, 100), 15, (109, 42, 255), -1)
        cv2.circle(img, (160, 160), 15, (109, 42, 255), -1)
        count = va.count_color_blobs(img, (109, 42, 255), tolerance=40, min_area=20)
        assert count == 3

    def test_count_blobs_empty(self):
        """Black image has 0 blobs."""
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        assert va.count_color_blobs(img, (109, 42, 255), tolerance=40, min_area=20) == 0

    def test_region_not_blank_with_content(self):
        """Region with varied pixels is not blank."""
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[10:30, 10:30] = (255, 200, 100)  # Some content
        assert va.assert_region_not_blank(img, 10, 10, 20, 20, threshold=10)

    def test_region_blank(self):
        """All-black region is blank."""
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        assert not va.assert_region_not_blank(img, 10, 10, 20, 20, threshold=10)

    def test_region_has_text_with_edges(self):
        """Region with edge-dense content detects as text."""
        import cv2
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        # Draw text-like content (high edge density)
        cv2.putText(img, "SCORE: 1234", (5, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        assert va.assert_region_has_text(img, 0, 0, 100, 100)


class TestStructuredLLM:
    """Layer 2: Structured LLM query parsing with majority vote."""

    def _make_fleet(self, response_text: str) -> MagicMock:
        """Create a mock fleet that always returns the given response."""
        mock_fleet = MagicMock()
        mock_fleet.generate.return_value = {
            "response": response_text,
            "host": "local",
            "model": "llava:7b",
            "elapsed_ms": 100,
        }
        return mock_fleet

    def test_ask_yes_no_yes(self):
        """YES response parsed correctly (all votes agree)."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = self._make_fleet("YES")
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        assert va.ask_yes_no(Path("/tmp/fake.png"), "Is there a map?") is True
        assert mock_fleet.generate.call_count == 3  # majority vote

    def test_ask_yes_no_no(self):
        """NO response parsed correctly (all votes agree)."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = self._make_fleet("NO")
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        assert va.ask_yes_no(Path("/tmp/fake.png"), "Is there a map?") is False

    def test_ask_yes_no_verbose_yes(self):
        """Verbose YES response still parsed."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = self._make_fleet("Yes, I can see green squares on the map.")
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        assert va.ask_yes_no(Path("/tmp/fake.png"), "Are green squares visible?") is True

    def test_ask_yes_no_majority_wins(self):
        """2/3 YES votes wins even with one NO."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = MagicMock()
        mock_fleet.generate.side_effect = [
            {"response": "YES"},
            {"response": "No, I don't see anything"},
            {"response": "Yes"},
        ]
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        assert va.ask_yes_no(Path("/tmp/fake.png"), "Green visible?") is True

    def test_ask_yes_no_majority_no(self):
        """2/3 NO votes means False."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = MagicMock()
        mock_fleet.generate.side_effect = [
            {"response": "No"},
            {"response": "Yes, I see it"},
            {"response": "No"},
        ]
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        assert va.ask_yes_no(Path("/tmp/fake.png"), "Green visible?") is False

    def test_ask_count_number(self):
        """Integer extracted from LLM response (median of votes)."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = self._make_fleet("5")
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        assert va.ask_count(Path("/tmp/fake.png"), "How many red shapes?") == 5

    def test_ask_count_verbose(self):
        """Integer extracted from verbose response like 'I see 5 shapes'."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = self._make_fleet("I can see approximately 5 red diamond shapes.")
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        assert va.ask_count(Path("/tmp/fake.png"), "How many red shapes?") == 5

    def test_ask_count_zero(self):
        """Zero when no count found in any vote."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = self._make_fleet("I don't see any shapes.")
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        assert va.ask_count(Path("/tmp/fake.png"), "How many red shapes?") == 0

    def test_ask_count_median(self):
        """Median of noisy counts stabilizes result."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = MagicMock()
        mock_fleet.generate.side_effect = [
            {"response": "3"},
            {"response": "13"},  # hallucinated
            {"response": "3"},
        ]
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        assert va.ask_count(Path("/tmp/fake.png"), "How many shapes?") == 3

    def test_ask_choice(self):
        """Choice extracted from response (majority vote)."""
        from tests.lib.visual_assert import VisualAssert
        mock_fleet = self._make_fleet("active")
        va = VisualAssert(fleet=mock_fleet, db=None, run_id=0)
        result = va.ask_choice(Path("/tmp/fake.png"), "Game state?", ["setup", "countdown", "active", "gameover"])
        assert result == "active"


class TestVerifyLogic:
    """Test the tiered pass logic in verify()."""

    def test_all_pass(self):
        """All three layers pass -> overall pass."""
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = va.verify(
            "test", "phase", Path("/tmp/fake.png"), img,
            opencv_checks=[("check1", lambda: True)],
            llm_checks=[("check2", lambda: True)],
            api_checks=[("check3", lambda: True)],
        )
        assert result["passed"] is True

    def test_opencv_api_pass_llm_fail_still_passes(self):
        """OpenCV+API pass but LLM fails -> overall PASS (LLM advisory)."""
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = va.verify(
            "test", "phase", Path("/tmp/fake.png"), img,
            opencv_checks=[("cv_ok", lambda: True)],
            llm_checks=[("llm_fail", lambda: False)],
            api_checks=[("api_ok", lambda: True)],
        )
        assert result["passed"] is True
        assert "llm_advisory" in result

    def test_opencv_fail_blocks(self):
        """OpenCV failure blocks even if LLM+API pass."""
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = va.verify(
            "test", "phase", Path("/tmp/fake.png"), img,
            opencv_checks=[("cv_fail", lambda: False)],
            llm_checks=[("llm_ok", lambda: True)],
            api_checks=[("api_ok", lambda: True)],
        )
        assert result["passed"] is False

    def test_api_fail_blocks(self):
        """API failure blocks even if OpenCV+LLM pass."""
        from tests.lib.visual_assert import VisualAssert
        va = VisualAssert(fleet=None, db=None, run_id=0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = va.verify(
            "test", "phase", Path("/tmp/fake.png"), img,
            opencv_checks=[("cv_ok", lambda: True)],
            llm_checks=[("llm_ok", lambda: True)],
            api_checks=[("api_fail", lambda: False)],
        )
        assert result["passed"] is False
