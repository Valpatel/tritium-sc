# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for new signal type constants in comms.py (Phase 1)."""

from __future__ import annotations

import pytest

from engine.simulation.comms import (
    SIGNAL_DISTRESS,
    SIGNAL_CONTACT,
    SIGNAL_REGROUP,
    SIGNAL_INSTIGATOR_MARKED,
    SIGNAL_EMP_JAMMING,
    UnitComms,
)


pytestmark = pytest.mark.unit


class TestNewSignalConstants:
    def test_instigator_marked_constant(self):
        """SIGNAL_INSTIGATOR_MARKED constant exists."""
        assert SIGNAL_INSTIGATOR_MARKED == "instigator_marked"

    def test_emp_jamming_constant(self):
        """SIGNAL_EMP_JAMMING constant exists."""
        assert SIGNAL_EMP_JAMMING == "emp_jamming"

    def test_existing_constants_unchanged(self):
        """Pre-existing signal constants are unchanged."""
        assert SIGNAL_DISTRESS == "distress"
        assert SIGNAL_CONTACT == "contact"
        assert SIGNAL_REGROUP == "regroup"

    def test_broadcast_instigator_marked(self):
        """UnitComms can broadcast an instigator_marked signal."""
        comms = UnitComms()
        sig = comms.broadcast(
            SIGNAL_INSTIGATOR_MARKED,
            sender_id="scout-1",
            sender_alliance="friendly",
            position=(50.0, 50.0),
            target_position=(60.0, 55.0),
        )
        assert sig.signal_type == "instigator_marked"
        assert sig.target_position == (60.0, 55.0)

    def test_broadcast_emp_jamming(self):
        """UnitComms can broadcast an emp_jamming signal."""
        comms = UnitComms()
        sig = comms.broadcast(
            SIGNAL_EMP_JAMMING,
            sender_id="hostile-scout-1",
            sender_alliance="hostile",
            position=(80.0, 80.0),
        )
        assert sig.signal_type == "emp_jamming"
