# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Meshtastic LoRa Mesh addon for Tritium.

Connects to Meshtastic devices via USB serial, Bluetooth, WiFi/TCP, or MQTT.
Each mesh node becomes a tracked target on the tactical map.
"""

from tritium_lib.sdk import SensorAddon, AddonInfo

from .connection import ConnectionManager
from .data_store import MeshtasticDataStore
from .device_manager import DeviceManager
from .message_bridge import MessageBridge
from .node_manager import NodeManager
from .router import create_router, create_compat_router


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
        self.data_store: MeshtasticDataStore | None = None
        self.device_manager: DeviceManager | None = None
        self.message_bridge: MessageBridge | None = None
        self.node_manager: NodeManager | None = None
        self._poll_task = None
        self._stats_task = None

    async def register(self, app):
        await super().register(app)

        # Resolve target_tracker from app.state.amy (where the Command Center stores it)
        target_tracker = None
        event_bus = None

        # Try app.state.amy first (the standard SC pattern)
        amy = getattr(getattr(app, 'state', None), 'amy', None)
        if amy is not None:
            target_tracker = getattr(amy, 'target_tracker', None)
            event_bus = getattr(amy, 'event_bus', None)

        # Fallback: direct attributes on app (for testing or alternate setups)
        if target_tracker is None:
            target_tracker = getattr(app, 'target_tracker', None)
        if event_bus is None:
            event_bus = getattr(app, 'event_bus', None)

        import logging
        log = logging.getLogger("meshtastic")
        if target_tracker:
            log.info("Meshtastic addon wired to TargetTracker")
        else:
            log.warning("Meshtastic addon: no TargetTracker found — mesh nodes will not appear on tactical map")

        # Reuse existing node_manager from app.state if available (preserves nodes across hot-reload)
        existing_nm = getattr(getattr(app, 'state', None), 'meshtastic_node_manager', None)
        if existing_nm and existing_nm.nodes:
            log.info(f"Reusing existing NodeManager with {len(existing_nm.nodes)} nodes")
            self.node_manager = existing_nm
            self.node_manager.event_bus = event_bus
            self.node_manager.target_tracker = target_tracker
        else:
            self.node_manager = NodeManager(
                event_bus=event_bus,
                target_tracker=target_tracker,
            )
        if hasattr(app, 'state'):
            app.state.meshtastic_node_manager = self.node_manager

        # Reuse existing connection from app.state if available (survives hot-reload)
        existing_conn = getattr(getattr(app, 'state', None), 'meshtastic_connection', None)
        if existing_conn and existing_conn.interface is not None:
            log.info("Reusing existing Meshtastic connection from app.state")
            self.connection = existing_conn
            self.connection.node_manager = self.node_manager
            self.connection.event_bus = event_bus
        else:
            self.connection = ConnectionManager(
                node_manager=self.node_manager,
                event_bus=event_bus,
            )
        # Store on app.state so it survives hot-reload
        if hasattr(app, 'state'):
            app.state.meshtastic_connection = self.connection

        # Device manager for config/firmware/control
        self.device_manager = DeviceManager(self.connection)

        # Message bridge — bidirectional mesh <-> Tritium messaging
        mqtt_bridge = getattr(app, 'mqtt_bridge', None)
        if mqtt_bridge is None:
            mqtt_bridge = getattr(getattr(app, 'state', None), 'mqtt_bridge', None)
        site_id = getattr(app, 'site_id', 'home')

        self.message_bridge = MessageBridge(
            connection=self.connection,
            node_manager=self.node_manager,
            event_bus=event_bus,
            mqtt_bridge=mqtt_bridge,
            site_id=site_id,
            data_store=self.data_store,
        )

        # Add API routes
        router = create_router(self.connection, self.node_manager, self.message_bridge)
        if hasattr(app, 'include_router'):
            app.include_router(router, prefix="/api/addons/meshtastic", tags=["meshtastic"])

            # Add device management routes
            from .device_manager import create_device_routes
            device_router = create_device_routes(self.device_manager)
            app.include_router(device_router, prefix="/api/addons/meshtastic", tags=["meshtastic-device"])

        # Initialize persistent data store
        self.data_store = MeshtasticDataStore()
        try:
            await self.data_store.initialize()
            log.info("Meshtastic persistent data store ready")
        except Exception as e:
            log.warning(f"Meshtastic data store init failed (non-fatal): {e}")
            self.data_store = None

        # Auto-detect and connect — skip if already connected (prevents rapid reconnect)
        if not self.connection.is_connected:
            try:
                await self.connection.auto_connect()
            except Exception as e:
                log.warning(f"Meshtastic auto-connect failed (will retry via API): {e}")
        else:
            log.info("Meshtastic already connected, skipping auto-connect")

        # Register message bridge callbacks after connection attempt
        self.message_bridge.register_callbacks()

        # Start polling loop and stats snapshot loop
        import asyncio
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._background_tasks.append(self._poll_task)
        self._stats_task = asyncio.create_task(self._stats_loop())
        self._background_tasks.append(self._stats_task)

    async def unregister(self, app):
        if self.message_bridge:
            self.message_bridge.unregister_callbacks()
            self.message_bridge = None
        if self.connection:
            await self.connection.disconnect()
            self.connection = None
        if self.data_store:
            await self.data_store.close()
            self.data_store = None
        self.node_manager = None
        await super().unregister(app)

    async def gather(self):
        """Return current mesh nodes as target dicts."""
        if not self.node_manager:
            return []
        return self.node_manager.get_targets()

    async def _poll_loop(self):
        """Background loop: poll device for node updates and persist to data store."""
        import asyncio
        while self._registered:
            try:
                if self.connection and self.connection.is_connected:
                    nodes = await self.connection.get_nodes()
                    if nodes and self.node_manager:
                        self.node_manager.update_nodes(nodes)

                        # Persist each node to the data store
                        if self.data_store:
                            for node_id, node_data in self.node_manager.nodes.items():
                                try:
                                    await self.data_store.store_node(node_data)
                                except Exception as e:
                                    import logging
                                    logging.getLogger("meshtastic").debug(
                                        f"Data store error for {node_id}: {e}"
                                    )
            except Exception as e:
                import logging
                logging.getLogger("meshtastic").warning(f"Poll error: {e}")
            await asyncio.sleep(10)

    async def _stats_loop(self):
        """Background loop: periodic network stats snapshots (every 5 minutes)."""
        import asyncio
        while self._registered:
            await asyncio.sleep(300)  # 5 minutes
            try:
                if self.node_manager and self.data_store:
                    stats = self.node_manager.get_stats()
                    await self.data_store.store_stats_snapshot(stats)
            except Exception as e:
                import logging
                logging.getLogger("meshtastic").debug(f"Stats snapshot error: {e}")

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
