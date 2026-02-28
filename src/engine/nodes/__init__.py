# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Sensor node abstraction — pluggable hardware endpoints for Amy."""

from .base import SensorNode, Position
from .virtual import VirtualNode

__all__ = ["SensorNode", "Position", "VirtualNode"]
