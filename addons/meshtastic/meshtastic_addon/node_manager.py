# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Node manager — converts Meshtastic nodes into Tritium tracked targets."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

log = logging.getLogger("meshtastic.nodes")

# Role names from the meshtastic protobuf
ROLE_NAMES = {
    0: "CLIENT",
    1: "CLIENT_MUTE",
    2: "ROUTER",
    3: "ROUTER_CLIENT",
    4: "REPEATER",
    5: "TRACKER",
    6: "SENSOR",
    7: "TAK",
    8: "CLIENT_HIDDEN",
    9: "LOST_AND_FOUND",
    10: "TAK_TRACKER",
}


class NodeManager:
    """Manages mesh node state and converts to Tritium targets."""

    def __init__(self, event_bus=None, target_tracker=None):
        self.event_bus = event_bus
        self.target_tracker = target_tracker
        self.nodes: dict[str, dict] = {}  # node_id → node data
        self._last_update = 0.0
        self._local_node_id: str | None = None  # our own node ID
        self._hop_counts: dict[str, int] = {}  # node_id → estimated hop count

    def set_local_node(self, node_id: str):
        """Set our own node ID for hop count estimation."""
        self._local_node_id = node_id
        self._hop_counts[node_id] = 0

    def update_nodes(self, raw_nodes: dict):
        """Update internal node state from meshtastic library data.

        Args:
            raw_nodes: Dict from interface.nodes — keyed by node ID string.
        """
        updated = 0
        for node_id, raw in raw_nodes.items():
            node = self._parse_node(node_id, raw)
            if node:
                prev = self.nodes.get(node_id)
                self.nodes[node_id] = node
                updated += 1

                # Detect new nodes
                if prev is None and self.event_bus:
                    self.event_bus.publish("meshtastic:node_discovered", {
                        "node_id": node_id,
                        "name": node.get("long_name", node_id),
                    })

        self._last_update = time.time()

        # Estimate hop counts from neighbor data
        self._estimate_hops()

        # Emit targets to the TargetTracker via update_from_mesh()
        if self.target_tracker and updated > 0:
            targets = self.get_targets()
            for t in targets:
                try:
                    self.target_tracker.update_from_mesh(t)
                except Exception as e:
                    log.debug(f"Failed to update target tracker for {t.get('target_id')}: {e}")

        if self.event_bus and updated > 0:
            self.event_bus.publish("meshtastic:nodes_updated", {
                "count": updated,
                "total": len(self.nodes),
            })

        log.debug(f"Updated {updated} nodes ({len(self.nodes)} total)")

    def _estimate_hops(self):
        """Estimate hop count from local node using BFS over neighbor graph."""
        if not self._local_node_id:
            return

        # Build adjacency list from neighbor data
        adjacency: dict[str, set[str]] = {}
        for node_id, node in self.nodes.items():
            neighbors = node.get("neighbors", [])
            if node_id not in adjacency:
                adjacency[node_id] = set()
            for n in neighbors:
                adjacency[node_id].add(n)
                if n not in adjacency:
                    adjacency[n] = set()
                adjacency[n].add(node_id)

        # BFS from local node
        visited = {self._local_node_id: 0}
        queue = [self._local_node_id]
        while queue:
            current = queue.pop(0)
            current_hops = visited[current]
            for neighbor in adjacency.get(current, set()):
                if neighbor not in visited:
                    visited[neighbor] = current_hops + 1
                    queue.append(neighbor)

        self._hop_counts = visited

        # Nodes not reachable via neighbor data get SNR-based estimate
        for node_id in self.nodes:
            if node_id not in self._hop_counts:
                snr = self.nodes[node_id].get("snr")
                if snr is not None:
                    # Rough estimate: direct = 1, weak = 2-3
                    if snr > 5:
                        self._hop_counts[node_id] = 1
                    elif snr > -5:
                        self._hop_counts[node_id] = 2
                    else:
                        self._hop_counts[node_id] = 3

    def get_targets(self) -> list[dict]:
        """Convert all nodes to Tritium target format."""
        targets = []
        now = time.time()
        for node_id, node in self.nodes.items():
            last_heard = node.get("last_heard", 0)
            age_s = now - last_heard if last_heard > 0 else float("inf")

            target = {
                "target_id": f"mesh_{node_id.replace('!', '')}",
                "name": node.get("long_name", node_id),
                "source": "mesh",
                "asset_type": "mesh_radio",
                "alliance": "friendly",
                "last_seen": last_heard,
                "stale": age_s > 600,  # 10 min = stale
            }

            # Position
            if node.get("lat") is not None and node.get("lng") is not None:
                target["lat"] = node["lat"]
                target["lng"] = node["lng"]
                target["alt"] = node.get("altitude", 0)
                target["position"] = {"x": node["lng"], "y": node["lat"]}

            # Telemetry
            if node.get("battery") is not None:
                target["battery"] = node["battery"] / 100.0  # 0-1

            if node.get("voltage") is not None:
                target["voltage"] = node["voltage"]

            if node.get("snr") is not None:
                target["snr"] = node["snr"]

            # Hop count
            if node_id in self._hop_counts:
                target["hops"] = self._hop_counts[node_id]

            # Role
            target["role"] = node.get("role", "CLIENT")
            target["is_router"] = node.get("role", "") in ("ROUTER", "ROUTER_CLIENT", "REPEATER")

            # Channel utilization
            if node.get("channel_util") is not None:
                target["channel_util"] = node["channel_util"]
            if node.get("air_util") is not None:
                target["air_util"] = node["air_util"]

            # Hardware info
            target["hw_model"] = node.get("hw_model", "")
            target["firmware"] = node.get("firmware", "")
            target["short_name"] = node.get("short_name", "")

            # Uptime
            if node.get("uptime"):
                target["uptime"] = node["uptime"]

            targets.append(target)

        return targets

    def get_stats(self) -> dict:
        """Network-level statistics."""
        now = time.time()
        total = len(self.nodes)
        with_gps = sum(1 for n in self.nodes.values() if n.get("lat") is not None)
        online = sum(1 for n in self.nodes.values()
                     if n.get("last_heard", 0) > now - 600)
        routers = sum(1 for n in self.nodes.values()
                      if n.get("role", "") in ("ROUTER", "ROUTER_CLIENT", "REPEATER"))

        avg_snr = None
        snrs = [n["snr"] for n in self.nodes.values() if n.get("snr") is not None]
        if snrs:
            avg_snr = round(sum(snrs) / len(snrs), 1)

        avg_battery = None
        batts = [n["battery"] for n in self.nodes.values() if n.get("battery") is not None and n["battery"] > 0]
        if batts:
            avg_battery = round(sum(batts) / len(batts), 0)

        return {
            "total_nodes": total,
            "online_nodes": online,
            "offline_nodes": total - online,
            "with_gps": with_gps,
            "routers": routers,
            "avg_snr": avg_snr,
            "avg_battery": avg_battery,
            "link_count": len(self.get_links()),
            "last_update": self._last_update,
        }

    def get_node(self, node_id: str) -> dict | None:
        """Get a single node's data."""
        return self.nodes.get(node_id)

    def get_links(self) -> list[dict]:
        """Get mesh link data (node pairs that have communicated)."""
        links = []
        seen = set()
        for node_id, node in self.nodes.items():
            neighbors = node.get("neighbors", [])
            for neighbor_id in neighbors:
                pair = tuple(sorted([node_id, neighbor_id]))
                if pair not in seen:
                    seen.add(pair)
                    links.append({
                        "from": node_id,
                        "to": neighbor_id,
                        "snr": node.get("neighbor_snr", {}).get(neighbor_id),
                    })
        return links

    def _parse_node(self, node_id: str, raw: dict) -> dict | None:
        """Parse raw meshtastic node data into our format."""
        user = raw.get("user", {})
        position = raw.get("position", {})
        metrics = raw.get("deviceMetrics", {})

        # Role from user protobuf
        role_num = user.get("role", 0)
        role_name = ROLE_NAMES.get(role_num, f"UNKNOWN({role_num})")

        node = {
            "node_id": node_id,
            "num": raw.get("num", 0),
            "long_name": user.get("longName", node_id),
            "short_name": user.get("shortName", ""),
            "hw_model": user.get("hwModel", ""),
            "mac": user.get("macaddr", ""),
            "role": role_name,
            "last_heard": raw.get("lastHeard", 0),
        }

        # Position — meshtastic uses both integer (latitudeI/1e7) and float formats
        lat_i = position.get("latitudeI")
        lng_i = position.get("longitudeI")
        if lat_i is not None and lng_i is not None:
            node["lat"] = lat_i / 1e7
            node["lng"] = lng_i / 1e7
            node["altitude"] = position.get("altitude", 0)
        else:
            # Some versions use float directly
            lat_f = position.get("latitude")
            lng_f = position.get("longitude")
            if lat_f is not None and lng_f is not None and (lat_f != 0 or lng_f != 0):
                node["lat"] = lat_f
                node["lng"] = lng_f
                node["altitude"] = position.get("altitude", 0)

        # Position extras
        if position.get("time"):
            node["gps_time"] = position["time"]
        if position.get("PDOP"):
            node["gps_pdop"] = position["PDOP"]
        if position.get("satsInView"):
            node["gps_sats"] = position["satsInView"]

        # Battery and telemetry
        if metrics:
            node["battery"] = metrics.get("batteryLevel", 0)
            node["voltage"] = metrics.get("voltage", 0)
            node["channel_util"] = metrics.get("channelUtilization", 0)
            node["air_util"] = metrics.get("airUtilTx", 0)
            node["uptime"] = metrics.get("uptimeSeconds", 0)

        # Environment metrics (some nodes have temp/humidity/pressure)
        env_metrics = raw.get("environmentMetrics", {})
        if env_metrics:
            if env_metrics.get("temperature") is not None:
                node["temperature"] = env_metrics["temperature"]
            if env_metrics.get("relativeHumidity") is not None:
                node["humidity"] = env_metrics["relativeHumidity"]
            if env_metrics.get("barometricPressure") is not None:
                node["pressure"] = env_metrics["barometricPressure"]

        # SNR (from last received packet)
        if "snr" in raw:
            node["snr"] = raw["snr"]

        # Hop limit / hops away (if present in raw data)
        if "hopsAway" in raw:
            node["hops_away"] = raw["hopsAway"]

        # Neighbor info (for link/topology extraction)
        if "neighborInfo" in raw:
            ni = raw["neighborInfo"]
            neighbors = []
            neighbor_snrs = {}
            for neighbor in ni.get("neighbors", []):
                nid = neighbor.get("nodeId")
                if nid:
                    # Convert numeric node ID to hex string format
                    if isinstance(nid, int):
                        nid = f"!{nid:08x}"
                    neighbors.append(nid)
                    if "snr" in neighbor:
                        neighbor_snrs[nid] = neighbor["snr"]
            node["neighbors"] = neighbors
            node["neighbor_snr"] = neighbor_snrs

        return node
