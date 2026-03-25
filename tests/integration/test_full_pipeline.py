# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Full Sense-Decide-Act pipeline integration test.

Exercises the complete pipeline in-process without a server:

    BLE sighting -> TargetTracker -> BLEClassifier -> EnrichmentPipeline
    Camera detection -> TargetTracker -> near BLE position
    TargetCorrelator -> fuses BLE + camera into one dossier (CARRIES edge)
    Fused target enters geofenced zone -> alert fires
    ThreatClassifier escalation -> threat level raised

Proves all tactical subsystems work together end-to-end.

Run with:
    .venv/bin/python3 -m pytest tests/integration/test_full_pipeline.py -v
"""

from __future__ import annotations

import asyncio
import queue as queue_mod
import time

import pytest

from src.engine.comms.event_bus import EventBus
from tritium_lib.tracking.ble_classifier import BLEClassifier
from tritium_lib.tracking.correlator import TargetCorrelator
from tritium_lib.tracking.dossier import DossierStore
from src.engine.tactical.dossier_manager import DossierManager
from src.engine.tactical.enrichment import EnrichmentPipeline
from src.engine.tactical.escalation import ThreatClassifier
from tritium_lib.tracking.geofence import GeofenceEngine, GeoZone
from tritium_lib.tracking.target_tracker import TargetTracker

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _drain_events(q: queue_mod.Queue, timeout: float = 0.5) -> list[dict]:
    """Drain all events from a queue within timeout."""
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            events.append(q.get(timeout=0.05))
        except queue_mod.Empty:
            break
    return events


def _wait_for_event(q: queue_mod.Queue, event_type: str, timeout: float = 3.0) -> dict | None:
    """Wait for a specific event type on the queue."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = q.get(timeout=0.1)
            if msg.get("type") == event_type:
                return msg
        except queue_mod.Empty:
            continue
    return None


