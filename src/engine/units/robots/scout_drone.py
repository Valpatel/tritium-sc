from engine.units.base import CombatStats, MovementCategory, UnitType


class ScoutDrone(UnitType):
    type_id = "scout_drone"
    display_name = "Scout Drone"
    icon = "D"
    cot_type = "a-f-A-M-F-Q"  # Friendly air drone/RPV/UAV (recon)
    category = MovementCategory.AIR
    speed = 5.0
    drain_rate = 0.0025
    vision_radius = 60.0
    ambient_radius = 25.0
    cone_range = 55.0
    cone_angle = 30.0
    cone_sweeps = True
    cone_sweep_rpm = 3.0
    placeable = True
    combat = CombatStats(
        health=40, max_health=40,
        weapon_range=8.0, weapon_cooldown=1.5, weapon_damage=5,
        is_combatant=True,
    )
