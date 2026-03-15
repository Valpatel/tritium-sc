# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Correlation strategies for multi-factor identity resolution.

Each strategy evaluates a pair of tracked targets and produces a score
from 0.0 (no correlation) to 1.0 (definite same entity). The correlator
combines strategy scores with configurable weights.

Strategies:
  - SpatialStrategy: distance-based proximity
  - TemporalStrategy: co-movement detection from position history
  - SignalPatternStrategy: appearance/disappearance timing correlation
  - DossierStrategy: known prior associations from DossierStore
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .target_history import TargetHistory
from .target_tracker import TrackedTarget


@dataclass(slots=True)
class StrategyScore:
    """Result of a single strategy evaluation."""

    strategy_name: str
    score: float  # 0.0 to 1.0
    detail: str  # human-readable explanation


class CorrelationStrategy(ABC):
    """Abstract base class for correlation strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short name identifying this strategy."""

    @abstractmethod
    def evaluate(
        self,
        target_a: TrackedTarget,
        target_b: TrackedTarget,
    ) -> StrategyScore:
        """Evaluate correlation strength between two targets.

        Args:
            target_a: First target.
            target_b: Second target.

        Returns:
            StrategyScore with score in [0.0, 1.0] and explanatory detail.
        """


class SpatialStrategy(CorrelationStrategy):
    """Distance-based spatial proximity scoring.

    Score is 1.0 when targets overlap (distance=0) and decays linearly
    to 0.0 at the configured radius.
    """

    def __init__(self, radius: float = 5.0) -> None:
        self.radius = radius

    @property
    def name(self) -> str:
        return "spatial"

    def evaluate(
        self,
        target_a: TrackedTarget,
        target_b: TrackedTarget,
    ) -> StrategyScore:
        dx = target_a.position[0] - target_b.position[0]
        dy = target_a.position[1] - target_b.position[1]
        dist = math.hypot(dx, dy)

        if dist > self.radius:
            return StrategyScore(
                strategy_name=self.name,
                score=0.0,
                detail=f"distance {dist:.1f} exceeds radius {self.radius}",
            )

        # Score: 1.0 at dist=0, decays but stays positive at boundary
        score = max(0.0, 1.0 - (dist / (self.radius * 1.1)))
        return StrategyScore(
            strategy_name=self.name,
            score=score,
            detail=f"distance {dist:.1f}/{self.radius} units",
        )