def _collect_events_of_type(q: queue_mod.Queue, event_type: str, timeout: float = 1.0) -> list[dict]:
    """Collect all events of a given type within timeout."""
    found: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = q.get(timeout=0.05)
            if msg.get("type") == event_type:
                found.append(msg)
        except queue_mod.Empty:
            continue
    return found


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """Sense-Decide-Act pipeline exercised in-process."""

    def test_ble_camera_fusion_geofence_escalation(self) -> None:
        """Full pipeline: BLE sighting + camera detection -> correlation
        -> dossier fusion -> geofence enter -> threat escalation.

        Steps:
            1. Wire up all components in-process (no server)
            2. BLE sighting arrives -> tracker updated, classifier runs,
               enrichment auto-triggers via EventBus
            3. Camera (YOLO) detection arrives near BLE position
            4. Correlator runs -> fuses BLE + camera into one dossier
               with CARRIES edge metadata
            5. Fused target enters a geofenced zone -> geofence:enter fires
            6. ThreatClassifier escalates threat level
            7. Verify: one dossier UUID with 2+ signals, correct enrichments,
               geofence event, threat escalated
        """

        # -- 1. Wire up all components ----------------------------------------
        event_bus = EventBus()
        tracker = TargetTracker()
        dossier_store = DossierStore()

        ble_classifier = BLEClassifier(event_bus=event_bus)
        enrichment = EnrichmentPipeline(event_bus=event_bus)

        # Use a mock graph_store to capture CARRIES edges
        graph_edges: list[dict] = []
        graph_entities: list[dict] = []

        class MockGraphStore:
            def create_entity(self, **kwargs):
                graph_entities.append(kwargs)

            def add_relationship(self, **kwargs):
                graph_edges.append(kwargs)

        graph_store = MockGraphStore()

        correlator = TargetCorrelator(
            tracker,
            radius=5.0,
            confidence_threshold=0.2,
            dossier_store=dossier_store,
            graph_store=graph_store,
        )

        # Geofence: define a restricted zone around position (5, 5)
        geofence = GeofenceEngine(event_bus=event_bus)
        zone = GeoZone(
            zone_id="zone-alpha",
            name="Restricted Area Alpha",
            polygon=[
                (2.0, 2.0),
                (8.0, 2.0),
                (8.0, 8.0),
                (2.0, 8.0),
            ],
            zone_type="restricted",
            alert_on_enter=True,
        )
        geofence.add_zone(zone)

        # ThreatClassifier with zone that matches our geofence area
        threat_zones = [
            {
                "name": "Restricted Area Alpha",
                "type": "restricted",
                "position": {"x": 5.0, "y": 5.0},
                "properties": {"radius": 5.0},
            }
        ]
        threat_classifier = ThreatClassifier(
            event_bus=event_bus,
            target_tracker=tracker,
            zones=threat_zones,
            linger_threshold=0.1,  # fast for testing
        )

        dossier_manager = DossierManager(
            store=dossier_store,
            tracker=tracker,
            event_bus=event_bus,
        )

        # Subscribe to EventBus for verification
        observer_queue = event_bus.subscribe()

        # -- 2. BLE sighting arrives ------------------------------------------
        # Simulate an Espressif device sighting at position (5.0, 5.0)
        ble_mac = "30:AE:A4:11:22:33"
        ble_sighting = {
            "mac": ble_mac,
            "name": "ESP32-Device",
            "rssi": -45,
            "node_id": "node-01",
            "position": {"x": 5.0, "y": 5.0},
        }

        # Feed to tracker
        tracker.update_from_ble(ble_sighting)
        ble_target_id = f"ble_{ble_mac.replace(':', '').lower()}"

        # Verify tracker has the BLE target
        ble_target = tracker.get_target(ble_target_id)
        assert ble_target is not None, "BLE target should be in tracker"
        assert ble_target.source == "ble"
        assert ble_target.position == (5.0, 5.0)

        # Run BLE classifier
        classification = ble_classifier.classify(ble_mac, "ESP32-Device", rssi=-45)
        assert classification.level in ("new", "suspicious"), (
            f"First-time device should be new or suspicious, got {classification.level}"
        )

        # Run enrichment pipeline (async)
        enrichment_results = asyncio.run(
            enrichment.enrich(ble_target_id, {"mac": ble_mac, "name": "ESP32-Device"})
        )

        # Verify enrichment found manufacturer (Espressif via OUI fallback)
        oui_results = [r for r in enrichment_results if r.provider == "oui_lookup"]
        assert len(oui_results) == 1, "OUI lookup should find Espressif for 30:AE:A4"
        assert oui_results[0].data["manufacturer"] == "Espressif"

        # BLE device class enrichment should match ESP32 pattern
        ble_class_results = [r for r in enrichment_results if r.provider == "ble_device_class"]
        assert len(ble_class_results) == 1, "BLE device class should match ESP32"
        assert ble_class_results[0].data["category"] == "microcontroller"

        # Drain early events (BLE alert etc.)
        _drain_events(observer_queue, timeout=0.3)

        # -- 3. Camera detection arrives near BLE position --------------------
        camera_detection = {
            "class_name": "person",
            "confidence": 0.85,
            "center_x": 5.1,
            "center_y": 5.1,
            "bbox": [4.8, 4.8, 5.4, 5.4],
        }
        tracker.update_from_detection(camera_detection)

        # Find the YOLO detection target
        all_targets = tracker.get_all()
        yolo_targets = [t for t in all_targets if t.source == "yolo"]
        assert len(yolo_targets) >= 1, "Should have at least one YOLO detection"
        yolo_target = yolo_targets[0]
        assert yolo_target.asset_type == "person"

        # -- 4. Correlator runs -----------------------------------------------
        # Both targets exist: BLE device at (5.0, 5.0), person at (5.1, 5.1)
        # Spatial proximity is very high, signal pattern should also score
        correlations = correlator.correlate()

        assert len(correlations) >= 1, (
            f"Correlator should fuse BLE + camera targets, got {len(correlations)} correlations"
        )
        record = correlations[0]
        assert record.dossier_uuid, "Correlation should produce a dossier UUID"
        assert record.confidence > 0.2, (
            f"Correlation confidence should exceed threshold, got {record.confidence}"
        )

        # Verify the dossier has both signal IDs
        dossier = dossier_store.find_by_uuid(record.dossier_uuid)
        assert dossier is not None, "Dossier should exist in store"
        assert len(dossier.signal_ids) >= 2, (
            f"Dossier should have 2+ signal IDs, got {dossier.signal_ids}"
        )
        assert len(dossier.sources) >= 2, (
            f"Dossier should have 2+ sources, got {dossier.sources}"
        )
        assert "ble" in dossier.sources, "Dossier should include BLE source"
        assert "yolo" in dossier.sources, "Dossier should include YOLO source"

        # Verify CARRIES edge was written to graph store
        carries_edges = [e for e in graph_edges if e.get("rel_type") == "CARRIES"]
        assert len(carries_edges) >= 1, (
            f"CARRIES edge should be written (BLE device -> person), got {graph_edges}"
        )
        carries = carries_edges[0]
        assert carries["rel_type"] == "CARRIES"

        # Verify CORRELATED_WITH edge
        corr_edges = [e for e in graph_edges if e.get("rel_type") == "CORRELATED_WITH"]
        assert len(corr_edges) >= 1, "CORRELATED_WITH edge should be written"

        # -- 5. Fused target enters geofenced zone ----------------------------
        # The primary target (surviving after merge) should be at ~(5, 5)
        # which is inside our geofence polygon
        surviving_targets = tracker.get_all()
        assert len(surviving_targets) >= 1, "Should have at least one target after merge"

        # Find the fused target (it will be the one that survived the merge)
        fused_target = surviving_targets[0]

        # Check geofence
        geo_events = geofence.check(fused_target.target_id, fused_target.position)

        # Should have an enter event since this is the first check
        enter_events = [e for e in geo_events if e.event_type == "enter"]
        assert len(enter_events) >= 1, (
            f"Fused target at {fused_target.position} should enter Restricted Area Alpha, "
            f"got events: {[e.event_type for e in geo_events]}"
        )
        assert enter_events[0].zone_name == "Restricted Area Alpha"
        assert enter_events[0].zone_type == "restricted"

        # Verify geofence:enter was published to EventBus
        geo_enter_event = _wait_for_event(observer_queue, "geofence:enter", timeout=1.0)
        assert geo_enter_event is not None, "geofence:enter event should be published to EventBus"
        assert geo_enter_event["data"]["zone_name"] == "Restricted Area Alpha"

        # -- 6. Threat escalation ---------------------------------------------
        # Run threat classifier tick manually (the target is in a restricted zone)
        threat_classifier._classify_tick()

        # The fused target should have been escalated
        records = threat_classifier.get_records()

        # Find the threat record for our fused target
        threat_record = records.get(fused_target.target_id)
        assert threat_record is not None, (
            f"Threat record should exist for {fused_target.target_id}, "
            f"records: {list(records.keys())}"
        )
        assert threat_record.threat_level in ("unknown", "suspicious", "hostile"), (
            f"Threat should be escalated from 'none', got '{threat_record.threat_level}'"
        )

        # Since we are in a restricted zone, should be at least suspicious
        assert threat_record.threat_level in ("suspicious", "hostile"), (
            f"Target in restricted zone should be suspicious or hostile, "
            f"got '{threat_record.threat_level}'"
        )

        # Verify escalation event was published
        esc_event = _wait_for_event(observer_queue, "threat_escalation", timeout=1.0)
        assert esc_event is not None, "threat_escalation event should be published"
        assert esc_event["data"]["target_id"] == fused_target.target_id

        # -- 7. Verify final state ---------------------------------------------
        # One dossier with 2+ signals
        all_dossiers = dossier_store.get_all()
        assert len(all_dossiers) == 1, (
            f"Should have exactly one dossier (fused), got {len(all_dossiers)}"
        )
        final_dossier = all_dossiers[0]
        assert len(final_dossier.signal_ids) >= 2
        assert final_dossier.confidence > 0

        # Enrichment results cached for the BLE target
        cached_enrichments = enrichment.get_cached(ble_target_id)
        assert cached_enrichments is not None, "Enrichment results should be cached"
        assert len(cached_enrichments) >= 1, "Should have at least OUI enrichment"

        # Geofence has the target tracked inside the zone
        target_zones = geofence.get_target_zones(fused_target.target_id)
        assert "zone-alpha" in target_zones, "Target should be inside zone-alpha"

        # Graph store has entities and relationships
        assert len(graph_entities) >= 2, "Graph should have 2+ entity nodes"
        assert len(graph_edges) >= 2, "Graph should have CORRELATED_WITH + CARRIES edges"

        # Clean up
        enrichment.stop()
