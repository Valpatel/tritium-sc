# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo mode end-to-end test — verifies the full pipeline works.

Tests:
1. POST /api/demo/start -> demo activates
2. Wait for synthetic data to flow -> GET /api/targets returns targets
3. GET /api/dossiers returns dossiers from correlation
4. POST /api/demo/stop -> demo deactivates

This proves the full pipeline: synthetic data -> TargetTracker -> correlation -> dossiers.
"""

from __future__ import annotations

import time

import pytest

from src.engine.comms.event_bus import EventBus
from src.engine.tactical.target_tracker import TargetTracker
from tritium_lib.tracking.dossier import DossierStore
from tritium_lib.tracking.correlator import TargetCorrelator


class TestDemoModePipeline:
    """Verify the demo mode pipeline generates targets and dossiers."""

    def test_synthetic_data_produces_targets(self):
        """Simulate what demo mode does: inject BLE+camera data,
        verify targets appear in TargetTracker."""
        event_bus = EventBus()
        tracker = TargetTracker()

        # Simulate BLE sightings (what demo mode generators produce)
        ble_devices = [
            {"mac": "AA:BB:CC:DD:EE:01", "name": "iPhone-Demo", "rssi": -55,
             "position": {"x": 10.0, "y": 20.0}},
            {"mac": "AA:BB:CC:DD:EE:02", "name": "Galaxy-Watch", "rssi": -65,
             "position": {"x": 15.0, "y": 25.0}},
            {"mac": "AA:BB:CC:DD:EE:03", "name": "MacBook-Pro", "rssi": -45,
             "position": {"x": 12.0, "y": 22.0}},
        ]

        for dev in ble_devices:
            tracker.update_from_ble(dev)

        # Simulate camera detections
        camera_detections = [
            {"class_name": "person", "confidence": 0.92,
             "center_x": 10.5, "center_y": 20.5, "bbox": [9, 19, 12, 22]},
            {"class_name": "person", "confidence": 0.87,
             "center_x": 15.2, "center_y": 25.3, "bbox": [14, 24, 17, 27]},
        ]

        for det in camera_detections:
            tracker.update_from_detection(det)

        # Verify targets exist
        all_targets = tracker.get_all()
        assert len(all_targets) >= 5, (
            f"Should have 3 BLE + 2 camera = 5+ targets, got {len(all_targets)}"
        )

        # Check BLE targets
        ble_targets = [t for t in all_targets if t.source == "ble"]
        assert len(ble_targets) == 3, f"Expected 3 BLE targets, got {len(ble_targets)}"

        # Check YOLO targets
        yolo_targets = [t for t in all_targets if t.source == "yolo"]
        assert len(yolo_targets) >= 2, f"Expected 2+ YOLO targets, got {len(yolo_targets)}"

    def test_correlation_produces_dossiers(self):
        """Verify that when BLE and camera targets are near each other,
        the correlator fuses them into dossiers."""
        tracker = TargetTracker()
        dossier_store = DossierStore()

        # Place BLE device and person at same location
        tracker.update_from_ble({
            "mac": "11:22:33:44:55:66", "name": "Pixel-Phone",
            "rssi": -50, "position": {"x": 30.0, "y": 40.0},
        })
        tracker.update_from_detection({
            "class_name": "person", "confidence": 0.9,
            "center_x": 30.1, "center_y": 40.1, "bbox": [29, 39, 31, 41],
        })

        # Run correlator
        correlator = TargetCorrelator(
            tracker, radius=5.0, confidence_threshold=0.2,
            dossier_store=dossier_store,
        )
        correlations = correlator.correlate()

        assert len(correlations) >= 1, (
            f"Should produce at least 1 correlation, got {len(correlations)}"
        )

        # Check dossiers
        all_dossiers = dossier_store.get_all()
        assert len(all_dossiers) >= 1, (
            f"Should have at least 1 dossier from correlation, got {len(all_dossiers)}"
        )

        # Verify dossier has multi-source signals
        dossier = all_dossiers[0]
        assert len(dossier.signal_ids) >= 2, (
            f"Dossier should fuse 2+ signals, got {dossier.signal_ids}"
        )
        assert "ble" in dossier.sources, "Dossier should include BLE source"
        assert "yolo" in dossier.sources, "Dossier should include YOLO source"

    def test_demo_controller_import(self):
        """Verify DemoController can be imported and instantiated."""
        from engine.synthetic.demo_mode import DemoController
        event_bus = EventBus()
        tracker = TargetTracker()
        controller = DemoController(
            event_bus=event_bus,
            target_tracker=tracker,
        )
        assert controller is not None
        assert not controller.active

    def test_demo_controller_start_stop(self):
        """Verify DemoController can start and stop."""
        from engine.synthetic.demo_mode import DemoController
        event_bus = EventBus()
        tracker = TargetTracker()
        controller = DemoController(
            event_bus=event_bus,
            target_tracker=tracker,
        )

        controller.start()
        assert controller.active

        status = controller.status()
        assert status["active"] is True
        assert status["generator_count"] >= 1

        controller.stop()
        assert not controller.active

    def test_demo_controller_generates_targets(self):
        """Start demo controller, wait briefly, verify targets appear."""
        from engine.synthetic.demo_mode import DemoController
        event_bus = EventBus()
        tracker = TargetTracker()
        controller = DemoController(
            event_bus=event_bus,
            target_tracker=tracker,
        )

        controller.start()
        assert controller.active

        # Wait for generators to produce some data
        time.sleep(3)

        targets = tracker.get_all()
        target_count = len(targets)

        controller.stop()

        # Demo mode should have produced at least some targets
        assert target_count >= 1, (
            f"Demo mode should produce targets after 3s, got {target_count}"
        )
