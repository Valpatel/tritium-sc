# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for engine.intelligence.correlation_learner module."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from engine.intelligence.correlation_learner import (
    CorrelationLearner,
    LearnedStrategy,
    _extract_features,
    _static_predict,
)


class TestStaticPredict:
    def test_returns_tuple(self):
        prob, conf = _static_predict({"distance": 1.0})
        assert isinstance(prob, float)
        assert isinstance(conf, float)
        assert 0.0 <= prob <= 1.0
        assert 0.0 <= conf <= 1.0

    def test_empty_features(self):
        prob, conf = _static_predict({})
        assert 0.0 <= prob <= 1.0

    def test_high_distance_lower(self):
        p_close, _ = _static_predict({"distance": 0.1})
        p_far, _ = _static_predict({"distance": 100.0})
        assert p_close > p_far


class TestExtractFeatures:
    def test_basic_extraction(self):
        class FakeTarget:
            def __init__(self, pos, source, asset_type, last_seen):
                self.position = pos
                self.source = source
                self.asset_type = asset_type
                self.last_seen = last_seen
                self.rssi = -60

        a = FakeTarget((0.0, 0.0), "ble", "phone", 100.0)
        b = FakeTarget((3.0, 4.0), "yolo", "person", 101.0)

        features = _extract_features(a, b)
        assert abs(features["distance"] - 5.0) < 0.01
        assert features["device_type_match"] == 1.0  # Cross-sensor
        assert features["time_gap"] == 1.0
        # Wave 150: verify new features are present
        assert "spatial" in features
        assert "temporal" in features
        assert "primary_confidence" in features
        assert "secondary_confidence" in features
        assert "source_pair" in features
        assert features["source_pair"] == 1.0  # ble+yolo = highest

    def test_same_source(self):
        class FakeTarget:
            def __init__(self):
                self.position = (0.0, 0.0)
                self.source = "ble"
                self.asset_type = "phone"
                self.last_seen = 100.0
                self.rssi = -50

        a = FakeTarget()
        b = FakeTarget()
        features = _extract_features(a, b)
        assert features["device_type_match"] == 0.3  # Same type, same source (semantic match)


class TestCorrelationLearner:
    def test_init_no_store(self):
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            assert not learner.is_trained
            assert learner.accuracy == 0.0

    def test_get_status(self):
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            status = learner.get_status()
            assert "trained" in status
            assert "accuracy" in status
            assert "sklearn_available" in status

    def test_train_no_store(self):
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            result = learner.train()
            assert not result["success"]
            assert "No training store" in result["error"]

    def test_train_insufficient_data(self):
        mock_store = MagicMock()
        mock_store.get_correlation_data.return_value = [
            {"features": {"distance": 1.0}, "outcome": "correct"}
        ]  # Only 1 example, need 10+

        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=mock_store,
                model_path=f"{td}/model.pkl",
            )
            result = learner.train()
            assert not result["success"]
            # May fail due to insufficient data OR sklearn not available
            assert "Insufficient" in result.get("error", "") or "scikit" in result.get("error", "").lower()

    def test_predict_without_model(self):
        with tempfile.TemporaryDirectory() as td:
            learner = CorrelationLearner(
                training_store=None,
                model_path=f"{td}/model.pkl",
            )
            prob, conf = learner.predict({"distance": 1.0, "co_movement": 0.5})
            assert 0.0 <= prob <= 1.0
            assert 0.0 <= conf <= 1.0


class TestLearnedStrategy:
    def test_name(self):
        learner = MagicMock()
        learner.predict.return_value = (0.7, 0.8)
        learner.is_trained = True

        strategy = LearnedStrategy(learner)
        assert strategy.name == "learned"

    def test_evaluate(self):
        learner = MagicMock()
        learner.predict.return_value = (0.85, 0.9)
        learner.is_trained = True

        strategy = LearnedStrategy(learner)

        class FakeTarget:
            def __init__(self):
                self.position = (0.0, 0.0)
                self.source = "ble"
                self.asset_type = "phone"
                self.last_seen = 100.0
                self.rssi = -50

        score = strategy.evaluate(FakeTarget(), FakeTarget())
        assert score.strategy_name == "learned"
        assert 0.0 <= score.score <= 1.0
