# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the proximity monitor engine."""

import math
import time
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field

# Minimal TrackedTarget stub for tests
@dataclass
class FakeTarget:
    target_id: str = ""
    name: str = ""
    alliance: str = "unknown"
    asset_type: str = "person"
    position: tuple = (0.0, 0.0)
    heading: float = 0.0
    speed: float = 0.0
    battery: float = 1.0
    last_seen: float = field(default_factory=time.monotonic)
    source: str = "manual"
    status: str = "active"


class FakeTracker:
    """Minimal tracker stub."""
    def __init__(self, targets: dict = None):
        self._targets = targets or {}

    def get_all(self):
        return dict(self._targets)


@pytest.fixture
def _no_persist(tmp_path, monkeypatch):
    """Point proximity data dir to tmp."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib
    import engine.tactical.proximity_monitor as pm
    monkeypatch.setattr(pm, "_DATA_DIR", tmp_path / "proximity")


class TestProximityMonitor:
    """Tests for ProximityMonitor."""

    def test_scan_no_targets(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        tracker = FakeTracker({})
        monitor = ProximityMonitor(target_tracker=tracker)
        monitor._scan()
        assert monitor._alerts_fired == 0

    def test_scan_same_alliance_no_alert(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        targets = {
            "a": FakeTarget(target_id="a", alliance="friendly", position=(0, 0)),
            "b": FakeTarget(target_id="b", alliance="friendly", position=(5, 0)),
        }
        tracker = FakeTracker(targets)
        monitor = ProximityMonitor(target_tracker=tracker)
        monitor._scan()
        assert monitor._alerts_fired == 0

    def test_scan_different_alliance_breach(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        targets = {
            "a": FakeTarget(target_id="a", alliance="hostile", position=(0, 0)),
            "b": FakeTarget(target_id="b", alliance="friendly", position=(5, 0)),
        }
        tracker = FakeTracker(targets)
        monitor = ProximityMonitor(target_tracker=tracker)
        # Default rule: hostile_friendly, 10m threshold
        monitor._scan()
        assert monitor._alerts_fired == 1
        alerts = monitor.get_recent_alerts()
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "breach"
        assert alerts[0]["distance_m"] == 5.0

    def test_scan_outside_threshold_no_alert(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        targets = {
            "a": FakeTarget(target_id="a", alliance="hostile", position=(0, 0)),
            "b": FakeTarget(target_id="b", alliance="friendly", position=(20, 0)),
        }
        tracker = FakeTracker(targets)
        monitor = ProximityMonitor(target_tracker=tracker)
        monitor._scan()
        assert monitor._alerts_fired == 0

    def test_cooldown_prevents_repeat_alert(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        targets = {
            "a": FakeTarget(target_id="a", alliance="hostile", position=(0, 0)),
            "b": FakeTarget(target_id="b", alliance="friendly", position=(5, 0)),
        }
        tracker = FakeTracker(targets)
        monitor = ProximityMonitor(target_tracker=tracker)
        monitor._scan()
        assert monitor._alerts_fired == 1
        # Second scan within cooldown — no new alert
        monitor._scan()
        assert monitor._alerts_fired == 1

    def test_departure_alert(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        targets = {
            "a": FakeTarget(target_id="a", alliance="hostile", position=(0, 0)),
            "b": FakeTarget(target_id="b", alliance="friendly", position=(5, 0)),
        }
        tracker = FakeTracker(targets)
        monitor = ProximityMonitor(target_tracker=tracker)
        monitor._scan()
        assert monitor._alerts_fired == 1
        # Move targets apart
        targets["b"].position = (50, 0)
        monitor._scan()
        # Should fire departure
        assert monitor._alerts_fired == 2
        alerts = monitor.get_recent_alerts()
        assert alerts[-1]["alert_type"] == "departure"

    def test_event_bus_publish(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        bus = MagicMock()
        targets = {
            "a": FakeTarget(target_id="a", alliance="hostile", position=(0, 0)),
            "b": FakeTarget(target_id="b", alliance="friendly", position=(3, 0)),
        }
        tracker = FakeTracker(targets)
        monitor = ProximityMonitor(target_tracker=tracker, event_bus=bus)
        monitor._scan()
        bus.publish.assert_called()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "proximity:alert"

    def test_rule_crud(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor, ProximityRule
        monitor = ProximityMonitor()
        initial_count = len(monitor.list_rules())

        rule = ProximityRule(rule_id="test_rule", name="Test", threshold_m=5.0)
        monitor.add_rule(rule)
        assert len(monitor.list_rules()) == initial_count + 1

        ok = monitor.update_rule("test_rule", {"threshold_m": 15.0})
        assert ok is True
        updated = [r for r in monitor.list_rules() if r.rule_id == "test_rule"][0]
        assert updated.threshold_m == 15.0

        ok = monitor.remove_rule("test_rule")
        assert ok is True
        assert len(monitor.list_rules()) == initial_count

    def test_acknowledge_alert(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        targets = {
            "a": FakeTarget(target_id="a", alliance="hostile", position=(0, 0)),
            "b": FakeTarget(target_id="b", alliance="friendly", position=(3, 0)),
        }
        tracker = FakeTracker(targets)
        monitor = ProximityMonitor(target_tracker=tracker)
        monitor._scan()
        alerts = monitor.get_recent_alerts()
        alert_id = alerts[0]["alert_id"]
        ok = monitor.acknowledge_alert(alert_id)
        assert ok is True

    def test_severity_classification(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        # Target at 2m with 10m threshold -> critical severity
        targets = {
            "a": FakeTarget(target_id="a", alliance="hostile", position=(0, 0)),
            "b": FakeTarget(target_id="b", alliance="friendly", position=(2, 0)),
        }
        tracker = FakeTracker(targets)
        monitor = ProximityMonitor(target_tracker=tracker)
        monitor._scan()
        alerts = monitor.get_recent_alerts()
        assert alerts[0]["severity"] == "critical"

    def test_get_stats(self, _no_persist):
        from engine.tactical.proximity_monitor import ProximityMonitor
        monitor = ProximityMonitor()
        stats = monitor.get_stats()
        assert "running" in stats
        assert "scans_completed" in stats
        assert "alerts_fired" in stats
        assert "total_rules" in stats
