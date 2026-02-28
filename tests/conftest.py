# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Root conftest — skip hardware/integration tests when not available."""

import subprocess

import pytest


def _bcc950_connected() -> bool:
    """Check if a BCC950 camera is connected via v4l2."""
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            capture_output=True, text=True, timeout=5,
        )
        return "BCC950" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _ollama_reachable() -> bool:
    """Check if Ollama API is reachable."""
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        return True
    except Exception:
        return False


_HAS_BCC950 = _bcc950_connected()
_HAS_OLLAMA = _ollama_reachable()


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "hardware" in item.keywords and not _HAS_BCC950:
            item.add_marker(pytest.mark.skip(reason="BCC950 not connected"))
        if "integration" in item.keywords and not _HAS_OLLAMA:
            item.add_marker(pytest.mark.skip(reason="Ollama not reachable"))
