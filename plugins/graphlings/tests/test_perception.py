# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for PerceptionEngine — translates TRITIUM-SC state to graphling perception.

TDD: Written before implementation.
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest


def _make_tracker_with_targets(targets: list[dict]) -> MagicMock:
    """Create a mock TargetTracker that returns TrackedTarget-like objects."""
    tracker = MagicMock()
    tracked = []
    for t in targets:
        obj = MagicMock()
        obj.target_id = t.get("target_id", "t_001")
        obj.name = t.get("name", "Unknown")
        obj.alliance = t.get("alliance", "neutral")
        obj.asset_type = t.get("asset_type", "rover")
        obj.position = t.get("position", (0.0, 0.0))
        obj.heading = t.get("heading", 0.0)
        obj.speed = t.get("speed", 0.0)
        obj.status = t.get("status", "active")
        tracked.append(obj)
    tracker.get_all.return_value = tracked
    tracker.get_target.return_value = None
    return tracker


def _make_event_bus_with_events(events: list[dict] | None = None) -> MagicMock:
    """Create a mock EventBus."""
    bus = MagicMock()
    return bus


# ── Build perception with no nearby entities ─────────────────────


class TestPerceptionNoEntities:
    """PerceptionEngine with an empty world."""

    def test_empty_world_returns_valid_packet(self):
        from graphlings.perception import PerceptionEngine

        tracker = _make_tracker_with_targets([])
        engine = PerceptionEngine(tracker, perception_radius=50.0)

        packet = engine.build_perception("graphling_001", (100.0, 200.0), 90.0)

        assert packet is not None
        assert len(packet["nearby_entities"]) == 0
        assert packet["danger_level"] == 0.0
        assert packet["nearby_friendlies"] == 0
        assert packet["nearby_hostiles"] == 0


# ── Build perception with friendlies and hostiles ────────────────


class TestPerceptionWithEntities:
    """PerceptionEngine with mixed entity types."""

    def test_friendlies_and_hostiles_classified(self):
        from graphlings.perception import PerceptionEngine

        targets = [
            {"target_id": "f_001", "name": "Scout", "alliance": "friendly",
             "asset_type": "rover", "position": (110.0, 200.0)},
            {"target_id": "h_001", "name": "Enemy Drone", "alliance": "hostile",
             "asset_type": "drone", "position": (120.0, 200.0)},
            {"target_id": "n_001", "name": "Civilian", "alliance": "neutral",
             "asset_type": "person", "position": (105.0, 205.0)},
        ]
        tracker = _make_tracker_with_targets(targets)
        engine = PerceptionEngine(tracker, perception_radius=50.0)

        packet = engine.build_perception("graphling_001", (100.0, 200.0), 90.0)

        assert len(packet["nearby_entities"]) == 3
        assert packet["nearby_friendlies"] == 1
        assert packet["nearby_hostiles"] == 1

    def test_hostile_is_marked_as_threat(self):
        from graphlings.perception import PerceptionEngine

        targets = [
            {"target_id": "h_001", "name": "Enemy", "alliance": "hostile",
             "asset_type": "drone", "position": (110.0, 200.0)},
        ]
        tracker = _make_tracker_with_targets(targets)
        engine = PerceptionEngine(tracker, perception_radius=50.0)

        packet = engine.build_perception("graphling_001", (100.0, 200.0), 90.0)

        assert len(packet["nearby_entities"]) == 1
        assert packet["nearby_entities"][0]["is_threat"] is True


# ── Danger level increases with nearby hostiles ──────────────────


class TestDangerLevel:
    """Danger level scales with hostile proximity."""

    def test_no_hostiles_zero_danger(self):
        from graphlings.perception import PerceptionEngine

        tracker = _make_tracker_with_targets([])
        engine = PerceptionEngine(tracker, perception_radius=50.0)
        packet = engine.build_perception("g_001", (0.0, 0.0), 0.0)
        assert packet["danger_level"] == 0.0

    def test_close_hostile_high_danger(self):
        from graphlings.perception import PerceptionEngine

        targets = [
            {"target_id": "h_001", "name": "Enemy", "alliance": "hostile",
             "asset_type": "drone", "position": (5.0, 0.0)},
        ]
        tracker = _make_tracker_with_targets(targets)
        engine = PerceptionEngine(tracker, perception_radius=50.0)
        packet = engine.build_perception("g_001", (0.0, 0.0), 0.0)
        assert packet["danger_level"] > 0.5

    def test_far_hostile_low_danger(self):
        from graphlings.perception import PerceptionEngine

        targets = [
            {"target_id": "h_001", "name": "Enemy", "alliance": "hostile",
             "asset_type": "drone", "position": (45.0, 0.0)},
        ]
        tracker = _make_tracker_with_targets(targets)
        engine = PerceptionEngine(tracker, perception_radius=50.0)
        packet = engine.build_perception("g_001", (0.0, 0.0), 0.0)
        assert packet["danger_level"] < 0.5


