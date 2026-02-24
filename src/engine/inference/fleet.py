"""Production Ollama Fleet — multi-host LLM inference with auto-discovery.

Discovers ollama instances from:
1. conf/ollama-fleet.conf (gitignored — no host info in repo)
2. OLLAMA_HOSTS env var (comma-separated)
3. Tailscale network scan (auto-discover peers)
4. Localhost fallback (always available)

All host references are dynamic — no IPs or hostnames baked into source.
Promoted from tests/lib/ollama_fleet.py to production use.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONF_PATH = Path(__file__).parent.parent / "conf" / "ollama-fleet.conf"
DEFAULT_PORT = 11434
PROBE_TIMEOUT = 3  # seconds


@dataclass
class FleetHost:
    """A reachable Ollama instance on the fleet."""
    url: str
    name: str
    models: list[str] = field(default_factory=list)
    latency_ms: float = 0.0

    def has_model(self, model: str) -> bool:
        """Check if this host has a model (prefix match)."""
        prefix = model.split(":")[0]
        return any(m.startswith(prefix) for m in self.models)


class OllamaFleet:
    """Manages a pool of Ollama hosts for production inference.

    Auto-discovers hosts from conf file, env vars, and Tailscale.
    Provides host selection by model capability and latency.
    """

    def __init__(self, auto_discover: bool = True):
        self._hosts: list[FleetHost] = []
        self._discover(auto_discover)

    @property
    def hosts(self) -> list[FleetHost]:
        return list(self._hosts)

    @property
    def count(self) -> int:
        return len(self._hosts)

    def hosts_with_model(self, model: str) -> list[FleetHost]:
        """Return hosts that have a specific model, sorted by latency."""
        return [h for h in self._hosts if h.has_model(model)]

    def best_host(self, model: str) -> FleetHost | None:
        """Return the fastest host with this model, or None."""
        hosts = self.hosts_with_model(model)
        return hosts[0] if hosts else None

    def refresh(self) -> None:
        """Re-discover hosts (useful after network changes)."""
        self._hosts.clear()
        self._discover(auto_discover=True)

    def _discover(self, auto_discover: bool) -> None:
        """Build host list from all sources."""
        candidates: set[str] = set()

        # Always include localhost
        candidates.add(f"localhost:{DEFAULT_PORT}")

        # 1. Conf file (gitignored)
        if CONF_PATH.exists():
            for line in CONF_PATH.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    if ":" not in line:
                        line = f"{line}:{DEFAULT_PORT}"
                    candidates.add(line)

        # 2. OLLAMA_HOSTS env var
        env_hosts = os.environ.get("OLLAMA_HOSTS", "")
        for h in env_hosts.split(","):
            h = h.strip()
            if h:
                if ":" not in h:
                    h = f"{h}:{DEFAULT_PORT}"
                candidates.add(h)

        # 3. Tailscale auto-discovery
        if auto_discover:
            candidates.update(self._scan_tailscale())

        # Probe all candidates in parallel
        if not candidates:
            return

        with ThreadPoolExecutor(max_workers=min(len(candidates), 10)) as pool:
            futures = {pool.submit(self._probe, c): c for c in candidates}
            for f in as_completed(futures, timeout=PROBE_TIMEOUT + 2):
                try:
                    host = f.result()
                    if host is not None:
                        self._hosts.append(host)
                except Exception:
                    pass

        # Sort by latency (fastest first)
        self._hosts.sort(key=lambda h: h.latency_ms)

    def _scan_tailscale(self) -> set[str]:
        """Discover Ollama on Tailscale peers."""
        hosts: set[str] = set()
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for peer_id, peer in data.get("Peer", {}).items():
                    if not peer.get("Online", False):
                        continue
                    name = peer.get("HostName", "")
                    if name:
                        hosts.add(f"{name}:{DEFAULT_PORT}")
        except (subprocess.TimeoutExpired, FileNotFoundError,
                json.JSONDecodeError, OSError):
            pass
        return hosts

    def _probe(self, host_port: str) -> FleetHost | None:
        """Check if a host has Ollama running and list its models."""
        import urllib.request
        url = f"http://{host_port}"
        name = host_port.split(":")[0]
        try:
            t0 = time.monotonic()
            req = urllib.request.Request(
                f"{url}/api/tags",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
                latency = (time.monotonic() - t0) * 1000
                data = json.loads(resp.read().decode())
                models = [m["name"] for m in data.get("models", [])]
                return FleetHost(
                    url=url, name=name, models=models, latency_ms=latency,
                )
        except Exception:
            return None

    def status(self) -> str:
        """Human-readable fleet status."""
        if not self._hosts:
            return "Ollama Fleet: no hosts found"
        lines = [f"Ollama Fleet: {len(self._hosts)} host(s)"]
        for h in self._hosts:
            vision = [m for m in h.models if "llava" in m or "minicpm" in m]
            lines.append(
                f"  {h.name}: {len(h.models)} models, "
                f"vision={vision}, {h.latency_ms:.0f}ms"
            )
        return "\n".join(lines)
