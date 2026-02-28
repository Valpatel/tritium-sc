# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Telemetry API — proxies InfluxDB queries so tokens never reach the browser."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from loguru import logger

from app.config import settings

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

# ---------------------------------------------------------------------------
# Lazy InfluxDB client singleton
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    """Return an InfluxDBClient, creating it lazily on first call.

    Returns None if InfluxDB is disabled or the client library is missing.
    """
    global _client
    if _client is not None:
        return _client

    if not settings.influx_enabled:
        return None

    try:
        from influxdb_client import InfluxDBClient

        _client = InfluxDBClient(
            url=settings.influx_url,
            token=settings.influx_token,
            org=settings.influx_org,
        )
        return _client
    except ImportError:
        logger.warning("influxdb-client not installed — telemetry API disabled")
        return None
    except Exception as exc:
        logger.warning(f"InfluxDB client init failed: {exc}")
        return None


def _query(flux: str) -> list[dict[str, Any]]:
    """Execute a Flux query and return results as a list of dicts."""
    client = _get_client()
    if client is None:
        return []

    try:
        api = client.query_api()
        tables = api.query(flux, org=settings.influx_org)
        rows: list[dict[str, Any]] = []
        for table in tables:
            for record in table.records:
                rows.append(record.values)
        return rows
    except Exception as exc:
        logger.warning(f"InfluxDB query failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health")
async def telemetry_health() -> dict[str, Any]:
    """Check InfluxDB connection status."""
    if not settings.influx_enabled:
        return {"status": "disabled", "message": "InfluxDB is disabled in config"}

    client = _get_client()
    if client is None:
        return {"status": "error", "message": "InfluxDB client not available"}

    try:
        health = client.health()
        return {
            "status": health.status,
            "message": health.message or "ok",
            "influx_url": settings.influx_url,
            "bucket": settings.influx_bucket,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@router.get("/robot/{robot_id}")
async def robot_telemetry(
    robot_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    field: str | None = Query(default=None),
) -> dict[str, Any]:
    """Query robot telemetry history.

    Args:
        robot_id: Robot identifier (e.g. "rover-alpha").
        hours: Lookback window in hours (1-168, default 24).
        field: Optional field filter (e.g. "battery", "speed").
    """
    field_filter = ""
    if field:
        field_filter = f'  |> filter(fn: (r) => r._field == "{field}")'

    flux = f"""
from(bucket: "{settings.influx_bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "robot_telemetry")
  |> filter(fn: (r) => r.robot_id == "{robot_id}")
{field_filter}
  |> sort(columns: ["_time"])
  |> limit(n: 1000)
"""
    rows = _query(flux)
    return {"robot_id": robot_id, "hours": hours, "field": field, "count": len(rows), "data": rows}


@router.get("/detections")
async def detection_counts(
    hours: int = Query(default=24, ge=1, le=168),
) -> dict[str, Any]:
    """Detection counts per camera over time (windowed)."""
    flux = f"""
from(bucket: "{settings.influx_bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "camera_detections")
  |> group(columns: ["camera_id"])
  |> aggregateWindow(every: 1h, fn: count, createEmpty: false)
  |> sort(columns: ["_time"])
"""
    rows = _query(flux)
    return {"hours": hours, "count": len(rows), "data": rows}


@router.get("/system")
async def system_metrics(
    hours: int = Query(default=24, ge=1, le=168),
) -> dict[str, Any]:
    """CPU, memory, and disk metrics across all nodes."""
    flux = f"""
from(bucket: "{settings.influx_bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "cpu" or r._measurement == "mem" or r._measurement == "disk")
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
  |> sort(columns: ["_time"])
  |> limit(n: 2000)
"""
    rows = _query(flux)
    return {"hours": hours, "count": len(rows), "data": rows}


@router.get("/summary")
async def fleet_summary() -> dict[str, Any]:
    """Fleet status: latest values from each robot, total counts."""
    # Latest telemetry per robot
    flux_robots = f"""
from(bucket: "{settings.influx_bucket}")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "robot_telemetry")
  |> group(columns: ["robot_id"])
  |> last()
"""
    robots = _query(flux_robots)

    # Total detection count last hour
    flux_detections = f"""
from(bucket: "{settings.influx_bucket}")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "camera_detections")
  |> count()
"""
    detections = _query(flux_detections)

    detection_count = 0
    for row in detections:
        val = row.get("_value", 0)
        if isinstance(val, (int, float)):
            detection_count += int(val)

    # Unique robot IDs from recent data
    robot_ids = sorted({r.get("robot_id", "unknown") for r in robots if r.get("robot_id")})

    return {
        "robots_online": len(robot_ids),
        "robot_ids": robot_ids,
        "detections_last_hour": detection_count,
        "latest_robot_data": robots,
    }
