# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""System self-test endpoint — quick health checks on all subsystems.

    GET /api/system/self-test  — run checks, return pass/fail per subsystem
"""

from __future__ import annotations

import time
import traceback
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/system", tags=["system"])


def _check_subsystem(name: str, check_fn) -> dict[str, Any]:
    """Run a single subsystem check and return result."""
    start = time.monotonic()
    try:
        result = check_fn()
        elapsed = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": name,
            "status": "pass",
            "elapsed_ms": elapsed,
            "details": result if isinstance(result, (dict, str)) else None,
        }
    except Exception as exc:
        elapsed = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": name,
            "status": "fail",
            "elapsed_ms": elapsed,
            "error": str(exc),
        }


@router.get("/self-test")
async def self_test(request: Request):
    """Run quick health checks on all subsystems.

    Returns pass/fail for each subsystem and an overall status.
    Checks: EventBus, TargetTracker, TargetCorrelator, PluginManager,
    SimulationEngine, MQTTBridge, DemoController, stores.
    """
    start = time.monotonic()
    results: list[dict[str, Any]] = []

    # 1. EventBus
    def check_event_bus():
        amy = getattr(request.app.state, "amy", None)
        if amy is not None:
            bus = getattr(amy, "event_bus", None)
            if bus is not None:
                # Quick pub/sub test
                received = []
                sub = bus.subscribe()
                bus.publish("self_test", {"ping": True})
                import queue
                try:
                    msg = sub.get(timeout=0.5)
                    received.append(msg)
                except queue.Empty:
                    pass
                bus.unsubscribe(sub)
                return {"subscribers": len(getattr(bus, "_subscribers", [])), "pub_sub_ok": len(received) > 0}
        # Headless — try to import and instantiate
        from engine.comms.event_bus import EventBus
        bus = EventBus()
        return {"status": "importable", "note": "no live instance"}

    results.append(_check_subsystem("event_bus", check_event_bus))

    # 2. TargetTracker
    def check_tracker():
        amy = getattr(request.app.state, "amy", None)
        if amy is not None:
            tracker = getattr(amy, "target_tracker", None)
            if tracker is not None:
                targets = tracker.get_all()
                return {"target_count": len(targets)}
        from tritium_lib.tracking.target_tracker import TargetTracker
        return {"status": "importable", "note": "no live instance"}

    results.append(_check_subsystem("target_tracker", check_tracker))

    # 3. TargetCorrelator
    def check_correlator():
        amy = getattr(request.app.state, "amy", None)
        if amy is not None:
            correlator = getattr(amy, "target_correlator", None)
            if correlator is not None:
                stats = {}
                if hasattr(correlator, "correlation_count"):
                    stats["correlations"] = correlator.correlation_count
                return stats or {"status": "running"}
        from engine.tactical.target_correlator import TargetCorrelator
        return {"status": "importable", "note": "no live instance"}

    results.append(_check_subsystem("target_correlator", check_correlator))

    # 4. PluginManager
    def check_plugins():
        pm = getattr(request.app.state, "plugin_manager", None)
        if pm is not None:
            plugins = pm.list_plugins()
            running = sum(1 for p in plugins if p.get("status") == "running")
            return {
                "total": len(plugins),
                "running": running,
                "names": [p.get("name", "?") for p in plugins],
            }
        return {"status": "not_initialized"}

    results.append(_check_subsystem("plugin_manager", check_plugins))

    # 5. SimulationEngine
    def check_simulation():
        amy = getattr(request.app.state, "amy", None)
        engine = None
        if amy is not None:
            engine = getattr(amy, "simulation_engine", None)
        if engine is None:
            engine = getattr(request.app.state, "simulation_engine", None)
        if engine is not None:
            targets = engine.get_targets()
            return {
                "running": getattr(engine, "_running", False),
                "target_count": len(targets),
                "tick_rate": getattr(engine, "tick_rate", None),
            }
        return {"status": "disabled"}

    results.append(_check_subsystem("simulation_engine", check_simulation))

    # 6. MQTT Bridge
    def check_mqtt():
        mqtt = getattr(request.app.state, "mqtt_bridge", None)
        if mqtt is not None:
            connected = getattr(mqtt, "connected", False)
            return {"connected": connected}
        return {"status": "disabled"}

    results.append(_check_subsystem("mqtt_bridge", check_mqtt))

    # 7. DemoController
    def check_demo():
        demo = getattr(request.app.state, "demo_controller", None)
        if demo is not None:
            active = getattr(demo, "active", False)
            return {"active": active}
        return {"status": "not_initialized"}

    results.append(_check_subsystem("demo_controller", check_demo))

    # 8. Heatmap Engine
    def check_heatmap():
        from app.routers.heatmap import get_engine
        engine = get_engine()
        return {"status": "running", "type": type(engine).__name__}

    results.append(_check_subsystem("heatmap_engine", check_heatmap))

    # 9. Geofence Engine
    def check_geofence():
        from app.routers.geofence import get_engine
        engine = get_engine()
        zones = engine.list_zones()
        return {"zone_count": len(zones)}

    results.append(_check_subsystem("geofence_engine", check_geofence))

    # 10. Notification Manager
    def check_notifications():
        from app.routers.notifications import get_manager
        mgr = get_manager()
        return {"unread": mgr.count_unread()}

    results.append(_check_subsystem("notification_manager", check_notifications))

    # 11. Key imports (sanity check)
    def check_imports():
        import engine.simulation
        import engine.comms.event_bus
        import tritium_lib.tracking.target_tracker
        import app.config
        return {"all_imports": "ok"}

    results.append(_check_subsystem("core_imports", check_imports))

    # 12. Amy Commander
    def check_amy():
        amy = getattr(request.app.state, "amy", None)
        if amy is not None:
            return {
                "state": getattr(amy, "_state", "?"),
                "mode": getattr(amy, "mode", "?"),
                "running": getattr(amy, "_running", False),
            }
        return {"status": "disabled"}

    results.append(_check_subsystem("amy_commander", check_amy))

    # Aggregate
    total_elapsed = round((time.monotonic() - start) * 1000, 1)
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    overall = "pass" if failed == 0 else "degraded" if failed <= 2 else "fail"

    return {
        "overall": overall,
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "elapsed_ms": total_elapsed,
        "subsystems": results,
        "timestamp": time.time(),
    }
