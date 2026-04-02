# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Ontology-driven REST API — enterprise platform-style typed object access.

Exposes the Tritium data model as a typed ontology with entity types, schemas,
objects, compositional search, link traversal, and typed actions.  Backed by
the existing TargetTracker, DossierStore, and BleStore.

Routes
------
GET  /api/v1/ontology/types                          — all entity types
GET  /api/v1/ontology/types/{type}                   — single type schema
GET  /api/v1/ontology/types/{type}/links              — outgoing link types
GET  /api/v1/ontology/objects/{type}                  — list objects (cursor)
GET  /api/v1/ontology/objects/{type}/{pk}              — single object
POST /api/v1/ontology/objects/{type}/search            — compositional filter
GET  /api/v1/ontology/objects/{type}/{pk}/links/{lt}  — traverse relationship
POST /api/v1/ontology/actions/{actionType}/apply       — execute typed action
"""

from __future__ import annotations

import base64
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ontology", tags=["ontology"])


# ---------------------------------------------------------------------------
# Type system — defines the ontology schema
# ---------------------------------------------------------------------------

_PROPERTY_TYPES = {
    "string": {"type": "string"},
    "double": {"type": "double"},
    "integer": {"type": "integer"},
    "boolean": {"type": "boolean"},
    "timestamp": {"type": "timestamp"},
    "geopoint": {"type": "geopoint"},
    "array[string]": {"type": "array", "items": "string"},
    "map[string,string]": {"type": "map", "keyType": "string", "valueType": "string"},
}

# Entity type definitions: apiName -> schema
ENTITY_TYPES: dict[str, dict[str, Any]] = {
    "Target": {
        "apiName": "Target",
        "displayName": "Tracked Target",
        "description": "A real-time tracked entity in the battlespace — simulation units, YOLO detections, BLE devices.",
        "primaryKey": "target_id",
        "properties": {
            "target_id": {"type": "string", "description": "Unique target identifier"},
            "name": {"type": "string", "description": "Display name"},
            "alliance": {"type": "string", "description": "Alliance: friendly, hostile, unknown"},
            "asset_type": {"type": "string", "description": "Asset class: rover, drone, person, vehicle, ble_device"},
            "position_x": {"type": "double", "description": "X coordinate in local space"},
            "position_y": {"type": "double", "description": "Y coordinate in local space"},
            "lat": {"type": "double", "description": "Latitude (WGS84)"},
            "lng": {"type": "double", "description": "Longitude (WGS84)"},
            "heading": {"type": "double", "description": "Heading in degrees"},
            "speed": {"type": "double", "description": "Speed in local units/s"},
            "battery": {"type": "double", "description": "Battery level 0.0-1.0"},
            "source": {"type": "string", "description": "Data source: simulation, yolo, ble, manual"},
            "status": {"type": "string", "description": "Target status: active, destroyed, etc."},
            "position_source": {"type": "string", "description": "How position was determined"},
            "position_confidence": {"type": "double", "description": "Position confidence 0.0-1.0"},
            "last_seen": {"type": "double", "description": "Monotonic timestamp of last update"},
        },
        "links": {
            "dossier": {
                "targetType": "Dossier",
                "description": "Persistent intelligence dossier linked to this target",
                "cardinality": "MANY_TO_ONE",
            },
            "trail": {
                "targetType": "TrailPoint",
                "description": "Historical position trail",
                "cardinality": "ONE_TO_MANY",
            },
        },
    },
    "Dossier": {
        "apiName": "Dossier",
        "displayName": "Target Dossier",
        "description": "Persistent identity record accumulating evidence from multiple sensors over time.",
        "primaryKey": "dossier_id",
        "properties": {
            "dossier_id": {"type": "string", "description": "Unique dossier UUID"},
            "name": {"type": "string", "description": "Display name or 'Unknown'"},
            "entity_type": {"type": "string", "description": "Entity class: person, vehicle, device, animal, unknown"},
            "confidence": {"type": "double", "description": "Identity confidence 0.0-1.0"},
            "alliance": {"type": "string", "description": "Alliance classification"},
            "threat_level": {"type": "string", "description": "Threat level: none, low, medium, high, critical"},
            "first_seen": {"type": "double", "description": "Unix timestamp of first observation"},
            "last_seen": {"type": "double", "description": "Unix timestamp of most recent observation"},
            "identifiers": {"type": "map[string,string]", "description": "Key-value identifier map (mac, ssid, etc.)"},
            "tags": {"type": "array[string]", "description": "User-applied tags"},
            "notes": {"type": "array[string]", "description": "Analyst notes"},
            "signal_count": {"type": "integer", "description": "Number of contributing signals"},
        },
        "links": {
            "signals": {
                "targetType": "Signal",
                "description": "Contributing detection signals",
                "cardinality": "ONE_TO_MANY",
            },
            "enrichments": {
                "targetType": "Enrichment",
                "description": "External intelligence enrichments",
                "cardinality": "ONE_TO_MANY",
            },
            "targets": {
                "targetType": "Target",
                "description": "Active tracked targets linked to this dossier",
                "cardinality": "ONE_TO_MANY",
            },
        },
    },
    "BleDevice": {
        "apiName": "BleDevice",
        "displayName": "BLE Device",
        "description": "A Bluetooth Low Energy device discovered by fleet sensor nodes.",
        "primaryKey": "mac",
        "properties": {
            "mac": {"type": "string", "description": "MAC address"},
            "name": {"type": "string", "description": "Advertised device name"},
            "is_known": {"type": "boolean", "description": "Whether the device is in the known-devices list"},
            "last_rssi": {"type": "integer", "description": "Most recent RSSI reading"},
            "strongest_rssi": {"type": "integer", "description": "Strongest RSSI ever recorded"},
            "node_count": {"type": "integer", "description": "Number of sensor nodes that see this device"},
            "last_seen": {"type": "string", "description": "ISO timestamp of last sighting"},
            "first_seen": {"type": "string", "description": "ISO timestamp of first sighting"},
            "total_sightings": {"type": "integer", "description": "Total sighting count"},
        },
        "links": {
            "dossier": {
                "targetType": "Dossier",
                "description": "Associated target dossier (if correlated)",
                "cardinality": "MANY_TO_ONE",
            },
            "sightings": {
                "targetType": "BleSighting",
                "description": "Per-node sighting history",
                "cardinality": "ONE_TO_MANY",
            },
        },
    },
    "Device": {
        "apiName": "Device",
        "displayName": "Fleet Device",
        "description": "A Tritium fleet sensor node (ESP32, robot, camera, etc.).",
        "primaryKey": "device_id",
        "properties": {
            "device_id": {"type": "string", "description": "Unique device identifier"},
            "device_name": {"type": "string", "description": "Human-readable name"},
            "board": {"type": "string", "description": "Hardware board type"},
            "family": {"type": "string", "description": "Device family (esp32, rpi, etc.)"},
            "firmware_version": {"type": "string", "description": "Running firmware version"},
            "ip_address": {"type": "string", "description": "Current IP address"},
            "status": {"type": "string", "description": "Connection status: online, offline, updating, error"},
            "capabilities": {"type": "array[string]", "description": "Device capabilities list"},
            "last_seen": {"type": "string", "description": "ISO timestamp of last heartbeat"},
        },
        "links": {
            "targets": {
                "targetType": "Target",
                "description": "Targets detected by this device",
                "cardinality": "ONE_TO_MANY",
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Action type definitions
# ---------------------------------------------------------------------------

ACTION_TYPES: dict[str, dict[str, Any]] = {
    "tag-dossier": {
        "apiName": "tag-dossier",
        "displayName": "Tag Dossier",
        "description": "Add a tag to a target dossier",
        "parameters": {
            "dossier_id": {"type": "string", "required": True, "description": "Target dossier ID"},
            "tag": {"type": "string", "required": True, "description": "Tag to add"},
        },
    },
    "note-dossier": {
        "apiName": "note-dossier",
        "displayName": "Add Note to Dossier",
        "description": "Add an analyst note to a target dossier",
        "parameters": {
            "dossier_id": {"type": "string", "required": True, "description": "Target dossier ID"},
            "note": {"type": "string", "required": True, "description": "Note text"},
        },
    },
    "set-threat-level": {
        "apiName": "set-threat-level",
        "displayName": "Set Threat Level",
        "description": "Update the threat level of a dossier",
        "parameters": {
            "dossier_id": {"type": "string", "required": True, "description": "Target dossier ID"},
            "level": {"type": "string", "required": True, "description": "Threat level: none, low, medium, high, critical"},
        },
    },
    "merge-dossiers": {
        "apiName": "merge-dossiers",
        "displayName": "Merge Dossiers",
        "description": "Merge two dossiers into one (absorbs secondary into primary)",
        "parameters": {
            "primary_id": {"type": "string", "required": True, "description": "Primary dossier to keep"},
            "secondary_id": {"type": "string", "required": True, "description": "Secondary dossier to absorb"},
        },
    },
}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class FilterValue(BaseModel):
    """A single filter condition."""
    field: str
    eq: Optional[Any] = None
    gt: Optional[float] = None
    lt: Optional[float] = None
    prefix: Optional[str] = None
    phrase: Optional[str] = None
    isNull: Optional[bool] = None


class SearchRequest(BaseModel):
    """Compositional filter search request."""
    where: Optional[dict[str, Any]] = None  # and/or/not + filter conditions
    pageSize: int = Field(default=25, ge=1, le=500)
    pageToken: Optional[str] = None
    properties: Optional[list[str]] = None
    orderBy: Optional[str] = None


class ActionRequest(BaseModel):
    """Action execution request."""
    parameters: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Data access helpers
# ---------------------------------------------------------------------------

def _get_tracker(request: Request):
    """Get TargetTracker from Amy or app state."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        tracker = getattr(amy, "target_tracker", None)
        if tracker is not None:
            return tracker
    return None


