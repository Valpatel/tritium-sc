# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Pydantic settings for the demo motion sensor.

Standalone -- no dependency on main tritium-sc app.
"""

from pydantic import BaseModel, Field


class SensorConfig(BaseModel):
    """Configuration for a single motion sensor instance."""

    sensor_id: str = Field(default="demo-pir-01", description="Unique sensor identifier")
    sensor_type: str = Field(default="pir", description="Sensor type: pir, microwave, acoustic, tripwire")
    zone: str = Field(default="default", description="Zone name where sensor is placed")
    mqtt_host: str = Field(default="localhost", description="MQTT broker hostname")
    mqtt_port: int = Field(default=1883, description="MQTT broker port")
    site: str = Field(default="home", description="Site identifier in MQTT topic prefix")
    position_x: float = Field(default=0.0, description="Sensor X position on map")
    position_y: float = Field(default=0.0, description="Sensor Y position on map")
    pattern: str = Field(default="random", description="Trigger pattern: random, scheduled, burst, walk_by")
    rate: float = Field(default=0.5, description="Trigger rate in Hz (events per second)")
