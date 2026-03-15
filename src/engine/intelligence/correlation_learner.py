# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RL-based correlation scorer — learns from TrainingStore data.

Loads training examples from the TrainingStore SQLite database. Trains
a logistic regression model (scikit-learn) on correlation features:
distance, RSSI delta, co-movement, device type match, time gap, signal
pattern. Falls back to static weights if no training data or if sklearn
is not installed.

Integrates with TargetCorrelator as a LearnedStrategy that wraps the
LearnedScorer from tritium-lib.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from tritium_lib.intelligence.base_learner import BaseLearner

logger = logging.getLogger("correlation_learner")

# Feature names must match what the correlator logs to TrainingStore.
# Wave 126: expanded from 6 to 10 features to improve 50.5% accuracy.
FEATURE_NAMES = [
    "distance",
    "rssi_delta",
    "co_movement",
    "device_type_match",
    "time_gap",
    "signal_pattern",
    # New features (Wave 126) — richer signals for correlation
    "co_movement_duration",
    "time_of_day_similarity",
    "source_diversity_score",
    "wifi_probe_correlation",
]

MODEL_PATH = "data/models/correlation_model.pkl"


class CorrelationLearner(BaseLearner):
    """Trains and manages a correlation scoring model.

    Loads data from TrainingStore, trains a logistic regression, and
    provides predictions through the tritium-lib CorrelationScorer
    interface.  Extends BaseLearner for shared persistence and status.
    """

    def __init__(
        self,
        training_store: Any = None,
        model_path: str = MODEL_PATH,
        feature_names: Optional[list[str]] = None,
    ) -> None:
        super().__init__(model_path)
        self._training_store = training_store
        self._feature_names = feature_names or list(FEATURE_NAMES)
        self._sklearn_available = _check_sklearn()

        # Try to load existing model
        self.load()

    @property
    def name(self) -> str:
        return "correlation"

    def get_status(self) -> dict[str, Any]:
        """Return model status for API response."""
        stats = self.get_stats()
        stats["sklearn_available"] = self._sklearn_available
        stats["feature_names"] = self._feature_names
        return stats

    def train(self) -> dict[str, Any]:
        """Train (or retrain) the model from TrainingStore data.

        Returns:
            Dict with training results: accuracy, count, success status.
        """
        if self._training_store is None:
            return {"success": False, "error": "No training store configured"}

        if not self._sklearn_available:
            return {"success": False, "error": "scikit-learn not available, using static weights"}

        try:
            # Get confirmed correlation decisions
            data = self._training_store.get_correlation_data(
                limit=10000,
                outcome_only=True,
            )

            if len(data) < 10:
                return {
                    "success": False,
                    "error": f"Insufficient training data: {len(data)} examples (need 10+)",
                    "count": len(data),
                }

            # Extract features and labels
            X, y = self._prepare_training_data(data)

            if len(X) < 10:
                return {
                    "success": False,
                    "error": f"Insufficient valid examples after filtering: {len(X)}",
                }

            # Train logistic regression
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import cross_val_score
            import numpy as np

            X_arr = np.array(X)
            y_arr = np.array(y)

            model = LogisticRegression(
                max_iter=1000,
                C=1.0,
                class_weight="balanced",
            )

            # Cross-validation for accuracy estimate
            if len(X) >= 20:
                cv_folds = min(5, len(X) // 4)
                scores = cross_val_score(model, X_arr, y_arr, cv=cv_folds, scoring="accuracy")
                accuracy = float(scores.mean())
            else:
                accuracy = 0.0  # Not enough data for CV

            # Train on full dataset
            model.fit(X_arr, y_arr)

            self._model = model
            self._accuracy = accuracy
            self._training_count = len(X)
            self._last_trained = time.time()

            # Save model
            self.save()

            logger.info(
                "Correlation model trained: accuracy=%.3f, n=%d",
                accuracy, len(X),
            )

            return {
                "success": True,
                "accuracy": accuracy,
                "training_count": len(X),
                "feature_names": self._feature_names,
            }

        except Exception as exc:
            logger.error("Model training failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def predict(self, features: dict[str, float]) -> tuple[float, float]:
        """Predict correlation probability.

        Args:
            features: Feature dict with keys from FEATURE_NAMES.

        Returns:
            (probability, confidence) tuple.
        """
        if self._model is None:
            return _static_predict(features)

        try:
            import numpy as np

            X = [[features.get(fn, 0.0) for fn in self._feature_names]]
            proba = self._model.predict_proba(np.array(X))[0]
            probability = float(proba[1]) if len(proba) > 1 else float(proba[0])
            confidence = min(1.0, abs(probability - 0.5) * 2.0)
            return probability, confidence
        except Exception:
            return _static_predict(features)

    def get_scorer(self) -> Any:
        """Return a tritium-lib CorrelationScorer wrapping this model.

        Returns:
            LearnedScorer or StaticScorer from tritium-lib.
        """
        try:
            from tritium_lib.intelligence.scorer import LearnedScorer, StaticScorer

            if self._model is not None:
                return LearnedScorer(
                    model=self._model,
                    feature_names=self._feature_names,
                    accuracy=self._accuracy,
                    training_count=self._training_count,
                )
            return StaticScorer()
        except ImportError:
            return None

    def _prepare_training_data(
        self, data: list[dict[str, Any]]
    ) -> tuple[list[list[float]], list[int]]:
        """Extract feature vectors and labels from training records."""
        X: list[list[float]] = []
        y: list[int] = []

        for record in data:
            outcome = record.get("outcome", "")
            if outcome not in ("correct", "incorrect"):
                continue

            features = record.get("features", {})
            if not isinstance(features, dict):
                continue

            row = [float(features.get(fn, 0.0)) for fn in self._feature_names]
            label = 1 if outcome == "correct" else 0

            X.append(row)
            y.append(label)

        return X, y

    def _serialize(self) -> dict[str, Any]:
        """Extend BaseLearner serialization with feature_names."""
        data = super()._serialize()
        data["feature_names"] = self._feature_names
        return data

    def _deserialize(self, data: dict[str, Any]) -> None:
        """Extend BaseLearner deserialization with feature_names."""
        super()._deserialize(data)
        self._feature_names = data.get("feature_names", self._feature_names)


class LearnedStrategy:
    """Correlation strategy adapter for the TargetCorrelator.

    Wraps a CorrelationLearner as a CorrelationStrategy compatible
    with the existing multi-strategy correlator framework.
    """

    def __init__(self, learner: CorrelationLearner) -> None:
        self._learner = learner

    @property
    def name(self) -> str:
        return "learned"

    def evaluate(self, target_a: Any, target_b: Any) -> Any:
        """Evaluate correlation using the learned model.

        Extracts features from the target pair and runs prediction.
        Returns a StrategyScore compatible with the correlator.
        """
        import math

        try:
            from engine.tactical.correlation_strategies import StrategyScore
        except ImportError:
            # Fallback dataclass if import fails
            from dataclasses import dataclass

            @dataclass
            class StrategyScore:
                strategy_name: str
                score: float
                detail: str

        # Extract features from target pair
        features = _extract_features(target_a, target_b)

        probability, confidence = self._learner.predict(features)

        detail = (
            f"learned model p={probability:.3f} conf={confidence:.3f}"
            if self._learner.is_trained
            else f"static fallback p={probability:.3f}"
        )

        return StrategyScore(
            strategy_name=self.name,
            score=max(0.0, min(1.0, probability)),
            detail=detail,
        )


def _extract_features(target_a: Any, target_b: Any) -> dict[str, float]:
    """Extract correlation features from a target pair.

    Works with TrackedTarget objects or any object with position,
    rssi, source, asset_type, and last_seen attributes.

    Wave 126: expanded from 6 to 10 features using tritium-lib
    feature_engineering functions for richer correlation signals.
    """
    import math

    features: dict[str, float] = {}

    # Distance
    try:
        pos_a = getattr(target_a, "position", (0.0, 0.0))
        pos_b = getattr(target_b, "position", (0.0, 0.0))
        dx = pos_a[0] - pos_b[0]
        dy = pos_a[1] - pos_b[1]
        features["distance"] = math.hypot(dx, dy)
    except (TypeError, IndexError):
        features["distance"] = 0.0

    # RSSI delta
    rssi_a = getattr(target_a, "rssi", 0)
    rssi_b = getattr(target_b, "rssi", 0)
    features["rssi_delta"] = abs(float(rssi_a or 0) - float(rssi_b or 0))

    # Co-movement (placeholder — requires history analysis)
    features["co_movement"] = 0.0

    # Device type match — now uses tritium-lib semantic matching
    type_a = getattr(target_a, "asset_type", "unknown")
    type_b = getattr(target_b, "asset_type", "unknown")
    source_a = getattr(target_a, "source", "")
    source_b = getattr(target_b, "source", "")
    try:
        from tritium_lib.intelligence.feature_engineering import device_type_match as _dtm
        features["device_type_match"] = _dtm(type_a, type_b, source_a, source_b)
    except ImportError:
        # Fallback to simple logic
        if source_a != source_b:
            features["device_type_match"] = 1.0
        elif type_a == type_b and type_a != "unknown":
            features["device_type_match"] = 0.5
        else:
            features["device_type_match"] = 0.0

    # Time gap
    try:
        last_a = getattr(target_a, "last_seen", 0.0)
        last_b = getattr(target_b, "last_seen", 0.0)
        features["time_gap"] = abs(float(last_a) - float(last_b))
    except (TypeError, ValueError):
        features["time_gap"] = 0.0

    # Signal pattern (1.0 if both seen very recently, decays)
    try:
        now = time.monotonic()
        age_a = now - float(getattr(target_a, "last_seen", now))
        age_b = now - float(getattr(target_b, "last_seen", now))
        max_age = max(age_a, age_b)
        features["signal_pattern"] = max(0.0, 1.0 - max_age / 30.0)
    except (TypeError, ValueError):
        features["signal_pattern"] = 0.0

    # --- New features (Wave 126) ---

    # Co-movement duration — uses position history if available
    features["co_movement_duration"] = 0.0
    try:
        from tritium_lib.intelligence.feature_engineering import co_movement_score as _cms
        history_a = getattr(target_a, "trail", None)
        history_b = getattr(target_b, "trail", None)
        if history_a and history_b:
            features["co_movement_duration"] = _cms(history_a, history_b)
    except (ImportError, Exception):
        pass

    # Time-of-day similarity
    try:
        from tritium_lib.intelligence.feature_engineering import time_similarity as _ts
        last_a_ts = float(getattr(target_a, "last_seen", 0.0))
        last_b_ts = float(getattr(target_b, "last_seen", 0.0))
        features["time_of_day_similarity"] = _ts(last_a_ts, last_b_ts)
    except (ImportError, Exception):
        features["time_of_day_similarity"] = 0.0

    # Source diversity score
    try:
        from tritium_lib.intelligence.feature_engineering import source_diversity as _sd
        sources_a = [source_a] if source_a else []
        sources_b = [source_b] if source_b else []
        # Check for multi-source targets (composite targets have multiple sources)
        extra_sources_a = getattr(target_a, "sources", [])
        extra_sources_b = getattr(target_b, "sources", [])
        if extra_sources_a:
            sources_a = list(extra_sources_a)
        if extra_sources_b:
            sources_b = list(extra_sources_b)
        features["source_diversity_score"] = _sd(sources_a, sources_b)
    except (ImportError, Exception):
        features["source_diversity_score"] = 0.0

    # WiFi probe correlation — temporal match between BLE and WiFi probe
    features["wifi_probe_correlation"] = 0.0
    try:
        from tritium_lib.intelligence.feature_engineering import (
            wifi_probe_temporal_correlation as _wptc,
        )
        # Check if either target is a WiFi probe and the other is BLE
        is_wifi_probe = source_a == "wifi_probe" or source_b == "wifi_probe"
        is_ble = source_a == "ble" or source_b == "ble"
        if is_wifi_probe and is_ble:
            last_a_ts = float(getattr(target_a, "last_seen", 0.0))
            last_b_ts = float(getattr(target_b, "last_seen", 0.0))
            # Check if same observer (same edge node reported both)
            observer_a = getattr(target_a, "observer_id", "")
            observer_b = getattr(target_b, "observer_id", "")
            same_obs = bool(observer_a and observer_a == observer_b)
            features["wifi_probe_correlation"] = _wptc(
                last_a_ts, last_b_ts, same_observer=same_obs
            )
    except (ImportError, Exception):
        pass

    return features


def _static_predict(features: dict[str, float]) -> tuple[float, float]:
    """Static weighted prediction fallback (no sklearn needed)."""
    import math

    weights = {
        "distance": -0.25,
        "rssi_delta": -0.08,
        "co_movement": 0.18,
        "device_type_match": 0.12,
        "time_gap": -0.08,
        "signal_pattern": 0.15,
        # New features (Wave 126)
        "co_movement_duration": 0.12,
        "time_of_day_similarity": 0.06,
        "source_diversity_score": 0.08,
        "wifi_probe_correlation": 0.14,
    }
    bias = 0.5

    logit = 0.0
    for fn, w in weights.items():
        logit += w * features.get(fn, 0.0)

    # Sigmoid
    x = logit + (bias - 0.5) * 2.0
    if x >= 0:
        probability = 1.0 / (1.0 + math.exp(-x))
    else:
        ez = math.exp(x)
        probability = ez / (1.0 + ez)

    confidence = min(1.0, abs(probability - 0.5) * 2.0)
    return probability, confidence


def _check_sklearn() -> bool:
    """Check if scikit-learn is available."""
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Auto-retrain scheduler
# ---------------------------------------------------------------------------

class RetrainScheduler:
    """Periodically retrains the correlation model in a daemon thread.

    Retrains every ``interval_seconds`` (default 6 hours) OR when the
    TrainingStore accumulates ``retrain_threshold`` new feedback entries
    since the last training run.

    All callbacks (on_retrain) are invoked in the daemon thread.
    """

    def __init__(
        self,
        learner: CorrelationLearner,
        *,
        interval_seconds: float = 6 * 3600,  # 6 hours
        retrain_threshold: int = 50,  # entries since last train
        on_retrain: Optional[Any] = None,  # callback(result_dict)
    ) -> None:
        self._learner = learner
        self._interval = interval_seconds
        self._threshold = retrain_threshold
        self._on_retrain = on_retrain
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_feedback_count: int = 0

    def start(self) -> None:
        """Start the scheduler daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name="retrain-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "RetrainScheduler started: interval=%ds, threshold=%d",
            int(self._interval), self._threshold,
        )

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._running

    def _should_retrain(self) -> bool:
        """Check if retraining is warranted due to new feedback."""
        if self._learner._training_store is None:
            return False
        try:
            stats = self._learner._training_store.get_stats()
            current_confirmed = stats.get("correlation", {}).get("confirmed", 0)
            delta = current_confirmed - self._last_feedback_count
            if delta >= self._threshold:
                return True
        except Exception:
            pass
        return False

    def _loop(self) -> None:
        """Background retrain loop — sleeps in short segments for responsiveness."""
        check_interval = min(60.0, self._interval)  # Check every minute
        elapsed = 0.0

        while self._running:
            time.sleep(check_interval)
            elapsed += check_interval

            should_train = elapsed >= self._interval or self._should_retrain()

            if should_train:
                elapsed = 0.0
                try:
                    result = self._learner.train()
                    if result.get("success"):
                        # Update feedback count baseline
                        try:
                            stats = self._learner._training_store.get_stats()
                            self._last_feedback_count = stats.get(
                                "correlation", {}
                            ).get("confirmed", 0)
                        except Exception:
                            pass

                    logger.info(
                        "Auto-retrain: success=%s accuracy=%.3f n=%d",
                        result.get("success"),
                        result.get("accuracy", 0.0),
                        result.get("training_count", 0),
                    )

                    if self._on_retrain:
                        try:
                            self._on_retrain(result)
                        except Exception as exc:
                            logger.warning("Retrain callback failed: %s", exc)
                except Exception as exc:
                    logger.error("Auto-retrain failed: %s", exc)


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

# Singleton learner
_learner: Optional[CorrelationLearner] = None
_scheduler: Optional[RetrainScheduler] = None


def get_correlation_learner(
    training_store: Any = None,
    model_path: str = MODEL_PATH,
) -> CorrelationLearner:
    """Get or create the singleton CorrelationLearner."""
    global _learner
    if _learner is None:
        if training_store is None:
            try:
                from engine.intelligence.training_store import get_training_store
                training_store = get_training_store()
            except ImportError:
                pass
        _learner = CorrelationLearner(
            training_store=training_store,
            model_path=model_path,
        )
    return _learner


def start_retrain_scheduler(
    on_retrain: Optional[Any] = None,
    interval_seconds: float = 6 * 3600,
    retrain_threshold: int = 50,
) -> RetrainScheduler:
    """Start the auto-retrain scheduler (singleton).

    Args:
        on_retrain: Optional callback invoked after each retrain with result dict.
        interval_seconds: Max interval between retrains (default 6 hours).
        retrain_threshold: Number of new feedback entries to trigger early retrain.

    Returns:
        The running RetrainScheduler.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    learner = get_correlation_learner()
    _scheduler = RetrainScheduler(
        learner,
        interval_seconds=interval_seconds,
        retrain_threshold=retrain_threshold,
        on_retrain=on_retrain,
    )
    _scheduler.start()
    return _scheduler


def stop_retrain_scheduler() -> None:
    """Stop the auto-retrain scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None
