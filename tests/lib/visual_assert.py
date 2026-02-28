# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Three-layer visual verification: OpenCV + structured LLM + API cross-validation.

Verification strategy:
  - Layer 1 (OpenCV): Deterministic pixel assertions. MUST pass.
  - Layer 2 (LLM): Majority-vote structured queries. Advisory when OpenCV+API agree.
  - Layer 3 (API): Ground truth state. MUST pass.

LLM reliability note (validated 2026-02-20):
  llava:7b has 20-83% false negative rate on dark/neon backgrounds.
  Single-shot queries are unreliable. Majority vote (3 calls, 2 must agree)
  reduces false negatives to ~4-12%. Even so, LLM failures do NOT block
  when OpenCV AND API both pass — they are logged for human review.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import requests

# BGR color constants from cybercore.css / war-fx.js
FRIENDLY_GREEN = (161, 255, 5)    # #05ffa1
HOSTILE_RED    = (109, 42, 255)   # #ff2a6d
CYAN_PRIMARY   = (255, 240, 0)    # #00f0ff
YELLOW_UNKNOWN = (10, 238, 252)   # #fcee0a
VOID_BLACK     = (15, 10, 10)     # #0a0a0f
DARK_BG        = (26, 18, 18)     # #12121a

VISION_MODEL = "llava:7b"
LLM_VOTE_COUNT = 3  # number of LLM calls for majority vote


