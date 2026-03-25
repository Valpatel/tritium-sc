# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for individual correlation strategies."""

import time

import pytest

from tritium_lib.tracking.correlation_strategies import (
    CorrelationStrategy,
    DossierStrategy,
    SignalPatternStrategy,
    SpatialStrategy,
    StrategyScore,
    TemporalStrategy,
)
from tritium_lib.tracking.dossier import DossierStore
from src.engine.tactical.target_history import TargetHistory
from tritium_lib.tracking.target_tracker import TrackedTarget


def _make_target(
    tid: str = "t1",
    source: str = "ble",
    pos: tuple[float, float] = (0.0, 0.0),
    confidence: float = 0.5,
    last_seen: float | None = None,
) -> TrackedTarget:
    return TrackedTarget(
        target_id=tid,
        name=f"Target {tid}",
        alliance="unknown",
        asset_type="ble_device" if source == "ble" else "person",
        position=pos,
        last_seen=last_seen if last_seen is not None else time.monotonic(),
        source=source,
        position_source="trilateration" if source == "ble" else "yolo",
        position_confidence=confidence,
    )


class TestSpatialStrategy:
    """Tests for SpatialStrategy."""

    @pytest.mark.unit
    def test_abc_implemented(self):
        """SpatialStrategy is a valid CorrelationStrategy."""
        s = SpatialStrategy(radius=5.0)
        assert isinstance(s, CorrelationStrategy)
        assert s.name == "spatial"

    @pytest.mark.unit
    def test_overlapping_targets_score_1(self):
        """Targets at the same position score 1.0."""
        s = SpatialStrategy(radius=5.0)
        a = _make_target(tid="a", pos=(3.0, 3.0))
        b = _make_target(tid="b", pos=(3.0, 3.0))
        result = s.evaluate(a, b)
        assert result.score == 1.0

    @pytest.mark.unit
    def test_at_radius_boundary_scores_low(self):
        """Targets at exactly the radius score slightly above 0 (soft edge)."""
        s = SpatialStrategy(radius=5.0)
        a = _make_target(tid="a", pos=(0.0, 0.0))
        b = _make_target(tid="b", pos=(5.0, 0.0))
        result = s.evaluate(a, b)
        assert 0.0 < result.score < 0.15

    @pytest.mark.unit
    def test_beyond_radius_scores_zero(self):
        """Targets beyond radius score 0.0."""
        s = SpatialStrategy(radius=5.0)
        a = _make_target(tid="a", pos=(0.0, 0.0))
        b = _make_target(tid="b", pos=(10.0, 0.0))
        result = s.evaluate(a, b)
        assert result.score == 0.0

    @pytest.mark.unit
    def test_halfway_scores_above_half(self):
        """Targets at half radius score around 0.5 (slightly above due to soft edge)."""
        s = SpatialStrategy(radius=10.0)
        a = _make_target(tid="a", pos=(0.0, 0.0))
        b = _make_target(tid="b", pos=(5.0, 0.0))
        result = s.evaluate(a, b)
        assert 0.45 < result.score < 0.6

    @pytest.mark.unit
    def test_custom_radius(self):
        """Custom radius correctly changes behavior."""
        s = SpatialStrategy(radius=2.0)
        a = _make_target(tid="a", pos=(0.0, 0.0))
        b = _make_target(tid="b", pos=(3.0, 0.0))
        result = s.evaluate(a, b)
        assert result.score == 0.0

    @pytest.mark.unit
    def test_returns_strategy_score_type(self):
        """Evaluate returns a StrategyScore dataclass."""
        s = SpatialStrategy(radius=5.0)
        a = _make_target(tid="a")
        b = _make_target(tid="b")
        result = s.evaluate(a, b)
        assert isinstance(result, StrategyScore)
        assert result.strategy_name == "spatial"
        assert isinstance(result.detail, str)


