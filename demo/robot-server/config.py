# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Pydantic settings for the demo robot server."""

from pydantic import BaseModel, Field


class RobotConfig(BaseModel):
    """Configuration for a demo robot instance."""

    robot_id: str = Field(default="demo-rover-01", description="Unique robot identifier")
    name: str = Field(default="Demo Rover", description="Human-readable robot name")
    asset_type: str = Field(default="rover", description="Robot type: rover, drone, turret, tank")
    mqtt_host: str = Field(default="localhost", description="MQTT broker hostname")
    mqtt_port: int = Field(default=1883, description="MQTT broker port")
    site: str = Field(default="home", description="Site identifier for MQTT topic prefix")
    start_x: float = Field(default=0.0, description="Starting X position (meters)")
    start_y: float = Field(default=0.0, description="Starting Y position (meters)")
    telemetry_interval: float = Field(default=0.5, description="Telemetry publish interval (seconds)")
