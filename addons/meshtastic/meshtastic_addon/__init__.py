# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Meshtastic LoRa Mesh addon for Tritium.

Connects to Meshtastic devices via USB serial, Bluetooth, WiFi/TCP, or MQTT.
Each mesh node becomes a tracked target on the tactical map.
"""

from tritium_lib.sdk import SensorAddon, AddonInfo, DeviceRegistry, DeviceState

from .connection import ConnectionManager, detect_meshtastic_ports
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
        # Multi-radio support via DeviceRegistry
        self.registry = DeviceRegistry("meshtastic")
        self._connections: dict[str, ConnectionManager] = {}  # device_id -> ConnectionManager
        self._node_managers: dict[str, NodeManager] = {}  # device_id -> NodeManager
        # Legacy single-radio aliases (point to primary radio)
        self.connection: ConnectionManager | None = None
        self.node_manager: NodeManager | None = None
        self.data_store: MeshtasticDataStore | None = None
        self.device_manager: DeviceManager | None = None
        self.message_bridge: MessageBridge | None = None
        self._poll_task = None
        self._stats_task = None

    def _get_primary_connection(self) -> ConnectionManager | None:
        """Return the first connected ConnectionManager, or the first one registered."""
        for conn in self._connections.values():
            if conn.is_connected:
                return conn
        # Fall back to any registered connection
        if self._connections:
            return next(iter(self._connections.values()))
        return None

    def _get_aggregate_node_manager(self, event_bus=None, target_tracker=None) -> NodeManager:
        """Return an aggregate NodeManager that merges nodes from all radios.

        Each node gets a 'bridge_id' field indicating which radio it came from.
        """
        if self.node_manager is None:
            self.node_manager = NodeManager(
                event_bus=event_bus,
                target_tracker=target_tracker,
            )
        return self.node_manager

    def _sync_aggregate_nodes(self):
        """Merge nodes from all per-device NodeManagers into the aggregate."""
        if not self.node_manager:
            return
        merged: dict[str, dict] = {}
        for device_id, nm in self._node_managers.items():
            for node_id, node_data in nm.nodes.items():
                # Add bridge_id to track which radio reported this node
                node_copy = dict(node_data)
                node_copy["bridge_id"] = device_id
                # If node already seen from another radio, keep the one with
                # the most recent last_heard timestamp
                existing = merged.get(node_id)
                if existing is None or (node_copy.get("last_heard", 0) > existing.get("last_heard", 0)):
                    merged[node_id] = node_copy
        self.node_manager.nodes = merged

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
            self.node_manager = self._get_aggregate_node_manager(
                event_bus=event_bus,
                target_tracker=target_tracker,
            )
        if hasattr(app, 'state'):
            app.state.meshtastic_node_manager = self.node_manager

        # Reuse existing connections from app.state if available (survives hot-reload)
        existing_connections = getattr(getattr(app, 'state', None), 'meshtastic_connections', None)
        existing_registry = getattr(getattr(app, 'state', None), 'meshtastic_registry', None)
        if existing_connections and isinstance(existing_connections, dict):
            log.info(f"Reusing {len(existing_connections)} existing Meshtastic connections from app.state")
            self._connections = existing_connections
            self._node_managers = getattr(getattr(app, 'state', None), 'meshtastic_node_managers', {})
            if existing_registry:
                self.registry = existing_registry
            # Update event_bus and node_manager refs on all existing connections
            for conn in self._connections.values():
                conn.event_bus = event_bus
        else:
            # Auto-detect serial ports and create a ConnectionManager per device
            detected = detect_meshtastic_ports()
            if detected:
                for port_info in detected:
                    device_id = port_info["device_id"]
                    try:
                        self.registry.add_device(
                            device_id=device_id,
                            device_type="meshtastic",
                            transport_type="serial",
                            metadata=port_info,
                        )
                    except ValueError:
                        pass  # Already registered

                    per_device_nm = NodeManager(event_bus=event_bus, target_tracker=None)
                    self._node_managers[device_id] = per_device_nm

                    conn = ConnectionManager(
                        node_manager=per_device_nm,
                        event_bus=event_bus,
                    )
                    self._connections[device_id] = conn
                    log.info(f"Registered Meshtastic device: {device_id} on {port_info['port']}")
            else:
                # No ports detected — create a single default connection for manual/TCP/BLE/MQTT
                default_id = "mesh-default"
                try:
                    self.registry.add_device(
                        device_id=default_id,
                        device_type="meshtastic",
                        transport_type="serial",
                        metadata={"port": "", "transport": "none"},
                    )
                except ValueError:
                    pass
                per_device_nm = NodeManager(event_bus=event_bus, target_tracker=None)
                self._node_managers[default_id] = per_device_nm
                conn = ConnectionManager(
                    node_manager=per_device_nm,
                    event_bus=event_bus,
                )
                self._connections[default_id] = conn
                log.info("No serial ports detected — created default connection for manual connect")

        # Also support legacy single-connection from app.state
        existing_conn = getattr(getattr(app, 'state', None), 'meshtastic_connection', None)
        if existing_conn and existing_conn.interface is not None:
            log.info("Reusing legacy single Meshtastic connection from app.state")
            # Add it to our multi-radio tracking if not already there
            legacy_id = "mesh-legacy"
            if legacy_id not in self._connections:
                self._connections[legacy_id] = existing_conn
                existing_conn.node_manager = self._node_managers.get(legacy_id, self.node_manager)
                existing_conn.event_bus = event_bus
                try:
                    self.registry.add_device(
                        device_id=legacy_id,
                        device_type="meshtastic",
                        transport_type=existing_conn.transport_type,
                        metadata={"port": existing_conn.port},
                    )
                    self.registry.set_state(legacy_id, DeviceState.CONNECTED)
                except ValueError:
                    pass

        # Set self.connection as alias to primary (first/connected) radio
        self.connection = self._get_primary_connection()

        # Store on app.state so they survive hot-reload
        if hasattr(app, 'state'):
            app.state.meshtastic_connection = self.connection
            app.state.meshtastic_connections = self._connections
            app.state.meshtastic_node_managers = self._node_managers
            app.state.meshtastic_registry = self.registry

        # Device manager for config/firmware/control (uses primary connection)
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

        # Add API routes (pass registry and connections for multi-radio endpoints)
        router = create_router(
            self.connection, self.node_manager, self.message_bridge,
            registry=self.registry,
            connections=self._connections,
            node_managers=self._node_managers,
        )
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

        # Auto-connect all detected radios
        for device_id, conn in self._connections.items():
            if conn.is_connected:
                log.info(f"Device {device_id} already connected, skipping auto-connect")
                self.registry.set_state(device_id, DeviceState.CONNECTED)
                continue
            dev = self.registry.get_device(device_id)
            port = dev.metadata.get("port", "") if dev else ""
            if port:
                try:
                    self.registry.set_state(device_id, DeviceState.CONNECTING)
                    await conn.connect_serial(port, timeout=60, noNodes=True)
                    if conn.is_connected:
                        self.registry.set_state(device_id, DeviceState.CONNECTED)
                        self.registry.touch(device_id)
                        log.info(f"Connected to {device_id} on {port}")
                    else:
                        self.registry.set_state(device_id, DeviceState.ERROR, error="connect failed")
                except Exception as e:
                    log.warning(f"Auto-connect failed for {device_id}: {e}")
                    self.registry.set_state(device_id, DeviceState.ERROR, error=str(e))
            else:
                # No port — try auto_connect (TCP/BLE/MQTT from env vars)
                try:
                    await conn.auto_connect()
                    if conn.is_connected:
                        self.registry.set_state(device_id, DeviceState.CONNECTED)
                        self.registry.touch(device_id)
                except Exception as e:
                    log.warning(f"Auto-connect failed for {device_id}: {e}")

        # Update primary connection alias after auto-connect
        self.connection = self._get_primary_connection()
        if hasattr(app, 'state'):
            app.state.meshtastic_connection = self.connection

        # Register message bridge callbacks after connection attempt
        self.message_bridge.register_callbacks()

        # Wire up MQTT bridge for remote Meshtastic radios
        self._mqtt_remote_bridge = None
        mqtt_client = mqtt_bridge  # already resolved above
        if mqtt_client is not None:
            from .mqtt_bridge import MeshtasticMQTTBridge
            self._mqtt_remote_bridge = MeshtasticMQTTBridge(
                self.registry, self._node_managers,
                site_id=site_id,
                event_bus=event_bus,
                target_tracker=target_tracker,
            )
            self._mqtt_remote_bridge.start(mqtt_client)
            log.info("Meshtastic MQTT remote bridge started for remote radio ingestion")

        # Start polling loop and stats snapshot loop
        import asyncio
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._background_tasks.append(self._poll_task)
        self._stats_task = asyncio.create_task(self._stats_loop())
        self._background_tasks.append(self._stats_task)

    async def unregister(self, app):
        # Stop MQTT remote bridge
        if self._mqtt_remote_bridge:
            self._mqtt_remote_bridge.stop()
            self._mqtt_remote_bridge = None

        if self.message_bridge:
            self.message_bridge.unregister_callbacks()
            self.message_bridge = None
        # Disconnect all radios
        for device_id, conn in self._connections.items():
            try:
                await conn.disconnect()
            except Exception:
                pass
            self.registry.set_state(device_id, DeviceState.DISCONNECTED)
        self._connections.clear()
        self._node_managers.clear()
        self.connection = None
        if self.data_store:
            await self.data_store.close()
            self.data_store = None
        self.node_manager = None
        await super().unregister(app)

    async def gather(self):
        """Return current mesh nodes as target dicts (aggregated from all radios)."""
        # Sync nodes from all per-device managers into aggregate
        self._sync_aggregate_nodes()
        if not self.node_manager:
            return []
        return self.node_manager.get_targets()

    async def _poll_loop(self):
        """Background loop: poll all devices for node updates and persist to data store."""
        import asyncio
        from pathlib import Path
        while self._registered:
            try:
                for device_id, conn in list(self._connections.items()):
                    if conn.is_connected:
                        # Check if serial port still exists
                        if conn.transport_type == "serial" and conn.port:
                            if not Path(conn.port).exists():
                                import logging
                                logging.getLogger("meshtastic").warning(
                                    f"Serial port {conn.port} disappeared — device {device_id} unplugged"
                                )
                                conn.is_connected = False
                                conn._close_interface()
                                self.registry.set_state(device_id, DeviceState.DISCONNECTED)
                                continue

                        nodes = await conn.get_nodes()
                        per_nm = self._node_managers.get(device_id)
                        if nodes and per_nm:
                            per_nm.update_nodes(nodes)

                        # Persist each node to the data store
                        if nodes and per_nm and self.data_store:
                            for node_id, node_data in per_nm.nodes.items():
                                try:
                                    await self.data_store.store_node(node_data)
                                except Exception as e:
                                    import logging
                                    logging.getLogger("meshtastic").debug(
                                        f"Data store error for {node_id}: {e}"
                                    )
                    elif not conn.is_connected:
                        # Not connected — try to auto-reconnect if port exists
                        dev = self.registry.get_device(device_id)
                        port = (dev.metadata.get("port", "") if dev else "") or conn.port or ""
                        if port and Path(port).exists():
                            import logging
                            logging.getLogger("meshtastic").info(
                                f"Port {port} detected — attempting reconnect for {device_id}"
                            )
                            try:
                                await conn.connect_serial(port, timeout=30, noNodes=True)
                                if conn.is_connected:
                                    self.registry.set_state(device_id, DeviceState.CONNECTED)
                                    self.registry.touch(device_id)
                            except Exception:
                                pass

                # Sync aggregate node manager after polling all devices
                self._sync_aggregate_nodes()

                # Update primary connection alias
                self.connection = self._get_primary_connection()

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
                    self._sync_aggregate_nodes()
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
        """Health check aggregated across all radios."""
        total_connected = sum(1 for c in self._connections.values() if c.is_connected)
        total_devices = len(self._connections)
        node_count = len(self.node_manager.nodes) if self.node_manager else 0

        if total_connected == 0:
            status = "degraded"
        elif total_connected < total_devices:
            status = "partial"
        else:
            status = "ok"

        return {
            "status": status,
            "connected": total_connected > 0,
            "total_radios": total_devices,
            "connected_radios": total_connected,
            "transport": self.connection.transport_type if self.connection else None,
            "device_port": self.connection.port if self.connection else None,
            "node_count": node_count,
            "devices": self.registry.to_dict()["devices"] if self.registry else {},
        }
