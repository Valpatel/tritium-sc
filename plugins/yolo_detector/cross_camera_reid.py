# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Cross-camera re-identification service.

When a target disappears from one camera and appears on another, uses the
ReID embedding store to match them by visual similarity. If the cosine
similarity exceeds the threshold (default 0.7), merges both detections
into the same dossier.

This module bridges the HandoffTracker (departure/arrival events) with the
ReIDStore (embedding similarity search) and the DossierStore (identity
merging). It listens for handoff events and triggers ReID matching.

Flow:
    1. HandoffTracker detects target departure from camera A
    2. HandoffTracker detects similar target arrival at camera B
    3. CrossCameraReID retrieves embeddings for both detections
    4. Computes cosine similarity between the embeddings
    5. If similarity > threshold, merges dossiers and publishes event
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("cross_camera_reid")

# Default cosine similarity threshold for cross-camera match
CROSS_CAMERA_THRESHOLD = 0.70

# Maximum embeddings to compare per handoff event
MAX_COMPARE_EMBEDDINGS = 5


class CrossCameraReID:
    """Bridges handoff events with ReID embedding matching.

    Subscribes to handoff events from the HandoffTracker. For each handoff,
    retrieves the most recent embeddings from both the departure camera and
    arrival camera, computes similarity, and merges dossiers on match.

    Parameters
    ----------
    reid_store:
        ReIDStore instance for embedding lookup and similarity search.
    dossier_store:
        Optional DossierStore for merging matched target identities.
    event_bus:
        Optional EventBus for publishing match events.
    threshold:
        Minimum cosine similarity to consider a cross-camera match.
    """

    def __init__(
        self,
        reid_store: Any,
        dossier_store: Any = None,
        event_bus: Any = None,
        threshold: float = CROSS_CAMERA_THRESHOLD,
    ) -> None:
        self._reid_store = reid_store
        self._dossier_store = dossier_store
        self._event_bus = event_bus
        self._threshold = threshold

        # Metrics
        self._handoffs_processed = 0
        self._matches_found = 0
        self._dossiers_merged = 0
        self._lock = threading.Lock()

    def on_handoff(self, handoff_event: Any) -> Optional[dict]:
        """Process a handoff event for cross-camera ReID matching.

        Called by the HandoffTracker's on_handoff callback. Retrieves
        embeddings from both cameras and attempts to match.

        Args:
            handoff_event: HandoffEvent dataclass or dict with
                target_id, from_sensor, to_sensor, departure_time,
                arrival_time, gap_seconds.

        Returns:
            Match result dict if a cross-camera match was found, else None.
        """
        # Accept both dataclass and dict
        if hasattr(handoff_event, "to_dict"):
            he = handoff_event
            target_id = he.target_id
            from_sensor = he.from_sensor
            to_sensor = he.to_sensor
            gap_seconds = he.gap_seconds
            confidence = he.confidence
        elif isinstance(handoff_event, dict):
            target_id = handoff_event.get("target_id", "")
            from_sensor = handoff_event.get("from_sensor", "")
            to_sensor = handoff_event.get("to_sensor", "")
            gap_seconds = handoff_event.get("gap_seconds", 0.0)
            confidence = handoff_event.get("confidence", 0.0)
        else:
            return None

        with self._lock:
            self._handoffs_processed += 1

        if not target_id or not from_sensor or not to_sensor:
            return None

        # Get recent embeddings from the departure camera
        departure_embeddings = self._get_camera_embeddings(
            from_sensor, limit=MAX_COMPARE_EMBEDDINGS,
        )
        # Get recent embeddings from the arrival camera
        arrival_embeddings = self._get_camera_embeddings(
            to_sensor, limit=MAX_COMPARE_EMBEDDINGS,
        )

        if not departure_embeddings or not arrival_embeddings:
            logger.debug(
                "No embeddings for handoff %s -> %s (dep=%d, arr=%d)",
                from_sensor, to_sensor,
                len(departure_embeddings), len(arrival_embeddings),
            )
            return None

        # Find best cross-camera match
        best_match = self._find_best_match(
            departure_embeddings, arrival_embeddings,
        )

        if best_match is None:
            return None

        dep_emb, arr_emb, similarity = best_match

        if similarity < self._threshold:
            return None

        with self._lock:
            self._matches_found += 1

        dep_target = dep_emb.get("target_id", "")
        arr_target = arr_emb.get("target_id", "")

        logger.info(
            "Cross-camera ReID match: %s (cam %s) <-> %s (cam %s) sim=%.3f",
            dep_target, from_sensor, arr_target, to_sensor, similarity,
        )

        # Merge dossiers if store is available
        merged = False
        if self._dossier_store is not None:
            try:
                merged = self._dossier_store.merge_dossiers(dep_target, arr_target)
                if merged:
                    with self._lock:
                        self._dossiers_merged += 1
                    logger.info(
                        "Dossiers merged: %s + %s (sim=%.3f)",
                        dep_target, arr_target, similarity,
                    )
            except Exception as exc:
                logger.debug("Dossier merge failed: %s", exc)

        # Build correlation evidence if available
        try:
            from tritium_lib.models.correlation_evidence import (
                build_visual_evidence,
                build_handoff_evidence,
            )
            visual_ev = build_visual_evidence(
                dep_target, arr_target,
                similarity=similarity,
                camera_a=from_sensor,
                camera_b=to_sensor,
                source="cross_camera_reid",
            )
            handoff_ev = build_handoff_evidence(
                dep_target, arr_target,
                from_sensor=from_sensor,
                to_sensor=to_sensor,
                gap_seconds=gap_seconds,
                source="cross_camera_reid",
            )
            evidence = [visual_ev.model_dump(), handoff_ev.model_dump()]
        except ImportError:
            evidence = []

        result = {
            "departure_target": dep_target,
            "arrival_target": arr_target,
            "from_camera": from_sensor,
            "to_camera": to_sensor,
            "similarity": round(similarity, 4),
            "gap_seconds": round(gap_seconds, 2),
            "dossier_merged": merged,
            "evidence": evidence,
        }

        # Publish event
        if self._event_bus is not None:
            self._event_bus.publish("cross_camera_reid_match", result)

        return result

    def _get_camera_embeddings(
        self, camera_id: str, limit: int = 5,
    ) -> list[dict]:
        """Get recent embeddings from a specific camera.

        Queries the ReID store for all embeddings from this camera,
        returning the most recent ones.
        """
        try:
            # Use the store's query methods to find embeddings by camera
            rows = self._reid_store._conn.execute(
                """SELECT embedding_id, target_id, embedding, source_camera,
                          timestamp, confidence
                   FROM reid_embeddings
                   WHERE source_camera = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (camera_id, limit),
            ).fetchall()

            from tritium_lib.store.reid import _blob_to_vector
            return [
                {
                    "embedding_id": r["embedding_id"],
                    "target_id": r["target_id"],
                    "embedding": _blob_to_vector(r["embedding"]),
                    "source_camera": r["source_camera"],
                    "timestamp": r["timestamp"],
                    "confidence": r["confidence"],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.debug("Failed to get camera embeddings: %s", exc)
            return []

    def _find_best_match(
        self,
        departure_embeddings: list[dict],
        arrival_embeddings: list[dict],
    ) -> Optional[tuple[dict, dict, float]]:
        """Find the best embedding match between two sets.

        Returns:
            Tuple of (departure_emb, arrival_emb, similarity) or None.
        """
        try:
            from tritium_lib.store.reid import cosine_similarity
        except ImportError:
            return None

        best_sim = 0.0
        best_dep = None
        best_arr = None

        for dep in departure_embeddings:
            dep_vec = dep.get("embedding", [])
            if not dep_vec:
                continue
            for arr in arrival_embeddings:
                arr_vec = arr.get("embedding", [])
                if not arr_vec or len(arr_vec) != len(dep_vec):
                    continue

                sim = cosine_similarity(dep_vec, arr_vec)
                if sim > best_sim:
                    best_sim = sim
                    best_dep = dep
                    best_arr = arr

        if best_dep is not None and best_arr is not None:
            return (best_dep, best_arr, best_sim)
        return None

    @property
    def stats(self) -> dict:
        """Return cross-camera ReID statistics."""
        with self._lock:
            return {
                "handoffs_processed": self._handoffs_processed,
                "matches_found": self._matches_found,
                "dossiers_merged": self._dossiers_merged,
                "threshold": self._threshold,
            }