class TestTemporalStrategy:
    """Tests for TemporalStrategy (co-movement detection)."""

    @pytest.mark.unit
    def test_insufficient_history_scores_zero(self):
        """With no position history, score is 0."""
        history = TargetHistory()
        s = TemporalStrategy(history=history)
        a = _make_target(tid="a")
        b = _make_target(tid="b")
        result = s.evaluate(a, b)
        assert result.score == 0.0
        assert "insufficient" in result.detail

    @pytest.mark.unit
    def test_co_moving_targets_score_high(self):
        """Targets moving in the same direction at same speed score high."""
        history = TargetHistory()
        now = time.monotonic()

        # Both targets move northeast at same speed
        for i in range(5):
            t = now + i * 1.0
            history.record("a", (float(i), float(i)), timestamp=t)
            history.record("b", (float(i) + 10, float(i) + 10), timestamp=t)

        s = TemporalStrategy(history=history)
        a = _make_target(tid="a", pos=(4.0, 4.0))
        b = _make_target(tid="b", pos=(14.0, 14.0))
        result = s.evaluate(a, b)
        assert result.score > 0.7

    @pytest.mark.unit
    def test_opposite_directions_score_low(self):
        """Targets moving in opposite directions score low."""
        history = TargetHistory()
        now = time.monotonic()

        for i in range(5):
            t = now + i * 1.0
            history.record("a", (float(i), 0.0), timestamp=t)
            history.record("b", (float(-i), 0.0), timestamp=t)

        s = TemporalStrategy(history=history)
        a = _make_target(tid="a", pos=(4.0, 0.0))
        b = _make_target(tid="b", pos=(-4.0, 0.0))
        result = s.evaluate(a, b)
        # 180deg heading diff -> heading_score=0, but same speed -> speed_score=1.0
        # Combined: 0.6*0 + 0.4*1.0 = 0.4 — lower than co-moving targets
        assert result.score <= 0.4

    @pytest.mark.unit
    def test_both_stationary_scores_zero(self):
        """Both stationary targets score 0 (not evidence of co-movement)."""
        history = TargetHistory()
        now = time.monotonic()

        for i in range(5):
            t = now + i * 1.0
            history.record("a", (5.0, 5.0), timestamp=t)
            history.record("b", (6.0, 6.0), timestamp=t)

        s = TemporalStrategy(history=history)
        a = _make_target(tid="a", pos=(5.0, 5.0))
        b = _make_target(tid="b", pos=(6.0, 6.0))
        result = s.evaluate(a, b)
        assert result.score == 0.0
        assert "stationary" in result.detail

    @pytest.mark.unit
    def test_different_speeds_penalized(self):
        """Targets at very different speeds get lower score."""
        history = TargetHistory()
        now = time.monotonic()

        for i in range(5):
            t = now + i * 1.0
            history.record("a", (float(i), 0.0), timestamp=t)
            history.record("b", (float(i) * 5, 0.0), timestamp=t)  # 5x faster

        s = TemporalStrategy(history=history, speed_ratio_max=3.0)
        a = _make_target(tid="a", pos=(4.0, 0.0))
        b = _make_target(tid="b", pos=(20.0, 0.0))
        result = s.evaluate(a, b)
        # Speed ratio is 5.0 > max 3.0, so speed_score = 0.0
        # Same heading -> heading_score=1.0, combined: 0.6*1.0 + 0.4*0.0 = 0.6
        assert result.score <= 0.6


