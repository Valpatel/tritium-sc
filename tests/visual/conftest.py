# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shared fixtures for visual E2E tests.

Provides fleet, test_db, run_id, visual_assert, and server management.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from tests.lib.ollama_fleet import OllamaFleet


def pytest_addoption(parser):
    """Add --update-baselines CLI option for screenshot regression tests."""
    parser.addoption(
        "--update-baselines",
        action="store_true",
        default=False,
        help="Capture new golden baselines instead of comparing",
    )
from tests.lib.results_db import ResultsDB
from tests.lib.visual_assert import VisualAssert
from tests.lib.server_manager import TritiumServer


@pytest.fixture(scope="session")
def fleet() -> OllamaFleet:
    """Discover ollama fleet once per session."""
    return OllamaFleet()


@pytest.fixture(scope="session")
def test_db(tmp_path_factory) -> ResultsDB:
    """Create a ResultsDB for the session."""
    db_dir = tmp_path_factory.mktemp("test_results")
    return ResultsDB(db_path=str(db_dir / "results.db"))


@pytest.fixture(scope="session")
def run_id(test_db: ResultsDB) -> int:
    """Record a new test run and return its ID."""
    git_hash = "unknown"
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            timeout=5,
        ).decode().strip()
    except Exception:
        pass
    machine = socket.gethostname()
    return test_db.record_run("visual", git_hash, machine)


@pytest.fixture(scope="session")
def tritium_server() -> TritiumServer:
    """Start/stop the test server for the session."""
    server = TritiumServer(auto_port=True)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def va(fleet: OllamaFleet, test_db: ResultsDB, run_id: int, tritium_server: TritiumServer) -> VisualAssert:
    """Fresh VisualAssert wired to fleet, db, and server."""
    return VisualAssert(
        fleet=fleet,
        db=test_db,
        run_id=run_id,
        server_url=tritium_server.url,
    )
