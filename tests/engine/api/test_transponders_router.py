# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the AIS/ADS-B transponder receiver router."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.transponders import router
from app.routers import transponders as tp_module


@pytest.fixture
def tp_app():
    """Minimal FastAPI app with only the transponders router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(tp_app):
    tp_module._flights.clear()
    tp_module._vessels.clear()
    tp_module._stats.update({
        "adsb_reports": 0,
        "ais_reports": 0,
        "active_flights": 0,
        "active_vessels": 0,
        "emergencies": 0,
    })
    return TestClient(tp_app, raise_server_exceptions=False)


def test_submit_adsb_report(client):
    """Submit a basic ADS-B flight report."""
    resp = client.post("/api/transponders/adsb/report", json={
        "icao_hex": "A1B2C3",
        "callsign": "UAL123",
        "latitude": 37.7749,
        "longitude": -122.4194,
        "altitude_ft": 35000,
        "ground_speed": 450,
        "squawk": "1200",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_id"] == "adsb_a1b2c3"
    assert data["emergency"] is False


def test_adsb_emergency_squawk(client):
    """Detect emergency squawk codes."""
    for code in ["7500", "7600", "7700"]:
        resp = client.post("/api/transponders/adsb/report", json={
            "icao_hex": f"EMG{code}",
            "squawk": code,
        })
        assert resp.json()["emergency"] is True


def test_list_flights(client):
    """List tracked flights."""
    client.post("/api/transponders/adsb/report", json={
        "icao_hex": "AAA111",
        "callsign": "DAL456",
    })
    client.post("/api/transponders/adsb/report", json={
        "icao_hex": "BBB222",
        "callsign": "SWA789",
    })

    resp = client.get("/api/transponders/adsb/flights")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_filter_emergency_flights(client):
    """Filter flights by emergency status."""
    client.post("/api/transponders/adsb/report", json={
        "icao_hex": "NORMAL1",
        "squawk": "1200",
    })
    client.post("/api/transponders/adsb/report", json={
        "icao_hex": "EMERG1",
        "squawk": "7700",
    })

    resp = client.get("/api/transponders/adsb/flights?emergency=true")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["icao_hex"] == "EMERG1"


def test_submit_ais_report(client):
    """Submit a basic AIS vessel report."""
    resp = client.post("/api/transponders/ais/report", json={
        "mmsi": 123456789,
        "name": "SS TRITIUM",
        "vessel_type": "cargo",
        "latitude": 37.8,
        "longitude": -122.4,
        "speed_over_ground": 12.5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_id"] == "ais_123456789"


def test_list_vessels(client):
    """List tracked vessels."""
    client.post("/api/transponders/ais/report", json={
        "mmsi": 111111111,
        "name": "Vessel A",
    })
    client.post("/api/transponders/ais/report", json={
        "mmsi": 222222222,
        "name": "Vessel B",
    })

    resp = client.get("/api/transponders/ais/vessels")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_filter_vessel_type(client):
    """Filter vessels by type."""
    client.post("/api/transponders/ais/report", json={
        "mmsi": 111111111,
        "vessel_type": "cargo",
    })
    client.post("/api/transponders/ais/report", json={
        "mmsi": 222222222,
        "vessel_type": "fishing",
    })

    resp = client.get("/api/transponders/ais/vessels?vessel_type=cargo")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["vessel_type"] == "cargo"


def test_stats(client):
    """Get transponder receiver stats."""
    client.post("/api/transponders/adsb/report", json={"icao_hex": "A1"})
    client.post("/api/transponders/ais/report", json={"mmsi": 111})

    resp = client.get("/api/transponders/stats")
    data = resp.json()
    assert data["adsb_reports_total"] == 1
    assert data["ais_reports_total"] == 1
    assert data["active_flights"] == 1
    assert data["active_vessels"] == 1


def test_emergencies(client):
    """Get active emergencies."""
    client.post("/api/transponders/adsb/report", json={
        "icao_hex": "EMG1",
        "squawk": "7500",
    })

    resp = client.get("/api/transponders/emergencies")
    data = resp.json()
    assert data["total"] == 1
    assert len(data["adsb_emergencies"]) == 1


def test_adsb_update_existing_flight(client):
    """Updating a flight with same ICAO should overwrite."""
    client.post("/api/transponders/adsb/report", json={
        "icao_hex": "AAA111",
        "altitude_ft": 30000,
    })
    client.post("/api/transponders/adsb/report", json={
        "icao_hex": "AAA111",
        "altitude_ft": 35000,
    })

    resp = client.get("/api/transponders/adsb/flights")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["altitude_ft"] == 35000
