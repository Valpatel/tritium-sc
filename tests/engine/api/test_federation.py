# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Federation plugin."""

import json
import os
import tempfile
import pytest

from tritium_lib.models.federation import (
    ConnectionState,
    FederatedSite,
    FederationMessage,
    FederationMessageType,
    SharedTarget,
    SharePolicy,
    SiteConnection,
    SiteRole,
)


class MockEventBus:
    """Minimal EventBus mock for testing."""
    def __init__(self):
        self.published = []

    def publish(self, event_type: str, data: dict = None):
        self.published.append({"type": event_type, "data": data or {}})

    def subscribe(self):
        import queue
        return queue.Queue()

    def unsubscribe(self, q):
        pass


class MockTracker:
    """Minimal TargetTracker mock."""
    def __init__(self):
        self.updates = []

    def update_from_federation(self, data: dict):
        self.updates.append(data)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def plugin(temp_dir):
    """Create a FederationPlugin with mocked dependencies."""
    # Import here so sys.path is set up
    import sys
    plugins_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins")
    plugins_dir = os.path.abspath(plugins_dir)
    if plugins_dir not in sys.path:
        sys.path.insert(0, plugins_dir)

    from federation.plugin import FederationPlugin

    p = FederationPlugin()
    p._event_bus = MockEventBus()
    p._tracker = MockTracker()
    p._logger = __import__("logging").getLogger("test-federation")
    p._sites_file = os.path.join(temp_dir, "federation_sites.json")
    p._running = True
    return p


class TestFederationPlugin:
    """Tests for FederationPlugin core functionality."""

    def test_plugin_identity(self, plugin):
        assert plugin.plugin_id == "tritium.federation"
        assert plugin.name == "Federation"
        assert plugin.version == "2.0.0"
        assert "bridge" in plugin.capabilities

    def test_add_site(self, plugin):
        site = FederatedSite(
            name="Alpha HQ",
            mqtt_host="10.0.0.1",
            role=SiteRole.PEER,
        )
        site_id = plugin.add_site(site)
        assert site_id == site.site_id
        assert plugin.get_site(site_id) is not None
        assert plugin.get_site(site_id).name == "Alpha HQ"

    def test_remove_site(self, plugin):
        site = FederatedSite(name="To Remove")
        plugin.add_site(site)
        assert plugin.remove_site(site.site_id) is True
        assert plugin.get_site(site.site_id) is None

    def test_remove_nonexistent(self, plugin):
        assert plugin.remove_site("nonexistent") is False

    def test_list_sites(self, plugin):
        site1 = FederatedSite(name="Site A")
        site2 = FederatedSite(name="Site B")
        plugin.add_site(site1)
        plugin.add_site(site2)
        sites = plugin.list_sites()
        assert len(sites) == 2
        names = {s["name"] for s in sites}
        assert "Site A" in names
        assert "Site B" in names

    def test_list_sites_includes_connection(self, plugin):
        site = FederatedSite(name="With Conn")
        plugin.add_site(site)
        sites = plugin.list_sites()
        assert len(sites) == 1
        assert "connection" in sites[0]

    def test_share_target(self, plugin):
        target = SharedTarget(
            target_id="ble_aabbccddeeff",
            source_site_id="site-alpha",
            name="Test Device",
        )
        plugin.share_target(target)
        shared = plugin.get_shared_targets()
        assert len(shared) == 1
        assert shared[0]["target_id"] == "ble_aabbccddeeff"

    def test_receive_target(self, plugin):
        target = SharedTarget(
            target_id="det_person_1",
            source_site_id="site-bravo",
            name="Remote Person",
            lat=37.7,
            lng=-121.9,
        )
        plugin.receive_target(target)
        shared = plugin.get_shared_targets()
        assert len(shared) == 1
        # Check tracker was updated
        assert len(plugin._tracker.updates) == 1
        assert plugin._tracker.updates[0]["target_id"] == "det_person_1"

    def test_get_stats(self, plugin):
        site = FederatedSite(name="Stats Site", enabled=True)
        plugin.add_site(site)
        stats = plugin.get_stats()
        assert stats["total_sites"] == 1
        assert stats["enabled_sites"] == 1
        assert stats["connected_sites"] == 0
        assert stats["shared_targets"] == 0

    def test_get_connection(self, plugin):
        site = FederatedSite(name="Conn Site")
        plugin.add_site(site)
        conn = plugin.get_connection(site.site_id)
        assert conn is not None
        assert conn.state == ConnectionState.DISCONNECTED

    def test_events_published_on_add(self, plugin):
        site = FederatedSite(name="Event Site")
        plugin.add_site(site)
        events = [e for e in plugin._event_bus.published if e["type"] == "federation:site_added"]
        assert len(events) == 1
        assert events[0]["data"]["name"] == "Event Site"

    def test_events_published_on_share(self, plugin):
        target = SharedTarget(
            target_id="ble_test",
            source_site_id="site-1",
        )
        plugin.share_target(target)
        events = [e for e in plugin._event_bus.published if e["type"] == "federation:target_shared"]
        assert len(events) == 1

    def test_events_published_on_receive(self, plugin):
        target = SharedTarget(
            target_id="ble_recv",
            source_site_id="site-2",
        )
        plugin.receive_target(target)
        events = [e for e in plugin._event_bus.published if e["type"] == "federation:target_received"]
        assert len(events) == 1


