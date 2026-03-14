# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the ontology API — /api/v1/ontology/*.

Tests all endpoints with mocked data stores (TargetTracker, DossierStore,
BleStore).
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.ontology import router, ENTITY_TYPES, ACTION_TYPES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(tracker=None, amy=None, dossier_store=None, ble_store=None):
    """Create FastAPI app with ontology router and optional state."""
    app = FastAPI()
    app.include_router(router)

    if amy is not None:
        app.state.amy = amy
    if ble_store is not None:
        app.state.ble_store = ble_store
    if dossier_store is not None:
        # Wire through dossier_manager
        mgr = MagicMock()
        mgr.store = dossier_store
        app.state.dossier_manager = mgr

    return app


def _mock_target(target_id="t1", alliance="friendly", name="Unit-1",
                 asset_type="rover", source="simulation"):
    """Create a mock TrackedTarget."""
    t = MagicMock()
    t.target_id = target_id
    t.alliance = alliance
    t.name = name
    t.asset_type = asset_type
    t.source = source
    t.to_dict.return_value = {
        "target_id": target_id,
        "name": name,
        "alliance": alliance,
        "asset_type": asset_type,
        "position": {"x": 1.0, "y": 2.0},
        "lat": 37.0,
        "lng": -122.0,
        "heading": 90.0,
        "speed": 1.5,
        "battery": 0.8,
        "source": source,
        "status": "active",
        "position_source": "simulation",
        "position_confidence": 1.0,
        "last_seen": time.monotonic(),
    }
    return t


def _mock_tracker(targets=None):
    """Create a mock TargetTracker."""
    tracker = MagicMock()
    tracker.get_all.return_value = targets or []
    tracker.history = MagicMock()
    tracker.history.get_trail_dicts.return_value = [
        {"x": 0.0, "y": 0.0, "t": 100.0},
        {"x": 1.0, "y": 1.0, "t": 101.0},
    ]
    return tracker


def _amy_with_tracker(tracker):
    amy = MagicMock()
    amy.target_tracker = tracker
    return amy


def _mock_dossier_store():
    """Create a mock DossierStore backed by an in-memory SQLite."""
    from tritium_lib.store.dossiers import DossierStore
    store = DossierStore(":memory:")
    return store


def _mock_ble_store():
    """Create a mock BleStore backed by in-memory SQLite."""
    from tritium_lib.store.ble import BleStore
    store = BleStore(":memory:")
    return store


