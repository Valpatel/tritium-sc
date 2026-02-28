# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the assets router -- asset CRUD, tasking, telemetry,
commands, and quick actions.

Tests Pydantic models, database operations with a temp SQLite backend,
and endpoint validation (404, 400, happy paths).
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.routers.assets import (
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    TaskCreate,
    TaskResponse,
    CommandRequest,
    TelemetryUpdate,
    router,
)
from app.database import Base, get_db
from app.models import Asset, AssetTask, AssetTelemetry


# ---------------------------------------------------------------------------
# Test helpers: per-test temp SQLite database
# ---------------------------------------------------------------------------

def _make_app_and_client():
    """Create a FastAPI app with the assets router backed by a fresh temp DB.

    Returns (TestClient, cleanup_func).  Call cleanup_func when done.
    """
    # Create a temp file for the DB
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(db_url, echo=False, future=True)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    # Create tables synchronously
    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_init())
    loop.close()

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _override_get_db

    client = TestClient(app)

    def _cleanup():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(engine.dispose())
        loop.close()
        os.unlink(db_path)

    return client, _cleanup


def _seed_asset(client: TestClient, **overrides) -> dict:
    """Helper: POST an asset and return the response JSON."""
    payload = {
        "asset_id": "UNIT-01",
        "name": "Alpha Rover",
        "asset_type": "ground",
        "asset_class": "patrol",
        "capabilities": ["patrol", "loiter", "recall"],
    }
    payload.update(overrides)
    resp = client.post("/api/assets", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Pydantic Model Validation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAssetModels:
    """Validate asset request/response models."""

    def test_asset_create_required_fields(self):
        a = AssetCreate(asset_id="UNIT-01", name="Alpha", asset_type="ground")
        assert a.asset_id == "UNIT-01"
        assert a.asset_class == "patrol"
        assert a.capabilities == ["patrol", "loiter", "recall"]

    def test_asset_create_missing_asset_id(self):
        with pytest.raises(ValidationError):
            AssetCreate(name="Alpha", asset_type="ground")

    def test_asset_create_missing_name(self):
        with pytest.raises(ValidationError):
            AssetCreate(asset_id="UNIT-01", asset_type="ground")

    def test_asset_create_missing_type(self):
        with pytest.raises(ValidationError):
            AssetCreate(asset_id="UNIT-01", name="Alpha")

    def test_asset_create_custom_capabilities(self):
        a = AssetCreate(
            asset_id="UNIT-02", name="Beta", asset_type="aerial",
            capabilities=["patrol", "track", "engage"],
        )
        assert "engage" in a.capabilities

    def test_asset_update_partial(self):
        u = AssetUpdate(name="New Name")
        assert u.name == "New Name"
        assert u.status is None
        assert u.battery_level is None

    def test_asset_update_all_fields(self):
        u = AssetUpdate(
            name="Updated", status="active", battery_level=85.5,
            ammo_level=50.0, position_x=10.0, position_y=20.0,
            heading=180.0, speed=2.5, enabled=False,
        )
        assert u.battery_level == pytest.approx(85.5)
        assert u.enabled is False

    def test_task_create_defaults(self):
        t = TaskCreate(task_type="patrol")
        assert t.priority == 5
        assert t.target_type is None
        assert t.waypoints is None

    def test_task_create_priority_bounds_low(self):
        with pytest.raises(ValidationError):
            TaskCreate(task_type="patrol", priority=0)

    def test_task_create_priority_bounds_high(self):
        with pytest.raises(ValidationError):
            TaskCreate(task_type="patrol", priority=11)

    def test_task_create_with_waypoints(self):
        t = TaskCreate(
            task_type="patrol",
            waypoints=[[10.0, 20.0], [30.0, 40.0]],
        )
        assert len(t.waypoints) == 2

    def test_command_request(self):
        c = CommandRequest(command="stop")
        assert c.command == "stop"
        assert c.parameters is None

    def test_command_request_with_params(self):
        c = CommandRequest(command="set_speed", parameters={"speed": 3.0})
        assert c.parameters["speed"] == 3.0

    def test_command_request_missing_command(self):
        with pytest.raises(ValidationError):
            CommandRequest()

    def test_telemetry_update(self):
        t = TelemetryUpdate(position_x=10.0, position_y=20.0)
        assert t.heading is None
        assert t.battery_level is None

    def test_telemetry_update_full(self):
        t = TelemetryUpdate(
            position_x=10.0, position_y=20.0, heading=90.0,
            speed=1.5, battery_level=72.0, status="active",
        )
        assert t.speed == pytest.approx(1.5)

    def test_telemetry_update_missing_position(self):
        with pytest.raises(ValidationError):
            TelemetryUpdate(position_x=10.0)  # Missing position_y


# ---------------------------------------------------------------------------
# Asset CRUD Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAssetCRUD:
    """POST/GET/PATCH/DELETE /api/assets."""

    def test_create_asset(self):
        client, cleanup = _make_app_and_client()
        try:
            data = _seed_asset(client)
            assert data["asset_id"] == "UNIT-01"
            assert data["name"] == "Alpha Rover"
            assert data["status"] == "standby"
            assert data["enabled"] is True
            assert "patrol" in data["capabilities"]
            assert data["current_task"] is None
        finally:
            cleanup()

    def test_create_duplicate_asset_400(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets", json={
                "asset_id": "UNIT-01", "name": "Duplicate",
                "asset_type": "ground",
            })
            assert resp.status_code == 400
            assert "already exists" in resp.json()["detail"]
        finally:
            cleanup()

    def test_list_assets_empty(self):
        client, cleanup = _make_app_and_client()
        try:
            resp = client.get("/api/assets")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            cleanup()

    def test_list_assets_populated(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client, asset_id="UNIT-01", name="Alpha")
            _seed_asset(client, asset_id="UNIT-02", name="Beta")
            resp = client.get("/api/assets")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
        finally:
            cleanup()

    def test_list_assets_filter_type(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client, asset_id="UNIT-01", asset_type="ground")
            _seed_asset(client, asset_id="UNIT-02", asset_type="aerial")
            resp = client.get("/api/assets?asset_type=ground")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["asset_type"] == "ground"
        finally:
            cleanup()

    def test_get_asset(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.get("/api/assets/UNIT-01")
            assert resp.status_code == 200
            data = resp.json()
            assert data["asset_id"] == "UNIT-01"
        finally:
            cleanup()

    def test_get_asset_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            resp = client.get("/api/assets/NONEXISTENT")
            assert resp.status_code == 404
        finally:
            cleanup()

    def test_update_asset(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.patch("/api/assets/UNIT-01", json={
                "name": "Updated Rover",
                "battery_level": 95.0,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "Updated Rover"
            assert data["battery_level"] == pytest.approx(95.0)
        finally:
            cleanup()

    def test_update_asset_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            resp = client.patch("/api/assets/NONEXISTENT", json={"name": "X"})
            assert resp.status_code == 404
        finally:
            cleanup()

    def test_delete_asset(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.delete("/api/assets/UNIT-01")
            assert resp.status_code == 200
            assert resp.json()["status"] == "deleted"
            # Verify gone
            resp2 = client.get("/api/assets/UNIT-01")
            assert resp2.status_code == 404
        finally:
            cleanup()

    def test_delete_asset_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            resp = client.delete("/api/assets/NONEXISTENT")
            assert resp.status_code == 404
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# Task Assignment
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTaskAssignment:
    """POST /api/assets/{id}/task -- task creation and validation."""

    def test_assign_task(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/task", json={
                "task_type": "patrol",
                "waypoints": [[10, 20], [30, 40]],
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["task_type"] == "patrol"
            assert data["status"] == "pending"
            assert data["priority"] == 5
            assert data["waypoints"] == [[10, 20], [30, 40]]
            assert data["task_id"].startswith("TASK-")
        finally:
            cleanup()

    def test_assign_task_asset_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            resp = client.post("/api/assets/NONEXISTENT/task", json={
                "task_type": "patrol",
            })
            assert resp.status_code == 404
        finally:
            cleanup()

    def test_assign_task_unsupported_capability(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client, capabilities=["patrol", "loiter"])
            resp = client.post("/api/assets/UNIT-01/task", json={
                "task_type": "engage",
            })
            assert resp.status_code == 400
            assert "does not support" in resp.json()["detail"]
        finally:
            cleanup()

    def test_assign_task_disabled_asset(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            # Disable the asset
            client.patch("/api/assets/UNIT-01", json={"enabled": False})
            resp = client.post("/api/assets/UNIT-01/task", json={
                "task_type": "patrol",
            })
            assert resp.status_code == 400
            assert "disabled" in resp.json()["detail"]
        finally:
            cleanup()

    def test_assign_task_changes_asset_status(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            client.post("/api/assets/UNIT-01/task", json={"task_type": "patrol"})
            resp = client.get("/api/assets/UNIT-01")
            assert resp.json()["status"] == "tasked"
        finally:
            cleanup()

    def test_list_tasks(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            client.post("/api/assets/UNIT-01/task", json={"task_type": "patrol"})
            client.post("/api/assets/UNIT-01/task", json={"task_type": "loiter"})
            resp = client.get("/api/assets/UNIT-01/tasks")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
        finally:
            cleanup()

    def test_list_tasks_asset_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            resp = client.get("/api/assets/NONEXISTENT/tasks")
            assert resp.status_code == 404
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# Task Lifecycle (start / complete / cancel)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTaskLifecycle:
    """Start, complete, and cancel tasks."""

    def _create_task(self, client: TestClient) -> str:
        _seed_asset(client)
        resp = client.post("/api/assets/UNIT-01/task", json={
            "task_type": "patrol",
        })
        return resp.json()["task_id"]

    def test_start_task(self):
        client, cleanup = _make_app_and_client()
        try:
            task_id = self._create_task(client)
            resp = client.post(f"/api/assets/UNIT-01/task/{task_id}/start")
            assert resp.status_code == 200
            assert resp.json()["status"] == "started"
        finally:
            cleanup()

    def test_start_task_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/task/TASK-FAKE/start")
            assert resp.status_code == 404
        finally:
            cleanup()

    def test_start_already_active_task(self):
        client, cleanup = _make_app_and_client()
        try:
            task_id = self._create_task(client)
            client.post(f"/api/assets/UNIT-01/task/{task_id}/start")
            resp = client.post(f"/api/assets/UNIT-01/task/{task_id}/start")
            assert resp.status_code == 400
            assert "not pending" in resp.json()["detail"]
        finally:
            cleanup()

    def test_complete_task(self):
        client, cleanup = _make_app_and_client()
        try:
            task_id = self._create_task(client)
            client.post(f"/api/assets/UNIT-01/task/{task_id}/start")
            resp = client.post(f"/api/assets/UNIT-01/task/{task_id}/complete")
            assert resp.status_code == 200
            assert resp.json()["status"] == "completed"
            # Asset should return to standby
            asset = client.get("/api/assets/UNIT-01").json()
            assert asset["status"] == "standby"
        finally:
            cleanup()

    def test_complete_task_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/task/TASK-FAKE/complete")
            assert resp.status_code == 404
        finally:
            cleanup()

    def test_cancel_task(self):
        client, cleanup = _make_app_and_client()
        try:
            task_id = self._create_task(client)
            resp = client.post(f"/api/assets/UNIT-01/task/{task_id}/cancel")
            assert resp.status_code == 200
            assert resp.json()["status"] == "cancelled"
            # Asset should return to standby
            asset = client.get("/api/assets/UNIT-01").json()
            assert asset["status"] == "standby"
        finally:
            cleanup()

    def test_cancel_task_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/task/TASK-FAKE/cancel")
            assert resp.status_code == 404
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTelemetry:
    """POST/GET /api/assets/{id}/telemetry."""

    def test_update_telemetry(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/telemetry", json={
                "position_x": 15.5, "position_y": 25.5,
                "heading": 90.0, "speed": 1.2,
                "battery_level": 88.0,
            })
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
            # Verify asset state updated
            asset = client.get("/api/assets/UNIT-01").json()
            assert asset["position_x"] == pytest.approx(15.5)
            assert asset["position_y"] == pytest.approx(25.5)
            assert asset["battery_level"] == pytest.approx(88.0)
        finally:
            cleanup()

    def test_update_telemetry_with_status(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            client.post("/api/assets/UNIT-01/telemetry", json={
                "position_x": 0.0, "position_y": 0.0,
                "status": "active",
            })
            asset = client.get("/api/assets/UNIT-01").json()
            assert asset["status"] == "active"
        finally:
            cleanup()

    def test_update_telemetry_asset_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            resp = client.post("/api/assets/NONEXISTENT/telemetry", json={
                "position_x": 0.0, "position_y": 0.0,
            })
            assert resp.status_code == 404
        finally:
            cleanup()

    def test_get_telemetry_history(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            # Send multiple telemetry updates
            for i in range(3):
                client.post("/api/assets/UNIT-01/telemetry", json={
                    "position_x": float(i * 10),
                    "position_y": float(i * 10),
                })
            resp = client.get("/api/assets/UNIT-01/telemetry")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 3
        finally:
            cleanup()

    def test_get_telemetry_history_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            resp = client.get("/api/assets/NONEXISTENT/telemetry")
            assert resp.status_code == 404
        finally:
            cleanup()

    def test_telemetry_updates_heartbeat(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            client.post("/api/assets/UNIT-01/telemetry", json={
                "position_x": 0.0, "position_y": 0.0,
            })
            asset = client.get("/api/assets/UNIT-01").json()
            assert asset["last_heartbeat"] is not None
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCommands:
    """POST /api/assets/{id}/command."""

    def test_stop_command(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/command", json={
                "command": "stop",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "sent"
            assert data["command"] == "stop"
            # Asset should be standby with speed 0
            asset = client.get("/api/assets/UNIT-01").json()
            assert asset["status"] == "standby"
        finally:
            cleanup()

    def test_return_home_command(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/command", json={
                "command": "return_home",
            })
            assert resp.status_code == 200
            asset = client.get("/api/assets/UNIT-01").json()
            assert asset["status"] == "returning"
        finally:
            cleanup()

    def test_emergency_stop_command(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/command", json={
                "command": "emergency_stop",
            })
            assert resp.status_code == 200
            asset = client.get("/api/assets/UNIT-01").json()
            assert asset["status"] == "stopped"
        finally:
            cleanup()

    def test_command_with_params(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/command", json={
                "command": "set_speed",
                "parameters": {"speed": 3.0},
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["parameters"]["speed"] == 3.0
        finally:
            cleanup()

    def test_command_asset_not_found(self):
        client, cleanup = _make_app_and_client()
        try:
            resp = client.post("/api/assets/NONEXISTENT/command", json={
                "command": "stop",
            })
            assert resp.status_code == 404
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# Quick Actions
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestQuickActions:
    """Quick action endpoints: patrol, recall, track."""

    def test_quick_patrol(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/patrol", json=[
                [10.0, 20.0], [30.0, 40.0],
            ])
            assert resp.status_code == 200
            data = resp.json()
            assert data["task_type"] == "patrol"
            assert data["waypoints"] == [[10.0, 20.0], [30.0, 40.0]]
        finally:
            cleanup()

    def test_quick_recall(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client)
            resp = client.post("/api/assets/UNIT-01/recall")
            assert resp.status_code == 200
            data = resp.json()
            assert data["task_type"] == "recall"
            assert data["priority"] == 1  # High priority
        finally:
            cleanup()

    def test_quick_track(self):
        client, cleanup = _make_app_and_client()
        try:
            _seed_asset(client, capabilities=["patrol", "track", "recall"])
            resp = client.post(
                "/api/assets/UNIT-01/track",
                params={"target_type": "person", "target_id": "TRACK-42"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["task_type"] == "track"
            assert data["target_type"] == "person"
            assert data["target_id"] == "TRACK-42"
        finally:
            cleanup()