class TestFederationPersistence:
    """Tests for site persistence."""

    def test_save_and_load(self, temp_dir):
        import sys
        plugins_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins")
        plugins_dir = os.path.abspath(plugins_dir)
        if plugins_dir not in sys.path:
            sys.path.insert(0, plugins_dir)

        from federation.plugin import FederationPlugin

        # Create plugin and add a site
        p1 = FederationPlugin()
        p1._logger = __import__("logging").getLogger("test")
        p1._sites_file = os.path.join(temp_dir, "sites.json")
        p1._running = True

        site = FederatedSite(name="Persistent Site", mqtt_host="10.0.0.5")
        p1.add_site(site)

        # Create new plugin and load
        p2 = FederationPlugin()
        p2._logger = __import__("logging").getLogger("test")
        p2._sites_file = os.path.join(temp_dir, "sites.json")
        p2._load_sites()

        assert len(p2._sites) == 1
        loaded = list(p2._sites.values())[0]
        assert loaded.name == "Persistent Site"
        assert loaded.mqtt_host == "10.0.0.5"

    def test_load_empty_file(self, temp_dir):
        import sys
        plugins_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins")
        plugins_dir = os.path.abspath(plugins_dir)
        if plugins_dir not in sys.path:
            sys.path.insert(0, plugins_dir)

        from federation.plugin import FederationPlugin

        p = FederationPlugin()
        p._logger = __import__("logging").getLogger("test")
        p._sites_file = os.path.join(temp_dir, "nonexistent.json")
        p._load_sites()
        assert len(p._sites) == 0


class TestFederationLifecycle:
    """Tests for start/stop lifecycle."""

    def test_start_stop(self, plugin):
        # plugin._running is already True from fixture, reset it
        plugin._running = False
        plugin.start()
        assert plugin._running is True
        assert plugin.healthy is True
        plugin.stop()
        assert plugin._running is False

    def test_double_start(self, plugin):
        plugin._running = False
        plugin.start()
        plugin.start()  # Should not raise
        assert plugin._running is True
        plugin.stop()


