# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the telemetry router -- InfluxDB proxy endpoints.

Tests all five endpoints (/health, /robot/{id}, /detections, /system,
/summary) with mocked InfluxDB client.  Also tests disabled/missing-library
fallback paths.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.telemetry import router, _query


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Helper — reset the module-level _client singleton between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_client():
    """Clear the cached InfluxDB client between every test."""
    import app.routers.telemetry as mod
    mod._client = None
    yield
    mod._client = None


# ---------------------------------------------------------------------------
# _get_client — lazy client creation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetClient:
    """Lazy InfluxDB client creation and fallback paths."""

    def test_returns_none_when_disabled(self):
        with patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_enabled = False
            from app.routers.telemetry import _get_client
            assert _get_client() is None

    def test_returns_none_when_library_missing(self):
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "influxdb_client":
                raise ImportError("No module named 'influxdb_client'")
            return real_import(name, *args, **kwargs)

        with patch("app.routers.telemetry.settings") as mock_settings, \
             patch("builtins.__import__", side_effect=mock_import):
            mock_settings.influx_enabled = True
            from app.routers.telemetry import _get_client
            assert _get_client() is None

    def test_returns_client_when_available(self):
        mock_influx_client = MagicMock()
        mock_class = MagicMock(return_value=mock_influx_client)

        with patch("app.routers.telemetry.settings") as mock_settings, \
             patch.dict("sys.modules", {"influxdb_client": MagicMock(InfluxDBClient=mock_class)}):
            mock_settings.influx_enabled = True
            mock_settings.influx_url = "http://localhost:8086"
            mock_settings.influx_token = "test-token"
            mock_settings.influx_org = "test-org"
            from app.routers.telemetry import _get_client
            client = _get_client()
            assert client is mock_influx_client

    def test_caches_client_on_second_call(self):
        """Once created, the singleton is reused."""
        import app.routers.telemetry as mod
        sentinel = MagicMock()
        mod._client = sentinel
        from app.routers.telemetry import _get_client
        assert _get_client() is sentinel

    def test_returns_none_on_init_exception(self):
        mock_class = MagicMock(side_effect=RuntimeError("connection refused"))

        with patch("app.routers.telemetry.settings") as mock_settings, \
             patch.dict("sys.modules", {"influxdb_client": MagicMock(InfluxDBClient=mock_class)}):
            mock_settings.influx_enabled = True
            mock_settings.influx_url = "http://localhost:8086"
            mock_settings.influx_token = "test-token"
            mock_settings.influx_org = "test-org"
            from app.routers.telemetry import _get_client
            assert _get_client() is None


# ---------------------------------------------------------------------------
# _query — execute Flux query
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestQueryHelper:
    """Low-level _query function."""

    def test_returns_empty_when_client_none(self):
        with patch("app.routers.telemetry._get_client", return_value=None):
            assert _query("from(bucket: \"x\")") == []

    def test_returns_rows_from_influx(self):
        record1 = MagicMock()
        record1.values = {"_time": "2026-01-01T00:00:00Z", "_value": 42}
        record2 = MagicMock()
        record2.values = {"_time": "2026-01-01T01:00:00Z", "_value": 99}
        table = MagicMock()
        table.records = [record1, record2]

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = [table]

        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api

        with patch("app.routers.telemetry._get_client", return_value=mock_client), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_org = "test-org"
            result = _query("from(bucket: \"x\")")
            assert len(result) == 2
            assert result[0]["_value"] == 42
            assert result[1]["_value"] == 99

    def test_returns_empty_on_query_exception(self):
        mock_query_api = MagicMock()
        mock_query_api.query.side_effect = RuntimeError("query failed")

        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api

        with patch("app.routers.telemetry._get_client", return_value=mock_client), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_org = "test-org"
            assert _query("bad query") == []

    def test_multiple_tables(self):
        rec_a = MagicMock()
        rec_a.values = {"_field": "battery", "_value": 80}
        rec_b = MagicMock()
        rec_b.values = {"_field": "speed", "_value": 2.5}
        table_a = MagicMock()
        table_a.records = [rec_a]
        table_b = MagicMock()
        table_b.records = [rec_b]

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = [table_a, table_b]
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api

        with patch("app.routers.telemetry._get_client", return_value=mock_client), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_org = "test-org"
            result = _query("from(bucket: \"x\")")
            assert len(result) == 2
            assert result[0]["_field"] == "battery"
            assert result[1]["_field"] == "speed"


