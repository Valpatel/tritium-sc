from engine.units.base import CombatStats, MovementCategory, UnitType


class APC(UnitType):
    type_id = "apc"
    display_name = "APC"
    icon = "A"
    cot_type = "a-f-G-E-V-A-A"  # Friendly ground APC
    category = MovementCategory.GROUND
    speed = 2.5
    drain_rate = 0.0010
    vision_radius = 35.0
    ambient_radius = 12.0
    cone_range = 25.0
    cone_angle = 120.0
    placeable = True
    combat = CombatStats(
        health=300, max_health=300,
        weapon_range=15.0, weapon_cooldown=1.0, weapon_damage=8,
        is_combatant=True,
    )
