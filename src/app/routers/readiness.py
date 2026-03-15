# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Operational readiness checklist endpoint.

Returns a per-subsystem checklist of what is configured and working:
MQTT broker, demo mode, authentication, plugins loaded, stores
initialized, Meshtastic bridge, Ollama availability.

Each item is rated green/yellow/red:
  - green:  fully operational
  - yellow: available but degraded or not active
  - red:    unavailable or misconfigured
"""
from __future__ import annotations

import socket
import time
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


def _check_item(
    name: str,
    status: str,
    detail: str = "",
    hint: str = "",
) -> dict[str, Any]:
    """Build a single checklist item."""
    item: dict[str, Any] = {
        "name": name,
        "status": status,
        "detail": detail,
    }
    if hint:
        item["hint"] = hint
    return item


def _build_checklist(request: Request) -> list[dict[str, Any]]:
    """Evaluate every subsystem and return ordered checklist."""
    items: list[dict[str, Any]] = []

    # 1. MQTT broker reachability
    from app.config import settings as _settings

    mqtt_host = _settings.mqtt_host or "localhost"
    mqtt_port = _settings.mqtt_port or 1883
    try:
        s = socket.create_connection((mqtt_host, mqtt_port), timeout=2)
        s.close()
        mqtt_status = "green"
        mqtt_detail = f"Broker reachable at {mqtt_host}:{mqtt_port}"
    except (ConnectionRefusedError, OSError):
        mqtt_status = "red"
        mqtt_detail = f"Cannot connect to {mqtt_host}:{mqtt_port}"

    mqtt_bridge = getattr(request.app.state, "mqtt_bridge", None)
    if mqtt_bridge is not None and getattr(mqtt_bridge, "connected", False):
        mqtt_detail += "; bridge connected"
    elif mqtt_bridge is not None:
        mqtt_status = "yellow"
        mqtt_detail += "; bridge created but not connected"

    items.append(_check_item("mqtt_broker", mqtt_status, mqtt_detail,
                             hint="sudo apt install mosquitto && sudo systemctl start mosquitto"
                             if mqtt_status == "red" else ""))

    # 2. Demo mode
    demo = getattr(request.app.state, "demo_controller", None)
    if demo is not None:
        active = getattr(demo, "active", False)
        items.append(_check_item(
            "demo_mode",
            "green" if active else "yellow",
            "Active" if active else "Available but not started",
            hint="POST /api/demo/start to activate" if not active else "",
        ))
    else:
        items.append(_check_item("demo_mode", "red", "Demo controller not initialized"))

    # 3. Authentication
    auth_enabled = getattr(_settings, "auth_enabled", False)
    items.append(_check_item(
        "authentication",
        "green" if auth_enabled else "yellow",
        "Enabled" if auth_enabled else "Disabled (open access)",
    ))

    # 4. Plugins loaded
    pm = getattr(request.app.state, "plugin_manager", None)
    if pm is not None:
        plugins = pm.list_plugins()
        running = sum(1 for p in plugins if p.get("status") == "running")
        total = len(plugins)
        if total == 0:
            p_status = "red"
        elif running < total:
            p_status = "yellow"
        else:
            p_status = "green"
        items.append(_check_item(
            "plugins",
            p_status,
            f"{running}/{total} running",
        ))
    else:
        items.append(_check_item("plugins", "red", "Plugin manager not initialized"))

    # 5. Stores initialized
    stores_ok = True
    store_details: list[str] = []
    for store_name in ("target_tracker", "training_store", "dossier_manager"):
        obj = getattr(request.app.state, store_name, None)
        if obj is not None:
            store_details.append(f"{store_name}: ok")
        else:
            store_details.append(f"{store_name}: missing")
            stores_ok = False
    items.append(_check_item(
        "stores",
        "green" if stores_ok else "yellow",
        "; ".join(store_details),
    ))

    # 6. Meshtastic bridge
    mesh = getattr(request.app.state, "meshtastic_bridge", None)
    if mesh is not None:
        items.append(_check_item("meshtastic_bridge", "green", "Connected"))
    else:
        items.append(_check_item(
            "meshtastic_bridge", "yellow",
            "Not connected (no Meshtastic hardware)",
        ))

    # 7. Ollama availability
    try:
        import urllib.request

        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            items.append(_check_item("ollama", "green", "Running at localhost:11434"))
    except Exception:
        items.append(_check_item(
            "ollama", "yellow",
            "Not reachable at localhost:11434",
            hint="curl -fsSL https://ollama.com/install.sh | sh && ollama serve",
        ))

    # 8. Amy AI commander
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        items.append(_check_item("amy_commander", "green", "Running"))
    else:
        items.append(_check_item("amy_commander", "yellow", "Disabled"))

    # 9. Database
    try:
        from app.database import async_session
        items.append(_check_item("database", "green", "SQLite configured"))
    except Exception:
        items.append(_check_item("database", "red", "Database not configured"))

    return items


@router.get("/api/system/readiness")
async def readiness_checklist(request: Request):
    """Operational readiness checklist.

    Returns a per-subsystem checklist with green/yellow/red status
    for every critical component.
    """
    items = _build_checklist(request)

    # Overall readiness
    statuses = [i["status"] for i in items]
    if "red" in statuses:
        overall = "not_ready"
    elif "yellow" in statuses:
        overall = "partially_ready"
    else:
        overall = "ready"

    green_count = statuses.count("green")
    total = len(statuses)

    return {
        "overall": overall,
        "score": f"{green_count}/{total}",
        "items": items,
        "checked_at": time.time(),
    }
