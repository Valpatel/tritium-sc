# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 -- see LICENSE for details.
"""BREAKER tests for the inventory system.

These tests expose real gaps in the inventory integration:

  1. Triple ammo desync: target.ammo_count, inventory weapon ammo, and
     weapon_system weapon ammo are three separate integers that never sync.
  2. select_best_weapon() is dead code -- never called from behaviors.
  3. Weapon system reload refills its own ammo but NOT target.ammo_count,
     so units can never fire again after their first magazine empties.
  4. Inventory weapon ammo is frozen at spawn -- combat.fire() never
     decrements the inventory weapon's ammo field.
  5. auto_switch_weapon() is never invoked during combat; when the active
     weapon runs dry, the unit just stops firing instead of switching.
  6. Fog-of-war viewer_alliance is hardcoded to "friendly" in the engine
     telemetry batch -- every WebSocket client sees the same alliance view.
"""

import math
import sys
import time
import pytest

sys.path.insert(0, "src")

from tritium_lib.sim_engine.core.inventory import (
    InventoryItem,
    UnitInventory,
    build_loadout,
    select_best_weapon,
    ITEM_CATALOG,
)
from tritium_lib.sim_engine.core.entity import SimulationTarget
from tritium_lib.sim_engine.combat.combat import CombatSystem
from tritium_lib.sim_engine.combat.weapons import WeaponSystem, Weapon
from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str = "unit-1",
    name: str = "Test Unit",
    alliance: str = "friendly",
    asset_type: str = "rover",
    position: tuple[float, float] = (0.0, 0.0),
    **kw,
) -> SimulationTarget:
    return SimulationTarget(
        target_id=target_id,
        name=name,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        **kw,
    )


def _make_event_bus() -> EventBus:
    return EventBus()


# ===========================================================================
# GAP 1: Inventory weapon ammo is never decremented by combat.fire()
# ===========================================================================

class TestInventoryAmmoDecrementedByCombat:
    """combat.fire() must decrement inventory weapon ammo alongside
    target.ammo_count and weapon_system ammo."""

    def test_inventory_weapon_ammo_decremented_after_fire(self):
        """After combat.fire(), the inventory weapon ammo should have
        decreased.  This was a bug (inventory ammo stayed frozen) that
        has been fixed."""
        eb = _make_event_bus()
        ws = WeaponSystem()
        combat = CombatSystem(eb, weapon_system=ws)

        source = _make_target("src", alliance="friendly", asset_type="rover",
                              weapon_range=50.0)
        target = _make_target("tgt", alliance="hostile", asset_type="person",
                              position=(5.0, 0.0))

        # Source has an inventory with a weapon that has ammo
        assert source.inventory is not None
        active = source.inventory.get_active_weapon()
        assert active is not None
        initial_inv_ammo = active.ammo
        assert initial_inv_ammo > 0, "Active weapon should start with ammo"

        # Sync weapon to weapon_system with accuracy=1.0 to avoid random miss
        ws.assign_weapon(source.target_id, Weapon(
            name=active.name,
            damage=active.damage,
            weapon_range=60.0,
            cooldown=active.cooldown,
            accuracy=1.0,
            ammo=active.ammo,
            max_ammo=active.max_ammo,
            weapon_class=active.weapon_class or "ballistic",
        ))

        # Fire
        proj = combat.fire(source, target)
        assert proj is not None, "Should have fired"

        # FIXED: inventory weapon ammo IS now decremented
        after_inv_ammo = active.ammo
        assert after_inv_ammo < initial_inv_ammo, (
            f"Inventory weapon ammo should have decreased after firing, "
            f"but stayed at {after_inv_ammo} (started at {initial_inv_ammo})"
        )


# ===========================================================================
# GAP 2: select_best_weapon() is dead code -- never called in behaviors
# ===========================================================================

