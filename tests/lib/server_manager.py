# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TritiumServer — manage uvicorn lifecycle for integration tests.

Starts the TRITIUM-SC FastAPI app on a test port, waits for the health
endpoint, and provides helpers for game API calls and cleanup.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import requests

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_PORT = 8765
HEALTH_TIMEOUT = 30  # seconds to wait for server startup
HEALTH_INTERVAL = 0.5  # seconds between health polls


def _find_free_port() -> int:
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TritiumServer:
    """Manages a uvicorn server process for integration testing.

    Args:
        port: TCP port to bind. Defaults to DEFAULT_PORT.
        host: Bind address. Defaults to 127.0.0.1.
        auto_port: If True, find a free port automatically (overrides port).
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        host: str = "127.0.0.1",
        auto_port: bool = False,
    ):
        self.host = host
        self.port = _find_free_port() if auto_port else port
        self.base_url = f"http://{self.host}:{self.port}"
        self._process: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        """Alias for base_url for convenience."""
        return self.base_url

    @property
    def is_running(self) -> bool:
        """True if the server process is alive."""
        return self._process is not None and self._process.poll() is None

    def start(self, timeout: float = HEALTH_TIMEOUT) -> None:
        """Start the server and block until healthy or timeout.

        Raises:
            RuntimeError: If server fails to start or become healthy.
        """
        if self.is_running:
            return

        env = os.environ.copy()
        # Ensure src/ is on PYTHONPATH so `app.main` resolves
        src_dir = str(PROJECT_ROOT / "src")
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_dir}:{existing}" if existing else src_dir
        env["SIMULATION_ENABLED"] = "true"
        env["AMY_ENABLED"] = "false"
        env["MQTT_ENABLED"] = "false"
        # Avoid CUDA issues on test machines
        env["CUDA_VISIBLE_DEVICES"] = ""

        cmd = [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", self.host,
            "--port", str(self.port),
            "--log-level", "warning",
        ]

        self._process = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if not self._wait_healthy(timeout):
            self.stop()
            raise RuntimeError(
                f"Server failed to become healthy within {timeout}s "
                f"on {self.base_url}"
            )

    def stop(self) -> None:
        """Stop the server process gracefully."""
        if self._process is None:
            return

        try:
            self._process.send_signal(signal.SIGTERM)
            self._process.wait(timeout=5)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            self._process.kill()
            self._process.wait(timeout=2)
        finally:
            self._process = None

    def is_healthy(self) -> bool:
        """Check if the server responds to health endpoint."""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=2)
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False

    def _wait_healthy(self, timeout: float) -> bool:
        """Poll health endpoint until responsive or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running:
                return False
            if self.is_healthy():
                return True
            time.sleep(HEALTH_INTERVAL)
        return False

    # -----------------------------------------------------------------------
    # Game API helpers
    # -----------------------------------------------------------------------

    def get_game_state(self) -> dict[str, Any]:
        """GET /api/game/state"""
        resp = requests.get(f"{self.base_url}/api/game/state", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def begin_war(self) -> dict[str, Any]:
        """POST /api/game/begin"""
        resp = requests.post(f"{self.base_url}/api/game/begin", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def reset_game(self) -> dict[str, Any]:
        """POST /api/game/reset"""
        resp = requests.post(f"{self.base_url}/api/game/reset", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def place_unit(
        self, name: str, x: float, y: float, unit_type: str = "turret",
    ) -> dict[str, Any]:
        """POST /api/game/place"""
        resp = requests.post(
            f"{self.base_url}/api/game/place",
            json={"name": name, "position": {"x": x, "y": y}, "asset_type": unit_type},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()

    def get_targets(self) -> dict[str, Any]:
        """GET /api/amy/simulation/targets"""
        resp = requests.get(
            f"{self.base_url}/api/amy/simulation/targets", timeout=5,
        )
        resp.raise_for_status()
        return resp.json()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


# ---------------------------------------------------------------------------
# Pytest fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def tritium_server():
    """Session-scoped fixture: starts TRITIUM-SC server once for all tests.

    Yields a TritiumServer instance with .base_url, .get_game_state(), etc.
    """
    server = TritiumServer(auto_port=True)
    server.start()
    yield server
    server.stop()