# ---------------------------------------------------------------------------
# GET /api/telemetry/health
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHealthEndpoint:
    """GET /api/telemetry/health — InfluxDB connection status."""

    def test_disabled(self):
        with patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_enabled = False
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "disabled"

    def test_client_unavailable(self):
        with patch("app.routers.telemetry.settings") as mock_settings, \
             patch("app.routers.telemetry._get_client", return_value=None):
            mock_settings.influx_enabled = True
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "error"
            assert "not available" in data["message"]

    def test_healthy(self):
        mock_health = MagicMock()
        mock_health.status = "pass"
        mock_health.message = "ready for queries"

        mock_influx = MagicMock()
        mock_influx.health.return_value = mock_health

        with patch("app.routers.telemetry.settings") as mock_settings, \
             patch("app.routers.telemetry._get_client", return_value=mock_influx):
            mock_settings.influx_enabled = True
            mock_settings.influx_url = "http://localhost:8086"
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "pass"
            assert data["message"] == "ready for queries"
            assert data["influx_url"] == "http://localhost:8086"
            assert data["bucket"] == "telemetry"

    def test_healthy_null_message(self):
        """When health.message is None, endpoint returns 'ok'."""
        mock_health = MagicMock()
        mock_health.status = "pass"
        mock_health.message = None

        mock_influx = MagicMock()
        mock_influx.health.return_value = mock_health

        with patch("app.routers.telemetry.settings") as mock_settings, \
             patch("app.routers.telemetry._get_client", return_value=mock_influx):
            mock_settings.influx_enabled = True
            mock_settings.influx_url = "http://localhost:8086"
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/health")
            data = resp.json()
            assert data["message"] == "ok"

    def test_health_exception(self):
        mock_influx = MagicMock()
        mock_influx.health.side_effect = ConnectionError("refused")

        with patch("app.routers.telemetry.settings") as mock_settings, \
             patch("app.routers.telemetry._get_client", return_value=mock_influx):
            mock_settings.influx_enabled = True
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "error"
            assert "refused" in data["message"]


# ---------------------------------------------------------------------------
# GET /api/telemetry/robot/{robot_id}
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRobotEndpoint:
    """GET /api/telemetry/robot/{robot_id} — robot telemetry history."""

    def test_basic_query(self):
        rows = [
            {"_time": "2026-01-01T00:00:00Z", "_field": "battery", "_value": 95},
            {"_time": "2026-01-01T01:00:00Z", "_field": "battery", "_value": 90},
        ]
        with patch("app.routers.telemetry._query", return_value=rows), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/robot/rover-alpha")
            assert resp.status_code == 200
            data = resp.json()
            assert data["robot_id"] == "rover-alpha"
            assert data["hours"] == 24  # default
            assert data["field"] is None
            assert data["count"] == 2
            assert len(data["data"]) == 2

    def test_custom_hours(self):
        with patch("app.routers.telemetry._query", return_value=[]) as mock_q, \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/robot/drone-1?hours=48")
            assert resp.status_code == 200
            data = resp.json()
            assert data["hours"] == 48
            assert data["robot_id"] == "drone-1"
            # Verify the Flux query contains the hours value
            flux_arg = mock_q.call_args[0][0]
            assert "-48h" in flux_arg

    def test_field_filter(self):
        with patch("app.routers.telemetry._query", return_value=[]) as mock_q, \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/robot/rover-alpha?field=speed")
            assert resp.status_code == 200
            data = resp.json()
            assert data["field"] == "speed"
            flux_arg = mock_q.call_args[0][0]
            assert 'r._field == "speed"' in flux_arg

    def test_hours_validation_low(self):
        client = TestClient(_make_app())
        resp = client.get("/api/telemetry/robot/rover-alpha?hours=0")
        assert resp.status_code == 422

    def test_hours_validation_high(self):
        client = TestClient(_make_app())
        resp = client.get("/api/telemetry/robot/rover-alpha?hours=200")
        assert resp.status_code == 422

    def test_empty_result(self):
        with patch("app.routers.telemetry._query", return_value=[]), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/robot/nonexistent")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0
            assert data["data"] == []

    def test_flux_query_contains_robot_id(self):
        with patch("app.routers.telemetry._query", return_value=[]) as mock_q, \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            client.get("/api/telemetry/robot/tank-bravo")
            flux_arg = mock_q.call_args[0][0]
            assert 'r.robot_id == "tank-bravo"' in flux_arg
            assert "robot_telemetry" in flux_arg

    def test_flux_query_contains_bucket(self):
        with patch("app.routers.telemetry._query", return_value=[]) as mock_q, \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "my-bucket"
            client = TestClient(_make_app())
            client.get("/api/telemetry/robot/rover-alpha")
            flux_arg = mock_q.call_args[0][0]
            assert 'from(bucket: "my-bucket")' in flux_arg


