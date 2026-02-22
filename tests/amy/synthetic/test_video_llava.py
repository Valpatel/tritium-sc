"""LLaVA structured visual validation of synthetic video frames.

Uses Ollama's llava:7b for visual verification with majority vote.
Skips gracefully if Ollama is unavailable.

Each scene type gets YES/NO questions validated with 3 calls, 2 must agree.

LLM reliability note (consistent with tests/lib/visual_assert.py):
  llava:7b has 20-83% false negative rate on dark/neon backgrounds.
  These tests record structured responses for reporting but do NOT
  hard-assert on LLM agreement. They issue pytest.warns when LLaVA
  disagrees. The OpenCV tests (test_video_opencv.py) are the
  deterministic ground truth; LLaVA results are advisory.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import cv2
import numpy as np
import pytest

from amy.synthetic.video_gen import (
    Explosion,
    Projectile,
    render_battle_scene,
    render_bird_eye,
    render_neighborhood,
    render_street_cam,
)
from amy.synthetic.video_library import SyntheticVideoLibrary, _make_demo_targets


pytestmark = pytest.mark.ml

SEED = 42
RESOLUTION = (640, 480)
VISION_MODEL = "llava:7b"
VOTE_COUNT = 3
RESULTS_DIR = Path(__file__).parent.parent / ".test-results"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _check_ollama():
    """Check if Ollama is available with llava:7b."""
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code != 200:
            return False
        models = [m["name"] for m in resp.json().get("models", [])]
        return any(m.startswith("llava") for m in models)
    except Exception:
        return False


@pytest.fixture(scope="module")
def ollama_available():
    """Skip all tests if Ollama not available with llava model."""
    if not _check_ollama():
        pytest.skip("Ollama with llava:7b not available")
    return True


@pytest.fixture(scope="module")
def fleet(ollama_available):
    """Get OllamaFleet instance."""
    from tests.lib.ollama_fleet import OllamaFleet
    f = OllamaFleet(auto_discover=True)
    if not f.hosts_with_model(VISION_MODEL):
        pytest.skip(f"No host has {VISION_MODEL}")
    return f


@pytest.fixture(scope="module")
def llava_results():
    """Collect LLaVA responses for reporting."""
    results: dict[str, dict] = {}
    yield results

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / "llava-report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_frame(frame: np.ndarray, name: str) -> Path:
    """Save a frame to a temp PNG and return the path."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"llava_{name}.png"
    cv2.imwrite(str(path), frame)
    return path


def _majority_vote(fleet, image_path: Path, question: str) -> tuple[bool, list[str]]:
    """Run majority vote YES/NO query. Returns (result, raw_responses)."""
    prompt = (
        f"{question}\n\n"
        "Answer with EXACTLY one word: YES or NO. "
        "Do not explain. Just YES or NO."
    )
    yes_count = 0
    responses = []
    for _ in range(VOTE_COUNT):
        try:
            resp = fleet.generate(VISION_MODEL, prompt, image_path=image_path)
            text = resp["response"].strip()
            responses.append(text)
            if "yes" in text.lower()[:20]:
                yes_count += 1
        except Exception as e:
            responses.append(f"[error: {e}]")

    return (yes_count > VOTE_COUNT // 2, responses)


def _assert_advisory(result: bool, scene: str, question: str, responses: list[str]):
    """Advisory assertion: warn on LLM disagreement, do not fail.

    llava:7b has documented 20-83% false negative rate on dark/neon
    backgrounds. LLM checks are recorded for human review but do not
    block test suite progression.
    """
    if not result:
        warnings.warn(
            f"LLaVA advisory: {scene} - '{question}' got NO majority. "
            f"Responses: {responses}. "
            f"This is expected with llava:7b on dark/neon backgrounds.",
            UserWarning,
            stacklevel=2,
        )


# ===========================================================================
# Bird Eye Scene
# ===========================================================================


class TestBirdEyeLLaVA:
    """LLaVA validation of bird-eye scene."""

    def test_is_top_down_tactical_view(self, fleet, llava_results):
        demo = _make_demo_targets("bird_eye", 25, 50, SEED)
        frame = render_bird_eye(
            resolution=RESOLUTION, seed=SEED, timestamp="12:00:00", **demo,
        )
        path = _save_frame(frame, "bird_eye")

        result, responses = _majority_vote(
            fleet, path, "Is this a top-down tactical or map view?"
        )
        llava_results["bird_eye_top_down"] = {
            "passed": result,
            "responses": responses,
        }
        _assert_advisory(result, "bird_eye", "top-down tactical view", responses)

    def test_colored_dots_on_dark_background(self, fleet, llava_results):
        demo = _make_demo_targets("bird_eye", 25, 50, SEED)
        frame = render_bird_eye(
            resolution=RESOLUTION, seed=SEED, timestamp="12:00:00", **demo,
        )
        path = _save_frame(frame, "bird_eye_dots")

        result, responses = _majority_vote(
            fleet, path,
            "Are there colored dots or shapes on a dark background?"
        )
        llava_results["bird_eye_colored_dots"] = {
            "passed": result,
            "responses": responses,
        }
        _assert_advisory(result, "bird_eye", "colored dots on dark background", responses)


# ===========================================================================
# Street Cam Scene
# ===========================================================================


class TestStreetCamLLaVA:
    """LLaVA validation of street cam scene."""

    def test_is_street_or_security_camera(self, fleet, llava_results):
        demo = _make_demo_targets("street_cam", 10, 50, SEED)
        frame = render_street_cam(
            resolution=RESOLUTION, seed=SEED, timestamp="2026-02-20 12:00:00",
            camera_name="CAM-01", **demo,
        )
        path = _save_frame(frame, "street_cam")

        result, responses = _majority_vote(
            fleet, path,
            "Is this a street-level or security camera view?"
        )
        llava_results["street_cam_security"] = {
            "passed": result,
            "responses": responses,
        }
        _assert_advisory(result, "street_cam", "street/security camera view", responses)


# ===========================================================================
# Battle Scene
# ===========================================================================


class TestBattleLLaVA:
    """LLaVA validation of battle scene."""

    def test_projectile_trails_or_explosions(self, fleet, llava_results):
        demo = _make_demo_targets("battle", 15, 50, SEED)
        frame = render_battle_scene(
            resolution=RESOLUTION, seed=SEED, timestamp="09:00:00", **demo,
        )
        path = _save_frame(frame, "battle")

        result, responses = _majority_vote(
            fleet, path,
            "Are there bright projectile trails or explosions visible?"
        )
        llava_results["battle_projectiles"] = {
            "passed": result,
            "responses": responses,
            "note": "Battle projectiles depend on frame index. Advisory only.",
        }
        _assert_advisory(result, "battle", "projectile trails or explosions", responses)


# ===========================================================================
# Neighborhood Scene
# ===========================================================================


class TestNeighborhoodLLaVA:
    """LLaVA validation of neighborhood scene."""

    def test_is_quiet_neighborhood(self, fleet, llava_results):
        demo = _make_demo_targets("neighborhood", 10, 50, SEED)
        frame = render_neighborhood(
            resolution=RESOLUTION, seed=SEED, timestamp="2026-02-20 22:00:00",
            camera_name="NBHD-01", **demo,
        )
        path = _save_frame(frame, "neighborhood")

        result, responses = _majority_vote(
            fleet, path,
            "Is this a quiet neighborhood scene with buildings?"
        )
        llava_results["neighborhood_quiet"] = {
            "passed": result,
            "responses": responses,
        }
        _assert_advisory(result, "neighborhood", "quiet neighborhood with buildings", responses)
