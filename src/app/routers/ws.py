# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WebSocket endpoints for real-time updates."""

import asyncio
import json
import queue
import threading
import time as _time
from datetime import datetime
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

router = APIRouter(prefix="/ws", tags=["websocket"])


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return

        message_str = json.dumps(message)
        disconnected = set()

        async with self._lock:
            for connection in self.active_connections:
                try:
                    await connection.send_text(message_str)
                except Exception as e:
                    logger.warning(f"Failed to send to websocket: {e}")
                    disconnected.add(connection)

            # Remove disconnected clients
            self.active_connections -= disconnected

    async def send_to(self, websocket: WebSocket, message: dict):
        """Send a message to a specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"Failed to send to websocket: {e}")


# Global connection manager
manager = ConnectionManager()

# Reference to the simulation engine's LOD system (set during bridge startup)
_lod_system = None

# Reference to the simulation engine for initial state sync on connect
_sim_engine = None


@router.websocket("/live")
async def websocket_live(websocket: WebSocket):
    """WebSocket endpoint for live updates (events, alerts, status)."""
    await manager.connect(websocket)

    # Send initial connection confirmation
    await manager.send_to(
        websocket,
        {
            "type": "connected",
            "timestamp": datetime.now(tz=None).isoformat(),
            "message": "TRITIUM UPLINK ESTABLISHED",
        },
    )

    # Send current game state so late-joining clients are immediately in sync.
    # Without this, clients that connect after a state transition miss the
    # game_state_change event and their HUD stays stuck at "idle".
    if _sim_engine is not None:
        try:
            game_state = _sim_engine.get_game_state()
            await manager.send_to(
                websocket,
                {
                    "type": "amy_game_state_change",
                    "data": game_state,
                    "timestamp": datetime.now(tz=None).isoformat(),
                },
            )
        except Exception:
            pass  # Non-fatal: client will get state on next heartbeat

    try:
        while True:
            # Handle incoming messages from client
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                await handle_client_message(websocket, message)
            except json.JSONDecodeError:
                await manager.send_to(
                    websocket, {"type": "error", "message": "Invalid JSON"}
                )
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


async def handle_client_message(websocket: WebSocket, message: dict):
    """Handle messages from WebSocket clients."""
    msg_type = message.get("type")

    if msg_type == "ping":
        await manager.send_to(
            websocket,
            {"type": "pong", "timestamp": datetime.now(tz=None).isoformat()},
        )
    elif msg_type == "subscribe":
        # Subscribe to specific channels/events
        channels = message.get("channels", [])
        await manager.send_to(
            websocket,
            {"type": "subscribed", "channels": channels},
        )
    elif msg_type == "viewport_update":
        # Frontend reports its current viewport center and zoom.
        # Forward to the simulation engine's LOD system to adjust fidelity.
        _handle_viewport_update(message)
    else:
        await manager.send_to(
            websocket,
            {"type": "error", "message": f"Unknown message type: {msg_type}"},
        )


def _handle_viewport_update(message: dict) -> None:
    """Process a viewport_update message from the frontend.

    Expected format:
        {
            "type": "viewport_update",
            "center_x": float,   # local X coord (meters from map origin)
            "center_y": float,   # local Y coord (meters from map origin)
            "zoom": float,       # MapLibre zoom level
            "radius": float      # optional: visible radius in meters
        }

    If center_x/center_y are not provided but center_lat/center_lng are,
    we convert using the geo module.
    """
    global _lod_system
    if _lod_system is None:
        return

    center_x = message.get("center_x")
    center_y = message.get("center_y")

    # If frontend sends lat/lng instead of local coords, convert
    if center_x is None or center_y is None:
        lat = message.get("center_lat") or message.get("lat")
        lng = message.get("center_lng") or message.get("lng")
        if lat is not None and lng is not None:
            try:
                from engine.tactical.geo import latlng_to_local
                local = latlng_to_local(lat, lng)
                center_x = local[0]  # x = East
                center_y = local[1]  # y = North
            except Exception:
                return
        else:
            return

    zoom = message.get("zoom")
    radius = message.get("radius")

    _lod_system.update_viewport(
        center_x=float(center_x),
        center_y=float(center_y),
        radius=float(radius) if radius is not None else None,
        zoom=float(zoom) if zoom is not None else None,
    )


# Utility functions for broadcasting from other parts of the app
async def broadcast_event(event_data: dict):
    """Broadcast a detection event to all clients."""
    await manager.broadcast(
        {
            "type": "event",
            "data": event_data,
            "timestamp": datetime.now(tz=None).isoformat(),
        }
    )


async def broadcast_alert(alert_data: dict):
    """Broadcast an alert to all clients."""
    await manager.broadcast(
        {
            "type": "alert",
            "data": alert_data,
            "timestamp": datetime.now(tz=None).isoformat(),
        }
    )


async def broadcast_camera_status(camera_id: int, status: str):
    """Broadcast camera status change."""
    await manager.broadcast(
        {
            "type": "camera_status",
            "camera_id": camera_id,
            "status": status,
            "timestamp": datetime.now(tz=None).isoformat(),
        }
    )


async def broadcast_asset_update(asset_data: dict):
    """Broadcast asset status/position update."""
    await manager.broadcast(
        {
            "type": "asset_update",
            "data": asset_data,
            "timestamp": datetime.now(tz=None).isoformat(),
        }
    )


async def broadcast_task_update(task_data: dict):
    """Broadcast task status update."""
    await manager.broadcast(
        {
            "type": "task_update",
            "data": task_data,
            "timestamp": datetime.now(tz=None).isoformat(),
        }
    )


async def broadcast_detection(detection_data: dict):
    """Broadcast new detection (person/vehicle)."""
    await manager.broadcast(
        {
            "type": "detection",
            "data": detection_data,
            "timestamp": datetime.now(tz=None).isoformat(),
        }
    )


# --- Amy event bridge ---

async def broadcast_amy_event(event_type: str, data: dict):
    """Broadcast an Amy event to all WebSocket clients."""
    await manager.broadcast(
        {
            "type": f"amy_{event_type}",
            "data": data,
            "timestamp": datetime.now(tz=None).isoformat(),
        }
    )


class TelemetryBatcher:
    """Accumulates sim_telemetry events and flushes as a batch every 100ms."""

    def __init__(self, loop: asyncio.AbstractEventLoop, interval: float = 0.1):
        self._loop = loop
        self._interval = interval
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="telemetry-batcher"
        )
        self._running = True

    def start(self) -> None:
        self._flush_thread.start()

    def add(self, data: dict) -> None:
        with self._lock:
            self._buffer.append(data)

    def _flush_loop(self) -> None:
        import time as _time

        while self._running:
            _time.sleep(self._interval)
            with self._lock:
                if not self._buffer:
                    continue
                batch = self._buffer[:]
                self._buffer.clear()
            asyncio.run_coroutine_threadsafe(
                broadcast_amy_event("sim_telemetry_batch", batch), self._loop
            )

    def stop(self) -> None:
        self._running = False


def _normalize_event_type(event_type: str) -> str:
    """Translate engine-internal event names to frontend-expected names.

    The engine's ThreatClassifier publishes ``threat_escalation`` and
    ``threat_deescalation``, but the frontend websocket.js handler and the
    NPC intelligence EventReactor both expect ``escalation_change``.  This
    function normalises the name so every downstream consumer sees a
    consistent event type.
    """
    if event_type in ("threat_escalation", "threat_deescalation"):
        return "escalation_change"
    return event_type


def start_amy_event_bridge(amy_commander, loop: asyncio.AbstractEventLoop):
    """Start a daemon thread that forwards Amy EventBus events to WebSocket.

    This bridges Amy's threaded EventBus to FastAPI's async WebSocket system.
    Also starts a game-state heartbeat that sends the current game state
    every 2 seconds so late-joining or reconnecting clients stay in sync.

    Args:
        amy_commander: Amy's Commander instance
        loop: The asyncio event loop to push events into
    """
    # Wire LOD system reference for viewport_update handling
    global _lod_system, _sim_engine
    sim_engine = getattr(amy_commander, "simulation_engine", None)
    if sim_engine is not None:
        _lod_system = getattr(sim_engine, "lod_system", None)
        _sim_engine = sim_engine

    sub = amy_commander.event_bus.subscribe()
    batcher = TelemetryBatcher(loop)
    batcher.start()

    def bridge_loop():
        while True:
            try:
                msg = sub.get(timeout=60)
                event_type = msg.get("type", "unknown")
                data = msg.get("data", {})
                # Normalise engine event names to frontend-expected names
                event_type = _normalize_event_type(event_type)
                if event_type == "sim_telemetry":
                    batcher.add(data)
                elif event_type == "sim_telemetry_batch":
                    # Engine-side batch — forward directly to clients
                    asyncio.run_coroutine_threadsafe(
                        broadcast_amy_event("sim_telemetry_batch", data), loop
                    )
                elif event_type.startswith("amy_"):
                    # Already has amy_ prefix (e.g. amy_announcement) —
                    # broadcast directly to avoid double-prefixing.
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({
                            "type": event_type,
                            "data": data,
                            "timestamp": datetime.now(tz=None).isoformat(),
                        }),
                        loop,
                    )
                elif event_type.startswith("fleet."):
                    # Fleet bridge events pass through as fleet_* for frontend.
                    ws_type = event_type.replace(".", "_")
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({
                            "type": ws_type,
                            "data": data,
                            "timestamp": datetime.now(tz=None).isoformat(),
                        }),
                        loop,
                    )
                elif event_type.startswith("mesh_"):
                    # Mesh events pass through without prefix mangling.
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({
                            "type": event_type,
                            "data": data,
                            "timestamp": datetime.now(tz=None).isoformat(),
                        }),
                        loop,
                    )
                elif event_type.startswith("tak_"):
                    # TAK events pass through without prefix mangling.
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({
                            "type": event_type,
                            "data": data,
                            "timestamp": datetime.now(tz=None).isoformat(),
                        }),
                        loop,
                    )
                else:
                    asyncio.run_coroutine_threadsafe(
                        broadcast_amy_event(event_type, data), loop
                    )
            except queue.Empty:
                continue
            except Exception:
                logger.warning(f"Bridge loop error for event '{event_type}'", exc_info=True)
                continue

    thread = threading.Thread(target=bridge_loop, daemon=True, name="amy-ws-bridge")
    thread.start()

    # Game state heartbeat: broadcast current game state every 2s.
    # This ensures clients stay in sync even if they miss a
    # game_state_change event (network hiccup, late join, reconnect).
    _start_game_state_heartbeat(sim_engine, loop)


def start_headless_event_bridge(event_bus, loop: asyncio.AbstractEventLoop,
                                simulation_engine=None):
    """Bridge a bare EventBus to WebSocket without requiring Amy.

    Used in headless mode (AMY_ENABLED=false, SIMULATION_ENABLED=true) so that
    sim_telemetry events reach the browser canvas for testing.

    Args:
        event_bus: An EventBus instance (from the standalone SimulationEngine)
        loop: The asyncio event loop to push events into
        simulation_engine: Optional SimulationEngine instance for LOD wiring
    """
    # Wire LOD system and engine reference for viewport_update and game state sync
    global _lod_system, _sim_engine
    if simulation_engine is not None:
        _lod_system = getattr(simulation_engine, "lod_system", None)
        _sim_engine = simulation_engine

    sub = event_bus.subscribe()
    batcher = TelemetryBatcher(loop)
    batcher.start()

    def bridge_loop():
        while True:
            try:
                msg = sub.get(timeout=60)
                event_type = msg.get("type", "unknown")
                data = msg.get("data", {})
                # Normalise engine event names to frontend-expected names
                event_type = _normalize_event_type(event_type)
                if event_type == "sim_telemetry":
                    batcher.add(data)
                elif event_type == "sim_telemetry_batch":
                    asyncio.run_coroutine_threadsafe(
                        broadcast_amy_event("sim_telemetry_batch", data), loop
                    )
                elif event_type in (
                    # Core game lifecycle
                    "game_state_change",
                    "wave_start",
                    "wave_complete",
                    "game_over",
                    # Combat events
                    "projectile_fired",
                    "projectile_hit",
                    "target_eliminated",
                    "elimination_streak",
                    "target_neutralized",
                    # Weapon/ammo events
                    "weapon_jam",
                    "ammo_depleted",
                    "ammo_low",
                    # NPC intelligence
                    "npc_thought",
                    "npc_thought_clear",
                    "npc_alliance_change",
                    # Threat escalation (normalised from threat_escalation/threat_deescalation)
                    "escalation_change",
                    # Mission generation
                    "mission_progress",
                    "scenario_generated",
                    "backstory_generated",
                    # Mission-type events (civil unrest + drone swarm)
                    "crowd_density",
                    "infrastructure_damage",
                    "infrastructure_overwhelmed",
                    "bomber_detonation",
                    "de_escalation",
                    "civilian_harmed",
                    # Environmental hazards
                    "hazard_spawned",
                    "hazard_expired",
                    # Sensor events
                    "sensor_triggered",
                    "sensor_cleared",
                    # Upgrade/ability system
                    "upgrade_applied",
                    "ability_activated",
                    "ability_expired",
                    # External device events
                    "robot_thought",
                    "detection",
                    "detections",
                    # Bonus objective completion
                    "bonus_objective_completed",
                    # Hostile commander intel
                    "hostile_intel",
                    # Unit communication signals
                    "unit_signal",
                    # Cover system state for map overlay
                    "cover_points",
                    # Mission-specific combat events
                    "instigator_identified",
                    "emp_activated",
                    # Auto-dispatch and zone breach announcements
                    "auto_dispatch_speech",
                    "zone_violation",
                    # Unit dispatch
                    "unit_dispatched",
                    # Amy mode/formation events
                    "formation_created",
                    "mode_change",
                    # Edge tracker BLE and WiFi updates
                    "edge:ble_update",
                    "edge:wifi_update",
                ):
                    asyncio.run_coroutine_threadsafe(
                        broadcast_amy_event(event_type, data), loop
                    )
                elif event_type.startswith("fleet."):
                    ws_type = event_type.replace(".", "_")
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({
                            "type": ws_type,
                            "data": data,
                            "timestamp": datetime.now(tz=None).isoformat(),
                        }),
                        loop,
                    )
                elif event_type.startswith("mesh_"):
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({
                            "type": event_type,
                            "data": data,
                            "timestamp": datetime.now(tz=None).isoformat(),
                        }),
                        loop,
                    )
                elif event_type.startswith("tak_"):
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({
                            "type": event_type,
                            "data": data,
                            "timestamp": datetime.now(tz=None).isoformat(),
                        }),
                        loop,
                    )
            except queue.Empty:
                continue
            except Exception:
                logger.warning(f"Headless bridge error for event '{event_type}'", exc_info=True)
                continue

    thread = threading.Thread(
        target=bridge_loop, daemon=True, name="headless-ws-bridge"
    )
    thread.start()

    # Game state heartbeat for headless mode too
    _start_game_state_heartbeat(simulation_engine, loop)


def _start_game_state_heartbeat(
    sim_engine, loop: asyncio.AbstractEventLoop, interval: float = 2.0
) -> None:
    """Broadcast current game state to all clients every ``interval`` seconds.

    This is a safety net: even if a client misses a game_state_change event
    (network hiccup, late join, reconnect), it will self-correct within
    ``interval`` seconds.  The heartbeat only sends when there are active
    connections to avoid unnecessary work.
    """
    if sim_engine is None:
        return

    _last_state: dict = {}

    def _heartbeat():
        nonlocal _last_state
        while True:
            _time.sleep(interval)
            if not manager.active_connections:
                continue
            try:
                state = sim_engine.get_game_state()
                # Only send if state changed since last heartbeat
                # to avoid spamming identical messages
                if state == _last_state:
                    continue
                _last_state = state
                asyncio.run_coroutine_threadsafe(
                    broadcast_amy_event("game_state_change", state), loop
                )
            except Exception:
                pass  # Engine shutting down or not yet ready

    thread = threading.Thread(
        target=_heartbeat, daemon=True, name="game-state-heartbeat"
    )
    thread.start()