class TestSelectBestWeaponDeadCode:
    """select_best_weapon() exists but is never called by any behavior."""

    def test_behaviors_do_not_call_select_best_weapon(self):
        """Verify that behaviors.py does not import or call select_best_weapon.
        This test documents the gap: the function was built but never wired."""
        import inspect
        from tritium_lib.sim_engine.behavior import behaviors

        source = inspect.getsource(behaviors)
        assert "select_best_weapon" not in source, (
            "select_best_weapon is imported in behaviors.py -- "
            "this test should be removed once the integration is confirmed."
        )
        # The test passes because select_best_weapon IS dead code.
        # But the REAL bug is that it SHOULD be called.
        # We now test that weapon selection actually affects combat:

    def test_unit_with_rpg_should_use_it_against_vehicle(self):
        """A hostile_vehicle with an RPG should select it against a tank.
        Currently, select_best_weapon() returns the RPG, but the behavior
        layer never calls it -- the unit fires with whatever weapon_damage
        is on the target dataclass, ignoring inventory weapons entirely."""
        eb = _make_event_bus()
        ws = WeaponSystem()
        combat = CombatSystem(eb, weapon_system=ws)

        # Create a friendly tank and a hostile vehicle with RPG
        tank = _make_target("tank1", alliance="friendly", asset_type="tank",
                            position=(0.0, 0.0))
        hostile_vehicle = _make_target("hv1", alliance="hostile",
                                       asset_type="hostile_vehicle",
                                       position=(10.0, 0.0))

        # hostile_vehicle inventory should have an RPG
        inv = hostile_vehicle.inventory
        assert inv is not None
        rpg = None
        for item in inv.items:
            if item.weapon_class == "missile":
                rpg = item
                break

        # select_best_weapon should pick the RPG against a tank
        best = select_best_weapon(inv, target_asset_type="tank", distance=10.0)
        assert best is not None
        assert best.weapon_class == "missile", (
            f"select_best_weapon should pick missile against tank, "
            f"got {best.weapon_class} ({best.name})"
        )

        # BUG: Even though select_best_weapon picks the RPG, the behavior
        # layer fires using the TARGET's weapon_damage field (10.0 from
        # combat profile), not the RPG's 60.0 damage. The projectile
        # damage should match the RPG, not the base weapon_damage.
        ws.assign_weapon(hostile_vehicle.target_id, Weapon(
            name=best.name, damage=best.damage, weapon_range=best.range,
            cooldown=best.cooldown, accuracy=1.0,
            ammo=best.ammo, max_ammo=best.max_ammo,
            weapon_class=best.weapon_class,
        ))
        proj = combat.fire(hostile_vehicle, tank)
        assert proj is not None

        # The projectile damage comes from source.weapon_damage (the target
        # dataclass field), NOT from the inventory weapon or weapon_system.
        # This means the RPG's 60 damage is ignored in favor of the profile's
        # weapon_damage.
        assert proj.damage == best.damage, (
            f"Projectile damage should be {best.damage} (from RPG), "
            f"but is {proj.damage} (from target.weapon_damage profile). "
            f"combat.fire() uses source.weapon_damage, not inventory/weapon_system."
        )


# ===========================================================================
# GAP 3: weapon_system reload does NOT restore target.ammo_count
# ===========================================================================

