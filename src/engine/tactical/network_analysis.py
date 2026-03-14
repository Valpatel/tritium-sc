# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""NetworkAnalyzer — WiFi probe request network analysis.

Builds a bipartite graph between devices and SSIDs they probe for,
revealing hidden relationships:

  - Device A and Device B both probe for "CorpNet" -> likely same org
  - Device C probes for many unique SSIDs -> likely a mobile phone
  - SSID "xfinitywifi" probed by 50 devices -> common carrier

Usage
-----
    analyzer = NetworkAnalyzer()
    analyzer.record_probe("AA:BB:CC:DD:EE:FF", "MyWiFi")
    graph = analyzer.get_network_graph()
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Known carrier/common SSIDs that are less useful for correlation
COMMON_SSIDS = frozenset({
    "xfinitywifi", "attwifi", "CableWiFi", "XFINITY",
    "tmobile", "Verizon", "FreeWiFi", "linksys",
    "NETGEAR", "default", "HOME-", "AndroidAP",
    "iPhone", "Galaxy", "",
})


@dataclass
class ProbeRecord:
    """A single probe request observation."""

    mac: str
    ssid: str
    timestamp: float
    rssi: int = -80


@dataclass
class DeviceProfile:
    """Aggregated probe behavior for a single device."""

    mac: str
    ssids: set[str] = field(default_factory=set)
    first_seen: float = 0.0
    last_seen: float = 0.0
    probe_count: int = 0
    oui_vendor: str = ""

    def to_dict(self) -> dict:
        return {
            "mac": self.mac,
            "ssids": sorted(self.ssids),
            "ssid_count": len(self.ssids),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "probe_count": self.probe_count,
            "oui_vendor": self.oui_vendor,
            "device_type": self._classify(),
        }

    def _classify(self) -> str:
        """Classify device based on probe behavior."""
        n = len(self.ssids)
        if n == 0:
            return "silent"
        if n == 1:
            return "single_network"
        if n <= 3:
            return "home_user"
        if n <= 8:
            return "mobile"
        return "heavy_traveler"


