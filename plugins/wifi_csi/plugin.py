# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WiFi CSI Plugin — human presence detection via WiFi Channel State Information.

Uses WiFi CSI (Channel State Information) analysis to detect:
- Human presence/occupancy (Phase 1: RSSI variance, no new hardware)
- Body pose estimation (Phase 2: CSI subcarrier analysis, research NICs)
- Vital signs (Phase 3: breathing rate, heart rate via FFT)

Inspired by: https://github.com/ruvnet/RuView
Edge component: tritium-edge hal_wifi_csi.cpp (future)
"""

from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger("wifi-csi")


class WiFiCSIPlugin:
    """WiFi CSI human detection — through-wall sensing without cameras."""

    def __init__(self) -> None:
        self._running = False
        self._config = {
            "enabled": False,
            "mode": "rssi",  # rssi | csi_pose | csi_vitals
            "detection_threshold": 0.6,
            "mqtt_topic": "tritium/+/csi/detection",
            "visualization": "heatmap",  # heatmap | markers | zones
        }
        self._detections = []  # Recent human detections

    @property
    def plugin_id(self) -> str:
        return "tritium.wifi-csi"

    @property
    def name(self) -> str:
        return "WiFi CSI"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def capabilities(self) -> set:
        return {"data_source", "routes", "ui"}

    @property
    def healthy(self) -> bool:
        return self._running

    def configure(self, ctx: Any) -> None:
        self._event_bus = getattr(ctx, "event_bus", None)
        self._logger = getattr(ctx, "logger", None) or log

    def start(self) -> None:
        self._running = True
        log.info("[WiFi CSI] Started (Phase 1: RSSI occupancy detection)")

    def stop(self) -> None:
        self._running = False
        self._detections.clear()

    def process_csi_event(self, data: dict) -> dict | None:
        """Process a CSI detection event from an edge device.

        Args:
            data: {device_id, ap_mac, rssi_variance, subcarriers?, timestamp}

        Returns:
            Detection dict or None if below threshold.
        """
        variance = data.get("rssi_variance", 0)
        if variance < self._config["detection_threshold"]:
            return None

        detection = {
            "type": "human_presence",
            "source": "wifi_csi",
            "device_id": data.get("device_id", "unknown"),
            "ap_mac": data.get("ap_mac", ""),
            "confidence": min(1.0, variance / 2.0),
            "occupancy_estimate": 1 + int(variance * 3),
            "timestamp": data.get("timestamp"),
        }

        self._detections.append(detection)
        if len(self._detections) > 100:
            self._detections = self._detections[-100:]

        return detection
