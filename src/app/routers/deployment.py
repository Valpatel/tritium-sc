# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Deployment status and service management API.

Provides endpoints to query and control Tritium services: MQTT broker,
Meshtastic bridge, Ollama, edge fleet, and the SC server itself.
The deployment status panel consumes these endpoints.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from app.auth import require_auth

router = APIRouter(prefix="/api/deployment", tags=["deployment"], dependencies=[Depends(require_auth)])

# Track bridge processes we started
_managed_processes: dict[str, dict] = {}

SC_DIR = Path(__file__).resolve().parent.parent.parent.parent  # tritium-sc root


def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """TCP probe a port."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


def _find_pid(name_pattern: str) -> int | None:
    """Find PID of a process matching a pattern (via pgrep)."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", name_pattern],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            return int(pids[0])
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass
    return None


def _process_uptime(pid: int) -> float:
    """Get process uptime in seconds from /proc."""
    try:
        stat_path = f"/proc/{pid}/stat"
        if os.path.exists(stat_path):
            with open(stat_path) as f:
                fields = f.read().split()
            # Field 21 is starttime in clock ticks
            starttime_ticks = int(fields[21])
            with open("/proc/uptime") as f:
                system_uptime = float(f.read().split()[0])
            hz = os.sysconf("SC_CLK_TCK")
            process_start = starttime_ticks / hz
            return system_uptime - process_start
    except (OSError, IndexError, ValueError):
        pass
    return 0.0


def _service_status_mosquitto(settings: Any) -> dict:
    """Check mosquitto MQTT broker status."""
    host = getattr(settings, "mqtt_host", "localhost") or "localhost"
    port = getattr(settings, "mqtt_port", 1883) or 1883
    reachable = _check_port(host, port)
    pid = _find_pid("mosquitto")
    installed = shutil.which("mosquitto") is not None

    # Check if systemctl is available for start/stop
    has_systemctl = shutil.which("systemctl") is not None

    return {
        "name": "mqtt_broker",
        "display_name": "MQTT Broker (Mosquitto)",
        "state": "running" if reachable else "stopped",
        "pid": pid,
        "uptime_s": _process_uptime(pid) if pid else 0.0,
        "port": port,
        "installed": installed,
        "can_start": installed and not reachable,
        "can_stop": reachable and pid is not None,
        "start_command": "systemctl start mosquitto" if has_systemctl else "mosquitto -d",
        "stop_command": "systemctl stop mosquitto" if has_systemctl else "kill",
        "error_message": "" if reachable else (
            "Not installed" if not installed else f"Not reachable at {host}:{port}"
        ),
    }


def _service_status_meshtastic_bridge() -> dict:
    """Check Meshtastic bridge script status."""
    bridge_script = SC_DIR / "scripts" / "meshtastic-bridge.py"
    pid = _find_pid("meshtastic-bridge.py")
    managed = _managed_processes.get("meshtastic_bridge", {})
    managed_pid = managed.get("pid")

    # If we have a managed PID, check if it's still alive
    if managed_pid:
        try:
            os.kill(managed_pid, 0)
            pid = managed_pid
        except OSError:
            # Process died
            _managed_processes.pop("meshtastic_bridge", None)
            if pid == managed_pid:
                pid = None

    running = pid is not None
    return {
        "name": "meshtastic_bridge",
        "display_name": "Meshtastic Bridge",
        "state": "running" if running else "stopped",
        "pid": pid,
        "uptime_s": _process_uptime(pid) if pid else 0.0,
        "installed": bridge_script.exists(),
        "can_start": bridge_script.exists() and not running,
        "can_stop": running,
        "start_command": f"python3 {bridge_script}",
        "stop_command": "kill",
        "started_at": managed.get("started_at"),
    }