# ── Perception respects radius ───────────────────────────────────


class TestPerceptionRadius:
    """Entities outside radius are excluded."""

    def test_outside_radius_excluded(self):
        from graphlings.perception import PerceptionEngine

        targets = [
            {"target_id": "far_001", "name": "Far Away", "alliance": "neutral",
             "asset_type": "rover", "position": (200.0, 200.0)},
        ]
        tracker = _make_tracker_with_targets(targets)
        engine = PerceptionEngine(tracker, perception_radius=50.0)
        packet = engine.build_perception("g_001", (0.0, 0.0), 0.0)
        assert len(packet["nearby_entities"]) == 0

    def test_inside_radius_included(self):
        from graphlings.perception import PerceptionEngine

        targets = [
            {"target_id": "near_001", "name": "Nearby", "alliance": "neutral",
             "asset_type": "rover", "position": (10.0, 10.0)},
        ]
        tracker = _make_tracker_with_targets(targets)
        engine = PerceptionEngine(tracker, perception_radius=50.0)
        packet = engine.build_perception("g_001", (0.0, 0.0), 0.0)
        assert len(packet["nearby_entities"]) == 1


# ── Entity perception calculates distance correctly ──────────────


class TestDistanceCalculation:
    """Distance between graphling and entities is correct."""

    def test_distance_calculated(self):
        from graphlings.perception import PerceptionEngine

        targets = [
            {"target_id": "t_001", "name": "Test", "alliance": "neutral",
             "asset_type": "rover", "position": (3.0, 4.0)},
        ]
        tracker = _make_tracker_with_targets(targets)
        engine = PerceptionEngine(tracker, perception_radius=50.0)
        packet = engine.build_perception("g_001", (0.0, 0.0), 0.0)

        assert len(packet["nearby_entities"]) == 1
        dist = packet["nearby_entities"][0]["distance"]
        assert abs(dist - 5.0) < 0.01  # 3-4-5 triangle


# ── Recent events are included ───────────────────────────────────


class TestRecentEvents:
    """Recent events from event bus are included."""

    def test_events_included_in_packet(self):
        from graphlings.perception import PerceptionEngine

        tracker = _make_tracker_with_targets([])
        engine = PerceptionEngine(tracker, perception_radius=50.0)

        # Record some events
        engine.record_event("explosion_nearby")
        engine.record_event("weather_changed")

        packet = engine.build_perception("g_001", (0.0, 0.0), 0.0)

        assert "explosion_nearby" in packet["recent_events"]
        assert "weather_changed" in packet["recent_events"]


# ── Own position and heading correct ─────────────────────────────


class TestOwnState:
    """Own position and heading are passed through correctly."""

    def test_own_position_in_packet(self):
        from graphlings.perception import PerceptionEngine

        tracker = _make_tracker_with_targets([])
        engine = PerceptionEngine(tracker, perception_radius=50.0)
        packet = engine.build_perception("g_001", (42.0, 99.0), 180.0)

        assert packet["own_position"] == [42.0, 99.0]
        assert packet["own_heading"] == 180.0


# ── Multiple graphlings get independent perceptions ──────────────


class TestIndependentPerceptions:
    """Different graphlings at different positions get different perceptions."""

    def test_independent_perceptions(self):
        from graphlings.perception import PerceptionEngine

        targets = [
            {"target_id": "t_001", "name": "NearA", "alliance": "neutral",
             "asset_type": "rover", "position": (5.0, 0.0)},
        ]
        tracker = _make_tracker_with_targets(targets)
        engine = PerceptionEngine(tracker, perception_radius=10.0)

        # Graphling A is close to the target
        packet_a = engine.build_perception("g_a", (0.0, 0.0), 0.0)
        # Graphling B is far from the target
        packet_b = engine.build_perception("g_b", (100.0, 100.0), 0.0)

        assert len(packet_a["nearby_entities"]) == 1
        assert len(packet_b["nearby_entities"]) == 0
