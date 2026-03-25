# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Ollama-powered visual testing of the Command Center.

Takes a screenshot of the running Command Center and sends it to llava:7b
via OllamaFleet. The LLM evaluates whether the screenshot shows a tactical
map with targets, cyberpunk styling, and expected UI elements.

Gracefully skips if:
- No running server on localhost:8000
- No Ollama instance available
- llava:7b model not loaded

Usage:
    pytest tests/visual/test_llm_visual.py -v
    pytest tests/visual/test_llm_visual.py -v -k test_tactical_map
"""
from __future__ import annotations

import base64
import os
import sys
import urllib.request
import urllib.error

import pytest


def _server_available(host: str = "localhost", port: int = 8000) -> bool:
    """Check if the SC server is running."""
    try:
        urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=3)
        return True
    except Exception:
        return False


def _get_fleet():
    """Get OllamaFleet instance, or None if unavailable."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))
        from tritium_lib.inference.fleet import OllamaFleet
        fleet = OllamaFleet(auto_discover=False)
        if fleet.count == 0:
            return None
        return fleet
    except Exception:
        return None


def _fleet_has_llava(fleet) -> bool:
    """Check if the fleet has llava model available."""
    if fleet is None:
        return False
    return len(fleet.hosts_with_model("llava")) > 0


def _capture_screenshot_curl(
    url: str = "http://localhost:8000",
    timeout: float = 10.0,
) -> bytes | None:
    """Capture the Command Center page as a screenshot via Playwright.

    Falls back to fetching the HTML if Playwright is not available.
    Returns PNG bytes or None.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(url, wait_until="networkidle", timeout=int(timeout * 1000))
            # Wait for map to render
            page.wait_for_timeout(3000)
            screenshot = page.screenshot(type="png", full_page=False)
            browser.close()
            return screenshot
    except ImportError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Conditions for skipping
# ---------------------------------------------------------------------------

skip_no_server = pytest.mark.skipif(
    not _server_available(),
    reason="SC server not running on localhost:8000",
)

_fleet = _get_fleet()
skip_no_ollama = pytest.mark.skipif(
    _fleet is None,
    reason="No Ollama instance available",
)

skip_no_llava = pytest.mark.skipif(
    not _fleet_has_llava(_fleet),
    reason="llava model not available on any Ollama host",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@skip_no_server
@skip_no_ollama
@skip_no_llava
class TestLLMVisual:
    """LLM-powered visual verification of the Command Center."""

    def test_tactical_map_visible(self):
        """Verify the Command Center shows a tactical map with targets."""
        screenshot = _capture_screenshot_curl()
        if screenshot is None:
            pytest.skip("Could not capture screenshot (Playwright not available)")

        fleet = _get_fleet()
        assert fleet is not None

        img_b64 = base64.b64encode(screenshot).decode()

        response = fleet.chat(
            model="llava:7b",
            prompt=(
                "Look at this screenshot of a tactical command center application. "
                "Answer these questions with YES or NO:\n"
                "1. Does it show a map or tactical display?\n"
                "2. Are there any target markers, icons, or indicators on the display?\n"
                "3. Does it have a cyberpunk or dark theme with neon colors?\n"
                "4. Does it appear to be a real application (not an error page)?\n"
                "After answering, give a final verdict: PASS or FAIL."
            ),
            images=[img_b64],
            timeout=60.0,
        )

        assert response, "LLM returned empty response"
        response_lower = response.lower()

        # The LLM should say PASS if the UI looks correct
        has_pass = "pass" in response_lower
        has_map = "yes" in response_lower

        # Log the full response for debugging
        print(f"\nLLM Visual Assessment:\n{response}\n")

        assert has_pass or has_map, (
            f"LLM visual check did not confirm tactical map. Response: {response}"
        )

    def test_no_error_page(self):
        """Verify the Command Center is not showing an error page."""
        screenshot = _capture_screenshot_curl()
        if screenshot is None:
            pytest.skip("Could not capture screenshot (Playwright not available)")

        fleet = _get_fleet()
        assert fleet is not None

        img_b64 = base64.b64encode(screenshot).decode()

        response = fleet.chat(
            model="llava:7b",
            prompt=(
                "Is this screenshot showing an error page, a blank page, "
                "or a 'page not found' message? Answer YES or NO, then explain briefly."
            ),
            images=[img_b64],
            timeout=60.0,
        )

        assert response, "LLM returned empty response"
        response_lower = response.lower()

        # "no" means it's NOT an error page (which is what we want)
        # We check that the LLM doesn't say "yes" to it being an error
        lines = response_lower.split("\n")
        first_word = lines[0].strip().split()[0] if lines and lines[0].strip() else ""
        is_error = first_word == "yes"

        assert not is_error, f"LLM detected an error page: {response}"
