# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WebSocket endpoints for real-time updates.

Security model
--------------
WebSocket connections support optional token-based authentication via the
``token`` query parameter (``/ws/live?token=<secret>``).  When the
environment variable ``WS_AUTH_TOKEN`` is set, connections without a valid
token are rejected with 4003.  When the variable is unset, all connections
are accepted (open mode, suitable for development / LAN deployment).

Heartbeat
---------
The server sends a ``{"type":"ping"}`` frame every 30 seconds.  Clients
must respond with ``{"type":"pong"}``.  Connections that miss 3 consecutive
pings are considered stale and are forcibly closed.  This prevents zombie
WebSocket connections from accumulating.
"""

import asyncio
import json
import os
import queue
import threading
import time as _time
import uuid
from datetime import datetime
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from loguru import logger
from starlette.websockets import WebSocketState

router = APIRouter(prefix="/ws", tags=["websocket"])

# Optional auth token — set WS_AUTH_TOKEN to enable
_WS_AUTH_TOKEN: str | None = os.environ.get("WS_AUTH_TOKEN")

# Heartbeat constants
_PING_INTERVAL_S = 30.0
_MAX_MISSED_PONGS = 3
# Warn clients this many seconds before JWT expiry so they can refresh
_TOKEN_EXPIRY_WARN_S = 120


class ConnectionManager:
    """Manages WebSocket connections for real-time updates.

    Tracks last-pong timestamps to detect stale connections.
    Also tracks JWT token expiry per connection for proactive refresh warnings.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._last_pong: Dict[WebSocket, float] = {}
        self._token_exp: Dict[WebSocket, float] = {}  # ws -> JWT exp timestamp
        self._token_warned: Set[WebSocket] = set()  # ws already warned about expiry
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, token_exp: float | None = None):
        """Accept and register a new WebSocket connection.

        Args:
            token_exp: Optional JWT expiry timestamp. When provided, the server
                       sends a ``token_expiring`` message before expiry so the
                       client can refresh without disconnecting.
        """
        await websocket.accept()
        now = _time.time()
        async with self._lock:
            self.active_connections.add(websocket)
            self._last_pong[websocket] = now
            if token_exp is not None:
                self._token_exp[websocket] = token_exp
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        async with self._lock:
            self.active_connections.discard(websocket)
            self._last_pong.pop(websocket, None)
            self._token_exp.pop(websocket, None)
            self._token_warned.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    def record_pong(self, websocket: WebSocket):
        """Record that a pong was received from a client."""
        self._last_pong[websocket] = _time.time()

    def update_token_exp(self, websocket: WebSocket, exp: float) -> None:
        """Update the stored JWT expiry for a connection after token refresh."""
        self._token_exp[websocket] = exp
        self._token_warned.discard(websocket)

    async def check_token_expiry(self) -> None:
        """Send ``token_expiring`` warnings to clients whose JWT is about to expire.

        Called periodically from the ping heartbeat. Warns once per connection
        when the token has ``_TOKEN_EXPIRY_WARN_S`` seconds or fewer remaining.
        """
        now = _time.time()
        async with self._lock:
            for ws in list(self.active_connections):
                exp = self._token_exp.get(ws)
                if exp is None:
                    continue
                remaining = exp - now
                if remaining <= _TOKEN_EXPIRY_WARN_S and ws not in self._token_warned:
                    self._token_warned.add(ws)
                    try:
                        await ws.send_text(json.dumps({
                            "type": "token_expiring",
                            "expires_in_seconds": max(0, int(remaining)),
                            "message": "JWT token expiring soon. Send a token_refresh message with a new token.",
                            "timestamp": datetime.now(tz=None).isoformat(),
                        }))
                    except Exception:
                        pass

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

# Reference to the TargetTracker for broadcasting BLE/mesh targets
_target_tracker = None