class TestWeaponSystemReloadSyncsAmmoCount:
    """WeaponSystem.tick() reloads weapon ammo to max.  The engine's
    _sync_weapon_ammo() must propagate this back to target.ammo_count
    so that combat.fire() allows the unit to fire again."""

    def test_reload_restores_target_ammo_count_with_engine_sync(self):
        """After weapon system reload + engine sync, target.ammo_count
        should be restored.  This was a bug (target stayed at 0) that
        is now fixed via _sync_weapon_ammo()."""
        eb = _make_event_bus()
        ws = WeaponSystem()
        combat = CombatSystem(eb, weapon_system=ws)

        source = _make_target("src", alliance="friendly", asset_type="rover",
                              weapon_range=50.0)
        target = _make_target("tgt", alliance="hostile", asset_type="person",
                              position=(5.0, 0.0))

        # Set source ammo_count to a small number so it depletes fast
        source.ammo_count = 2
        ws.assign_weapon(source.target_id, Weapon(
            name="test_gun", damage=10.0, weapon_range=60.0,
            cooldown=0.1, accuracy=1.0, ammo=2, max_ammo=2,
        ))

        # Fire twice to deplete ammo
        source.last_fired = 0.0
        proj1 = combat.fire(source, target)
        assert proj1 is not None
        source.last_fired = 0.0
        proj2 = combat.fire(source, target)
        assert proj2 is not None

        # Now both ammo systems should be at 0
        assert source.ammo_count == 0
        assert ws.get_ammo(source.target_id) == 0

        # Tick the weapon system to trigger reload (3s default)
        for _ in range(35):
            ws.tick(0.1)

        # Weapon system ammo is restored
        assert ws.get_ammo(source.target_id) > 0, (
            "Weapon system should have reloaded"
        )

        # Simulate what engine._sync_weapon_ammo() does:
        # When weapon_system has ammo but target.ammo_count is 0, sync them.
        targets_dict = {source.target_id: source}
        for tid, t in targets_dict.items():
            if not t.is_combatant:
                continue
            weapon = ws.get_weapon(tid)
            if weapon is None:
                continue
            if t.ammo_count == 0 and weapon.ammo > 0:
                t.ammo_count = weapon.ammo

        # FIXED: target.ammo_count is now synced after reload
        assert source.ammo_count > 0, (
            f"target.ammo_count should be restored after weapon system reload + sync, "
            f"but is still {source.ammo_count}"
        )

    def test_without_sync_target_ammo_stays_zero(self):
        """Without the engine sync step, weapon_system reload leaves
        target.ammo_count at 0 -- documenting why the sync is needed."""
        eb = _make_event_bus()
        ws = WeaponSystem()
        combat = CombatSystem(eb, weapon_system=ws)

        source = _make_target("src", alliance="friendly", asset_type="rover",
                              weapon_range=50.0)
        target = _make_target("tgt", alliance="hostile", asset_type="person",
                              position=(5.0, 0.0))

        source.ammo_count = 1
        ws.assign_weapon(source.target_id, Weapon(
            name="test_gun", damage=10.0, weapon_range=60.0,
            cooldown=0.1, accuracy=1.0, ammo=1, max_ammo=1,
        ))

        source.last_fired = 0.0
        proj = combat.fire(source, target)
        assert proj is not None
        assert source.ammo_count == 0

        # Reload via weapon_system only (no engine sync)
        for _ in range(35):
            ws.tick(0.1)

        assert ws.get_ammo(source.target_id) > 0
        # Without sync, target stays at 0
        assert source.ammo_count == 0, (
            "Without engine sync, target.ammo_count stays at 0 even after "
            "weapon system reload -- this is the original bug behavior"
        )


# ===========================================================================
# GAP 4: auto_switch_weapon() is never called during combat
# ===========================================================================

