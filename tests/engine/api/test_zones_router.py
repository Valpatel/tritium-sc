"""Unit tests for the zones router API — CRUD endpoints, event listing,
and request/response model validation.

Tests the API layer with a mocked ZoneManager (zone logic already tested
in test_zones.py with 41 tests).
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.routers.zones import (
    CreateZoneRequest,
    UpdateZoneRequest,
    ZoneResponse,
    ZoneEventResponse,
    router,
)
from app.zones.models import Zone, ZoneEvent, ZoneType, ZoneEventType


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _make_zone(**kwargs) -> Zone:
    """Create a test Zone dataclass."""
    defaults = dict(
        zone_id="zone-1",
        camera_id=1,
        name="Front Door",
        polygon=[(100, 100), (200, 100), (200, 200), (100, 200)],
        zone_type=ZoneType.ENTRY_EXIT,
        enabled=True,
        created_at=datetime(2026, 1, 15, 10, 0),
        total_events=5,
        last_event_at=datetime(2026, 1, 15, 14, 30),
    )
    defaults.update(kwargs)
    return Zone(**defaults)


def _make_event(**kwargs) -> ZoneEvent:
    """Create a test ZoneEvent dataclass."""
    defaults = dict(
        event_id="evt-1",
        zone_id="zone-1",
        zone_name="Front Door",
        event_type=ZoneEventType.ENTER,
        timestamp=datetime(2026, 1, 15, 14, 30),
        camera_id=1,
        target_type="person",
    )
    defaults.update(kwargs)
    return ZoneEvent(**defaults)


# ---------------------------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestZoneRequestModels:
    """Validate zone request models."""

    def test_create_zone_request(self):
        r = CreateZoneRequest(
            camera_id=1, name="Driveway",
            polygon=[[0, 0], [100, 0], [100, 100], [0, 100]],
            zone_type="entry_exit",
        )
        assert r.camera_id == 1
        assert r.alert_on_enter is True
        assert r.cooldown_seconds == 30

    def test_create_zone_request_all_fields(self):
        r = CreateZoneRequest(
            camera_id=2, name="Garage",
            polygon=[[0, 0], [50, 0], [50, 50]],
            zone_type="object_monitor",
            monitored_object="garage_door",
            alert_on_enter=False,
            alert_on_exit=True,
            alert_on_linger=True,
            linger_threshold_seconds=120,
            cooldown_seconds=60,
        )
        assert r.monitored_object == "garage_door"
        assert r.linger_threshold_seconds == 120

    def test_update_zone_request_empty(self):
        r = UpdateZoneRequest()
        assert r.name is None
        assert r.enabled is None

    def test_update_zone_request_partial(self):
        r = UpdateZoneRequest(name="New Name", enabled=False)
        assert r.name == "New Name"
        assert r.enabled is False

    def test_zone_response(self):
        r = ZoneResponse(
            zone_id="z1", camera_id=1, name="Test",
            polygon=[[0, 0], [1, 0], [1, 1]],
            zone_type="entry_exit", enabled=True,
            created_at="2026-01-15T10:00:00",
            monitored_object=None,
            total_events=0, last_event_at=None,
        )
        assert r.zone_id == "z1"

    def test_zone_event_response(self):
        r = ZoneEventResponse(
            event_id="e1", zone_id="z1", zone_name="Test",
            event_type="enter", timestamp="2026-01-15T14:30:00",
            camera_id=1, target_type="person",
            target_thumbnail_id=None, video_path=None,
            frame_number=None,
        )
        assert r.event_type == "enter"


# ---------------------------------------------------------------------------
# Zone CRUD Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestZoneCRUD:
    """Zone creation, listing, get, update, delete."""

    def test_create_zone(self):
        zone = _make_zone()
        mock_mgr = MagicMock()
        mock_mgr.create_zone.return_value = zone
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.post("/api/zones/", json={
                "camera_id": 1, "name": "Front Door",
                "polygon": [[100, 100], [200, 100], [200, 200], [100, 200]],
                "zone_type": "entry_exit",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["zone_id"] == "zone-1"
            assert data["name"] == "Front Door"

    def test_create_zone_invalid_type(self):
        mock_mgr = MagicMock()
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.post("/api/zones/", json={
                "camera_id": 1, "name": "Test",
                "polygon": [[0, 0], [1, 0], [1, 1]],
                "zone_type": "invalid_type",
            })
            assert resp.status_code == 400
            assert "Invalid zone_type" in resp.json()["detail"]

    def test_create_zone_too_few_points(self):
        mock_mgr = MagicMock()
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.post("/api/zones/", json={
                "camera_id": 1, "name": "Test",
                "polygon": [[0, 0], [1, 0]],
                "zone_type": "entry_exit",
            })
            assert resp.status_code == 400
            assert "at least 3" in resp.json()["detail"]

    def test_list_zones(self):
        zones = [_make_zone(zone_id="z1", name="A"), _make_zone(zone_id="z2", name="B")]
        mock_mgr = MagicMock()
        mock_mgr.get_all_zones.return_value = zones
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/zones/")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2

    def test_list_zones_by_camera(self):
        zones = [_make_zone(camera_id=2)]
        mock_mgr = MagicMock()
        mock_mgr.get_zones_for_camera.return_value = zones
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/zones/?camera_id=2")
            assert resp.status_code == 200
            mock_mgr.get_zones_for_camera.assert_called_once_with(2)

    def test_get_zone(self):
        zone = _make_zone()
        mock_mgr = MagicMock()
        mock_mgr.get_zone.return_value = zone
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/zones/zone-1")
            assert resp.status_code == 200
            assert resp.json()["zone_id"] == "zone-1"

    def test_get_zone_not_found(self):
        mock_mgr = MagicMock()
        mock_mgr.get_zone.return_value = None
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/zones/nonexistent")
            assert resp.status_code == 404

    def test_update_zone(self):
        zone = _make_zone(name="Updated Name")
        mock_mgr = MagicMock()
        mock_mgr.update_zone.return_value = zone
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.put("/api/zones/zone-1", json={"name": "Updated Name"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "Updated Name"

    def test_update_zone_not_found(self):
        mock_mgr = MagicMock()
        mock_mgr.update_zone.return_value = None
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.put("/api/zones/nonexistent", json={"name": "X"})
            assert resp.status_code == 404

    def test_delete_zone(self):
        mock_mgr = MagicMock()
        mock_mgr.delete_zone.return_value = True
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.delete("/api/zones/zone-1")
            assert resp.status_code == 200
            assert resp.json()["status"] == "deleted"

    def test_delete_zone_not_found(self):
        mock_mgr = MagicMock()
        mock_mgr.delete_zone.return_value = False
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.delete("/api/zones/nonexistent")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Zone Events
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestZoneEvents:
    """GET /api/zones/{id}/events, summary, and by-target."""

    def test_get_zone_events(self):
        events = [_make_event(event_id="e1"), _make_event(event_id="e2")]
        mock_mgr = MagicMock()
        mock_mgr.get_zone.return_value = _make_zone()
        mock_mgr.get_events_for_zone.return_value = events
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/zones/zone-1/events")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2

    def test_get_zone_events_not_found(self):
        mock_mgr = MagicMock()
        mock_mgr.get_zone.return_value = None
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/zones/nonexistent/events")
            assert resp.status_code == 404

    def test_get_zone_summary(self):
        mock_mgr = MagicMock()
        mock_mgr.get_zone_summary.return_value = {
            "zone_id": "zone-1", "total_events": 10,
            "hourly_distribution": [0] * 24,
        }
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/zones/zone-1/summary")
            assert resp.status_code == 200
            assert resp.json()["total_events"] == 10

    def test_get_zone_summary_not_found(self):
        mock_mgr = MagicMock()
        mock_mgr.get_zone_summary.return_value = None
        with patch("app.routers.zones.get_zone_manager", return_value=mock_mgr):
            client = TestClient(_make_app())
            resp = client.get("/api/zones/nonexistent/summary")
            assert resp.status_code == 404
