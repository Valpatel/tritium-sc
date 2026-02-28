# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Ollama Fleet — discover and parallelize LLM inference across hosts.

Discovers ollama instances from:
1. conf/ollama-fleet.conf (explicit host list)
2. OLLAMA_HOSTS env var (comma-separated)
3. Tailscale network scan (auto-discover)
4. Localhost fallback

All host references are dynamic — no IPs baked into source.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

CONF_PATH = Path(__file__).parent.parent.parent / "conf" / "ollama-fleet.conf"
DEFAULT_PORT = 11434
PROBE_TIMEOUT = 3  # seconds


@dataclass
class OllamaHost:
    """A reachable ollama instance."""
    url: str
    name: str
    models: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    busy: bool = False

    def has_model(self, model: str) -> bool:
        return any(m.startswith(model.split(":")[0]) for m in self.models)


class OllamaFleet:
    """Manages a pool of ollama hosts for parallel inference."""

    def __init__(self, auto_discover: bool = True):
        self._hosts: list[OllamaHost] = []
        self._discover(auto_discover)

    @property
    def hosts(self) -> list[OllamaHost]:
        return list(self._hosts)

    @property
    def count(self) -> int:
        return len(self._hosts)

    def hosts_with_model(self, model: str) -> list[OllamaHost]:
        """Return hosts that have a specific model available."""
        return [h for h in self._hosts if h.has_model(model)]

    def _discover(self, auto_discover: bool) -> None:
        """Build host list from all sources."""
        candidates: set[str] = set()

        # Always include localhost
        candidates.add("localhost:11434")

        # 1. Read conf file
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
        with ThreadPoolExecutor(max_workers=min(len(candidates), 10)) as pool:
            futures = {pool.submit(self._probe, c): c for c in candidates}
            for f in as_completed(futures, timeout=PROBE_TIMEOUT + 2):
                host = f.result()
                if host is not None:
                    self._hosts.append(host)

        # Sort by latency (fastest first)
        self._hosts.sort(key=lambda h: h.latency_ms)

    def _scan_tailscale(self) -> set[str]:
        """Discover ollama on tailscale peers."""
        hosts = set()
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
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass
        return hosts

    def _probe(self, host_port: str) -> OllamaHost | None:
        """Check if a host has ollama running and list its models."""
        url = f"http://{host_port}"
        name = host_port.split(":")[0]
        try:
            t0 = time.monotonic()
            resp = requests.get(f"{url}/api/tags", timeout=PROBE_TIMEOUT)
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                return OllamaHost(
                    url=url, name=name, models=models, latency_ms=latency,
                )
        except (requests.ConnectionError, requests.Timeout):
            pass
        return None

    def generate(
        self, model: str, prompt: str, image_path: Path | None = None,
        timeout: float = 120, prefer_host: str | None = None,
    ) -> dict[str, Any]:
        """Run a generate request on the best available host.

        Returns {"response": str, "host": str, "model": str, "elapsed_ms": float}
        """
        hosts = self.hosts_with_model(model)
        if not hosts:
            raise RuntimeError(f"No host has model '{model}'. Available: {[h.name for h in self._hosts]}")

        # Prefer a specific host if requested
        if prefer_host:
            preferred = [h for h in hosts if h.name == prefer_host]
            if preferred:
                hosts = preferred + [h for h in hosts if h.name != prefer_host]

        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if image_path is not None:
            with open(image_path, "rb") as f:
                payload["images"] = [base64.b64encode(f.read()).decode()]

        last_err = None
        for host in hosts:
            try:
                t0 = time.monotonic()
                resp = requests.post(
                    f"{host.url}/api/generate", json=payload, timeout=timeout,
                )
                elapsed = (time.monotonic() - t0) * 1000
                if resp.status_code == 200:
                    return {
                        "response": resp.json().get("response", ""),
                        "host": host.name,
                        "model": model,
                        "elapsed_ms": elapsed,
                    }
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"All hosts failed for model '{model}': {last_err}")

    def parallel_vision(
        self, model: str, tasks: list[dict],
        max_workers: int | None = None,
    ) -> list[dict]:
        """Run multiple vision tasks in parallel across the fleet.

        Each task: {"image": Path, "prompt": str, "name": str}
        Returns: list of {"name": str, "response": str, "host": str, "elapsed_ms": float}
        """
        hosts = self.hosts_with_model(model)
        if not hosts:
            raise RuntimeError(f"No host has model '{model}'")

        workers = max_workers or len(hosts)
        results = []

        def _run(task: dict, host: OllamaHost) -> dict:
            result = self.generate(
                model=model,
                prompt=task["prompt"],
                image_path=task["image"],
                prefer_host=host.name,
            )
            return {"name": task["name"], **result}

        # Round-robin assign tasks to hosts
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i, task in enumerate(tasks):
                host = hosts[i % len(hosts)]
                futures[pool.submit(_run, task, host)] = task["name"]

            for f in as_completed(futures):
                try:
                    results.append(f.result())
                except Exception as e:
                    results.append({
                        "name": futures[f],
                        "response": f"[error: {e}]",
                        "host": "failed",
                        "elapsed_ms": 0,
                    })

        return results

    def status(self) -> str:
        """Human-readable fleet status."""
        lines = [f"Ollama Fleet: {len(self._hosts)} hosts"]
        for h in self._hosts:
            vision = [m for m in h.models if "llava" in m or "minicpm" in m]
            lines.append(f"  {h.name}: {len(h.models)} models, vision={vision}, {h.latency_ms:.0f}ms")
        return "\n".join(lines)