@router.websocket("/live")
async def websocket_live(websocket: WebSocket, token: str | None = Query(default=None)):
    """WebSocket endpoint for live updates (events, alerts, status).

    Authentication: when WS_AUTH_TOKEN is set, connections must provide
    a matching ``token`` query parameter.  Unauthenticated connections
    are rejected with close code 4003.
    """
    # --- Auth check ---
    if _WS_AUTH_TOKEN is not None:
        if token != _WS_AUTH_TOKEN:
            await websocket.close(code=4003, reason="Forbidden — invalid or missing token")
            return

    # Extract JWT expiry timestamp for proactive refresh warnings
    token_exp: float | None = None
    if token:
        try:
            import jwt as _jwt
            # Decode without verification just to read exp claim
            payload = _jwt.decode(token, options={"verify_signature": False})
            token_exp = payload.get("exp")
        except Exception:
            pass

    await manager.connect(websocket, token_exp=token_exp)

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
        manager.record_pong(websocket)
        await manager.send_to(
            websocket,
            {"type": "pong", "timestamp": datetime.now(tz=None).isoformat()},
        )
    elif msg_type == "pong":
        # Client responding to our server-initiated ping
        manager.record_pong(websocket)
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
    elif msg_type == "cursor_update":
        # Operator cursor position on the map — broadcast to all other clients
        await _handle_cursor_update(websocket, message)
    elif msg_type == "drawing_update":
        # Real-time map drawing stroke — broadcast to all other operators
        await _handle_drawing_update(websocket, message)
    elif msg_type == "chat_message":
        # Inline chat message via WebSocket — broadcast to all operators
        await _handle_ws_chat(websocket, message)
    elif msg_type == "token_refresh":
        # Client sends a new JWT token to extend the session without reconnecting.
        # Expected: {"type": "token_refresh", "token": "<new_jwt>"}
        await _handle_token_refresh(websocket, message)
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


async def _handle_cursor_update(websocket: WebSocket, message: dict) -> None:
    """Handle cursor position updates from operators.

    Expected format:
        {
            "type": "cursor_update",
            "session_id": "...",
            "username": "...",
            "display_name": "...",
            "role": "commander",
            "color": "#ff2a6d",
            "lat": 40.7128,
            "lng": -74.0060
        }

    Broadcasts the cursor position to all other connected clients so they
    can render colored dots on the map with the operator's username.
    """
    session_id = message.get("session_id", "")
    lat = message.get("lat")
    lng = message.get("lng")

    # Update the session store if available
    if session_id:
        try:
            from app.routers.sessions import get_session_store
            sessions = get_session_store()
            session = sessions.get(session_id)
            if session:
                session.cursor_lat = lat
                session.cursor_lng = lng
                session.touch()
        except Exception:
            pass

    # Broadcast cursor to all other clients (includes viewport if provided)
    cursor_msg = {
        "type": "cursor_position",
        "session_id": session_id,
        "username": message.get("username", ""),
        "display_name": message.get("display_name", ""),
        "role": message.get("role", "observer"),
        "color": message.get("color", "#00f0ff"),
        "lat": lat,
        "lng": lng,
        "timestamp": datetime.now(tz=None).isoformat(),
    }
    # Operator viewport: zoom level and visible bounds for coordination
    if message.get("zoom") is not None:
        cursor_msg["zoom"] = message["zoom"]
    if message.get("bounds"):
        cursor_msg["bounds"] = message["bounds"]  # {north, south, east, west}
    if message.get("viewport_label"):
        cursor_msg["viewport_label"] = message["viewport_label"]

    # Send to all clients except the sender
    message_str = json.dumps(cursor_msg)
    async with manager._lock:
        for conn in manager.active_connections:
            if conn is not websocket:
                try:
                    await conn.send_text(message_str)
                except Exception:
                    pass


