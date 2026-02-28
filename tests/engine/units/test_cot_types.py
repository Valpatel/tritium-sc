# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for CoT type codes on unit types.

Validates that every UnitType has a valid cot_type field and that
the registry helper functions (get_cot_type, cot_type_for_target)
correctly resolve and swap affiliations.
"""

import pytest


# ---------------------------------------------------------------------------
# All types have cot_type
# ---------------------------------------------------------------------------

class TestCotTypeField:
    """Every registered UnitType must have a valid cot_type."""

    def test_all_types_have_cot_type(self):
        from engine.units import all_types
        for cls in all_types():
            assert hasattr(cls, "cot_type"), f"{cls.type_id} missing cot_type"
            assert isinstance(cls.cot_type, str), f"{cls.type_id} cot_type not str"

    def test_all_cot_types_start_with_a(self):
        from engine.units import all_types
        for cls in all_types():
            assert cls.cot_type.startswith("a-"), (
                f"{cls.type_id} cot_type={cls.cot_type!r} must start with 'a-'"
            )

    def test_all_cot_types_have_affiliation_char(self):
        from engine.units import all_types
        valid_affil = {"f", "h", "n", "u"}
        for cls in all_types():
            assert len(cls.cot_type) >= 3, f"{cls.type_id} cot_type too short"
            affil = cls.cot_type[2]
            assert affil in valid_affil, (
                f"{cls.type_id} affiliation char {affil!r} not in {valid_affil}"
            )

    def test_all_cot_types_have_dimension(self):
        """Position 4 should be a dimension marker (G=ground, A=air, etc.)."""
        from engine.units import all_types
        for cls in all_types():
            parts = cls.cot_type.split("-")
            assert len(parts) >= 3, f"{cls.type_id} code has < 3 parts"

    def test_friendly_types_have_f_affiliation(self):
        from engine.units import get_type
        friendly_ids = ["rover", "drone", "scout_drone", "turret",
                        "heavy_turret", "missile_turret", "tank", "apc",
                        "camera", "sensor"]
        for tid in friendly_ids:
            cls = get_type(tid)
            assert cls is not None, f"{tid} not registered"
            assert cls.cot_type[2] == "f", (
                f"{tid} expected friendly (f), got {cls.cot_type[2]!r}"
            )

    def test_hostile_types_have_h_affiliation(self):
        from engine.units import get_type
        hostile_ids = ["hostile_person", "hostile_leader", "hostile_vehicle"]
        for tid in hostile_ids:
            cls = get_type(tid)
            assert cls is not None, f"{tid} not registered"
            assert cls.cot_type[2] == "h", (
                f"{tid} expected hostile (h), got {cls.cot_type[2]!r}"
            )

    def test_neutral_types_have_n_affiliation(self):
        from engine.units import get_type
        neutral_ids = ["person", "vehicle", "animal"]
        for tid in neutral_ids:
            cls = get_type(tid)
            assert cls is not None, f"{tid} not registered"
            assert cls.cot_type[2] == "n", (
                f"{tid} expected neutral (n), got {cls.cot_type[2]!r}"
            )


# ---------------------------------------------------------------------------
# Specific codes per the MIL-STD-2525 mapping
# ---------------------------------------------------------------------------

class TestSpecificCodes:
    """Verify exact CoT codes for each unit type."""

    @pytest.mark.parametrize("type_id,expected", [
        ("rover",          "a-f-G-E-V-A-L"),
        ("drone",          "a-f-A-M-F-Q"),
        ("scout_drone",    "a-f-A-M-F-Q"),
        ("turret",         "a-f-G-E-W-D"),
        ("heavy_turret",   "a-f-G-E-W-D-H"),
        ("missile_turret", "a-f-G-E-W-M-A"),
        ("tank",           "a-f-G-E-V-A-T"),
        ("apc",            "a-f-G-E-V-A-A"),
        ("camera",         "a-f-G-E-S-E"),
        ("sensor",         "a-f-G-E-S-E"),
        ("person",         "a-n-G-U-C"),
        ("hostile_person", "a-h-G-U-C-I"),
        ("hostile_leader", "a-h-G-U-C-I"),
        ("hostile_vehicle","a-h-G-E-V"),
        ("vehicle",        "a-n-G-E-V-C"),
        ("animal",         "a-n-G-U-i"),
    ])
    def test_cot_type_code(self, type_id, expected):
        from engine.units import get_type
        cls = get_type(type_id)
        assert cls is not None, f"{type_id} not registered"
        assert cls.cot_type == expected


# ---------------------------------------------------------------------------
# get_cot_type
# ---------------------------------------------------------------------------

class TestGetCotType:
    """Test the get_cot_type() registry helper."""

    def test_known_type(self):
        from engine.units import get_cot_type
        assert get_cot_type("rover") == "a-f-G-E-V-A-L"

    def test_unknown_type_returns_none(self):
        from engine.units import get_cot_type
        assert get_cot_type("submarine") is None

    def test_alias_resolves(self):
        from engine.units import get_cot_type
        assert get_cot_type("person_hostile") == "a-h-G-U-C-I"


# ---------------------------------------------------------------------------
# cot_type_for_target (alliance swap)
# ---------------------------------------------------------------------------

class TestCotTypeForTarget:
    """Test alliance-swapped CoT code generation."""

    def test_friendly_rover(self):
        from engine.units import cot_type_for_target
        result = cot_type_for_target("rover", "friendly")
        assert result == "a-f-G-E-V-A-L"

    def test_hostile_rover(self):
        from engine.units import cot_type_for_target
        result = cot_type_for_target("rover", "hostile")
        assert result == "a-h-G-E-V-A-L"

    def test_neutral_rover(self):
        from engine.units import cot_type_for_target
        result = cot_type_for_target("rover", "neutral")
        assert result == "a-n-G-E-V-A-L"

    def test_unknown_rover(self):
        from engine.units import cot_type_for_target
        result = cot_type_for_target("rover", "unknown")
        assert result == "a-u-G-E-V-A-L"

    def test_hostile_person(self):
        from engine.units import cot_type_for_target
        result = cot_type_for_target("person", "hostile")
        assert result is not None
        assert result[2] == "h"

    def test_friendly_person(self):
        from engine.units import cot_type_for_target
        result = cot_type_for_target("person", "friendly")
        assert result is not None
        assert result[2] == "f"

    def test_drone_hostile(self):
        from engine.units import cot_type_for_target
        result = cot_type_for_target("drone", "hostile")
        assert result == "a-h-A-M-F-Q"

    def test_unknown_type_returns_none(self):
        from engine.units import cot_type_for_target
        assert cot_type_for_target("submarine", "friendly") is None

    def test_suffix_preserved(self):
        """Alliance swap only changes position 2, suffix stays intact."""
        from engine.units import cot_type_for_target
        friendly = cot_type_for_target("tank", "friendly")
        hostile = cot_type_for_target("tank", "hostile")
        assert friendly[3:] == hostile[3:]
        assert friendly[2] == "f"
        assert hostile[2] == "h"

    def test_all_types_resolve(self):
        """Every registered type should resolve for every alliance."""
        from engine.units import all_types, cot_type_for_target
        for cls in all_types():
            for alliance in ("friendly", "hostile", "neutral", "unknown"):
                result = cot_type_for_target(cls.type_id, alliance)
                assert result is not None, (
                    f"{cls.type_id}/{alliance} returned None"
                )
                expected_affil = {"friendly": "f", "hostile": "h",
                                  "neutral": "n", "unknown": "u"}[alliance]
                assert result[2] == expected_affil, (
                    f"{cls.type_id}/{alliance}: got affil {result[2]!r}"
                )


# ---------------------------------------------------------------------------
# Reverse lookup (CoT code -> TRITIUM type_id)
# ---------------------------------------------------------------------------

class TestReverseLookup:
    """Test that CoT codes resolve back to TRITIUM type_ids."""

    def test_new_rover_code(self):
        from engine.comms.cot import _get_reverse_type
        rev = _get_reverse_type()
        for prefix, tid in rev:
            if "a-f-G-E-V-A-L".startswith(prefix):
                assert tid == "rover"
                return
        pytest.fail("No reverse match for a-f-G-E-V-A-L")

    def test_old_rover_code_still_works(self):
        """Legacy ATAK code a-f-G-E-V should still resolve."""
        from engine.comms.cot import _get_reverse_type
        rev = _get_reverse_type()
        for prefix, tid in rev:
            if "a-f-G-E-V".startswith(prefix):
                assert tid in ("rover", "vehicle")
                return
        pytest.fail("No reverse match for a-f-G-E-V")

    def test_new_drone_code(self):
        from engine.comms.cot import _get_reverse_type
        rev = _get_reverse_type()
        for prefix, tid in rev:
            if "a-f-A-M-F-Q".startswith(prefix):
                assert tid == "drone"
                return
        pytest.fail("No reverse match for a-f-A-M-F-Q")

    def test_old_drone_code_still_works(self):
        from engine.comms.cot import _get_reverse_type
        rev = _get_reverse_type()
        for prefix, tid in rev:
            if "a-f-A-M-H".startswith(prefix):
                assert tid == "drone"
                return
        pytest.fail("No reverse match for a-f-A-M-H")

    def test_hostile_infantry(self):
        from engine.comms.cot import _get_reverse_type
        rev = _get_reverse_type()
        for prefix, tid in rev:
            if "a-h-G-U-C-I".startswith(prefix):
                assert tid in ("hostile_person", "hostile_leader")
                return
        pytest.fail("No reverse match for a-h-G-U-C-I")

    def test_longest_prefix_wins(self):
        """Longer specific codes should match before short generic ones."""
        from engine.comms.cot import _get_reverse_type
        rev = _get_reverse_type()
        # heavy_turret (a-f-G-E-W-D-H) should match before turret (a-f-G-E-W-D)
        for prefix, tid in rev:
            if "a-f-G-E-W-D-H".startswith(prefix):
                assert tid == "heavy_turret"
                return
        pytest.fail("No reverse match for a-f-G-E-W-D-H")

    def test_turret_matches_before_generic(self):
        from engine.comms.cot import _get_reverse_type
        rev = _get_reverse_type()
        for prefix, tid in rev:
            if "a-f-G-E-W-D".startswith(prefix):
                assert tid == "turret"
                return
        pytest.fail("No reverse match for a-f-G-E-W-D")

    def test_cot_xml_to_target_uses_registry(self):
        """End-to-end: CoT XML with new code resolves correctly."""
        from engine.comms.cot import cot_xml_to_target
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        xml = f"""<event version="2.0" uid="test-1" type="a-f-G-E-V-A-T"
                   how="m-s" time="{now}" start="{now}" stale="{now}">
          <point lat="37.7749" lon="-122.4194" hae="16.0" ce="10" le="10"/>
          <detail><contact callsign="Tank-1"/></detail>
        </event>"""
        result = cot_xml_to_target(xml)
        assert result is not None
        assert result["asset_type"] == "tank"
        assert result["alliance"] == "friendly"
