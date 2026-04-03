# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for RL metrics wiring into CorrelationLearner.

Verifies that the CorrelationLearner records training runs and
predictions in its RLMetrics tracker, making them available to the
/api/intelligence/rl-metrics endpoint.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from engine.intelligence.correlation_learner import (
    CorrelationLearner,
    FEATURE_NAMES,
)
from tritium_lib.intelligence.rl_metrics import RLMetrics


class TestRLMetricsWiring:
    """Verify CorrelationLearner has an _rl_metrics attribute and records to it."""

    def test_learner_has_rl_metrics(self):
        """CorrelationLearner must expose _rl_metrics for the API endpoint."""
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            assert hasattr(learner, "_rl_metrics")
            assert isinstance(learner._rl_metrics, RLMetrics)

    def test_predict_records_to_rl_metrics(self):
        """Predictions via static fallback should record in _rl_metrics."""
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            assert learner._rl_metrics.get_status()["total_predictions"] == 0

            # Make a prediction (uses static fallback since no model)
            learner.predict({"distance": 1.0, "co_movement": 0.5})

            status = learner._rl_metrics.get_status()
            assert status["total_predictions"] == 1

    def test_multiple_predictions_accumulate(self):
        """Multiple predictions should accumulate in rl_metrics."""
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )

            for i in range(5):
                learner.predict({"distance": float(i), "signal_pattern": 0.8})

            status = learner._rl_metrics.get_status()
            assert status["total_predictions"] == 5

    def test_record_feedback_updates_rl_metrics(self):
        """record_feedback should update correct/incorrect counters."""
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            # Need to record training first to create the model entry
            learner._rl_metrics.record_training(
                accuracy=0.8, training_count=100, model_name="correlation",
            )

            learner.record_feedback(correct=True)
            learner.record_feedback(correct=False)
            learner.record_feedback(correct=True)

            status = learner._rl_metrics.get_status()
            assert status["total_correct"] == 2
            assert status["total_incorrect"] == 1

    def test_export_serializable(self):
        """Export from the wired RLMetrics should be JSON-serializable."""
        import json

        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            learner.predict({"distance": 2.0})
            learner.predict({"distance": 0.5, "co_movement": 0.9})

            export = learner._rl_metrics.export()
            json_str = json.dumps(export)
            assert len(json_str) > 10
            parsed = json.loads(json_str)
            assert parsed["total_predictions"] == 2

    def test_rl_metrics_status_has_prediction_distribution(self):
        """The status should include prediction distribution data."""
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            # Make predictions with different features
            learner.predict({"distance": 0.1})
            learner.predict({"distance": 100.0})

            status = learner._rl_metrics.get_status()
            dist = status["prediction_distribution"]
            assert dist["total"] == 2
            assert sum(dist["probability_histogram"]) == 2

    def test_get_status_returns_model_name(self):
        """Per-model tracking should use the learner's name."""
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            # Record a fake training run to establish the model entry
            learner._rl_metrics.record_training(
                accuracy=0.85, training_count=200,
                feature_importance={"distance": 0.3},
                model_name="correlation",
            )
            learner.predict({"distance": 1.0})

            status = learner._rl_metrics.get_status()
            assert "correlation" in status["models"]
            model_info = status["models"]["correlation"]
            assert model_info["total_predictions"] == 1
            assert model_info["last_accuracy"] == 0.85
