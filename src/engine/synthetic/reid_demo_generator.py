# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ReID cross-camera matching demo generator.

Simulates a person moving from camera A's FOV to camera B's FOV.
Generates synthetic detection events with similar embeddings, so the
ReID store matches them and the DossierManager merges their dossiers.

The simulation:
1. Person appears in cam-A at tick 0-5 with embedding E
2. Person disappears from cam-A at tick 5
3. Person appears in cam-B at tick 6-10 with embedding E + noise
4. ReID store matches cam-B detection to cam-A detection
5. DossierManager merges the two dossiers

This demonstrates Tritium's ability to track entities across camera
boundaries without requiring the same camera to see both.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

logger = logging.getLogger("synthetic.reid_demo")

# Embedding dimension for synthetic ReID vectors
EMBED_DIM = 64


def _normalize(vec: list[float]) -> list[float]:
    """Normalize a vector to unit length."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def _generate_embedding(seed: int) -> list[float]:
    """Generate a deterministic synthetic embedding from a seed.

    Same seed = same identity = similar embedding.
    """
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(EMBED_DIM)]
    return _normalize(vec)


def _add_noise(embedding: list[float], noise_level: float = 0.05) -> list[float]:
    """Add small noise to an embedding (simulates appearance variation)."""
    noisy = [x + random.gauss(0, noise_level) for x in embedding]
    return _normalize(noisy)


class ReIDDemoGenerator:
    """Generates cross-camera ReID matching scenarios in demo mode.

    Creates synthetic person detections that move from camera A to
    camera B, with similar embeddings that the ReID store should match.

    Parameters
    ----------
    interval:
        Seconds between ticks.
    event_bus:
        EventBus for publishing detection events.
    num_persons:
        Number of simulated persons to track across cameras.
    """

    def __init__(
        self,
        interval: float = 2.0,
        event_bus: Optional[EventBus] = None,
        num_persons: int = 2,
    ) -> None:
        self._interval = interval
        self._event_bus = event_bus
        self._num_persons = num_persons
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tick_count = 0
        self._reid_store: Any = None
        self._matches_found: int = 0

    @property
    def running(self) -> bool:
        return self._running

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def matches_found(self) -> int:
        return self._matches_found

    def start(self) -> None:
        """Start the ReID demo generator."""
        if self._running:
            return

        # Get ReID store
        try:
            from engine.intelligence.reid_store import get_reid_store
            self._reid_store = get_reid_store()
        except Exception as exc:
            logger.warning("ReID store not available: %s", exc)

        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name="reid-demo-gen",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "ReID demo generator started: %d persons, %.1fs interval",
            self._num_persons, self._interval,
        )

    def stop(self) -> None:
        """Stop the generator."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._interval + 1)
            self._thread = None
        logger.info(
            "ReID demo stopped: %d ticks, %d matches found",
            self._tick_count, self._matches_found,
        )

    def _loop(self) -> None:
        """Background generation loop."""
        while self._running:
            try:
                self._generate_tick()
                self._tick_count += 1
            except Exception as exc:
                logger.warning("ReID demo tick failed: %s", exc)
            time.sleep(self._interval)

    def _generate_tick(self) -> None:
        """Generate one tick of the cross-camera scenario."""
        if self._event_bus is None:
            return

        for person_idx in range(self._num_persons):
            # Each person has a cycle of 12 ticks:
            # Ticks 0-4: visible in cam-A
            # Tick 5: transition (not visible)
            # Ticks 6-10: visible in cam-B
            # Tick 11: transition (not visible)
            cycle_tick = (self._tick_count + person_idx * 3) % 12

            person_seed = 42000 + person_idx
            base_embedding = _generate_embedding(person_seed)

            person_label = f"demo_reid_person_{person_idx}"

            if cycle_tick <= 4:
                # Visible in camera A
                cam_id = "demo-cam-A"
                target_id = f"det_person_{person_label}_camA"
                noisy_embedding = _add_noise(base_embedding, noise_level=0.03)

                # Position within camera A FOV
                x = 100.0 + person_idx * 30.0 + cycle_tick * 5.0
                y = 200.0 + person_idx * 20.0

                self._publish_detection(
                    target_id=target_id,
                    camera_id=cam_id,
                    class_name="person",
                    embedding=noisy_embedding,
                    x=x, y=y,
                    confidence=0.85 + random.uniform(-0.05, 0.05),
                )

            elif cycle_tick >= 6 and cycle_tick <= 10:
                # Visible in camera B
                cam_id = "demo-cam-B"
                target_id = f"det_person_{person_label}_camB"
                noisy_embedding = _add_noise(base_embedding, noise_level=0.04)

                # Position within camera B FOV (different location)
                x = 300.0 + person_idx * 30.0 + (cycle_tick - 6) * 5.0
                y = 250.0 + person_idx * 20.0

                self._publish_detection(
                    target_id=target_id,
                    camera_id=cam_id,
                    class_name="person",
                    embedding=noisy_embedding,
                    x=x, y=y,
                    confidence=0.82 + random.uniform(-0.05, 0.05),
                )

                # Try ReID matching against camera A embeddings
                if self._reid_store is not None:
                    matches = self._reid_store.find_matches(
                        target_id=target_id,
                        embedding=noisy_embedding,
                        camera_id=cam_id,
                        class_name="person",
                        cross_camera_only=True,
                    )

                    for match in matches:
                        self._matches_found += 1
                        logger.info(
                            "ReID match: %s <-> %s (sim=%.3f, cams=%s/%s)",
                            match.target_id, match.matched_target_id,
                            match.similarity, match.camera_id,
                            match.matched_camera_id,
                        )

                        # Publish correlation event for DossierManager merge
                        if self._event_bus is not None:
                            self._event_bus.publish("correlation", {
                                "primary_id": match.matched_target_id,
                                "secondary_id": match.target_id,
                                "confidence": match.similarity,
                                "reason": f"ReID cross-camera match (sim={match.similarity:.3f})",
                                "primary_name": match.matched_target_id,
                                "secondary_name": match.target_id,
                            })

    def _publish_detection(
        self,
        target_id: str,
        camera_id: str,
        class_name: str,
        embedding: list[float],
        x: float,
        y: float,
        confidence: float,
    ) -> None:
        """Publish a detection event and add embedding to ReID store."""
        # Add to ReID store
        if self._reid_store is not None:
            self._reid_store.add_embedding(
                target_id=target_id,
                embedding=embedding,
                camera_id=camera_id,
                class_name=class_name,
                confidence=confidence,
            )

        # Publish detection event
        if self._event_bus is not None:
            self._event_bus.publish("detection:camera:fusion", {
                "detections": [{
                    "target_id": target_id,
                    "class_name": class_name,
                    "confidence": confidence,
                    "bbox": [int(x), int(y), int(x + 60), int(y + 120)],
                    "camera_id": camera_id,
                }],
                "camera_id": camera_id,
                "source": "reid_demo",
            })

    def get_stats(self) -> dict[str, Any]:
        """Return generator statistics."""
        stats = {
            "running": self._running,
            "tick_count": self._tick_count,
            "num_persons": self._num_persons,
            "matches_found": self._matches_found,
            "interval": self._interval,
        }
        if self._reid_store is not None:
            stats["reid_store"] = self._reid_store.get_stats()
        return stats
