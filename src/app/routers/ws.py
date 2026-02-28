"""WebSocket endpoints for real-time updates."""

import asyncio
import json
import threading
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
    else:
        await manager.send_to(
            websocket,
            {"type": "error", "message": f"Unknown message type: {msg_type}"},
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


def start_amy_event_bridge(amy_commander, loop: asyncio.AbstractEventLoop):
    """Start a daemon thread that forwards Amy EventBus events to WebSocket.

    This bridges Amy's threaded EventBus to FastAPI's async WebSocket system.

    Args:
        amy_commander: Amy's Commander instance
        loop: The asyncio event loop to push events into
    """
    sub = amy_commander.event_bus.subscribe()
    batcher = TelemetryBatcher(loop)
    batcher.start()

    def bridge_loop():
        while True:
            try:
                msg = sub.get(timeout=60)
                event_type = msg.get("type", "unknown")
                data = msg.get("data", {})
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
                else:
                    asyncio.run_coroutine_threadsafe(
                        broadcast_amy_event(event_type, data), loop
                    )
            except Exception:
                continue

    thread = threading.Thread(target=bridge_loop, daemon=True, name="amy-ws-bridge")
    thread.start()


def start_headless_event_bridge(event_bus, loop: asyncio.AbstractEventLoop):
    """Bridge a bare EventBus to WebSocket without requiring Amy.

    Used in headless mode (AMY_ENABLED=false, SIMULATION_ENABLED=true) so that
    sim_telemetry events reach the browser canvas for testing.

    Args:
        event_bus: An EventBus instance (from the standalone SimulationEngine)
        loop: The asyncio event loop to push events into
    """
    sub = event_bus.subscribe()
    batcher = TelemetryBatcher(loop)
    batcher.start()

    def bridge_loop():
        while True:
            try:
                msg = sub.get(timeout=60)
                event_type = msg.get("type", "unknown")
                data = msg.get("data", {})
                if event_type == "sim_telemetry":
                    batcher.add(data)
                elif event_type == "sim_telemetry_batch":
                    asyncio.run_coroutine_threadsafe(
                        broadcast_amy_event("sim_telemetry_batch", data), loop
                    )
                elif event_type in (
                    "game_state_change",
                    "wave_start",
                    "wave_complete",
                    "target_eliminated",
                    "game_over",
                    "projectile_fired",
                    "projectile_hit",
                    "elimination_streak",
                    "announcer",
                    "npc_thought",
                    "npc_thought_clear",
                    "mission_progress",
                    "scenario_generated",
                ):
                    asyncio.run_coroutine_threadsafe(
                        broadcast_amy_event(event_type, data), loop
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
            except Exception:
                continue

    thread = threading.Thread(
        target=bridge_loop, daemon=True, name="headless-ws-bridge"
    )
    thread.start()
