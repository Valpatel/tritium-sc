from engine.units.base import CombatStats, MovementCategory, UnitType


class MotionSensor(UnitType):
    type_id = "sensor"
    display_name = "Motion Sensor"
    icon = "S"
    cot_type = "a-f-G-E-S-E"  # Friendly ground emplaced sensor
    category = MovementCategory.STATIONARY
    speed = 0.0
    drain_rate = 0.0
    vision_radius = 30.0
    ambient_radius = 20.0
    placeable = False
    combat = CombatStats(
        health=30, max_health=30,
        weapon_range=0.0, weapon_cooldown=0.0, weapon_damage=0,
        is_combatant=False,
    )
