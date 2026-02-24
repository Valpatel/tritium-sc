from engine.units.base import CombatStats, MovementCategory, UnitType


class Tank(UnitType):
    type_id = "tank"
    display_name = "Tank"
    icon = "K"
    cot_type = "a-f-G-E-V-A-T"  # Friendly ground tank
    category = MovementCategory.GROUND
    speed = 1.5
    drain_rate = 0.0008
    vision_radius = 45.0
    ambient_radius = 15.0
    cone_range = 35.0
    cone_angle = 90.0
    placeable = True
    combat = CombatStats(
        health=400, max_health=400,
        weapon_range=25.0, weapon_cooldown=3.0, weapon_damage=30,
        is_combatant=True,
    )