def _service_status_ollama() -> dict:
    """Check LLM service status (llama-server preferred, ollama legacy)."""
    # Check llama-server first
    llama_reachable = _check_port("localhost", 8081)
    llama_pid = _find_pid("llama-server")
    # Fallback to ollama
    ollama_reachable = _check_port("localhost", 11434)
    ollama_pid = _find_pid("ollama serve")

    if llama_reachable:
        return {
            "name": "llm",
            "display_name": "llama-server (LLM)",
            "state": "running",
            "pid": llama_pid,
            "uptime_s": _process_uptime(llama_pid) if llama_pid else 0.0,
            "port": 8081,
            "installed": True,
            "can_start": False,
            "can_stop": llama_pid is not None,
            "start_command": "llama-server -m <model> --port 8081",
            "stop_command": "kill",
        }

    installed = shutil.which("ollama") is not None
    return {
        "name": "llm",
        "display_name": "ollama (LLM, legacy)",
        "state": "running" if ollama_reachable else "stopped",
        "pid": ollama_pid,
        "uptime_s": _process_uptime(ollama_pid) if ollama_pid else 0.0,
        "port": 11434,
        "installed": installed,
        "can_start": installed and not ollama_reachable,
        "can_stop": ollama_reachable and ollama_pid is not None,
        "start_command": "ollama serve",
        "stop_command": "kill",
    }


def _service_status_sc_server() -> dict:
    """Check SC server status (always running if this endpoint is hit)."""
    pid = os.getpid()
    return {
        "name": "sc_server",
        "display_name": "Command Center (SC)",
        "state": "running",
        "pid": pid,
        "uptime_s": _process_uptime(pid),
        "port": 8000,
        "installed": True,
        "can_start": False,  # Already running
        "can_stop": False,   # Don't allow self-termination via API
    }


def _service_status_fleet_server() -> dict:
    """Check edge fleet server status."""
    reachable = _check_port("localhost", 8080)
    pid = _find_pid("tritium-edge/server")

    fleet_dir = SC_DIR.parent / "tritium-edge" / "server"
    installed = fleet_dir.exists()

    return {
        "name": "edge_fleet_server",
        "display_name": "Edge Fleet Server",
        "state": "running" if reachable else "stopped",
        "pid": pid,
        "uptime_s": _process_uptime(pid) if pid else 0.0,
        "port": 8080,
        "installed": installed,
        "can_start": installed and not reachable,
        "can_stop": reachable and pid is not None,
    }


