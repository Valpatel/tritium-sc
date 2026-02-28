# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
from engine.units.base import CombatStats, MovementCategory, UnitType


class SwarmDrone(UnitType):
    """Hostile swarm drone -- fast, fragile, flying kamikaze/strafing unit.

    Designed for mass attacks (50+). Low HP, fast speed, short-range weapon.
    Uses boids-like flocking behavior via SwarmBehavior.
    """
    type_id = "swarm_drone"
    display_name = "Swarm Drone"
    icon = "S"
    cot_type = "a-h-A-M-F-Q"  # Hostile air drone/RPV/UAV
    category = MovementCategory.AIR
    speed = 6.0
    cruising_altitude = 8.0
    drain_rate = 0.003
    vision_radius = 30.0
    ambient_radius = 15.0
    placeable = False
    combat = CombatStats(
        health=25, max_health=25,
        weapon_range=20.0, weapon_cooldown=1.0, weapon_damage=5,
        is_combatant=True,
    )
