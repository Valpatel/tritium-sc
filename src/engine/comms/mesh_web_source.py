"""MeshWebSource — periodic polling of public mesh network maps.

Polls web APIs for publicly visible mesh radio nodes, converts lat/lng
to local coordinates, and registers them in TargetTracker as
asset_type="mesh_radio" with metadata.source="web".

Stale nodes (not seen for 5 consecutive polls) are removed.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.tactical.target_tracker import TargetTracker

logger = logging.getLogger("amy.mesh_web")


class MeshWebSource:
    """Polls public mesh network maps and registers nodes in TargetTracker."""

    # Nodes not seen for this many consecutive polls are removed.
    STALE_THRESHOLD = 5

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker,
        poll_interval: int = 60,
        mesh_web_url: str = "",
    ) -> None:
        self._event_bus = event_bus
        self._tracker = target_tracker
        self._poll_interval = poll_interval
        self._mesh_web_url = mesh_web_url
        self._running = False
        self._poll_count = 0
        self._last_error = ""
        self._lock = threading.Lock()
        # {node_id: {"seen_count": int, "missed_polls": int, ...}}
        self._known_nodes: dict[str, dict] = {}
        self._thread: threading.Thread | None = None

    # --- Properties ---

    @property
    def stats(self) -> dict:
        return {
            "running": self._running,
            "poll_count": self._poll_count,
            "nodes_known": len(self._known_nodes),
            "last_error": self._last_error,
        }

    # --- Lifecycle ---

    def start(self) -> None:
        """Start background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="mesh-web-poller"
        )
        self._thread.start()
        logger.info(f"Mesh web source started (interval={self._poll_interval}s)")

    def stop(self) -> None:
        """Stop background polling."""
        self._running = False
        logger.info("Mesh web source stopped")

    # --- Poll processing (public, also called from _poll_loop) ---

    def process_poll_result(self, nodes: list[dict]) -> None:
        """Process a list of nodes from a web poll.

        Each node dict should have:
          - node_id: str
          - lat: float
          - lng: float
          - name: str (optional)
          - protocol: str (optional, e.g. "meshtastic", "meshcore")
          - last_seen: str (optional, ISO timestamp)
        """
        self._poll_count += 1
        seen_ids = set()

        for node_data in nodes:
            node_id = node_data.get("node_id", "")
            if not node_id:
                continue

            lat = node_data.get("lat", 0.0)
            lng = node_data.get("lng", 0.0)

            # Skip (0,0) coordinates
            if lat == 0.0 and lng == 0.0:
                continue

            # Convert WGS84 to local coordinates
            try:
                from engine.tactical.geo import latlng_to_local
                x, y, z = latlng_to_local(lat, lng, 0.0)
            except Exception:
                x, y, z = 0.0, 0.0, 0.0

            name = node_data.get("name", node_id)
            protocol = node_data.get("protocol", "unknown")

            # Register in target tracker
            self._tracker.update_from_simulation({
                "target_id": f"meshweb_{node_id}",
                "name": name,
                "alliance": "friendly",
                "asset_type": "mesh_radio",
                "position": {"x": x, "y": y},
                "heading": 0,
                "speed": 0,
                "battery": 1.0,
                "status": "active",
                "metadata": {"source": "web", "protocol": protocol},
            })

            seen_ids.add(node_id)

            # Update known nodes tracking
            with self._lock:
                if node_id in self._known_nodes:
                    self._known_nodes[node_id]["missed_polls"] = 0
                    self._known_nodes[node_id]["seen_count"] += 1
                else:
                    self._known_nodes[node_id] = {
                        "seen_count": 1,
                        "missed_polls": 0,
                        "name": name,
                        "protocol": protocol,
                    }

        # Increment missed_polls for nodes not in this poll
        with self._lock:
            stale_ids = []
            for nid, info in self._known_nodes.items():
                if nid not in seen_ids:
                    info["missed_polls"] += 1
                    if info["missed_polls"] >= self.STALE_THRESHOLD:
                        stale_ids.append(nid)

            # Remove stale nodes
            for nid in stale_ids:
                del self._known_nodes[nid]
                self._tracker.remove(f"meshweb_{nid}")

        self._event_bus.publish("mesh_web:nodes_updated", {
            "count": len(seen_ids),
            "stale_removed": len(stale_ids) if 'stale_ids' in dir() else 0,
        })

    # --- Background poller ---

    def _poll_loop(self) -> None:
        """Periodically poll web sources for mesh node data."""
        while self._running:
            try:
                nodes = self._fetch_nodes()
                self.process_poll_result(nodes)
            except Exception as e:
                logger.debug(f"Mesh web poll error: {e}")
                self._last_error = str(e)

            # Sleep in small increments so stop() is responsive
            for _ in range(self._poll_interval):
                if not self._running:
                    break
                time.sleep(1.0)

    def _fetch_nodes(self) -> list[dict]:
        """Fetch node data from a configured mesh network map API.

        If ``mesh_web_url`` is empty, returns [] (graceful no-op).
        Otherwise fetches JSON from the URL and parses nodes.

        Expected response: a JSON array of objects, each with at
        minimum ``{id, lat, lng}`` or ``{node_id, lat, lng}``.
        Optional fields: ``name``, ``protocol``, ``last_seen``.

        Returns a list of node dicts suitable for process_poll_result().
        """
        if not self._mesh_web_url:
            return []

        import json
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                self._mesh_web_url,
                headers={"User-Agent": "tritium-sc/1.0 mesh-monitor", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                data = json.loads(raw)
        except urllib.error.URLError as e:
            logger.debug(f"Mesh web fetch URL error: {e}")
            self._last_error = f"URL error: {e}"
            return []
        except urllib.error.HTTPError as e:
            logger.debug(f"Mesh web fetch HTTP {e.code}: {e}")
            self._last_error = f"HTTP {e.code}"
            return []
        except TimeoutError:
            logger.debug("Mesh web fetch timeout")
            self._last_error = "timeout"
            return []
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Mesh web fetch JSON error: {e}")
            self._last_error = f"JSON error: {e}"
            return []
        except Exception as e:
            logger.debug(f"Mesh web fetch error: {e}")
            self._last_error = str(e)
            return []

        # Normalize response: accept both array-of-objects and {"nodes": [...]}
        if isinstance(data, dict):
            data = data.get("nodes", data.get("data", []))
        if not isinstance(data, list):
            self._last_error = "unexpected response format"
            return []

        nodes = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            node_id = entry.get("node_id") or entry.get("id") or ""
            if not node_id:
                continue
            node_id = str(node_id)

            # Latitude: lat > latitude
            lat = entry.get("lat") or entry.get("latitude") or 0.0
            # Longitude: lng > lon > longitude
            lng = entry.get("lng") or entry.get("lon") or entry.get("longitude") or 0.0

            lat = float(lat) if lat else 0.0
            lng = float(lng) if lng else 0.0

            # Skip nodes with no position or at (0,0) (invalid GPS)
            if lat == 0.0 and lng == 0.0:
                continue

            # Name: name > long_name > node_id
            name = entry.get("name") or entry.get("long_name") or node_id

            # Last seen: last_seen > last_heard
            last_seen = entry.get("last_seen") or entry.get("last_heard") or ""
            if last_seen != "":
                last_seen = str(last_seen)

            nodes.append({
                "node_id": node_id,
                "lat": lat,
                "lng": lng,
                "name": name,
                "protocol": entry.get("protocol", "meshtastic"),
                "last_seen": last_seen,
            })

        return nodes