def _get_dossier_store(request: Request):
    """Get DossierStore from DossierManager or lazy singleton."""
    mgr = getattr(request.app.state, "dossier_manager", None)
    if mgr is not None:
        store = getattr(mgr, "store", None)
        if store is not None:
            return store

    # Fallback: try lazy singleton
    try:
        from app.routers.dossiers import _get_store
        return _get_store()
    except Exception:
        return None


def _get_ble_store(request: Request):
    """Get BleStore from app state."""
    return getattr(request.app.state, "ble_store", None)


# ---------------------------------------------------------------------------
# Cursor encoding
# ---------------------------------------------------------------------------

def _encode_cursor(offset: int) -> str:
    """Encode a pagination offset as an opaque cursor token."""
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


def _decode_cursor(token: str | None) -> int:
    """Decode cursor token back to offset.  Returns 0 for None/invalid."""
    if not token:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        if decoded.startswith("o:"):
            return int(decoded[2:])
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# Object loaders — translate store data into ontology objects
# ---------------------------------------------------------------------------

def _load_targets(request: Request) -> list[dict]:
    """Load all tracked targets as ontology objects."""
    tracker = _get_tracker(request)
    if tracker is None:
        return []
    targets = tracker.get_all()
    result = []
    for t in targets:
        d = t.to_dict(history=tracker.history)
        obj = {
            "target_id": d["target_id"],
            "name": d.get("name", ""),
            "alliance": d.get("alliance", "unknown"),
            "asset_type": d.get("asset_type", "unknown"),
            "position_x": d.get("position", {}).get("x", 0.0),
            "position_y": d.get("position", {}).get("y", 0.0),
            "lat": d.get("lat", 0.0),
            "lng": d.get("lng", 0.0),
            "heading": d.get("heading", 0.0),
            "speed": d.get("speed", 0.0),
            "battery": d.get("battery", 1.0),
            "source": d.get("source", "unknown"),
            "status": d.get("status", "active"),
            "position_source": d.get("position_source", "unknown"),
            "position_confidence": d.get("position_confidence", 0.0),
            "last_seen": d.get("last_seen", 0.0),
        }
        result.append(obj)
    return result