class TestSignalPatternStrategy:
    """Tests for SignalPatternStrategy (appearance/disappearance timing)."""

    @pytest.mark.unit
    def test_same_source_scores_zero(self):
        """Same-source targets get 0 (signal pattern is meaningless)."""
        s = SignalPatternStrategy()
        a = _make_target(tid="a", source="ble")
        b = _make_target(tid="b", source="ble")
        result = s.evaluate(a, b)
        assert result.score == 0.0

    @pytest.mark.unit
    def test_simultaneous_appearance_high_score(self):
        """BLE + YOLO targets seen at the same time score high."""
        now = time.monotonic()
        s = SignalPatternStrategy(appearance_window=10.0)
        a = _make_target(tid="a", source="ble", last_seen=now)
        b = _make_target(tid="b", source="yolo", last_seen=now)
        result = s.evaluate(a, b)
        assert result.score > 0.9

    @pytest.mark.unit
    def test_appearance_within_window(self):
        """Targets seen within the window get a positive score."""
        now = time.monotonic()
        s = SignalPatternStrategy(appearance_window=10.0)
        a = _make_target(tid="a", source="ble", last_seen=now)
        b = _make_target(tid="b", source="yolo", last_seen=now - 5.0)
        result = s.evaluate(a, b)
        assert result.score == pytest.approx(0.5, abs=0.1)

    @pytest.mark.unit
    def test_appearance_beyond_window(self):
        """Targets seen beyond the window get 0."""
        now = time.monotonic()
        s = SignalPatternStrategy(appearance_window=10.0)
        a = _make_target(tid="a", source="ble", last_seen=now)
        b = _make_target(tid="b", source="yolo", last_seen=now - 15.0)
        result = s.evaluate(a, b)
        assert result.score == 0.0

    @pytest.mark.unit
    def test_ble_yolo_pair_bonus(self):
        """BLE + YOLO pair gets a bonus multiplier."""
        now = time.monotonic()
        s = SignalPatternStrategy(appearance_window=10.0)

        # BLE + YOLO
        a = _make_target(tid="a", source="ble", last_seen=now)
        b = _make_target(tid="b", source="yolo", last_seen=now - 1.0)
        result_ble_yolo = s.evaluate(a, b)

        # simulation + yolo (no bonus)
        c = _make_target(tid="c", source="simulation", last_seen=now)
        result_sim_yolo = s.evaluate(c, b)

        assert result_ble_yolo.score >= result_sim_yolo.score


class TestDossierStrategy:
    """Tests for DossierStrategy (known prior associations)."""

    @pytest.mark.unit
    def test_no_prior_association_scores_zero(self):
        """Unknown pair with no dossier history scores 0."""
        store = DossierStore()
        s = DossierStrategy(dossier_store=store)
        a = _make_target(tid="a")
        b = _make_target(tid="b")
        result = s.evaluate(a, b)
        assert result.score == 0.0

    @pytest.mark.unit
    def test_known_association_scores_high(self):
        """Targets previously correlated get a high score."""
        store = DossierStore()
        store.create_or_update("a", "ble", "b", "yolo", 0.8)

        s = DossierStrategy(dossier_store=store)
        a = _make_target(tid="a")
        b = _make_target(tid="b")
        result = s.evaluate(a, b)
        assert result.score >= 0.7

    @pytest.mark.unit
    def test_score_increases_with_correlation_count(self):
        """More prior correlations increase confidence."""
        store = DossierStore()
        store.create_or_update("a", "ble", "b", "yolo", 0.8)
        store.create_or_update("a", "ble", "b", "yolo", 0.9)
        store.create_or_update("a", "ble", "b", "yolo", 0.9)

        s = DossierStrategy(dossier_store=store)
        a = _make_target(tid="a")
        b = _make_target(tid="b")
        result = s.evaluate(a, b)
        # 0.7 + 0.1 * 3 = 1.0
        assert result.score >= 0.9

    @pytest.mark.unit
    def test_different_dossiers_scores_zero(self):
        """Targets in different dossiers score 0."""
        store = DossierStore()
        store.create_or_update("a", "ble", "x", "yolo", 0.8)
        store.create_or_update("b", "ble", "y", "yolo", 0.8)

        s = DossierStrategy(dossier_store=store)
        a = _make_target(tid="a")
        b = _make_target(tid="b")
        result = s.evaluate(a, b)
        assert result.score == 0.0
        assert "different known dossiers" in result.detail


