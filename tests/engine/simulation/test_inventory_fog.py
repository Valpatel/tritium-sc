# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests: inventory fog-of-war in to_dict() serialization.

Tests cover:
  - Friendly units expose full inventory in to_dict()
  - Hostile units hide inventory details when viewer is friendly
  - Neutral units hide inventory details when viewer is friendly
  - Internal view (viewer_alliance=None) shows everything
  - Eliminated units may reveal inventory
  - to_dict backward compatibility (no viewer_alliance param = friendly default)
"""

from __future__ import annotations

import pytest

from tritium_lib.sim_engine.core.entity import SimulationTarget
from tritium_lib.sim_engine.core.inventory import (
    ArmorItem,
    UnitInventory,
    WeaponItem,
)


pytestmark = pytest.mark.unit


def _make_target_with_inventory(
    target_id: str,
    alliance: str,
    asset_type: str = "rover",
) -> SimulationTarget:
    """Create a target with a populated inventory."""
    inv = UnitInventory(owner_id=target_id)
    inv.add_item(ArmorItem(
        item_id=f"{target_id}_vest",
        item_type="armor",
        name="Tactical Vest",
        damage_reduction=0.3,
        durability=10,
        max_durability=10,
    ))
    inv.add_item(WeaponItem(
        item_id=f"{target_id}_gun",
        item_type="weapon",
        name="Nerf Blaster",
        damage=15.0,
        range=25.0,
        cooldown=1.5,
        accuracy=0.85,
        ammo=30,
        max_ammo=30,
    ))
    return SimulationTarget(
        target_id=target_id,
        name=f"Unit-{target_id}",
        alliance=alliance,
        asset_type=asset_type,
        position=(10.0, 20.0),
        inventory=inv,
    )


class TestFriendlyShowsFullInventory:
    """Friendly units should expose complete inventory details."""

    def test_friendly_to_dict_has_inventory(self):
        """Friendly unit to_dict() includes full inventory."""
        t = _make_target_with_inventory("f1", "friendly")
        d = t.to_dict(viewer_alliance="friendly")
        assert "inventory" in d
        inv_data = d["inventory"]
        assert "items" in inv_data
        assert len(inv_data["items"]) == 2

    def test_friendly_inventory_has_item_details(self):
        """Friendly inventory items include damage_reduction, damage, etc."""
        t = _make_target_with_inventory("f1", "friendly")
        d = t.to_dict(viewer_alliance="friendly")
        items = d["inventory"]["items"]
        # Find the armor item
        armor = [i for i in items if i.get("item_type") == "armor"][0]
        assert "damage_reduction" in armor
        assert armor["damage_reduction"] == pytest.approx(0.3)
        # Find the weapon item
        weapon = [i for i in items if i.get("item_type") == "weapon"][0]
        assert "damage" in weapon
        assert weapon["damage"] == pytest.approx(15.0)

    def test_friendly_sees_friendly_full(self):
        """Friendly viewer sees friendly unit's full inventory."""
        t = _make_target_with_inventory("f1", "friendly")
        d = t.to_dict(viewer_alliance="friendly")
        assert "inventory" in d
        assert "items" in d["inventory"]
        assert len(d["inventory"]["items"]) == 2


class TestHostileHidesInventory:
    """Hostile unit inventory should be hidden from friendly viewer."""

    def test_hostile_hides_from_friendly(self):
        """Hostile to_dict(viewer_alliance='friendly') should hide details."""
        t = _make_target_with_inventory("h1", "hostile", "person")
        d = t.to_dict(viewer_alliance="friendly")
        assert "inventory" in d
        inv_data = d["inventory"]
        # Should be fog dict — no detailed item stats
        if "items" in inv_data:
            for item in inv_data["items"]:
                # Individual item stats should be hidden
                assert "damage_reduction" not in item or item.get("damage_reduction") is None
                assert "damage" not in item or item.get("damage") is None

    def test_hostile_item_count_visible(self):
        """Fog dict should at minimum indicate how many items exist."""
        t = _make_target_with_inventory("h1", "hostile", "person")
        d = t.to_dict(viewer_alliance="friendly")
        inv_data = d["inventory"]
        # Should have item_count or items with hidden stats
        has_count = "item_count" in inv_data
        has_items = "items" in inv_data and len(inv_data["items"]) > 0
        assert has_count or has_items


class TestNeutralHidesInventory:
    """Neutral unit inventory should be hidden from friendly viewer."""

    def test_neutral_hides_from_friendly(self):
        """Neutral to_dict(viewer_alliance='friendly') should hide details."""
        t = _make_target_with_inventory("n1", "neutral", "person")
        d = t.to_dict(viewer_alliance="friendly")
        assert "inventory" in d
        inv_data = d["inventory"]
        if "items" in inv_data:
            for item in inv_data["items"]:
                assert "damage_reduction" not in item or item.get("damage_reduction") is None


class TestInternalShowsAll:
    """Internal view (viewer_alliance=None) exposes everything."""

    def test_internal_shows_hostile_inventory(self):
        """viewer_alliance=None reveals hostile inventory fully."""
        t = _make_target_with_inventory("h1", "hostile", "person")
        d = t.to_dict(viewer_alliance=None)
        assert "inventory" in d
        inv_data = d["inventory"]
        assert "items" in inv_data
        assert len(inv_data["items"]) == 2
        # Full details visible
        armor = [i for i in inv_data["items"] if i.get("item_type") == "armor"][0]
        assert "damage_reduction" in armor
        assert armor["damage_reduction"] == pytest.approx(0.3)

    def test_internal_shows_neutral_inventory(self):
        """viewer_alliance=None reveals neutral inventory fully."""
        t = _make_target_with_inventory("n1", "neutral", "person")
        d = t.to_dict(viewer_alliance=None)
        assert "inventory" in d
        inv_data = d["inventory"]
        assert "items" in inv_data


class TestEliminatedRevealsInventory:
    """Dead units could reveal their inventory (design choice)."""

    def test_eliminated_hostile_reveals(self):
        """Eliminated hostile shows full inventory to friendly viewer."""
        t = _make_target_with_inventory("h1", "hostile", "person")
        t.health = 0.0
        t.status = "eliminated"
        d = t.to_dict(viewer_alliance="friendly")
        assert "inventory" in d
        inv_data = d["inventory"]
        # Eliminated units reveal their inventory
        assert "items" in inv_data
        assert len(inv_data["items"]) == 2


class TestToDictBackwardCompatibility:
    """to_dict() without viewer_alliance should work like before."""

    def test_default_viewer_alliance(self):
        """to_dict() with no args should use viewer_alliance='friendly' default."""
        t = _make_target_with_inventory("f1", "friendly")
        # Call without args — should work
        d = t.to_dict()
        assert "inventory" in d

    def test_no_inventory_no_key(self):
        """Non-combatant target without inventory should have inventory=None."""
        # Neutral persons are non-combatants and get no auto-built inventory
        t = SimulationTarget(
            target_id="bare",
            name="Bare",
            alliance="neutral",
            asset_type="animal",
            position=(0.0, 0.0),
            is_combatant=False,
        )
        d = t.to_dict()
        # Non-combatant neutral should have inventory=None
        inv = d.get("inventory")
        assert inv is None

    def test_existing_fields_unchanged(self):
        """Adding inventory should not affect existing to_dict fields."""
        t = _make_target_with_inventory("f1", "friendly")
        d = t.to_dict()
        # All existing fields should still be present
        assert "target_id" in d
        assert "name" in d
        assert "alliance" in d
        assert "health" in d
        assert "position" in d
        assert "weapon_range" in d
        assert d["target_id"] == "f1"
