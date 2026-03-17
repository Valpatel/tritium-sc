# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the RadioLock mutual exclusion system."""

import time
import pytest
from hackrf_addon.radio_lock import RadioLock


class TestRadioLockBasic:
    """Basic acquire/release behavior."""

    def test_initial_state_unlocked(self):
        lock = RadioLock()
        assert lock.is_locked is False
        assert lock.current_owner is None

    def test_acquire_succeeds_when_free(self):
        lock = RadioLock()
        assert lock.acquire("sweep", "FM 88-108") is True
        assert lock.is_locked is True
        assert lock.current_owner == "sweep"
        assert lock.current_description == "FM 88-108"

    def test_acquire_fails_when_busy(self):
        lock = RadioLock()
        lock.acquire("sweep", "FM scan")
        result = lock.acquire("rtl_433", "315 MHz TPMS")
        assert result is False
        assert lock.current_owner == "sweep"  # Original owner retained

    def test_release_frees_lock(self):
        lock = RadioLock()
        lock.acquire("sweep")
        lock.release("sweep")
        assert lock.is_locked is False
        assert lock.current_owner is None

    def test_double_release_safe(self):
        """Releasing when not locked should not crash."""
        lock = RadioLock()
        lock.release("sweep")  # Not locked — should be safe
        assert lock.is_locked is False


class TestRadioLockConflicts:
    """Mode conflict resolution."""

    def test_sweep_blocks_rtl433(self):
        lock = RadioLock()
        lock.acquire("sweep", "FM 88-108 MHz")
        result = lock.acquire("rtl_433", "315 MHz TPMS")
        assert result is False

    def test_rtl433_blocks_sweep(self):
        lock = RadioLock()
        lock.acquire("rtl_433", "433 MHz ISM")
        result = lock.acquire("sweep", "Full spectrum")
        assert result is False

    def test_scanner_blocks_manual_sweep(self):
        lock = RadioLock()
        lock.acquire("scanner", "Continuous 24/7")
        result = lock.acquire("sweep", "FM Radio")
        assert result is False

    def test_receiver_blocks_sweep(self):
        lock = RadioLock()
        lock.acquire("receiver", "FM 92.5 MHz")
        result = lock.acquire("sweep", "FM scan")
        assert result is False

    def test_same_owner_can_reacquire(self):
        """Same operation re-acquiring should succeed (update description)."""
        lock = RadioLock()
        lock.acquire("sweep", "FM 88-108")
        result = lock.acquire("sweep", "ISM 430-440")
        assert result is True
        assert lock.current_description == "ISM 430-440"

    def test_release_then_new_owner(self):
        lock = RadioLock()
        lock.acquire("sweep", "FM")
        lock.release("sweep")
        result = lock.acquire("rtl_433", "315 MHz")
        assert result is True
        assert lock.current_owner == "rtl_433"


class TestRadioLockStatus:
    """Status reporting for UI."""

    def test_status_when_unlocked(self):
        lock = RadioLock()
        s = lock.get_status()
        assert s["locked"] is False
        assert s["owner"] is None
        assert s["duration_s"] == 0

    def test_status_when_locked(self):
        lock = RadioLock()
        lock.acquire("sweep", "FM 88-108 MHz")
        s = lock.get_status()
        assert s["locked"] is True
        assert s["owner"] == "sweep"
        assert s["description"] == "FM 88-108 MHz"
        assert s["duration_s"] >= 0

    def test_duration_increases(self):
        lock = RadioLock()
        lock.acquire("sweep")
        time.sleep(0.1)
        assert lock.lock_duration_s >= 0.05


class TestRadioLockRecovery:
    """Error recovery scenarios."""

    def test_force_release(self):
        lock = RadioLock()
        lock.acquire("sweep", "stuck operation")
        lock.force_release()
        assert lock.is_locked is False

    def test_wrong_owner_release_ignored(self):
        """Releasing with wrong owner name should not release the lock."""
        lock = RadioLock()
        lock.acquire("sweep", "FM")
        lock.release("rtl_433")  # Wrong owner
        assert lock.is_locked is True  # Still locked by sweep
        assert lock.current_owner == "sweep"
