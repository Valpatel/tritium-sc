"""Sensor node abstraction — pluggable hardware endpoints for Amy."""

from .base import SensorNode, Position
from .virtual import VirtualNode

__all__ = ["SensorNode", "Position", "VirtualNode"]
