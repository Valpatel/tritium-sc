# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""System inventory endpoint — complete system awareness in one call.

Returns panel count, plugin count, route count, model count, store count,
HAL count (from fleet), and test count (from test reporting).

Endpoints:
    GET /api/system/inventory — Full system inventory
"""
from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

# Resolve src/ directory (file is at src/app/routers/system_inventory.py)
_SRC_DIR = Path(__file__).resolve().parents[2]  # src/
_PROJECT_DIR = _SRC_DIR.parent  # tritium-sc/


def _count_panel_files() -> int:
    """Count JS panel files in the frontend panels directory."""
    panels_dir = _SRC_DIR / "frontend" / "js" / "command" / "panels"
    if not panels_dir.is_dir():
        return 0
    return len([f for f in panels_dir.iterdir() if f.suffix == ".js"])


def _count_router_files() -> int:
    """Count router files in the routers directory."""
    routers_dir = Path(__file__).resolve().parent
    if not routers_dir.is_dir():
        return 0
    return len([
        f for f in routers_dir.iterdir()
        if f.suffix == ".py" and f.name != "__init__.py"
    ])


def _count_plugin_dirs() -> int:
    """Count plugin directories under engine/plugins."""
    plugins_dir = _SRC_DIR / "engine" / "plugins"
    if not plugins_dir.is_dir():
        return 0
    return len([
        f for f in plugins_dir.iterdir()
        if f.is_dir() and not f.name.startswith("_")
    ])


def _count_test_files() -> int:
    """Count test files across the tests/ directory."""
    tests_dir = _PROJECT_DIR / "tests"
    if not tests_dir.is_dir():
        return 0
    count = 0
    for root, dirs, files in os.walk(tests_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in files:
            if f.startswith("test_") and (f.endswith(".py") or f.endswith(".js")):
                count += 1
    return count


def _count_models() -> dict[str, int]:
    """Count data model classes."""
    counts: dict[str, int] = {}

    # SQLAlchemy models
    try:
        from app import models as app_models
        sa_models = [
            name for name in dir(app_models)
            if isinstance(getattr(app_models, name, None), type)
            and hasattr(getattr(app_models, name), "__tablename__")
        ]
        counts["sqlalchemy"] = len(sa_models)
    except Exception:
        counts["sqlalchemy"] = 0

    # Pydantic models in config
    try:
        from app.config import settings
        counts["config_settings"] = 1
    except Exception:
        counts["config_settings"] = 0

    return counts


def _count_unit_types() -> int:
    """Count registered unit types."""
    try:
        from engine.units import get_all_unit_types
        return len(get_all_unit_types())
    except Exception:
        # Fallback: count files in units directory
        units_dir = _SRC_DIR / "engine" / "units"
        if not units_dir.is_dir():
            return 0
        return len([
            f for f in units_dir.iterdir()
            if f.suffix == ".py" and f.name not in ("__init__.py", "base.py", "registry.py")
        ])


def _get_fleet_info(request: Request) -> dict[str, Any]:
    """Get fleet/HAL info if available."""
    info: dict[str, Any] = {"device_count": 0, "online_count": 0}
    try:
        # Check if fleet registry is in app state
        fleet = getattr(request.app.state, "fleet_registry", None)
        if fleet:
            devices = fleet.get_all_devices() if hasattr(fleet, "get_all_devices") else []
            info["device_count"] = len(devices)
            info["online_count"] = sum(1 for d in devices if getattr(d, "online", False))
    except Exception:
        pass

    # Check MQTT bridge status
    try:
        mqtt = getattr(request.app.state, "mqtt_bridge", None)
        info["mqtt_connected"] = mqtt is not None and getattr(mqtt, "connected", False)
    except Exception:
        info["mqtt_connected"] = False

    return info


def _get_intelligence_info() -> dict[str, Any]:
    """Get ML model and training data info."""
    info: dict[str, Any] = {}
    try:
        from engine.intelligence.correlation_learner import get_correlation_learner
        learner = get_correlation_learner()
        info["correlation_model"] = {
            "trained": learner.is_trained,
            "accuracy": learner.accuracy,
            "training_count": learner.training_count,
        }
    except Exception:
        info["correlation_model"] = {"trained": False, "accuracy": 0.0, "training_count": 0}

    try:
        from engine.intelligence.training_store import get_training_store
        store = get_training_store()
        info["training_data"] = store.get_stats()
    except Exception:
        info["training_data"] = {}

    return info


@router.get("/inventory")
async def system_inventory(request: Request):
    """Return complete system inventory for full system awareness.

    Single endpoint that returns panel count, plugin count, route count,
    model count, store count, HAL count, test count, and intelligence
    model status.
    """
    # Route count from the app
    route_count = len(request.app.routes)

    # Panel files
    panel_count = _count_panel_files()

    # Router files
    router_count = _count_router_files()

    # Plugin infrastructure
    plugin_count = _count_plugin_dirs()

    # Test files
    test_count = _count_test_files()

    # Data models
    model_counts = _count_models()

    # Unit types
    unit_type_count = _count_unit_types()

    # Fleet/HAL info
    fleet_info = _get_fleet_info(request)

    # Intelligence/ML status
    intelligence = _get_intelligence_info()

    # Tracker info
    tracker_info: dict[str, Any] = {"target_count": 0}
    try:
        tracker = getattr(request.app.state, "target_tracker", None)
        if tracker:
            targets = tracker.get_all()
            tracker_info["target_count"] = len(targets)
            sources = {}
            for t in targets:
                src = getattr(t, "source", "unknown")
                sources[src] = sources.get(src, 0) + 1
            tracker_info["by_source"] = sources
    except Exception:
        pass

    # Simulation status
    sim_info: dict[str, Any] = {"enabled": False}
    try:
        sim = getattr(request.app.state, "simulation_engine", None)
        if sim:
            sim_info["enabled"] = True
            sim_info["running"] = getattr(sim, "running", False)
            targets = getattr(sim, "targets", {})
            sim_info["sim_target_count"] = len(targets) if isinstance(targets, dict) else 0
    except Exception:
        pass

    return {
        "panels": {
            "file_count": panel_count,
            "note": "Panel JS files in frontend/js/command/panels/",
        },
        "routers": {
            "file_count": router_count,
            "registered_routes": route_count,
        },
        "plugins": {
            "directory_count": plugin_count,
        },
        "models": model_counts,
        "unit_types": unit_type_count,
        "tests": {
            "file_count": test_count,
        },
        "fleet": fleet_info,
        "intelligence": intelligence,
        "tracker": tracker_info,
        "simulation": sim_info,
    }
