"""Abstract hardware interface for robot control.

All hardware backends (simulated, GPIO, etc.) implement this interface.
The brain modules only talk to this interface, never directly to hardware.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class HardwareInterface(ABC):
    """Abstract interface for robot hardware control."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize hardware (open GPIO, connect to motor drivers, etc)."""

    @abstractmethod
    def shutdown(self) -> None:
        """Safely shut down all hardware."""

    @abstractmethod
    def set_motors(self, left: float, right: float) -> None:
        """Set motor speeds. -1.0 = full reverse, 0 = stop, 1.0 = full forward."""

    @abstractmethod
    def get_position(self) -> tuple[float, float]:
        """Get current (x, y) position estimate."""

    @abstractmethod
    def get_heading(self) -> float:
        """Get current heading in degrees (0 = north/+y, clockwise)."""

    @abstractmethod
    def get_speed(self) -> float:
        """Get current speed in units/second."""

    @abstractmethod
    def get_battery(self) -> float:
        """Get battery level 0.0-1.0."""

    @abstractmethod
    def set_turret(self, pan: float, tilt: float) -> None:
        """Set turret pan/tilt angles in degrees."""

    @abstractmethod
    def fire_trigger(self) -> None:
        """Activate the firing mechanism (nerf trigger)."""