async def _handle_drawing_update(websocket: WebSocket, message: dict) -> None:
    """Handle real-time map drawing strokes from operators.

    Expected format:
        {
            "type": "drawing_update",
            "drawing_id": "...",
            "operator_id": "...",
            "operator_name": "...",
            "color": "#00f0ff",
            "drawing_type": "freehand",
            "points": [[lng, lat], ...],
            "action": "stroke" | "complete" | "erase"
        }

    Broadcasts the drawing data to all other connected clients so they
    can render the drawing in real time on their maps.
    """
    import html as _html

    # Validate points length to prevent memory abuse
    points = message.get("points", [])
    if len(points) > 5000:
        points = points[:5000]

    drawing_msg = {
        "type": "map_drawing_live",
        "drawing_id": str(message.get("drawing_id", ""))[:20],
        "operator_id": _html.escape(str(message.get("operator_id", ""))[:100]),
        "operator_name": _html.escape(str(message.get("operator_name", ""))[:100]),
        "color": str(message.get("color", "#00f0ff"))[:20],
        "drawing_type": str(message.get("drawing_type", "freehand"))[:20],
        "points": points,
        "action": str(message.get("action", "stroke"))[:20],
        "radius": message.get("radius"),
        "text": _html.escape(str(message.get("text") or ""))[:200] or None,
        "line_width": max(0.5, min(20.0, float(message.get("line_width", 2.0)))),
        "opacity": max(0.0, min(1.0, float(message.get("opacity", 0.8)))),
        "timestamp": datetime.now(tz=None).isoformat(),
    }
    # Send to all clients except the sender
    message_str = json.dumps(drawing_msg)
    async with manager._lock:
        for conn in manager.active_connections:
            if conn is not websocket:
                try:
                    await conn.send_text(message_str)
                except Exception:
                    pass


async def _handle_ws_chat(websocket: WebSocket, message: dict) -> None:
    """Handle inline chat messages sent via WebSocket.

    Expected format:
        {
            "type": "chat_message",
            "operator_id": "...",
            "operator_name": "...",
            "content": "message text",
            "channel": "general"
        }

    Broadcasts the message to all connected clients including the sender
    (for confirmation), and logs to the chat history.
    """
    import html as _html
    import re as _re

    content = (message.get("content") or "").strip()
    if not content:
        return

    # Sanitize: strip HTML tags and escape to prevent injection
    _html_tag_re = _re.compile(r"<[^>]+>")
    content = _html_tag_re.sub("", content)
    content = _html.escape(content)[:2000]

    import time as _t
    chat_msg = {
        "type": "operator_chat",
        "data": {
            "message_id": str(uuid.uuid4())[:12],
            "operator_id": _html.escape((message.get("operator_id") or "")[:100]),
            "operator_name": _html.escape((message.get("operator_name") or "")[:100]),
            "content": content,
            "message_type": message.get("message_type", "text"),
            "channel": (message.get("channel") or "general")[:50],
            "timestamp": _t.time(),
        },
        "timestamp": datetime.now(tz=None).isoformat(),
    }

    # Broadcast to all clients
    await manager.broadcast(chat_msg)


async def _handle_token_refresh(websocket: WebSocket, message: dict) -> None:
    """Handle a token_refresh message from a client.

    When a client receives ``token_expiring``, it should obtain a new JWT
    (via POST /api/auth/refresh) and send it here so the server can update
    the stored expiry for this connection. This avoids a disconnect/reconnect
    cycle.

    Expected format:
        {"type": "token_refresh", "token": "<new_jwt>"}
    """
    new_token = message.get("token", "")
    if not new_token:
        await manager.send_to(websocket, {
            "type": "error",
            "message": "token_refresh requires a 'token' field",
        })
        return

    try:
        from app.auth import decode_token
        payload = decode_token(new_token)
        exp = payload.get("exp")
        if exp is not None:
            manager.update_token_exp(websocket, float(exp))
            await manager.send_to(websocket, {
                "type": "token_refreshed",
                "expires_at": exp,
                "timestamp": datetime.now(tz=None).isoformat(),
            })
            logger.debug(f"WebSocket token refreshed for user={payload.get('sub')}")
        else:
            await manager.send_to(websocket, {
                "type": "error",
                "message": "New token has no exp claim",
            })
    except Exception as e:
        await manager.send_to(websocket, {
            "type": "error",
            "message": f"Token refresh failed: {e}",
        })


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


