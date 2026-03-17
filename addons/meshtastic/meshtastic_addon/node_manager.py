# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Node manager — converts Meshtastic nodes into Tritium tracked targets."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

log = logging.getLogger("meshtastic.nodes")


class NodeManager:
    """Manages mesh node state and converts to Tritium targets."""

    def __init__(self, event_bus=None, target_tracker=None):
        self.event_bus = event_bus
        self.target_tracker = target_tracker
        self.nodes: dict[str, dict] = {}  # node_id → node data
        self._last_update = 0.0

    def update_nodes(self, raw_nodes: dict):
        """Update internal node state from meshtastic library data.

        Args:
            raw_nodes: Dict from interface.nodes — keyed by node ID string.
        """
        updated = 0
        for node_id, raw in raw_nodes.items():
            node = self._parse_node(node_id, raw)
            if node:
                self.nodes[node_id] = node
                updated += 1

        self._last_update = time.time()

        # Emit targets to the tracker
        if self.target_tracker and updated > 0:
            targets = self.get_targets()
            for t in targets:
                try:
                    self.target_tracker.update_target(t)
                except Exception:
                    pass  # Target tracker might not support this method yet

        if self.event_bus and updated > 0:
            self.event_bus.emit("meshtastic:nodes_updated", {
                "count": updated,
                "total": len(self.nodes),
            })

        log.debug(f"Updated {updated} nodes ({len(self.nodes)} total)")

    def get_targets(self) -> list[dict]:
        """Convert all nodes to Tritium target format."""
        targets = []
        for node_id, node in self.nodes.items():
            target = {
                "target_id": f"mesh_{node_id.replace('!', '')}",
                "name": node.get("long_name", node_id),
                "source": "mesh",
                "asset_type": "mesh_radio",
                "alliance": "friendly",
                "last_seen": node.get("last_heard", 0),
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

            # Hardware info
            target["hw_model"] = node.get("hw_model", "")
            target["firmware"] = node.get("firmware", "")
            target["short_name"] = node.get("short_name", "")

            targets.append(target)

        return targets

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

        node = {
            "node_id": node_id,
            "num": raw.get("num", 0),
            "long_name": user.get("longName", node_id),
            "short_name": user.get("shortName", ""),
            "hw_model": user.get("hwModel", ""),
            "mac": user.get("macaddr", ""),
            "last_heard": raw.get("lastHeard", 0),
        }

        # Position (convert from integer format)
        lat_i = position.get("latitudeI")
        lng_i = position.get("longitudeI")
        if lat_i is not None and lng_i is not None:
            node["lat"] = lat_i / 1e7
            node["lng"] = lng_i / 1e7
            node["altitude"] = position.get("altitude", 0)

        # Battery and telemetry
        if metrics:
            node["battery"] = metrics.get("batteryLevel", 0)
            node["voltage"] = metrics.get("voltage", 0)
            node["channel_util"] = metrics.get("channelUtilization", 0)
            node["air_util"] = metrics.get("airUtilTx", 0)
            node["uptime"] = metrics.get("uptimeSeconds", 0)

        # SNR (from last received packet)
        if "snr" in raw:
            node["snr"] = raw["snr"]

        return node
