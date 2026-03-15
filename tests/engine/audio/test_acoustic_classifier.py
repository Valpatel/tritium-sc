# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for acoustic event classifier — rule-based, pure-Python KNN, and MFCC+KNN."""

import math

import pytest
from engine.audio.acoustic_classifier import (
    AcousticClassifier,
    AcousticEventType,
    AudioFeatures,
    MFCCClassifier,
    TRAINING_DATA,
    _HAS_SCIPY,
    _HAS_SKLEARN,
    _HAS_NUMPY,
    extract_mfcc_scipy,
)


class TestAcousticEventType:
    def test_enum_values(self):
        assert AcousticEventType.GUNSHOT == "gunshot"
        assert AcousticEventType.VOICE == "voice"
        assert AcousticEventType.VEHICLE == "vehicle"


class TestAudioFeatures:
    def test_defaults(self):
        f = AudioFeatures()
        assert f.rms_energy == 0.0
        assert f.duration_ms == 0


class TestAcousticClassifier:
    def setup_method(self):
        self.classifier = AcousticClassifier()

    def test_gunshot_detection(self):
        """High energy, short duration = gunshot."""
        features = AudioFeatures(
            peak_amplitude=0.95,
            rms_energy=0.9,
            spectral_centroid=1000,
            duration_ms=50,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.GUNSHOT
        assert event.confidence > 0.8

    def test_voice_detection(self):
        """Mid-frequency, moderate energy, sustained = voice."""
        features = AudioFeatures(
            peak_amplitude=0.3,
            rms_energy=0.2,
            spectral_centroid=500,
            duration_ms=2000,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.VOICE

    def test_vehicle_detection(self):
        """Low frequency, sustained = vehicle."""
        features = AudioFeatures(
            peak_amplitude=0.4,
            rms_energy=0.3,
            spectral_centroid=200,
            duration_ms=5000,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.VEHICLE

    def test_siren_detection(self):
        """Mid-high frequency, sustained, loud = siren."""
        features = AudioFeatures(
            peak_amplitude=0.7,
            rms_energy=0.5,
            spectral_centroid=1200,
            duration_ms=3000,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.SIREN

    def test_glass_break_detection(self):
        """High frequency, high energy, short = glass break."""
        features = AudioFeatures(
            peak_amplitude=0.7,
            rms_energy=0.6,
            spectral_centroid=4000,
            duration_ms=200,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.GLASS_BREAK

    def test_unknown_classification(self):
        """Low energy noise = unknown."""
        features = AudioFeatures(
            peak_amplitude=0.05,
            rms_energy=0.02,
            spectral_centroid=1000,
            duration_ms=100,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.UNKNOWN

    def test_event_history(self):
        """Events are recorded in history."""
        for i in range(5):
            self.classifier.classify(AudioFeatures(
                peak_amplitude=0.9, duration_ms=50, spectral_centroid=1000,
            ))
        events = self.classifier.get_recent_events()
        assert len(events) == 5

    def test_event_counts(self):
        """Event counts track by type."""
        self.classifier.classify(AudioFeatures(
            peak_amplitude=0.9, duration_ms=50, spectral_centroid=1000,
        ))
        self.classifier.classify(AudioFeatures(
            peak_amplitude=0.2, rms_energy=0.15, spectral_centroid=500, duration_ms=2000,
        ))
        counts = self.classifier.get_event_counts()
        assert "gunshot" in counts
        assert "voice" in counts


class TestMFCCKNNUpgrade:
    """Tests for the Wave 151 MFCC+KNN upgrade."""

    def test_model_version_v3(self):
        """Model version bumped to v3 for MFCC+KNN upgrade."""
        assert MFCCClassifier.MODEL_VERSION == "mfcc_knn_v3"

    def test_default_k_is_5(self):
        """Default k changed from 3 to 5."""
        clf = MFCCClassifier()
        assert clf.k == 5

    def test_sklearn_available(self):
        """sklearn should be available in this environment."""
        assert _HAS_SKLEARN, "sklearn not installed"
        assert _HAS_NUMPY, "numpy not installed"

    def test_scipy_available(self):
        """scipy should be available for real MFCC extraction."""
        assert _HAS_SCIPY, "scipy not installed"

    def test_uses_sklearn_backend(self):
        """Classifier should use sklearn KNN when available."""
        clf = MFCCClassifier(k=5)
        clf.train()
        assert clf.uses_sklearn, "Should use sklearn backend"

    def test_classify_gunshot_mfcc_knn(self):
        """Gunshot features should classify correctly with sklearn KNN."""
        clf = MFCCClassifier(k=5)
        clf.train()
        features = AudioFeatures(
            mfcc=[-40, 12, -5, 3, -2, 1, -1, 0.5, -0.3, 0.2, -0.1, 0.05, -0.02],
            spectral_centroid=3500,
            zero_crossing_rate=0.15,
            rms_energy=0.92,
            spectral_bandwidth=4000,
            duration_ms=80,
        )
        best, conf, preds = clf.classify(features)
        assert best == "gunshot"
        assert conf > 0.5

    def test_classify_voice_mfcc_knn(self):
        """Voice features should classify correctly with sklearn KNN."""
        clf = MFCCClassifier(k=5)
        clf.train()
        features = AudioFeatures(
            mfcc=[-20, 8, 6, -3, 2, -1, 0.5, -0.3, 0.2, -0.1, 0.05, -0.03, 0.01],
            spectral_centroid=800,
            zero_crossing_rate=0.08,
            rms_energy=0.25,
            spectral_bandwidth=1200,
            duration_ms=1500,
        )
        best, conf, preds = clf.classify(features)
        assert best == "voice"
        assert conf > 0.3

    def test_classify_vehicle_mfcc_knn(self):
        """Vehicle features should classify correctly."""
        clf = MFCCClassifier(k=5)
        clf.train()
        features = AudioFeatures(
            mfcc=[-30, 5, -2, 1, -0.5, 0.3, -0.2, 0.1, -0.05, 0.03, -0.02, 0.01, -0.005],
            spectral_centroid=250,
            zero_crossing_rate=0.03,
            rms_energy=0.35,
            spectral_bandwidth=400,
            duration_ms=5000,
        )
        best, conf, preds = clf.classify(features)
        assert best == "vehicle"
        assert conf > 0.3

    def test_predictions_have_probabilities(self):
        """sklearn KNN should return proper probability estimates."""
        clf = MFCCClassifier(k=5)
        clf.train()
        features = AudioFeatures(
            mfcc=[-40, 12, -5, 3, -2, 1, -1, 0.5, -0.3, 0.2, -0.1, 0.05, -0.02],
            spectral_centroid=3500,
            zero_crossing_rate=0.15,
            rms_energy=0.92,
            spectral_bandwidth=4000,
            duration_ms=80,
        )
        _, _, preds = clf.classify(features)
        assert len(preds) > 0
        total = sum(p["confidence"] for p in preds)
        # Probabilities should sum to ~1.0 (within rounding)
        assert 0.9 <= total <= 1.1

    def test_training_sample_count(self):
        """Training should report correct sample count."""
        clf = MFCCClassifier(k=5)
        clf.train()
        assert clf._training_sample_count == len(TRAINING_DATA)
        assert clf._training_class_count >= 8  # At least 8 sound classes

    def test_custom_data_training(self):
        """Training with custom data subset works."""
        clf = MFCCClassifier(k=3)
        clf.train(TRAINING_DATA[:10])
        assert clf.is_trained
        assert clf._training_sample_count == 10

    def test_fallback_no_mfcc(self):
        """Classifier works even without MFCC features (uses zeros)."""
        clf = MFCCClassifier(k=5)
        clf.train()
        features = AudioFeatures(
            spectral_centroid=3500,
            zero_crossing_rate=0.15,
            rms_energy=0.92,
            spectral_bandwidth=4000,
            duration_ms=80,
        )
        best, conf, preds = clf.classify(features)
        assert isinstance(best, str)
        assert 0.0 <= conf <= 1.0

    def test_acoustic_classifier_uses_v3(self):
        """AcousticClassifier should use the upgraded model version."""
        ac = AcousticClassifier(enable_ml=True)
        assert ac.ml_available
        event = ac.classify(AudioFeatures(
            mfcc=[-40, 12, -5, 3, -2, 1, -1, 0.5, -0.3, 0.2, -0.1, 0.05, -0.02],
            spectral_centroid=3500,
            zero_crossing_rate=0.15,
            rms_energy=0.92,
            spectral_bandwidth=4000,
            duration_ms=80,
        ))
        assert event.model_version == "mfcc_knn_v3"


class TestMFCCExtraction:
    """Tests for scipy-based MFCC extraction."""

    def test_extract_mfcc_sine_wave(self):
        """Extract MFCCs from a synthetic sine wave."""
        if not _HAS_SCIPY or not _HAS_NUMPY:
            pytest.skip("scipy/numpy not available")
        import numpy as np_local

        sr = 16000
        duration = 1.0
        freq = 440.0
        t = np_local.linspace(0, duration, int(sr * duration), endpoint=False)
        samples = (0.5 * np_local.sin(2 * np_local.pi * freq * t)).tolist()

        mfcc = extract_mfcc_scipy(samples, sr)
        assert mfcc is not None
        assert len(mfcc) == 13
        # MFCCs should be finite numbers
        for c in mfcc:
            assert math.isfinite(c), f"Non-finite MFCC coefficient: {c}"

    def test_extract_mfcc_white_noise(self):
        """Extract MFCCs from white noise."""
        if not _HAS_SCIPY or not _HAS_NUMPY:
            pytest.skip("scipy/numpy not available")
        import numpy as np_local

        sr = 16000
        np_local.random.seed(42)
        samples = (0.1 * np_local.random.randn(sr)).tolist()

        mfcc = extract_mfcc_scipy(samples, sr)
        assert mfcc is not None
        assert len(mfcc) == 13

    def test_extract_mfcc_too_short(self):
        """Too-short signals return None."""
        if not _HAS_SCIPY or not _HAS_NUMPY:
            pytest.skip("scipy/numpy not available")

        samples = [0.0] * 100  # Less than n_fft=2048
        result = extract_mfcc_scipy(samples, 16000)
        assert result is None

    def test_mfcc_different_for_different_signals(self):
        """Different audio signals produce different MFCCs."""
        if not _HAS_SCIPY or not _HAS_NUMPY:
            pytest.skip("scipy/numpy not available")
        import numpy as np_local

        sr = 16000
        n = sr  # 1 second
        t = np_local.linspace(0, 1.0, n, endpoint=False)

        # Low frequency sine
        low = (0.5 * np_local.sin(2 * np_local.pi * 200 * t)).tolist()
        # High frequency sine
        high = (0.5 * np_local.sin(2 * np_local.pi * 4000 * t)).tolist()

        mfcc_low = extract_mfcc_scipy(low, sr)
        mfcc_high = extract_mfcc_scipy(high, sr)

        assert mfcc_low is not None
        assert mfcc_high is not None

        # They should differ significantly
        diff = sum(abs(a - b) for a, b in zip(mfcc_low, mfcc_high))
        assert diff > 1.0, f"MFCCs should differ for 200Hz vs 4000Hz, diff={diff}"

    def test_uses_scipy_mfcc_flag(self):
        """MFCCClassifier reports scipy availability."""
        clf = MFCCClassifier()
        assert clf.uses_scipy_mfcc == (_HAS_SCIPY and _HAS_NUMPY)


class TestAcousticRouter:
    def test_import(self):
        from app.routers.acoustic import router
        assert router is not None
