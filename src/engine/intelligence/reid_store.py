# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ReID (Re-Identification) embedding store for cross-camera matching.

Maintains a lightweight in-memory embedding store for person/vehicle
appearance descriptors. When a detection from camera A has a similar
embedding to a detection from camera B, they are likely the same entity.

In demo mode, uses synthetic 64-dimensional embeddings that simulate
real CLIP or ReID model outputs. In production, this would be backed by
a real embedding model (CLIP, OSNet, or similar).

Usage::

    store = ReIDStore()
    store.add_embedding("cam_a_person_1", embedding_vec, camera_id="cam-01", ...)
    matches = store.find_matches("cam_b_person_1", new_embedding, threshold=0.75)
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("intelligence.reid_store")


@dataclass
class ReIDEntry:
    """A stored ReID embedding with metadata."""

    target_id: str
    embedding: list[float]
    camera_id: str = ""
    class_name: str = "person"
    timestamp: float = 0.0
    confidence: float = 0.0
    dossier_id: str = ""


@dataclass
class ReIDMatch:
    """Result of a ReID matching query."""

    target_id: str
    matched_target_id: str
    similarity: float
    camera_id: str = ""
    matched_camera_id: str = ""
    dossier_id: str = ""


class ReIDStore:
    """In-memory ReID embedding store for cross-camera identity matching.

    Thread-safe. Embeddings are stored with metadata (camera, class,
    timestamp) and can be queried for nearest-neighbor matches.

    Parameters
    ----------
    match_threshold:
        Cosine similarity threshold for a match (default 0.75).
    max_entries:
        Maximum embeddings to retain (default 1000).
    ttl_seconds:
        Time-to-live for entries (default 1 hour).
    """

    def __init__(
        self,
        match_threshold: float = 0.75,
        max_entries: int = 1000,
        ttl_seconds: float = 3600.0,
    ) -> None:
        self._threshold = match_threshold
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entries: list[ReIDEntry] = []
        self._total_added = 0
        self._total_matches = 0

    def add_embedding(
        self,
        target_id: str,
        embedding: list[float],
        camera_id: str = "",
        class_name: str = "person",
        confidence: float = 0.0,
        dossier_id: str = "",
    ) -> None:
        """Add a ReID embedding for a detection.

        Parameters
        ----------
        target_id:
            Unique detection ID (e.g., "det_person_1_cam01").
        embedding:
            Feature vector (normalized to unit length).
        camera_id:
            Camera that produced this detection.
        class_name:
            YOLO class name.
        confidence:
            Detection confidence.
        dossier_id:
            Associated dossier ID if known.
        """
        entry = ReIDEntry(
            target_id=target_id,
            embedding=embedding,
            camera_id=camera_id,
            class_name=class_name,
            timestamp=time.time(),
            confidence=confidence,
            dossier_id=dossier_id,
        )

        with self._lock:
            self._entries.append(entry)
            self._total_added += 1

            # Prune old entries
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]

    def find_matches(
        self,
        target_id: str,
        embedding: list[float],
        camera_id: str = "",
        class_name: str = "person",
        threshold: float | None = None,
        max_results: int = 5,
        cross_camera_only: bool = True,
    ) -> list[ReIDMatch]:
        """Find matching embeddings for a new detection.

        Parameters
        ----------
        target_id:
            ID of the new detection to match.
        embedding:
            Feature vector of the new detection.
        camera_id:
            Camera that produced the new detection.
        class_name:
            YOLO class name to filter by.
        threshold:
            Similarity threshold (overrides default).
        max_results:
            Maximum matches to return.
        cross_camera_only:
            If True, only match across different cameras.

        Returns
        -------
        List of ReIDMatch sorted by similarity (highest first).
        """
        thresh = threshold if threshold is not None else self._threshold
        now = time.time()
        matches: list[ReIDMatch] = []

        with self._lock:
            for entry in self._entries:
                # Skip self
                if entry.target_id == target_id:
                    continue

                # Skip same camera if cross_camera_only
                if cross_camera_only and camera_id and entry.camera_id == camera_id:
                    continue

                # Skip different classes
                if class_name and entry.class_name != class_name:
                    continue

                # Skip expired
                if now - entry.timestamp > self._ttl:
                    continue

                # Compute cosine similarity
                sim = _cosine_similarity(embedding, entry.embedding)
                if sim >= thresh:
                    matches.append(ReIDMatch(
                        target_id=target_id,
                        matched_target_id=entry.target_id,
                        similarity=sim,
                        camera_id=camera_id,
                        matched_camera_id=entry.camera_id,
                        dossier_id=entry.dossier_id,
                    ))

            if matches:
                self._total_matches += len(matches)

        # Sort by similarity descending
        matches.sort(key=lambda m: m.similarity, reverse=True)
        return matches[:max_results]

    def get_stats(self) -> dict[str, Any]:
        """Return store statistics."""
        with self._lock:
            cameras = set(e.camera_id for e in self._entries if e.camera_id)
            return {
                "total_entries": len(self._entries),
                "total_added": self._total_added,
                "total_matches": self._total_matches,
                "cameras": list(cameras),
                "max_entries": self._max_entries,
                "threshold": self._threshold,
            }

    def prune_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.time()
        with self._lock:
            before = len(self._entries)
            self._entries = [
                e for e in self._entries
                if now - e.timestamp <= self._ttl
            ]
            removed = before - len(self._entries)
        return removed


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or len(a) == 0:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


# Singleton
_store: Optional[ReIDStore] = None


def get_reid_store(**kwargs) -> ReIDStore:
    """Get or create the singleton ReIDStore."""
    global _store
    if _store is None:
        _store = ReIDStore(**kwargs)
    return _store
