from engine.units.base import CombatStats, MovementCategory, UnitType


class Person(UnitType):
    """Neutral civilian. Alliance determined at spawn time."""
    type_id = "person"
    display_name = "Person"
    icon = "P"
    cot_type = "a-n-G-U-C"  # Neutral ground civilian
    category = MovementCategory.FOOT
    speed = 1.5
    drain_rate = 0.0
    vision_radius = 15.0
    ambient_radius = 10.0
    placeable = False
    combat = CombatStats(
        health=50, max_health=50,
        weapon_range=0.0, weapon_cooldown=0.0, weapon_damage=0,
        is_combatant=False,
    )
