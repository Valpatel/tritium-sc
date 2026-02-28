# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
from engine.units.base import CombatStats, MovementCategory, UnitType


class Animal(UnitType):
    """Animal -- non-combatant."""
    type_id = "animal"
    display_name = "Animal"
    icon = "A"
    cot_type = "a-n-G-U-i"  # Neutral ground individual
    category = MovementCategory.FOOT
    speed = 0.0
    drain_rate = 0.0
    vision_radius = 25.0
    ambient_radius = 5.0
    placeable = False
    combat = CombatStats(
        health=30, max_health=30,
        weapon_range=0.0, weapon_cooldown=0.0, weapon_damage=0,
        is_combatant=False,
    )
