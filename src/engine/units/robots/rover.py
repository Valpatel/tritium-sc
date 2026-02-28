# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
from engine.units.base import CombatStats, MovementCategory, UnitType


class Rover(UnitType):
    type_id = "rover"
    display_name = "Rover"
    icon = "R"
    cot_type = "a-f-G-E-V-A-L"  # Friendly ground light armored vehicle
    category = MovementCategory.GROUND
    speed = 2.0
    drain_rate = 0.001
    vision_radius = 40.0
    ambient_radius = 12.0
    cone_range = 30.0
    cone_angle = 120.0
    placeable = True
    combat = CombatStats(
        health=150, max_health=150,
        weapon_range=60.0, weapon_cooldown=2.0, weapon_damage=12,
        is_combatant=True,
    )
