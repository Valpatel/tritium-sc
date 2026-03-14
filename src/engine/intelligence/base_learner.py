# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BaseLearner re-export from tritium-lib for SC intelligence learners.

SC learners (CorrelationLearner, BLEClassificationLearner) can inherit
from this base class to get consistent save/load/stats behavior.

This module re-exports the ABC from tritium-lib and adds SC-specific
utilities (auto-registration with ModelRegistry, sklearn detection).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

# Re-export the ABC from lib
from tritium_lib.intelligence.base_learner import BaseLearner

logger = logging.getLogger("sc.intelligence.base_learner")


def check_sklearn() -> bool:
    """Check if scikit-learn is available."""
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


def register_model_in_registry(
    name: str,
    version: str,
    learner: BaseLearner,
) -> Optional[dict[str, Any]]:
    """Save a trained learner's model to the ModelRegistry.

    Serializes the learner's pickle data and stores it in the
    global ModelRegistry for export/federation sharing.

    Returns:
        Save result dict, or None on failure.
    """
    try:
        import pickle
        from tritium_lib.intelligence.model_registry import ModelRegistry
        import os

        db_path = os.environ.get("MODEL_REGISTRY_DB", "data/model_registry.db")
        registry = ModelRegistry(db_path)

        data = pickle.dumps(learner._serialize())
        metadata = {
            "accuracy": learner.accuracy,
            "training_count": learner.training_count,
            "learner_name": learner.name,
        }
        result = registry.save_model(name, version, data, metadata)
        registry.close()
        return result
    except Exception as exc:
        logger.warning("Failed to register model in registry: %s", exc)
        return None


__all__ = ["BaseLearner", "check_sklearn", "register_model_in_registry"]
