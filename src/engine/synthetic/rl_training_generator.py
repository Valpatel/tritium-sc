# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RL training data generator for demo mode.

Generates synthetic correlation decisions and BLE classifications
that accumulate training data in the TrainingStore. After 5 minutes
of demo mode, there should be enough data to trigger a retrain of
the CorrelationLearner.

Designed to run alongside the existing FusionScenario, producing
realistic-looking training examples that exercise the full RL pipeline.
"""
from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

logger = logging.getLogger("synthetic.rl_training")

# BLE device types for classification training
DEVICE_TYPES = [
    "phone", "watch", "laptop", "tablet", "headphones",
    "speaker", "fitness_tracker", "beacon", "iot_device",
]

ALLIANCES = ["friendly", "hostile", "unknown"]


class RLTrainingGenerator:
    """Generates synthetic RL training data during demo mode.

    Produces:
    1. Correlation decisions — BLE+camera pairs with feature vectors
       and simulated outcomes (correct/incorrect).
    2. Classification decisions — BLE devices with feature vectors
       and device type predictions.
    3. Operator feedback — simulated corrections on past decisions.

    Rate: ~20 decisions/minute = ~100 decisions in 5 minutes, which
    exceeds the CorrelationLearner's 50-entry retrain threshold.
    """

    def __init__(
        self,
        interval: float = 3.0,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._interval = interval
        self._event_bus = event_bus
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tick_count = 0
        self._store: Any = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def tick_count(self) -> int:
        return self._tick_count

    def start(self) -> None:
        """Start the training data generator."""
        if self._running:
            return

        # Get training store
        try:
            from engine.intelligence.training_store import get_training_store
            self._store = get_training_store()
        except Exception as exc:
            logger.warning("TrainingStore not available: %s", exc)
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name="rl-training-gen",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "RL training generator started: interval=%.1fs", self._interval
        )

    def stop(self) -> None:
        """Stop the generator."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._interval + 1)
            self._thread = None
        logger.info(
            "RL training generator stopped: %d training examples generated",
            self._tick_count,
        )

    def _loop(self) -> None:
        """Background generation loop."""
        while self._running:
            try:
                self._generate_tick()
                self._tick_count += 1
            except Exception as exc:
                logger.warning("RL training gen tick failed: %s", exc)
            time.sleep(self._interval)

    def _generate_tick(self) -> None:
        """Generate one batch of synthetic training data."""
        if self._store is None:
            return

        # Each tick: 1 correlation decision + 1 classification decision
        # Every 5th tick: also add operator feedback
        self._generate_correlation_decision()
        self._generate_classification_decision()

        if self._tick_count % 5 == 0:
            self._generate_operator_feedback()

        # Publish event for monitoring
        if self._event_bus is not None:
            self._event_bus.publish("demo:rl_training_tick", {
                "tick": self._tick_count,
                "timestamp": time.time(),
            })

    def _generate_correlation_decision(self) -> None:
        """Generate a synthetic correlation decision with features."""
        i = self._tick_count

        # Create two synthetic targets
        ble_mac = f"de:mo:{i:02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:00"
        target_a = f"ble_{ble_mac.replace(':', '').lower()}"
        target_b = f"det_person_{i}"

        # Generate plausible features
        distance = random.uniform(0.5, 15.0)
        rssi_delta = random.uniform(0.0, 30.0)
        co_movement = random.uniform(0.0, 1.0)
        device_type_match = 1.0 if random.random() > 0.3 else 0.0
        time_gap = random.uniform(0.0, 10.0)
        signal_pattern = max(0.0, 1.0 - distance / 20.0 + random.gauss(0, 0.1))

        # Wave 126: new features for richer training signal
        co_movement_duration = random.uniform(0.0, 1.0) if co_movement > 0.3 else random.uniform(0.0, 0.3)
        time_of_day_similarity = random.uniform(0.5, 1.0)  # Synthetic targets often same session
        source_diversity_score = random.choice([0.0, 0.4, 0.6, 0.8, 1.0])
        wifi_probe_correlation = random.uniform(0.0, 1.0) if random.random() > 0.5 else 0.0

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
            "spatial": max(0.0, 1.0 - distance / 10.0),
            "temporal": co_movement * 0.8,
            "primary_confidence": random.uniform(0.3, 0.95),
            "secondary_confidence": random.uniform(0.1, 0.8),
            "source_pair": random.random(),
        }

        # Score based on features (ground truth simulation) — updated for 10 features
        score = (
            0.30 * max(0.0, 1.0 - distance / 5.0)
            + 0.15 * co_movement
            + 0.10 * device_type_match
            + 0.10 * signal_pattern
            + 0.08 * max(0.0, 1.0 - time_gap / 5.0)
            + 0.10 * co_movement_duration
            + 0.05 * time_of_day_similarity
            + 0.05 * source_diversity_score
            + 0.07 * wifi_probe_correlation
        )

        # Decision: merge if score > 0.5, else unrelated
        is_correlated = score > 0.5
        decision = "merge" if is_correlated else "unrelated"

        # Outcome: 80% of time the decision is correct
        if random.random() < 0.8:
            outcome = "correct"
        else:
            outcome = "incorrect"

        self._store.log_correlation(
            target_a_id=target_a,
            target_b_id=target_b,
            features=features,
            score=score,
            decision=decision,
            outcome=outcome,
            source="demo_rl_generator",
        )

    def _generate_classification_decision(self) -> None:
        """Generate a synthetic BLE classification with features."""
        i = self._tick_count

        mac = f"de:mo:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{i % 256:02x}:01"
        target_id = f"ble_{mac.replace(':', '').lower()}"

        predicted_type = random.choice(DEVICE_TYPES)
        confidence = random.uniform(0.4, 0.95)
        predicted_alliance = random.choice(ALLIANCES)

        features = {
            "rssi": random.randint(-90, -30),
            "adv_interval_ms": random.choice([20, 100, 250, 500, 1000, 2000]),
            "has_name": 1.0 if random.random() > 0.3 else 0.0,
            "service_count": random.randint(0, 8),
            "manufacturer_known": 1.0 if random.random() > 0.4 else 0.0,
            "is_connectable": 1.0 if random.random() > 0.5 else 0.0,
        }

        # Occasionally provide a "correction" (operator feedback on classification)
        correct_type = None
        correct_alliance = None
        if random.random() < 0.3:
            # 70% of corrections confirm the prediction
            if random.random() < 0.7:
                correct_type = predicted_type
            else:
                correct_type = random.choice(
                    [t for t in DEVICE_TYPES if t != predicted_type]
                )

        self._store.log_classification(
            target_id=target_id,
            features=features,
            predicted_type=predicted_type,
            confidence=confidence,
            predicted_alliance=predicted_alliance,
            correct_type=correct_type,
            correct_alliance=correct_alliance,
            source="demo_rl_generator",
        )

    def _generate_operator_feedback(self) -> None:
        """Generate synthetic operator feedback on recent decisions."""
        i = self._tick_count

        target_id = f"ble_demo_feedback_{i}"
        decision_type = random.choice(["correlation", "classification", "threat"])
        correct = random.random() < 0.75  # 75% accuracy rate

        self._store.log_feedback(
            target_id=target_id,
            decision_type=decision_type,
            correct=correct,
            notes=f"synthetic feedback from demo tick {i}",
            operator="demo_system",
        )

    def get_stats(self) -> dict:
        """Return generator stats and training store state."""
        stats = {
            "running": self._running,
            "tick_count": self._tick_count,
            "interval": self._interval,
            "estimated_examples": self._tick_count * 2,  # correlation + classification per tick
        }

        if self._store is not None:
            try:
                store_stats = self._store.get_stats()
                stats["training_store"] = store_stats
            except Exception:
                pass

        return stats
