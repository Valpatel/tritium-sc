# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
from engine.units.base import CombatStats, MovementCategory, UnitType


class HostileVehicle(UnitType):
    type_id = "hostile_vehicle"
    display_name = "Hostile Vehicle"
    icon = "V"
    cot_type = "a-h-G-E-V"  # Hostile ground vehicle
    category = MovementCategory.GROUND
    speed = 6.0
    drain_rate = 0.0
    vision_radius = 30.0
    ambient_radius = 15.0
    cone_range = 20.0
    cone_angle = 90.0
    placeable = False
    combat = CombatStats(
        health=200, max_health=200,
        weapon_range=70.0, weapon_cooldown=2.0, weapon_damage=15,
        is_combatant=True,
    )