# ---------------------------------------------------------------------------
# Type endpoints
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestListTypes:
    """GET /api/v1/ontology/types."""

    def test_returns_all_types(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/types")
        assert resp.status_code == 200
        data = resp.json()
        assert "types" in data
        type_names = [t["apiName"] for t in data["types"]]
        assert "Target" in type_names
        assert "Dossier" in type_names
        assert "BleDevice" in type_names
        assert "Device" in type_names

    def test_type_has_metadata(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/types")
        types = resp.json()["types"]
        for t in types:
            assert "displayName" in t
            assert "description" in t
            assert "primaryKey" in t
            assert "propertyCount" in t
            assert t["propertyCount"] > 0


@pytest.mark.unit
class TestGetType:
    """GET /api/v1/ontology/types/{type}."""

    def test_get_target_type(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/types/Target")
        assert resp.status_code == 200
        data = resp.json()
        assert data["apiName"] == "Target"
        assert "properties" in data
        assert "target_id" in data["properties"]
        assert "links" in data

    def test_get_dossier_type(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/types/Dossier")
        assert resp.status_code == 200
        data = resp.json()
        assert data["primaryKey"] == "dossier_id"
        assert "signals" in data["links"]

    def test_unknown_type_404(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/types/Nonexistent")
        assert resp.status_code == 404


@pytest.mark.unit
class TestGetTypeLinks:
    """GET /api/v1/ontology/types/{type}/links."""

    def test_target_links(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/types/Target/links")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "Target"
        link_names = [l["apiName"] for l in data["links"]]
        assert "dossier" in link_names
        assert "trail" in link_names

    def test_unknown_type_404(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/types/Bogus/links")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Object listing endpoints
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestListObjects:
    """GET /api/v1/ontology/objects/{type}."""

    def test_list_targets(self):
        t1 = _mock_target("unit-1", "friendly")
        t2 = _mock_target("hostile-1", "hostile", name="Bad Guy")
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/v1/ontology/objects/Target")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalCount"] == 2
        assert len(data["data"]) == 2
        assert data["nextPageToken"] is None

    def test_list_targets_pagination(self):
        targets = [_mock_target(f"t-{i}") for i in range(10)]
        tracker = _mock_tracker(targets=targets)
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        # First page
        resp = client.get("/api/v1/ontology/objects/Target?pageSize=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 3
        assert data["totalCount"] == 10
        assert data["nextPageToken"] is not None

        # Second page
        resp2 = client.get(
            f"/api/v1/ontology/objects/Target?pageSize=3&pageToken={data['nextPageToken']}"
        )
        data2 = resp2.json()
        assert len(data2["data"]) == 3
        assert data2["nextPageToken"] is not None

    def test_list_targets_property_selection(self):
        t1 = _mock_target("unit-1")
        tracker = _mock_tracker(targets=[t1])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/v1/ontology/objects/Target?properties=name,alliance")
        assert resp.status_code == 200
        obj = resp.json()["data"][0]
        assert "name" in obj
        assert "alliance" in obj
        # Should NOT include unselected fields
        assert "heading" not in obj
        assert "speed" not in obj

    def test_list_empty_type(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/objects/Target")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []
        assert data["totalCount"] == 0

    def test_list_unknown_type(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/objects/FakeType")
        assert resp.status_code == 404

    def test_list_dossiers(self):
        store = _mock_dossier_store()
        d_id = store.create_dossier("Alice", entity_type="person", tags=["vip"])
        client = TestClient(_make_app(dossier_store=store))

        resp = client.get("/api/v1/ontology/objects/Dossier")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalCount"] >= 1
        assert any(d["name"] == "Alice" for d in data["data"])

    def test_list_ble_devices(self):
        ble = _mock_ble_store()
        ble.record_sighting("AA:BB:CC:DD:EE:FF", "Phone", -50, "node-1")
        client = TestClient(_make_app(ble_store=ble))

        resp = client.get("/api/v1/ontology/objects/BleDevice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalCount"] >= 1


# ---------------------------------------------------------------------------
# Get single object
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetObject:
    """GET /api/v1/ontology/objects/{type}/{pk}."""

    def test_get_target(self):
        t1 = _mock_target("unit-1")
        tracker = _mock_tracker(targets=[t1])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/v1/ontology/objects/Target/unit-1")
        assert resp.status_code == 200
        assert resp.json()["target_id"] == "unit-1"

    def test_get_target_not_found(self):
        tracker = _mock_tracker(targets=[])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/v1/ontology/objects/Target/nope")
        assert resp.status_code == 404

    def test_get_dossier(self):
        store = _mock_dossier_store()
        d_id = store.create_dossier("Bob", entity_type="person")
        client = TestClient(_make_app(dossier_store=store))

        resp = client.get(f"/api/v1/ontology/objects/Dossier/{d_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Bob"

    def test_get_dossier_not_found(self):
        store = _mock_dossier_store()
        client = TestClient(_make_app(dossier_store=store))

        resp = client.get("/api/v1/ontology/objects/Dossier/nonexistent-uuid")
        assert resp.status_code == 404

    def test_unknown_type_404(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/objects/FakeType/pk1")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSearch:
    """POST /api/v1/ontology/objects/{type}/search."""

    def test_search_eq_filter(self):
        t1 = _mock_target("unit-1", "friendly", name="Alpha")
        t2 = _mock_target("unit-2", "hostile", name="Bravo")
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {"field": "alliance", "eq": "hostile"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalCount"] == 1
        assert data["data"][0]["alliance"] == "hostile"

    def test_search_gt_filter(self):
        t1 = _mock_target("unit-1")
        t1.to_dict.return_value["speed"] = 5.0
        t2 = _mock_target("unit-2")
        t2.to_dict.return_value["speed"] = 0.0
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {"field": "speed", "gt": 1.0},
        })
        assert resp.status_code == 200
        assert resp.json()["totalCount"] == 1

    def test_search_lt_filter(self):
        t1 = _mock_target("unit-1")
        t1.to_dict.return_value["battery"] = 0.2
        t2 = _mock_target("unit-2")
        t2.to_dict.return_value["battery"] = 0.9
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {"field": "battery", "lt": 0.5},
        })
        assert resp.status_code == 200
        assert resp.json()["totalCount"] == 1

    def test_search_prefix_filter(self):
        t1 = _mock_target("unit-1", name="Alpha-1")
        t2 = _mock_target("unit-2", name="Bravo-2")
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {"field": "name", "prefix": "Alpha"},
        })
        assert resp.status_code == 200
        assert resp.json()["totalCount"] == 1

    def test_search_phrase_filter(self):
        t1 = _mock_target("unit-1", name="Alpha Recon")
        t2 = _mock_target("unit-2", name="Bravo Strike")
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {"field": "name", "phrase": "recon"},
        })
        assert resp.status_code == 200
        assert resp.json()["totalCount"] == 1

    def test_search_isnull_filter(self):
        t1 = _mock_target("unit-1")
        t1.to_dict.return_value["name"] = ""
        t2 = _mock_target("unit-2", name="Bravo")
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {"field": "name", "isNull": True},
        })
        assert resp.status_code == 200
        assert resp.json()["totalCount"] == 1

    def test_search_and_filter(self):
        t1 = _mock_target("unit-1", "friendly", asset_type="rover")
        t2 = _mock_target("unit-2", "hostile", asset_type="person")
        t3 = _mock_target("unit-3", "friendly", asset_type="drone")
        tracker = _mock_tracker(targets=[t1, t2, t3])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {
                "and": [
                    {"field": "alliance", "eq": "friendly"},
                    {"field": "asset_type", "eq": "rover"},
                ],
            },
        })
        assert resp.status_code == 200
        assert resp.json()["totalCount"] == 1

    def test_search_or_filter(self):
        t1 = _mock_target("unit-1", "friendly")
        t2 = _mock_target("unit-2", "hostile")
        t3 = _mock_target("unit-3", "unknown")
        tracker = _mock_tracker(targets=[t1, t2, t3])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {
                "or": [
                    {"field": "alliance", "eq": "friendly"},
                    {"field": "alliance", "eq": "hostile"},
                ],
            },
        })
        assert resp.status_code == 200
        assert resp.json()["totalCount"] == 2

    def test_search_not_filter(self):
        t1 = _mock_target("unit-1", "friendly")
        t2 = _mock_target("unit-2", "hostile")
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {
                "not": {"field": "alliance", "eq": "hostile"},
            },
        })
        assert resp.status_code == 200
        assert resp.json()["totalCount"] == 1

    def test_search_with_pagination(self):
        targets = [_mock_target(f"t-{i}", "hostile") for i in range(10)]
        tracker = _mock_tracker(targets=targets)
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "where": {"field": "alliance", "eq": "hostile"},
            "pageSize": 3,
        })
        data = resp.json()
        assert len(data["data"]) == 3
        assert data["totalCount"] == 10
        assert data["nextPageToken"] is not None

    def test_search_with_property_selection(self):
        t1 = _mock_target("unit-1")
        tracker = _mock_tracker(targets=[t1])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "properties": ["name", "alliance"],
        })
        data = resp.json()
        obj = data["data"][0]
        assert "name" in obj
        assert "alliance" in obj
        assert "heading" not in obj

    def test_search_unknown_type(self):
        client = TestClient(_make_app())
        resp = client.post("/api/v1/ontology/objects/Bogus/search", json={})
        assert resp.status_code == 404

    def test_search_no_filter_returns_all(self):
        t1 = _mock_target("t1")
        t2 = _mock_target("t2")
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={})
        assert resp.status_code == 200
        assert resp.json()["totalCount"] == 2

    def test_search_with_order_by(self):
        t1 = _mock_target("unit-a", name="Zulu")
        t2 = _mock_target("unit-b", name="Alpha")
        tracker = _mock_tracker(targets=[t1, t2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.post("/api/v1/ontology/objects/Target/search", json={
            "orderBy": "name",
        })
        data = resp.json()["data"]
        assert data[0]["name"] == "Alpha"
        assert data[1]["name"] == "Zulu"


# ---------------------------------------------------------------------------
# Link traversal
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLinkTraversal:
    """GET /api/v1/ontology/objects/{type}/{pk}/links/{linkType}."""

    def test_target_trail(self):
        t1 = _mock_target("unit-1")
        tracker = _mock_tracker(targets=[t1])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/v1/ontology/objects/Target/unit-1/links/trail")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalCount"] == 2
        assert len(data["data"]) == 2

    def test_dossier_signals(self):
        store = _mock_dossier_store()
        d_id = store.create_dossier("Test", entity_type="device")
        store.add_signal(d_id, "ble", "mac_sighting", {"mac": "AA:BB"})
        store.add_signal(d_id, "yolo", "visual_detection", {"class": "person"})
        client = TestClient(_make_app(dossier_store=store))

        resp = client.get(f"/api/v1/ontology/objects/Dossier/{d_id}/links/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalCount"] == 2

    def test_dossier_enrichments(self):
        store = _mock_dossier_store()
        d_id = store.create_dossier("Test")
        store.add_enrichment(d_id, "oui_lookup", "manufacturer", {"vendor": "Apple"})
        client = TestClient(_make_app(dossier_store=store))

        resp = client.get(f"/api/v1/ontology/objects/Dossier/{d_id}/links/enrichments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalCount"] == 1

    def test_ble_sightings(self):
        ble = _mock_ble_store()
        ble.record_sighting("AA:BB:CC:DD:EE:FF", "Phone", -45, "node-1")
        ble.record_sighting("AA:BB:CC:DD:EE:FF", "Phone", -55, "node-2")
        client = TestClient(_make_app(ble_store=ble))

        resp = client.get(
            "/api/v1/ontology/objects/BleDevice/AA:BB:CC:DD:EE:FF/links/sightings"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalCount"] == 2

    def test_unknown_link_type_404(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/objects/Target/t1/links/bogus")
        assert resp.status_code == 404

    def test_unknown_source_type_404(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v1/ontology/objects/FakeType/pk/links/something")
        assert resp.status_code == 404

    def test_link_pagination(self):
        ble = _mock_ble_store()
        for i in range(10):
            ble.record_sighting("AA:BB:CC:DD:EE:FF", "Phone", -40 - i, f"node-{i}")
        client = TestClient(_make_app(ble_store=ble))

        resp = client.get(
            "/api/v1/ontology/objects/BleDevice/AA:BB:CC:DD:EE:FF/links/sightings?pageSize=3"
        )
        data = resp.json()
        assert len(data["data"]) == 3
        assert data["totalCount"] == 10
        assert data["nextPageToken"] is not None


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestActions:
    """POST /api/v1/ontology/actions/{actionType}/apply."""

    def test_tag_dossier(self):
        store = _mock_dossier_store()
        d_id = store.create_dossier("Alice")
        client = TestClient(_make_app(dossier_store=store))

        resp = client.post("/api/v1/ontology/actions/tag-dossier/apply", json={
            "parameters": {"dossier_id": d_id, "tag": "suspect"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "suspect" in data["result"]["tags"]

    def test_note_dossier(self):
        store = _mock_dossier_store()
        d_id = store.create_dossier("Bob")
        client = TestClient(_make_app(dossier_store=store))

        resp = client.post("/api/v1/ontology/actions/note-dossier/apply", json={
            "parameters": {"dossier_id": d_id, "note": "Seen near perimeter"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "Seen near perimeter" in data["result"]["notes"]

    def test_set_threat_level(self):
        store = _mock_dossier_store()
        d_id = store.create_dossier("Charlie")
        client = TestClient(_make_app(dossier_store=store))

        resp = client.post("/api/v1/ontology/actions/set-threat-level/apply", json={
            "parameters": {"dossier_id": d_id, "level": "high"},
        })
        assert resp.status_code == 200
        assert resp.json()["result"]["threat_level"] == "high"

    def test_set_invalid_threat_level(self):
        store = _mock_dossier_store()
        d_id = store.create_dossier("Dave")
        client = TestClient(_make_app(dossier_store=store))

        resp = client.post("/api/v1/ontology/actions/set-threat-level/apply", json={
            "parameters": {"dossier_id": d_id, "level": "mega-danger"},
        })
        assert resp.status_code == 400

    def test_merge_dossiers(self):
        store = _mock_dossier_store()
        d1 = store.create_dossier("Primary", tags=["seen-lobby"])
        d2 = store.create_dossier("Secondary", tags=["seen-parking"])
        client = TestClient(_make_app(dossier_store=store))

        resp = client.post("/api/v1/ontology/actions/merge-dossiers/apply", json={
            "parameters": {"primary_id": d1, "secondary_id": d2},
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Verify secondary is gone
        assert store.get_dossier(d2) is None
        # Verify primary has merged tags
        merged = store.get_dossier(d1)
        assert "seen-lobby" in merged["tags"]
        assert "seen-parking" in merged["tags"]

    def test_unknown_action_404(self):
        client = TestClient(_make_app())
        resp = client.post("/api/v1/ontology/actions/nuke-everything/apply", json={
            "parameters": {},
        })
        assert resp.status_code == 404

    def test_missing_required_param(self):
        client = TestClient(_make_app())
        resp = client.post("/api/v1/ontology/actions/tag-dossier/apply", json={
            "parameters": {"dossier_id": "abc"},
            # Missing "tag"
        })
        assert resp.status_code == 400

    def test_dossier_not_found(self):
        store = _mock_dossier_store()
        client = TestClient(_make_app(dossier_store=store))

        resp = client.post("/api/v1/ontology/actions/tag-dossier/apply", json={
            "parameters": {"dossier_id": "nonexistent", "tag": "test"},
        })
        assert resp.status_code == 404

    def test_no_store_503(self):
        client = TestClient(_make_app())
        # Patch the store getter to return None
        with patch("app.routers.ontology._get_dossier_store", return_value=None):
            resp = client.post("/api/v1/ontology/actions/tag-dossier/apply", json={
                "parameters": {"dossier_id": "abc", "tag": "test"},
            })
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Cursor encoding roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCursorEncoding:
    """Cursor token encode/decode roundtrip."""

    def test_roundtrip(self):
        from app.routers.ontology import _encode_cursor, _decode_cursor
        assert _decode_cursor(_encode_cursor(0)) == 0
        assert _decode_cursor(_encode_cursor(25)) == 25
        assert _decode_cursor(_encode_cursor(100)) == 100

    def test_none_returns_zero(self):
        from app.routers.ontology import _decode_cursor
        assert _decode_cursor(None) == 0

    def test_invalid_returns_zero(self):
        from app.routers.ontology import _decode_cursor
        assert _decode_cursor("garbage") == 0
        assert _decode_cursor("") == 0