class TestTargetDeduplication:
    """Tests for cross-site target deduplication."""

    def test_canonical_key_from_mac_identifier(self, plugin):
        target = {"target_id": "t1", "identifiers": {"mac": "AA:BB:CC:DD:EE:FF"}}
        key = plugin._canonical_key(target)
        assert key == "mac:aa:bb:cc:dd:ee:ff"

    def test_canonical_key_from_ble_target_id(self, plugin):
        target = {"target_id": "ble_aabbccddeeff", "identifiers": {}}
        key = plugin._canonical_key(target)
        assert key == "mac:aabbccddeeff"

    def test_canonical_key_from_wifi_target_id(self, plugin):
        target = {"target_id": "wifi_001122334455", "identifiers": {}}
        key = plugin._canonical_key(target)
        assert key == "bssid:001122334455"

    def test_canonical_key_from_name(self, plugin):
        target = {"target_id": "det_person_1", "name": "John Doe", "entity_type": "person"}
        key = plugin._canonical_key(target)
        assert key == "name:person:john doe"

    def test_canonical_key_fallback_to_id(self, plugin):
        target = {"target_id": "random_123", "name": "", "entity_type": "unknown"}
        key = plugin._canonical_key(target)
        assert key == "id:random_123"

    def test_deduplicate_new_target(self, plugin):
        result = plugin.deduplicate_target({
            "target_id": "ble_aabb",
            "identifiers": {"mac": "AA:BB"},
        })
        assert result["is_duplicate"] is False
        assert result["merged_target_id"] == "ble_aabb"

    def test_deduplicate_same_mac_different_id(self, plugin):
        # First target
        plugin.deduplicate_target({
            "target_id": "ble_aabb_site1",
            "identifiers": {"mac": "AA:BB"},
        })
        # Same MAC from different site
        result = plugin.deduplicate_target({
            "target_id": "ble_aabb_site2",
            "identifiers": {"mac": "AA:BB"},
        })
        assert result["is_duplicate"] is True
        assert result["merged_target_id"] == "ble_aabb_site1"
        assert len(result["existing_ids"]) == 2

    def test_deduplicate_same_target_twice_not_duplicate(self, plugin):
        plugin.deduplicate_target({"target_id": "t1", "identifiers": {"mac": "X"}})
        result = plugin.deduplicate_target({"target_id": "t1", "identifiers": {"mac": "X"}})
        assert result["is_duplicate"] is False

    def test_dedup_stats(self, plugin):
        plugin.deduplicate_target({"target_id": "t1", "identifiers": {"mac": "AA"}})
        plugin.deduplicate_target({"target_id": "t2", "identifiers": {"mac": "AA"}})
        plugin.deduplicate_target({"target_id": "t3", "identifiers": {"mac": "BB"}})
        stats = plugin.get_dedup_stats()
        assert stats["unique_entities"] == 2
        assert stats["total_target_ids"] == 3
        assert stats["duplicated_entities"] == 1
        assert stats["dedup_savings"] == 1

    def test_dedup_event_published(self, plugin):
        plugin.deduplicate_target({"target_id": "t1", "identifiers": {"mac": "CC"}})
        plugin.deduplicate_target({"target_id": "t2", "identifiers": {"mac": "CC"}})
        events = [e for e in plugin._event_bus.published if e["type"] == "federation:target_deduplicated"]
        assert len(events) == 1
        assert events[0]["data"]["merged_into"] == "t1"