# ---------------------------------------------------------------------------
# GET /api/telemetry/detections
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDetectionsEndpoint:
    """GET /api/telemetry/detections — detection counts per camera."""

    def test_basic_query(self):
        rows = [
            {"camera_id": "cam-1", "_time": "2026-01-01T00:00:00Z", "_value": 15},
            {"camera_id": "cam-2", "_time": "2026-01-01T00:00:00Z", "_value": 8},
        ]
        with patch("app.routers.telemetry._query", return_value=rows), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/detections")
            assert resp.status_code == 200
            data = resp.json()
            assert data["hours"] == 24
            assert data["count"] == 2
            assert len(data["data"]) == 2

    def test_custom_hours(self):
        with patch("app.routers.telemetry._query", return_value=[]) as mock_q, \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/detections?hours=72")
            assert resp.status_code == 200
            data = resp.json()
            assert data["hours"] == 72
            flux_arg = mock_q.call_args[0][0]
            assert "-72h" in flux_arg

    def test_hours_validation(self):
        client = TestClient(_make_app())
        resp = client.get("/api/telemetry/detections?hours=0")
        assert resp.status_code == 422

    def test_empty_result(self):
        with patch("app.routers.telemetry._query", return_value=[]), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/detections")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0
            assert data["data"] == []

    def test_flux_query_structure(self):
        with patch("app.routers.telemetry._query", return_value=[]) as mock_q, \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            client.get("/api/telemetry/detections")
            flux_arg = mock_q.call_args[0][0]
            assert "camera_detections" in flux_arg
            assert "aggregateWindow" in flux_arg
            assert "group" in flux_arg


# ---------------------------------------------------------------------------
# GET /api/telemetry/system
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSystemEndpoint:
    """GET /api/telemetry/system — CPU/mem/disk metrics."""

    def test_basic_query(self):
        rows = [
            {"_measurement": "cpu", "_time": "2026-01-01T00:00:00Z", "_value": 45.2},
            {"_measurement": "mem", "_time": "2026-01-01T00:00:00Z", "_value": 68.1},
        ]
        with patch("app.routers.telemetry._query", return_value=rows), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/system")
            assert resp.status_code == 200
            data = resp.json()
            assert data["hours"] == 24
            assert data["count"] == 2

    def test_custom_hours(self):
        with patch("app.routers.telemetry._query", return_value=[]) as mock_q, \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/system?hours=168")
            assert resp.status_code == 200
            data = resp.json()
            assert data["hours"] == 168
            flux_arg = mock_q.call_args[0][0]
            assert "-168h" in flux_arg

    def test_hours_validation(self):
        client = TestClient(_make_app())
        resp = client.get("/api/telemetry/system?hours=169")
        assert resp.status_code == 422

    def test_empty_result(self):
        with patch("app.routers.telemetry._query", return_value=[]), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/system")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0

    def test_flux_query_structure(self):
        with patch("app.routers.telemetry._query", return_value=[]) as mock_q, \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            client.get("/api/telemetry/system")
            flux_arg = mock_q.call_args[0][0]
            assert '"cpu"' in flux_arg
            assert '"mem"' in flux_arg
            assert '"disk"' in flux_arg
            assert "aggregateWindow" in flux_arg
            assert "limit(n: 2000)" in flux_arg