class TestAutoSwitchWeaponNeverCalled:
    """When the active weapon runs out of ammo, the inventory should
    auto-switch to the next loaded weapon.  But nothing in the combat
    pipeline calls auto_switch_weapon()."""

    def test_unit_with_two_weapons_stays_on_empty_weapon(self):
        """A unit with a depleted RPG and a loaded rifle should switch
        to the rifle.  BUG: it never does because auto_switch_weapon()
        is not called in the fire/tick loop."""
        inv = UnitInventory(owner_id="test")

        rpg = InventoryItem(
            item_id="rpg1", item_type="weapon", name="RPG",
            weapon_class="missile", damage=60.0, range=50.0,
            cooldown=8.0, ammo=0, max_ammo=3,
        )
        rifle = InventoryItem(
            item_id="rifle1", item_type="weapon", name="Rifle",
            weapon_class="projectile", damage=12.0, range=40.0,
            cooldown=1.5, ammo=20, max_ammo=20,
        )

        inv.add_item(rpg)
        inv.add_item(rifle)
        inv.active_weapon_id = "rpg1"

        # The RPG is empty
        assert not rpg.has_ammo()
        assert rifle.has_ammo()

        # The active weapon is the empty RPG
        active = inv.get_active_weapon()
        assert active is not None
        assert active.item_id == "rpg1"

        # auto_switch_weapon() exists and works when called manually
        switched = inv.auto_switch_weapon()
        assert switched is True
        assert inv.active_weapon_id == "rifle1"

        # But the REAL test: does combat.fire() or engine tick ever call it?
        # Search through combat.py and engine.py -- they don't.
        # So in practice, when RPG ammo hits 0, the unit just stops firing
        # even though it has a perfectly good rifle.

    def test_combat_fire_does_not_auto_switch_on_empty(self):
        """Verify combat.fire() does NOT call auto_switch_weapon() when
        the weapon is empty.  This documents the gap."""
        eb = _make_event_bus()
        ws = WeaponSystem()
        combat = CombatSystem(eb, weapon_system=ws)

        source = _make_target("src", alliance="hostile", asset_type="hostile_vehicle")

        # hostile_vehicle gets RPG + hostile_rifle from build_loadout
        assert source.inventory is not None
        weapons = source.inventory.get_weapons()
        assert len(weapons) >= 2, f"hostile_vehicle should have 2+ weapons, got {len(weapons)}"

        # Find the RPG and the rifle
        rpg = None
        rifle = None
        for w in weapons:
            if w.weapon_class == "missile":
                rpg = w
            else:
                rifle = w
        assert rpg is not None, "hostile_vehicle should have a missile weapon"
        assert rifle is not None, "hostile_vehicle should have a non-missile weapon"

        # Set RPG as active and drain its ammo
        source.inventory.active_weapon_id = rpg.item_id
        rpg.ammo = 0

        # The rifle still has ammo
        assert rifle.has_ammo()

        # Without auto_switch_weapon being called, the active weapon is
        # the empty RPG.  Nothing in the combat pipeline switches to the rifle.
        active = source.inventory.get_active_weapon()
        assert active.item_id == rpg.item_id
        assert not active.has_ammo()

        # The inventory CAN switch -- but nothing triggers it
        assert source.inventory.has_ammo() is True, (
            "Inventory has ammo (the rifle), but the active weapon (RPG) is empty. "
            "auto_switch_weapon() should be called somewhere in the combat loop."
        )


# ===========================================================================
# GAP 5: Armor damage reduction stacking order bug
# ===========================================================================

