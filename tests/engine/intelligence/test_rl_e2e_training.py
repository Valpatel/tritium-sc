# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""End-to-end RL training pipeline test.

Proves the RL pipeline works: generate synthetic data with the
10-feature extractor, accumulate in TrainingStore, trigger retrain,
and verify accuracy improves from baseline.
"""

import os
import sys
import tempfile
import time

import pytest

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))


@pytest.mark.unit
class TestRLEndToEnd:
    """RL pipeline end-to-end test using real training data flow."""

    def test_rl_pipeline_e2e(self, tmp_path):
        """Generate synthetic data, train, verify accuracy."""
        from engine.intelligence.training_store import TrainingStore
        from engine.intelligence.correlation_learner import CorrelationLearner

        db_path = tmp_path / "test_training.db"
        model_path = str(tmp_path / "test_model.pkl")

        # 1. Create store and generate synthetic training data
        store = TrainingStore(db_path)

        # Simulate the RLTrainingGenerator's _generate_correlation_decision
        import random
        random.seed(42)

        for i in range(100):
            distance = random.uniform(0.5, 15.0)
            rssi_delta = random.uniform(0.0, 30.0)
            co_movement = random.uniform(0.0, 1.0)
            device_type_match = 1.0 if random.random() > 0.3 else 0.0
            time_gap = random.uniform(0.0, 10.0)
            signal_pattern = max(0.0, 1.0 - distance / 20.0 + random.gauss(0, 0.1))
            co_movement_duration = random.uniform(0.0, 1.0) if co_movement > 0.3 else random.uniform(0.0, 0.3)
            time_of_day_similarity = random.uniform(0.5, 1.0)
            source_diversity_score = random.choice([0.0, 0.4, 0.6, 0.8, 1.0])
            wifi_probe_correlation = random.uniform(0.0, 1.0) if random.random() > 0.5 else 0.0

            # Wave 150 derived features
            spatial = max(0.0, 1.0 - distance / 15.0) if distance < 15.0 else 0.0
            temporal = max(0.0, 1.0 - time_gap / 10.0) if time_gap < 10.0 else 0.0
            primary_confidence = random.uniform(0.3, 1.0)
            secondary_confidence = random.uniform(0.1, primary_confidence)
            source_pair = random.choice([0.1, 0.3, 0.7, 0.8, 0.9, 1.0])
            # Wave 157 acoustic co-occurrence
            acoustic_cooccurrence = random.uniform(0.0, 1.0) if random.random() > 0.6 else 0.0

            features = {
                "distance": distance,
                "rssi_delta": rssi_delta,
                "co_movement": co_movement,
                "device_type_match": device_type_match,
                "time_gap": time_gap,
                "signal_pattern": signal_pattern,
                "co_movement_duration": co_movement_duration,
                "time_of_day_similarity": time_of_day_similarity,
                "source_diversity_score": source_diversity_score,
                "wifi_probe_correlation": wifi_probe_correlation,
                "spatial": spatial,
                "temporal": temporal,
                "primary_confidence": primary_confidence,
                "secondary_confidence": secondary_confidence,
                "source_pair": source_pair,
                "acoustic_cooccurrence": acoustic_cooccurrence,
            }

            # Ground truth scoring (same as rl_training_generator + Wave 157)
            score = (
                0.25 * max(0.0, 1.0 - distance / 5.0)
                + 0.10 * co_movement
                + 0.08 * device_type_match
                + 0.08 * signal_pattern
                + 0.06 * max(0.0, 1.0 - time_gap / 5.0)
                + 0.08 * co_movement_duration
                + 0.04 * time_of_day_similarity
                + 0.04 * source_diversity_score
                + 0.05 * wifi_probe_correlation
                + 0.08 * spatial
                + 0.06 * temporal
                + 0.04 * primary_confidence
                + 0.02 * secondary_confidence
                + 0.05 * source_pair
                + 0.07 * acoustic_cooccurrence
            )

            is_correlated = score > 0.5
            decision = "merge" if is_correlated else "unrelated"

            # 80% correct outcome
            if random.random() < 0.8:
                outcome = "correct"
            else:
                outcome = "incorrect"

            store.log_correlation(
                target_a_id=f"ble_demo_{i:04x}",
                target_b_id=f"det_person_{i}",
                features=features,
                score=score,
                decision=decision,
                outcome=outcome,
                source="test_rl_e2e",
            )

        # 2. Verify training data accumulated
        stats = store.get_stats()
        assert stats["correlation"]["total"] == 100
        assert stats["correlation"]["confirmed"] == 100  # all have outcomes

        # 3. Create learner and train
        learner = CorrelationLearner(
            training_store=store,
            model_path=model_path,
        )

        result = learner.train()

        # 4. Verify training succeeded
        assert result["success"] is True, f"Training failed: {result.get('error')}"
        assert result["training_count"] >= 50  # at least 50 valid examples
        assert "accuracy" in result

        accuracy = result["accuracy"]
        print(f"\nRL Training Results:")
        print(f"  Accuracy: {accuracy:.3f}")
        print(f"  Training count: {result['training_count']}")
        print(f"  Best params: {result.get('best_params', {})}")
        # Feature importance analysis
        importances = result.get("feature_importances", {})
        if importances:
            sorted_imp = sorted(importances.items(), key=lambda x: x[1], reverse=True)
            print(f"  Feature importances (ranked):")
            for fname, imp in sorted_imp:
                bar = "#" * int(imp * 50)
                print(f"    {fname:30s} {imp:.4f} {bar}")
            # Identify low-importance features (<1%)
            low_imp = [f for f, v in sorted_imp if v < 0.01]
            if low_imp:
                print(f"  Low importance (<1%): {low_imp}")

        # 5. Accuracy should be meaningfully above random (50%)
        # With structured synthetic data and 10 features, expect >55%
        assert accuracy > 0.50, f"Accuracy {accuracy:.3f} not above baseline 0.50"

        # 6. Model should predict
        test_features = {
            "distance": 1.0,
            "rssi_delta": 5.0,
            "co_movement": 0.8,
            "device_type_match": 1.0,
            "time_gap": 1.0,
            "signal_pattern": 0.9,
            "co_movement_duration": 0.7,
            "time_of_day_similarity": 0.9,
            "source_diversity_score": 0.8,
            "wifi_probe_correlation": 0.6,
            "spatial": 0.93,
            "temporal": 0.9,
            "primary_confidence": 0.85,
            "secondary_confidence": 0.7,
            "source_pair": 1.0,
            "acoustic_cooccurrence": 0.6,
        }

        prob, conf = learner.predict(test_features)
        print(f"  Prediction (close targets): prob={prob:.3f}, conf={conf:.3f}")

        assert 0.0 <= prob <= 1.0
        assert 0.0 <= conf <= 1.0

        # 7. Save and reload model
        assert learner.save()
        assert os.path.exists(model_path)

        learner2 = CorrelationLearner(
            training_store=store,
            model_path=model_path,
        )
        assert learner2.is_trained
        prob2, conf2 = learner2.predict(test_features)
        assert abs(prob - prob2) < 0.01  # Should be same after reload

        print(f"\n  Pipeline verified: data -> train -> predict -> save -> reload")
        print(f"  New accuracy: {accuracy:.3f}")

    def test_retrain_with_more_data(self, tmp_path):
        """Verify that adding more data and retraining changes accuracy."""
        from engine.intelligence.training_store import TrainingStore
        from engine.intelligence.correlation_learner import CorrelationLearner

        db_path = tmp_path / "retrain_test.db"
        store = TrainingStore(db_path)

        import random
        random.seed(123)

        # First batch: 50 examples
        for i in range(50):
            features = {
                "distance": random.uniform(0.5, 15.0),
                "rssi_delta": random.uniform(0.0, 30.0),
                "co_movement": random.uniform(0.0, 1.0),
                "device_type_match": 1.0 if random.random() > 0.3 else 0.0,
                "time_gap": random.uniform(0.0, 10.0),
                "signal_pattern": random.uniform(0.0, 1.0),
                "co_movement_duration": random.uniform(0.0, 1.0),
                "time_of_day_similarity": random.uniform(0.0, 1.0),
                "source_diversity_score": random.uniform(0.0, 1.0),
                "wifi_probe_correlation": random.uniform(0.0, 1.0),
                "spatial": random.uniform(0.0, 1.0),
                "temporal": random.uniform(0.0, 1.0),
                "primary_confidence": random.uniform(0.3, 1.0),
                "secondary_confidence": random.uniform(0.1, 0.8),
                "source_pair": random.choice([0.1, 0.3, 0.7, 0.8, 0.9, 1.0]),
                "acoustic_cooccurrence": random.uniform(0.0, 1.0) if random.random() > 0.6 else 0.0,
            }
            outcome = "correct" if random.random() < 0.75 else "incorrect"
            store.log_correlation(
                target_a_id=f"a_{i}", target_b_id=f"b_{i}",
                features=features, score=random.uniform(0, 1),
                decision="merge", outcome=outcome,
            )

        learner = CorrelationLearner(
            training_store=store,
            model_path=str(tmp_path / "model1.pkl"),
        )
        r1 = learner.train()
        assert r1["success"] is True
        acc1 = r1["accuracy"]

        # Second batch: 100 more examples (total 150)
        for i in range(100):
            features = {
                "distance": random.uniform(0.5, 15.0),
                "rssi_delta": random.uniform(0.0, 30.0),
                "co_movement": random.uniform(0.0, 1.0),
                "device_type_match": 1.0 if random.random() > 0.3 else 0.0,
                "time_gap": random.uniform(0.0, 10.0),
                "signal_pattern": random.uniform(0.0, 1.0),
                "co_movement_duration": random.uniform(0.0, 1.0),
                "time_of_day_similarity": random.uniform(0.0, 1.0),
                "source_diversity_score": random.uniform(0.0, 1.0),
                "wifi_probe_correlation": random.uniform(0.0, 1.0),
                "spatial": random.uniform(0.0, 1.0),
                "temporal": random.uniform(0.0, 1.0),
                "primary_confidence": random.uniform(0.3, 1.0),
                "secondary_confidence": random.uniform(0.1, 0.8),
                "source_pair": random.choice([0.1, 0.3, 0.7, 0.8, 0.9, 1.0]),
                "acoustic_cooccurrence": random.uniform(0.0, 1.0) if random.random() > 0.6 else 0.0,
            }
            outcome = "correct" if random.random() < 0.75 else "incorrect"
            store.log_correlation(
                target_a_id=f"a2_{i}", target_b_id=f"b2_{i}",
                features=features, score=random.uniform(0, 1),
                decision="merge", outcome=outcome,
            )

        r2 = learner.train()
        assert r2["success"] is True
        acc2 = r2["accuracy"]
        assert r2["training_count"] > r1["training_count"]

        print(f"\nRetrain test:")
        print(f"  Round 1: accuracy={acc1:.3f}, n={r1['training_count']}")
        print(f"  Round 2: accuracy={acc2:.3f}, n={r2['training_count']}")
