# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Meshtastic LoRa Mesh addon for Tritium.

Connects to Meshtastic devices via USB serial, Bluetooth, WiFi/TCP, or MQTT.
Each mesh node becomes a tracked target on the tactical map.
"""

from tritium_lib.sdk import SensorAddon, AddonInfo

from .connection import ConnectionManager
from .node_manager import NodeManager
from .router import create_router


class MeshtasticAddon(SensorAddon):
    """Meshtastic LoRa mesh radio integration."""

    info = AddonInfo(
        id="meshtastic",
        name="Meshtastic LoRa Mesh",
        version="1.0.0",
        description="LoRa mesh radio network with GPS tracking and fleet management",
        author="Valpatel Software LLC",
        category="radio",
        icon="📡",
    )

    def __init__(self):
        super().__init__()
        self.connection: ConnectionManager | None = None
        self.node_manager: NodeManager | None = None
        self._poll_task = None

    async def register(self, app):
        await super().register(app)

        self.node_manager = NodeManager(
            event_bus=getattr(app, 'event_bus', None),
            target_tracker=getattr(app, 'target_tracker', None),
        )

        self.connection = ConnectionManager(
            node_manager=self.node_manager,
            event_bus=getattr(app, 'event_bus', None),
        )

        # Add API routes
        router = create_router(self.connection, self.node_manager)
        if hasattr(app, 'include_router'):
            app.include_router(router, prefix="/api/addons/meshtastic", tags=["meshtastic"])

        # Auto-detect and connect
        await self.connection.auto_connect()

        # Start polling loop
        import asyncio
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._background_tasks.append(self._poll_task)

    async def unregister(self, app):
        if self.connection:
            await self.connection.disconnect()
            self.connection = None
        self.node_manager = None
        await super().unregister(app)

    async def gather(self):
        """Return current mesh nodes as target dicts."""
        if not self.node_manager:
            return []
        return self.node_manager.get_targets()

    async def _poll_loop(self):
        """Background loop: poll device for node updates."""
        import asyncio
        while self._registered:
            try:
                if self.connection and self.connection.is_connected:
                    nodes = await self.connection.get_nodes()
                    if nodes and self.node_manager:
                        self.node_manager.update_nodes(nodes)
            except Exception as e:
                import logging
                logging.getLogger("meshtastic").warning(f"Poll error: {e}")
            await asyncio.sleep(10)

    def get_panels(self):
        return [
            {"id": "mesh-network", "title": "MESHTASTIC", "file": "mesh-network.js",
             "category": "radio", "tab_order": 1},
            {"id": "mesh-nodes", "title": "MESH NODES", "file": "mesh-nodes.js",
             "category": "radio", "tab_order": 2},
            {"id": "mesh-config", "title": "DEVICE CONFIG", "file": "mesh-config.js",
             "category": "radio", "tab_order": 3},
            {"id": "mesh-messages", "title": "MESH CHAT", "file": "mesh-messages.js",
             "category": "radio", "tab_order": 4},
        ]

    def get_layers(self):
        return [
            {"id": "meshNodes", "label": "Mesh Nodes", "category": "MESH NETWORK",
             "color": "#00d4aa", "key": "showMeshNodes"},
            {"id": "meshLinks", "label": "Mesh Links", "category": "MESH NETWORK",
             "color": "#00d4aa", "key": "showMeshLinks"},
            {"id": "meshCoverage", "label": "Coverage Estimate", "category": "MESH NETWORK",
             "color": "rgba(0,212,170,0.3)", "key": "showMeshCoverage"},
        ]

    def health_check(self):
        connected = self.connection.is_connected if self.connection else False
        node_count = len(self.node_manager.nodes) if self.node_manager else 0
        return {
            "status": "ok" if connected else "degraded",
            "connected": connected,
            "transport": self.connection.transport_type if self.connection else None,
            "device_port": self.connection.port if self.connection else None,
            "node_count": node_count,
        }
