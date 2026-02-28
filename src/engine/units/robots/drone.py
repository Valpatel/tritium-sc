# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
from engine.units.base import CombatStats, MovementCategory, UnitType


class Drone(UnitType):
    type_id = "drone"
    display_name = "Drone"
    icon = "D"
    cot_type = "a-f-A-M-F-Q"  # Friendly air drone/RPV/UAV
    category = MovementCategory.AIR
    speed = 4.0
    cruising_altitude = 15.0
    drain_rate = 0.002
    vision_radius = 60.0
    ambient_radius = 20.0
    cone_range = 45.0
    cone_angle = 45.0
    cone_sweeps = True
    cone_sweep_rpm = 2.0
    placeable = True
    combat = CombatStats(
        health=60, max_health=60,
        weapon_range=50.0, weapon_cooldown=1.0, weapon_damage=8,
        is_combatant=True,
    )
