# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
from engine.units.base import CombatStats, MovementCategory, UnitType


class HostileLeader(UnitType):
    type_id = "hostile_leader"
    display_name = "Hostile Leader"
    icon = "L"
    cot_type = "a-h-G-U-C-I"  # Hostile ground infantry (command)
    category = MovementCategory.FOOT
    speed = 1.8
    drain_rate = 0.0
    vision_radius = 25.0
    ambient_radius = 15.0
    placeable = False
    combat = CombatStats(
        health=150, max_health=150,
        weapon_range=50.0, weapon_cooldown=2.0, weapon_damage=12,
        is_combatant=True,
    )
