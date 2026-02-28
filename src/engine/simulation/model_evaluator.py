# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ModelEvaluator — benchmarks local Ollama models for scenario generation.

Evaluates available models on:
- Speed (response time for a standard prompt)
- JSON compliance (does the model return valid JSON?)
- Output quality (length and richness)
- Model size (smaller preferred for latency)

Provides recommendations: fast (quick games), quality (rich scenarios), balanced.
Results are cached to avoid re-evaluation.
"""

from __future__ import annotations

import json
import re
import time
from typing import Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore


# -- Model size categories ---------------------------------------------------

_SIZE_PATTERNS = [
    (re.compile(r'(\d+\.?\d*)b', re.IGNORECASE), lambda m: float(m.group(1))),
]


def _extract_param_count(model_name: str) -> float:
    """Extract parameter count in billions from model name."""
    for pattern, extractor in _SIZE_PATTERNS:
        match = pattern.search(model_name)
        if match:
            return extractor(match)
    return 7.0  # Default assumption


def categorize_model(model_name: str) -> str:
    """Categorize a model by parameter count."""
    params = _extract_param_count(model_name)
    if params < 2:
        return "tiny"
    elif params < 6:
        return "small"
    elif params < 10:
        return "medium"
    elif params < 20:
        return "large"
    else:
        return "xlarge"


class ModelEvaluator:
    """Evaluates and ranks available Ollama models for scenario generation."""

    DEFAULT_MODEL = "gemma3:4b"

    # Standard test prompt for evaluation
    TEST_PROMPT = (
        "Generate a brief scenario for a neighborhood security battle. "
        'Respond in JSON: {"reason": "...", "urgency": "high|medium|low"}'
    )

    def __init__(self, ollama_host: str = "http://localhost:11434") -> None:
        self._host = ollama_host
        self._cache: dict[str, dict] = {}

    def compute_score(
        self,
        response_time: float,
        json_valid: bool,
        output_length: int = 0,
        size_gb: float = 0.0,
    ) -> float:
        """Compute a 0-1 quality score for a model evaluation result.

        Weights:
        - JSON validity: 40% (critical — must return parseable JSON)
        - Speed: 30% (faster = better, normalized to 0-30s range)
        - Output quality: 20% (longer, richer output)
        - Size efficiency: 10% (smaller models preferred)
        """
        json_score = 1.0 if json_valid else 0.0
        speed_score = max(0, 1.0 - (response_time / 30.0))
        length_score = min(1.0, output_length / 300.0) if output_length > 0 else 0.5
        size_score = max(0, 1.0 - (size_gb / 50.0)) if size_gb > 0 else 0.5

        return (
            json_score * 0.4 +
            speed_score * 0.3 +
            length_score * 0.2 +
            size_score * 0.1
        )

    def rank_models(self, results: list[dict]) -> list[dict]:
        """Rank evaluation results by composite score.

        Args:
            results: List of dicts with model, response_time, json_valid, etc.

        Returns:
            Sorted list (best first).
        """
        for r in results:
            if "score" not in r:
                r["score"] = self.compute_score(
                    response_time=r.get("response_time", 30.0),
                    json_valid=r.get("json_valid", False),
                    output_length=r.get("output_length", 0),
                    size_gb=r.get("size_gb", 0.0),
                )
        return sorted(results, key=lambda r: r["score"], reverse=True)

    def recommend(self, prefer: str = "balanced") -> str:
        """Recommend a model based on cached evaluation results.

        Args:
            prefer: "fast" (lowest latency), "quality" (highest score),
                    or "balanced" (default).

        Returns:
            Model name string.
        """
        if not self._cache:
            return self.DEFAULT_MODEL

        items = [
            {
                "model": model,
                "response_time": data.get("response_time", 30.0),
                "json_valid": data.get("json_valid", False),
                "score": data.get("score", 0.0),
            }
            for model, data in self._cache.items()
        ]

        if prefer == "fast":
            # Fastest JSON-compliant model
            valid = [i for i in items if i["json_valid"]]
            if valid:
                return min(valid, key=lambda x: x["response_time"])["model"]
        elif prefer == "quality":
            # Highest score
            return max(items, key=lambda x: x["score"])["model"]

        # Balanced: highest score among models under 10s
        fast_enough = [i for i in items if i["response_time"] < 10.0 and i["json_valid"]]
        if fast_enough:
            return max(fast_enough, key=lambda x: x["score"])["model"]

        # Fall back to highest score overall
        if items:
            return max(items, key=lambda x: x["score"])["model"]

        return self.DEFAULT_MODEL

    def evaluate_model(self, model_name: str) -> dict:
        """Evaluate a single model by sending the test prompt.

        Returns dict with: model, response_time, json_valid, output_length, score.
        """
        if requests is None:
            return {
                "model": model_name,
                "response_time": 999.0,
                "json_valid": False,
                "output_length": 0,
                "score": 0.0,
                "error": "requests library not available",
            }

        start = time.monotonic()
        try:
            resp = requests.post(
                f"{self._host}/api/chat",
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "Respond with valid JSON only."},
                        {"role": "user", "content": self.TEST_PROMPT},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.7, "num_predict": 256},
                },
                timeout=60,
            )
            elapsed = time.monotonic() - start
            resp.raise_for_status()
            data = resp.json()
            text = data.get("message", {}).get("content", "")

            # Try parsing JSON
            json_valid = False
            try:
                # Strip markdown code blocks
                clean = text.strip()
                if clean.startswith("```"):
                    clean = re.sub(r'```(?:json)?\s*\n?', '', clean)
                    clean = clean.replace('```', '').strip()
                json.loads(clean)
                json_valid = True
            except (json.JSONDecodeError, ValueError):
                # Try finding JSON object
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    try:
                        json.loads(match.group())
                        json_valid = True
                    except (json.JSONDecodeError, ValueError):
                        pass

            result = {
                "model": model_name,
                "response_time": round(elapsed, 2),
                "json_valid": json_valid,
                "output_length": len(text),
                "category": categorize_model(model_name),
            }
            result["score"] = self.compute_score(
                response_time=elapsed,
                json_valid=json_valid,
                output_length=len(text),
            )
            self._cache[model_name] = result
            return result

        except Exception as e:
            elapsed = time.monotonic() - start
            result = {
                "model": model_name,
                "response_time": round(elapsed, 2),
                "json_valid": False,
                "output_length": 0,
                "score": 0.0,
                "error": str(e),
            }
            self._cache[model_name] = result
            return result

    def evaluate_all(
        self,
        models: list[str] | None = None,
        max_size: str = "large",
    ) -> list[dict]:
        """Evaluate multiple models.

        Args:
            models: List of model names (or auto-discover from Ollama).
            max_size: Maximum size category to test ("tiny", "small", "medium", "large", "xlarge").

        Returns:
            Ranked list of evaluation results.
        """
        if models is None:
            models = self._discover_models(max_size)

        results = []
        for model in models:
            result = self.evaluate_model(model)
            results.append(result)

        return self.rank_models(results)

    def _discover_models(self, max_size: str = "large") -> list[str]:
        """Discover available models from Ollama, filtered by size."""
        if requests is None:
            return [self.DEFAULT_MODEL]

        size_order = ["tiny", "small", "medium", "large", "xlarge"]
        max_idx = size_order.index(max_size) if max_size in size_order else 3

        try:
            resp = requests.get(f"{self._host}/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = []
                for m in data.get("models", []):
                    name = m["name"]
                    cat = categorize_model(name)
                    if size_order.index(cat) <= max_idx:
                        # Skip vision-only models
                        if "vision" not in name and "llava" not in name and "moondream" not in name:
                            models.append(name)
                return models or [self.DEFAULT_MODEL]
        except Exception:
            pass

        return [self.DEFAULT_MODEL]

    def get_cache(self) -> dict[str, dict]:
        """Get cached evaluation results."""
        return dict(self._cache)
