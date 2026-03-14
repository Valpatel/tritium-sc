# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TargetCorrelator — multi-signal identity resolution engine.

Fuses detections from different sensors into composite targets using
weighted multi-strategy scoring. A camera sees a "person" at position X,
and a BLE scanner sees a phone MAC at position Y nearby. Multiple
correlation strategies evaluate the pair independently:

  1. Spatial proximity — targets within a configurable radius
  2. Temporal co-movement — same direction and speed over time
  3. Signal pattern matching — BLE/camera appear/disappear together
  4. Dossier lookup — known prior associations from DossierStore

Each strategy produces a score (0-1). A weighted sum determines final
correlation confidence. When correlated, targets are merged and a
TargetDossier is created/updated in DossierStore for persistent identity.

Optionally writes entity nodes and relationship edges into a KuzuDB graph
store (TritiumGraph) for graph traversal queries. If kuzu is not installed
or no graph_store is provided, graph writes are silently skipped.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field

from .correlation_strategies import (
    CorrelationStrategy,
    DossierStrategy,
    SignalPatternStrategy,
    SpatialStrategy,
    StrategyScore,
    TemporalStrategy,
)
from .dossier import DossierStore, TargetDossier
from .target_tracker import TargetTracker, TrackedTarget

logger = logging.getLogger("correlator")

# Map tracker asset_type values to graph node table names.
# Anything not listed falls back to "Device".
_ASSET_TYPE_TO_NODE: dict[str, str] = {
    "person": "Person",
    "vehicle": "Vehicle",
    "car": "Vehicle",
    "motorcycle": "Vehicle",
    "bicycle": "Vehicle",
    "ble_device": "Device",
    "rover": "Device",
    "drone": "Device",
    "turret": "Device",
}


def _node_type_for(asset_type: str) -> str:
    """Return the graph node table name for a tracker asset_type."""
    return _ASSET_TYPE_TO_NODE.get(asset_type, "Device")


@dataclass
class CorrelationRecord:
    """Record of a successful correlation between two targets."""

    primary_id: str
    secondary_id: str
    confidence: float
    reason: str
    timestamp: float = field(default_factory=time.monotonic)
    strategy_scores: list[StrategyScore] = field(default_factory=list)
    dossier_uuid: str = ""


# Default strategy weights — spatial dominates, others contribute
DEFAULT_WEIGHTS: dict[str, float] = {
    "spatial": 0.40,
    "temporal": 0.20,
    "signal_pattern": 0.20,
    "dossier": 0.20,
}


