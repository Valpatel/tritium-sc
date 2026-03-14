# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ReID integration for the YOLO Detector plugin.

When YOLO detects a person or vehicle, this module extracts a stub feature
embedding from the detection crop, stores it in the ReIDStore, and searches
for cross-camera matches via cosine similarity.  Matches are linked to the
same target dossier.

The embedding extractor is a stub (random vector) until a real model
(e.g., OSNet, FastReID) is integrated.  The pipeline is fully wired so
swapping in a real extractor requires only replacing extract_embedding().
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from typing import Any, Optional

log = logging.getLogger("yolo-detector.reid")

# Embedding dimension for the stub extractor
EMBEDDING_DIM = 128

# Minimum cosine similarity to consider a match
REID_THRESHOLD = 0.70


def extract_embedding(
    frame: Any,
    bbox: tuple[int, int, int, int],
) -> list[float]:
    """Extract an appearance feature embedding from a detection crop.

    This is a STUB implementation that generates a deterministic pseudo-random
    vector based on the bounding box center region pixel statistics.  Replace
    with a real embedding model (OSNet, FastReID, etc.) for production use.

    Args:
        frame: BGR image as numpy array.
        bbox: Bounding box (x1, y1, x2, y2).

    Returns:
        Feature vector of length EMBEDDING_DIM.
    """
    try:
        import numpy as np
        x1, y1, x2, y2 = bbox
        # Crop the detection region
        crop = frame[max(0, y1):max(1, y2), max(0, x1):max(1, x2)]
        if crop.size == 0:
            return [0.0] * EMBEDDING_DIM

        # Generate a pseudo-embedding from crop statistics
        # This gives some discrimination between very different crops
        # but is NOT a real appearance model
        h, w = crop.shape[:2]
        # Divide crop into grid cells and compute mean per cell
        grid_h = max(1, h // 4)
        grid_w = max(1, w // 4)
        features = []
        for gy in range(4):
            for gx in range(4):
                cell = crop[gy * grid_h:(gy + 1) * grid_h,
                            gx * grid_w:(gx + 1) * grid_w]
                if cell.size > 0:
                    features.extend([
                        float(cell[:, :, 0].mean()) / 255.0,
                        float(cell[:, :, 1].mean()) / 255.0,
                        float(cell[:, :, 2].mean()) / 255.0,
                    ])
                else:
                    features.extend([0.0, 0.0, 0.0])

        # Pad or truncate to EMBEDDING_DIM
        while len(features) < EMBEDDING_DIM:
            features.append(0.0)
        features = features[:EMBEDDING_DIM]

        # L2 normalize
        norm = sum(f * f for f in features) ** 0.5
        if norm > 0:
            features = [f / norm for f in features]

        return features
    except Exception as exc:
        log.debug("Embedding extraction failed: %s", exc)
        return [0.0] * EMBEDDING_DIM


class ReIDIntegration:
    """Wires YOLO detections to the ReIDStore for cross-camera matching.

    On each person/vehicle detection:
      1. Extract embedding from the detection crop
      2. Search ReIDStore for similar embeddings from other cameras
      3. If match found, record it and link to same dossier
      4. Store the new embedding

    Parameters
    ----------
    reid_store:
        A ReIDStore instance (from tritium_lib.store).
    dossier_store:
        Optional DossierStore for linking matched targets.
    threshold:
        Minimum cosine similarity for a match (0.0 to 1.0).
    """

    def __init__(
        self,
        reid_store: Any,
        dossier_store: Any = None,
        threshold: float = REID_THRESHOLD,
    ) -> None:
        self._store = reid_store
        self._dossier_store = dossier_store
        self._threshold = threshold
        self._match_count = 0
        self._embedding_count = 0

    def process_detection(
        self,
        frame: Any,
        detection: dict,
        source_camera: str,
    ) -> Optional[dict]:
        """Process a single YOLO detection for ReID.

        Args:
            frame: BGR image (numpy array).
            detection: Detection dict with 'bbox', 'class_name', 'confidence'.
            source_camera: Camera ID that produced this detection.

        Returns:
            Match dict if a cross-camera match was found, else None.
            Match dict: {
                'matched_target_id': str,
                'similarity': float,
                'source_camera': str,
                'matched_camera': str,
                'embedding_id': str,
            }
        """
        class_name = detection.get("class_name", "")
        if class_name not in ("person", "car", "truck", "bus", "motorcycle"):
            return None

        bbox = detection.get("bbox")
        if not bbox or len(bbox) != 4:
            return None

        confidence = detection.get("confidence", 0.0)

        # Extract embedding
        embedding = extract_embedding(frame, tuple(bbox))
        if all(v == 0.0 for v in embedding):
            return None

        # Generate target ID for this detection
        cx, cy = detection.get("center", (0, 0))
        target_id = f"yolo-{class_name}-{source_camera}-{cx}-{cy}"

        # Search for matches from OTHER cameras
        matches = self._store.find_similar(
            embedding, threshold=self._threshold, limit=5
        )

        best_match = None
        for m in matches:
            # Skip matches from the same camera (same-frame duplicates)
            if m["source_camera"] == source_camera:
                continue
            best_match = m
            break

        # Store the new embedding
        emb_id = self._store.store_embedding(
            target_id=target_id,
            embedding_vector=embedding,
            source_camera=source_camera,
            confidence=confidence,
        )
        self._embedding_count += 1

        if best_match is not None:
            # Record the match
            self._store.record_match(
                query_embedding_id=emb_id,
                matched_embedding_id=best_match["embedding_id"],
                similarity=best_match["similarity"],
            )
            self._match_count += 1

            log.info(
                "ReID match: %s (cam %s) <-> %s (cam %s) sim=%.3f",
                target_id, source_camera,
                best_match["target_id"], best_match["source_camera"],
                best_match["similarity"],
            )

            # Link dossiers if dossier store is available
            if self._dossier_store is not None:
                try:
                    self._dossier_store.link_targets(
                        target_id, best_match["target_id"]
                    )
                except Exception:
                    pass  # Dossier store API may vary

            return {
                "matched_target_id": best_match["target_id"],
                "similarity": best_match["similarity"],
                "source_camera": source_camera,
                "matched_camera": best_match["source_camera"],
                "embedding_id": emb_id,
            }

        return None

    def process_frame_detections(
        self,
        frame: Any,
        detections: list[dict],
        source_camera: str,
    ) -> list[dict]:
        """Process all detections from a single frame.

        Returns list of match dicts for detections that found cross-camera matches.
        """
        matches = []
        for det in detections:
            result = self.process_detection(frame, det, source_camera)
            if result is not None:
                matches.append(result)
        return matches

    @property
    def stats(self) -> dict:
        """Return ReID statistics."""
        return {
            "embeddings_stored": self._embedding_count,
            "matches_found": self._match_count,
            "threshold": self._threshold,
            "total_in_store": self._store.count_embeddings(),
            "total_matches": self._store.count_matches(),
        }