def _load_dossiers(request: Request) -> list[dict]:
    """Load dossiers as ontology objects."""
    store = _get_dossier_store(request)
    if store is None:
        return []
    rows = store.get_recent(limit=1000)
    return rows


def _load_ble_devices(request: Request) -> list[dict]:
    """Load BLE devices as ontology objects."""
    ble_store = _get_ble_store(request)
    if ble_store is None:
        return []
    return ble_store.get_active_devices(timeout_minutes=60)


def _load_devices(request: Request) -> list[dict]:
    """Load fleet devices as ontology objects."""
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        cached = getattr(bridge, "cached_nodes", None)
        if cached:
            return cached if isinstance(cached, list) else list(cached.values())
    return []


_TYPE_LOADERS = {
    "Target": _load_targets,
    "Dossier": _load_dossiers,
    "BleDevice": _load_ble_devices,
    "Device": _load_devices,
}


def _get_pk_field(type_name: str) -> str:
    """Return the primary key field name for an entity type."""
    schema = ENTITY_TYPES.get(type_name)
    return schema["primaryKey"] if schema else "id"


# ---------------------------------------------------------------------------
# Filter engine
# ---------------------------------------------------------------------------

def _match_filter(obj: dict, condition: dict) -> bool:
    """Evaluate a single filter condition against an object."""
    field = condition.get("field")
    if not field:
        return True

    value = obj.get(field)

    if "eq" in condition:
        return value == condition["eq"]
    if "gt" in condition:
        try:
            return float(value) > float(condition["gt"])
        except (TypeError, ValueError):
            return False
    if "lt" in condition:
        try:
            return float(value) < float(condition["lt"])
        except (TypeError, ValueError):
            return False
    if "prefix" in condition:
        return isinstance(value, str) and value.startswith(condition["prefix"])
    if "phrase" in condition:
        return isinstance(value, str) and condition["phrase"].lower() in value.lower()
    if "isNull" in condition:
        if condition["isNull"]:
            return value is None or value == ""
        else:
            return value is not None and value != ""

    return True


