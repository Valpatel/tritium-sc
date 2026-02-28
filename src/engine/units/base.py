# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Base classes for the unit type system.

MovementCategory -- enum for movement capabilities
CombatStats      -- frozen dataclass for weapon/health stats
UnitType         -- abstract base every concrete type subclasses
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class MovementCategory(Enum):
    """How a unit moves through the battlespace."""
    STATIONARY = "stationary"
    GROUND = "ground"
    FOOT = "foot"
    AIR = "air"


@dataclass(frozen=True)
class CombatStats:
    """Immutable combat profile for a unit type."""
    health: int
    max_health: int
    weapon_range: float
    weapon_cooldown: float
    weapon_damage: int
    is_combatant: bool
    weapon_id: str = ""  # Reference to weapon definition in weapons.WEAPONS


class UnitType:
    """Abstract base for every unit type definition.

    Subclasses MUST set all ClassVar fields.  The registry discovers
    concrete subclasses automatically at import time.
    """

    # -- identity --
    type_id: ClassVar[str]
    display_name: ClassVar[str]
    icon: ClassVar[str]
    cot_type: ClassVar[str] = "a-u-G"  # MIL-STD-2525 CoT type code

    # -- movement --
    category: ClassVar[MovementCategory]
    speed: ClassVar[float]

    # -- combat --
    combat: ClassVar[CombatStats]

    # -- power --
    drain_rate: ClassVar[float]  # battery drain per second

    # -- altitude --
    cruising_altitude: ClassVar[float] = 0.0  # meters AGL for flying types

    # -- perception --
    vision_radius: ClassVar[float]
    ambient_radius: ClassVar[float] = 10.0
    cone_range: ClassVar[float] = 0.0
    cone_angle: ClassVar[float] = 0.0
    cone_sweeps: ClassVar[bool] = False
    cone_sweep_rpm: ClassVar[float] = 0.0

    # -- spawn rules --
    placeable: ClassVar[bool] = False  # can operator place this during setup?

    # -- helpers --

    @classmethod
    def is_mobile(cls) -> bool:
        return cls.category is not MovementCategory.STATIONARY

    @classmethod
    def is_flying(cls) -> bool:
        return cls.category is MovementCategory.AIR

    @classmethod
    def is_ground(cls) -> bool:
        return cls.category is MovementCategory.GROUND

    @classmethod
    def is_foot(cls) -> bool:
        return cls.category is MovementCategory.FOOT

    @classmethod
    def is_stationary(cls) -> bool:
        return cls.category is MovementCategory.STATIONARY

    def __repr__(self) -> str:
        return f"<UnitType {self.type_id}>"
