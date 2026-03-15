# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for investigation auto-close functionality."""

import time
import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass, field


@dataclass
class FakeTarget:
    target_id: str = ""
    alliance: str = "unknown"
    position: tuple = (0.0, 0.0)


class FakeTracker:
    def __init__(self, targets=None):
        self._targets = targets or {}
    def get_all(self):
        return dict(self._targets)


class FakeDossierStore:
    def __init__(self, dossiers=None):
        self._dossiers = dossiers or {}
    def get_dossier(self, entity_id):
        return self._dossiers.get(entity_id)


@pytest.fixture
def inv_engine(tmp_path):
    from engine.tactical.investigation import InvestigationEngine
    return InvestigationEngine(db_path=str(tmp_path / "test_inv.db"))


class TestInvestigationAutoClose:
    """Tests for check_auto_close functionality."""

    def test_empty_investigation_schedules_close(self, inv_engine):
        inv = inv_engine.create("Empty test", [])
        closed = inv_engine.check_auto_close(auto_close_delay_s=0.0)
        # Should schedule, not immediately close
        assert len(closed) == 0  # first call schedules

    def test_empty_investigation_closes_after_delay(self, inv_engine):
        inv = inv_engine.create("Empty test", [])
        # First call schedules with 0 delay
        inv_engine.check_auto_close(auto_close_delay_s=0.0)
        # Second call should close (scheduled time already passed)
        closed = inv_engine.check_auto_close(auto_close_delay_s=0.0)
        assert inv.inv_id in closed

    def test_resolved_dossiers_trigger_close(self, inv_engine):
        store = FakeDossierStore({
            "entity1": {"threat_level": "none"},
            "entity2": {"threat_level": "low"},
        })
        inv = inv_engine.create("Resolved test", ["entity1", "entity2"])
        inv_engine.check_auto_close(dossier_store=store, auto_close_delay_s=0.0)
        closed = inv_engine.check_auto_close(dossier_store=store, auto_close_delay_s=0.0)
        assert inv.inv_id in closed

    def test_active_threats_prevent_close(self, inv_engine):
        store = FakeDossierStore({
            "entity1": {"threat_level": "high"},
        })
        inv = inv_engine.create("Active threat", ["entity1"])
        closed = inv_engine.check_auto_close(dossier_store=store, auto_close_delay_s=0.0)
        assert len(closed) == 0
        # Should not schedule either — threat is active
        inv_reloaded = inv_engine.get(inv.inv_id)
        schedule_anns = [
            a for a in inv_reloaded.annotations
            if "AUTO-CLOSE SCHEDULED" in a.note
        ]
        assert len(schedule_anns) == 0

    def test_friendly_targets_trigger_close(self, inv_engine):
        tracker = FakeTracker({
            "target1": FakeTarget(target_id="target1", alliance="friendly"),
        })
        inv = inv_engine.create("Friendly test", ["target1"])
        inv_engine.check_auto_close(target_tracker=tracker, auto_close_delay_s=0.0)
        closed = inv_engine.check_auto_close(target_tracker=tracker, auto_close_delay_s=0.0)
        assert inv.inv_id in closed

    def test_hostile_targets_prevent_close(self, inv_engine):
        tracker = FakeTracker({
            "target1": FakeTarget(target_id="target1", alliance="hostile"),
        })
        inv = inv_engine.create("Hostile test", ["target1"])
        closed = inv_engine.check_auto_close(target_tracker=tracker, auto_close_delay_s=0.0)
        assert len(closed) == 0

    def test_departed_entities_considered_resolved(self, inv_engine):
        # Empty stores — entity not found anywhere
        store = FakeDossierStore({})
        tracker = FakeTracker({})
        inv = inv_engine.create("Departed test", ["gone_entity"])
        inv_engine.check_auto_close(
            dossier_store=store, target_tracker=tracker, auto_close_delay_s=0.0
        )
        closed = inv_engine.check_auto_close(
            dossier_store=store, target_tracker=tracker, auto_close_delay_s=0.0
        )
        assert inv.inv_id in closed

    def test_already_closed_not_reclosed(self, inv_engine):
        inv = inv_engine.create("Already closed", [])
        inv_engine.close(inv.inv_id)
        closed = inv_engine.check_auto_close(auto_close_delay_s=0.0)
        assert inv.inv_id not in closed

    def test_mixed_entities_resolved_and_active(self, inv_engine):
        store = FakeDossierStore({
            "resolved": {"threat_level": "none"},
            "active": {"threat_level": "critical"},
        })
        inv = inv_engine.create("Mixed test", ["resolved", "active"])
        closed = inv_engine.check_auto_close(dossier_store=store, auto_close_delay_s=0.0)
        assert len(closed) == 0

    def test_auto_close_annotation_added(self, inv_engine):
        inv = inv_engine.create("Annotation test", [])
        inv_engine.check_auto_close(auto_close_delay_s=0.0)
        inv_engine.check_auto_close(auto_close_delay_s=0.0)
        inv_reloaded = inv_engine.get(inv.inv_id)
        assert inv_reloaded.status == "closed"
        close_anns = [
            a for a in inv_reloaded.annotations
            if "Auto-closed" in a.note
        ]
        assert len(close_anns) >= 1
