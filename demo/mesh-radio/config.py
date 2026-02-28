# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Pydantic settings for the demo mesh radio node.

Standalone -- no dependency on main tritium-sc app.
"""

from pydantic import BaseModel, Field


class MeshRadioConfig(BaseModel):
    """Configuration for a single mesh radio node instance."""

    node_id: str = Field(default="!aabbccdd", description="Unique node identifier (hex with ! prefix)")
    long_name: str = Field(default="Demo Node", description="Human-readable node name")
    short_name: str = Field(default="", description="Short name (auto-generated from long_name if empty)")
    protocol: str = Field(default="meshtastic", description="Mesh protocol: meshtastic or meshcore")
    lat: float = Field(default=0.0, description="Latitude")
    lng: float = Field(default=0.0, description="Longitude")
    alt: float = Field(default=0.0, description="Altitude in meters")
    mqtt_host: str = Field(default="localhost", description="MQTT broker hostname")
    mqtt_port: int = Field(default=1883, description="MQTT broker port")
    site: str = Field(default="home", description="Site identifier in MQTT topic prefix")
    hardware: str = Field(default="heltec_v3", description="Hardware type identifier")
    movement: str = Field(default="stationary", description="Movement pattern: stationary, random_walk, waypoint")
    position_interval: float = Field(default=15.0, description="Position broadcast interval in seconds")
    telemetry_interval: float = Field(default=60.0, description="Telemetry broadcast interval in seconds")
