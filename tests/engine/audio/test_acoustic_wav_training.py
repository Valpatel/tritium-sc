# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for acoustic classifier WAV-based training pipeline."""

import pytest

from engine.audio.acoustic_classifier import (
    AcousticClassifier,
    AudioFeatures,
    ESC50_CATEGORY_MAP,
    MFCCClassifier,
    TRAINING_DATA,
    _extract_wav_features,
    train_from_wav_directory,
)


class TestExtractWavFeatures:
    """Test the built-in WAV feature extractor."""

    def test_returns_none_for_nonexistent(self):
        result = _extract_wav_features("/nonexistent/file.wav")
        assert result is None

    def test_returns_none_for_invalid_file(self, tmp_path):
        bad_file = tmp_path / "bad.wav"
        bad_file.write_bytes(b"not a wav file")
        result = _extract_wav_features(str(bad_file))
        assert result is None


class TestTrainFromWavDirectory:
    """Test WAV directory training data extraction."""

    def test_empty_directory(self, tmp_path):
        result = train_from_wav_directory(str(tmp_path))
        assert result == []

    def test_nonexistent_directory(self):
        result = train_from_wav_directory("/nonexistent/dir")
        assert result == []

    def test_missing_csv(self, tmp_path):
        result = train_from_wav_directory(
            str(tmp_path),
            metadata_csv=str(tmp_path / "missing.csv"),
        )
        assert result == []


class TestESC50CategoryMap:
    """Test the ESC-50 category mapping."""

    def test_has_expected_categories(self):
        assert "dog" in ESC50_CATEGORY_MAP
        assert "siren" in ESC50_CATEGORY_MAP
        assert "engine" in ESC50_CATEGORY_MAP
        assert "glass_breaking" in ESC50_CATEGORY_MAP

    def test_maps_to_valid_classes(self):
        valid = {"animal", "voice", "vehicle", "machinery", "explosion",
                 "alarm", "siren", "glass_break", "footsteps"}
        for cat, label in ESC50_CATEGORY_MAP.items():
            assert label in valid, f"{cat} maps to invalid label {label}"

    def test_animal_count(self):
        animals = [k for k, v in ESC50_CATEGORY_MAP.items() if v == "animal"]
        assert len(animals) >= 10


class TestMFCCClassifierV2:
    """Test MFCCClassifier v2 with train_from_wavs method."""

    def test_model_version(self):
        clf = MFCCClassifier()
        assert clf.MODEL_VERSION == "mfcc_knn_v3"

    def test_train_default(self):
        clf = MFCCClassifier()
        clf.train()
        assert clf.is_trained
        assert clf._training_sample_count == len(TRAINING_DATA)

    def test_train_custom_data(self):
        # Use first 5 entries of builtin data
        clf = MFCCClassifier()
        clf.train(TRAINING_DATA[:5])
        assert clf.is_trained
        assert clf._training_sample_count == 5

    def test_classify_after_train(self):
        clf = MFCCClassifier()
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
        assert isinstance(best, str)
        assert 0.0 <= conf <= 1.0
        assert len(preds) > 0

    def test_train_from_wavs_fallback(self):
        """train_from_wavs falls back to builtin when no WAVs found."""
        clf = MFCCClassifier()
        count = clf.train_from_wavs("/nonexistent/dir")
        assert count == 0
        assert clf.is_trained  # Should still train on builtin

    def test_train_from_wavs_with_augment(self):
        """train_from_wavs with augment=True includes builtin data."""
        clf = MFCCClassifier()
        count = clf.train_from_wavs("/nonexistent", augment_with_builtin=True)
        assert count == 0
        assert clf.is_trained


class TestAcousticClassifierWavIntegration:
    """Test AcousticClassifier with the WAV training pipeline."""

    def test_ml_classifier_available(self):
        clf = AcousticClassifier(enable_ml=True)
        assert clf.ml_available

    def test_classify_with_mfcc(self):
        clf = AcousticClassifier(enable_ml=True)
        features = AudioFeatures(
            mfcc=[-20, 8, 6, -3, 2, -1, 0.5, -0.3, 0.2, -0.1, 0.05, -0.03, 0.01],
            spectral_centroid=800,
            zero_crossing_rate=0.08,
            rms_energy=0.25,
            spectral_bandwidth=1200,
            duration_ms=1500,
        )
        event = clf.classify(features)
        assert event.event_type.value in [
            "gunshot", "voice", "vehicle", "animal", "glass_break",
            "explosion", "siren", "alarm", "footsteps", "machinery",
            "music", "unknown",
        ]
        assert event.confidence > 0.0
