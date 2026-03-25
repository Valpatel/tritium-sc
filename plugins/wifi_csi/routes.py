# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WiFi CSI plugin API routes."""

from __future__ import annotations
from fastapi import APIRouter
from typing import Any


def create_router(plugin: Any) -> APIRouter:
    router = APIRouter(prefix="/api/wifi-csi", tags=["wifi-csi"])

    @router.get("/status")
    async def get_status():
        return {
            "plugin": "wifi-csi",
            "healthy": plugin.healthy,
            "mode": plugin._config.get("mode", "rssi"),
            "detections": len(plugin._detections),
            "config": plugin._config,
        }

    @router.get("/detections")
    async def get_detections(limit: int = 20):
        return {"detections": plugin._detections[-limit:]}

    @router.put("/config")
    async def set_config(body: dict):
        for key, value in body.items():
            if key in plugin._config:
                plugin._config[key] = value
        return plugin._config

    return router