class TemporalStrategy(CorrelationStrategy):
    """Co-movement detection from target position history.

    Compares the direction and speed of two targets over recent history.
    If both targets have been moving in the same direction at similar speed,
    they are likely the same physical entity (e.g., a phone in someone's
    pocket moves with the person).

    Requires at least 3 position records per target.
    """

    def __init__(
        self,
        history: TargetHistory,
        *,
        min_samples: int = 3,
        heading_tolerance: float = 45.0,
        speed_ratio_max: float = 3.0,
    ) -> None:
        """
        Args:
            history: TargetHistory instance to read position trails.
            min_samples: Minimum history records needed to evaluate.
            heading_tolerance: Max heading difference (degrees) for co-movement.
            speed_ratio_max: Max speed ratio before penalizing (faster/slower).
        """
        self.history = history
        self.min_samples = min_samples
        self.heading_tolerance = heading_tolerance
        self.speed_ratio_max = speed_ratio_max

    @property
    def name(self) -> str:
        return "temporal"

    def evaluate(
        self,
        target_a: TrackedTarget,
        target_b: TrackedTarget,
    ) -> StrategyScore:
        trail_a = self.history.get_trail(target_a.target_id, max_points=20)
        trail_b = self.history.get_trail(target_b.target_id, max_points=20)

        if len(trail_a) < self.min_samples or len(trail_b) < self.min_samples:
            return StrategyScore(
                strategy_name=self.name,
                score=0.0,
                detail=f"insufficient history ({len(trail_a)}/{len(trail_b)} samples)",
            )

        # Compute heading (direction of movement)
        heading_a = self._compute_heading(trail_a)
        heading_b = self._compute_heading(trail_b)

        # Compute speed
        speed_a = self._compute_speed(trail_a)
        speed_b = self._compute_speed(trail_b)

        # Heading similarity: angular difference
        heading_diff = abs(heading_a - heading_b)
        if heading_diff > 180.0:
            heading_diff = 360.0 - heading_diff

        # Both stationary is not strong evidence of co-movement
        if speed_a < 0.01 and speed_b < 0.01:
            return StrategyScore(
                strategy_name=self.name,
                score=0.0,
                detail="both targets stationary",
            )

        # Heading score: 1.0 when perfectly aligned, 0.0 at tolerance
        if heading_diff > self.heading_tolerance:
            heading_score = 0.0
        else:
            heading_score = 1.0 - (heading_diff / self.heading_tolerance)

        # Speed similarity score
        max_speed = max(speed_a, speed_b)
        min_speed = min(speed_a, speed_b)
        if min_speed < 0.01:
            # One moving, one not — low score
            speed_score = 0.1
        else:
            ratio = max_speed / min_speed
            if ratio > self.speed_ratio_max:
                speed_score = 0.0
            else:
                speed_score = 1.0 - ((ratio - 1.0) / (self.speed_ratio_max - 1.0))

        score = 0.6 * heading_score + 0.4 * speed_score
        return StrategyScore(
            strategy_name=self.name,
            score=min(1.0, max(0.0, score)),
            detail=(
                f"heading diff {heading_diff:.0f}deg, "
                f"speed {speed_a:.2f}/{speed_b:.2f} u/s"
            ),
        )

    @staticmethod
    def _compute_heading(trail: list[tuple[float, float, float]]) -> float:
        """Compute overall heading from trail (degrees, 0=north, clockwise)."""
        if len(trail) < 2:
            return 0.0
        dx = trail[-1][0] - trail[0][0]
        dy = trail[-1][1] - trail[0][1]
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return 0.0
        return math.degrees(math.atan2(dx, dy)) % 360

    @staticmethod
    def _compute_speed(trail: list[tuple[float, float, float]]) -> float:
        """Compute average speed from trail in units/second."""
        if len(trail) < 2:
            return 0.0
        total_dist = 0.0
        for i in range(1, len(trail)):
            dx = trail[i][0] - trail[i - 1][0]
            dy = trail[i][1] - trail[i - 1][1]
            total_dist += math.hypot(dx, dy)
        dt = trail[-1][2] - trail[0][2]
        if dt <= 0:
            return 0.0
        return total_dist / dt


class SignalPatternStrategy(CorrelationStrategy):
    """Appearance/disappearance timing correlation.

    If a BLE signal appears around the same time a camera detection appears,
    or if both disappear together, they are likely the same entity.

    Evaluates temporal overlap: how close are the first_seen and last_seen
    times of both targets? Tighter temporal coupling = higher score.
    """

    def __init__(self, *, appearance_window: float = 10.0) -> None:
        """
        Args:
            appearance_window: Maximum time difference (seconds) between
                target appearances to score positively.
        """
        self.appearance_window = appearance_window

    @property
    def name(self) -> str:
        return "signal_pattern"

    def evaluate(
        self,
        target_a: TrackedTarget,
        target_b: TrackedTarget,
    ) -> StrategyScore:
        # Source diversity required — same-source patterns are meaningless
        if target_a.source == target_b.source:
            return StrategyScore(
                strategy_name=self.name,
                score=0.0,
                detail="same source type, signal pattern N/A",
            )

        # Temporal co-presence: both were seen recently at similar times
        time_diff = abs(target_a.last_seen - target_b.last_seen)

        if time_diff > self.appearance_window:
            return StrategyScore(
                strategy_name=self.name,
                score=0.0,
                detail=f"last_seen diff {time_diff:.1f}s exceeds window",
            )

        # Score decays linearly with time difference
        score = 1.0 - (time_diff / self.appearance_window)

        # Bonus for cross-sensor type (BLE+camera is strongest signal)
        source_pair = frozenset((target_a.source, target_b.source))
        if source_pair == frozenset(("ble", "yolo")):
            score = min(1.0, score * 1.2)

        return StrategyScore(
            strategy_name=self.name,
            score=min(1.0, max(0.0, score)),
            detail=f"last_seen diff {time_diff:.1f}s, sources {target_a.source}+{target_b.source}",
        )


