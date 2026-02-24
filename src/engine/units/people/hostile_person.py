from engine.units.base import CombatStats, MovementCategory, UnitType


class HostilePerson(UnitType):
    """Armed hostile combatant on foot.

    Maps to the ``person_hostile`` combat profile in the legacy engine.
    """
    type_id = "hostile_person"
    display_name = "Hostile"
    icon = "H"
    cot_type = "a-h-G-U-C-I"  # Hostile ground infantry
    category = MovementCategory.FOOT
    speed = 1.5
    drain_rate = 0.0
    vision_radius = 20.0
    ambient_radius = 12.0
    placeable = False
    combat = CombatStats(
        health=80, max_health=80,
        weapon_range=8.0, weapon_cooldown=2.5, weapon_damage=10,
        is_combatant=True,
    )
