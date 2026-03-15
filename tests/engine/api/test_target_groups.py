# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for target groups API."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

# Set data dir to temp before importing router
_tmpdir = tempfile.mkdtemp()
os.environ["TRITIUM_DATA_DIR"] = _tmpdir

from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.routers.target_groups import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_db():
    """Reset DB between tests."""
    import app.routers.target_groups as tg
    tg._db_initialized = False
    tg._DB_PATH = None
    os.environ["TRITIUM_DATA_DIR"] = tempfile.mkdtemp()
    yield


class TestTargetGroupsCRUD:
    def test_list_empty(self):
        resp = client.get("/api/target-groups")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["groups"] == []

    def test_create_group(self):
        resp = client.post("/api/target-groups", json={
            "name": "Building A",
            "description": "Devices in building A",
            "color": "#ff2a6d",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Building A"
        assert data["group_id"].startswith("grp_")
        assert data["color"] == "#ff2a6d"
        assert data["target_ids"] == []

    def test_get_group(self):
        create = client.post("/api/target-groups", json={"name": "G1"}).json()
        gid = create["group_id"]
        resp = client.get(f"/api/target-groups/{gid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "G1"

    def test_get_group_not_found(self):
        resp = client.get("/api/target-groups/nonexistent")
        assert resp.status_code == 404

    def test_update_group(self):
        create = client.post("/api/target-groups", json={"name": "G1"}).json()
        gid = create["group_id"]
        resp = client.put(f"/api/target-groups/{gid}", json={"name": "G1 Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "G1 Updated"

    def test_delete_group(self):
        create = client.post("/api/target-groups", json={"name": "G1"}).json()
        gid = create["group_id"]
        resp = client.delete(f"/api/target-groups/{gid}")
        assert resp.status_code == 200
        assert resp.json()["ok"]
        # Verify deleted
        resp = client.get(f"/api/target-groups/{gid}")
        assert resp.status_code == 404

    def test_add_targets(self):
        create = client.post("/api/target-groups", json={"name": "G1"}).json()
        gid = create["group_id"]
        resp = client.post(f"/api/target-groups/{gid}/targets", json={
            "target_ids": ["ble_aa:bb:cc:dd:ee:ff", "det_person_1"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["added"]) == 2
        assert data["total_targets"] == 2

    def test_add_duplicate_targets(self):
        create = client.post("/api/target-groups", json={
            "name": "G1",
            "target_ids": ["t1"],
        }).json()
        gid = create["group_id"]
        resp = client.post(f"/api/target-groups/{gid}/targets", json={
            "target_ids": ["t1", "t2"],
        })
        data = resp.json()
        assert "t1" not in data["added"]
        assert "t2" in data["added"]
        assert data["total_targets"] == 2

    def test_remove_targets(self):
        create = client.post("/api/target-groups", json={
            "name": "G1",
            "target_ids": ["t1", "t2", "t3"],
        }).json()
        gid = create["group_id"]
        resp = client.request("DELETE", f"/api/target-groups/{gid}/targets", json={
            "target_ids": ["t1", "t3"],
        })
        data = resp.json()
        assert len(data["removed"]) == 2
        assert data["total_targets"] == 1
