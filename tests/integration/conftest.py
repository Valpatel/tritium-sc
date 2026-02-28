# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shared fixtures for integration tests.

Provides a session-scoped TritiumServer and an httpx client wired to it.
The server starts once per pytest session with AMY_ENABLED=false and
SIMULATION_ENABLED=true (headless mode).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.lib.server_manager import TritiumServer

# Where to drop the integration report JSON
_RESULTS_DIR = Path(__file__).parent.parent / ".test-results"


@pytest.fixture(scope="session")
def server() -> TritiumServer:
    """Session-scoped fixture: starts TRITIUM-SC in headless sim mode.

    Yields a TritiumServer instance with .base_url, game helpers, etc.
    The server is stopped automatically at teardown.
    """
    srv = TritiumServer(auto_port=True)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="session")
def base_url(server: TritiumServer) -> str:
    """Convenience: the server's base URL as a plain string."""
    return server.base_url


class IntegrationReport:
    """Accumulates test results and writes a JSON report on close."""

    def __init__(self) -> None:
        self.results: list[dict] = []

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append({
            "test": name,
            "passed": passed,
            "detail": detail,
        })

    def write(self) -> None:
        _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = _RESULTS_DIR / "integration-report.json"
        summary = {
            "total": len(self.results),
            "passed": sum(1 for r in self.results if r["passed"]),
            "failed": sum(1 for r in self.results if not r["passed"]),
            "tests": self.results,
        }
        path.write_text(json.dumps(summary, indent=2))


@pytest.fixture(scope="session")
def report() -> IntegrationReport:
    """Session-scoped report that flushes to disk at teardown."""
    r = IntegrationReport()
    yield r
    r.write()