def _apply_where(objects: list[dict], where: dict | None) -> list[dict]:
    """Apply compositional filter (and/or/not) to a list of objects."""
    if where is None:
        return objects

    if "and" in where:
        result = objects
        for sub in where["and"]:
            result = _apply_where(result, sub)
        return result

    if "or" in where:
        seen_ids = set()
        result = []
        for sub in where["or"]:
            for obj in _apply_where(objects, sub):
                obj_id = id(obj)
                if obj_id not in seen_ids:
                    seen_ids.add(obj_id)
                    result.append(obj)
        return result

    if "not" in where:
        excluded = set(id(o) for o in _apply_where(objects, where["not"]))
        return [o for o in objects if id(o) not in excluded]

    # Leaf filter condition
    return [o for o in objects if _match_filter(o, where)]


def _select_properties(obj: dict, properties: list[str] | None) -> dict:
    """Project object to requested properties (plus primary key)."""
    if properties is None:
        return obj
    result = {}
    for k in properties:
        if k in obj:
            result[k] = obj[k]
    return result


# ---------------------------------------------------------------------------
# Type endpoints
# ---------------------------------------------------------------------------

@router.get("/schema")
async def get_schema():
    """Return the full Tritium ontology as a JSON schema document.

    External tools (ATAK plugins, federation peers, AI agents) can
    consume this endpoint to understand all entity types, relationships,
    actions, and their properties without reading source code.
    """
    # Build entity type schemas
    entity_schemas = {}
    for name, schema in ENTITY_TYPES.items():
        entity_schemas[name] = {
            "apiName": schema["apiName"],
            "displayName": schema["displayName"],
            "description": schema["description"],
            "primaryKey": schema["primaryKey"],
            "properties": schema["properties"],
            "links": schema.get("links", {}),
        }

    # Build action type schemas
    action_schemas = {}
    for name, action in ACTION_TYPES.items():
        action_schemas[name] = {
            "apiName": action["apiName"],
            "displayName": action["displayName"],
            "description": action["description"],
            "parameters": action["parameters"],
        }

    # Event types from tritium-lib if available
    event_types = []
    try:
        from tritium_lib.models.event_schema import list_event_types
        event_types = list_event_types()
    except ImportError:
        pass

    # Ontology from tritium-lib if available
    lib_ontology = None
    try:
        from tritium_lib.ontology.schema import TRITIUM_ONTOLOGY
        lib_ontology = {
            "version": TRITIUM_ONTOLOGY.version,
            "entity_type_count": len(TRITIUM_ONTOLOGY.entity_types),
            "relationship_type_count": len(TRITIUM_ONTOLOGY.relationship_types),
            "interface_count": len(TRITIUM_ONTOLOGY.interfaces),
            "entity_types": {
                k: v.model_dump() for k, v in TRITIUM_ONTOLOGY.entity_types.items()
            },
            "relationship_types": {
                k: v.model_dump() for k, v in TRITIUM_ONTOLOGY.relationship_types.items()
            },
            "interfaces": {
                k: v.model_dump() for k, v in TRITIUM_ONTOLOGY.interfaces.items()
            },
        }
    except (ImportError, Exception):
        pass

    return {
        "schema_version": "1.0.0",
        "system": "tritium",
        "description": "Tritium unified operating picture ontology — all entity types, relationships, actions, and event schemas",
        "entity_types": entity_schemas,
        "action_types": action_schemas,
        "event_types": event_types,
        "lib_ontology": lib_ontology,
        "endpoints": {
            "list_types": "GET /api/v1/ontology/types",
            "get_type": "GET /api/v1/ontology/types/{type}",
            "get_type_links": "GET /api/v1/ontology/types/{type}/links",
            "list_objects": "GET /api/v1/ontology/objects/{type}",
            "get_object": "GET /api/v1/ontology/objects/{type}/{pk}",
            "search_objects": "POST /api/v1/ontology/objects/{type}/search",
            "traverse_links": "GET /api/v1/ontology/objects/{type}/{pk}/links/{linkType}",
            "apply_action": "POST /api/v1/ontology/actions/{actionType}/apply",
        },
    }


