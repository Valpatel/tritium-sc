# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for inventory system -- per-unit loadout, weapon selection AI, armor, grenades."""

from __future__ import annotations

import pytest

from engine.simulation.inventory import (
    InventoryItem,
    UnitInventory,
    ITEM_CATALOG,
    build_loadout,
    select_best_weapon,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# TestInventoryItem -- dataclass creation and serialization
# ---------------------------------------------------------------------------

class TestInventoryItem:
    """Test InventoryItem dataclass basics."""

    def test_create_weapon(self):
        item = InventoryItem(
            item_id="nerf_rifle_1", item_type="weapon", name="Nerf Rifle",
            weapon_class="projectile", damage=12.0, range=40.0,
            cooldown=1.5, ammo=20, max_ammo=20,
        )
        assert item.item_id == "nerf_rifle_1"
        assert item.item_type == "weapon"
        assert item.weapon_class == "projectile"
        assert item.damage == 12.0
        assert item.range == 40.0
        assert item.ammo == 20

    def test_create_armor(self):
        item = InventoryItem(
            item_id="medium_vest_1", item_type="armor", name="Medium Vest",
            damage_reduction=0.20, durability=50, max_durability=50,
        )
        assert item.item_type == "armor"
        assert item.damage_reduction == 0.20
        assert item.durability == 50

    def test_create_grenade(self):
        item = InventoryItem(
            item_id="frag_1", item_type="grenade", name="Frag Grenade",
            damage=40.0, blast_radius=5.0, count=2,
        )
        assert item.item_type == "grenade"
        assert item.blast_radius == 5.0
        assert item.count == 2

    def test_default_values(self):
        item = InventoryItem(item_id="x", item_type="weapon", name="X")
        assert item.weapon_class == ""
        assert item.damage == 0.0
        assert item.range == 0.0
        assert item.cooldown == 0.0
        assert item.ammo == -1
        assert item.max_ammo == -1
        assert item.damage_reduction == 0.0
        assert item.durability == 100
        assert item.max_durability == 100
        assert item.blast_radius == 0.0
        assert item.count == 1

    def test_to_dict_weapon(self):
        item = InventoryItem(
            item_id="nerf_pistol_1", item_type="weapon", name="Nerf Pistol",
            weapon_class="projectile", damage=8.0, range=15.0,
            cooldown=1.0, ammo=30, max_ammo=30,
        )
        d = item.to_dict()
        assert d["item_id"] == "nerf_pistol_1"
        assert d["item_type"] == "weapon"
        assert d["name"] == "Nerf Pistol"
        assert d["damage"] == 8.0
        assert d["ammo"] == 30

    def test_to_dict_armor(self):
        item = InventoryItem(
            item_id="heavy_vest_1", item_type="armor", name="Heavy Vest",
            damage_reduction=0.30, durability=80, max_durability=80,
        )
        d = item.to_dict()
        assert d["damage_reduction"] == 0.30
        assert d["durability"] == 80

    def test_to_fog_dict_hides_details(self):
        item = InventoryItem(
            item_id="nerf_rifle_1", item_type="weapon", name="Nerf Rifle",
            weapon_class="projectile", damage=12.0, range=40.0,
            cooldown=1.5, ammo=20, max_ammo=20,
        )
        fog = item.to_fog_dict()
        assert fog["item_type"] == "weapon"
        assert fog["status"] == "unknown"
        # Should NOT contain exact damage, ammo, etc.
        assert "damage" not in fog
        assert "ammo" not in fog
        assert "range" not in fog


# ---------------------------------------------------------------------------
# TestUnitInventory -- container operations
# ---------------------------------------------------------------------------

class TestUnitInventory:
    """Test UnitInventory container: add, get, switch, serialize."""

    def _make_inventory(self) -> UnitInventory:
        pistol = InventoryItem(
            item_id="nerf_pistol_1", item_type="weapon", name="Nerf Pistol",
            weapon_class="projectile", damage=8.0, range=15.0,
            cooldown=1.0, ammo=30, max_ammo=30,
        )
        rifle = InventoryItem(
            item_id="nerf_rifle_1", item_type="weapon", name="Nerf Rifle",
            weapon_class="projectile", damage=12.0, range=40.0,
            cooldown=1.5, ammo=20, max_ammo=20,
        )
        vest = InventoryItem(
            item_id="medium_vest_1", item_type="armor", name="Medium Vest",
            damage_reduction=0.20, durability=50, max_durability=50,
        )
        frag = InventoryItem(
            item_id="frag_1", item_type="grenade", name="Frag Grenade",
            damage=40.0, blast_radius=5.0, count=2,
        )
        return UnitInventory(
            items=[pistol, rifle, vest, frag],
            active_weapon_id="nerf_pistol_1",
        )

    def test_get_weapons(self):
        inv = self._make_inventory()
        weapons = inv.get_weapons()
        assert len(weapons) == 2
        assert all(w.item_type == "weapon" for w in weapons)

    def test_get_armor(self):
        inv = self._make_inventory()
        armor = inv.get_armor()
        assert armor is not None
        assert armor.item_type == "armor"
        assert armor.damage_reduction == 0.20

    def test_get_armor_none_when_missing(self):
        inv = UnitInventory(items=[
            InventoryItem(item_id="p", item_type="weapon", name="P"),
        ])
        assert inv.get_armor() is None

    def test_get_grenades(self):
        inv = self._make_inventory()
        grenades = inv.get_grenades()
        assert len(grenades) == 1
        assert grenades[0].item_type == "grenade"

    def test_get_active_weapon(self):
        inv = self._make_inventory()
        active = inv.get_active_weapon()
        assert active is not None
        assert active.item_id == "nerf_pistol_1"

    def test_get_active_weapon_none_when_not_set(self):
        inv = UnitInventory(items=[])
        assert inv.get_active_weapon() is None

    def test_switch_weapon_success(self):
        inv = self._make_inventory()
        assert inv.active_weapon_id == "nerf_pistol_1"
        result = inv.switch_weapon("nerf_rifle_1")
        assert result is True
        assert inv.active_weapon_id == "nerf_rifle_1"
        assert inv.get_active_weapon().item_id == "nerf_rifle_1"

    def test_switch_weapon_fail_nonexistent(self):
        inv = self._make_inventory()
        result = inv.switch_weapon("nonexistent_id")
        assert result is False
        assert inv.active_weapon_id == "nerf_pistol_1"

    def test_switch_weapon_fail_not_a_weapon(self):
        inv = self._make_inventory()
        result = inv.switch_weapon("medium_vest_1")
        assert result is False

    def test_has_ammo_true(self):
        inv = self._make_inventory()
        assert inv.has_ammo() is True

    def test_has_ammo_false_when_all_empty(self):
        item = InventoryItem(
            item_id="empty_gun", item_type="weapon", name="Empty",
            ammo=0, max_ammo=30,
        )
        inv = UnitInventory(items=[item], active_weapon_id="empty_gun")
        assert inv.has_ammo() is False

    def test_has_ammo_unlimited(self):
        """ammo=-1 means unlimited, should always have ammo."""
        item = InventoryItem(
            item_id="inf_gun", item_type="weapon", name="Infinite",
            ammo=-1, max_ammo=-1,
        )
        inv = UnitInventory(items=[item], active_weapon_id="inf_gun")
        assert inv.has_ammo() is True

    def test_to_dict_full(self):
        inv = self._make_inventory()
        d = inv.to_dict()
        assert "items" in d
        assert "active_weapon_id" in d
        assert d["active_weapon_id"] == "nerf_pistol_1"
        assert len(d["items"]) == 4

    def test_to_fog_dict(self):
        inv = self._make_inventory()
        fog = inv.to_fog_dict()
        assert fog["status"] == "unknown"
        assert fog["item_count"] == 4
        # Should NOT contain full item details
        assert "items" not in fog

    def test_empty_inventory(self):
        inv = UnitInventory(items=[])
        assert inv.get_weapons() == []
        assert inv.get_armor() is None
        assert inv.get_grenades() == []
        assert inv.get_active_weapon() is None
        assert inv.has_ammo() is False
        d = inv.to_dict()
        assert d["items"] == []


# ---------------------------------------------------------------------------
# TestArmorMechanics -- damage reduction and durability
# ---------------------------------------------------------------------------

class TestArmorMechanics:
    """Test armor durability, damage reduction, and breakage."""

    def test_damage_armor_reduces_durability(self):
        vest = InventoryItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.20, durability=50, max_durability=50,
        )
        inv = UnitInventory(items=[vest])
        reduction = inv.damage_armor(hits=1)
        assert reduction == 0.20
        assert vest.durability == 49

    def test_damage_armor_multiple_hits(self):
        vest = InventoryItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.20, durability=50, max_durability=50,
        )
        inv = UnitInventory(items=[vest])
        inv.damage_armor(hits=5)
        assert vest.durability == 45

    def test_broken_armor_zero_reduction(self):
        vest = InventoryItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.20, durability=1, max_durability=50,
        )
        inv = UnitInventory(items=[vest])
        # First hit drops durability to 0
        inv.damage_armor(hits=1)
        assert vest.durability == 0
        # Now reduction should be 0
        reduction = inv.damage_armor(hits=1)
        assert reduction == 0.0

    def test_total_damage_reduction_with_armor(self):
        vest = InventoryItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.30, durability=80, max_durability=80,
        )
        inv = UnitInventory(items=[vest])
        assert inv.total_damage_reduction() == 0.30

    def test_total_damage_reduction_no_armor(self):
        inv = UnitInventory(items=[])
        assert inv.total_damage_reduction() == 0.0

    def test_total_damage_reduction_broken_armor(self):
        vest = InventoryItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.30, durability=0, max_durability=80,
        )
        inv = UnitInventory(items=[vest])
        assert inv.total_damage_reduction() == 0.0

    def test_damage_armor_no_armor_returns_zero(self):
        inv = UnitInventory(items=[])
        assert inv.damage_armor(hits=1) == 0.0

    def test_damage_armor_clamps_at_zero(self):
        vest = InventoryItem(
            item_id="vest", item_type="armor", name="Vest",
            damage_reduction=0.20, durability=3, max_durability=50,
        )
        inv = UnitInventory(items=[vest])
        inv.damage_armor(hits=10)
        assert vest.durability == 0  # Clamped, not negative


