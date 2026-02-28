# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Amy — AI Commander for TRITIUM-SC.

Factory function auto-detects available hardware and creates Amy
with the appropriate sensor nodes.
"""

from __future__ import annotations

import sqlite3

__version__ = "0.1.0"


def _discover_ip_cameras(db_path: str) -> dict:
    """Discover IP cameras from SQLite Camera table.

    Reads all enabled cameras with an rtsp_url and creates
    IPCameraNode instances.  Uses synchronous sqlite3 so it
    can be called during app startup (before the async loop).

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        dict mapping node_id -> IPCameraNode
    """
    from engine.nodes.ip_camera import IPCameraNode

    nodes = {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT channel, name, rtsp_url FROM cameras WHERE enabled = 1 AND rtsp_url IS NOT NULL"
        ).fetchall()
        conn.close()
    except Exception:
        return nodes

    for row in rows:
        channel = row["channel"]
        node_id = f"ip-cam-{channel}"
        nodes[node_id] = IPCameraNode(
            node_id=node_id,
            name=row["name"],
            rtsp_url=row["rtsp_url"],
        )

    return nodes


def create_amy(settings=None, simulation_engine=None) -> "Commander":
    """Create and configure an Amy Commander instance.

    Auto-detects available hardware:
    - BCC950 PTZ camera → BCC950Node (camera + mic + speaker + PTZ)
    - Falls back to VirtualNode if no hardware found

    Args:
        settings: Pydantic settings object (from app.config) or None for defaults.
        simulation_engine: Optional SimulationEngine for virtual targets.

    Returns:
        A Commander instance ready to be started with .run()
    """
    from .commander import Commander
    from engine.nodes.virtual import VirtualNode

    # Read config from settings (or use defaults)
    deep_model = "llava:7b"
    chat_model = "gemma3:4b"
    whisper_model = "large-v3"
    tts_enabled = True
    wake_word = "amy"
    camera_device = None
    think_interval = 8.0
    ollama_host = "http://localhost:11434"

    if settings is not None:
        deep_model = getattr(settings, "amy_deep_model", deep_model)
        chat_model = getattr(settings, "amy_chat_model", chat_model)
        whisper_model = getattr(settings, "amy_whisper_model", whisper_model)
        tts_enabled = getattr(settings, "amy_tts_enabled", tts_enabled)
        wake_word = getattr(settings, "amy_wake_word", wake_word)
        camera_device = getattr(settings, "amy_camera_device", camera_device)
        think_interval = getattr(settings, "amy_think_interval", think_interval)
        ollama_host = getattr(settings, "ollama_host", ollama_host)

    # Set Ollama host for all Amy vision/LLM calls
    from engine.perception.vision import set_ollama_host
    set_ollama_host(ollama_host)

    # Model routing — fleet-aware or static fallback
    model_router = None
    fleet_enabled = getattr(settings, "fleet_enabled", False) if settings else False
    if fleet_enabled:
        try:
            from engine.inference.fleet import OllamaFleet
            from engine.inference.model_router import ModelRouter, ModelProfile
            fleet_auto = getattr(settings, "fleet_auto_discover", True) if settings else True
            fleet = OllamaFleet(auto_discover=fleet_auto)
            print(f"  [Amy] Fleet: {fleet.status()}")
            model_router = ModelRouter.from_static(
                chat_model=chat_model,
                deep_model=deep_model,
                ollama_host=ollama_host,
            )
            model_router._fleet = fleet
            # Register additional profiles discovered from fleet
            for host in fleet.hosts:
                for model_name in host.models:
                    if model_router.get_profile(model_name) is None:
                        caps = {"text"}
                        if "llava" in model_name or "minicpm" in model_name:
                            caps.add("vision")
                        if "code" in model_name or "deepseek" in model_name:
                            caps.add("code")
                        model_router.register(ModelProfile(
                            name=model_name,
                            capabilities=caps,
                            priority=5,  # Default priority for discovered models
                        ))
            print(f"  [Amy] ModelRouter: {len(model_router.profiles)} profiles")
        except Exception as e:
            print(f"  [Amy] Fleet init failed, using static routing: {e}")
            model_router = None

    # Auto-detect hardware
    nodes = {}

    # Try BCC950
    try:
        from engine.nodes.bcc950 import BCC950Node
        node = BCC950Node(device=camera_device)
        # Don't start yet — just check if bcc950 package is importable
        # and the constructor doesn't fail
        nodes["bcc950"] = node
        print("  [Amy] BCC950 node registered (will init on boot)")
    except Exception as e:
        print(f"  [Amy] BCC950 not available: {e}")

    # Discover IP cameras from database
    db_url = getattr(settings, "database_url", "") if settings else ""
    if db_url:
        # Extract file path from SQLAlchemy URL (e.g. sqlite+aiosqlite:///./tritium.db)
        db_path = db_url.split("///", 1)[-1] if "///" in db_url else ""
        if db_path:
            ip_cameras = _discover_ip_cameras(db_path)
            if ip_cameras:
                nodes.update(ip_cameras)
                print(f"  [Amy] IP cameras discovered: {len(ip_cameras)} ({', '.join(ip_cameras.keys())})")

    # Fallback to virtual if no hardware
    if not nodes:
        nodes["virtual"] = VirtualNode()
        print("  [Amy] No hardware detected — using virtual node")

    commander = Commander(
        nodes=nodes,
        deep_model=deep_model,
        chat_model=chat_model,
        whisper_model=whisper_model,
        use_tts=tts_enabled,
        wake_word=wake_word,
        think_interval=think_interval,
        simulation_engine=simulation_engine,
        model_router=model_router,
    )

    # Set initial tactical mode from config
    initial_mode = getattr(settings, "simulation_mode", "sim") if settings else "sim"
    if initial_mode in ("sim", "live"):
        commander._mode = initial_mode

    return commander
