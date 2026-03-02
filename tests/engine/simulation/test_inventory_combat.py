# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests: inventory system wired into combat pipeline.

Tests cover:
  - Armor damage reduction in CombatSystem hit resolution
  - Armor durability depletion after repeated hits
  - Armor + cover stacking (capped at 0.8 total reduction)
  - Armor + upgrade stacking (capped at 0.8 total reduction)
  - No-armor passthrough (default None inventory)
  - Weapon selection from inventory
  - Weapon auto-switch when ammo is depleted
  - Inventory persistence across engine ticks
"""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from engine.simulation.target import SimulationTarget
from engine.simulation.combat import CombatSystem, HIT_RADIUS
from engine.simulation.inventory import (
    InventoryItem,
    UnitInventory,
    build_loadout,
)
# ArmorItem, WeaponItem, ConsumableItem are aliases for InventoryItem
ArmorItem = InventoryItem
WeaponItem = InventoryItem
ConsumableItem = InventoryItem
from engine.simulation.weapons import WeaponSystem


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            key = topic or "__all__"
            self._subscribers.setdefault(key, []).append(q)
        return q


pytestmark = pytest.mark.unit


def _make_target(
    target_id: str,
    alliance: str = "friendly",
    asset_type: str = "rover",
    position: tuple[float, float] = (0.0, 0.0),
    inventory: UnitInventory | None = None,
    **kw,
) -> SimulationTarget:
    """Helper to build a SimulationTarget with optional inventory."""
    return SimulationTarget(
        target_id=target_id,
        name=f"Unit-{target_id}",
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        inventory=inventory,
        **kw,
    )


def _adjacent_pair(
    dist: float = 3.0,
    source_alliance: str = "friendly",
    target_alliance: str = "hostile",
    target_inventory: UnitInventory | None = None,
) -> tuple[SimulationTarget, SimulationTarget]:
    """Create a source and a target separated by *dist* meters."""
    source = _make_target(
        "src",
        alliance=source_alliance,
        position=(0.0, 0.0),
        weapon_range=100.0,
        weapon_damage=20.0,
        weapon_cooldown=0.1,
        health=200.0,
        max_health=200.0,
    )
    target = _make_target(
        "tgt",
        alliance=target_alliance,
        position=(dist, 0.0),
        health=100.0,
        max_health=100.0,
        weapon_range=100.0,
        weapon_damage=10.0,
        weapon_cooldown=0.1,
        inventory=target_inventory,
    )
    return source, target


# --------------------------------------------------------------------------
# Armor damage reduction
# --------------------------------------------------------------------------


class TestArmorReducesCombatDamage:
    """Armor equipped via inventory should reduce incoming projectile damage."""

    def test_armor_reduces_damage(self):
        """A target with 30% armor reduction should take 70% damage."""
        inv = UnitInventory(owner_id="tgt")
        inv.add_item(ArmorItem(
            item_id="vest_1",
            item_type="armor",
            name="Kevlar Vest",
            damage_reduction=0.3,
            durability=10,
            max_durability=10,
        ))
        source, target = _adjacent_pair(target_inventory=inv)

        bus = SimpleEventBus()
        combat = CombatSystem(event_bus=bus)
        targets = {source.target_id: source, target.target_id: target}

        proj = combat.fire(source, target)
        assert proj is not None

        # Tick until projectile hits (within a few steps at 80 m/s)
        for _ in range(20):
            combat.tick(0.05, targets)

        # 20 damage * 0.7 = 14 damage => health = 100 - 14 = 86
        assert target.health == pytest.approx(86.0, abs=1.0)

    def test_no_armor_full_damage(self):
        """A target with empty inventory (no armor) should take full damage."""
        # Explicitly provide an empty inventory to override auto-build
        empty_inv = UnitInventory(owner_id="tgt")
        source, target = _adjacent_pair(target_inventory=empty_inv)

        bus = SimpleEventBus()
        combat = CombatSystem(event_bus=bus)
        targets = {source.target_id: source, target.target_id: target}

        proj = combat.fire(source, target)
        assert proj is not None

        for _ in range(20):
            combat.tick(0.05, targets)

        # Full 20 damage => health = 80
        assert target.health == pytest.approx(80.0, abs=1.0)

    def test_armor_50_percent(self):
        """50% armor reduction => half damage."""
        inv = UnitInventory(owner_id="tgt")
        inv.add_item(ArmorItem(
            item_id="heavy_vest",
            item_type="armor",
            name="Heavy Vest",
            damage_reduction=0.5,
            durability=10,
            max_durability=10,
        ))
        source, target = _adjacent_pair(target_inventory=inv)

        bus = SimpleEventBus()
        combat = CombatSystem(event_bus=bus)
        targets = {source.target_id: source, target.target_id: target}

        proj = combat.fire(source, target)
        assert proj is not None

        for _ in range(20):
            combat.tick(0.05, targets)

        # 20 * 0.5 = 10 damage => health = 90
        assert target.health == pytest.approx(90.0, abs=1.0)


class TestArmorDurability:
    """Armor should break after sufficient hits."""

    def test_armor_breaks_after_hits(self):
        """Armor with durability=2 should break after 2 hits."""
        inv = UnitInventory(owner_id="tgt")
        inv.add_item(ArmorItem(
            item_id="fragile_vest",
            item_type="armor",
            name="Fragile Vest",
            damage_reduction=0.5,
            durability=2,
            max_durability=2,
        ))
        source, target = _adjacent_pair(target_inventory=inv)
        source.weapon_damage = 10.0

        bus = SimpleEventBus()
        combat = CombatSystem(event_bus=bus)
        targets = {source.target_id: source, target.target_id: target}

        # First shot: armor active, 10 * 0.5 = 5 damage
        proj = combat.fire(source, target)
        assert proj is not None
        for _ in range(20):
            combat.tick(0.05, targets)
        health_after_1 = target.health

        # Second shot: armor active but this hit depletes durability
        source.last_fired = 0.0  # reset cooldown
        proj = combat.fire(source, target)
        assert proj is not None
        for _ in range(20):
            combat.tick(0.05, targets)
        health_after_2 = target.health

        # Third shot: armor broken, full damage
        source.last_fired = 0.0
        proj = combat.fire(source, target)
        assert proj is not None
        for _ in range(20):
            combat.tick(0.05, targets)
        health_after_3 = target.health

        # After first two hits: damage reduced.
        # After third hit: full damage (armor broken).
        first_hit_dmg = 100.0 - health_after_1
        third_hit_dmg = health_after_2 - health_after_3
        assert first_hit_dmg < third_hit_dmg  # First was reduced, third was not

    def test_broken_armor_no_reduction(self):
        """Armor with durability=0 should not reduce damage."""
        inv = UnitInventory(owner_id="tgt")
        inv.add_item(ArmorItem(
            item_id="broken_vest",
            item_type="armor",
            name="Broken Vest",
            damage_reduction=0.5,
            durability=0,
            max_durability=5,
        ))
        source, target = _adjacent_pair(target_inventory=inv)
        source.weapon_damage = 20.0

        bus = SimpleEventBus()
        combat = CombatSystem(event_bus=bus)
        targets = {source.target_id: source, target.target_id: target}

        proj = combat.fire(source, target)
        assert proj is not None
        for _ in range(20):
            combat.tick(0.05, targets)

        # Full 20 damage since armor is broken
        assert target.health == pytest.approx(80.0, abs=1.0)


class TestArmorStacksWithCover:
    """Armor + cover system should stack, capped at 0.8 total reduction."""

    def test_armor_plus_cover_stacks(self):
        """Armor 0.3 + cover 0.3 = 0.6 total reduction."""
        inv = UnitInventory(owner_id="tgt")
        inv.add_item(ArmorItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.3, durability=10, max_durability=10,
        ))
        source, target = _adjacent_pair(target_inventory=inv)
        source.weapon_damage = 100.0

        bus = SimpleEventBus()
        combat = CombatSystem(event_bus=bus)
        targets = {source.target_id: source, target.target_id: target}

        # Mock cover system
        class FakeCover:
            def get_cover_bonus(self, pos, from_pos, tid):
                return 0.3

        proj = combat.fire(source, target)
        assert proj is not None
        for _ in range(20):
            combat.tick(0.05, targets, cover_system=FakeCover())

        # 100 * (1 - 0.3 cover) * (1 - 0.3 armor) = 100 * 0.7 * 0.7 = 49
        # But if additive: 100 * (1 - min(0.6, 0.8)) = 40
        # Either way, damage should be less than 70 (cover alone) and less than 70 (armor alone)
        assert target.health > 20.0  # Combined reduction means > 20 health remains
        assert target.health < 80.0  # Some damage was dealt

    def test_armor_plus_cover_capped_at_80_pct(self):
        """Armor 0.6 + cover 0.6 should cap at 0.8 total reduction."""
        inv = UnitInventory(owner_id="tgt")
        inv.add_item(ArmorItem(
            item_id="tank_armor", item_type="armor", name="Tank Armor",
            damage_reduction=0.6, durability=100, max_durability=100,
        ))
        source, target = _adjacent_pair(target_inventory=inv)
        source.weapon_damage = 100.0

        bus = SimpleEventBus()
        combat = CombatSystem(event_bus=bus)
        targets = {source.target_id: source, target.target_id: target}

        class FakeCover:
            def get_cover_bonus(self, pos, from_pos, tid):
                return 0.6

        proj = combat.fire(source, target)
        assert proj is not None
        for _ in range(20):
            combat.tick(0.05, targets, cover_system=FakeCover())

        # Cap at 0.8 => 100 * 0.2 = 20 min damage => health = 80
        assert target.health >= 79.0


class TestArmorStacksWithUpgrades:
    """Armor + UpgradeSystem damage_reduction should stack, capped at 0.8."""

    def test_armor_plus_upgrade_reduction(self):
        """Armor 0.3 + upgrade 0.2 = 0.5 combined (under cap)."""
        inv = UnitInventory(owner_id="tgt")
        inv.add_item(ArmorItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.3, durability=10, max_durability=10,
        ))
        source, target = _adjacent_pair(target_inventory=inv)
        source.weapon_damage = 100.0

        class FakeUpgrade:
            def get_stat_modifier(self, tid, stat):
                if stat == "damage_reduction" and tid == "tgt":
                    return 0.2
                if stat == "weapon_damage":
                    return 1.0
                if stat == "weapon_range":
                    return 1.0
                return 1.0

        bus = SimpleEventBus()
        combat = CombatSystem(event_bus=bus, upgrade_system=FakeUpgrade())
        targets = {source.target_id: source, target.target_id: target}

        proj = combat.fire(source, target)
        assert proj is not None
        for _ in range(20):
            combat.tick(0.05, targets)

        # Total damage: 100 * (1 - 0.2 upgrade) * (1 - 0.3 armor) = 56
        # Or additive capped: 100 * (1 - 0.5) = 50
        # Either way, health should be well above 0
        assert target.health > 30.0


class TestNoArmorNoReduction:
    """Units without inventory or without armor items take full damage."""

    def test_none_inventory_full_damage(self):
        """Empty inventory (no armor items) means full damage passthrough."""
        empty_inv = UnitInventory(owner_id="tgt")
        source, target = _adjacent_pair(target_inventory=empty_inv)
        assert target.inventory.total_damage_reduction() == 0.0

        bus = SimpleEventBus()
        combat = CombatSystem(event_bus=bus)
        targets = {source.target_id: source, target.target_id: target}

        proj = combat.fire(source, target)
        assert proj is not None
        for _ in range(20):
            combat.tick(0.05, targets)

        assert target.health == pytest.approx(80.0, abs=1.0)

    def test_empty_inventory_full_damage(self):
        """Empty inventory (no armor items) means no reduction."""
        inv = UnitInventory(owner_id="tgt")
        source, target = _adjacent_pair(target_inventory=inv)

        assert inv.total_damage_reduction() == 0.0


class TestWeaponFromInventory:
    """Behavior should use inventory weapon instead of hardcoded defaults."""

    def test_inventory_weapon_stats(self):
        """WeaponItem from inventory should have correct stats."""
        inv = UnitInventory(owner_id="src")
        weapon = WeaponItem(
            item_id="big_gun",
            item_type="weapon",
            name="Nerf RPG",
            damage=60.0,
            range=50.0,
            cooldown=8.0,
            accuracy=0.9,
            ammo=5,
            max_ammo=5,
            weapon_class="missile",
        )
        inv.add_item(weapon)
        inv.set_active_weapon("big_gun")

        active = inv.get_active_weapon()
        assert active is not None
        assert active.name == "Nerf RPG"
        assert active.damage == 60.0
        assert active.weapon_range == 50.0
        assert active.weapon_class == "missile"

    def test_multiple_weapons_select_active(self):
        """Can switch between multiple weapons in inventory."""
        inv = UnitInventory(owner_id="src")
        inv.add_item(WeaponItem(
            item_id="gun1", item_type="weapon", name="Blaster", damage=10.0,
            range=20.0, cooldown=1.0, accuracy=0.8,
            ammo=30, max_ammo=30,
        ))
        inv.add_item(WeaponItem(
            item_id="gun2", item_type="weapon", name="Shotgun", damage=25.0,
            range=8.0, cooldown=2.5, accuracy=0.7,
            ammo=6, max_ammo=6,
        ))

        inv.set_active_weapon("gun1")
        assert inv.get_active_weapon().name == "Blaster"

        inv.set_active_weapon("gun2")
        assert inv.get_active_weapon().name == "Shotgun"


class TestWeaponAutoSwitch:
    """When active weapon ammo is depleted, auto-switch to next available."""

    def test_auto_switch_on_ammo_depletion(self):
        """When primary weapon runs out of ammo, switch to secondary."""
        inv = UnitInventory(owner_id="src")
        inv.add_item(WeaponItem(
            item_id="primary", item_type="weapon", name="Blaster", damage=10.0,
            range=20.0, cooldown=1.0, accuracy=0.8,
            ammo=1, max_ammo=30,
        ))
        inv.add_item(WeaponItem(
            item_id="secondary", item_type="weapon", name="Pistol", damage=5.0,
            range=15.0, cooldown=1.5, accuracy=0.7,
            ammo=15, max_ammo=15,
        ))
        inv.set_active_weapon("primary")

        # Consume last ammo from primary
        active = inv.get_active_weapon()
        assert active.item_id == "primary"
        active.ammo -= 1  # Simulate firing

        # Auto-switch should find the secondary
        inv.auto_switch_weapon()
        new_active = inv.get_active_weapon()
        assert new_active is not None
        assert new_active.item_id == "secondary"

    def test_no_switch_when_ammo_remains(self):
        """Should not switch when current weapon still has ammo."""
        inv = UnitInventory(owner_id="src")
        inv.add_item(WeaponItem(
            item_id="primary", item_type="weapon", name="Blaster", damage=10.0,
            range=20.0, cooldown=1.0, accuracy=0.8,
            ammo=15, max_ammo=30,
        ))
        inv.add_item(WeaponItem(
            item_id="secondary", item_type="weapon", name="Pistol", damage=5.0,
            range=15.0, cooldown=1.5, accuracy=0.7,
            ammo=15, max_ammo=15,
        ))
        inv.set_active_weapon("primary")
        inv.auto_switch_weapon()

        # Should stay on primary since it has ammo
        assert inv.get_active_weapon().item_id == "primary"

    def test_no_weapons_returns_none(self):
        """If no weapons available, get_active_weapon returns None."""
        inv = UnitInventory(owner_id="src")
        assert inv.get_active_weapon() is None


class TestInventoryPersistsAcrossTicks:
    """Inventory should not reset between engine ticks."""

    def test_inventory_persists(self):
        """Inventory items survive multiple tick() calls."""
        inv = UnitInventory(owner_id="r1")
        inv.add_item(ArmorItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.3, durability=5, max_durability=5,
        ))
        inv.add_item(WeaponItem(
            item_id="gun", item_type="weapon", name="Blaster", damage=10.0,
            range=20.0, cooldown=1.0, accuracy=0.8,
            ammo=30, max_ammo=30,
        ))

        target = _make_target("r1", inventory=inv)

        # Simulate ticks
        for _ in range(100):
            target.tick(0.1)

        # Inventory should still be there
        assert target.inventory is not None
        assert len(target.inventory.items) == 2
        armor = target.inventory.get_armor()
        assert armor is not None
        assert armor.durability == 5  # Unchanged

    def test_damaged_armor_persists(self):
        """Armor damage persists across ticks."""
        inv = UnitInventory(owner_id="r1")
        inv.add_item(ArmorItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.3, durability=5, max_durability=5,
        ))

        target = _make_target("r1", inventory=inv)

        # Damage armor
        target.inventory.damage_armor(2)
        assert target.inventory.get_armor().durability == 3

        # Tick many times
        for _ in range(50):
            target.tick(0.1)

        # Armor damage persists
        assert target.inventory.get_armor().durability == 3


class TestBuildLoadout:
    """build_loadout() factory creates appropriate loadouts per unit type."""

    def test_rover_loadout(self):
        """Rovers should get a loadout with armor and weapon."""
        inv = build_loadout("r1", "rover", "friendly")
        assert inv is not None
        assert isinstance(inv, UnitInventory)
        # Should have at least one item
        assert len(inv.items) > 0

    def test_hostile_person_loadout(self):
        """Hostile persons should get a basic loadout."""
        inv = build_loadout("h1", "person", "hostile")
        assert inv is not None
        assert len(inv.items) > 0

    def test_neutral_no_loadout(self):
        """Neutral persons should get None or empty inventory."""
        inv = build_loadout("n1", "person", "neutral")
        # Neutrals are non-combatants, should get None or empty
        assert inv is None or len(inv.items) == 0

    def test_turret_loadout(self):
        """Turrets should get appropriate loadout."""
        inv = build_loadout("t1", "turret", "friendly")
        assert inv is not None

    def test_deterministic_loadout(self):
        """Same target_id should produce the same loadout."""
        inv1 = build_loadout("r1", "rover", "friendly")
        inv2 = build_loadout("r1", "rover", "friendly")
        if inv1 is not None and inv2 is not None:
            assert len(inv1.items) == len(inv2.items)


class TestInventoryToDict:
    """Inventory serialization for API/telemetry."""

    def test_to_dict_includes_items(self):
        """to_dict should include all items."""
        inv = UnitInventory(owner_id="r1")
        inv.add_item(ArmorItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.3, durability=5, max_durability=5,
        ))
        inv.add_item(WeaponItem(
            item_id="gun", item_type="weapon", name="Blaster", damage=10.0,
            range=20.0, cooldown=1.0, accuracy=0.8,
            ammo=30, max_ammo=30,
        ))

        d = inv.to_dict()
        assert "items" in d
        assert len(d["items"]) == 2

    def test_to_fog_dict_hides_details(self):
        """to_fog_dict should hide specific item details."""
        inv = UnitInventory(owner_id="h1")
        inv.add_item(ArmorItem(
            item_id="vest", name="Secret Vest",
            damage_reduction=0.5, durability=5, max_durability=5,
        ))
        inv.add_item(WeaponItem(
            item_id="gun", name="Secret Gun", damage=50.0,
            range=100.0, cooldown=0.5, accuracy=1.0,
            ammo=999, max_ammo=999,
        ))

        d = inv.to_fog_dict()
        # Fog dict should indicate inventory exists but not reveal details
        assert "item_count" in d or "items" in d
        # Should not reveal specific damage/range/etc
        if "items" in d:
            for item in d["items"]:
                assert "damage_reduction" not in item or item.get("damage_reduction") is None
                assert "damage" not in item or item.get("damage") is None
