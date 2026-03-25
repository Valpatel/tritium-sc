# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Ollama LLM status for system health dashboard.

Checks if Ollama is running, which models are loaded, and reports
GPU utilization where available. Integrated into the system health
panel alongside MQTT and Meshtastic status.

Endpoints:
    GET /api/health/ollama — Ollama service health and model inventory
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


def _check_ollama_local() -> dict:
    """Probe local LLM instances for health and model info.

    Checks llama-server (ports 8081-8083) first, then ollama (11434) as fallback.
    """
    import urllib.request
    import json

    result = {
        "status": "unreachable",
        "url": "http://localhost:8081",
        "backend": "unknown",
        "models": [],
        "model_count": 0,
        "gpu_available": False,
        "error": None,
    }

    # Check llama-server instances first (ports 8081-8083)
    for port in [8081, 8082, 8083]:
        try:
            req = urllib.request.Request(
                f"http://localhost:{port}/v1/models",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                models = data.get("data", [])
                if models or resp.status == 200:
                    result["status"] = "running"
                    result["backend"] = "llama-server"
                    result["url"] = f"http://localhost:{port}"
                    result["model_count"] = result.get("model_count", 0) + len(models)
                    for m in models:
                        result["models"].append({
                            "name": m.get("id", m.get("model", "")),
                            "size": 0,
                            "port": port,
                            "backend": "llama-server",
                        })
        except Exception:
            continue

    # Also check ollama (legacy, port 11434)
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            models = data.get("models", [])
            if result["status"] != "running":
                result["status"] = "running"
                result["backend"] = "ollama"
                result["url"] = "http://localhost:11434"
            result["model_count"] += len(models)
            result["models"].extend([
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "modified_at": m.get("modified_at", ""),
                    "family": m.get("details", {}).get("family", ""),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                    "quantization": m.get("details", {}).get("quantization_level", ""),
                    "backend": "ollama",
                }
                for m in models
            ])
    except Exception as e:
        if result["status"] != "running":
            result["error"] = str(e)
            return result

    # Check for running models via ollama /api/ps (if ollama available)
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/ps",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            running = data.get("models", [])
            result["running_models"] = [
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "size_vram": m.get("size_vram", 0),
                    "expires_at": m.get("expires_at", ""),
                }
                for m in running
            ]
            result["loaded_count"] = len(running)

            # If any model has VRAM usage, GPU is available
            if any(m.get("size_vram", 0) > 0 for m in running):
                result["gpu_available"] = True
    except Exception:
        result["running_models"] = []
        result["loaded_count"] = 0

    return result


def _check_ollama_fleet() -> dict | None:
    """Check OllamaFleet for multi-host status."""
    try:
        from tritium_lib.inference.fleet import OllamaFleet
        fleet = OllamaFleet(auto_discover=False)
        if fleet.count == 0:
            return None

        hosts = []
        for h in fleet.hosts:
            host_info = {
                "name": h.name,
                "url": h.url,
                "reachable": h.reachable,
                "model_count": len(h.models) if hasattr(h, "models") else 0,
            }
            if hasattr(h, "models"):
                host_info["models"] = list(h.models)
            hosts.append(host_info)

        return {
            "host_count": len(hosts),
            "hosts": hosts,
        }
    except Exception:
        return None


@router.get("/ollama")
async def ollama_health():
    """Check Ollama LLM service health.

    Returns:
    - Connection status (running/unreachable)
    - Available models with size and quantization info
    - Currently loaded models (in GPU/RAM)
    - GPU availability
    - OllamaFleet multi-host status (if configured)

    Designed for the system health dashboard panel.
    """
    local = _check_ollama_local()
    fleet = _check_ollama_fleet()

    result = {
        "local": local,
        "overall_status": local["status"],
    }

    if fleet is not None:
        result["fleet"] = fleet

    return result
