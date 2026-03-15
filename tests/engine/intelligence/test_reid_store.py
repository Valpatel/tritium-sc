# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for ReID embedding store — cross-camera identity matching."""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

from engine.intelligence.reid_store import ReIDStore, _cosine_similarity


@pytest.mark.unit
class TestReIDStore:
    """ReID store unit tests."""

    def _make_embedding(self, seed: int, dim: int = 64) -> list[float]:
        """Generate a deterministic embedding."""
        import random
        rng = random.Random(seed)
        vec = [rng.gauss(0, 1) for _ in range(dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]

    def _add_noise(self, emb: list[float], noise: float = 0.05) -> list[float]:
        """Add noise to an embedding."""
        import random
        noisy = [x + random.gauss(0, noise) for x in emb]
        norm = math.sqrt(sum(x * x for x in noisy))
        return [x / norm for x in noisy]

    def test_cosine_similarity_same(self):
        emb = self._make_embedding(42)
        assert abs(_cosine_similarity(emb, emb) - 1.0) < 0.001

    def test_cosine_similarity_different(self):
        emb_a = self._make_embedding(42)
        emb_b = self._make_embedding(99)
        sim = _cosine_similarity(emb_a, emb_b)
        assert sim < 0.5  # Different seeds should be dissimilar

    def test_add_and_find_cross_camera(self):
        store = ReIDStore(match_threshold=0.8)
        emb_base = self._make_embedding(42)

        # Add detection from camera A
        store.add_embedding(
            target_id="person_1_camA",
            embedding=emb_base,
            camera_id="cam-A",
            class_name="person",
        )

        # Query with similar embedding from camera B
        emb_noisy = self._add_noise(emb_base, 0.03)
        matches = store.find_matches(
            target_id="person_1_camB",
            embedding=emb_noisy,
            camera_id="cam-B",
            class_name="person",
        )

        assert len(matches) >= 1
        assert matches[0].matched_target_id == "person_1_camA"
        assert matches[0].similarity > 0.8

    def test_no_match_different_person(self):
        store = ReIDStore(match_threshold=0.8)
        emb_a = self._make_embedding(42)
        emb_b = self._make_embedding(99)

        store.add_embedding("person_1_camA", emb_a, camera_id="cam-A")

        matches = store.find_matches(
            target_id="person_2_camB",
            embedding=emb_b,
            camera_id="cam-B",
        )
        assert len(matches) == 0

    def test_cross_camera_only_filter(self):
        store = ReIDStore(match_threshold=0.8)
        emb = self._make_embedding(42)

        store.add_embedding("person_1_camA", emb, camera_id="cam-A")

        # Same camera should not match when cross_camera_only=True
        matches = store.find_matches(
            target_id="person_2_camA",
            embedding=emb,
            camera_id="cam-A",
            cross_camera_only=True,
        )
        assert len(matches) == 0

        # Different camera should match
        matches = store.find_matches(
            target_id="person_2_camB",
            embedding=emb,
            camera_id="cam-B",
            cross_camera_only=True,
        )
        assert len(matches) >= 1

    def test_stats(self):
        store = ReIDStore()
        emb = self._make_embedding(42)
        store.add_embedding("t1", emb, camera_id="cam-1")
        store.add_embedding("t2", emb, camera_id="cam-2")

        stats = store.get_stats()
        assert stats["total_entries"] == 2
        assert stats["total_added"] == 2
        assert set(stats["cameras"]) == {"cam-1", "cam-2"}

    def test_class_filter(self):
        store = ReIDStore(match_threshold=0.5)
        emb = self._make_embedding(42)

        store.add_embedding("person_1", emb, camera_id="cam-A", class_name="person")

        # Query for vehicle should not match person
        matches = store.find_matches(
            target_id="car_1",
            embedding=emb,
            camera_id="cam-B",
            class_name="vehicle",
        )
        assert len(matches) == 0
