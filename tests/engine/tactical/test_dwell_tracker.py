# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for DwellTracker — target loitering detection."""

import time
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest


@dataclass
class FakeTarget:
    target_id: str
    name: str = "Test"
    alliance: str = "unknown"
    asset_type: str = "phone"
    position: tuple = (0.0, 0.0)


class FakeEventBus:
    def __init__(self):
        self.events = []
    def publish(self, event_type, data):
        self.events.append((event_type, data))


class FakeTracker:
    def __init__(self):
        self._targets = []
    def get_all(self):
        return list(self._targets)
    def add(self, t):
        self._targets.append(t)


@pytest.fixture
def setup():
    eb = FakeEventBus()
    tt = FakeTracker()
    from tritium_lib.tracking.dwell_tracker import DwellTracker
    dt = DwellTracker(eb, tt, threshold_s=5.0, radius_m=10.0)
    return dt, eb, tt


def test_no_dwell_when_below_threshold(setup):
    """Targets below threshold should not generate dwell events."""
    dt, eb, tt = setup
    tt.add(FakeTarget("t1", position=(10.0, 20.0)))
    dt._check_all_targets()
    assert len(dt.active_dwells) == 0
    assert len([e for e in eb.events if e[0] == "dwell_start"]) == 0


def test_dwell_detected_after_threshold(setup):
    """Target staying put should trigger dwell after threshold."""
    dt, eb, tt = setup
    tt.add(FakeTarget("t1", position=(10.0, 20.0)))

    # First check — sets anchor
    dt._check_all_targets()
    assert len(dt.active_dwells) == 0

    # Simulate time passing by manipulating the anchor time
    import threading
    with dt._lock:
        dt._tracking["t1"]["anchor_time"] = time.time() - 10.0  # 10s ago

    # Second check — should detect dwell (threshold is 5s)
    dt._check_all_targets()
    assert len(dt.active_dwells) == 1
    assert dt.active_dwells[0].target_id == "t1"
    assert len([e for e in eb.events if e[0] == "dwell_start"]) == 1


def test_dwell_ends_on_movement(setup):
    """Moving target should end the dwell."""
    dt, eb, tt = setup
    t = FakeTarget("t1", position=(10.0, 20.0))
    tt.add(t)

    # Start dwell
    dt._check_all_targets()
    with dt._lock:
        dt._tracking["t1"]["anchor_time"] = time.time() - 10.0
    dt._check_all_targets()
    assert len(dt.active_dwells) == 1

    # Move the target far away
    t.position = (100.0, 200.0)
    dt._check_all_targets()
    assert len(dt.active_dwells) == 0
    assert len(dt.history) == 1
    assert len([e for e in eb.events if e[0] == "dwell_end"]) == 1


def test_dwell_updates_duration(setup):
    """Active dwell should get duration updates."""
    dt, eb, tt = setup
    tt.add(FakeTarget("t1", position=(10.0, 20.0)))

    dt._check_all_targets()
    with dt._lock:
        dt._tracking["t1"]["anchor_time"] = time.time() - 10.0
    dt._check_all_targets()

    # Check again — should update duration
    with dt._lock:
        dt._tracking["t1"]["anchor_time"] = time.time() - 20.0
    dt._check_all_targets()

    updates = [e for e in eb.events if e[0] == "dwell_update"]
    assert len(updates) >= 1


def test_dwell_for_target(setup):
    """get_dwell_for_target returns active dwell or None."""
    dt, eb, tt = setup
    tt.add(FakeTarget("t1", position=(10.0, 20.0)))

    assert dt.get_dwell_for_target("t1") is None

    dt._check_all_targets()
    with dt._lock:
        dt._tracking["t1"]["anchor_time"] = time.time() - 10.0
    dt._check_all_targets()

    dwell = dt.get_dwell_for_target("t1")
    assert dwell is not None
    assert dwell.target_id == "t1"


def test_small_movement_within_radius(setup):
    """Small movements within radius should not reset the anchor."""
    dt, eb, tt = setup
    t = FakeTarget("t1", position=(10.0, 20.0))
    tt.add(t)

    dt._check_all_targets()

    # Move slightly within radius (10m)
    t.position = (12.0, 22.0)  # ~2.83m
    with dt._lock:
        dt._tracking["t1"]["anchor_time"] = time.time() - 10.0
    dt._check_all_targets()

    # Should still detect dwell since movement was within radius
    assert len(dt.active_dwells) == 1


def test_cleanup_removed_targets(setup):
    """Targets that disappear should have their dwells ended."""
    dt, eb, tt = setup
    t = FakeTarget("t1", position=(10.0, 20.0))
    tt.add(t)

    dt._check_all_targets()
    with dt._lock:
        dt._tracking["t1"]["anchor_time"] = time.time() - 10.0
    dt._check_all_targets()
    assert len(dt.active_dwells) == 1

    # Remove target
    tt._targets.clear()
    dt._check_all_targets()
    assert len(dt.active_dwells) == 0
