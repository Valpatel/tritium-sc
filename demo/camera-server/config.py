# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Pydantic settings for the demo camera server."""
from pydantic import BaseModel, Field


class CameraConfig(BaseModel):
    """Configuration for the demo camera server."""

    camera_id: str = Field(default="demo-cam-01", description="Unique camera identifier")
    port: int = Field(default=8081, description="HTTP server port for MJPEG/snapshot/status")
    mqtt_host: str = Field(default="localhost", description="MQTT broker hostname")
    mqtt_port: int = Field(default=1883, description="MQTT broker port")
    site: str = Field(default="home", description="Site identifier for MQTT topic prefix")
    fps: int = Field(default=10, description="Target frames per second")
    width: int = Field(default=640, description="Frame width in pixels")
    height: int = Field(default=480, description="Frame height in pixels")
    mode: str = Field(default="procedural", description="Frame generation mode: procedural, noise, video")
    video_file: str = Field(default="", description="Path to video file (for video mode)")