@router.get("/types")
async def list_types():
    """List all entity types with their schemas."""
    types = []
    for name, schema in ENTITY_TYPES.items():
        types.append({
            "apiName": schema["apiName"],
            "displayName": schema["displayName"],
            "description": schema["description"],
            "primaryKey": schema["primaryKey"],
            "propertyCount": len(schema["properties"]),
            "linkCount": len(schema.get("links", {})),
        })
    return {"types": types}


@router.get("/types/{type_name}")
async def get_type(type_name: str):
    """Get single type schema with full property and link definitions."""
    schema = ENTITY_TYPES.get(type_name)
    if schema is None:
        raise HTTPException(status_code=404, detail=f"Unknown type: {type_name}")
    return schema


@router.get("/types/{type_name}/links")
async def get_type_links(type_name: str):
    """Get outgoing relationship types for an entity type."""
    schema = ENTITY_TYPES.get(type_name)
    if schema is None:
        raise HTTPException(status_code=404, detail=f"Unknown type: {type_name}")
    links = schema.get("links", {})
    return {
        "type": type_name,
        "links": [
            {"apiName": name, **defn}
            for name, defn in links.items()
        ],
    }


# ---------------------------------------------------------------------------
# Object endpoints
# ---------------------------------------------------------------------------

@router.get("/objects/{type_name}")
async def list_objects(
    request: Request,
    type_name: str,
    pageSize: int = Query(25, ge=1, le=500),
    pageToken: Optional[str] = Query(None),
    properties: Optional[str] = Query(None, description="Comma-separated field names"),
):
    """List objects of a type with cursor-based pagination."""
    if type_name not in ENTITY_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown type: {type_name}")

    loader = _TYPE_LOADERS.get(type_name)
    if loader is None:
        return {"data": [], "nextPageToken": None, "totalCount": 0}

    all_objects = loader(request)
    offset = _decode_cursor(pageToken)
    page = all_objects[offset:offset + pageSize]

    prop_list = properties.split(",") if properties else None
    projected = [_select_properties(o, prop_list) for o in page]

    next_token = None
    if offset + pageSize < len(all_objects):
        next_token = _encode_cursor(offset + pageSize)

    return {
        "data": projected,
        "nextPageToken": next_token,
        "totalCount": len(all_objects),
    }


