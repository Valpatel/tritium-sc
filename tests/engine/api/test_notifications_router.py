# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the notifications router — list, mark-read, count.

Uses a fresh NotificationManager per test (no database needed).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.notifications import router, set_manager
from engine.comms.notifications import NotificationManager


def _make_client() -> TestClient:
    """Create a TestClient backed by a fresh NotificationManager."""
    mgr = NotificationManager()
    set_manager(mgr)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), mgr


@pytest.mark.unit
class TestNotificationsAPI:
    """HTTP endpoint tests."""

    def test_list_empty(self):
        client, _ = _make_client()
        resp = client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_add(self):
        client, mgr = _make_client()
        mgr.add("Alert", "Something happened", severity="warning", source="test")
        resp = client.get("/api/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Alert"
        assert data[0]["severity"] == "warning"

    def test_list_unread_only(self):
        client, mgr = _make_client()
        nid1 = mgr.add("A", "a", source="x")
        mgr.add("B", "b", source="x")
        mgr.mark_read(nid1)
        resp = client.get("/api/notifications?unread_only=true")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "B"

    def test_list_with_limit(self):
        client, mgr = _make_client()
        for i in range(10):
            mgr.add(f"T{i}", f"m{i}", source="x")
        resp = client.get("/api/notifications?limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_mark_read_single(self):
        client, mgr = _make_client()
        nid = mgr.add("Test", "msg", source="x")
        resp = client.post(
            "/api/notifications/read",
            json={"notification_id": nid},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "marked_read"
        assert mgr.count_unread() == 0

    def test_mark_read_nonexistent(self):
        client, _ = _make_client()
        resp = client.post(
            "/api/notifications/read",
            json={"notification_id": "doesnotexist"},
        )
        assert resp.status_code == 404

    def test_mark_all_read(self):
        client, mgr = _make_client()
        mgr.add("A", "a", source="x")
        mgr.add("B", "b", source="x")
        resp = client.post(
            "/api/notifications/read",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "all_marked_read"
        assert resp.json()["count"] == 2
        assert mgr.count_unread() == 0

    def test_unread_count(self):
        client, mgr = _make_client()
        mgr.add("A", "a", source="x")
        mgr.add("B", "b", source="x")
        resp = client.get("/api/notifications/count")
        assert resp.status_code == 200
        assert resp.json()["unread"] == 2

    def test_unread_count_after_mark(self):
        client, mgr = _make_client()
        nid = mgr.add("A", "a", source="x")
        mgr.add("B", "b", source="x")
        mgr.mark_read(nid)
        resp = client.get("/api/notifications/count")
        assert resp.status_code == 200
        assert resp.json()["unread"] == 1

    def test_notification_with_entity_id(self):
        client, mgr = _make_client()
        mgr.add("Alert", "msg", source="x", entity_id="dossier-42")
        resp = client.get("/api/notifications")
        data = resp.json()
        assert data[0]["entity_id"] == "dossier-42"