class VisualAssert:
    """Three-layer visual verification: OpenCV + structured LLM + API."""

    def __init__(self, fleet, db, run_id: int, server_url: str = "http://localhost:8765"):
        self.fleet = fleet
        self.db = db
        self.run_id = run_id
        self.server_url = server_url
        self._last_llm_responses: list[dict] = []

    # -- Layer 1: OpenCV pixel assertions --

    def assert_color_present(self, img: np.ndarray, bgr: tuple, tolerance: int = 40, min_pixels: int = 50) -> bool:
        """Check if enough pixels match the target BGR color within tolerance."""
        lower = np.array([max(0, c - tolerance) for c in bgr], dtype=np.uint8)
        upper = np.array([min(255, c + tolerance) for c in bgr], dtype=np.uint8)
        mask = cv2.inRange(img, lower, upper)
        return int(cv2.countNonZero(mask)) >= min_pixels

    def count_color_blobs(self, img: np.ndarray, bgr: tuple, tolerance: int = 40, min_area: int = 20) -> int:
        """Count distinct blobs of a specific color."""
        lower = np.array([max(0, c - tolerance) for c in bgr], dtype=np.uint8)
        upper = np.array([min(255, c + tolerance) for c in bgr], dtype=np.uint8)
        mask = cv2.inRange(img, lower, upper)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return sum(1 for c in contours if cv2.contourArea(c) >= min_area)

    def assert_region_not_blank(self, img: np.ndarray, x: int, y: int, w: int, h: int, threshold: int = 10) -> bool:
        """Check if a region has non-trivial content (not all near-black)."""
        region = img[y:y+h, x:x+w]
        if region.size == 0:
            return False
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) > threshold

    def assert_region_has_text(self, img: np.ndarray, x: int, y: int, w: int, h: int) -> bool:
        """Check if a region has text-like content (high edge density)."""
        region = img[y:y+h, x:x+w]
        if region.size == 0:
            return False
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = cv2.countNonZero(edges) / edges.size
        return edge_density > 0.03  # text regions typically have >3% edge density

    # -- Layer 2: Structured LLM queries (majority vote) --

    def _vote_yes_no(self, image_path: Path, prompt: str) -> tuple[bool, int, int, list[dict]]:
        """Run majority vote YES/NO. Returns (result, yes_count, total, raw_responses).

        Each entry in raw_responses is {"response": str, "host": str, "elapsed_ms": float}.
        """
        yes_count = 0
        raw_responses: list[dict] = []
        for _ in range(LLM_VOTE_COUNT):
            try:
                resp = self.fleet.generate(VISION_MODEL, prompt, image_path=image_path)
                raw_responses.append(resp)
                if "yes" in resp["response"].strip().lower()[:20]:
                    yes_count += 1
            except Exception:
                pass
        return (yes_count > LLM_VOTE_COUNT // 2, yes_count, LLM_VOTE_COUNT, raw_responses)

    def ask_yes_no(self, image_path: Path, question: str) -> bool:
        """Ask a yes/no question with majority vote."""
        prompt = (f"{question}\n\nAnswer with EXACTLY one word: YES or NO. "
                  f"Do not explain. Just YES or NO.")
        result, _, _, raw = self._vote_yes_no(image_path, prompt)
        self._last_llm_responses = raw
        return result

    def ask_count(self, image_path: Path, question: str) -> int:
        """Ask a counting question (median of multiple calls for stability)."""
        prompt = (f"{question}\n\nAnswer with EXACTLY one number. "
                  f"If you cannot count them, answer 0. Just the number, nothing else.")
        counts = []
        raw_responses: list[dict] = []
        for _ in range(LLM_VOTE_COUNT):
            try:
                resp = self.fleet.generate(VISION_MODEL, prompt, image_path=image_path)
                raw_responses.append(resp)
                text = resp["response"].strip()
                match = re.search(r'\d+', text)
                if match:
                    counts.append(int(match.group()))
            except Exception:
                pass
        self._last_llm_responses = raw_responses
        if not counts:
            return 0
        counts.sort()
        return counts[len(counts) // 2]  # median

    def ask_choice(self, image_path: Path, question: str, choices: list[str]) -> str:
        """Ask a multiple-choice question (majority vote)."""
        choices_str = ", ".join(choices)
        prompt = (f"{question}\n\nChoose EXACTLY one of: {choices_str}\n"
                  f"Answer with just the choice, nothing else.")
        votes: dict[str, int] = {c: 0 for c in choices}
        for _ in range(LLM_VOTE_COUNT):
            try:
                resp = self.fleet.generate(VISION_MODEL, prompt, image_path=image_path)
                text = resp["response"].strip().lower()
                for choice in choices:
                    if choice.lower() in text:
                        votes[choice] += 1
                        break
            except Exception:
                pass
        winner = max(votes, key=lambda k: votes[k])
        return winner if votes[winner] > 0 else choices[0]

    def ask_describe(self, image_path: Path, question: str) -> str:
        """Free-form description for reporting (single call, not voted)."""
        try:
            resp = self.fleet.generate(VISION_MODEL, question, image_path=image_path)
            return resp["response"]
        except Exception:
            return "(LLM unavailable)"

    # -- Layer 3: API cross-validation --

    def api_get(self, path: str) -> dict | None:
        """Safe GET request to the server API."""
        try:
            resp = requests.get(f"{self.server_url}{path}", timeout=5)
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    # -- Combined verification --

    def verify(self, test_name: str, phase: str, image_path: Path, img: np.ndarray,
               opencv_checks: list[tuple[str, Callable]],
               llm_checks: list[tuple[str, Callable]],
               api_checks: list[tuple[str, Callable]]) -> dict:
        """Run all three layers and return structured results.

        Pass logic:
          - OpenCV checks MUST all pass (deterministic, reliable)
          - API checks MUST all pass (ground truth)
          - LLM checks are advisory: logged but do NOT block when
            OpenCV AND API both pass. This accounts for llava:7b's
            20-83% false negative rate on dark/neon backgrounds.
          - If OpenCV OR API fails, LLM failures also count (all layers
            need to agree something is wrong).
        """
        results: dict[str, Any] = {"test_name": test_name, "phase": phase, "layers": {}}

        # Layer 1: OpenCV (MUST pass)
        opencv_results: dict[str, bool] = {}
        opencv_pass = True
        for name, check_fn in opencv_checks:
            try:
                opencv_results[name] = check_fn()
                if not opencv_results[name]:
                    opencv_pass = False
            except Exception:
                opencv_results[name] = False
                opencv_pass = False
        results["layers"]["opencv"] = opencv_results

        # Layer 2: LLM (advisory when deterministic layers agree)
        llm_results: dict[str, bool] = {}
        llm_response_texts: list[str] = []
        llm_host = ""
        llm_total_ms = 0.0
        llm_pass = True
        for name, check_fn in llm_checks:
            try:
                llm_results[name] = check_fn()
                if not llm_results[name]:
                    llm_pass = False
            except Exception:
                llm_results[name] = False
                llm_pass = False
        results["layers"]["llm"] = llm_results

        # Collect LLM response details from _last_llm_responses if available
        if hasattr(self, "_last_llm_responses") and self._last_llm_responses:
            llm_response_texts = [r.get("response", "") for r in self._last_llm_responses]
            if self._last_llm_responses:
                llm_host = self._last_llm_responses[0].get("host", "")
                llm_total_ms = sum(r.get("elapsed_ms", 0) for r in self._last_llm_responses)

        # Layer 3: API (MUST pass)
        api_results: dict[str, bool] = {}
        api_pass = True
        for name, check_fn in api_checks:
            try:
                api_results[name] = check_fn()
                if not api_results[name]:
                    api_pass = False
            except Exception:
                api_results[name] = False
                api_pass = False
        results["layers"]["api"] = api_results

        # Tiered pass logic
        if opencv_pass and api_pass:
            # Deterministic layers agree — LLM is advisory only
            overall_pass = True
            if not llm_pass:
                results["llm_advisory"] = "LLM disagreed but OpenCV+API passed"
        else:
            # At least one deterministic layer failed — require ALL
            overall_pass = opencv_pass and api_pass and llm_pass

        results["passed"] = overall_pass

        # Record in DB if available
        if self.db is not None:
            llm_text = " | ".join(llm_response_texts) if llm_response_texts else json.dumps(llm_results)
            self.db.record_screenshot(
                self.run_id, test_name, phase, str(image_path),
                opencv_results, llm_text, llm_host, llm_total_ms, api_results,
            )

        return results
