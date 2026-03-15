# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FleetDashboardPlugin — aggregated fleet device registry and dashboard API.

Subscribes to fleet.heartbeat and edge:ble_update events on the EventBus,
maintains an in-memory device registry with status tracking, and exposes
REST endpoints for the fleet dashboard frontend panel.

Devices not seen within PRUNE_TIMEOUT_S are pruned automatically.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Optional

from engine.plugins.base import EventDrainPlugin, PluginContext

log = logging.getLogger("fleet-dashboard")

PRUNE_TIMEOUT_S = 300  # 5 minutes
TARGET_HISTORY_MAXLEN = 60  # Keep 60 data points per device (1 per minute = 1 hour)
ANALYTICS_HISTORY_MAXLEN = 1440  # 24h at 1-minute granularity

# Device lifecycle states
DEVICE_STATES = {"provisioning", "active", "maintenance", "retired", "error"}
VALID_STATE_TRANSITIONS = {
    "provisioning": {"active", "error", "retired"},
    "active": {"maintenance", "retired", "error"},
    "maintenance": {"active", "retired", "error"},
    "retired": {"provisioning"},
    "error": {"maintenance", "provisioning", "retired"},
}


class FleetDashboardPlugin(EventDrainPlugin):
    """Aggregated fleet device registry with dashboard API."""

    def __init__(self) -> None:
        super().__init__()
        self._prune_thread: Optional[threading.Thread] = None

        # device_id -> device info dict
        self._devices: dict[str, dict] = {}
        self._lock = threading.Lock()

        # Target count history per device: device_id -> list of {ts, count}
        self._target_history: dict[str, list[dict]] = {}

        # Fleet coordination state
        self._device_groups: dict[str, dict] = {}  # group_id -> group info
        self._fleet_commands: list[dict] = []  # command history
        self._config_templates: dict[str, dict] = {}  # template_id -> template
        self._analytics_history: list[dict] = []  # periodic snapshots

        # Device lifecycle tracking: device_id -> {state, since, history}
        self._lifecycle: dict[str, dict] = {}

        # Initialize built-in templates
        self._init_builtin_templates()

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.fleet-dashboard"

    @property
    def name(self) -> str:
        return "Fleet Dashboard"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "ui"}

    # -- EventDrainPlugin overrides ----------------------------------------

    def _on_configure(self, ctx: PluginContext) -> None:
        self._register_routes()
        self._logger.info("Fleet Dashboard plugin configured")

    def _on_start(self) -> None:
        self._prune_thread = threading.Thread(
            target=self._prune_loop,
            daemon=True,
            name="fleet-dashboard-prune",
        )
        self._prune_thread.start()
        self._logger.info("Fleet Dashboard plugin started")

    def _on_stop(self) -> None:
        if self._prune_thread and self._prune_thread.is_alive():
            self._prune_thread.join(timeout=2.0)
        self._logger.info("Fleet Dashboard plugin stopped")

    def _handle_event(self, event: dict) -> None:
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type == "fleet.heartbeat":
            self._on_heartbeat(data)
        elif event_type == "edge:ble_update":
            self._on_ble_update(data)

    # -- Device registry ---------------------------------------------------

    def get_devices(self) -> list[dict]:
        """Return list of all tracked devices with computed status."""
        now = time.time()
        with self._lock:
            result = []
            for dev in self._devices.values():
                entry = dict(dev)
                age = now - entry.get("last_seen", 0)
                if age > 180:
                    entry["status"] = "offline"
                elif age > 60:
                    entry["status"] = "stale"
                else:
                    entry["status"] = "online"
                result.append(entry)
            return result

    def get_device(self, device_id: str) -> Optional[dict]:
        """Return a single device by ID, or None."""
        now = time.time()
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return None
            entry = dict(dev)
            age = now - entry.get("last_seen", 0)
            if age > 180:
                entry["status"] = "offline"
            elif age > 60:
                entry["status"] = "stale"
            else:
                entry["status"] = "online"
            return entry

    def get_target_history(self, device_id: str) -> list[dict]:
        """Return target count history for sparkline rendering."""
        with self._lock:
            return list(self._target_history.get(device_id, []))

    def get_all_target_histories(self) -> dict[str, list[dict]]:
        """Return target count histories for all devices."""
        with self._lock:
            return {did: list(h) for did, h in self._target_history.items()}

    def get_topology(self) -> dict:
        """Build network topology from device registry for comm-link visualization.

        Returns nodes (fleet devices with positions) and links (peer connections
        extracted from heartbeat mesh_peers data).
        """
        devices = self.get_devices()
        nodes = []
        links = []
        seen_edges: set[tuple[str, str]] = set()

        for dev in devices:
            did = dev.get("device_id", "")
            nodes.append({
                "node_id": did,
                "name": dev.get("name", did),
                "ip": dev.get("ip", ""),
                "online": dev.get("status") == "online",
                "battery": dev.get("battery"),
                "peer_count": 0,
                # Position: use stored lat/lng or derive from x/y
                "x": dev.get("x", 0),
                "y": dev.get("y", 0),
                "lat": dev.get("lat"),
                "lng": dev.get("lng"),
            })

        # Extract peer links from heartbeat mesh_peers data
        with self._lock:
            for did, dev in self._devices.items():
                peers = dev.get("mesh_peers", [])
                if not peers:
                    continue

                # Update node peer_count
                for node in nodes:
                    if node["node_id"] == did:
                        node["peer_count"] = len(peers)
                        break

                for peer in peers:
                    peer_mac = peer.get("mac", "")
                    if not peer_mac:
                        continue

                    # Dedup edges (A->B == B->A)
                    edge_key = tuple(sorted((did, peer_mac)))
                    if edge_key in seen_edges:
                        continue
                    seen_edges.add(edge_key)

                    quality = peer.get("quality", {})
                    links.append({
                        "source_id": did,
                        "target_id": peer_mac,
                        "transport": "espnow",
                        "rssi": peer.get("rssi"),
                        "quality_score": quality.get("score", 0) if isinstance(quality, dict) else 0,
                        "packet_loss_pct": quality.get("pkt_loss", 0) if isinstance(quality, dict) else 0,
                        "active": True,
                    })

        return {
            "nodes": nodes,
            "links": links,
            "node_count": len(nodes),
            "link_count": len(links),
        }

    def get_summary(self) -> dict:
        """Return fleet summary: counts by status, avg battery, total sightings."""
        devices = self.get_devices()
        online = sum(1 for d in devices if d["status"] == "online")
        stale = sum(1 for d in devices if d["status"] == "stale")
        offline = sum(1 for d in devices if d["status"] == "offline")
        batteries = [
            d["battery"] for d in devices
            if d.get("battery") is not None
        ]
        avg_battery = (
            round(sum(batteries) / len(batteries), 1)
            if batteries else None
        )
        total_ble = sum(d.get("ble_count", 0) for d in devices)
        total_wifi = sum(d.get("wifi_count", 0) for d in devices)
        return {
            "total": len(devices),
            "online": online,
            "stale": stale,
            "offline": offline,
            "avg_battery": avg_battery,
            "total_ble_sightings": total_ble,
            "total_wifi_sightings": total_wifi,
        }

    # -- Event handling ----------------------------------------------------

    def _on_ble_update(self, data: dict) -> None:
        """Handle edge:ble_update — update BLE counts for relevant devices."""
        count = data.get("count", 0)
        devices = data.get("devices", [])

        # Try to attribute BLE count to a specific device
        node_ids = set()
        for dev in devices:
            nid = dev.get("node_id")
            if nid:
                node_ids.add(nid)

        now = time.time()
        with self._lock:
            for nid in node_ids:
                if nid in self._devices:
                    self._devices[nid]["ble_count"] = count
                    self._devices[nid]["last_seen"] = now

    # -- Pruning -----------------------------------------------------------

    def _prune_loop(self) -> None:
        while self._running:
            time.sleep(30)
            self._prune_stale()

    def _prune_stale(self) -> None:
        now = time.time()
        with self._lock:
            stale_ids = [
                did for did, dev in self._devices.items()
                if now - dev.get("last_seen", 0) > PRUNE_TIMEOUT_S
            ]
            for did in stale_ids:
                del self._devices[did]
                log.debug("Pruned stale device: %s", did)

    # -- Built-in templates ------------------------------------------------

    def _init_builtin_templates(self) -> None:
        """Initialize built-in configuration templates."""
        self._config_templates = {
            "perimeter_high_security": {
                "id": "perimeter_high_security",
                "name": "Perimeter - High Security",
                "description": "Fast scan rates for perimeter nodes. Maximum detection speed.",
                "ble_scan_interval_ms": 5000,
                "wifi_scan_interval_ms": 15000,
                "heartbeat_interval_ms": 15000,
                "sighting_interval_ms": 5000,
                "power_mode": "high_performance",
                "builtin": True,
            },
            "indoor_normal": {
                "id": "indoor_normal",
                "name": "Indoor - Normal",
                "description": "Balanced scan rates for indoor monitoring.",
                "ble_scan_interval_ms": 10000,
                "wifi_scan_interval_ms": 30000,
                "heartbeat_interval_ms": 30000,
                "sighting_interval_ms": 15000,
                "power_mode": "normal",
                "builtin": True,
            },
            "power_saver_mobile": {
                "id": "power_saver_mobile",
                "name": "Power Saver - Mobile",
                "description": "Reduced scan rates for battery-powered mobile nodes.",
                "ble_scan_interval_ms": 30000,
                "wifi_scan_interval_ms": 60000,
                "heartbeat_interval_ms": 60000,
                "sighting_interval_ms": 30000,
                "power_mode": "low_power",
                "builtin": True,
            },
        }

    # -- Fleet coordination ------------------------------------------------

    def send_fleet_command(
        self,
        target_group: str,
        command_type: str,
        payload: Optional[dict] = None,
    ) -> dict:
        """Send a command to all devices in a group via MQTT broadcast.

        Returns the command record with status tracking.
        """
        cmd_id = str(uuid.uuid4())[:8]
        now = time.time()

        # Count expected targets
        devices = self.get_devices()
        group_devices = [
            d for d in devices
            if d.get("device_group") == target_group
            or target_group == "__all__"
        ]

        command = {
            "id": cmd_id,
            "command_type": command_type,
            "target_group": target_group,
            "payload": payload or {},
            "status": "broadcasting",
            "created_at": now,
            "expected_targets": len(group_devices),
            "acked_targets": 0,
            "failed_targets": 0,
            "ack_device_ids": [],
            "fail_device_ids": [],
        }

        # Publish to MQTT for each device in the group
        mqtt_published = 0
        if self._event_bus is not None:
            for dev in group_devices:
                device_id = dev.get("device_id", "")
                if not device_id:
                    continue
                # Publish command via event bus (MQTT bridge picks it up)
                cmd_event = {
                    "type": "fleet.command",
                    "data": {
                        "device_id": device_id,
                        "command_type": command_type,
                        "target_group": target_group,
                        "command_id": cmd_id,
                        "payload": payload or {},
                    },
                }
                self._event_bus.publish("fleet.command", cmd_event)
                mqtt_published += 1

        command["mqtt_published"] = mqtt_published
        if mqtt_published == 0 and len(group_devices) == 0:
            command["status"] = "complete"
        elif mqtt_published == 0:
            command["status"] = "failed"
            command["error"] = "No MQTT connection or event bus"

        with self._lock:
            self._fleet_commands.append(command)
            # Keep last 100 commands
            if len(self._fleet_commands) > 100:
                self._fleet_commands = self._fleet_commands[-100:]

        self._logger.info(
            "Fleet command %s: %s -> group '%s' (%d devices)",
            cmd_id, command_type, target_group, mqtt_published,
        )
        return command

    def get_fleet_commands(self, limit: int = 50) -> list[dict]:
        """Return recent fleet command history."""
        with self._lock:
            return list(reversed(self._fleet_commands[-limit:]))

    def get_devices_in_group(self, group: str) -> list[dict]:
        """Return all devices belonging to a specific group."""
        devices = self.get_devices()
        return [d for d in devices if d.get("device_group") == group]

    def get_groups(self) -> dict[str, list[dict]]:
        """Return all groups and their devices."""
        devices = self.get_devices()
        groups: dict[str, list[dict]] = {}
        for dev in devices:
            grp = dev.get("device_group", "")
            if grp:
                if grp not in groups:
                    groups[grp] = []
                groups[grp].append(dev)
        return groups

    # -- Config templates --------------------------------------------------

    def get_config_templates(self) -> list[dict]:
        """Return all configuration templates."""
        with self._lock:
            return list(self._config_templates.values())

    def get_config_template(self, template_id: str) -> Optional[dict]:
        """Return a single template by ID."""
        with self._lock:
            return self._config_templates.get(template_id)

    def create_config_template(self, template: dict) -> dict:
        """Create a new custom configuration template."""
        tid = template.get("id", str(uuid.uuid4())[:8])
        template["id"] = tid
        template["builtin"] = False
        template["created_at"] = time.time()
        with self._lock:
            self._config_templates[tid] = template
        self._logger.info("Created config template: %s (%s)", tid, template.get("name"))
        return template

    def apply_template_to_group(self, template_id: str, group: str) -> dict:
        """Apply a config template to all devices in a group.

        Sends config_update commands via MQTT with template parameters.
        """
        template = self.get_config_template(template_id)
        if not template:
            return {"error": f"Template '{template_id}' not found", "status": "failed"}

        payload = {
            "template_id": template_id,
            "ble_scan_interval_ms": template.get("ble_scan_interval_ms", 10000),
            "wifi_scan_interval_ms": template.get("wifi_scan_interval_ms", 30000),
            "heartbeat_interval_ms": template.get("heartbeat_interval_ms", 30000),
            "sighting_interval_ms": template.get("sighting_interval_ms", 15000),
            "power_mode": template.get("power_mode", "normal"),
        }
        return self.send_fleet_command(group, "apply_template", payload)

    # -- Fleet analytics ---------------------------------------------------

    def get_analytics_snapshot(self) -> dict:
        """Compute a current fleet analytics snapshot."""
        now = time.time()
        devices = self.get_devices()

        online_devs = [d for d in devices if d.get("status") == "online"]
        offline_devs = [d for d in devices if d.get("status") == "offline"]

        # Uptime trends from current data
        uptime_records = []
        for dev in devices:
            uptime_records.append({
                "device_id": dev.get("device_id", ""),
                "timestamp": now,
                "uptime_s": dev.get("uptime", 0) or 0,
                "online": dev.get("status") == "online",
            })

        # Sighting rates from sparkline data
        sighting_rates = []
        with self._lock:
            for did, history in self._target_history.items():
                if len(history) >= 2:
                    # Calculate rate from last two data points
                    last = history[-1]
                    prev = history[-2]
                    dt = last["ts"] - prev["ts"]
                    if dt > 0:
                        rate = (last["count"] - prev["count"]) / (dt / 60.0)
                    else:
                        rate = 0.0
                else:
                    rate = 0.0
                sighting_rates.append({
                    "device_id": did,
                    "timestamp": now,
                    "rate": round(rate, 2),
                })

        # Group distribution
        groups: dict[str, int] = {}
        for dev in devices:
            grp = dev.get("device_group", "unassigned")
            groups[grp] = groups.get(grp, 0) + 1

        # Batteries
        batteries = [d["battery"] for d in devices if d.get("battery") is not None]
        avg_battery = round(sum(batteries) / len(batteries), 1) if batteries else None

        # Uptimes
        uptimes = [d.get("uptime", 0) or 0 for d in devices]
        avg_uptime = round(sum(uptimes) / len(uptimes), 1) if uptimes else 0.0

        snapshot = {
            "timestamp": now,
            "total_devices": len(devices),
            "online_devices": len(online_devs),
            "offline_devices": len(offline_devs),
            "avg_uptime_s": avg_uptime,
            "avg_battery_pct": avg_battery,
            "total_ble_sightings": sum(d.get("ble_count", 0) for d in devices),
            "total_wifi_sightings": sum(d.get("wifi_count", 0) for d in devices),
            "uptime_records": uptime_records,
            "sighting_rates": sighting_rates,
            "groups": groups,
        }

        # Store in history
        with self._lock:
            self._analytics_history.append(snapshot)
            if len(self._analytics_history) > ANALYTICS_HISTORY_MAXLEN:
                self._analytics_history = self._analytics_history[-ANALYTICS_HISTORY_MAXLEN:]

        return snapshot

    def get_analytics_history(self, hours: int = 24) -> list[dict]:
        """Return analytics snapshots for the given time window."""
        cutoff = time.time() - (hours * 3600)
        with self._lock:
            return [s for s in self._analytics_history if s["timestamp"] >= cutoff]

    def get_coverage_map(self) -> list[dict]:
        """Return coverage map showing areas with sensor overlap.

        Uses device positions (lat/lng) to compute coverage regions.
        """
        devices = self.get_devices()
        coverage: list[dict] = []

        # Build coverage from devices with known positions
        positioned = [
            d for d in devices
            if d.get("lat") is not None and d.get("lng") is not None
        ]
        for dev in positioned:
            coverage.append({
                "lat": dev["lat"],
                "lng": dev["lng"],
                "sensor_count": 1,
                "device_ids": [dev.get("device_id", "")],
                "status": dev.get("status", "unknown"),
            })

        return coverage

    # -- Heartbeat update with device_group tracking -----------------------

    def _on_heartbeat(self, data: dict) -> None:
        device_id = data.get("device_id", data.get("id", data.get("node_id")))
        if not device_id:
            return

        now = time.time()
        with self._lock:
            existing = self._devices.get(device_id, {})
            existing.update({
                "device_id": device_id,
                "name": data.get("name", data.get("hostname", existing.get("name", device_id))),
                "ip": data.get("ip", existing.get("ip", "")),
                "battery": data.get("battery_pct", data.get("battery", existing.get("battery"))),
                "uptime": data.get("uptime_s", data.get("uptime", existing.get("uptime"))),
                "ble_count": data.get("ble_count", data.get("ble_device_count", existing.get("ble_count", 0))),
                "wifi_count": data.get("wifi_count", data.get("wifi_network_count", existing.get("wifi_count", 0))),
                "free_heap": data.get("free_heap", existing.get("free_heap")),
                "firmware": data.get("version", data.get("firmware", existing.get("firmware", ""))),
                "rssi": data.get("rssi", data.get("wifi_rssi", existing.get("rssi"))),
                "last_seen": now,
            })
            # Track device group from heartbeat
            device_group = data.get("device_group", existing.get("device_group", ""))
            if device_group:
                existing["device_group"] = device_group

            # Track position if available
            lat = data.get("lat", existing.get("lat"))
            lng = data.get("lng", existing.get("lng"))
            if lat is not None:
                existing["lat"] = lat
            if lng is not None:
                existing["lng"] = lng

            # Track device lifecycle state from heartbeat
            device_lifecycle_state = data.get("lifecycle_state")
            if device_lifecycle_state and device_lifecycle_state in DEVICE_STATES:
                existing["lifecycle_state"] = device_lifecycle_state
                # Auto-initialize lifecycle tracking if not already set
                if device_id not in self._lifecycle:
                    self._lifecycle[device_id] = {
                        "device_id": device_id,
                        "state": device_lifecycle_state,
                        "state_since": now,
                        "transition_count": 0,
                        "history": [],
                    }

            # Store mesh peer data for topology visualization
            mesh_peers = data.get("mesh_peers", data.get("peers", []))
            if mesh_peers:
                existing["mesh_peers"] = mesh_peers
            self._devices[device_id] = existing

            # Record target count for sparkline history
            target_count = existing.get("ble_count", 0) + existing.get("wifi_count", 0)
            if device_id not in self._target_history:
                self._target_history[device_id] = []
            history = self._target_history[device_id]
            history.append({"ts": now, "count": target_count})
            # Trim to max length
            if len(history) > TARGET_HISTORY_MAXLEN:
                self._target_history[device_id] = history[-TARGET_HISTORY_MAXLEN:]

    # -- Fleet health summary ----------------------------------------------

    def get_health_summary(self) -> dict:
        """Aggregate fleet health: device counts, avg battery, avg sighting rate,
        sensor health summary, and lifecycle state distribution."""
        devices = self.get_devices()
        now = time.time()

        online = sum(1 for d in devices if d["status"] == "online")
        stale = sum(1 for d in devices if d["status"] == "stale")
        offline = sum(1 for d in devices if d["status"] == "offline")

        # Battery stats
        batteries = [d["battery"] for d in devices if d.get("battery") is not None]
        avg_battery = round(sum(batteries) / len(batteries), 1) if batteries else None
        low_battery_count = sum(1 for b in batteries if b < 20)

        # Sighting rates
        total_ble = sum(d.get("ble_count", 0) for d in devices)
        total_wifi = sum(d.get("wifi_count", 0) for d in devices)
        avg_sighting_rate = 0.0
        active_rates: list[float] = []
        with self._lock:
            for did, history in self._target_history.items():
                if len(history) >= 2:
                    last = history[-1]
                    prev = history[-2]
                    dt = last["ts"] - prev["ts"]
                    if dt > 0:
                        rate = (last["count"] - prev["count"]) / (dt / 60.0)
                        active_rates.append(rate)
        if active_rates:
            avg_sighting_rate = round(sum(active_rates) / len(active_rates), 2)

        # Sensor health: count devices with each sensor type active
        sensor_summary: dict[str, int] = {"ble": 0, "wifi": 0, "camera": 0, "mesh": 0}
        for d in devices:
            if d.get("ble_count", 0) > 0:
                sensor_summary["ble"] += 1
            if d.get("wifi_count", 0) > 0:
                sensor_summary["wifi"] += 1
            if d.get("mesh_peers"):
                sensor_summary["mesh"] += 1

        # Uptime stats
        uptimes = [d.get("uptime", 0) or 0 for d in devices]
        avg_uptime_s = round(sum(uptimes) / len(uptimes), 1) if uptimes else 0.0

        # Lifecycle state distribution
        lifecycle_counts = {s: 0 for s in DEVICE_STATES}
        with self._lock:
            for did in self._lifecycle:
                state = self._lifecycle[did].get("state", "active")
                if state in lifecycle_counts:
                    lifecycle_counts[state] += 1
            # Devices without explicit lifecycle are considered active
            tracked_ids = set(self._lifecycle.keys())
            for d in devices:
                did = d.get("device_id", "")
                if did and did not in tracked_ids:
                    lifecycle_counts["active"] += 1

        return {
            "total_devices": len(devices),
            "online": online,
            "stale": stale,
            "offline": offline,
            "avg_battery_pct": avg_battery,
            "low_battery_count": low_battery_count,
            "avg_sighting_rate_per_min": avg_sighting_rate,
            "total_ble_sightings": total_ble,
            "total_wifi_sightings": total_wifi,
            "sensor_health": sensor_summary,
            "avg_uptime_s": avg_uptime_s,
            "lifecycle": lifecycle_counts,
            "timestamp": now,
        }

    # -- Device lifecycle management ----------------------------------------

    def get_device_lifecycle(self, device_id: str) -> Optional[dict]:
        """Return lifecycle status for a device."""
        with self._lock:
            lc = self._lifecycle.get(device_id)
            if lc:
                return dict(lc)
        return None

    def set_device_state(
        self, device_id: str, new_state: str, reason: str = "", operator: str = "system"
    ) -> dict:
        """Transition a device to a new lifecycle state.

        Returns the updated lifecycle record or error dict.
        """
        if new_state not in DEVICE_STATES:
            return {"error": f"Invalid state: {new_state}", "valid_states": sorted(DEVICE_STATES)}

        now = time.time()
        with self._lock:
            lc = self._lifecycle.get(device_id)
            if lc is None:
                # First time — initialize
                lc = {
                    "device_id": device_id,
                    "state": "provisioning",
                    "state_since": now,
                    "transition_count": 0,
                    "history": [],
                }

            current_state = lc["state"]
            allowed = VALID_STATE_TRANSITIONS.get(current_state, set())
            if new_state not in allowed and current_state != new_state:
                return {
                    "error": f"Cannot transition from '{current_state}' to '{new_state}'",
                    "allowed_transitions": sorted(allowed),
                }

            if current_state == new_state:
                return dict(lc)

            # Record transition
            event = {
                "from_state": current_state,
                "to_state": new_state,
                "timestamp": now,
                "reason": reason,
                "operator": operator,
            }
            lc["history"].append(event)
            # Keep last 50 transitions
            if len(lc["history"]) > 50:
                lc["history"] = lc["history"][-50:]

            lc["state"] = new_state
            lc["state_since"] = now
            lc["transition_count"] = lc.get("transition_count", 0) + 1
            self._lifecycle[device_id] = lc

        self._logger.info(
            "Device %s: %s -> %s (reason: %s)", device_id, current_state, new_state, reason
        )
        return dict(lc)

    def get_all_lifecycle_states(self) -> dict[str, dict]:
        """Return lifecycle state for all tracked devices."""
        with self._lock:
            return {did: dict(lc) for did, lc in self._lifecycle.items()}

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