class TestSharedThreatAssessments:
    """Tests for cross-site threat score sharing."""

    def test_create_assessment(self, plugin):
        result = plugin.share_threat_assessment(
            target_id="ble_bad_device",
            threat_score=0.8,
            threat_level="high",
            reasons=["known_bad_mac"],
            assessor="operator",
        )
        assert result["target_id"] == "ble_bad_device"
        assert result["threat_score"] == 0.8
        assert result["consensus_score"] == 0.8
        assert "known_bad_mac" in result["reasons"]

    def test_multi_site_consensus(self, plugin):
        # Site 1 says 0.8
        plugin.share_threat_assessment(
            target_id="t1",
            threat_score=0.8,
            threat_level="high",
            source_site_id="site-alpha",
        )
        # Site 2 says 0.4
        result = plugin.share_threat_assessment(
            target_id="t1",
            threat_score=0.4,
            threat_level="medium",
            source_site_id="site-bravo",
        )
        # Consensus should be average
        assert result["consensus_score"] == pytest.approx(0.6, abs=0.01)
        assert len(result["site_scores"]) == 2

    def test_reasons_merge(self, plugin):
        plugin.share_threat_assessment(
            target_id="t1", threat_score=0.5,
            reasons=["reason_a", "reason_b"],
            source_site_id="s1",
        )
        result = plugin.share_threat_assessment(
            target_id="t1", threat_score=0.7,
            reasons=["reason_b", "reason_c"],
            source_site_id="s2",
        )
        assert "reason_a" in result["reasons"]
        assert "reason_b" in result["reasons"]
        assert "reason_c" in result["reasons"]

    def test_list_assessments_filtered(self, plugin):
        plugin.share_threat_assessment(target_id="low", threat_score=0.2, source_site_id="s1")
        plugin.share_threat_assessment(target_id="high", threat_score=0.9, source_site_id="s1")
        results = plugin.list_threat_assessments(min_score=0.5)
        assert len(results) == 1
        assert results[0]["target_id"] == "high"

    def test_get_assessment(self, plugin):
        plugin.share_threat_assessment(target_id="t1", threat_score=0.5, source_site_id="s1")
        a = plugin.get_threat_assessment("t1")
        assert a is not None
        assert a["target_id"] == "t1"

    def test_get_assessment_not_found(self, plugin):
        assert plugin.get_threat_assessment("nonexistent") is None

    def test_clear_assessment(self, plugin):
        plugin.share_threat_assessment(target_id="t1", threat_score=0.5, source_site_id="s1")
        assert plugin.clear_threat_assessment("t1") is True
        assert plugin.get_threat_assessment("t1") is None

    def test_clear_nonexistent(self, plugin):
        assert plugin.clear_threat_assessment("nonexistent") is False

    def test_threat_score_clamping(self, plugin):
        result = plugin.share_threat_assessment(
            target_id="t1", threat_score=1.5, source_site_id="s1",
        )
        assert result["threat_score"] == 1.0
        result2 = plugin.share_threat_assessment(
            target_id="t2", threat_score=-0.5, source_site_id="s1",
        )
        assert result2["threat_score"] == 0.0

    def test_threat_event_published(self, plugin):
        plugin.share_threat_assessment(target_id="t1", threat_score=0.7, source_site_id="s1")
        events = [e for e in plugin._event_bus.published if e["type"] == "federation:threat_assessment"]
        assert len(events) == 1


class TestSiteHealthMonitoring:
    """Tests for ping/latency health monitoring between sites."""

    def test_record_successful_ping(self, plugin):
        result = plugin.record_health_ping("site-alpha", latency_ms=42.5, success=True)
        assert result["site_id"] == "site-alpha"
        assert result["total_pings"] == 1
        assert result["successful_pings"] == 1
        assert result["avg_latency_ms"] == pytest.approx(42.5)
        assert result["status"] == "healthy"

    def test_record_failed_ping(self, plugin):
        result = plugin.record_health_ping("site-alpha", latency_ms=0, success=False, error="timeout")
        assert result["failed_pings"] == 1
        assert result["last_error"] == "timeout"
        assert result["status"] == "down"

    def test_multiple_pings_averaging(self, plugin):
        plugin.record_health_ping("s1", latency_ms=10.0)
        plugin.record_health_ping("s1", latency_ms=20.0)
        result = plugin.record_health_ping("s1", latency_ms=30.0)
        assert result["avg_latency_ms"] == pytest.approx(20.0)
        assert result["min_latency_ms"] == pytest.approx(10.0)
        assert result["max_latency_ms"] == pytest.approx(30.0)
        assert result["total_pings"] == 3

    def test_degraded_status(self, plugin):
        # 3 successes, 2 failures within last 5
        plugin.record_health_ping("s1", latency_ms=10.0, success=True)
        plugin.record_health_ping("s1", latency_ms=10.0, success=True)
        plugin.record_health_ping("s1", latency_ms=10.0, success=True)
        plugin.record_health_ping("s1", latency_ms=0, success=False)
        result = plugin.record_health_ping("s1", latency_ms=0, success=False)
        assert result["status"] == "degraded"

    def test_uptime_percentage(self, plugin):
        plugin.record_health_ping("s1", latency_ms=10.0, success=True)
        plugin.record_health_ping("s1", latency_ms=10.0, success=True)
        plugin.record_health_ping("s1", latency_ms=0, success=False)
        result = plugin.record_health_ping("s1", latency_ms=10.0, success=True)
        # 3 out of 4 successful
        assert result["uptime_pct"] == pytest.approx(75.0)

    def test_get_health_metrics(self, plugin):
        plugin.record_health_ping("s1", latency_ms=15.0)
        metrics = plugin.get_health_metrics("s1")
        assert metrics is not None
        assert metrics["site_id"] == "s1"

    def test_get_health_metrics_not_found(self, plugin):
        assert plugin.get_health_metrics("nonexistent") is None

    def test_get_all_health_metrics(self, plugin):
        plugin.record_health_ping("s1", latency_ms=10.0)
        plugin.record_health_ping("s2", latency_ms=20.0)
        all_metrics = plugin.get_all_health_metrics()
        assert len(all_metrics) == 2

    def test_health_summary(self, plugin):
        plugin.record_health_ping("s1", latency_ms=10.0, success=True)
        plugin.record_health_ping("s2", latency_ms=0, success=False)
        summary = plugin.get_health_summary()
        assert summary["total_monitored"] == 2
        assert summary["healthy"] == 1
        assert summary["down"] == 1

    def test_connection_latency_updated(self, plugin):
        from tritium_lib.models.federation import FederatedSite
        site = FederatedSite(name="Latency Test")
        plugin.add_site(site)
        plugin.record_health_ping(site.site_id, latency_ms=55.0, success=True)
        conn = plugin.get_connection(site.site_id)
        assert conn.latency_ms == pytest.approx(55.0)

    def test_rolling_window_limit(self, plugin):
        # Record 110 pings, history should keep only last 100
        for i in range(110):
            plugin.record_health_ping("s1", latency_ms=float(i))
        with plugin._lock:
            assert len(plugin._health_metrics["s1"]["ping_history"]) == 100


