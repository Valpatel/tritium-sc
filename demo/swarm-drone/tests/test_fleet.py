# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for fleet.py -- fleet launcher that spawns N drone subprocesses."""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fleet import build_drone_args, generate_start_positions, validate_fleet_args


# ---------------------------------------------------------------------------
# Argument building
# ---------------------------------------------------------------------------
class TestBuildDroneArgs:
    """build_drone_args() creates CLI args for a single drone subprocess."""

    def test_returns_list(self):
        args = build_drone_args(
            drone_id="swarm-01",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
            start_x=10.0,
            start_y=20.0,
        )
        assert isinstance(args, list)

    def test_contains_drone_id(self):
        args = build_drone_args(
            drone_id="swarm-01",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
            start_x=0.0,
            start_y=0.0,
        )
        assert "--drone-id" in args
        idx = args.index("--drone-id")
        assert args[idx + 1] == "swarm-01"

    def test_contains_mqtt_host(self):
        args = build_drone_args(
            drone_id="swarm-01",
            mqtt_host="192.168.1.100",
            mqtt_port=1883,
            site="home",
            start_x=0.0,
            start_y=0.0,
        )
        assert "--mqtt-host" in args
        idx = args.index("--mqtt-host")
        assert args[idx + 1] == "192.168.1.100"

    def test_contains_start_position(self):
        args = build_drone_args(
            drone_id="swarm-01",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
            start_x=15.5,
            start_y=-3.2,
        )
        assert "--start-x" in args
        assert "--start-y" in args

    def test_main_py_in_args(self):
        args = build_drone_args(
            drone_id="swarm-01",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
            start_x=0.0,
            start_y=0.0,
        )
        assert any("main.py" in a for a in args)


# ---------------------------------------------------------------------------
# Start position generation
# ---------------------------------------------------------------------------
class TestGenerateStartPositions:
    """generate_start_positions() creates spread-out positions for N drones."""

    def test_correct_count(self):
        positions = generate_start_positions(count=4, center_x=0.0, center_y=0.0, radius=10.0)
        assert len(positions) == 4

    def test_positions_are_tuples(self):
        positions = generate_start_positions(count=3, center_x=0.0, center_y=0.0, radius=5.0)
        for pos in positions:
            assert len(pos) == 2

    def test_positions_within_radius(self):
        import math
        positions = generate_start_positions(count=8, center_x=5.0, center_y=5.0, radius=10.0)
        for x, y in positions:
            dist = math.sqrt((x - 5.0) ** 2 + (y - 5.0) ** 2)
            assert dist <= 10.0 + 0.01

    def test_single_drone_at_center(self):
        positions = generate_start_positions(count=1, center_x=5.0, center_y=5.0, radius=10.0)
        assert len(positions) == 1
        assert positions[0][0] == pytest.approx(5.0, abs=0.1)
        assert positions[0][1] == pytest.approx(5.0, abs=0.1)

    def test_zero_drones(self):
        positions = generate_start_positions(count=0, center_x=0.0, center_y=0.0, radius=10.0)
        assert len(positions) == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class TestValidateFleetArgs:
    """validate_fleet_args() checks fleet parameters."""

    def test_valid_args(self):
        errors = validate_fleet_args(count=4, prefix="swarm", mqtt_host="localhost")
        assert errors == []

    def test_zero_count(self):
        errors = validate_fleet_args(count=0, prefix="swarm", mqtt_host="localhost")
        assert len(errors) > 0

    def test_negative_count(self):
        errors = validate_fleet_args(count=-1, prefix="swarm", mqtt_host="localhost")
        assert len(errors) > 0

    def test_empty_prefix(self):
        errors = validate_fleet_args(count=4, prefix="", mqtt_host="localhost")
        assert len(errors) > 0

    def test_empty_mqtt_host(self):
        errors = validate_fleet_args(count=4, prefix="swarm", mqtt_host="")
        assert len(errors) > 0