@router.get("/objects/{type_name}/{pk}")
async def get_object(request: Request, type_name: str, pk: str):
    """Get a single object by type and primary key."""
    if type_name not in ENTITY_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown type: {type_name}")

    pk_field = _get_pk_field(type_name)

    # Specialized lookups for better performance
    if type_name == "Dossier":
        store = _get_dossier_store(request)
        if store is not None:
            dossier = store.get_dossier(pk)
            if dossier is not None:
                return dossier
        raise HTTPException(status_code=404, detail=f"Dossier {pk} not found")

    # Generic loader fallback
    loader = _TYPE_LOADERS.get(type_name)
    if loader is None:
        raise HTTPException(status_code=404, detail=f"No data source for type: {type_name}")

    objects = loader(request)
    for obj in objects:
        if str(obj.get(pk_field, "")) == pk:
            return obj

    raise HTTPException(status_code=404, detail=f"{type_name} with {pk_field}={pk} not found")


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------

@router.post("/objects/{type_name}/search")
async def search_objects(request: Request, type_name: str, body: SearchRequest):
    """Compositional filter search with cursor-based pagination."""
    if type_name not in ENTITY_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown type: {type_name}")

    loader = _TYPE_LOADERS.get(type_name)
    if loader is None:
        return {"data": [], "nextPageToken": None, "totalCount": 0}

    all_objects = loader(request)

    # Apply compositional filter
    filtered = _apply_where(all_objects, body.where)

    # Apply ordering
    if body.orderBy:
        desc = body.orderBy.startswith("-")
        field = body.orderBy.lstrip("-")
        try:
            filtered.sort(key=lambda o: o.get(field, ""), reverse=desc)
        except TypeError:
            pass

    # Paginate
    offset = _decode_cursor(body.pageToken)
    page = filtered[offset:offset + body.pageSize]

    projected = [_select_properties(o, body.properties) for o in page]

    next_token = None
    if offset + body.pageSize < len(filtered):
        next_token = _encode_cursor(offset + body.pageSize)

    return {
        "data": projected,
        "nextPageToken": next_token,
        "totalCount": len(filtered),
    }


# ---------------------------------------------------------------------------
# Link traversal
# ---------------------------------------------------------------------------

@router.get("/objects/{type_name}/{pk}/links/{link_type}")
async def get_links(
    request: Request,
    type_name: str,
    pk: str,
    link_type: str,
    pageSize: int = Query(25, ge=1, le=500),
    pageToken: Optional[str] = Query(None),
):
    """Traverse a relationship from a source object."""
    schema = ENTITY_TYPES.get(type_name)
    if schema is None:
        raise HTTPException(status_code=404, detail=f"Unknown type: {type_name}")

    link_def = schema.get("links", {}).get(link_type)
    if link_def is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown link type '{link_type}' on {type_name}",
        )

    offset = _decode_cursor(pageToken)
    related: list[dict] = []

    # Target -> dossier: find dossier whose identifiers contain a matching signal
    if type_name == "Target" and link_type == "dossier":
        store = _get_dossier_store(request)
        if store is not None:
            dossier = store.find_by_identifier("target_id", pk)
            if dossier is not None:
                related = [dossier]

    # Target -> trail: position history from tracker
    elif type_name == "Target" and link_type == "trail":
        tracker = _get_tracker(request)
        if tracker is not None:
            trail = tracker.history.get_trail_dicts(pk, max_points=100)
            related = trail

    # Dossier -> signals: get signals from store
    elif type_name == "Dossier" and link_type == "signals":
        store = _get_dossier_store(request)
        if store is not None:
            dossier = store.get_dossier(pk)
            if dossier is not None:
                related = dossier.get("signals", [])

    # Dossier -> enrichments
    elif type_name == "Dossier" and link_type == "enrichments":
        store = _get_dossier_store(request)
        if store is not None:
            dossier = store.get_dossier(pk)
            if dossier is not None:
                related = dossier.get("enrichments", [])

    # Dossier -> targets: find tracker targets matching dossier identifiers
    elif type_name == "Dossier" and link_type == "targets":
        tracker = _get_tracker(request)
        store = _get_dossier_store(request)
        if tracker is not None and store is not None:
            dossier = store.get_dossier(pk)
            if dossier is not None:
                ids = dossier.get("identifiers", {})
                all_targets = tracker.get_all()
                for t in all_targets:
                    # Match by target_id or MAC in identifiers
                    if t.target_id in ids.values():
                        related.append(t.to_dict())

    # BleDevice -> sightings: sighting history from BLE store
    elif type_name == "BleDevice" and link_type == "sightings":
        ble_store = _get_ble_store(request)
        if ble_store is not None:
            related = ble_store.get_device_history(pk)

    # BleDevice -> dossier
    elif type_name == "BleDevice" and link_type == "dossier":
        store = _get_dossier_store(request)
        if store is not None:
            dossier = store.find_by_identifier("mac", pk)
            if dossier is not None:
                related = [dossier]

    # Paginate
    page = related[offset:offset + pageSize]
    next_token = None
    if offset + pageSize < len(related):
        next_token = _encode_cursor(offset + pageSize)

    return {
        "data": page,
        "nextPageToken": next_token,
        "totalCount": len(related),
    }


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

