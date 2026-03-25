# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Root conftest — skip hardware/integration tests when not available."""

import subprocess
import warnings

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


def _check_memory_pressure() -> tuple[bool, str]:
    """Check if system memory is critically low.

    Returns (is_critical, message).
    Critical = available RAM < 4 GB and swap > 80% used.
    """
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])  # kB
            avail_mb = info.get("MemAvailable", 0) // 1024
            swap_total = info.get("SwapTotal", 0)
            swap_free = info.get("SwapFree", 0)
            swap_used_pct = (
                ((swap_total - swap_free) / swap_total * 100)
                if swap_total > 0
                else 0
            )
            is_critical = avail_mb < 4096 and swap_used_pct > 80
            msg = f"RAM available: {avail_mb} MB, swap used: {swap_used_pct:.0f}%"
            return is_critical, msg
    except Exception:
        return False, "memory check unavailable"


_HAS_BCC950 = _bcc950_connected()
_HAS_OLLAMA = _ollama_reachable()


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "hardware" in item.keywords and not _HAS_BCC950:
            item.add_marker(pytest.mark.skip(reason="BCC950 not connected"))
        if "integration" in item.keywords and not _HAS_OLLAMA:
            item.add_marker(pytest.mark.skip(reason="Ollama not reachable"))


def pytest_sessionstart(session):
    """Emit a warning at session start if memory is critically low."""
    is_critical, msg = _check_memory_pressure()
    if is_critical:
        warnings.warn(
            f"MEMORY PRESSURE: {msg}. Tests may be killed by OOM. "
            f"Consider closing other processes or using --gentle mode.",
            RuntimeWarning,
            stacklevel=1,
        )
