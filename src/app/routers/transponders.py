# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""AIS/ADS-B transponder receiver API endpoints.

Ingests maritime (AIS) and aviation (ADS-B) transponder data from
external receivers (RTL-SDR + dump1090 for ADS-B, rtl_ais for AIS)
and feeds into the unified target tracker.

Endpoints:
    POST /api/transponders/adsb/report   — submit ADS-B flight report
    GET  /api/transponders/adsb/flights  — list tracked flights
    POST /api/transponders/ais/report    — submit AIS vessel report
    GET  /api/transponders/ais/vessels   — list tracked vessels
    GET  /api/transponders/stats         — receiver statistics
    GET  /api/transponders/emergencies   — active emergency squawks/situations
"""

import time
from threading import Lock

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/transponders", tags=["transponders"])


# --- In-memory stores ---

_flights: dict[str, dict] = {}  # icao_hex -> flight dict
_flights_lock = Lock()

_vessels: dict[int, dict] = {}  # mmsi -> vessel dict
_vessels_lock = Lock()

_stats = {
    "adsb_reports": 0,
    "ais_reports": 0,
    "active_flights": 0,
    "active_vessels": 0,
    "emergencies": 0,
}
_stats_lock = Lock()

# Stale timeout: remove entries not seen for 5 minutes
STALE_TIMEOUT_S = 300


# --- Request models ---


class ADSBReport(BaseModel):
    """ADS-B position report from dump1090 or similar."""

    icao_hex: str
    callsign: str = ""
    registration: str = ""
    aircraft_type: str = ""
    operator: str = ""
    category: str = "unknown"  # light, small, large, heavy, rotorcraft, etc.
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_ft: float = 0.0
    heading: float = 0.0
    ground_speed: float = 0.0  # knots
    vertical_rate: float = 0.0  # ft/min
    squawk: str = "0000"
    on_ground: bool = False
    signal_strength: float = 0.0
    receiver_id: str = ""
    timestamp: float = Field(default_factory=time.time)


class AISReport(BaseModel):
    """AIS position report from rtl_ais or similar."""

    mmsi: int
    name: str = ""
    call_sign: str = ""
    imo_number: int = 0
    vessel_type: str = "unknown"
    vessel_type_code: int = 0
    latitude: float = 0.0
    longitude: float = 0.0
    heading: float = 0.0
    course_over_ground: float = 0.0
    speed_over_ground: float = 0.0  # knots
    navigation_status: str = "unknown"
    destination: str = ""
    length: float = 0.0
    beam: float = 0.0
    draught: float = 0.0
    signal_strength: float = 0.0
    receiver_id: str = ""
    timestamp: float = Field(default_factory=time.time)


# --- Helpers ---


def _is_emergency_squawk(squawk: str) -> bool:
    """Check if a squawk code indicates an emergency."""
    return squawk in ("7500", "7600", "7700")


def _prune_stale(store: dict, lock: Lock, timeout: float = STALE_TIMEOUT_S):
    """Remove entries not seen within timeout."""
    now = time.time()
    with lock:
        stale_keys = [
            k for k, v in store.items()
            if now - v.get("last_seen", 0) > timeout
        ]
        for k in stale_keys:
            del store[k]


# --- ADS-B endpoints ---


@router.post("/adsb/report")
async def submit_adsb_report(report: ADSBReport):
    """Submit an ADS-B position report."""
    icao = report.icao_hex.upper()
    target_id = f"adsb_{icao.lower()}"

    flight = {
        "icao_hex": icao,
        "callsign": report.callsign,
        "registration": report.registration,
        "aircraft_type": report.aircraft_type,
        "operator": report.operator,
        "category": report.category,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "altitude_ft": report.altitude_ft,
        "altitude_m": report.altitude_ft * 0.3048,
        "heading": report.heading,
        "ground_speed": report.ground_speed,
        "vertical_rate": report.vertical_rate,
        "squawk": report.squawk,
        "on_ground": report.on_ground,
        "emergency": _is_emergency_squawk(report.squawk),
        "signal_strength": report.signal_strength,
        "receiver_id": report.receiver_id,
        "target_id": target_id,
        "last_seen": report.timestamp,
    }

    with _flights_lock:
        _flights[icao] = flight

    with _stats_lock:
        _stats["adsb_reports"] += 1

    # Periodic pruning
    if _stats["adsb_reports"] % 100 == 0:
        _prune_stale(_flights, _flights_lock)

    return {
        "status": "accepted",
        "target_id": target_id,
        "emergency": flight["emergency"],
    }


@router.get("/adsb/flights")
async def get_flights(
    on_ground: bool | None = None,
    emergency: bool | None = None,
    limit: int = 100,
):
    """List currently tracked ADS-B flights."""
    _prune_stale(_flights, _flights_lock)

    with _flights_lock:
        results = list(_flights.values())

    if on_ground is not None:
        results = [f for f in results if f["on_ground"] == on_ground]
    if emergency is not None:
        results = [f for f in results if f["emergency"] == emergency]

    # Sort by last_seen descending
    results.sort(key=lambda f: f["last_seen"], reverse=True)
    return results[:limit]


# --- AIS endpoints ---


@router.post("/ais/report")
async def submit_ais_report(report: AISReport):
    """Submit an AIS position report."""
    target_id = f"ais_{report.mmsi}"

    vessel = {
        "mmsi": report.mmsi,
        "name": report.name,
        "call_sign": report.call_sign,
        "imo_number": report.imo_number,
        "vessel_type": report.vessel_type,
        "vessel_type_code": report.vessel_type_code,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "heading": report.heading,
        "course_over_ground": report.course_over_ground,
        "speed_over_ground": report.speed_over_ground,
        "navigation_status": report.navigation_status,
        "destination": report.destination,
        "length": report.length,
        "beam": report.beam,
        "draught": report.draught,
        "signal_strength": report.signal_strength,
        "receiver_id": report.receiver_id,
        "target_id": target_id,
        "last_seen": report.timestamp,
    }

    with _vessels_lock:
        _vessels[report.mmsi] = vessel

    with _stats_lock:
        _stats["ais_reports"] += 1

    if _stats["ais_reports"] % 100 == 0:
        _prune_stale(_vessels, _vessels_lock)

    return {"status": "accepted", "target_id": target_id}


@router.get("/ais/vessels")
async def get_vessels(
    vessel_type: str | None = None,
    limit: int = 100,
):
    """List currently tracked AIS vessels."""
    _prune_stale(_vessels, _vessels_lock)

    with _vessels_lock:
        results = list(_vessels.values())

    if vessel_type:
        results = [v for v in results if v["vessel_type"] == vessel_type]

    results.sort(key=lambda v: v["last_seen"], reverse=True)
    return results[:limit]


# --- Combined endpoints ---


@router.get("/stats")
async def get_stats():
    """Get transponder receiver statistics."""
    _prune_stale(_flights, _flights_lock)
    _prune_stale(_vessels, _vessels_lock)

    with _flights_lock:
        active_flights = len(_flights)
        emergencies = sum(1 for f in _flights.values() if f.get("emergency"))

    with _vessels_lock:
        active_vessels = len(_vessels)

    with _stats_lock:
        return {
            "adsb_reports_total": _stats["adsb_reports"],
            "ais_reports_total": _stats["ais_reports"],
            "active_flights": active_flights,
            "active_vessels": active_vessels,
            "active_emergencies": emergencies,
        }


@router.get("/emergencies")
async def get_emergencies():
    """Get all active emergency situations (ADS-B squawks + AIS distress)."""
    with _flights_lock:
        flight_emergencies = [
            f for f in _flights.values() if f.get("emergency")
        ]
    # Could add AIS distress signals here in future
    return {
        "adsb_emergencies": flight_emergencies,
        "ais_emergencies": [],
        "total": len(flight_emergencies),
    }
