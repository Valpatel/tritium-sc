# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for fleet proxy router — /api/fleet/*.

Verifies each endpoint returns correct responses in three scenarios:
  1. Fleet server is reachable (live proxy)
  2. Fleet server unreachable, bridge has cached data
  3. Fleet server unreachable, no bridge (unavailable fallback)
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_request(bridge=None) -> MagicMock:
    """Create a mock Request with optional fleet_bridge on app.state."""
    request = MagicMock()
    if bridge is not None:
        request.app.state.fleet_bridge = bridge
    else:
        request.app.state = MagicMock(spec=[])
    return request


def _make_bridge(**kwargs) -> MagicMock:
    """Create a mock FleetBridge with configurable cached data."""
    bridge = MagicMock()
    bridge.rest_url = "http://fleet:8080"
    bridge.devices = kwargs.get("devices", {})
    bridge.ble_presence = kwargs.get("ble_presence", [])
    bridge.config_sync = kwargs.get("config_sync", {})
    bridge.dashboard = kwargs.get("dashboard", {})
    bridge.health_report = kwargs.get("health_report", {})
    bridge.correlations = kwargs.get("correlations", {})
    bridge.topology = kwargs.get("topology", {})
    bridge.heap_trends = kwargs.get("heap_trends", {})
    bridge.node_diag = kwargs.get("node_diag", {})
    return bridge


# ---------------------------------------------------------------------------
# /api/fleet/nodes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetNodesEndpoint:
    """GET /api/fleet/nodes."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_nodes
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        live_data = {"devices": [{"device_id": "d1", "name": "Node-1"}]}
        with patch("app.routers.fleet._proxy_get", return_value=live_data):
            result = _run(fleet_nodes(request))
        assert result["source"] == "live"
        assert result["count"] == 1
        assert result["nodes"][0]["device_id"] == "d1"

    def test_fallback_to_bridge_cache(self):
        from app.routers.fleet import fleet_nodes
        bridge = _make_bridge(devices={"d1": {"device_id": "d1", "name": "Cached"}})
        request = _make_request(bridge=bridge)
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_nodes(request))
        assert result["source"] == "cached"
        assert result["count"] == 1

    def test_unavailable(self):
        from app.routers.fleet import fleet_nodes
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_nodes(request))
        assert result["source"] == "unavailable"
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# /api/fleet/presence
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetPresenceEndpoint:
    """GET /api/fleet/presence."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_presence
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        live_data = {"devices": [{"mac": "AA:BB:CC", "rssi": -50}]}
        with patch("app.routers.fleet._proxy_get", return_value=live_data):
            result = _run(fleet_presence(request))
        assert result["source"] == "live"
        assert result["count"] == 1

    def test_fallback_cached(self):
        from app.routers.fleet import fleet_presence
        bridge = _make_bridge(ble_presence=[{"mac": "AA:BB:CC"}])
        request = _make_request(bridge=bridge)
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_presence(request))
        assert result["source"] == "cached"
        assert result["count"] == 1

    def test_unavailable(self):
        from app.routers.fleet import fleet_presence
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_presence(request))
        assert result["source"] == "unavailable"
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# /api/fleet/config
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetConfigEndpoint:
    """GET /api/fleet/config."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_config
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        live_data = {"config_version": "v2", "nodes_synced": 3, "nodes_total": 5}
        with patch("app.routers.fleet._proxy_get", return_value=live_data):
            result = _run(fleet_config(request))
        assert result["source"] == "live"
        assert result["config_version"] == "v2"

    def test_fallback_cached(self):
        from app.routers.fleet import fleet_config
        bridge = _make_bridge(config_sync={"config_version": "v1", "nodes_synced": 2})
        request = _make_request(bridge=bridge)
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_config(request))
        assert result["source"] == "cached"
        assert result["config_version"] == "v1"

    def test_unavailable(self):
        from app.routers.fleet import fleet_config
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_config(request))
        assert result["source"] == "unavailable"
        assert result["config_version"] == "unknown"


# ---------------------------------------------------------------------------
# /api/fleet/dashboard
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetDashboardEndpoint:
    """GET /api/fleet/dashboard."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_dashboard
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        live_data = {"health": {"score": 95}, "alerts": {"critical": 0}}
        with patch("app.routers.fleet._proxy_get", return_value=live_data):
            result = _run(fleet_dashboard(request))
        assert result["source"] == "live"
        assert result["health"]["score"] == 95

    def test_fallback_cached(self):
        from app.routers.fleet import fleet_dashboard
        bridge = _make_bridge(dashboard={"health": {"score": 80}})
        request = _make_request(bridge=bridge)
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_dashboard(request))
        assert result["source"] == "cached"

    def test_unavailable(self):
        from app.routers.fleet import fleet_dashboard
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_dashboard(request))
        assert result["source"] == "unavailable"
        assert result["health"]["score"] == 0


