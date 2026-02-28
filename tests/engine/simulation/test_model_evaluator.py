# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for model evaluation and recommendation system.

The MissionDirector can evaluate available Ollama models to determine
which are best suited for scenario generation. Factors:
- Speed (response time)
- JSON compliance (does the model return valid JSON?)
- Creative quality (variety and richness of output)
- Size (smaller models preferred for latency)

Results are cached so evaluation only runs once.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestModelEvaluatorImport:
    def test_import(self):
        from engine.simulation.model_evaluator import ModelEvaluator
        assert ModelEvaluator is not None

    def test_create(self):
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        assert ev is not None


class TestModelRanking:
    """Test model ranking criteria."""

    def test_rank_by_speed(self):
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        results = [
            {"model": "gemma3:4b", "response_time": 2.5, "json_valid": True},
            {"model": "qwen2.5:7b", "response_time": 5.0, "json_valid": True},
            {"model": "qwen2.5:0.5b", "response_time": 0.8, "json_valid": False},
        ]
        ranked = ev.rank_models(results)
        # JSON-valid models should rank higher
        assert ranked[0]["model"] != "qwen2.5:0.5b"

    def test_rank_penalizes_invalid_json(self):
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        results = [
            {"model": "fast_bad", "response_time": 0.5, "json_valid": False},
            {"model": "slow_good", "response_time": 10.0, "json_valid": True},
        ]
        ranked = ev.rank_models(results)
        assert ranked[0]["model"] == "slow_good"

    def test_rank_prefers_smaller_models_when_equal(self):
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        results = [
            {"model": "big:27b", "response_time": 3.0, "json_valid": True, "size_gb": 17.0},
            {"model": "small:4b", "response_time": 3.0, "json_valid": True, "size_gb": 3.3},
        ]
        ranked = ev.rank_models(results)
        assert ranked[0]["model"] == "small:4b"


class TestModelRecommendation:
    """Test model recommendation for different tasks."""

    def test_recommend_returns_model_name(self):
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        # Set cached results
        ev._cache = {
            "gemma3:4b": {"response_time": 2.5, "json_valid": True, "score": 0.8},
            "qwen2.5:7b": {"response_time": 5.0, "json_valid": True, "score": 0.7},
        }
        rec = ev.recommend()
        assert isinstance(rec, str)
        assert len(rec) > 0

    def test_recommend_fast(self):
        """Recommend fastest JSON-compliant model."""
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        ev._cache = {
            "gemma3:4b": {"response_time": 2.5, "json_valid": True, "score": 0.8},
            "qwen2.5:0.5b": {"response_time": 0.3, "json_valid": True, "score": 0.9},
        }
        rec = ev.recommend(prefer="fast")
        assert rec == "qwen2.5:0.5b"

    def test_recommend_quality(self):
        """Recommend highest-quality model."""
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        ev._cache = {
            "gemma3:4b": {"response_time": 2.5, "json_valid": True, "score": 0.8},
            "gemma3:12b": {"response_time": 8.0, "json_valid": True, "score": 0.95},
        }
        rec = ev.recommend(prefer="quality")
        assert rec == "gemma3:12b"

    def test_recommend_default_no_cache(self):
        """With no evaluation, recommend default model."""
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        rec = ev.recommend()
        assert rec == "gemma3:4b"  # Default fallback


class TestEvaluationResult:
    """Test evaluation result format."""

    def test_result_has_required_fields(self):
        result = {
            "model": "gemma3:4b",
            "response_time": 2.5,
            "json_valid": True,
            "output_length": 150,
            "score": 0.8,
        }
        assert "model" in result
        assert "response_time" in result
        assert "json_valid" in result
        assert "score" in result

    def test_score_range(self):
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        # Score should be 0-1
        score = ev.compute_score(response_time=2.5, json_valid=True, output_length=150)
        assert 0.0 <= score <= 1.0

    def test_invalid_json_lowers_score(self):
        from engine.simulation.model_evaluator import ModelEvaluator
        ev = ModelEvaluator()
        good = ev.compute_score(response_time=2.5, json_valid=True, output_length=150)
        bad = ev.compute_score(response_time=2.5, json_valid=False, output_length=150)
        assert good > bad


class TestModelCategories:
    """Test categorization of models by capability."""

    def test_categorize_by_size(self):
        from engine.simulation.model_evaluator import categorize_model
        assert categorize_model("qwen2.5:0.5b") == "tiny"
        assert categorize_model("gemma3:4b") == "small"
        assert categorize_model("qwen2.5:7b") == "medium"
        assert categorize_model("qwen2.5:14b") == "large"
        assert categorize_model("gemma3:27b") == "xlarge"

    def test_categorize_unknown(self):
        from engine.simulation.model_evaluator import categorize_model
        cat = categorize_model("unknown_model")
        assert cat in ("tiny", "small", "medium", "large", "xlarge", "unknown")
