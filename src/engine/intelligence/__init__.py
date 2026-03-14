# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Intelligence subsystem — self-improving correlation and classification.

Provides:
- TrainingStore: SQLite-backed ML training data collection
- CorrelationLearner: Trains logistic regression from operator feedback
- BLEClassificationLearner: Random forest on BLE advertisement features
- LearnedStrategy: Adapter for TargetCorrelator integration
- BaseLearner: ABC for all learners (re-exported from tritium-lib)
- register_model_in_registry: Helper to save models for federation sharing
"""
