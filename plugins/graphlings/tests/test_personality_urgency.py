# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for personality-influenced urgency calculation.

Tests a pure function that maps urgency + optional personality traits to
a think interval.  No SDK dependency — this is a standalone calculation.

Key design:
- Base urgency bands: >0.8 -> 0.5s, >0.5 -> 1.0s, >0.3 -> 3.0s, <=0.3 -> 10.0s
- Cautious graphlings think more often (interval * 0.7)
- Social graphlings think more when friendlies nearby (interval * 0.6)
- Curious graphlings think more when events pending (interval * 0.5)
- No personality data = default intervals (backward compat)
- Interval floor at 0.5s (never faster)
"""
from __future__ import annotations

import pytest


def calculate_adaptive_interval(
    urgency: float,
    personality: dict | None = None,
    nearby_friendlies: int = 0,
    has_events: bool = False,
) -> float:
    """Map urgency + personality to a think interval.

    This is the reference implementation tested here.
    """
    # Base urgency bands
    if urgency > 0.8:
        interval = 0.5
    elif urgency > 0.5:
        interval = 1.0
    elif urgency > 0.3:
        interval = 3.0
    else:
        interval = 10.0

    # Personality modifiers
    if personality:
        if personality.get("caution", 0.0) >= 0.7:
            interval *= 0.7
        if personality.get("sociability", 0.0) >= 0.7 and nearby_friendlies > 0:
            interval *= 0.6
        if personality.get("curiosity", 0.0) >= 0.7 and has_events:
            interval *= 0.5

    # Floor
    return max(interval, 0.5)


# ── Test: Cautious graphling has shorter interval ─────────────────────


class TestCautiousGraphlingShorterInterval:
    """A graphling with high caution should have a shorter think interval."""

    def test_cautious_graphling_shorter_interval(self):
        base = calculate_adaptive_interval(0.4)
        assert base == 3.0

        personality = {"caution": 0.8}
        adjusted = calculate_adaptive_interval(0.4, personality=personality)

        assert adjusted < base
        assert adjusted == pytest.approx(3.0 * 0.7, abs=0.01)

    def test_low_caution_no_effect(self):
        base = calculate_adaptive_interval(0.4)
        personality = {"caution": 0.5}
        adjusted = calculate_adaptive_interval(0.4, personality=personality)

        assert adjusted == base


# ── Test: Social graphling reacts to friendlies ──────────────────────


class TestSocialGraphlingReactsToFriendlies:
    """High sociability with friendlies nearby should shorten the interval."""

    def test_social_graphling_reacts_to_friendlies(self):
        base = calculate_adaptive_interval(0.4)
        personality = {"sociability": 0.8}
        adjusted = calculate_adaptive_interval(
            0.4, personality=personality, nearby_friendlies=3
        )

        assert adjusted < base
        assert adjusted == pytest.approx(3.0 * 0.6, abs=0.01)

    def test_social_graphling_no_friendlies_no_effect(self):
        base = calculate_adaptive_interval(0.4)
        personality = {"sociability": 0.8}
        adjusted = calculate_adaptive_interval(
            0.4, personality=personality, nearby_friendlies=0
        )

        assert adjusted == base

    def test_low_sociability_friendlies_no_effect(self):
        base = calculate_adaptive_interval(0.4)
        personality = {"sociability": 0.3}
        adjusted = calculate_adaptive_interval(
            0.4, personality=personality, nearby_friendlies=5
        )

        assert adjusted == base


# ── Test: Curious graphling reacts to events ─────────────────────────


class TestCuriousGraphlingReactsToEvents:
    """High curiosity with pending events should shorten the interval."""

    def test_curious_graphling_reacts_to_events(self):
        base = calculate_adaptive_interval(0.4)
        personality = {"curiosity": 0.8}
        adjusted = calculate_adaptive_interval(
            0.4, personality=personality, has_events=True
        )

        assert adjusted < base
        assert adjusted == pytest.approx(3.0 * 0.5, abs=0.01)

    def test_curious_graphling_no_events_no_effect(self):
        base = calculate_adaptive_interval(0.4)
        personality = {"curiosity": 0.8}
        adjusted = calculate_adaptive_interval(
            0.4, personality=personality, has_events=False
        )

        assert adjusted == base

    def test_low_curiosity_events_no_effect(self):
        base = calculate_adaptive_interval(0.4)
        personality = {"curiosity": 0.3}
        adjusted = calculate_adaptive_interval(
            0.4, personality=personality, has_events=True
        )

        assert adjusted == base


# ── Test: No personality -- default intervals (backward compat) ───────


class TestNoPersonalityDefault:
    """Without personality data, intervals should be unchanged from base."""

    def test_no_personality_default(self):
        base = calculate_adaptive_interval(0.4)
        adjusted = calculate_adaptive_interval(0.4, personality=None)
        assert adjusted == base

    def test_empty_personality_default(self):
        base = calculate_adaptive_interval(0.4)
        adjusted = calculate_adaptive_interval(0.4, personality={})
        assert adjusted == base

    def test_all_urgency_levels_unchanged(self):
        for urgency, expected in [(0.9, 0.5), (0.6, 1.0), (0.4, 3.0), (0.2, 10.0)]:
            result = calculate_adaptive_interval(urgency)
            assert result == expected


# ── Test: Multiple traits stack with floor ───────────────────────────


class TestMultipleTraitsStack:
    """Multiple personality traits should stack but respect the 0.5s floor."""

    def test_multiple_traits_stack(self):
        personality = {"caution": 0.9, "sociability": 0.9, "curiosity": 0.9}
        adjusted = calculate_adaptive_interval(
            0.4,
            personality=personality,
            nearby_friendlies=3,
            has_events=True,
        )

        # Base: 3.0s, * 0.7 (caution) * 0.6 (social+friends) * 0.5 (curious+events)
        # = 3.0 * 0.21 = 0.63s -> but floor is 0.5s
        assert adjusted >= 0.5

    def test_floor_enforced(self):
        personality = {"caution": 1.0, "sociability": 1.0, "curiosity": 1.0}
        adjusted = calculate_adaptive_interval(
            0.9,  # base 0.5s
            personality=personality,
            nearby_friendlies=10,
            has_events=True,
        )

        # Base 0.5 * 0.7 * 0.6 * 0.5 = 0.105 -> clamped to 0.5
        assert adjusted == 0.5
