# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for YOLO ReID integration."""

import pytest
import numpy as np


@pytest.mark.unit
def test_extract_embedding():
    from plugins.yolo_detector.reid_integration import extract_embedding, EMBEDDING_DIM

    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    emb = extract_embedding(frame, (100, 100, 200, 200))
    assert len(emb) == EMBEDDING_DIM
    # Should be L2-normalized
    norm = sum(v * v for v in emb) ** 0.5
    assert abs(norm - 1.0) < 0.01 or norm == 0.0


@pytest.mark.unit
def test_extract_embedding_empty_crop():
    from plugins.yolo_detector.reid_integration import extract_embedding, EMBEDDING_DIM

    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    emb = extract_embedding(frame, (0, 0, 0, 0))
    assert len(emb) == EMBEDDING_DIM


@pytest.mark.unit
def test_reid_integration_process():
    from plugins.yolo_detector.reid_integration import ReIDIntegration
    from tritium_lib.store import ReIDStore

    store = ReIDStore(":memory:")
    reid = ReIDIntegration(store, threshold=0.5)

    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

    # First detection on camera A
    det1 = {
        "class_name": "person",
        "bbox": (100, 100, 200, 200),
        "confidence": 0.9,
        "center": (150, 150),
    }
    result1 = reid.process_detection(frame, det1, "cam_A")
    # No match expected (first detection)
    assert result1 is None

    assert reid.stats["embeddings_stored"] == 1
    assert store.count_embeddings() == 1


@pytest.mark.unit
def test_reid_skips_non_person():
    from plugins.yolo_detector.reid_integration import ReIDIntegration
    from tritium_lib.store import ReIDStore

    store = ReIDStore(":memory:")
    reid = ReIDIntegration(store)

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    det = {"class_name": "bird", "bbox": (0, 0, 50, 50), "confidence": 0.8, "center": (25, 25)}
    result = reid.process_detection(frame, det, "cam_A")
    assert result is None
    assert reid.stats["embeddings_stored"] == 0


@pytest.mark.unit
def test_reid_stats():
    from plugins.yolo_detector.reid_integration import ReIDIntegration
    from tritium_lib.store import ReIDStore

    store = ReIDStore(":memory:")
    reid = ReIDIntegration(store)
    s = reid.stats
    assert "embeddings_stored" in s
    assert "matches_found" in s
    assert "threshold" in s
