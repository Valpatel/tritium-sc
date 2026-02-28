# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
from engine.units.base import CombatStats, MovementCategory, UnitType


class HeavyTurret(UnitType):
    type_id = "heavy_turret"
    display_name = "Heavy Turret"
    icon = "T"
    cot_type = "a-f-G-E-W-D-H"  # Friendly ground direct fire gun heavy
    category = MovementCategory.STATIONARY
    speed = 0.0
    drain_rate = 0.0004
    vision_radius = 50.0
    ambient_radius = 8.0
    cone_range = 50.0
    cone_angle = 75.0
    placeable = True
    combat = CombatStats(
        health=350, max_health=350,
        weapon_range=120.0, weapon_cooldown=2.5, weapon_damage=25,
        is_combatant=True,
    )
