# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the weather API router."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from app.routers.weather import WMO_CODES, WMO_ICONS, _cache_key


class TestWMOCodes:
    """Test WMO weather code mappings."""

    def test_clear_sky(self):
        assert WMO_CODES[0] == "Clear sky"

    def test_thunderstorm(self):
        assert WMO_CODES[95] == "Thunderstorm"

    def test_all_codes_have_icons(self):
        for code in WMO_CODES:
            assert code in WMO_ICONS, f"WMO code {code} missing icon mapping"

    def test_icon_values(self):
        assert WMO_ICONS[0] == "sun"
        assert WMO_ICONS[63] == "rain"
        assert WMO_ICONS[95] == "thunder"
        assert WMO_ICONS[75] == "snow_heavy"


class TestCacheKey:
    """Test cache key generation."""

    def test_rounds_to_2_decimals(self):
        key = _cache_key(40.7128, -74.0060)
        assert key == "40.71,-74.01"

    def test_nearby_coords_same_key(self):
        k1 = _cache_key(40.7128, -74.0060)
        k2 = _cache_key(40.7131, -74.0062)
        assert k1 == k2

    def test_different_cities_different_key(self):
        k1 = _cache_key(40.7128, -74.0060)  # NYC
        k2 = _cache_key(34.0522, -118.2437)  # LA
        assert k1 != k2