# ---------------------------------------------------------------------------
# GET /api/telemetry/summary
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSummaryEndpoint:
    """GET /api/telemetry/summary — fleet overview."""

    def test_basic_summary(self):
        robot_rows = [
            {"robot_id": "rover-alpha", "_field": "battery", "_value": 85},
            {"robot_id": "drone-1", "_field": "battery", "_value": 70},
        ]
        detection_rows = [
            {"_value": 42},
            {"_value": 18},
        ]

        call_count = 0

        def mock_query(flux):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return robot_rows
            return detection_rows

        with patch("app.routers.telemetry._query", side_effect=mock_query), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/summary")
            assert resp.status_code == 200
            data = resp.json()
            assert data["robots_online"] == 2
            assert sorted(data["robot_ids"]) == ["drone-1", "rover-alpha"]
            assert data["detections_last_hour"] == 60  # 42 + 18
            assert len(data["latest_robot_data"]) == 2

    def test_empty_fleet(self):
        with patch("app.routers.telemetry._query", return_value=[]), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/summary")
            assert resp.status_code == 200
            data = resp.json()
            assert data["robots_online"] == 0
            assert data["robot_ids"] == []
            assert data["detections_last_hour"] == 0
            assert data["latest_robot_data"] == []

    def test_detection_count_with_non_numeric(self):
        """Non-numeric _value entries are safely skipped."""
        robot_rows = [{"robot_id": "rover-alpha", "_field": "battery", "_value": 85}]
        detection_rows = [
            {"_value": 10},
            {"_value": "N/A"},  # non-numeric
            {"_value": 5},
        ]

        call_count = 0

        def mock_query(flux):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return robot_rows
            return detection_rows

        with patch("app.routers.telemetry._query", side_effect=mock_query), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/summary")
            data = resp.json()
            assert data["detections_last_hour"] == 15  # 10 + 5 (skips "N/A")

    def test_detection_count_missing_value_key(self):
        """Rows without _value key contribute 0."""
        robot_rows = []
        detection_rows = [
            {"_value": 7},
            {"other_key": "no value"},
        ]

        call_count = 0

        def mock_query(flux):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return robot_rows
            return detection_rows

        with patch("app.routers.telemetry._query", side_effect=mock_query), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/summary")
            data = resp.json()
            assert data["detections_last_hour"] == 7

    def test_robot_ids_deduplicated_and_sorted(self):
        robot_rows = [
            {"robot_id": "tank-bravo", "_value": 1},
            {"robot_id": "rover-alpha", "_value": 2},
            {"robot_id": "tank-bravo", "_value": 3},  # duplicate
            {"robot_id": "drone-1", "_value": 4},
        ]

        call_count = 0

        def mock_query(flux):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return robot_rows
            return []

        with patch("app.routers.telemetry._query", side_effect=mock_query), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/summary")
            data = resp.json()
            assert data["robot_ids"] == ["drone-1", "rover-alpha", "tank-bravo"]
            assert data["robots_online"] == 3

    def test_robot_rows_without_robot_id_excluded(self):
        """Rows missing robot_id are excluded from the robot_ids list."""
        robot_rows = [
            {"robot_id": "rover-alpha", "_value": 1},
            {"_value": 2},  # missing robot_id
            {"robot_id": "", "_value": 3},  # empty robot_id (falsy)
        ]

        call_count = 0

        def mock_query(flux):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return robot_rows
            return []

        with patch("app.routers.telemetry._query", side_effect=mock_query), \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            resp = client.get("/api/telemetry/summary")
            data = resp.json()
            assert data["robot_ids"] == ["rover-alpha"]
            assert data["robots_online"] == 1

    def test_summary_makes_two_queries(self):
        """Summary endpoint issues exactly two Flux queries."""
        with patch("app.routers.telemetry._query", return_value=[]) as mock_q, \
             patch("app.routers.telemetry.settings") as mock_settings:
            mock_settings.influx_bucket = "telemetry"
            client = TestClient(_make_app())
            client.get("/api/telemetry/summary")
            assert mock_q.call_count == 2
            # First query is robot_telemetry, second is camera_detections
            first_flux = mock_q.call_args_list[0][0][0]
            second_flux = mock_q.call_args_list[1][0][0]
            assert "robot_telemetry" in first_flux
            assert "camera_detections" in second_flux
