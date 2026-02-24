from engine.units.base import CombatStats, MovementCategory, UnitType


class MissileTurret(UnitType):
    type_id = "missile_turret"
    display_name = "Missile Turret"
    icon = "T"
    cot_type = "a-f-G-E-W-M-A"  # Friendly ground air defense missile launcher
    category = MovementCategory.STATIONARY
    speed = 0.0
    drain_rate = 0.0003
    vision_radius = 50.0
    ambient_radius = 8.0
    cone_range = 60.0
    cone_angle = 60.0
    placeable = True
    combat = CombatStats(
        health=200, max_health=200,
        weapon_range=35.0, weapon_cooldown=5.0, weapon_damage=50,
        is_combatant=True,
    )