class NetworkAnalyzer:
    """Bipartite graph analyzer for device-SSID probe relationships.

    Thread-safe. Records probe requests and builds network graphs
    showing which devices probe for which SSIDs.

    Parameters
    ----------
    retention_hours:
        How long to keep probe records. Default 24 hours.
    """

    def __init__(self, retention_hours: float = 24.0) -> None:
        self._lock = threading.Lock()
        self._retention = retention_hours * 3600
        # mac -> DeviceProfile
        self._devices: dict[str, DeviceProfile] = {}
        # ssid -> set of MACs
        self._ssid_devices: dict[str, set[str]] = defaultdict(set)
        # Raw probe records for time-windowed queries
        self._probes: list[ProbeRecord] = []

    def record_probe(
        self,
        mac: str,
        ssid: str,
        rssi: int = -80,
        timestamp: float | None = None,
        oui_vendor: str = "",
    ) -> None:
        """Record a WiFi probe request.

        Args:
            mac:        Device MAC address.
            ssid:       SSID being probed for.
            rssi:       Signal strength in dBm.
            timestamp:  Unix timestamp (default now).
            oui_vendor: Manufacturer from OUI lookup.
        """
        ts = timestamp if timestamp is not None else time.time()
        mac = mac.upper()

        with self._lock:
            # Update device profile
            if mac not in self._devices:
                self._devices[mac] = DeviceProfile(
                    mac=mac, first_seen=ts, last_seen=ts
                )
            dev = self._devices[mac]
            dev.ssids.add(ssid)
            dev.last_seen = max(dev.last_seen, ts)
            dev.probe_count += 1
            if oui_vendor:
                dev.oui_vendor = oui_vendor

            # Update SSID index
            self._ssid_devices[ssid].add(mac)

            # Store raw probe
            self._probes.append(ProbeRecord(mac=mac, ssid=ssid, timestamp=ts, rssi=rssi))

    def get_network_graph(
        self,
        min_shared_ssids: int = 1,
        exclude_common: bool = True,
        time_window_hours: float | None = None,
    ) -> dict:
        """Build a network graph of device-SSID relationships.

        Returns a graph with nodes (devices + SSIDs) and edges (probes).

        Args:
            min_shared_ssids: Minimum shared SSIDs for a device-device edge.
            exclude_common:   Filter out common carrier SSIDs.
            time_window_hours: Only include probes from last N hours (None=all).
        """
        with self._lock:
            devices = dict(self._devices)
            ssid_devices = {k: set(v) for k, v in self._ssid_devices.items()}

        nodes: list[dict] = []
        edges: list[dict] = []
        device_ssids: dict[str, set[str]] = {}

        # Filter by time window if specified
        if time_window_hours is not None:
            cutoff = time.time() - time_window_hours * 3600
            active_macs = set()
            active_ssids: dict[str, set[str]] = defaultdict(set)
            with self._lock:
                for p in self._probes:
                    if p.timestamp >= cutoff:
                        active_macs.add(p.mac)
                        active_ssids[p.ssid].add(p.mac)
            devices = {m: devices[m] for m in active_macs if m in devices}
            ssid_devices = dict(active_ssids)

        # Filter common SSIDs
        filtered_ssids = set()
        if exclude_common:
            for ssid in ssid_devices:
                ssid_lower = ssid.lower()
                if any(c.lower() in ssid_lower for c in COMMON_SSIDS if c):
                    filtered_ssids.add(ssid)

        # Build device nodes
        for mac, dev in devices.items():
            dev_ssids = dev.ssids - filtered_ssids if exclude_common else dev.ssids
            device_ssids[mac] = dev_ssids
            nodes.append({
                "id": mac,
                "type": "device",
                "label": dev.oui_vendor or mac[:8],
                **dev.to_dict(),
            })

        # Build SSID nodes and device-SSID edges
        ssid_set = set()
        for mac, ssids in device_ssids.items():
            for ssid in ssids:
                if ssid not in ssid_set:
                    device_count = len(ssid_devices.get(ssid, set()))
                    nodes.append({
                        "id": f"ssid:{ssid}",
                        "type": "ssid",
                        "label": ssid,
                        "device_count": device_count,
                    })
                    ssid_set.add(ssid)
                edges.append({
                    "source": mac,
                    "target": f"ssid:{ssid}",
                    "type": "probes_for",
                })

        # Build device-device edges (shared SSIDs)
        mac_list = list(device_ssids.keys())
        device_edges: list[dict] = []
        for i in range(len(mac_list)):
            for j in range(i + 1, len(mac_list)):
                shared = device_ssids[mac_list[i]] & device_ssids[mac_list[j]]
                if len(shared) >= min_shared_ssids:
                    device_edges.append({
                        "source": mac_list[i],
                        "target": mac_list[j],
                        "type": "shared_network",
                        "shared_ssids": sorted(shared),
                        "strength": len(shared),
                    })
        edges.extend(device_edges)

        return {
            "nodes": nodes,
            "edges": edges,
            "device_count": len(devices),
            "ssid_count": len(ssid_set),
            "device_edges": len(device_edges),
        }

    def get_device_profile(self, mac: str) -> dict | None:
        """Get detailed profile for a single device."""
        mac = mac.upper()
        with self._lock:
            dev = self._devices.get(mac)
            if dev is None:
                return None
            return dev.to_dict()

    def get_ssid_devices(self, ssid: str) -> list[str]:
        """Get all MACs that probe for a given SSID."""
        with self._lock:
            return sorted(self._ssid_devices.get(ssid, set()))

    def get_correlated_devices(self, mac: str, min_shared: int = 2) -> list[dict]:
        """Find devices that share SSIDs with the given MAC.

        Returns a list of {mac, shared_ssids, strength} dicts.
        """
        mac = mac.upper()
        with self._lock:
            dev = self._devices.get(mac)
            if dev is None:
                return []
            my_ssids = set(dev.ssids)

        results = []
        with self._lock:
            for other_mac, other_dev in self._devices.items():
                if other_mac == mac:
                    continue
                shared = my_ssids & other_dev.ssids
                if len(shared) >= min_shared:
                    results.append({
                        "mac": other_mac,
                        "shared_ssids": sorted(shared),
                        "strength": len(shared),
                        "vendor": other_dev.oui_vendor,
                    })

        results.sort(key=lambda r: r["strength"], reverse=True)
        return results

    def get_statistics(self) -> dict:
        """Return summary statistics about the probe database."""
        with self._lock:
            total_probes = len(self._probes)
            total_devices = len(self._devices)
            total_ssids = len(self._ssid_devices)

            # Device type distribution
            type_counts: dict[str, int] = defaultdict(int)
            for dev in self._devices.values():
                type_counts[dev._classify()] += 1

            # Top SSIDs by device count
            top_ssids = sorted(
                self._ssid_devices.items(),
                key=lambda kv: len(kv[1]),
                reverse=True,
            )[:10]

        return {
            "total_probes": total_probes,
            "total_devices": total_devices,
            "total_ssids": total_ssids,
            "device_types": dict(type_counts),
            "top_ssids": [
                {"ssid": s, "device_count": len(macs)}
                for s, macs in top_ssids
            ],
        }

    def prune(self, before: float | None = None) -> int:
        """Remove probe records older than the retention window.

        Returns the number of records removed.
        """
        cutoff = before if before is not None else (time.time() - self._retention)
        with self._lock:
            original = len(self._probes)
            self._probes = [p for p in self._probes if p.timestamp >= cutoff]
            removed = original - len(self._probes)
        if removed:
            logger.debug("Pruned %d probe records", removed)
        return removed

    def clear(self) -> None:
        """Clear all data."""
        with self._lock:
            self._devices.clear()
            self._ssid_devices.clear()
            self._probes.clear()