# ---------------------------------------------------------------------------
# /api/fleet/health-report
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetHealthReportEndpoint:
    """GET /api/fleet/health-report."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_health_report
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        live_data = {"total_nodes": 5, "healthy": 4, "warning": 1}
        with patch("app.routers.fleet._proxy_get", return_value=live_data):
            result = _run(fleet_health_report(request))
        assert result["source"] == "live"
        assert result["total_nodes"] == 5

    def test_fallback_cached(self):
        from app.routers.fleet import fleet_health_report
        bridge = _make_bridge(health_report={"total_nodes": 3, "healthy": 3})
        request = _make_request(bridge=bridge)
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_health_report(request))
        assert result["source"] == "cached"

    def test_unavailable(self):
        from app.routers.fleet import fleet_health_report
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_health_report(request))
        assert result["source"] == "unavailable"
        assert result["total_nodes"] == 0


# ---------------------------------------------------------------------------
# /api/fleet/correlations
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetCorrelationsEndpoint:
    """GET /api/fleet/correlations."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_correlations
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        live_data = {"correlations": [{"type": "sync_reboot"}], "count": 1}
        with patch("app.routers.fleet._proxy_get", return_value=live_data):
            result = _run(fleet_correlations(request))
        assert result["source"] == "live"
        assert len(result["correlations"]) == 1

    def test_unavailable(self):
        from app.routers.fleet import fleet_correlations
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_correlations(request))
        assert result["source"] == "unavailable"
        assert result["correlations"] == []


# ---------------------------------------------------------------------------
# /api/fleet/topology
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetTopologyEndpoint:
    """GET /api/fleet/topology."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_topology
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        live_data = {"nodes": [{"id": "n1"}], "edges": []}
        with patch("app.routers.fleet._proxy_get", return_value=live_data):
            result = _run(fleet_topology(request))
        assert result["source"] == "live"
        assert len(result["nodes"]) == 1

    def test_unavailable(self):
        from app.routers.fleet import fleet_topology
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_topology(request))
        assert result["source"] == "unavailable"
        assert result["nodes"] == []


# ---------------------------------------------------------------------------
# /api/fleet/heap-trends
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetHeapTrendsEndpoint:
    """GET /api/fleet/heap-trends."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_heap_trends
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        live_data = {"trends": [{"node": "n1", "direction": "rising"}]}
        with patch("app.routers.fleet._proxy_get", return_value=live_data):
            result = _run(fleet_heap_trends(request))
        assert result["source"] == "live"
        assert len(result["trends"]) == 1

    def test_unavailable(self):
        from app.routers.fleet import fleet_heap_trends
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_heap_trends(request))
        assert result["source"] == "unavailable"
        assert result["trends"] == []


# ---------------------------------------------------------------------------
# /api/fleet/node/{device_id}
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetNodeDetailEndpoint:
    """GET /api/fleet/node/{device_id}."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_node_detail
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        devices_data = {"devices": [{"device_id": "d1", "name": "Node-1"}]}
        sensors_data = {"temperature": 22.5, "humidity": 45}
        with patch("app.routers.fleet._proxy_get", side_effect=[devices_data, sensors_data]):
            result = _run(fleet_node_detail(request, "d1"))
        assert result["device_id"] == "d1"
        assert result["sensors_detail"]["temperature"] == 22.5

    def test_fallback_to_bridge(self):
        from app.routers.fleet import fleet_node_detail
        bridge = _make_bridge(devices={"d1": {"device_id": "d1", "name": "Cached-Node"}})
        request = _make_request(bridge=bridge)
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_node_detail(request, "d1"))
        assert result["device_id"] == "d1"
        assert result["name"] == "Cached-Node"

    def test_not_found(self):
        from app.routers.fleet import fleet_node_detail
        from fastapi import HTTPException
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                _run(fleet_node_detail(request, "unknown"))
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# /api/fleet/node/{device_id}/diag
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFleetNodeDiagEndpoint:
    """GET /api/fleet/node/{device_id}/diag."""

    def test_live_proxy(self):
        from app.routers.fleet import fleet_node_diag
        bridge = _make_bridge()
        request = _make_request(bridge=bridge)
        live_data = {"health": {"uptime_s": 3600}, "i2c_slaves": [{"addr": "0x3B"}]}
        with patch("app.routers.fleet._proxy_get", return_value=live_data):
            result = _run(fleet_node_diag(request, "d1"))
        assert result["source"] == "live"
        assert result["device_id"] == "d1"
        assert result["health"]["uptime_s"] == 3600

    def test_fallback_cached(self):
        from app.routers.fleet import fleet_node_diag
        bridge = _make_bridge(node_diag={"d1": {"health": {"uptime_s": 1000}}})
        request = _make_request(bridge=bridge)
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_node_diag(request, "d1"))
        assert result["source"] == "cached"
        assert result["device_id"] == "d1"

    def test_unavailable(self):
        from app.routers.fleet import fleet_node_diag
        request = _make_request()
        with patch("app.routers.fleet._proxy_get", return_value=None):
            result = _run(fleet_node_diag(request, "d1"))
        assert result["source"] == "unavailable"
        assert result["device_id"] == "d1"
        assert result["health"] == {}