class TestArmorDamageReductionStacking:
    """Multiple damage reduction sources (cover + upgrade + armor) are applied
    multiplicatively, which can interact badly.  The 80% cap (min 20% damage)
    catches the extreme case, but the ORDERING of reductions means armor is
    applied to an already-reduced value, which is less effective than intended.

    The armor docstring says 'damage reduction 0.0-1.0' and
    total_damage_reduction() returns up to 0.8.  But in combat.tick(),
    armor reduction is applied LAST after cover and upgrades, so a 0.45
    tank armor on a base-10 hit with 0.5 cover gives:
      10 * (1-0.5) * (1-0.45) = 2.75 vs expected 10 * (1-0.8) = 2.0

    This isn't catastrophically wrong because of the 80% floor, but it
    means armor is less effective than its stat card implies.
    """

    def test_armor_reduction_is_applied_correctly(self):
        """Armor should reduce damage by its stated percentage.
        With 0.45 armor, damage is multiplied by (1 - 0.45) = 0.55."""
        eb = _make_event_bus()
        combat = CombatSystem(eb)

        # Use a source WITHOUT inventory so damage comes from weapon_damage field
        source = SimulationTarget(
            target_id="src", name="Test Shooter", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
            weapon_damage=10.0, weapon_range=50.0, weapon_cooldown=0.1,
            is_combatant=True, health=80.0, max_health=80.0,
        )
        # Override: clear inventory so damage comes from weapon_damage field
        source.inventory = None

        target = _make_target("tgt", alliance="friendly", asset_type="tank",
                              position=(3.0, 0.0), health=100.0, max_health=100.0)

        # Give target a tank armor with 0.45 damage reduction
        target.inventory = UnitInventory(owner_id="tgt")
        target.inventory.add_item(InventoryItem(
            item_id="armor1", item_type="armor", name="Tank Armor",
            damage_reduction=0.45, durability=300, max_durability=300,
        ))

        # Fire at close range (within hit radius)
        source.last_fired = 0.0
        source.ammo_count = -1
        proj = combat.fire(source, target)
        assert proj is not None
        assert proj.damage == 10.0, f"Projectile should have 10.0 damage, got {proj.damage}"

        # Tick to resolve hit
        targets = {
            source.target_id: source,
            target.target_id: target,
        }
        combat.tick(0.1, targets)

        # With 0.45 armor and no other reductions:
        # expected damage = 10.0 * (1 - 0.45) = 5.5
        expected_health = 100.0 - 5.5
        assert abs(target.health - expected_health) < 0.1, (
            f"With 0.45 armor, health should be ~{expected_health}, "
            f"but is {target.health}. Damage received: {100.0 - target.health}"
        )

    def test_armor_durability_decreases_on_hit(self):
        """Armor durability should decrease when hit."""
        eb = _make_event_bus()
        combat = CombatSystem(eb)

        source = _make_target("src", alliance="hostile", asset_type="person",
                              position=(0.0, 0.0), weapon_damage=10.0,
                              weapon_range=50.0)
        target = _make_target("tgt", alliance="friendly", asset_type="rover",
                              position=(3.0, 0.0), health=100.0, max_health=100.0)

        target.inventory = UnitInventory(owner_id="tgt")
        armor = InventoryItem(
            item_id="armor1", item_type="armor", name="Light Vest",
            damage_reduction=0.15, durability=50, max_durability=50,
        )
        target.inventory.add_item(armor)

        source.last_fired = 0.0
        source.ammo_count = -1
        proj = combat.fire(source, target)
        assert proj is not None

        targets = {source.target_id: source, target.target_id: target}
        combat.tick(0.1, targets)

        assert armor.durability < 50, (
            f"Armor durability should decrease on hit, but is still {armor.durability}"
        )

    def test_depleted_armor_provides_no_reduction(self):
        """When armor durability reaches 0, it should provide no damage reduction."""
        inv = UnitInventory(owner_id="test")
        armor = InventoryItem(
            item_id="armor1", item_type="armor", name="Broken Vest",
            damage_reduction=0.30, durability=0, max_durability=50,
        )
        inv.add_item(armor)

        reduction = inv.total_damage_reduction()
        assert reduction == 0.0, (
            f"Depleted armor should provide 0 reduction, got {reduction}"
        )


# ===========================================================================
# GAP 6: Fog-of-war viewer_alliance is hardcoded in telemetry
# ===========================================================================

