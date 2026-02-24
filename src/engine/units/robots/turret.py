from engine.units.base import CombatStats, MovementCategory, UnitType


class Turret(UnitType):
    type_id = "turret"
    display_name = "Turret"
    icon = "T"
    cot_type = "a-f-G-E-W-D"  # Friendly ground direct fire gun
    category = MovementCategory.STATIONARY
    speed = 0.0
    drain_rate = 0.0005
    vision_radius = 50.0
    ambient_radius = 8.0
    cone_range = 40.0
    cone_angle = 90.0
    placeable = True
    combat = CombatStats(
        health=200, max_health=200,
        weapon_range=20.0, weapon_cooldown=1.5, weapon_damage=15,
        is_combatant=True,
    )
