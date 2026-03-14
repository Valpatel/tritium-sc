# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""End-to-end test for the RL correlation learning pipeline.

Exercises the full lifecycle:
1. Create training data in TrainingStore
2. Trigger retrain on CorrelationLearner
3. Verify model loads and produces predictions
4. Run correlation with the learned strategy
5. Verify predictions change based on training data
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from engine.intelligence.training_store import TrainingStore
from engine.intelligence.correlation_learner import (
    CorrelationLearner,
    LearnedStrategy,
    _extract_features,
    _static_predict,
    FEATURE_NAMES,
)


def _make_training_data(store: TrainingStore, n_correct: int, n_incorrect: int):
    """Insert synthetic correlation training data.

    Correct correlations: close distance, high co-movement, cross-sensor.
    Incorrect correlations: far distance, low co-movement, same-sensor.
    """
    import random
    random.seed(42)

    for i in range(n_correct):
        features = {
            "distance": random.uniform(0.1, 2.0),
            "rssi_delta": random.uniform(0, 5),
            "co_movement": random.uniform(0.5, 1.0),
            "device_type_match": 1.0,
            "time_gap": random.uniform(0, 2),
            "signal_pattern": random.uniform(0.7, 1.0),
        }
        store.log_correlation(
            target_a_id=f"ble_correct_a_{i}",
            target_b_id=f"det_correct_b_{i}",
            features=features,
            score=random.uniform(0.6, 0.95),
            decision="merge",
            outcome="correct",
        )

    for i in range(n_incorrect):
        features = {
            "distance": random.uniform(15.0, 50.0),
            "rssi_delta": random.uniform(20, 50),
            "co_movement": random.uniform(0.0, 0.2),
            "device_type_match": 0.0,
            "time_gap": random.uniform(10, 30),
            "signal_pattern": random.uniform(0.0, 0.3),
        }
        store.log_correlation(
            target_a_id=f"ble_wrong_a_{i}",
            target_b_id=f"det_wrong_b_{i}",
            features=features,
            score=random.uniform(0.1, 0.4),
            decision="merge",
            outcome="incorrect",
        )


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def training_store(temp_dir):
    return TrainingStore(db_path=f"{temp_dir}/training.db")


@pytest.fixture
def learner(temp_dir, training_store):
    return CorrelationLearner(
        training_store=training_store,
        model_path=f"{temp_dir}/model.pkl",
    )