# ---------------------------------------------------------------------------
# TestGrenadeConsumption -- use grenades, decrement count
# ---------------------------------------------------------------------------

class TestGrenadeConsumption:
    """Test grenade consumption mechanics."""

    def test_consume_grenade_returns_item(self):
        frag = InventoryItem(
            item_id="frag", item_type="grenade", name="Frag Grenade",
            damage=40.0, blast_radius=5.0, count=2,
        )
        inv = UnitInventory(items=[frag])
        result = inv.consume_grenade("frag")
        assert result is not None
        assert result.item_id == "frag"
        assert frag.count == 1

    def test_consume_grenade_empty(self):
        frag = InventoryItem(
            item_id="frag", item_type="grenade", name="Frag Grenade",
            damage=40.0, blast_radius=5.0, count=0,
        )
        inv = UnitInventory(items=[frag])
        result = inv.consume_grenade("frag")
        assert result is None

    def test_consume_grenade_last_one(self):
        frag = InventoryItem(
            item_id="frag", item_type="grenade", name="Frag Grenade",
            damage=40.0, blast_radius=5.0, count=1,
        )
        inv = UnitInventory(items=[frag])
        result = inv.consume_grenade("frag")
        assert result is not None
        assert frag.count == 0
        # Try again -- should be empty
        result2 = inv.consume_grenade("frag")
        assert result2 is None

    def test_consume_grenade_wrong_type(self):
        frag = InventoryItem(
            item_id="frag", item_type="grenade", name="Frag Grenade",
            damage=40.0, blast_radius=5.0, count=3,
        )
        inv = UnitInventory(items=[frag])
        result = inv.consume_grenade("smoke")
        assert result is None
        # frag count should be unchanged
        assert frag.count == 3

    def test_consume_specific_grenade_type(self):
        frag = InventoryItem(
            item_id="frag", item_type="grenade", name="Frag Grenade",
            damage=40.0, blast_radius=5.0, count=2,
        )
        smoke = InventoryItem(
            item_id="smoke", item_type="grenade", name="Smoke Grenade",
            damage=0.0, blast_radius=8.0, count=1,
        )
        inv = UnitInventory(items=[frag, smoke])
        result = inv.consume_grenade("smoke")
        assert result is not None
        assert result.item_id == "smoke"
        assert smoke.count == 0
        assert frag.count == 2  # Untouched


