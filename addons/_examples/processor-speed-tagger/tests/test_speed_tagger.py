# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the speed tagger processor addon."""

import asyncio
from pathlib import Path

import pytest

from tritium_lib.sdk import ProcessorAddon
from tritium_lib.sdk.manifest import load_manifest, validate_manifest


MANIFEST_PATH = Path(__file__).parent.parent / "tritium_addon.toml"


# ---------------------------------------------------------------------------
# Manifest tests
# ---------------------------------------------------------------------------

class TestManifest:
    def test_manifest_loads(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.id == "processor-speed-tagger"
        assert m.name == "Speed Tagger"

    def test_manifest_valid(self):
        m = load_manifest(MANIFEST_PATH)
        errors = validate_manifest(m)
        assert errors == [], f"Manifest errors: {errors}"

    def test_manifest_category(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.category_window == "intelligence"

    def test_manifest_no_panels(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.panels == []

    def test_manifest_no_hardware(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.hardware_devices == []
        assert m.auto_detect is False


# ---------------------------------------------------------------------------
# classify_speed tests
# ---------------------------------------------------------------------------

class TestClassifySpeed:
    def test_stationary(self):
        from speed_tagger_addon import classify_speed
        assert classify_speed(0.0) == "stationary"
        assert classify_speed(0.1) == "stationary"
        assert classify_speed(0.49) == "stationary"

    def test_walking(self):
        from speed_tagger_addon import classify_speed
        assert classify_speed(0.5) == "walking"
        assert classify_speed(1.0) == "walking"
        assert classify_speed(1.99) == "walking"

    def test_vehicle(self):
        from speed_tagger_addon import classify_speed
        assert classify_speed(2.0) == "vehicle"
        assert classify_speed(10.0) == "vehicle"
        assert classify_speed(14.99) == "vehicle"

    def test_fast(self):
        from speed_tagger_addon import classify_speed
        assert classify_speed(15.0) == "fast"
        assert classify_speed(100.0) == "fast"
        assert classify_speed(999.0) == "fast"

    def test_negative_treated_as_stationary(self):
        from speed_tagger_addon import classify_speed
        assert classify_speed(-5.0) == "stationary"


# ---------------------------------------------------------------------------
# compute_speed tests
# ---------------------------------------------------------------------------

class TestComputeSpeed:
    def test_explicit_speed_mps(self):
        from speed_tagger_addon import compute_speed
        assert compute_speed({"speed_mps": 3.5}) == 3.5

    def test_explicit_speed(self):
        from speed_tagger_addon import compute_speed
        assert compute_speed({"speed": 7.2}) == 7.2

    def test_velocity_components(self):
        from speed_tagger_addon import compute_speed
        speed = compute_speed({"vx": 3.0, "vy": 4.0})
        assert abs(speed - 5.0) < 0.001

    def test_velocity_dict(self):
        from speed_tagger_addon import compute_speed
        speed = compute_speed({"velocity": {"x": 3.0, "y": 4.0, "z": 0.0}})
        assert abs(speed - 5.0) < 0.001

    def test_no_speed_info(self):
        from speed_tagger_addon import compute_speed
        assert compute_speed({"target_id": "test"}) is None


# ---------------------------------------------------------------------------
# Addon class tests
# ---------------------------------------------------------------------------

class TestAddonClass:
    def test_import(self):
        from speed_tagger_addon import SpeedTaggerAddon
        addon = SpeedTaggerAddon()
        assert addon.info.id == "processor-speed-tagger"

    def test_is_processor(self):
        from speed_tagger_addon import SpeedTaggerAddon
        assert issubclass(SpeedTaggerAddon, ProcessorAddon)

    def test_process_with_speed(self):
        from speed_tagger_addon import SpeedTaggerAddon
        addon = SpeedTaggerAddon()
        target = {"target_id": "ble_abc", "speed_mps": 1.2}
        result = asyncio.run(addon.process(target))
        assert result["speed_class"] == "walking"
        assert result["speed_mps"] == 1.2

    def test_process_with_velocity(self):
        from speed_tagger_addon import SpeedTaggerAddon
        addon = SpeedTaggerAddon()
        target = {"target_id": "det_car_1", "vx": 10.0, "vy": 0.0}
        result = asyncio.run(addon.process(target))
        assert result["speed_class"] == "vehicle"
        assert abs(result["speed_mps"] - 10.0) < 0.001

    def test_process_without_speed(self):
        from speed_tagger_addon import SpeedTaggerAddon
        addon = SpeedTaggerAddon()
        target = {"target_id": "ble_xyz"}
        result = asyncio.run(addon.process(target))
        assert result["speed_class"] == "unknown"

    def test_process_increments_count(self):
        from speed_tagger_addon import SpeedTaggerAddon
        addon = SpeedTaggerAddon()
        assert addon._tagged_count == 0
        asyncio.run(addon.process({"target_id": "t1", "speed": 0}))
        asyncio.run(addon.process({"target_id": "t2", "speed": 5}))
        assert addon._tagged_count == 2

    def test_health_check(self):
        from speed_tagger_addon import SpeedTaggerAddon
        addon = SpeedTaggerAddon()
        addon._registered = True
        asyncio.run(addon.process({"speed": 0}))
        h = addon.health_check()
        assert h["status"] == "ok"
        assert h["tagged_count"] == 1