class TargetCorrelator:
    """Multi-strategy identity resolution engine.

    Runs a periodic loop that examines all tracked targets, evaluates
    each pair through multiple correlation strategies, and merges pairs
    that exceed the confidence threshold.
    """

    def __init__(
        self,
        tracker: TargetTracker,
        *,
        radius: float = 5.0,
        max_age: float = 30.0,
        interval: float = 5.0,
        confidence_threshold: float = 0.3,
        dossier_store: DossierStore | None = None,
        strategies: list[CorrelationStrategy] | None = None,
        weights: dict[str, float] | None = None,
        graph_store: object | None = None,
    ) -> None:
        """
        Args:
            tracker: The TargetTracker to read/write targets from.
            radius: Maximum distance between targets to consider correlation.
            max_age: Maximum age (seconds) for a target to be eligible.
            interval: How often the correlation loop runs (seconds).
            confidence_threshold: Minimum weighted score to trigger correlation.
            dossier_store: Optional DossierStore for persistent identity. Created
                automatically if not provided.
            strategies: Custom strategy list. If None, defaults are created.
            weights: Strategy name -> weight mapping. Defaults to DEFAULT_WEIGHTS.
            graph_store: Optional TritiumGraph instance for writing entity nodes
                and relationship edges. If None or kuzu not installed, graph
                writes are silently skipped.
        """
        self.tracker = tracker
        self.radius = radius
        self.max_age = max_age
        self.interval = interval
        self.confidence_threshold = confidence_threshold
        self.dossier_store = dossier_store or DossierStore()
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.graph_store = graph_store

        # Build strategies
        if strategies is not None:
            self.strategies = list(strategies)
        else:
            self.strategies = self._default_strategies()

        self._correlations: list[CorrelationRecord] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def _default_strategies(self) -> list[CorrelationStrategy]:
        """Create the default set of correlation strategies."""
        return [
            SpatialStrategy(radius=self.radius),
            TemporalStrategy(history=self.tracker.history),
            SignalPatternStrategy(),
            DossierStrategy(dossier_store=self.dossier_store),
        ]

    def correlate(self) -> list[CorrelationRecord]:
        """Run one correlation pass over all tracked targets.

        Returns a list of new CorrelationRecords for pairs that were fused.
        """
        targets = self.tracker.get_all()
        now = time.monotonic()

        # Filter to recent targets only
        recent = [t for t in targets if (now - t.last_seen) <= self.max_age]

        new_correlations: list[CorrelationRecord] = []
        consumed: set[str] = set()

        # Sort by confidence descending — higher-confidence targets become primary
        recent.sort(key=lambda t: t.position_confidence, reverse=True)

        for i, primary in enumerate(recent):
            if primary.target_id in consumed:
                continue
            for secondary in recent[i + 1 :]:
                if secondary.target_id in consumed:
                    continue

                # Source diversity — don't fuse same-sensor detections
                if primary.source == secondary.source:
                    continue

                # Evaluate all strategies
                scores = self._evaluate_pair(primary, secondary)
                weighted_confidence = self._weighted_score(scores)

                if weighted_confidence < self.confidence_threshold:
                    continue

                # Build reason string from contributing strategies
                contributing = [s for s in scores if s.score > 0]
                reason_parts = [f"{s.strategy_name}={s.score:.2f}" for s in contributing]
                reason = (
                    f"{primary.source}+{secondary.source} "
                    f"[{', '.join(reason_parts)}] "
                    f"combined={weighted_confidence:.2f}"
                )

                # Create/update dossier
                dossier = self.dossier_store.create_or_update(
                    signal_a=primary.target_id,
                    source_a=primary.source,
                    signal_b=secondary.target_id,
                    source_b=secondary.source,
                    confidence=weighted_confidence,
                    metadata={
                        "primary_name": primary.name,
                        "secondary_name": secondary.name,
                        "primary_type": primary.asset_type,
                        "secondary_type": secondary.asset_type,
                    },
                )

                # Write entity nodes and relationship edges to graph store
                self._write_graph(primary, secondary, weighted_confidence)

                record = CorrelationRecord(
                    primary_id=primary.target_id,
                    secondary_id=secondary.target_id,
                    confidence=weighted_confidence,
                    reason=reason,
                    strategy_scores=list(scores),
                    dossier_uuid=dossier.uuid,
                )
                new_correlations.append(record)
                consumed.add(secondary.target_id)

                # Merge secondary into primary
                self._merge(primary, secondary)

                # Remove the secondary from the tracker
                self.tracker.remove(secondary.target_id)

                logger.info(
                    "Correlated %s + %s -> dossier %s (confidence=%.2f)",
                    primary.target_id,
                    secondary.target_id,
                    dossier.uuid[:8],
                    weighted_confidence,
                )

        with self._lock:
            self._correlations.extend(new_correlations)

        return new_correlations

    def _evaluate_pair(
        self, target_a: TrackedTarget, target_b: TrackedTarget
    ) -> list[StrategyScore]:
        """Run all strategies against a target pair."""
        scores: list[StrategyScore] = []
        for strategy in self.strategies:
            try:
                score = strategy.evaluate(target_a, target_b)
                scores.append(score)
            except Exception as exc:
                logger.warning(
                    "Strategy %s failed for %s/%s: %s",
                    strategy.name,
                    target_a.target_id,
                    target_b.target_id,
                    exc,
                )
                scores.append(
                    StrategyScore(
                        strategy_name=strategy.name,
                        score=0.0,
                        detail=f"error: {exc}",
                    )
                )
        return scores

    def _weighted_score(self, scores: list[StrategyScore]) -> float:
        """Compute weighted combination of strategy scores.

        Strategies not present in the weights dict are ignored.
        The result is normalized by the sum of active weights.
        """
        total_weight = 0.0
        total_score = 0.0

        for s in scores:
            w = self.weights.get(s.strategy_name, 0.0)
            total_weight += w
            total_score += w * s.score

        if total_weight <= 0:
            return 0.0

        return min(1.0, total_score / total_weight)

    def get_correlations(self) -> list[CorrelationRecord]:
        """Return all correlation records."""
        with self._lock:
            return list(self._correlations)

    def _merge(self, primary: TrackedTarget, secondary: TrackedTarget) -> None:
        """Merge secondary target attributes into primary."""
        # Boost confidence
        primary.position_confidence = min(
            1.0,
            primary.position_confidence + secondary.position_confidence * 0.5,
        )

        # Update last_seen to the most recent
        primary.last_seen = max(primary.last_seen, secondary.last_seen)

        # Append source info to name if not already composite
        if secondary.source not in primary.name:
            primary.name = f"{primary.name} [{secondary.source}]"

        # If primary has low-quality position but secondary is better, use secondary
        if secondary.position_confidence > primary.position_confidence:
            primary.position = secondary.position
            primary.position_source = secondary.position_source

    def _write_graph(
        self,
        primary: TrackedTarget,
        secondary: TrackedTarget,
        confidence: float,
    ) -> None:
        """Write entity nodes and relationship edges into the graph store.

        Creates/updates entity nodes for both targets, then writes edges:
          - CORRELATED_WITH between the two entities (always)
          - CARRIES from device to person (BLE + camera person)
          - DETECTED_WITH between two BLE devices seen together

        Silently skips if graph_store is None or if any graph operation fails.
        """
        if self.graph_store is None:
            return

        try:
            graph = self.graph_store
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Determine node types
            primary_node = _node_type_for(primary.asset_type)
            secondary_node = _node_type_for(secondary.asset_type)

            # Create/update entity nodes
            graph.create_entity(
                entity_type=primary_node,
                id=primary.target_id,
                name=primary.name,
                properties={
                    "source": primary.source,
                    "asset_type": primary.asset_type,
                },
                confidence=primary.position_confidence,
            )
            graph.create_entity(
                entity_type=secondary_node,
                id=secondary.target_id,
                name=secondary.name,
                properties={
                    "source": secondary.source,
                    "asset_type": secondary.asset_type,
                },
                confidence=secondary.position_confidence,
            )

            # Always write CORRELATED_WITH
            graph.add_relationship(
                from_id=primary.target_id,
                to_id=secondary.target_id,
                rel_type="CORRELATED_WITH",
                properties={
                    "timestamp": now_iso,
                    "confidence": confidence,
                    "source": f"{primary.source}+{secondary.source}",
                    "count": 1,
                },
            )

            # BLE device correlated with camera person -> CARRIES (device->person)
            source_pair = frozenset((primary.source, secondary.source))
            type_pair = frozenset((primary.asset_type, secondary.asset_type))

            if source_pair == frozenset(("ble", "yolo")) and "person" in type_pair:
                # Identify which is device and which is person
                if primary.asset_type == "person":
                    device, person = secondary, primary
                else:
                    device, person = primary, secondary
                graph.add_relationship(
                    from_id=device.target_id,
                    to_id=person.target_id,
                    rel_type="CARRIES",
                    properties={
                        "timestamp": now_iso,
                        "confidence": confidence,
                        "source": "correlator",
                        "count": 1,
                    },
                )

            # Two BLE devices correlated -> DETECTED_WITH
            if primary.source == "ble" and secondary.source == "ble":
                graph.add_relationship(
                    from_id=primary.target_id,
                    to_id=secondary.target_id,
                    rel_type="DETECTED_WITH",
                    properties={
                        "timestamp": now_iso,
                        "confidence": confidence,
                        "source": "correlator",
                        "count": 1,
                    },
                )

            logger.debug(
                "Graph: wrote %s(%s) -[CORRELATED_WITH]-> %s(%s)",
                primary_node,
                primary.target_id,
                secondary_node,
                secondary.target_id,
            )

        except Exception as exc:
            logger.warning("Graph write failed (non-fatal): %s", exc)

    def _loop(self) -> None:
        """Background correlation loop."""
        while self._running:
            self.correlate()
            time.sleep(self.interval)

    def start(self) -> None:
        """Start the periodic correlation loop."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="correlator", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the periodic correlation loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
            self._thread = None


def start_correlator(tracker: TargetTracker, **kwargs) -> TargetCorrelator:
    """Create and start a TargetCorrelator.

    Args:
        tracker: The TargetTracker instance to correlate against.
        **kwargs: Passed to TargetCorrelator constructor (radius, max_age, interval).

    Returns:
        The running TargetCorrelator instance.
    """
    correlator = TargetCorrelator(tracker, **kwargs)
    correlator.start()
    return correlator


def stop_correlator(correlator: TargetCorrelator) -> None:
    """Stop a running TargetCorrelator."""
    correlator.stop()
