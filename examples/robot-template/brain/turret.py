"""Turret controller — pan/tilt aiming and firing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hardware.base import HardwareInterface


class TurretController:
    """Controls the turret pan/tilt servos and trigger."""

    def __init__(self, hardware: HardwareInterface, config: dict) -> None:
        self._hw = hardware
        self._pan = 0.0   # degrees, 0 = forward
        self._tilt = 0.0  # degrees, 0 = level

    @property
    def pan(self) -> float:
        return self._pan

    @property
    def tilt(self) -> float:
        return self._tilt

    def aim(self, pan: float, tilt: float) -> None:
        """Set turret pan/tilt angles."""
        self._pan = max(-90, min(90, pan))
        self._tilt = max(-30, min(60, tilt))
        self._hw.set_turret(self._pan, self._tilt)

    def fire(self) -> None:
        """Activate trigger."""
        print("  [TURRET] FIRE!")
        self._hw.fire_trigger()

    def stop(self) -> None:
        """Center turret."""
        self.aim(0, 0)
