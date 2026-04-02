# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Server lifecycle API — restart, status, version."""

from __future__ import annotations

import os
import sys
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/server", tags=["server"])

# Exit code 42 = restart requested. start.sh loop catches this and restarts.
RESTART_EXIT_CODE = 42

_boot_time = time.time()


@router.get("/status")
async def server_status():
    """Server process info."""
    return {
        "pid": os.getpid(),
        "uptime_s": round(time.time() - _boot_time),
        "python": sys.version.split()[0],
    }


@router.post("/restart")
async def restart_server():
    """Restart the server process.

    Exits with code 42 which start.sh catches and restarts.
    The browser will lose connection briefly, then auto-reconnect.
    """
    import asyncio

    async def _do_restart():
        # Small delay so the HTTP response gets sent first
        await asyncio.sleep(0.5)
        os._exit(RESTART_EXIT_CODE)

    asyncio.create_task(_do_restart())

    return JSONResponse(
        content={
            "restarting": True,
            "message": "Server restarting in 0.5s. Page will auto-reconnect.",
        },
        status_code=200,
    )
