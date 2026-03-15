# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for DossierEnvEnrichment — meshtastic env data -> BLE target dossiers."""

import time
import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from engine.tactical.dossier_env_enrichment import DossierEnvEnrichment


class FakeEventBus:
    """Minimal EventBus mock for testing."""

    def __init__(self):
        self._subscriptions = []
        self._published = []

    def subscribe(self):
        import queue
        q = queue.Queue()
        self._subscriptions.append(q)
        return q

    def unsubscribe(self, q):
        self._subscriptions = [s for s in self._subscriptions if s is not q]

    def publish(self, event_type, data=None):
        msg = {"type": event_type, "data": data or {}}
        self._published.append(msg)
        for q in self._subscriptions:
            q.put(msg)


class FakeTracker:
    """Minimal TargetTracker mock."""

    def __init__(self, targets=None):
        self._targets = targets or []
        self._annotations = {}

    def get_all_targets(self):
        return self._targets

    def annotate_target(self, target_id, data):
        self._annotations[target_id] = data


class TestDossierEnvEnrichment:
    """Test the DossierEnvEnrichment service."""

    def test_init(self):
        bus = FakeEventBus()
        tracker = FakeTracker()
        service = DossierEnvEnrichment(bus, tracker)
        assert service is not None

    def test_get_latest_environment_empty(self):
        bus = FakeEventBus()
        tracker = FakeTracker()
        service = DossierEnvEnrichment(bus, tracker)
        assert service.get_latest_environment() is None

    def test_env_cache_update(self):
        bus = FakeEventBus()
        tracker = FakeTracker()
        service = DossierEnvEnrichment(bus, tracker)

        # Simulate environment event processing directly
        service._on_environment({
            "source_id": "!abc123",
            "source_name": "Node-Alpha",
            "temperature_c": 22.5,
            "humidity_pct": 45.0,
            "pressure_hpa": 1013.25,
        })

        env = service.get_latest_environment("!abc123")
        assert env is not None
        assert env["temperature_c"] == 22.5
        assert env["humidity_pct"] == 45.0
        assert env["source_name"] == "Node-Alpha"

    def test_enriches_ble_targets(self):
        bus = FakeEventBus()
        targets = [
            {
                "target_id": "ble_aabbccddeeff",
                "source": "ble",
                "last_seen": time.time(),
            },
            {
                "target_id": "det_person_1",
                "source": "yolo",
                "last_seen": time.time(),
            },
        ]
        tracker = FakeTracker(targets)

        service = DossierEnvEnrichment(bus, tracker, cooldown_s=0)

        service._on_environment({
            "source_id": "!abc123",
            "source_name": "Node-Alpha",
            "temperature_c": 22.5,
            "humidity_pct": 45.0,
            "pressure_hpa": 1013.25,
        })

        # BLE target should have been annotated
        assert "ble_aabbccddeeff" in tracker._annotations
        ann = tracker._annotations["ble_aabbccddeeff"]
        assert "environment" in ann
        assert ann["environment"]["temperature_c"] == 22.5

        # YOLO target should NOT have been annotated (not BLE)
        assert "det_person_1" not in tracker._annotations

    def test_cooldown_prevents_spam(self):
        bus = FakeEventBus()
        targets = [
            {
                "target_id": "ble_aabbccddeeff",
                "source": "ble",
                "last_seen": time.time(),
            },
        ]
        tracker = FakeTracker(targets)

        service = DossierEnvEnrichment(bus, tracker, cooldown_s=300)

        service._on_environment({
            "source_id": "!abc123",
            "source_name": "Node-Alpha",
            "temperature_c": 22.5,
        })

        # First enrichment should work
        assert "ble_aabbccddeeff" in tracker._annotations

        # Clear annotations
        tracker._annotations.clear()

        # Second enrichment within cooldown should be skipped
        service._on_environment({
            "source_id": "!abc123",
            "source_name": "Node-Alpha",
            "temperature_c": 25.0,
        })

        assert "ble_aabbccddeeff" not in tracker._annotations

    def test_stale_target_not_enriched(self):
        bus = FakeEventBus()
        targets = [
            {
                "target_id": "ble_aabbccddeeff",
                "source": "ble",
                "last_seen": time.time() - 500,  # 500 seconds old
            },
        ]
        tracker = FakeTracker(targets)

        service = DossierEnvEnrichment(bus, tracker, max_target_age_s=120, cooldown_s=0)

        service._on_environment({
            "source_id": "!abc123",
            "source_name": "Node-Alpha",
            "temperature_c": 22.5,
        })

        # Stale target should not be enriched
        assert "ble_aabbccddeeff" not in tracker._annotations

    def test_get_all_environments(self):
        bus = FakeEventBus()
        tracker = FakeTracker()
        service = DossierEnvEnrichment(bus, tracker)

        service._on_environment({
            "source_id": "!node1",
            "source_name": "Alpha",
            "temperature_c": 20.0,
        })
        service._on_environment({
            "source_id": "!node2",
            "source_name": "Beta",
            "temperature_c": 25.0,
        })

        envs = service.get_all_environments()
        assert len(envs) == 2
        assert "!node1" in envs
        assert "!node2" in envs