class WiFiProbeStrategy(CorrelationStrategy):
    """WiFi probe request correlation with BLE detections.

    When a BLE device and a WiFi probe request are seen at the same time
    from the same observer (edge node), they are very likely the same
    physical device. A phone's WiFi radio sends probe requests while its
    BLE radio advertises — both originate from the same hardware.

    This strategy strengthens correlation for BLE+WiFi probe pairs seen
    within a tight time window, especially from the same edge observer.
    """

    def __init__(self, *, max_window: float = 10.0) -> None:
        """
        Args:
            max_window: Maximum time difference (seconds) between
                BLE and WiFi probe detections to score positively.
        """
        self.max_window = max_window

    @property
    def name(self) -> str:
        return "wifi_probe"

    def evaluate(
        self,
        target_a: TrackedTarget,
        target_b: TrackedTarget,
    ) -> StrategyScore:
        # Only evaluate BLE + WiFi probe pairs
        sources = frozenset((target_a.source, target_b.source))
        if sources != frozenset(("ble", "wifi_probe")):
            return StrategyScore(
                strategy_name=self.name,
                score=0.0,
                detail="not a BLE+wifi_probe pair",
            )

        # Temporal proximity
        time_diff = abs(target_a.last_seen - target_b.last_seen)
        if time_diff > self.max_window:
            return StrategyScore(
                strategy_name=self.name,
                score=0.0,
                detail=f"time diff {time_diff:.1f}s exceeds window {self.max_window}s",
            )

        # Base score from temporal proximity
        score = 1.0 - (time_diff / self.max_window)

        # Same observer bonus: much stronger signal if same edge node saw both
        observer_a = getattr(target_a, "observer_id", "")
        observer_b = getattr(target_b, "observer_id", "")
        same_observer = bool(observer_a and observer_a == observer_b)
        if same_observer:
            score = min(1.0, score * 1.3)

        # RSSI similarity bonus: if both have similar RSSI, likely same device
        rssi_a = getattr(target_a, "rssi", None)
        rssi_b = getattr(target_b, "rssi", None)
        if rssi_a is not None and rssi_b is not None:
            rssi_diff = abs(float(rssi_a) - float(rssi_b))
            if rssi_diff < 15:
                score = min(1.0, score * 1.1)

        detail = (
            f"BLE+wifi_probe dt={time_diff:.1f}s"
            f"{' same_observer' if same_observer else ''}"
        )

        return StrategyScore(
            strategy_name=self.name,
            score=min(1.0, max(0.0, score)),
            detail=detail,
        )


class DossierStrategy(CorrelationStrategy):
    """Check DossierStore for known prior associations.

    If these two targets (or their signal IDs) were previously correlated
    and stored in a dossier, this strategy returns a high score — they
    are known to be the same entity.
    """

    def __init__(self, dossier_store: "DossierStore") -> None:
        from .dossier import DossierStore as _DS
        self._store: _DS = dossier_store

    @property
    def name(self) -> str:
        return "dossier"

    def evaluate(
        self,
        target_a: TrackedTarget,
        target_b: TrackedTarget,
    ) -> StrategyScore:
        dossier = self._store.find_association(
            target_a.target_id, target_b.target_id
        )
        if dossier is not None:
            # Known association — confidence scales with prior correlation count
            score = min(1.0, 0.7 + 0.1 * dossier.correlation_count)
            return StrategyScore(
                strategy_name=self.name,
                score=score,
                detail=f"known dossier {dossier.uuid[:8]}, {dossier.correlation_count} prior correlations",
            )

        # Check if either signal is in any dossier (partial match)
        d_a = self._store.find_by_signal(target_a.target_id)
        d_b = self._store.find_by_signal(target_b.target_id)

        if d_a is not None and d_b is not None and d_a.uuid != d_b.uuid:
            # Both known but in different dossiers — weak negative signal
            return StrategyScore(
                strategy_name=self.name,
                score=0.0,
                detail="targets belong to different known dossiers",
            )

        return StrategyScore(
            strategy_name=self.name,
            score=0.0,
            detail="no prior association found",
        )