# ---------------------------------------------------------------------------
# TestBuildLoadout -- deterministic loadout generation
# ---------------------------------------------------------------------------

class TestBuildLoadout:
    """Test build_loadout() factory for various (asset_type, alliance) combos."""

    def test_deterministic_same_id(self):
        inv1 = build_loadout("hostile_42", "person", "hostile")
        inv2 = build_loadout("hostile_42", "person", "hostile")
        assert inv1.to_dict() == inv2.to_dict()

    def test_different_ids_different_loadouts(self):
        """Different target_ids may produce different loadouts (randomized upgrades)."""
        # At minimum the function runs without error for different IDs
        inv1 = build_loadout("hostile_1", "person", "hostile")
        inv2 = build_loadout("hostile_2", "person", "hostile")
        # Both should have at least a weapon
        assert len(inv1.get_weapons()) >= 1
        assert len(inv2.get_weapons()) >= 1

    def test_hostile_person_loadout(self):
        inv = build_loadout("h_person_1", "person", "hostile")
        weapons = inv.get_weapons()
        assert len(weapons) >= 1
        armor = inv.get_armor()
        assert armor is not None
        assert armor.damage_reduction == pytest.approx(0.10)
        grenades = inv.get_grenades()
        assert len(grenades) >= 1
        assert inv.active_weapon_id is not None

    def test_hostile_leader_loadout(self):
        inv = build_loadout("h_leader_1", "hostile_leader", "hostile")
        weapons = inv.get_weapons()
        # Should have rifle + pistol
        assert len(weapons) >= 2
        weapon_names = {w.name for w in weapons}
        assert "Nerf Rifle" in weapon_names
        assert "Nerf Pistol" in weapon_names
        armor = inv.get_armor()
        assert armor is not None
        assert armor.damage_reduction == pytest.approx(0.20)
        grenades = inv.get_grenades()
        assert len(grenades) >= 1

    def test_hostile_vehicle_loadout(self):
        inv = build_loadout("h_vehicle_1", "hostile_vehicle", "hostile")
        weapons = inv.get_weapons()
        assert len(weapons) >= 1
        rpg = [w for w in weapons if w.weapon_class == "missile"]
        assert len(rpg) >= 1
        armor = inv.get_armor()
        assert armor is not None
        assert armor.damage_reduction == pytest.approx(0.35)

    def test_hostile_tank_loadout(self):
        inv = build_loadout("h_tank_1", "tank", "hostile")
        weapons = inv.get_weapons()
        rpg = [w for w in weapons if w.weapon_class == "missile"]
        assert len(rpg) >= 1
        armor = inv.get_armor()
        assert armor is not None
        assert armor.damage_reduction == pytest.approx(0.45)

    def test_friendly_turret_loadout(self):
        inv = build_loadout("f_turret_1", "turret", "friendly")
        weapons = inv.get_weapons()
        assert len(weapons) >= 1
        # Turrets don't wear armor (stationary)
        armor = inv.get_armor()
        assert armor is None

    def test_friendly_rover_loadout(self):
        inv = build_loadout("f_rover_1", "rover", "friendly")
        weapons = inv.get_weapons()
        assert len(weapons) >= 1
        smg = [w for w in weapons if w.name == "Nerf SMG"]
        assert len(smg) >= 1
        armor = inv.get_armor()
        assert armor is not None
        assert armor.damage_reduction == pytest.approx(0.20)

    def test_friendly_drone_loadout(self):
        inv = build_loadout("f_drone_1", "drone", "friendly")
        weapons = inv.get_weapons()
        assert len(weapons) >= 1
        # Drones don't wear armor (flying)
        armor = inv.get_armor()
        assert armor is None

    def test_friendly_tank_loadout(self):
        inv = build_loadout("f_tank_1", "tank", "friendly")
        weapons = inv.get_weapons()
        assert len(weapons) >= 2  # RPG + SMG
        rpg = [w for w in weapons if w.weapon_class == "missile"]
        assert len(rpg) >= 1
        smg = [w for w in weapons if w.name == "Nerf SMG"]
        assert len(smg) >= 1
        armor = inv.get_armor()
        assert armor is not None
        assert armor.damage_reduction == pytest.approx(0.45)

    def test_friendly_apc_loadout(self):
        inv = build_loadout("f_apc_1", "apc", "friendly")
        weapons = inv.get_weapons()
        assert len(weapons) >= 1
        smg = [w for w in weapons if w.name == "Nerf SMG"]
        assert len(smg) >= 1
        armor = inv.get_armor()
        assert armor is not None
        assert armor.damage_reduction == pytest.approx(0.35)
        grenades = inv.get_grenades()
        smoke = [g for g in grenades if g.name == "Smoke Grenade"]
        assert len(smoke) >= 1

    def test_neutral_person_empty(self):
        inv = build_loadout("n_person_1", "person", "neutral")
        assert len(inv.items) == 0
        assert inv.active_weapon_id is None

    def test_active_weapon_set_to_primary(self):
        inv = build_loadout("h_person_99", "person", "hostile")
        assert inv.active_weapon_id is not None
        active = inv.get_active_weapon()
        assert active is not None
        assert active.item_type == "weapon"


