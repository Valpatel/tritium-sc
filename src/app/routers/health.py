# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""System health endpoint.

Returns system status, subsystem health, plugin health, uptime, and
test baselines. Used by Docker HEALTHCHECK and monitoring systems.
"""

import socket
import time
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])

# Set at import time; updated to real value when lifespan starts.
_start_time: float = time.time()


def reset_start_time() -> None:
    """Reset the start time (called during lifespan startup)."""
    global _start_time
    _start_time = time.time()


def _subsystem_status(request: Request) -> dict[str, str]:
    """Check health of core subsystems attached to app.state."""
    checks: dict[str, str] = {}

    # Amy AI Commander
    amy = getattr(request.app.state, "amy", None)
    checks["amy"] = "running" if amy is not None else "disabled"

    # MQTT bridge — check bridge state AND broker reachability
    mqtt = getattr(request.app.state, "mqtt_bridge", None)
    if mqtt is not None:
        connected = getattr(mqtt, "connected", False)
        checks["mqtt"] = "connected" if connected else "disconnected"
    else:
        checks["mqtt"] = "disabled"

    # MQTT broker reachability (TCP probe regardless of bridge state)
    from app.config import settings as _settings
    mqtt_host = _settings.mqtt_host or "localhost"
    mqtt_port = _settings.mqtt_port or 1883
    try:
        _s = socket.create_connection((mqtt_host, mqtt_port), timeout=2)
        _s.close()
        checks["mqtt_broker"] = "reachable"
    except (ConnectionRefusedError, OSError):
        checks["mqtt_broker"] = "unreachable"
        checks["mqtt_broker_hint"] = (
            f"MQTT broker not running at {mqtt_host}:{mqtt_port}. "
            f"Install and start: sudo apt install mosquitto && sudo systemctl start mosquitto"
        )

    # Simulation engine
    sim = getattr(request.app.state, "simulation_engine", None)
    if sim is None and amy is not None:
        sim = getattr(amy, "simulation_engine", None)
    checks["simulation"] = "running" if sim is not None else "disabled"

    # Plugin manager
    pm = getattr(request.app.state, "plugin_manager", None)
    if pm is not None:
        plugins = pm.list_plugins()
        running = sum(1 for p in plugins if p.get("running", False))
        checks["plugins"] = f"{running}/{len(plugins)} running"
    else:
        checks["plugins"] = "disabled"

    # Demo mode
    demo = getattr(request.app.state, "demo_controller", None)
    if demo is not None and getattr(demo, "active", False):
        checks["demo"] = "active"

    # Fleet bridge
    fleet = getattr(request.app.state, "fleet_bridge", None)
    if fleet is not None:
        checks["fleet_bridge"] = "connected"

    # Meshtastic bridge
    mesh = getattr(request.app.state, "meshtastic_bridge", None)
    if mesh is not None:
        checks["meshtastic"] = "connected"

    # Ollama LLM service
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            checks["ollama"] = "running"
    except Exception:
        checks["ollama"] = "unreachable"

    return checks


def _plugin_health(request: Request) -> dict[str, Any]:
    """Detailed plugin health from PluginManager."""
    pm = getattr(request.app.state, "plugin_manager", None)
    if pm is None:
        return {}
    try:
        return pm.health_check()
    except Exception:
        return {"error": "health check failed"}


def _plugin_discovery_report(request: Request) -> dict[str, Any]:
    """Plugin auto-discovery report from boot."""
    report = getattr(request.app.state, "plugin_discovery_report", None)
    if report is None:
        return {}
    return report


def _rl_training_metrics() -> dict[str, Any]:
    """Collect RL training data metrics from TrainingStore and CorrelationLearner."""
    metrics: dict[str, Any] = {}

    # Training store stats
    try:
        from engine.intelligence.training_store import get_training_store
        store = get_training_store()
        stats = store.get_stats()
        metrics["correlation_decisions"] = stats.get("correlation", {}).get("total", 0)
        metrics["correlation_confirmed"] = stats.get("correlation", {}).get("confirmed", 0)
        metrics["classification_decisions"] = stats.get("classification", {}).get("total", 0)
        metrics["classification_corrected"] = stats.get("classification", {}).get("corrected", 0)
        metrics["feedback_entries"] = stats.get("feedback", {}).get("total", 0)
        metrics["feedback_accuracy"] = stats.get("feedback", {}).get("accuracy", 0.0)
    except Exception:
        metrics["store"] = "unavailable"

    # Learner model status
    try:
        from engine.intelligence.correlation_learner import get_correlation_learner
        learner = get_correlation_learner()
        learner_stats = learner.get_status()
        metrics["model_trained"] = learner_stats.get("trained", False)
        metrics["model_accuracy"] = learner_stats.get("accuracy", 0.0)
        metrics["model_training_count"] = learner_stats.get("training_count", 0)
        metrics["last_retrain"] = learner_stats.get("last_trained", None)
    except Exception:
        metrics["model"] = "unavailable"

    return metrics


@router.get("/api/health")
async def health_check(request: Request):
    """Comprehensive health check endpoint.

    Returns system status, subsystem health, plugin health, uptime,
    and test baselines. Used by Docker HEALTHCHECK, load balancers,
    and monitoring dashboards.
    """
    uptime_seconds = time.time() - _start_time
    subsystems = _subsystem_status(request)
    plugins = _plugin_health(request)

    # Overall status: degraded if any critical subsystem is down
    # but still responding (the endpoint itself proves the app is alive)
    all_healthy = True
    for key, val in subsystems.items():
        if val in ("disconnected", "unreachable"):
            all_healthy = False
            break

    # Plugin auto-discovery report (boot-time scan results)
    discovery = _plugin_discovery_report(request)

    # RL training data metrics
    rl_metrics = _rl_training_metrics()

    return {
        "status": "healthy" if all_healthy else "degraded",
        "version": "0.1.0",
        "system": "TRITIUM-SC",
        "uptime_seconds": round(uptime_seconds, 1),
        "subsystems": subsystems,
        "plugins": plugins,
        "plugin_discovery": discovery,
        "rl_training": rl_metrics,
        "test_baselines": {
            "tritium_lib": 1822,
            "tritium_sc_pytest": 7800,
            "tritium_sc_js": 281,
            "tritium_sc_test_files": 672,
            "tritium_lib_test_files": 89,
            "tritium_edge_warnings": 0,
        },
    }
