from engine.units.base import CombatStats, MovementCategory, UnitType


class Camera(UnitType):
    type_id = "camera"
    display_name = "Camera"
    icon = "C"
    cot_type = "a-f-G-E-S-E"  # Friendly ground emplaced sensor
    category = MovementCategory.STATIONARY
    speed = 0.0
    drain_rate = 0.0
    vision_radius = 30.0
    ambient_radius = 5.0
    cone_range = 30.0
    cone_angle = 60.0
    cone_sweeps = True
    cone_sweep_rpm = 1.0
    placeable = False
    combat = CombatStats(
        health=50, max_health=50,
        weapon_range=0.0, weapon_cooldown=0.0, weapon_damage=0,
        is_combatant=False,
    )
