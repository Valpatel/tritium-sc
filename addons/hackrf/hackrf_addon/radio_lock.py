# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Radio lock — ensures only one operation uses the HackRF at a time.

The HackRF One is a single-radio device that can only do one thing at
a time: sweep, receive, transmit, or be used by rtl_433. This lock
ensures mutual exclusion and provides clear error messages when the
radio is busy.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger("hackrf.radio_lock")


class RadioLock:
    """Mutual exclusion for HackRF radio operations.

    Usage:
        lock = RadioLock()
        if lock.acquire("sweep", "FM 88-108 MHz"):
            try:
                # ... do sweep ...
            finally:
                lock.release("sweep")
        else:
            print(f"Radio busy: {lock.current_owner} - {lock.current_description}")
    """

    def __init__(self):
        self._owner: str | None = None
        self._description: str = ""
        self._acquired_at: float = 0.0

    @property
    def is_locked(self) -> bool:
        return self._owner is not None

    @property
    def current_owner(self) -> str | None:
        return self._owner

    @property
    def current_description(self) -> str:
        return self._description

    @property
    def lock_duration_s(self) -> float:
        if self._acquired_at > 0:
            return time.time() - self._acquired_at
        return 0.0

    def acquire(self, owner: str, description: str = "") -> bool:
        """Try to acquire the radio lock.

        Args:
            owner: Name of the operation (e.g., "sweep", "rtl_433", "receiver", "scanner")
            description: Human-readable description (e.g., "FM 88-108 MHz")

        Returns:
            True if lock acquired, False if radio is busy.
        """
        if self._owner is not None:
            if self._owner == owner:
                # Same owner re-acquiring — update description
                self._description = description
                return True
            log.warning(f"Radio busy: {self._owner} ({self._description}) — rejected {owner}")
            return False

        self._owner = owner
        self._description = description
        self._acquired_at = time.time()
        log.info(f"Radio lock acquired by {owner}: {description}")
        return True

    def release(self, owner: str = ""):
        """Release the radio lock.

        Args:
            owner: Name of the releasing operation. If provided, must match current owner.
        """
        if owner and self._owner and self._owner != owner:
            log.warning(f"Lock release mismatch: {owner} tried to release lock held by {self._owner}")
            return

        if self._owner:
            log.info(f"Radio lock released by {self._owner} after {self.lock_duration_s:.1f}s")
        self._owner = None
        self._description = ""
        self._acquired_at = 0.0

    def force_release(self):
        """Force-release the lock regardless of owner. Use for error recovery."""
        if self._owner:
            log.warning(f"Force-releasing radio lock from {self._owner}")
        self._owner = None
        self._description = ""
        self._acquired_at = 0.0

    def get_status(self) -> dict:
        """Get lock status for the UI."""
        return {
            "locked": self.is_locked,
            "owner": self._owner,
            "description": self._description,
            "duration_s": round(self.lock_duration_s, 1) if self.is_locked else 0,
        }