class TargetUpdateBatcher:
    """Deduplicates target updates by target_id before flushing.

    When many targets update rapidly (100+ BLE devices, sim entities),
    sending one WS frame per target wastes bandwidth.  This batcher
    collects updates keyed by ``target_id`` and flushes only the latest
    state for each target at a fixed interval.  This can reduce WS
    frame count by 5-10x for large target counts.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop,
                 event_type: str = "target_update_batch",
                 interval: float = 0.25):
        self._loop = loop
        self._event_type = event_type
        self._interval = interval
        self._buffer: dict[str, dict] = {}  # target_id -> latest state
        self._lock = threading.Lock()
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True,
            name=f"target-batcher-{event_type}",
        )
        self._running = True

    def start(self) -> None:
        self._flush_thread.start()

    def add(self, target_id: str, data: dict) -> None:
        """Add or update a target's state.  Only latest state is kept."""
        with self._lock:
            self._buffer[target_id] = data

    def add_many(self, targets: list[dict], key: str = "target_id") -> None:
        """Bulk-add targets from a list of dicts."""
        with self._lock:
            for t in targets:
                tid = t.get(key, "")
                if tid:
                    self._buffer[tid] = t

    def _flush_loop(self) -> None:
        while self._running:
            _time.sleep(self._interval)
            with self._lock:
                if not self._buffer:
                    continue
                batch = list(self._buffer.values())
                self._buffer.clear()
            asyncio.run_coroutine_threadsafe(
                broadcast_amy_event(self._event_type, batch), self._loop
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
    global _lod_system, _sim_engine, _target_tracker
    sim_engine = getattr(amy_commander, "simulation_engine", None)
    if sim_engine is not None:
        _lod_system = getattr(sim_engine, "lod_system", None)
        _sim_engine = sim_engine

    tracker = getattr(amy_commander, "target_tracker", None)
    _target_tracker = tracker

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
                elif event_type == "detection:camera":
                    # Camera YOLO detection events — broadcast each detection
                    # individually as "detection" so camera-feeds panel updates
                    camera_id = data.get("camera_id", "")
                    dets = data.get("detections", [])
                    for det in dets:
                        det_data = {
                            "camera_id": camera_id,
                            "class_name": det.get("label") or det.get("class_name", "unknown"),
                            "confidence": det.get("confidence", 0),
                            "timestamp": datetime.now(tz=None).isoformat(),
                            "bbox": det.get("bbox"),
                        }
                        asyncio.run_coroutine_threadsafe(
                            broadcast_detection(det_data), loop
                        )
                elif event_type.startswith("system:"):
                    # System-wide events (threat level, etc.) — convert : to _
                    ws_type = event_type.replace(":", "_")
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({
                            "type": ws_type,
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

    # Broadcast BLE/mesh targets from the tracker every 2s
    _start_tracker_broadcast(tracker, loop)

    # Start server-side WebSocket ping heartbeat
    _start_ws_ping_heartbeat(loop)


def start_headless_event_bridge(event_bus, loop: asyncio.AbstractEventLoop,
                                simulation_engine=None, target_tracker=None):
    """Bridge a bare EventBus to WebSocket without requiring Amy.

    Used in headless mode (AMY_ENABLED=false, SIMULATION_ENABLED=true) so that
    sim_telemetry events reach the browser canvas for testing.

    Args:
        event_bus: An EventBus instance (from the standalone SimulationEngine)
        loop: The asyncio event loop to push events into
        simulation_engine: Optional SimulationEngine instance for LOD wiring
        target_tracker: Optional TargetTracker for BLE/mesh broadcast
    """
    # Wire LOD system and engine reference for viewport_update and game state sync
    global _lod_system, _sim_engine, _target_tracker
    if simulation_engine is not None:
        _lod_system = getattr(simulation_engine, "lod_system", None)
        _sim_engine = simulation_engine
    if target_tracker is not None:
        _target_tracker = target_tracker

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
                    # Edge target handoff events
                    "edge:target_handoff",
                    # Trilateration position updates
                    "trilat:position_update",
                    # Dossier lifecycle
                    "dossier_created",
                    # Federation events
                    "federation:site_added",
                    "federation:target_shared",
                    "federation:target_received",
                ):
                    asyncio.run_coroutine_threadsafe(
                        broadcast_amy_event(event_type, data), loop
                    )
                elif event_type == "detection:camera":
                    # Camera YOLO detection events — broadcast each detection
                    # individually as "detection" so camera-feeds panel updates
                    camera_id = data.get("camera_id", "")
                    dets = data.get("detections", [])
                    for det in dets:
                        det_data = {
                            "camera_id": camera_id,
                            "class_name": det.get("label") or det.get("class_name", "unknown"),
                            "confidence": det.get("confidence", 0),
                            "timestamp": datetime.now(tz=None).isoformat(),
                            "bbox": det.get("bbox"),
                        }
                        asyncio.run_coroutine_threadsafe(
                            broadcast_detection(det_data), loop
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

    # Broadcast BLE/mesh targets for headless mode too
    _start_tracker_broadcast(target_tracker, loop)

    # Start server-side WebSocket ping heartbeat
    _start_ws_ping_heartbeat(loop)


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


def _start_tracker_broadcast(
    tracker, loop: asyncio.AbstractEventLoop, interval: float = 2.0
) -> None:
    """Broadcast BLE and mesh targets from the TargetTracker every ``interval`` seconds.

    The SimulationEngine only publishes sim_telemetry_batch for simulation targets.
    BLE devices (source="ble") and mesh radios (asset_type="mesh_radio") enter the
    tracker via update_from_ble() and update_from_simulation() respectively, but
    never appear in the sim telemetry stream.  This heartbeat ensures those targets
    reach WebSocket clients as part of the telemetry batch.

    Uses a TargetUpdateBatcher to deduplicate updates by target_id, reducing
    WS frame count by 5-10x when many targets are present.
    """
    if tracker is None:
        return

    # Sources/asset_types that are NOT covered by sim_telemetry_batch
    _NON_SIM_SOURCES = {"ble", "yolo", "manual"}
    _MESH_ASSET_TYPES = {"mesh_radio", "meshtastic"}

    # Batcher deduplicates by target_id and flushes as sim_telemetry_batch
    batcher = TargetUpdateBatcher(
        loop, event_type="sim_telemetry_batch", interval=0.5
    )
    batcher.start()

    def _broadcast():
        while True:
            _time.sleep(interval)
            if not manager.active_connections:
                continue
            try:
                all_targets = tracker.get_all()
                non_sim = [
                    t for t in all_targets
                    if t.source in _NON_SIM_SOURCES
                    or t.asset_type in _MESH_ASSET_TYPES
                ]
                if not non_sim:
                    continue
                batch = [t.to_dict() for t in non_sim]
                batcher.add_many(batch)
            except Exception:
                pass  # Tracker not ready or shutting down

    thread = threading.Thread(
        target=_broadcast, daemon=True, name="tracker-broadcast"
    )
    thread.start()


# Track whether the ping heartbeat has already been started (singleton)
_ping_heartbeat_started = False


def _start_ws_ping_heartbeat(loop: asyncio.AbstractEventLoop) -> None:
    """Send a ping frame to every connected client every 30s.

    Clients must respond with ``{"type":"pong"}``.  Connections that miss
    3 consecutive pings (90s of silence) are considered stale and are
    forcibly closed.  This prevents zombie WebSocket connections from
    accumulating memory and CPU.
    """
    global _ping_heartbeat_started
    if _ping_heartbeat_started:
        return
    _ping_heartbeat_started = True

    async def _ping_loop():
        while True:
            await asyncio.sleep(_PING_INTERVAL_S)
            if not manager.active_connections:
                continue

            now = _time.time()
            stale_threshold = now - (_PING_INTERVAL_S * _MAX_MISSED_PONGS)

            # Identify stale connections
            stale: set = set()
            async with manager._lock:
                for ws in list(manager.active_connections):
                    last = manager._last_pong.get(ws, 0)
                    if last < stale_threshold:
                        stale.add(ws)

            # Close stale connections
            for ws in stale:
                try:
                    logger.warning("Closing stale WebSocket (no pong received)")
                    await ws.close(code=4001, reason="Ping timeout")
                except Exception:
                    pass
                await manager.disconnect(ws)

            # Send ping to all remaining connections
            ping_msg = json.dumps({
                "type": "ping",
                "timestamp": datetime.now(tz=None).isoformat(),
            })
            async with manager._lock:
                for ws in list(manager.active_connections):
                    try:
                        if ws.client_state == WebSocketState.CONNECTED:
                            await ws.send_text(ping_msg)
                    except Exception:
                        pass

            # Check for expiring JWT tokens and warn clients
            await manager.check_token_expiry()

    asyncio.run_coroutine_threadsafe(_ping_loop(), loop)
