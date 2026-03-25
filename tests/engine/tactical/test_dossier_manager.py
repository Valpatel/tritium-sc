# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for DossierManager — bridges TargetTracker and DossierStore."""

import tempfile
import time

import pytest

from tritium_lib.store.dossiers import DossierStore

from src.engine.comms.event_bus import EventBus
from src.engine.tactical.dossier_manager import DossierManager
from tritium_lib.tracking.target_tracker import TargetTracker, TrackedTarget


def _make_store(tmp_path=None):
    """Create a temporary DossierStore."""
    if tmp_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        return DossierStore(tmp.name)
    return DossierStore(tmp_path / "test_dossiers.db")


def _make_tracker_with(*targets: TrackedTarget) -> TargetTracker:
    """Create a TargetTracker pre-loaded with targets."""
    tracker = TargetTracker()
    with tracker._lock:
        for t in targets:
            tracker._targets[t.target_id] = t
    return tracker


class TestDossierManagerCRUD:
    """Basic create, read, find-or-create operations."""

    @pytest.mark.unit
    def test_find_or_create_creates_new(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("test_target_1", name="Test Target")
        assert did
        dossier = mgr.get_dossier(did)
        assert dossier is not None
        assert dossier["name"] == "Test Target"
        store.close()

    @pytest.mark.unit
    def test_find_or_create_returns_existing(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did1 = mgr.find_or_create_for_target("t1", name="Alpha")
        did2 = mgr.find_or_create_for_target("t1", name="Should Not Change")
        assert did1 == did2
        store.close()

    @pytest.mark.unit
    def test_find_or_create_ble_by_mac(self):
        """BLE targets should be found by MAC identifier lookup."""
        store = _make_store()
        mgr = DossierManager(store=store)
        # Create dossier with MAC identifier
        did1 = mgr.find_or_create_for_target(
            "ble_aabbccddeeff",
            name="Phone",
            identifiers={"mac": "AA:BB:CC:DD:EE:FF"},
        )
        # Second lookup with same MAC-based target_id should find it
        did2 = mgr.find_or_create_for_target("ble_aabbccddeeff")
        assert did1 == did2
        store.close()

    @pytest.mark.unit
    def test_get_dossier_for_target(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("target_x", name="X")

        result = mgr.get_dossier_for_target("target_x")
        assert result is not None
        assert result["dossier_id"] == did
        store.close()

    @pytest.mark.unit
    def test_get_dossier_for_unknown_target(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        result = mgr.get_dossier_for_target("nonexistent")
        assert result is None
        store.close()


class TestSignalsAndEnrichments:
    """Adding signals and enrichments through the manager."""

    @pytest.mark.unit
    def test_add_signal(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1")
        sig_id = mgr.add_signal_to_target(
            "t1", source="ble", signal_type="mac_sighting",
            data={"mac": "AA:BB:CC:DD:EE:FF"}, confidence=0.8,
        )
        assert sig_id is not None

        dossier = mgr.get_dossier_for_target("t1")
        assert len(dossier["signals"]) == 1
        assert dossier["signals"][0]["source"] == "ble"
        store.close()

    @pytest.mark.unit
    def test_add_signal_no_dossier(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        result = mgr.add_signal_to_target("ghost", "ble", "sighting")
        assert result is None
        store.close()

    @pytest.mark.unit
    def test_add_enrichment(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1")
        eid = mgr.add_enrichment_to_target(
            "t1", provider="oui", enrichment_type="manufacturer",
            data={"manufacturer": "Apple"},
        )
        assert eid is not None

        dossier = mgr.get_dossier_for_target("t1")
        assert len(dossier["enrichments"]) == 1
        assert dossier["enrichments"][0]["provider"] == "oui"
        store.close()


class TestTagsAndNotes:
    """Tag and note management."""

    @pytest.mark.unit
    def test_add_tag(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t1")
        assert mgr.add_tag(did, "suspicious") is True
        dossier = mgr.get_dossier(did)
        assert "suspicious" in dossier["tags"]
        store.close()

    @pytest.mark.unit
    def test_add_tag_deduplication(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t1")
        mgr.add_tag(did, "ble")
        mgr.add_tag(did, "ble")
        dossier = mgr.get_dossier(did)
        assert dossier["tags"].count("ble") == 1
        store.close()

    @pytest.mark.unit
    def test_add_tag_nonexistent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        assert mgr.add_tag("fake_id", "tag") is False
        store.close()

    @pytest.mark.unit
    def test_add_note(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t1")
        assert mgr.add_note(did, "First seen near gate") is True
        dossier = mgr.get_dossier(did)
        assert "First seen near gate" in dossier["notes"]
        store.close()

    @pytest.mark.unit
    def test_add_note_nonexistent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        assert mgr.add_note("fake_id", "note") is False
        store.close()


class TestMerge:
    """Dossier merge operations."""

    @pytest.mark.unit
    def test_merge_success(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did1 = mgr.find_or_create_for_target("t1", name="Alpha", tags=["ble"])
        did2 = mgr.find_or_create_for_target("t2", name="Beta", tags=["yolo"])

        # Add signals to both
        mgr.add_signal_to_target("t1", "ble", "sighting", confidence=0.5)
        mgr.add_signal_to_target("t2", "yolo", "detection", confidence=0.7)

        result = mgr.merge(did1, did2)
        assert result is True

        # Primary should have both signals
        dossier = mgr.get_dossier(did1)
        assert dossier is not None
        assert len(dossier["signals"]) == 2

        # Secondary should be gone
        assert mgr.get_dossier(did2) is None

        # Target t2 should now map to primary dossier
        assert mgr.get_dossier_for_target("t2")["dossier_id"] == did1
        store.close()

    @pytest.mark.unit
    def test_merge_nonexistent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did1 = mgr.find_or_create_for_target("t1")
        assert mgr.merge(did1, "fake_id") is False
        store.close()


class TestSearch:
    """Full-text search."""

    @pytest.mark.unit
    def test_search_by_name(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1", name="iPhone Pro Max")
        mgr.find_or_create_for_target("t2", name="Android Phone")

        results = mgr.search("iPhone")
        assert len(results) >= 1
        assert any("iPhone" in r.get("name", "") for r in results)
        store.close()

    @pytest.mark.unit
    def test_search_empty_query(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        results = mgr.search("")
        assert results == []
        store.close()


class TestListing:
    """List and pagination."""

    @pytest.mark.unit
    def test_list_dossiers(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        for i in range(5):
            mgr.find_or_create_for_target(f"t{i}", name=f"Target {i}")

        result = mgr.list_dossiers(limit=3)
        assert len(result) == 3
        store.close()

    @pytest.mark.unit
    def test_list_with_offset(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        for i in range(5):
            mgr.find_or_create_for_target(f"t{i}", name=f"Target {i}")

        page1 = mgr.list_dossiers(limit=3, offset=0)
        page2 = mgr.list_dossiers(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2

        # No overlap
        ids1 = {d["dossier_id"] for d in page1}
        ids2 = {d["dossier_id"] for d in page2}
        assert ids1.isdisjoint(ids2)
        store.close()

    @pytest.mark.unit
    def test_get_all_active(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1", name="Recent")
        result = mgr.get_all_active_dossiers()
        assert len(result) >= 1
        store.close()


class TestEventHandling:
    """Event-driven dossier creation via EventBus."""

    @pytest.mark.unit
    def test_handle_ble_event(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr._handle_ble_device({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "iPhone",
            "rssi": -50,
        })
        dossier = mgr.get_dossier_for_target("ble_aabbccddeeff")
        assert dossier is not None
        assert dossier["name"] == "iPhone"
        assert len(dossier["signals"]) >= 1
        store.close()

    @pytest.mark.unit
    def test_handle_ble_event_no_mac(self):
        """BLE event without MAC should be ignored."""
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr._handle_ble_device({"name": "noMAC"})
        assert len(store.get_recent()) == 0
        store.close()

    @pytest.mark.unit
    def test_handle_detection_event(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr._handle_detection({
            "detections": [
                {"class_name": "person", "confidence": 0.85, "target_id": "det_person_1"},
            ],
        })
        dossier = mgr.get_dossier_for_target("det_person_1")
        assert dossier is not None
        assert len(dossier["signals"]) >= 1
        store.close()

    @pytest.mark.unit
    def test_handle_detection_low_confidence_ignored(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr._handle_detection({
            "detections": [
                {"class_name": "person", "confidence": 0.2, "target_id": "det_low"},
            ],
        })
        result = mgr.get_dossier_for_target("det_low")
        assert result is None
        store.close()

    @pytest.mark.unit
    def test_handle_correlation_event(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        # Pre-create both targets
        mgr.find_or_create_for_target("ble_abc", name="BLE Device")
        mgr.find_or_create_for_target("det_person_1", name="Person")

        mgr._handle_correlation({
            "primary_id": "ble_abc",
            "secondary_id": "det_person_1",
            "confidence": 0.8,
            "reason": "ble+yolo within 3.0 units",
        })

        # Should have merged — only primary dossier remains
        primary = mgr.get_dossier_for_target("ble_abc")
        assert primary is not None
        # Secondary should now point to primary
        secondary = mgr.get_dossier_for_target("det_person_1")
        assert secondary is not None
        assert secondary["dossier_id"] == primary["dossier_id"]
        store.close()

    @pytest.mark.unit
    def test_handle_enrichment_event(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1")
        mgr._handle_enrichment({
            "target_id": "t1",
            "results": [
                {
                    "provider": "oui_lookup",
                    "enrichment_type": "manufacturer",
                    "data": {"manufacturer": "Apple"},
                },
            ],
        })
        dossier = mgr.get_dossier_for_target("t1")
        assert len(dossier["enrichments"]) == 1
        assert dossier["enrichments"][0]["provider"] == "oui_lookup"
        store.close()


class TestLifecycle:
    """Start/stop lifecycle."""

    @pytest.mark.unit
    def test_start_stop_no_event_bus(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.start()
        assert mgr._running is True
        assert mgr._flush_thread is not None
        assert mgr._listener_thread is None  # no event bus
        mgr.stop()
        assert mgr._running is False
        store.close()

    @pytest.mark.unit
    def test_start_stop_with_event_bus(self):
        store = _make_store()
        bus = EventBus()
        mgr = DossierManager(store=store, event_bus=bus, flush_interval=0.5)
        mgr.start()
        assert mgr._running is True
        assert mgr._listener_thread is not None
        assert mgr._flush_thread is not None
        mgr.stop()
        assert mgr._running is False
        store.close()

    @pytest.mark.unit
    def test_start_idempotent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.start()
        thread = mgr._flush_thread
        mgr.start()  # should not create new thread
        assert mgr._flush_thread is thread
        mgr.stop()
        store.close()

    @pytest.mark.unit
    def test_event_bus_integration(self):
        """Events published to EventBus should create dossiers."""
        store = _make_store()
        bus = EventBus()
        mgr = DossierManager(store=store, event_bus=bus, flush_interval=60)
        mgr.start()

        # Publish a BLE event
        bus.publish("ble:new_device", {
            "mac": "11:22:33:44:55:66",
            "name": "TestDevice",
            "rssi": -60,
        })

        # Give the listener thread time to process
        time.sleep(0.5)

        dossier = mgr.get_dossier_for_target("ble_112233445566")
        assert dossier is not None
        assert dossier["name"] == "TestDevice"

        mgr.stop()
        store.close()


class TestDossierStoreUpdateJsonField:
    """Tests for the _update_json_field helper on DossierStore."""

    @pytest.mark.unit
    def test_update_tags(self):
        store = _make_store()
        did = store.create_dossier("Test", tags=["initial"])
        store._update_json_field(did, "tags", ["initial", "new_tag"])
        dossier = store.get_dossier(did)
        assert "new_tag" in dossier["tags"]
        store.close()

    @pytest.mark.unit
    def test_update_notes(self):
        store = _make_store()
        did = store.create_dossier("Test")
        store._update_json_field(did, "notes", ["A note"])
        dossier = store.get_dossier(did)
        assert "A note" in dossier["notes"]
        store.close()

    @pytest.mark.unit
    def test_update_invalid_field_raises(self):
        store = _make_store()
        did = store.create_dossier("Test")
        with pytest.raises(ValueError):
            store._update_json_field(did, "name", "evil")
        store.close()

    @pytest.mark.unit
    def test_update_nonexistent_dossier(self):
        store = _make_store()
        result = store._update_json_field("fake_id", "tags", ["x"])
        assert result is False
        store.close()


class TestWiFiProbeEnrichment:
    """WiFi probe data auto-enrichment of BLE dossiers."""

    @pytest.mark.unit
    def test_wifi_probe_enriches_ble_dossier(self):
        """BLE dossier with matching node_id gets WiFi probe enrichment."""
        store = _make_store()
        mgr = DossierManager(store=store)

        # Create BLE dossier with signal from node "edge-01"
        did = mgr.find_or_create_for_target(
            "ble_aabbccddeeff",
            name="Phone",
            identifiers={"mac": "AA:BB:CC:DD:EE:FF"},
        )
        mgr.add_signal_to_target(
            "ble_aabbccddeeff",
            source="ble",
            signal_type="presence",
            data={"mac": "AA:BB:CC:DD:EE:FF", "rssi": -50, "node_id": "edge-01"},
        )

        # Now WiFi presence arrives from the same node
        mgr._handle_wifi_presence({
            "node_id": "edge-01",
            "networks": [
                {"ssid": "HomeNet-5G", "probe": True},
                {"ssid": "WorkOffice", "probe": True},
            ],
        })

        dossier = mgr.get_dossier(did)
        assert dossier is not None
        enrichments = dossier.get("enrichments", [])
        wifi_enrichments = [e for e in enrichments if e.get("provider") == "wifi_probe_enrichment"]
        assert len(wifi_enrichments) >= 1
        data = wifi_enrichments[0].get("data", {})
        assert "HomeNet-5G" in data.get("ssids", [])
        assert "WorkOffice" in data.get("ssids", [])
        store.close()

    @pytest.mark.unit
    def test_wifi_probe_no_enrichment_different_node(self):
        """BLE dossier from different node should NOT be enriched."""
        store = _make_store()
        mgr = DossierManager(store=store)

        # Create BLE dossier from node "edge-01"
        mgr.find_or_create_for_target(
            "ble_112233445566",
            name="Watch",
            identifiers={"mac": "11:22:33:44:55:66"},
        )
        mgr.add_signal_to_target(
            "ble_112233445566",
            source="ble",
            signal_type="presence",
            data={"mac": "11:22:33:44:55:66", "rssi": -70, "node_id": "edge-01"},
        )

        # WiFi from a different node
        mgr._handle_wifi_presence({
            "node_id": "edge-99",
            "networks": [{"ssid": "OtherNet", "probe": True}],
        })

        dossier = mgr.get_dossier_for_target("ble_112233445566")
        enrichments = dossier.get("enrichments", [])
        wifi_enrichments = [e for e in enrichments if e.get("provider") == "wifi_probe_enrichment"]
        assert len(wifi_enrichments) == 0
        store.close()

    @pytest.mark.unit
    def test_wifi_probe_empty_networks_ignored(self):
        """Empty network list should be ignored."""
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("ble_aabb")
        # Should not raise
        mgr._handle_wifi_presence({"node_id": "edge-01", "networks": []})
        mgr._handle_wifi_presence({"node_id": "", "networks": [{"ssid": "test"}]})
        store.close()

    @pytest.mark.unit
    def test_wifi_probe_uses_ap_ssids_as_fallback(self):
        """When no probe flag, AP SSIDs are used as environmental data."""
        store = _make_store()
        mgr = DossierManager(store=store)

        mgr.find_or_create_for_target(
            "ble_ffeeddccbbaa",
            name="Tablet",
        )
        mgr.add_signal_to_target(
            "ble_ffeeddccbbaa",
            source="ble",
            signal_type="presence",
            data={"node_id": "edge-05"},
        )

        mgr._handle_wifi_presence({
            "node_id": "edge-05",
            "networks": [
                {"ssid": "CoffeeShop-WiFi"},  # No probe flag
                {"ssid": "ATT-Guest"},
            ],
        })

        dossier = mgr.get_dossier_for_target("ble_ffeeddccbbaa")
        enrichments = dossier.get("enrichments", [])
        wifi_enrichments = [e for e in enrichments if e.get("provider") == "wifi_probe_enrichment"]
        assert len(wifi_enrichments) >= 1
        data = wifi_enrichments[0].get("data", {})
        assert "CoffeeShop-WiFi" in data.get("ap_ssids", [])
        store.close()


class TestAutoEnrichOnCorrelation:
    """Auto-enrichment when BLE + camera (or other sources) are correlated."""

    @pytest.mark.unit
    def test_correlation_creates_fusion_enrichment(self):
        """Correlating BLE + camera should add a fusion_profile enrichment."""
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("ble_aabb", name="Phone")
        mgr.find_or_create_for_target("det_person_1", name="Person")

        mgr._handle_correlation({
            "primary_id": "ble_aabb",
            "secondary_id": "det_person_1",
            "confidence": 0.85,
            "reason": "ble+yolo within 3m",
        })

        dossier = mgr.get_dossier_for_target("ble_aabb")
        enrichments = dossier.get("enrichments", [])
        fusion = [e for e in enrichments if e.get("enrichment_type") == "fusion_profile"]
        assert len(fusion) >= 1
        data = fusion[0].get("data", {})
        assert data["fusion_type"] == "ble+camera"
        assert data["source_count"] == 2
        assert data["inferred_entity"] == "person_with_device"
        store.close()

    @pytest.mark.unit
    def test_correlation_same_source_type(self):
        """Correlating two BLE targets should still create enrichment."""
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("ble_1111", name="Phone1")
        mgr.find_or_create_for_target("ble_2222", name="Phone2")

        mgr._handle_correlation({
            "primary_id": "ble_1111",
            "secondary_id": "ble_2222",
            "confidence": 0.6,
        })

        dossier = mgr.get_dossier_for_target("ble_1111")
        enrichments = dossier.get("enrichments", [])
        fusion = [e for e in enrichments if e.get("enrichment_type") == "fusion_profile"]
        assert len(fusion) >= 1
        assert fusion[0]["data"]["fusion_type"] == "ble"
        store.close()


class TestGeofenceEventHandling:
    """Geofence enter/exit events recorded in dossier history."""

    @pytest.mark.unit
    def test_geofence_enter_adds_signal(self):
        """Entering a zone should add a zone_entered signal to the dossier."""
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("ble_abc123", name="Phone")

        mgr._handle_geofence_event("geofence:enter", {
            "target_id": "ble_abc123",
            "zone_id": "zone-1",
            "zone_name": "Parking Lot",
            "zone_type": "monitored",
            "position": [10.0, 20.0],
            "timestamp": 1700000000.0,
        })

        dossier = mgr.get_dossier_for_target("ble_abc123")
        signals = dossier.get("signals", [])
        geo_signals = [s for s in signals if s.get("source") == "geofence"]
        assert len(geo_signals) >= 1
        assert geo_signals[0]["signal_type"] == "zone_entered"
        assert geo_signals[0]["data"]["zone_name"] == "Parking Lot"
        store.close()

    @pytest.mark.unit
    def test_geofence_exit_adds_signal(self):
        """Exiting a zone should add a zone_exited signal."""
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("ble_def456", name="Watch")

        mgr._handle_geofence_event("geofence:exit", {
            "target_id": "ble_def456",
            "zone_id": "zone-2",
            "zone_name": "Lobby",
            "zone_type": "safe",
            "position": [5.0, 15.0],
        })

        dossier = mgr.get_dossier_for_target("ble_def456")
        signals = dossier.get("signals", [])
        geo_signals = [s for s in signals if s.get("source") == "geofence"]
        assert len(geo_signals) >= 1
        assert geo_signals[0]["signal_type"] == "zone_exited"
        store.close()

    @pytest.mark.unit
    def test_geofence_unknown_target_restricted_creates_dossier(self):
        """Unknown target entering restricted zone should create a dossier."""
        store = _make_store()
        mgr = DossierManager(store=store)

        mgr._handle_geofence_event("geofence:enter", {
            "target_id": "ble_unknown1",
            "zone_id": "zone-restricted",
            "zone_name": "Server Room",
            "zone_type": "restricted",
            "position": [0.0, 0.0],
        })

        dossier = mgr.get_dossier_for_target("ble_unknown1")
        assert dossier is not None
        assert "geofence_alert" in dossier.get("tags", [])
        store.close()

    @pytest.mark.unit
    def test_geofence_unknown_target_monitored_creates_dossier(self):
        """Unknown target entering monitored zone should create a dossier (no geofence_alert tag)."""
        store = _make_store()
        mgr = DossierManager(store=store)

        mgr._handle_geofence_event("geofence:enter", {
            "target_id": "ble_nobody",
            "zone_name": "Garden",
            "zone_type": "monitored",
            "position": [1.0, 2.0],
        })

        dossier = mgr.get_dossier_for_target("ble_nobody")
        assert dossier is not None
        # Monitored zones should NOT get the geofence_alert tag (only restricted zones do)
        assert "geofence_alert" not in dossier.get("tags", [])
        # But should have the zone_entered signal
        signals = dossier.get("signals", [])
        assert any(s["signal_type"] == "zone_entered" for s in signals)
        store.close()

    @pytest.mark.unit
    def test_geofence_exit_unknown_target_ignored(self):
        """Unknown target exiting a zone (without prior entry) should NOT create a dossier."""
        store = _make_store()
        mgr = DossierManager(store=store)

        mgr._handle_geofence_event("geofence:exit", {
            "target_id": "ble_ghost",
            "zone_name": "Garden",
            "zone_type": "monitored",
            "position": [1.0, 2.0],
        })

        dossier = mgr.get_dossier_for_target("ble_ghost")
        assert dossier is None
        store.close()


class TestSignalHistory:
    """Signal history timeline API."""

    @pytest.mark.unit
    def test_signal_history_returns_timeline(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("ble_hist1", name="Phone")

        # Add several signals with RSSI
        for i in range(5):
            mgr.add_signal_to_target(
                "ble_hist1", source="ble", signal_type="presence",
                data={"rssi": -60 + i * 2, "mac": "AA:BB:CC:DD:EE:01"},
                confidence=0.7,
            )

        timeline = mgr.get_signal_history(did)
        assert len(timeline) == 5
        # Should be chronological (oldest first)
        for i in range(1, len(timeline)):
            assert timeline[i]["timestamp"] >= timeline[i - 1]["timestamp"]
        # Should have RSSI values
        assert all("rssi" in t for t in timeline)
        store.close()

    @pytest.mark.unit
    def test_signal_history_filter_by_source(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t_filter", name="Target")

        mgr.add_signal_to_target("t_filter", source="ble", signal_type="presence",
                                  data={"rssi": -50})
        mgr.add_signal_to_target("t_filter", source="yolo", signal_type="detection",
                                  data={"class": "person"})

        ble_only = mgr.get_signal_history(did, source="ble")
        assert len(ble_only) == 1
        assert ble_only[0]["source"] == "ble"
        store.close()

    @pytest.mark.unit
    def test_signal_history_nonexistent_dossier(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        result = mgr.get_signal_history("fake_id")
        assert result == []
        store.close()


class TestLocationSummary:
    """Location history summary."""

    @pytest.mark.unit
    def test_location_summary_with_positions(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t_loc", name="Mover")

        # Add positioned signals
        store.add_signal(did, "ble", "presence", {"rssi": -50},
                         position_x=0.0, position_y=0.0)
        store.add_signal(did, "ble", "presence", {"rssi": -55},
                         position_x=3.0, position_y=4.0)

        summary = mgr.get_location_summary(did)
        assert summary["position_count"] == 2
        assert summary["total_distance"] == 5.0  # 3-4-5 triangle
        assert len(summary["positions"]) == 2
        store.close()

    @pytest.mark.unit
    def test_location_summary_nonexistent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        summary = mgr.get_location_summary("fake")
        assert summary["position_count"] == 0
        assert summary["total_distance"] == 0.0
        store.close()


class TestBehavioralProfile:
    """Behavioral profile analysis."""

    @pytest.mark.unit
    def test_stationary_profile(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t_stat", name="Static")

        # Add signals all at same position
        now = time.time()
        for i in range(5):
            store.add_signal(did, "ble", "presence", {"rssi": -50},
                             position_x=1.0, position_y=1.0,
                             timestamp=now + i * 10)

        profile = mgr.get_behavioral_profile(did)
        assert profile["movement_pattern"] == "stationary"
        assert profile["average_speed"] == 0.0
        assert profile["signal_count"] == 5
        assert "ble" in profile["source_breakdown"]
        store.close()

    @pytest.mark.unit
    def test_mobile_profile(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t_mobile", name="Walker")

        now = time.time()
        # Move in a straight line
        for i in range(5):
            store.add_signal(did, "ble", "presence", {"rssi": -60},
                             position_x=float(i * 10), position_y=0.0,
                             timestamp=now + i * 5)

        profile = mgr.get_behavioral_profile(did)
        assert profile["movement_pattern"] == "mobile"
        assert profile["average_speed"] > 0
        assert profile["signal_count"] == 5
        store.close()

    @pytest.mark.unit
    def test_rssi_stats(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t_rssi", name="Device")

        now = time.time()
        rssi_values = [-80, -70, -60, -50, -40]
        for i, rssi in enumerate(rssi_values):
            store.add_signal(did, "ble", "presence", {"rssi": rssi},
                             timestamp=now + i * 10)

        profile = mgr.get_behavioral_profile(did)
        assert profile["rssi_stats"]["min"] == -80
        assert profile["rssi_stats"]["max"] == -40
        assert profile["rssi_stats"]["trend"] == "approaching"
        store.close()

    @pytest.mark.unit
    def test_rssi_receding_trend(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t_recede", name="Leaving")

        now = time.time()
        rssi_values = [-40, -50, -60, -70, -80]
        for i, rssi in enumerate(rssi_values):
            store.add_signal(did, "ble", "presence", {"rssi": rssi},
                             timestamp=now + i * 10)

        profile = mgr.get_behavioral_profile(did)
        assert profile["rssi_stats"]["trend"] == "receding"
        store.close()

    @pytest.mark.unit
    def test_behavioral_profile_nonexistent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        profile = mgr.get_behavioral_profile("nonexistent")
        assert profile["movement_pattern"] == "unknown"
        assert profile["signal_count"] == 0
        store.close()

    @pytest.mark.unit
    def test_source_breakdown(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t_multi", name="Multi")

        store.add_signal(did, "ble", "presence", {"rssi": -50})
        store.add_signal(did, "ble", "presence", {"rssi": -55})
        store.add_signal(did, "yolo", "detection", {"class": "person"})

        profile = mgr.get_behavioral_profile(did)
        assert profile["source_breakdown"]["ble"] == 2
        assert profile["source_breakdown"]["yolo"] == 1
        store.close()
