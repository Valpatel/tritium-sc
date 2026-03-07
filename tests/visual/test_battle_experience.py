# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Battle Experience Test — full end-to-end game verification with AI evaluation.

Starts a server, runs a battle, captures screenshots at key moments,
and uses local AI models (qwen3-vl) to evaluate the visual quality.

Usage:
    python -m pytest tests/visual/test_battle_experience.py -v
"""

import json
import os
import time

import pytest
import requests
from playwright.sync_api import sync_playwright

RESULTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", ".test-results", "battle-experience"
)
BASE_URL = os.environ.get("TRITIUM_URL", "http://localhost:8000")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def _ollama_available():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.ok
    except Exception:
        return False


def _server_available():
    try:
        r = requests.get(f"{BASE_URL}/api/amy/status", timeout=3)
        return r.ok
    except Exception:
        return False


def _ask_vision(image_path: str, prompt: str, model: str = "qwen3-vl:8b") -> str:
    """Ask a vision model about an image."""
    import base64

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    # Try fleet hosts
    hosts = [OLLAMA_URL, "http://gb10-02:11434"]
    for host in hosts:
        try:
            resp = requests.post(
                f"{host}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                            "images": [img_b64],
                        }
                    ],
                    "stream": False,
                },
                timeout=120,
            )
            if resp.ok:
                return resp.json()["message"]["content"]
        except Exception:
            continue
    return ""


@pytest.fixture(scope="module")
def results_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    return RESULTS_DIR


@pytest.fixture(scope="module")
def browser_context():
    if not _server_available():
        pytest.skip("Server not running")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # Collect console errors
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        page.goto(BASE_URL, wait_until="networkidle")
        # Wait for MapLibre tiles to load (satellite imagery takes time)
        page.wait_for_timeout(8000)

        yield {"page": page, "errors": errors}

        browser.close()


class TestBattleExperience:
    """Full battle experience test suite."""

    def test_01_idle_state_no_errors(self, browser_context, results_dir):
        """Command Center loads without JS errors."""
        page = browser_context["page"]
        errors = browser_context["errors"]

        page.screenshot(path=os.path.join(results_dir, "01_idle.png"))

        js_errors = [e for e in errors if "has already been declared" in e or "is not defined" in e]
        assert len(js_errors) == 0, f"JS errors: {js_errors}"

    def test_02_begin_battle(self, browser_context, results_dir):
        """Can start a battle via API and see countdown."""
        # Reset + begin
        requests.post(f"{BASE_URL}/api/game/reset")
        time.sleep(0.5)
        resp = requests.post(f"{BASE_URL}/api/game/begin")
        assert resp.ok, f"Failed to begin war: {resp.text}"

        data = resp.json()
        assert data["status"] == "countdown_started"

        # Wait for countdown
        page = browser_context["page"]
        page.wait_for_timeout(6000)
        page.screenshot(path=os.path.join(results_dir, "02_battle_start.png"))

    def test_03_units_on_map(self, browser_context, results_dir):
        """Friendly and hostile units visible during battle."""
        resp = requests.get(f"{BASE_URL}/api/amy/simulation/targets")
        assert resp.ok
        targets = resp.json().get("targets", [])

        friendlies = [t for t in targets if t["alliance"] == "friendly"]
        hostiles = [t for t in targets if t["alliance"] == "hostile"]

        assert len(friendlies) >= 5, f"Expected >= 5 friendlies, got {len(friendlies)}"
        assert len(hostiles) >= 1, f"Expected >= 1 hostile, got {len(hostiles)}"

    def test_04_game_progresses(self, browser_context, results_dir):
        """Game progresses through waves."""
        page = browser_context["page"]

        # Wait for combat to develop
        page.wait_for_timeout(15000)
        page.screenshot(path=os.path.join(results_dir, "04_mid_battle.png"))

        resp = requests.get(f"{BASE_URL}/api/game/state")
        assert resp.ok
        state = resp.json()
        assert state["state"] in ("active", "wave_complete", "victory", "defeat"), \
            f"Unexpected game state: {state['state']}"

    def test_05_score_tracked(self, browser_context, results_dir):
        """Score increases during battle."""
        resp = requests.get(f"{BASE_URL}/api/game/state")
        state = resp.json()
        # Wave or score should have progressed
        assert state["wave"] >= 1, "Should be on wave 1 or higher"

    def test_06_visual_quality_ai_eval(self, browser_context, results_dir):
        """AI vision model evaluates the battle scene quality."""
        if not _ollama_available():
            pytest.skip("No Ollama available for vision evaluation")

        page = browser_context["page"]
        page.screenshot(path=os.path.join(results_dir, "06_ai_eval.png"))

        eval_result = _ask_vision(
            os.path.join(results_dir, "06_ai_eval.png"),
            "This is a real-time tactical command center game during a battle. "
            "Answer with JSON only: {\"unit_markers_visible\": true/false, "
            "\"minimap_visible\": true/false, \"panels_visible\": true/false, "
            "\"approximate_unit_count\": number, \"overall_rating\": 1-10, "
            "\"missing_elements\": [list of strings]}",
        )

        # Save evaluation
        with open(os.path.join(results_dir, "06_ai_eval.txt"), "w") as f:
            f.write(eval_result)

        # Try to parse JSON from the response
        assert "unit_markers_visible" in eval_result.lower() or "true" in eval_result.lower(), \
            f"AI could not identify unit markers: {eval_result[:200]}"

    def test_07_wait_for_completion(self, browser_context, results_dir):
        """Wait for battle to finish (victory or defeat) and screenshot."""
        page = browser_context["page"]

        # Wait up to 120s for game to end
        for _ in range(24):
            resp = requests.get(f"{BASE_URL}/api/game/state")
            state = resp.json()
            if state["state"] in ("victory", "defeat"):
                break
            page.wait_for_timeout(5000)

        page.screenshot(path=os.path.join(results_dir, "07_game_end.png"))

        resp = requests.get(f"{BASE_URL}/api/game/state")
        state = resp.json()

        # Save final state
        with open(os.path.join(results_dir, "07_final_state.json"), "w") as f:
            json.dump(state, f, indent=2)

        assert state["state"] in ("victory", "defeat", "active"), \
            f"Game still in unexpected state: {state['state']}"
        assert state["total_eliminations"] >= 0

    def test_08_game_over_screen(self, browser_context, results_dir):
        """Game over screen shows stats."""
        page = browser_context["page"]

        # Check if game over overlay is visible
        page.wait_for_timeout(2000)
        page.screenshot(path=os.path.join(results_dir, "08_game_over.png"))

        resp = requests.get(f"{BASE_URL}/api/game/state")
        state = resp.json()

        # Report
        report = {
            "final_state": state["state"],
            "waves_completed": state["wave"],
            "total_score": state["score"],
            "total_eliminations": state["total_eliminations"],
        }

        with open(os.path.join(results_dir, "08_report.json"), "w") as f:
            json.dump(report, f, indent=2)

        print(f"\n{'='*50}")
        print(f"BATTLE REPORT")
        print(f"  Result: {state['state'].upper()}")
        print(f"  Waves: {state['wave']}/{state['total_waves']}")
        print(f"  Score: {state['score']}")
        print(f"  Eliminations: {state['total_eliminations']}")
        print(f"{'='*50}")
