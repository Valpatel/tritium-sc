# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for scenarios router Pydantic models and pure logic.

Tests RunRequest, RateRequest validation. No server or runner needed.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.routers.scenarios import RunRequest, RateRequest


# ===========================================================================
# RunRequest
# ===========================================================================

@pytest.mark.unit
class TestRunRequest:
    """RunRequest — scenario run configuration."""

    def test_minimal(self):
        r = RunRequest(name="basic_greeting")
        assert r.name == "basic_greeting"

    def test_defaults(self):
        r = RunRequest(name="test")
        assert r.chat_model is None
        assert r.deep_model is None
        assert r.system_prompt_override is None
        assert r.use_listener is False

    def test_full(self):
        r = RunRequest(
            name="deep_conversation",
            chat_model="qwen2.5:7b",
            deep_model="llava:34b",
            system_prompt_override="Be extra creative.",
            use_listener=True,
        )
        assert r.chat_model == "qwen2.5:7b"
        assert r.deep_model == "llava:34b"
        assert r.system_prompt_override == "Be extra creative."
        assert r.use_listener is True

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            RunRequest()


# ===========================================================================
# RateRequest
# ===========================================================================

@pytest.mark.unit
class TestRateRequest:
    """RateRequest — human rating submission."""

    def test_valid_rating(self):
        r = RateRequest(rating=3)
        assert r.rating == 3

    def test_min_rating(self):
        r = RateRequest(rating=1)
        assert r.rating == 1

    def test_max_rating(self):
        r = RateRequest(rating=5)
        assert r.rating == 5

    def test_below_min_raises(self):
        with pytest.raises(ValidationError):
            RateRequest(rating=0)

    def test_above_max_raises(self):
        with pytest.raises(ValidationError):
            RateRequest(rating=6)

    def test_missing_rating_raises(self):
        with pytest.raises(ValidationError):
            RateRequest()