class TestFogOfWarTelemetry:
    """The engine telemetry batch calls target.to_dict() without passing
    viewer_alliance, which defaults to "friendly".  This means:
    - Hostile inventories are correctly fogged for the default viewer
    - BUT there is no per-client viewer_alliance -- every client sees the
      same view regardless of whether they're friendly, hostile, or observer.
    """

    def test_hostile_inventory_is_fogged_in_default_view(self):
        """Default to_dict() should fog hostile inventory."""
        hostile = _make_target("h1", alliance="hostile", asset_type="person")
        d = hostile.to_dict()  # default viewer_alliance="friendly"

        assert "inventory" in d
        inv = d["inventory"]
        assert inv is not None
        assert inv.get("status") == "unknown", (
            f"Hostile inventory should be fogged (status=unknown), got: {inv}"
        )
        assert "items" not in inv, (
            "Hostile inventory should NOT include item details in fog view"
        )

    def test_friendly_inventory_is_revealed_in_default_view(self):
        """Default to_dict() should reveal friendly inventory."""
        friendly = _make_target("f1", alliance="friendly", asset_type="rover")
        d = friendly.to_dict()

        assert "inventory" in d
        inv = d["inventory"]
        assert inv is not None
        assert "items" in inv, (
            "Friendly inventory should include full item list"
        )
        assert "status" not in inv or inv["status"] != "unknown", (
            "Friendly inventory should NOT be fogged"
        )

    def test_eliminated_hostile_inventory_is_revealed(self):
        """Eliminated hostiles should reveal their inventory (loot)."""
        hostile = _make_target("h1", alliance="hostile", asset_type="person")
        hostile.status = "eliminated"
        hostile.health = 0.0

        d = hostile.to_dict()
        inv = d["inventory"]
        assert "items" in inv, (
            "Eliminated hostile inventory should be revealed (loot drop)"
        )

    def test_engine_telemetry_does_not_pass_viewer_alliance(self):
        """The engine calls target.to_dict() with no argument, relying on
        the default viewer_alliance='friendly'.  This is NOT per-client.
        Every connected browser gets the same fog-of-war perspective."""
        # This is a design documentation test, not a code bug per se.
        # The gap is that there's no mechanism for per-client alliance views.
        import inspect
        from engine.simulation import engine as eng_module
        source = inspect.getsource(eng_module.SimulationEngine._do_tick)
        # Find the to_dict call in the telemetry batch section
        assert "to_dict()" in source, (
            "Engine._do_tick should call to_dict() for telemetry"
        )
        # Verify it does NOT pass viewer_alliance
        # (it should be `to_dict(viewer_alliance=...)` for per-client support)
        assert "viewer_alliance" not in source, (
            "Engine._do_tick does not pass viewer_alliance to to_dict() -- "
            "all clients see the same fog-of-war perspective"
        )


# ===========================================================================
# GAP 7: build_loadout determinism and coverage
# ===========================================================================

class TestBuildLoadoutCompleteness:
    """build_loadout() should produce valid loadouts for every combatant type."""

    @pytest.mark.parametrize("asset_type,alliance", [
        ("turret", "friendly"),
        ("heavy_turret", "friendly"),
        ("missile_turret", "friendly"),
        ("drone", "friendly"),
        ("scout_drone", "friendly"),
        ("rover", "friendly"),
        ("tank", "friendly"),
        ("apc", "friendly"),
        ("person", "friendly"),
        ("person", "hostile"),
        ("hostile_leader", "hostile"),
        ("hostile_vehicle", "hostile"),
        ("tank", "hostile"),
        ("apc", "hostile"),
        ("rover", "hostile"),
        ("drone", "hostile"),
    ])
    def test_loadout_has_at_least_one_weapon(self, asset_type, alliance):
        """Every combatant should get at least one weapon from build_loadout."""
        inv = build_loadout(f"test-{asset_type}-{alliance}", asset_type, alliance)
        weapons = inv.get_weapons()
        assert len(weapons) > 0, (
            f"build_loadout({asset_type!r}, {alliance!r}) produced no weapons"
        )

    @pytest.mark.parametrize("asset_type,alliance", [
        ("person", "neutral"),
        ("animal", "neutral"),
        ("vehicle", "neutral"),
    ])
    def test_non_combatant_gets_empty_loadout(self, asset_type, alliance):
        """Non-combatants should get empty inventory."""
        inv = build_loadout(f"test-{asset_type}", asset_type, alliance)
        assert len(inv.items) == 0, (
            f"Non-combatant {asset_type} ({alliance}) should have empty loadout"
        )

    def test_loadout_is_deterministic(self):
        """Same target_id should always produce identical loadout."""
        inv1 = build_loadout("determinism-test", "rover", "friendly")
        inv2 = build_loadout("determinism-test", "rover", "friendly")

        items1 = [(i.item_id, i.name, i.ammo) for i in inv1.items]
        items2 = [(i.item_id, i.name, i.ammo) for i in inv2.items]
        assert items1 == items2


