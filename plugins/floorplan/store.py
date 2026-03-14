# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""In-memory store for floor plans, rooms, and indoor positions.

Persists floor plan metadata to JSON on disk.  Image files are stored
in data/floorplans/ alongside the metadata.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("floorplan-store")

# Default storage directory
_DEFAULT_DATA_DIR = Path("data/floorplans")


class FloorPlanStore:
    """Thread-safe in-memory store for floor plans with JSON persistence."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        # plan_id -> dict
        self._plans: dict[str, dict] = {}
        # WiFi fingerprints: fingerprint_id -> dict
        self._fingerprints: dict[str, dict] = {}
        # Indoor positions: target_id -> dict
        self._positions: dict[str, dict] = {}

        self._load()

    # -- Persistence -----------------------------------------------------------

    def _meta_path(self) -> Path:
        return self._data_dir / "floorplans.json"

    def _fingerprint_path(self) -> Path:
        return self._data_dir / "fingerprints.json"

    def _load(self) -> None:
        meta = self._meta_path()
        if meta.exists():
            try:
                data = json.loads(meta.read_text())
                self._plans = {p["plan_id"]: p for p in data.get("plans", [])}
                log.info("Loaded %d floor plans from %s", len(self._plans), meta)
            except Exception as exc:
                log.error("Failed to load floor plans: %s", exc)

        fp = self._fingerprint_path()
        if fp.exists():
            try:
                data = json.loads(fp.read_text())
                self._fingerprints = {
                    f["fingerprint_id"]: f for f in data.get("fingerprints", [])
                }
                log.info("Loaded %d WiFi fingerprints", len(self._fingerprints))
            except Exception as exc:
                log.error("Failed to load fingerprints: %s", exc)

    def _save(self) -> None:
        try:
            meta = self._meta_path()
            meta.write_text(json.dumps(
                {"plans": list(self._plans.values())},
                indent=2, default=str,
            ))
        except Exception as exc:
            log.error("Failed to save floor plans: %s", exc)

    def _save_fingerprints(self) -> None:
        try:
            fp = self._fingerprint_path()
            fp.write_text(json.dumps(
                {"fingerprints": list(self._fingerprints.values())},
                indent=2, default=str,
            ))
        except Exception as exc:
            log.error("Failed to save fingerprints: %s", exc)

    # -- Floor plan CRUD -------------------------------------------------------

    def create_plan(
        self,
        name: str,
        building: str = "",
        floor_level: int = 0,
        image_path: str = "",
        image_format: str = "png",
        image_width: int = 0,
        image_height: int = 0,
        bounds: Optional[dict] = None,
        anchors: Optional[list[dict]] = None,
        rooms: Optional[list[dict]] = None,
        opacity: float = 0.7,
        rotation: float = 0.0,
    ) -> dict:
        """Create a new floor plan and return its metadata."""
        plan_id = f"fp_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        plan = {
            "plan_id": plan_id,
            "name": name,
            "building": building,
            "floor_level": floor_level,
            "image_path": image_path,
            "image_format": image_format,
            "image_width": image_width,
            "image_height": image_height,
            "bounds": bounds,
            "anchors": anchors or [],
            "rooms": rooms or [],
            "status": "draft",
            "opacity": opacity,
            "rotation": rotation,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._plans[plan_id] = plan
            self._save()
        return plan

    def get_plan(self, plan_id: str) -> Optional[dict]:
        """Get a floor plan by ID."""
        with self._lock:
            return self._plans.get(plan_id)

    def list_plans(
        self,
        building: Optional[str] = None,
        floor_level: Optional[int] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """List floor plans, optionally filtered."""
        with self._lock:
            plans = list(self._plans.values())

        if building is not None:
            plans = [p for p in plans if p.get("building") == building]
        if floor_level is not None:
            plans = [p for p in plans if p.get("floor_level") == floor_level]
        if status is not None:
            plans = [p for p in plans if p.get("status") == status]

        return plans

    def update_plan(self, plan_id: str, updates: dict) -> Optional[dict]:
        """Update a floor plan's metadata."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return None
            # Don't allow changing plan_id
            updates.pop("plan_id", None)
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            plan.update(updates)
            self._save()
            return plan

    def delete_plan(self, plan_id: str) -> bool:
        """Delete a floor plan and its image file."""
        with self._lock:
            plan = self._plans.pop(plan_id, None)
            if plan is None:
                return False
            # Remove image file
            img = plan.get("image_path", "")
            if img:
                img_path = self._data_dir / img
                if img_path.exists():
                    try:
                        img_path.unlink()
                    except Exception as exc:
                        log.warning("Failed to remove image %s: %s", img_path, exc)
            self._save()
            return True

    # -- Room management -------------------------------------------------------

    def add_room(self, plan_id: str, room: dict) -> Optional[dict]:
        """Add a room to a floor plan."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return None
            if "room_id" not in room:
                room["room_id"] = f"room_{uuid.uuid4().hex[:8]}"
            plan.setdefault("rooms", []).append(room)
            plan["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
            return room

    def remove_room(self, plan_id: str, room_id: str) -> bool:
        """Remove a room from a floor plan."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return False
            rooms = plan.get("rooms", [])
            before = len(rooms)
            plan["rooms"] = [r for r in rooms if r.get("room_id") != room_id]
            if len(plan["rooms"]) == before:
                return False
            plan["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
            return True

    # -- Indoor positions ------------------------------------------------------

    def set_position(self, target_id: str, position: dict) -> None:
        """Set/update indoor position for a target."""
        position["target_id"] = target_id
        position["timestamp"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._positions[target_id] = position

    def get_position(self, target_id: str) -> Optional[dict]:
        """Get current indoor position for a target."""
        with self._lock:
            return self._positions.get(target_id)

    def get_all_positions(self) -> list[dict]:
        """Get all current indoor positions."""
        with self._lock:
            return list(self._positions.values())

    def clear_positions(self) -> int:
        """Clear all indoor positions. Returns count cleared."""
        with self._lock:
            count = len(self._positions)
            self._positions.clear()
            return count

    # -- WiFi fingerprints -----------------------------------------------------

    def add_fingerprint(self, fingerprint: dict) -> dict:
        """Add a WiFi RSSI fingerprint."""
        if "fingerprint_id" not in fingerprint:
            fingerprint["fingerprint_id"] = f"wfp_{uuid.uuid4().hex[:10]}"
        fingerprint.setdefault(
            "collected_at", datetime.now(timezone.utc).isoformat()
        )
        with self._lock:
            self._fingerprints[fingerprint["fingerprint_id"]] = fingerprint
            self._save_fingerprints()
        return fingerprint

    def get_fingerprints(
        self,
        plan_id: Optional[str] = None,
        room_id: Optional[str] = None,
    ) -> list[dict]:
        """Get WiFi fingerprints, optionally filtered."""
        with self._lock:
            fps = list(self._fingerprints.values())
        if plan_id is not None:
            fps = [f for f in fps if f.get("plan_id") == plan_id]
        if room_id is not None:
            fps = [f for f in fps if f.get("room_id") == room_id]
        return fps

    def clear_fingerprints(self, plan_id: Optional[str] = None) -> int:
        """Clear fingerprints, optionally for a specific plan."""
        with self._lock:
            if plan_id is None:
                count = len(self._fingerprints)
                self._fingerprints.clear()
            else:
                to_remove = [
                    fid for fid, f in self._fingerprints.items()
                    if f.get("plan_id") == plan_id
                ]
                count = len(to_remove)
                for fid in to_remove:
                    del self._fingerprints[fid]
            self._save_fingerprints()
            return count

    # -- Occupancy computation -------------------------------------------------

    def compute_occupancy(self, plan_id: str) -> Optional[dict]:
        """Compute building occupancy from current indoor positions.

        Returns a BuildingOccupancy-shaped dict or None if plan not found.
        """
        plan = self.get_plan(plan_id)
        if plan is None:
            return None

        rooms_def = plan.get("rooms", [])
        now = datetime.now(timezone.utc).isoformat()

        # Build room occupancy
        room_occupancies: dict[str, dict] = {}
        for r in rooms_def:
            rid = r["room_id"]
            room_occupancies[rid] = {
                "room_id": rid,
                "room_name": r.get("name", rid),
                "room_type": r.get("room_type", "other"),
                "floor_level": r.get("floor_level", plan.get("floor_level", 0)),
                "person_count": 0,
                "device_count": 0,
                "target_ids": [],
                "capacity": r.get("capacity"),
                "updated_at": now,
            }

        total_persons = 0
        total_devices = 0

        with self._lock:
            positions = [
                p for p in self._positions.values()
                if p.get("plan_id") == plan_id
            ]

        for pos in positions:
            rid = pos.get("room_id")
            tid = pos.get("target_id", "")

            if rid and rid in room_occupancies:
                occ = room_occupancies[rid]
                occ["target_ids"].append(tid)
                # Classify as person or device based on target_id prefix
                if tid.startswith("det_person"):
                    occ["person_count"] += 1
                    total_persons += 1
                else:
                    occ["device_count"] += 1
                    total_devices += 1

        return {
            "plan_id": plan_id,
            "building": plan.get("building", ""),
            "floor_level": plan.get("floor_level", 0),
            "total_persons": total_persons,
            "total_devices": total_devices,
            "rooms": list(room_occupancies.values()),
            "updated_at": now,
        }

    # -- Image storage path ----------------------------------------------------

    @property
    def image_dir(self) -> Path:
        """Directory for floor plan image files."""
        return self._data_dir