class TestEnhancedStats:
    """Tests for the enhanced get_stats with dedup and health info."""

    def test_stats_includes_dedup(self, plugin):
        plugin.deduplicate_target({"target_id": "t1", "identifiers": {"mac": "AA"}})
        plugin.deduplicate_target({"target_id": "t2", "identifiers": {"mac": "AA"}})
        stats = plugin.get_stats()
        assert "dedup" in stats
        assert stats["dedup"]["duplicated_entities"] == 1

    def test_stats_includes_threats(self, plugin):
        plugin.share_threat_assessment(target_id="t1", threat_score=0.9, source_site_id="s1")
        stats = plugin.get_stats()
        assert stats["threat_assessments"] == 1
        assert stats["high_threats"] == 1

    def test_stats_includes_health(self, plugin):
        plugin.record_health_ping("s1", latency_ms=10.0, success=True)
        stats = plugin.get_stats()
        assert "health" in stats
        assert stats["health"]["healthy"] == 1


class TestReceiveTargetDedup:
    """Tests for receive_target_dedup which combines receiving and dedup."""

    def test_receive_new_target(self, plugin):
        from tritium_lib.models.federation import SharedTarget
        target = SharedTarget(
            target_id="ble_aabb",
            source_site_id="remote",
            name="Device",
            identifiers={"mac": "AA:BB"},
        )
        result = plugin.receive_target_dedup(target)
        assert result["is_duplicate"] is False
        assert len(plugin._tracker.updates) == 1

    def test_receive_duplicate_target(self, plugin):
        from tritium_lib.models.federation import SharedTarget
        # Register the first one
        plugin.deduplicate_target({"target_id": "ble_local", "identifiers": {"mac": "AA:BB"}})
        # Receive from remote with same MAC
        target = SharedTarget(
            target_id="ble_remote",
            source_site_id="remote",
            identifiers={"mac": "AA:BB"},
        )
        result = plugin.receive_target_dedup(target)
        assert result["is_duplicate"] is True
        assert result["merged_target_id"] == "ble_local"
        # Tracker should use the merged ID
        assert plugin._tracker.updates[0]["target_id"] == "ble_local"
