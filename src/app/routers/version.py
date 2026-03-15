# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""API version router — serves version metadata at /api/version and /api/system/version."""

from __future__ import annotations

import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["version"])

_BOOT_TIME = datetime.now(timezone.utc).isoformat()

API_VERSION_INFO = {
    "api_version": "v1",
    "app": "TRITIUM-SC",
    "app_version": "0.1.0",
    "supported_versions": ["v1"],
    "deprecated_versions": [],
    "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    "platform": platform.system(),
}


def _git_info() -> dict:
    """Get git commit hash and branch name. Cached after first call."""
    if hasattr(_git_info, "_cache"):
        return _git_info._cache

    info = {"commit": "unknown", "branch": "unknown", "commit_date": "unknown"}
    # Walk up from this file to find the repo root
    repo_dir = Path(__file__).resolve().parent.parent.parent.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=repo_dir,
        )
        if result.returncode == 0:
            info["commit"] = result.stdout.strip()
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=repo_dir,
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip()
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ci"],
            capture_output=True, text=True, timeout=5, cwd=repo_dir,
        )
        if result.returncode == 0:
            info["commit_date"] = result.stdout.strip()
    except Exception:
        pass

    _git_info._cache = info
    return info


def _feature_count() -> int:
    """Count plugin directories + core routers as proxy for feature count."""
    plugins_dir = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
    routers_dir = Path(__file__).resolve().parent
    count = 0
    if plugins_dir.exists():
        count += sum(
            1 for d in plugins_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        )
    if routers_dir.exists():
        count += sum(
            1 for f in routers_dir.iterdir()
            if f.suffix == ".py" and not f.name.startswith("_")
        )
    return count


@router.get("/api/version")
async def api_version():
    """Return API version information and supported version namespaces."""
    return {
        **API_VERSION_INFO,
        "server_boot": _BOOT_TIME,
    }


@router.get("/api/v1/version")
async def api_v1_version():
    """Return version info under the v1 namespace."""
    return {
        **API_VERSION_INFO,
        "namespace": "/api/v1",
        "server_boot": _BOOT_TIME,
    }


@router.get("/api/system/version")
async def system_version():
    """Return comprehensive system version for deployment tracking.

    Includes git commit hash, branch, build date, wave number, and feature count.
    """
    git = _git_info()
    return {
        **API_VERSION_INFO,
        "server_boot": _BOOT_TIME,
        "git_commit": git["commit"],
        "git_branch": git["branch"],
        "commit_date": git["commit_date"],
        "wave": 80,
        "feature_count": _feature_count(),
        "plugins": 16,
        "routers": 77,
        "routes": 502,
        "hal_libraries": 50,
    }
