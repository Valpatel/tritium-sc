# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for adaptive think interval calculation.

The adaptive interval logic maps urgency to think frequency.  This is a
pure function that lives in the plugin (no SDK dependency).

Urgency bands:
    > 0.8  -> 0.5s  (danger: react fast)
    > 0.5  -> 1.0s  (active: engaged)
    > 0.3  -> 3.0s  (normal: aware)
    <= 0.3 -> 10.0s (idle: conserve compute)
"""
from __future__ import annotations

import pytest


def calculate_adaptive_interval(urgency: float) -> float:
    """Map urgency to think interval (seconds).

    This is the reference implementation for the pure urgency-to-interval
    mapping.  The actual game may have a richer version with personality
    modifiers, but this tests the core contract.
    """
    if urgency > 0.8:
        return 0.5
    elif urgency > 0.5:
        return 1.0
    elif urgency > 0.3:
        return 3.0
    else:
        return 10.0


class TestAdaptiveInterval:
    """Test that urgency maps to correct intervals."""

    def test_high_urgency_returns_short_interval(self):
        assert calculate_adaptive_interval(0.9) == 0.5

    def test_active_urgency_returns_one_second(self):
        assert calculate_adaptive_interval(0.6) == 1.0

    def test_normal_urgency_returns_three_seconds(self):
        assert calculate_adaptive_interval(0.4) == 3.0

    def test_low_urgency_returns_ten_seconds(self):
        assert calculate_adaptive_interval(0.2) == 10.0

    def test_zero_urgency_returns_ten_seconds(self):
        assert calculate_adaptive_interval(0.0) == 10.0

    def test_boundary_0_8_returns_active(self):
        """urgency = 0.8 is NOT > 0.8, so active band."""
        assert calculate_adaptive_interval(0.8) == 1.0

    def test_boundary_0_5_returns_normal(self):
        """urgency = 0.5 is NOT > 0.5, so normal band."""
        assert calculate_adaptive_interval(0.5) == 3.0

    def test_boundary_0_3_returns_idle(self):
        """urgency = 0.3 is NOT > 0.3, so idle band."""
        assert calculate_adaptive_interval(0.3) == 10.0

    def test_max_urgency_returns_short(self):
        assert calculate_adaptive_interval(1.0) == 0.5