@router.get("/services")
async def list_services(request: Request):
    """List all Tritium services with their current status."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config import settings as _settings
        settings = _settings

    services = [
        _service_status_sc_server(),
        _service_status_mosquitto(settings),
        _service_status_meshtastic_bridge(),
        _service_status_ollama(),
        _service_status_fleet_server(),
    ]

    running_count = sum(1 for s in services if s["state"] == "running")
    installed_count = sum(1 for s in services if s.get("installed", False))

    return {
        "services": services,
        "total": len(services),
        "running": running_count,
        "installed": installed_count,
        "healthy": running_count >= 2,  # At least SC + MQTT
    }


class ServiceAction(BaseModel):
    """Request body for service start/stop."""
    service: str


@router.post("/services/start")
async def start_service(action: ServiceAction, request: Request):
    """Start a stopped service."""
    name = action.service
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config import settings as _settings
        settings = _settings

    if name == "mqtt_broker":
        status = _service_status_mosquitto(settings)
        if status["state"] == "running":
            return {"ok": True, "message": "MQTT broker already running"}
        if not status["installed"]:
            raise HTTPException(400, "Mosquitto not installed. Run: sudo apt install mosquitto")
        # Try systemctl first, fall back to direct
        has_systemctl = shutil.which("systemctl") is not None
        try:
            if has_systemctl:
                subprocess.run(
                    ["systemctl", "start", "mosquitto"],
                    capture_output=True, text=True, timeout=10
                )
            else:
                subprocess.Popen(
                    ["mosquitto", "-d"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            # Verify
            time.sleep(1)
            if _check_port(
                getattr(settings, "mqtt_host", "localhost") or "localhost",
                getattr(settings, "mqtt_port", 1883) or 1883
            ):
                return {"ok": True, "message": "MQTT broker started"}
            return {"ok": False, "message": "MQTT broker start command sent but port not responding yet"}
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"Failed to start mosquitto: {e}")
            raise HTTPException(500, "Service operation failed")

    elif name == "meshtastic_bridge":
        status = _service_status_meshtastic_bridge()
        if status["state"] == "running":
            return {"ok": True, "message": "Meshtastic bridge already running", "pid": status["pid"]}
        bridge_script = SC_DIR / "scripts" / "meshtastic-bridge.py"
        if not bridge_script.exists():
            logger.error(f"Bridge script not found at {bridge_script}")
            raise HTTPException(400, "Bridge script not found")
        try:
            venv_python = SC_DIR / ".venv" / "bin" / "python3"
            python = str(venv_python) if venv_python.exists() else "python3"
            proc = subprocess.Popen(
                [python, str(bridge_script)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                cwd=str(SC_DIR),
                start_new_session=True,
            )
            _managed_processes["meshtastic_bridge"] = {
                "pid": proc.pid,
                "started_at": time.time(),
            }
            return {"ok": True, "message": "Meshtastic bridge started", "pid": proc.pid}
        except (FileNotFoundError, OSError) as e:
            logger.error(f"Failed to start bridge: {e}")
            raise HTTPException(500, "Service operation failed")

    elif name == "ollama":
        status = _service_status_ollama()
        if status["state"] == "running":
            return {"ok": True, "message": "Ollama already running"}
        if not status["installed"]:
            raise HTTPException(400, "Ollama not installed. See https://ollama.ai")
        try:
            proc = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _managed_processes["ollama"] = {
                "pid": proc.pid,
                "started_at": time.time(),
            }
            return {"ok": True, "message": "Ollama started", "pid": proc.pid}
        except (FileNotFoundError, OSError) as e:
            logger.error(f"Failed to start Ollama: {e}")
            raise HTTPException(500, "Service operation failed")

    else:
        raise HTTPException(400, "Unknown service")


@router.post("/services/stop")
async def stop_service(action: ServiceAction):
    """Stop a running service."""
    name = action.service

    if name == "sc_server":
        raise HTTPException(400, "Cannot stop the SC server from its own API")

    if name == "mqtt_broker":
        has_systemctl = shutil.which("systemctl") is not None
        try:
            if has_systemctl:
                subprocess.run(
                    ["systemctl", "stop", "mosquitto"],
                    capture_output=True, text=True, timeout=10
                )
            else:
                pid = _find_pid("mosquitto")
                if pid:
                    os.kill(pid, signal.SIGTERM)
            return {"ok": True, "message": "MQTT broker stop requested"}
        except (subprocess.TimeoutExpired, ProcessLookupError, OSError) as e:
            raise HTTPException(500, f"Failed to stop mosquitto: {e}")

    elif name == "meshtastic_bridge":
        managed = _managed_processes.pop("meshtastic_bridge", None)
        pid = managed.get("pid") if managed else _find_pid("meshtastic-bridge.py")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                return {"ok": True, "message": "Meshtastic bridge stopped"}
            except ProcessLookupError:
                return {"ok": True, "message": "Bridge was already stopped"}
        return {"ok": False, "message": "No bridge process found"}

    elif name == "ollama":
        managed = _managed_processes.pop("ollama", None)
        pid = managed.get("pid") if managed else _find_pid("ollama serve")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                return {"ok": True, "message": "Ollama stopped"}
            except ProcessLookupError:
                return {"ok": True, "message": "Ollama was already stopped"}
        return {"ok": False, "message": "No Ollama process found"}

    else:
        raise HTTPException(400, "Unknown service")


@router.get("/requirements")
async def system_requirements():
    """Return system requirements for running Tritium."""
    import platform
    import sys

    return {
        "python": {
            "required": "3.12+",
            "current": sys.version,
            "ok": sys.version_info >= (3, 12),
        },
        "system_packages": {
            pkg: shutil.which(pkg) is not None
            for pkg in ["mosquitto", "git", "ffmpeg", "ollama"]
        },
        "platform": platform.platform(),
        "hostname": platform.node(),
    }