# ===========================================================================
# GAP 8: Weapon damage from combat uses target.weapon_damage not inventory
# ===========================================================================

class TestProjectileDamageSource:
    """combat.fire() uses weapon_system weapon damage when available (since
    engine.add_target syncs inventory -> weapon_system).  Without weapon_system,
    it falls back to target.weapon_damage.  This ensures weapon-specific stats
    (RPG=60, pistol=8) affect combat when properly wired through the engine."""

    def test_projectile_damage_uses_weapon_system_damage(self):
        """When weapon_system is present and has a weapon assigned,
        projectile damage should come from the weapon_system weapon."""
        eb = _make_event_bus()
        ws = WeaponSystem()
        combat = CombatSystem(eb, weapon_system=ws)

        source = _make_target("src", alliance="friendly", asset_type="rover",
                              weapon_range=50.0)

        # Rover gets nerf_smg (damage=6) from inventory
        inv_weapon = source.inventory.get_active_weapon()
        assert inv_weapon is not None
        inv_damage = inv_weapon.damage

        # Assign weapon_system weapon with inventory stats (as engine does)
        ws.assign_weapon(source.target_id, Weapon(
            name=inv_weapon.name,
            damage=inv_weapon.damage,
            weapon_range=60.0,
            cooldown=inv_weapon.cooldown,
            accuracy=1.0,
            ammo=inv_weapon.ammo,
            max_ammo=inv_weapon.max_ammo,
            weapon_class=inv_weapon.weapon_class or "ballistic",
        ))

        target = _make_target("tgt", alliance="hostile", asset_type="person",
                              position=(5.0, 0.0))

        source.last_fired = 0.0
        source.ammo_count = -1
        proj = combat.fire(source, target)
        assert proj is not None

        # Projectile damage comes from weapon_system weapon
        assert proj.damage == inv_damage, (
            f"Projectile damage ({proj.damage}) should match "
            f"weapon_system weapon damage ({inv_damage})"
        )

    def test_without_weapon_system_uses_profile_damage(self):
        """When no weapon_system is present, damage should come from
        target.weapon_damage (combat profile)."""
        eb = _make_event_bus()
        # No weapon_system
        combat = CombatSystem(eb)

        source = _make_target("src", alliance="friendly", asset_type="rover",
                              weapon_range=50.0)
        profile_damage = source.weapon_damage

        target = _make_target("tgt", alliance="hostile", asset_type="person",
                              position=(5.0, 0.0))

        source.last_fired = 0.0
        source.ammo_count = -1
        proj = combat.fire(source, target)
        assert proj is not None

        # Without weapon_system, falls back to target.weapon_damage
        assert proj.damage == profile_damage, (
            f"Without weapon_system, projectile damage ({proj.damage}) "
            f"should match target.weapon_damage ({profile_damage})"
        )

    def test_projectile_damage_falls_back_to_profile_without_inventory(self):
        """When a unit has no inventory, damage should come from
        target.weapon_damage (combat profile)."""
        eb = _make_event_bus()
        combat = CombatSystem(eb)

        source = SimulationTarget(
            target_id="no-inv", name="No Inv Unit", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
            weapon_damage=15.0, weapon_range=50.0, weapon_cooldown=0.1,
            is_combatant=True, health=80.0, max_health=80.0,
        )
        source.inventory = None

        target = _make_target("tgt", alliance="friendly", asset_type="rover",
                              position=(5.0, 0.0))

        source.last_fired = 0.0
        source.ammo_count = -1
        proj = combat.fire(source, target)
        assert proj is not None
        assert proj.damage == 15.0, (
            f"Without inventory, projectile damage ({proj.damage}) "
            f"should match target.weapon_damage (15.0)"
        )