class TestDossierStore:
    """Tests for the DossierStore itself."""

    @pytest.mark.unit
    def test_create_new_dossier(self):
        """Creating a new association creates a dossier."""
        store = DossierStore()
        dossier = store.create_or_update("mac_aa", "ble", "person_1", "yolo", 0.7)

        assert dossier.uuid
        assert dossier.has_signal("mac_aa")
        assert dossier.has_signal("person_1")
        assert "ble" in dossier.sources
        assert "yolo" in dossier.sources
        assert dossier.correlation_count == 1
        assert store.count == 1

    @pytest.mark.unit
    def test_find_by_signal(self):
        """Can find dossier by any of its signal IDs."""
        store = DossierStore()
        dossier = store.create_or_update("mac_aa", "ble", "person_1", "yolo", 0.7)

        found = store.find_by_signal("mac_aa")
        assert found is not None
        assert found.uuid == dossier.uuid

        found2 = store.find_by_signal("person_1")
        assert found2 is not None
        assert found2.uuid == dossier.uuid

    @pytest.mark.unit
    def test_find_unknown_signal(self):
        """Unknown signal returns None."""
        store = DossierStore()
        assert store.find_by_signal("nonexistent") is None

    @pytest.mark.unit
    def test_update_existing_dossier(self):
        """Re-correlating the same pair updates the dossier."""
        store = DossierStore()
        d1 = store.create_or_update("a", "ble", "b", "yolo", 0.5)
        d2 = store.create_or_update("a", "ble", "b", "yolo", 0.8)

        assert d1.uuid == d2.uuid
        assert store.count == 1
        assert d2.correlation_count == 2
        assert d2.confidence == 0.8  # max of 0.5 and 0.8

    @pytest.mark.unit
    def test_merge_dossiers(self):
        """Adding a signal that bridges two dossiers merges them."""
        store = DossierStore()
        store.create_or_update("a", "ble", "b", "yolo", 0.5)
        store.create_or_update("c", "ble", "d", "yolo", 0.6)
        assert store.count == 2

        # Now correlate "a" with "c" — should merge the two dossiers
        merged = store.create_or_update("a", "ble", "c", "ble", 0.9)
        assert store.count == 1
        assert merged.has_signal("a")
        assert merged.has_signal("b")
        assert merged.has_signal("c")
        assert merged.has_signal("d")

    @pytest.mark.unit
    def test_find_association(self):
        """find_association returns dossier when both signals are in the same one."""
        store = DossierStore()
        store.create_or_update("a", "ble", "b", "yolo", 0.7)

        assert store.find_association("a", "b") is not None
        assert store.find_association("a", "unknown") is None

    @pytest.mark.unit
    def test_get_all(self):
        """get_all returns all dossiers."""
        store = DossierStore()
        store.create_or_update("a", "ble", "b", "yolo", 0.5)
        store.create_or_update("c", "ble", "d", "yolo", 0.6)

        all_dossiers = store.get_all()
        assert len(all_dossiers) == 2

    @pytest.mark.unit
    def test_clear(self):
        """clear removes all dossiers."""
        store = DossierStore()
        store.create_or_update("a", "ble", "b", "yolo", 0.5)
        store.clear()
        assert store.count == 0
        assert store.find_by_signal("a") is None

    @pytest.mark.unit
    def test_to_dict(self):
        """TargetDossier serializes to dict."""
        store = DossierStore()
        dossier = store.create_or_update("a", "ble", "b", "yolo", 0.7)
        d = dossier.to_dict()
        assert d["uuid"] == dossier.uuid
        assert "a" in d["signal_ids"]
        assert "b" in d["signal_ids"]
        assert d["confidence"] == 0.7

    @pytest.mark.unit
    def test_add_signal_to_existing_dossier(self):
        """Adding one known + one new signal extends the dossier."""
        store = DossierStore()
        store.create_or_update("a", "ble", "b", "yolo", 0.5)

        d = store.create_or_update("a", "ble", "c", "simulation", 0.6)
        assert d.has_signal("a")
        assert d.has_signal("b")
        assert d.has_signal("c")
        assert store.count == 1