@router.post("/actions/{action_type}/apply")
async def apply_action(request: Request, action_type: str, body: ActionRequest):
    """Execute a typed action."""
    action_def = ACTION_TYPES.get(action_type)
    if action_def is None:
        raise HTTPException(status_code=404, detail=f"Unknown action type: {action_type}")

    params = body.parameters

    # Validate required parameters
    for pname, pdef in action_def["parameters"].items():
        if pdef.get("required") and pname not in params:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required parameter: {pname}",
            )

    store = _get_dossier_store(request)

    if action_type == "tag-dossier":
        if store is None:
            raise HTTPException(status_code=503, detail="Dossier store unavailable")
        dossier = store.get_dossier(params["dossier_id"])
        if dossier is None:
            raise HTTPException(status_code=404, detail="Dossier not found")
        tags = dossier.get("tags", [])
        tag = params["tag"]
        if tag not in tags:
            tags.append(tag)
            store._update_json_field(params["dossier_id"], "tags", tags)
        return {"ok": True, "action": action_type, "result": {"tags": tags}}

    elif action_type == "note-dossier":
        if store is None:
            raise HTTPException(status_code=503, detail="Dossier store unavailable")
        dossier = store.get_dossier(params["dossier_id"])
        if dossier is None:
            raise HTTPException(status_code=404, detail="Dossier not found")
        notes = dossier.get("notes", [])
        notes.append(params["note"])
        store._update_json_field(params["dossier_id"], "notes", notes)
        return {"ok": True, "action": action_type, "result": {"notes": notes}}

    elif action_type == "set-threat-level":
        if store is None:
            raise HTTPException(status_code=503, detail="Dossier store unavailable")
        valid_levels = ("none", "low", "medium", "high", "critical")
        level = params["level"]
        if level not in valid_levels:
            raise HTTPException(status_code=400, detail=f"Invalid threat level: {level}")
        ok = store.update_threat_level(params["dossier_id"], level)
        if not ok:
            raise HTTPException(status_code=404, detail="Dossier not found")
        return {"ok": True, "action": action_type, "result": {"threat_level": level}}

    elif action_type == "merge-dossiers":
        if store is None:
            raise HTTPException(status_code=503, detail="Dossier store unavailable")
        ok = store.merge_dossiers(params["primary_id"], params["secondary_id"])
        if not ok:
            raise HTTPException(status_code=404, detail="One or both dossiers not found")
        return {
            "ok": True,
            "action": action_type,
            "result": {
                "primary_id": params["primary_id"],
                "merged_from": params["secondary_id"],
            },
        }

    raise HTTPException(status_code=501, detail=f"Action not implemented: {action_type}")