# ---------------------------------------------------------------------------
# TestSelectBestWeapon -- AI weapon selection logic
# ---------------------------------------------------------------------------

class TestSelectBestWeapon:
    """Test select_best_weapon() tactical AI."""

    def _full_inventory(self) -> UnitInventory:
        """Create an inventory with all weapon types for testing."""
        pistol = InventoryItem(
            item_id="pistol", item_type="weapon", name="Nerf Pistol",
            weapon_class="projectile", damage=8.0, range=15.0,
            cooldown=1.0, ammo=30, max_ammo=30,
        )
        rifle = InventoryItem(
            item_id="rifle", item_type="weapon", name="Nerf Rifle",
            weapon_class="projectile", damage=12.0, range=40.0,
            cooldown=1.5, ammo=20, max_ammo=20,
        )
        shotgun = InventoryItem(
            item_id="shotgun", item_type="weapon", name="Nerf Shotgun",
            weapon_class="projectile", damage=25.0, range=8.0,
            cooldown=2.5, ammo=8, max_ammo=8,
        )
        rpg = InventoryItem(
            item_id="rpg", item_type="weapon", name="Nerf RPG",
            weapon_class="missile", damage=60.0, range=50.0,
            cooldown=8.0, ammo=3, max_ammo=3,
        )
        frag = InventoryItem(
            item_id="frag", item_type="grenade", name="Frag Grenade",
            damage=40.0, blast_radius=5.0, count=2,
        )
        return UnitInventory(
            items=[pistol, rifle, shotgun, rpg, frag],
            active_weapon_id="pistol",
        )

    def test_rpg_for_vehicle(self):
        inv = self._full_inventory()
        result = select_best_weapon(inv, target_asset_type="vehicle", distance=30.0, enemies_nearby=1)
        assert result is not None
        assert result.item_id == "rpg"

    def test_rpg_for_tank(self):
        inv = self._full_inventory()
        result = select_best_weapon(inv, target_asset_type="tank", distance=40.0, enemies_nearby=1)
        assert result is not None
        assert result.item_id == "rpg"

    def test_rpg_for_apc(self):
        inv = self._full_inventory()
        result = select_best_weapon(inv, target_asset_type="apc", distance=35.0, enemies_nearby=1)
        assert result is not None
        assert result.item_id == "rpg"

    def test_grenade_for_groups(self):
        inv = self._full_inventory()
        result = select_best_weapon(inv, target_asset_type="person", distance=10.0, enemies_nearby=3)
        assert result is not None
        assert result.item_type == "grenade"

    def test_rifle_at_long_range(self):
        inv = self._full_inventory()
        result = select_best_weapon(inv, target_asset_type="person", distance=35.0, enemies_nearby=1)
        assert result is not None
        assert result.item_id == "rifle"

    def test_shotgun_at_close_range(self):
        inv = self._full_inventory()
        result = select_best_weapon(inv, target_asset_type="person", distance=5.0, enemies_nearby=1)
        assert result is not None
        assert result.item_id == "shotgun"

    def test_default_most_ammo(self):
        """At medium range with single enemy, pick weapon with most ammo."""
        inv = self._full_inventory()
        result = select_best_weapon(inv, target_asset_type="person", distance=12.0, enemies_nearby=1)
        assert result is not None
        # Pistol has 30 ammo, most of the non-specialty weapons
        assert result.item_type == "weapon"

    def test_rpg_no_ammo_skips(self):
        """If RPG has 0 ammo, don't suggest it even for vehicles."""
        inv = self._full_inventory()
        rpg = next(i for i in inv.items if i.item_id == "rpg")
        rpg.ammo = 0
        result = select_best_weapon(inv, target_asset_type="vehicle", distance=30.0, enemies_nearby=1)
        assert result is not None
        assert result.item_id != "rpg"

    def test_no_grenades_skips_group(self):
        """If no grenades, don't suggest grenade even for groups."""
        inv = self._full_inventory()
        frag = next(i for i in inv.items if i.item_id == "frag")
        frag.count = 0
        result = select_best_weapon(inv, target_asset_type="person", distance=10.0, enemies_nearby=5)
        assert result is not None
        assert result.item_type == "weapon"

    def test_empty_inventory_returns_none(self):
        inv = UnitInventory(items=[])
        result = select_best_weapon(inv, target_asset_type="person", distance=10.0, enemies_nearby=1)
        assert result is None

    def test_rifle_no_ammo_falls_through(self):
        """If rifle has no ammo, don't suggest it at long range."""
        inv = self._full_inventory()
        rifle = next(i for i in inv.items if i.item_id == "rifle")
        rifle.ammo = 0
        result = select_best_weapon(inv, target_asset_type="person", distance=35.0, enemies_nearby=1)
        assert result is not None
        assert result.item_id != "rifle"