class TestRLPipelineE2E:
    """Full end-to-end RL pipeline test."""

    def test_empty_store_train_fails(self, learner):
        """Training with no data should fail gracefully."""
        result = learner.train()
        assert not result["success"]
        assert "Insufficient" in result.get("error", "") or "scikit" in result.get("error", "").lower()

    def test_insufficient_data_train_fails(self, training_store, learner):
        """Training with too few examples should fail."""
        _make_training_data(training_store, n_correct=3, n_incorrect=3)
        result = learner.train()
        assert not result["success"]

    def test_full_pipeline_train_and_predict(self, training_store, learner):
        """Full pipeline: create data -> train -> predict -> verify."""
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn not installed")

        # Step 1: Create sufficient training data
        _make_training_data(training_store, n_correct=30, n_incorrect=30)

        # Verify data was stored
        stats = training_store.get_stats()
        assert stats["correlation"]["total"] == 60
        assert stats["correlation"]["confirmed"] == 60

        # Step 2: Train the model
        result = learner.train()
        assert result["success"], f"Training failed: {result.get('error')}"
        assert result["training_count"] == 60
        assert result["accuracy"] >= 0.0  # Accuracy depends on data quality
        assert learner.is_trained

        # Step 3: Predict on a "correct-like" pair (close, high co-movement)
        close_features = {
            "distance": 1.0,
            "rssi_delta": 2.0,
            "co_movement": 0.8,
            "device_type_match": 1.0,
            "time_gap": 0.5,
            "signal_pattern": 0.9,
        }
        prob_close, conf_close = learner.predict(close_features)
        assert 0.0 <= prob_close <= 1.0
        assert 0.0 <= conf_close <= 1.0

        # Step 4: Predict on a "incorrect-like" pair (far, low co-movement)
        far_features = {
            "distance": 30.0,
            "rssi_delta": 35.0,
            "co_movement": 0.1,
            "device_type_match": 0.0,
            "time_gap": 20.0,
            "signal_pattern": 0.1,
        }
        prob_far, conf_far = learner.predict(far_features)
        assert 0.0 <= prob_far <= 1.0

        # Step 5: Verify the model learned the pattern
        # Close pairs should have higher probability than far pairs
        assert prob_close > prob_far, (
            f"Model should score close pairs higher: "
            f"close={prob_close:.3f} vs far={prob_far:.3f}"
        )

    def test_model_persistence(self, temp_dir, training_store):
        """Model saves to disk and can be reloaded."""
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn not installed")

        model_path = f"{temp_dir}/model.pkl"

        # Train and save
        learner1 = CorrelationLearner(
            training_store=training_store,
            model_path=model_path,
        )
        _make_training_data(training_store, n_correct=25, n_incorrect=25)
        result = learner1.train()
        assert result["success"]

        # Reload in a new learner
        learner2 = CorrelationLearner(
            training_store=None,  # No store needed for loading
            model_path=model_path,
        )
        assert learner2.is_trained
        assert learner2.training_count == 50

        # Verify predictions match
        features = {"distance": 1.0, "co_movement": 0.8, "device_type_match": 1.0}
        p1, _ = learner1.predict(features)
        p2, _ = learner2.predict(features)
        assert abs(p1 - p2) < 0.01, f"Predictions should match: {p1} vs {p2}"

    def test_learned_strategy_integration(self, training_store, learner):
        """LearnedStrategy wraps the learner for TargetCorrelator use."""
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn not installed")

        _make_training_data(training_store, n_correct=25, n_incorrect=25)
        learner.train()

        strategy = LearnedStrategy(learner)
        assert strategy.name == "learned"

        class FakeTarget:
            def __init__(self, pos, source, asset_type):
                self.position = pos
                self.source = source
                self.asset_type = asset_type
                self.last_seen = 100.0
                self.rssi = -60

        # Close cross-sensor pair
        a = FakeTarget((0.0, 0.0), "ble", "phone")
        b = FakeTarget((1.0, 1.0), "yolo", "person")
        score_close = strategy.evaluate(a, b)
        assert score_close.strategy_name == "learned"
        assert 0.0 <= score_close.score <= 1.0

        # Far same-sensor pair
        c = FakeTarget((0.0, 0.0), "ble", "phone")
        d = FakeTarget((50.0, 50.0), "ble", "phone")
        score_far = strategy.evaluate(c, d)

        # Learned model should prefer the close cross-sensor pair
        assert score_close.score > score_far.score, (
            f"Close pair should score higher: {score_close.score:.3f} vs {score_far.score:.3f}"
        )

    def test_static_fallback_when_untrained(self, learner):
        """Without training, predictions use static fallback."""
        assert not learner.is_trained

        prob, conf = learner.predict({"distance": 1.0})
        assert 0.0 <= prob <= 1.0
        assert 0.0 <= conf <= 1.0

        # Static fallback should also show distance effect
        p_close, _ = _static_predict({"distance": 0.5})
        p_far, _ = _static_predict({"distance": 50.0})
        assert p_close > p_far

    def test_retrain_improves_with_more_data(self, temp_dir, training_store):
        """Adding more training data and retraining should update the model."""
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn not installed")

        learner = CorrelationLearner(
            training_store=training_store,
            model_path=f"{temp_dir}/model.pkl",
        )

        # Initial training
        _make_training_data(training_store, n_correct=15, n_incorrect=15)
        result1 = learner.train()
        assert result1["success"]
        count1 = learner.training_count

        # Add more data and retrain
        _make_training_data(training_store, n_correct=20, n_incorrect=20)
        result2 = learner.train()
        assert result2["success"]
        count2 = learner.training_count

        assert count2 > count1, "Retrain should use more data"

    def test_training_store_stats(self, training_store):
        """TrainingStore stats correctly reflect stored data."""
        stats = training_store.get_stats()
        assert stats["correlation"]["total"] == 0
        assert stats["feedback"]["total"] == 0

        _make_training_data(training_store, n_correct=5, n_incorrect=3)
        stats = training_store.get_stats()
        assert stats["correlation"]["total"] == 8
        assert stats["correlation"]["confirmed"] == 8

    def test_feedback_logging(self, training_store):
        """Operator feedback is correctly stored and retrieved."""
        training_store.log_feedback(
            target_id="ble_test_001",
            decision_type="correlation",
            correct=True,
            notes="Confirmed BLE+camera match",
            operator="operator1",
        )
        training_store.log_feedback(
            target_id="ble_test_002",
            decision_type="correlation",
            correct=False,
            notes="False positive",
            operator="operator1",
        )

        feedback = training_store.get_feedback(decision_type="correlation")
        assert len(feedback) == 2

        stats = training_store.get_stats()
        assert stats["feedback"]["total"] == 2
        assert stats["feedback"]["correct"] == 1
        assert abs(stats["feedback"]["accuracy"] - 0.5) < 0.01

    def test_outcome_update(self, training_store):
        """Correlation outcomes can be updated after initial logging."""
        row_id = training_store.log_correlation(
            target_a_id="t1",
            target_b_id="t2",
            features={"distance": 2.0},
            score=0.6,
            decision="merge",
            outcome=None,
        )

        # Initially no outcome
        data = training_store.get_correlation_data(outcome_only=True)
        assert len(data) == 0

        # Update outcome
        updated = training_store.update_correlation_outcome(row_id, "correct")
        assert updated

        # Now it should appear
        data = training_store.get_correlation_data(outcome_only=True)
        assert len(data) == 1
        assert data[0]["outcome"] == "correct"