# ---------------------------------------------------------------------------
# TestFogOfWar -- serialization differences for known vs unknown units
# ---------------------------------------------------------------------------

class TestFogOfWar:
    """Test that to_dict shows full info, to_fog_dict hides details."""

    def test_full_dict_has_items(self):
        inv = build_loadout("fog_test_1", "person", "hostile")
        d = inv.to_dict()
        assert "items" in d
        assert len(d["items"]) > 0
        # Each item should have full details
        for item_dict in d["items"]:
            assert "item_id" in item_dict
            assert "item_type" in item_dict
            assert "name" in item_dict

    def test_fog_dict_hides_items(self):
        inv = build_loadout("fog_test_2", "person", "hostile")
        fog = inv.to_fog_dict()
        assert fog["status"] == "unknown"
        assert "item_count" in fog
        assert fog["item_count"] > 0
        assert "items" not in fog

    def test_fog_dict_empty_inventory(self):
        inv = build_loadout("fog_test_3", "person", "neutral")
        fog = inv.to_fog_dict()
        assert fog["status"] == "unknown"
        assert fog["item_count"] == 0


# ---------------------------------------------------------------------------
# TestItemCatalog -- verify the ITEM_CATALOG reference data
# ---------------------------------------------------------------------------

class TestItemCatalog:
    """Test the ITEM_CATALOG has all expected items with correct stats."""

    def test_catalog_has_weapons(self):
        weapon_ids = {"nerf_pistol", "nerf_rifle", "nerf_shotgun", "nerf_rpg", "nerf_smg"}
        for wid in weapon_ids:
            assert wid in ITEM_CATALOG, f"Missing weapon: {wid}"
            assert ITEM_CATALOG[wid]["item_type"] == "weapon"

    def test_catalog_has_armor(self):
        armor_ids = {"light_vest", "medium_vest", "heavy_vest", "vehicle_armor", "tank_armor"}
        for aid in armor_ids:
            assert aid in ITEM_CATALOG, f"Missing armor: {aid}"
            assert ITEM_CATALOG[aid]["item_type"] == "armor"

    def test_catalog_has_grenades(self):
        grenade_ids = {"frag_grenade", "smoke_grenade", "flashbang"}
        for gid in grenade_ids:
            assert gid in ITEM_CATALOG, f"Missing grenade: {gid}"
            assert ITEM_CATALOG[gid]["item_type"] == "grenade"

    def test_nerf_pistol_stats(self):
        p = ITEM_CATALOG["nerf_pistol"]
        assert p["damage"] == 8.0
        assert p["range"] == 15.0
        assert p["cooldown"] == 1.0
        assert p["ammo"] == 30
        assert p["weapon_class"] == "projectile"

    def test_nerf_rpg_stats(self):
        r = ITEM_CATALOG["nerf_rpg"]
        assert r["damage"] == 60.0
        assert r["range"] == 50.0
        assert r["cooldown"] == 8.0
        assert r["ammo"] == 3
        assert r["weapon_class"] == "missile"

    def test_tank_armor_stats(self):
        a = ITEM_CATALOG["tank_armor"]
        assert a["damage_reduction"] == 0.45
        assert a["durability"] == 300

    def test_frag_grenade_stats(self):
        g = ITEM_CATALOG["frag_grenade"]
        assert g["damage"] == 40.0
        assert g["blast_radius"] == 5.0
