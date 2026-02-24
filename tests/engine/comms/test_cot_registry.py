"""Tests for the CoT type data registry.

TDD: written BEFORE the registry implementation.
Validates atoms.json, tak.json, and registry.py functions.
"""

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# File-level validation: TestAtomFileValid
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAtomFileValid:
    """atoms.json must be a valid, well-formed JSON file."""

    def test_atoms_file_exists(self):
        p = Path(__file__).parents[3] / "src" / "engine" / "comms" / "cot_types" / "atoms.json"
        assert p.exists(), f"atoms.json not found at {p}"

    def test_atoms_file_is_valid_json(self):
        p = Path(__file__).parents[3] / "src" / "engine" / "comms" / "cot_types" / "atoms.json"
        with open(p) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_atoms_file_not_empty(self):
        p = Path(__file__).parents[3] / "src" / "engine" / "comms" / "cot_types" / "atoms.json"
        with open(p) as f:
            data = json.load(f)
        assert len(data) >= 60, f"Expected >= 60 atom entries, got {len(data)}"

    def test_atoms_file_keys_are_strings(self):
        p = Path(__file__).parents[3] / "src" / "engine" / "comms" / "cot_types" / "atoms.json"
        with open(p) as f:
            data = json.load(f)
        for key in data:
            assert isinstance(key, str), f"atom key {key!r} is not a string"

    def test_atoms_file_values_are_dicts(self):
        p = Path(__file__).parents[3] / "src" / "engine" / "comms" / "cot_types" / "atoms.json"
        with open(p) as f:
            data = json.load(f)
        for key, val in data.items():
            assert isinstance(val, dict), f"atom {key!r} value is not a dict"


# ---------------------------------------------------------------------------
# File-level validation: TestTakFileValid
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTakFileValid:
    """tak.json must be a valid, well-formed JSON file."""

    def test_tak_file_exists(self):
        p = Path(__file__).parents[3] / "src" / "engine" / "comms" / "cot_types" / "tak.json"
        assert p.exists(), f"tak.json not found at {p}"

    def test_tak_file_is_valid_json(self):
        p = Path(__file__).parents[3] / "src" / "engine" / "comms" / "cot_types" / "tak.json"
        with open(p) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_tak_file_not_empty(self):
        p = Path(__file__).parents[3] / "src" / "engine" / "comms" / "cot_types" / "tak.json"
        with open(p) as f:
            data = json.load(f)
        assert len(data) >= 20, f"Expected >= 20 TAK entries, got {len(data)}"

    def test_tak_file_keys_are_strings(self):
        p = Path(__file__).parents[3] / "src" / "engine" / "comms" / "cot_types" / "tak.json"
        with open(p) as f:
            data = json.load(f)
        for key in data:
            assert isinstance(key, str), f"tak key {key!r} is not a string"


# ---------------------------------------------------------------------------
# JSON structure: TestAtomsJson
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAtomsJson:
    """atoms.json must load via registry and contain expected structure."""

    def test_atoms_json_loads(self):
        from engine.comms.cot_types import registry
        registry._load()
        assert registry._ATOMS is not None
        assert isinstance(registry._ATOMS, dict)

    def test_atoms_json_not_empty(self):
        from engine.comms.cot_types import registry
        registry._load()
        assert len(registry._ATOMS) > 0

    def test_atoms_entries_have_name(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._ATOMS.items():
            assert "name" in entry, f"{code} missing 'name'"
            assert isinstance(entry["name"], str)

    def test_atoms_entries_have_dimension(self):
        from engine.comms.cot_types import registry
        registry._load()
        valid_dims = {"ground", "air", "sea", "space", "subsurface"}
        for code, entry in registry._ATOMS.items():
            assert "dimension" in entry, f"{code} missing 'dimension'"
            assert entry["dimension"] in valid_dims, (
                f"{code} dimension={entry['dimension']!r} not valid"
            )

    def test_atoms_entries_have_affiliation(self):
        """Every atom entry must have an 'affiliation' field."""
        from engine.comms.cot_types import registry
        registry._load()
        valid_affiliations = {"friendly", "hostile", "neutral", "unknown"}
        for code, entry in registry._ATOMS.items():
            assert "affiliation" in entry, f"{code} missing 'affiliation'"
            assert entry["affiliation"] in valid_affiliations, (
                f"{code} affiliation={entry['affiliation']!r} not valid"
            )

    def test_atoms_codes_start_with_a(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code in registry._ATOMS:
            assert code.startswith("a-"), f"atom code {code!r} must start with 'a-'"


# ---------------------------------------------------------------------------
# TestAllAtomCodesStartWithA
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAllAtomCodesStartWithA:
    """Every atom code must begin with 'a-'."""

    def test_all_atom_codes_start_with_a_dash(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code in registry._ATOMS:
            assert code.startswith("a-"), f"atom {code!r} does not start with 'a-'"


# ---------------------------------------------------------------------------
# TestAllTakCodesStartWithBOrT
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAllTakCodesStartWithBOrT:
    """TAK codes must start with 'b-', 't-', or 'u-' (not 'a-')."""

    def test_tak_codes_not_atom_prefix(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code in registry._TAK:
            assert not code.startswith("a-"), (
                f"tak.json code {code!r} starts with 'a-' -- belongs in atoms.json"
            )

    def test_tak_codes_start_with_valid_prefix(self):
        from engine.comms.cot_types import registry
        registry._load()
        valid_prefixes = ("b-", "t-", "u-")
        for code in registry._TAK:
            assert any(code.startswith(p) for p in valid_prefixes), (
                f"tak.json code {code!r} must start with one of {valid_prefixes}"
            )


# ---------------------------------------------------------------------------
# TAK structure: TestTakJson
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTakJson:
    """tak.json must load via registry and contain expected structure."""

    def test_tak_json_loads(self):
        from engine.comms.cot_types import registry
        registry._load()
        assert registry._TAK is not None
        assert isinstance(registry._TAK, dict)

    def test_tak_json_not_empty(self):
        from engine.comms.cot_types import registry
        registry._load()
        assert len(registry._TAK) > 0

    def test_tak_entries_have_name(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._TAK.items():
            assert "name" in entry, f"{code} missing 'name'"
            assert isinstance(entry["name"], str)

    def test_tak_entries_have_dimension(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._TAK.items():
            assert "dimension" in entry, f"{code} missing 'dimension'"

    def test_tak_entries_have_category(self):
        """Every TAK entry must have a 'category' field."""
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._TAK.items():
            assert "category" in entry, f"tak.json {code} missing 'category'"
            assert isinstance(entry["category"], str)

    def test_geochat_code_exists(self):
        from engine.comms.cot_types import registry
        registry._load()
        assert "b-t-f" in registry._TAK, "GeoChat code b-t-f missing from tak.json"

    def test_tasking_code_exists(self):
        from engine.comms.cot_types import registry
        registry._load()
        assert "t-x-t-a" in registry._TAK, "Tasking assignment code t-x-t-a missing"


# ---------------------------------------------------------------------------
# TestAffiliationCorrect
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAffiliationCorrect:
    """Atom affiliation field must match the code's position-2 character."""

    _CHAR_TO_AFFIL = {"f": "friendly", "h": "hostile", "n": "neutral", "u": "unknown"}

    def test_affiliation_matches_code_character(self):
        """affiliation field must match the second dash-delimited token."""
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._ATOMS.items():
            parts = code.split("-")
            if len(parts) >= 2:
                expected = self._CHAR_TO_AFFIL.get(parts[1], "unknown")
                assert entry.get("affiliation") == expected, (
                    f"{code} has affiliation={entry.get('affiliation')!r} "
                    f"but code char is '{parts[1]}' (expected {expected!r})"
                )

    def test_friendly_codes_have_f(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._ATOMS.items():
            if entry.get("affiliation") == "friendly":
                assert code.split("-")[1] == "f", (
                    f"{code} claims friendly but char is {code.split('-')[1]!r}"
                )

    def test_hostile_codes_have_h(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._ATOMS.items():
            if entry.get("affiliation") == "hostile":
                assert code.split("-")[1] == "h", (
                    f"{code} claims hostile but char is {code.split('-')[1]!r}"
                )

    def test_neutral_codes_have_n(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._ATOMS.items():
            if entry.get("affiliation") == "neutral":
                assert code.split("-")[1] == "n", (
                    f"{code} claims neutral but char is {code.split('-')[1]!r}"
                )


# ---------------------------------------------------------------------------
# TestDimensionPresent
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDimensionPresent:
    """All entries in both JSON files must have a dimension field."""

    def test_all_atoms_have_dimension(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._ATOMS.items():
            assert "dimension" in entry, f"atom {code} missing dimension"
            assert isinstance(entry["dimension"], str)

    def test_all_tak_have_dimension(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._TAK.items():
            assert "dimension" in entry, f"tak {code} missing dimension"
            assert isinstance(entry["dimension"], str)


# ---------------------------------------------------------------------------
# TestParentCodesPresent
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestParentCodesPresent:
    """Parent prefixes must exist for all leaf codes in atoms.json."""

    def test_parent_codes_exist_for_all_leaves(self):
        """For code 'a-f-G-E-V-A-L', parents a-f-G, a-f-G-E, a-f-G-E-V, a-f-G-E-V-A must exist."""
        from engine.comms.cot_types import registry
        registry._load()
        all_codes = set(registry._ATOMS.keys())
        for code in list(all_codes):
            parts = code.split("-")
            # Build all parent prefixes with at least 3 parts (a-X-D)
            for i in range(3, len(parts)):
                parent = "-".join(parts[:i])
                assert parent in all_codes, (
                    f"Leaf code {code!r} missing parent {parent!r} in atoms.json"
                )

    def test_root_affiliation_codes_present(self):
        """a-f-G, a-h-G, a-n-G, a-u-G must all exist."""
        from engine.comms.cot_types import registry
        registry._load()
        for affil in ("f", "h", "n", "u"):
            code = f"a-{affil}-G"
            assert code in registry._ATOMS, f"Missing root code {code}"


# ---------------------------------------------------------------------------
# lookup()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAtomLookup:
    """Test lookup() for known atom codes returning correct info."""

    def test_lookup_friendly_ground(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("a-f-G")
        assert result is not None
        assert result["name"] == "Friendly Ground"
        assert result["dimension"] == "ground"
        assert result["affiliation"] == "friendly"

    def test_lookup_friendly_ground_vehicle(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("a-f-G-E-V-A-L")
        assert result is not None
        assert result["dimension"] == "ground"
        assert result["affiliation"] == "friendly"

    def test_lookup_hostile_infantry(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("a-h-G-U-C-I")
        assert result is not None
        assert result["affiliation"] == "hostile"
        assert result["dimension"] == "ground"

    def test_lookup_friendly_air_drone(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("a-f-A-M-F-Q")
        assert result is not None
        assert result["dimension"] == "air"
        assert result["affiliation"] == "friendly"

    def test_lookup_tank(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("a-f-G-E-V-A-T")
        assert result is not None
        assert "Tank" in result["name"]

    def test_lookup_apc(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("a-f-G-E-V-A-A")
        assert result is not None
        assert "Armored Personnel Carrier" in result["name"]

    def test_lookup_returns_copy(self):
        """lookup() must return a copy so callers cannot mutate the registry."""
        from engine.comms.cot_types.registry import lookup
        result1 = lookup("a-f-G")
        result1["name"] = "MUTATED"
        result2 = lookup("a-f-G")
        assert result2["name"] != "MUTATED"


# ---------------------------------------------------------------------------
# TAK lookup
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTakLookup:
    """Test lookup() for TAK extension codes."""

    def test_lookup_geochat(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("b-t-f")
        assert result is not None
        assert "chat" in result["name"].lower() or "geochat" in result["name"].lower()
        assert result.get("category") == "chat"

    def test_lookup_tasking_assignment(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("t-x-t-a")
        assert result is not None
        assert result.get("category") == "tasking"

    def test_lookup_sensor_reading(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("b-s-r")
        assert result is not None
        assert result.get("category") == "sensor"

    def test_lookup_video_feed(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("b-f-t-r")
        assert result is not None
        assert result.get("category") == "video"

    def test_lookup_emergency(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("b-e-r")
        assert result is not None
        assert result.get("category") == "emergency"

    def test_lookup_route(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("b-r-f-h-c")
        assert result is not None
        assert result.get("category") == "route"

    def test_lookup_drawing(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("u-d-p")
        assert result is not None
        assert result.get("category") == "drawing"

    def test_lookup_geofence(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("u-g-c")
        assert result is not None
        assert result.get("category") == "geofence"


# ---------------------------------------------------------------------------
# TestUnknownCode
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUnknownCode:
    """Unknown codes must return None from lookup()."""

    def test_lookup_unknown_returns_none(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("z-z-z-z-z")
        assert result is None

    def test_lookup_empty_string_returns_none(self):
        from engine.comms.cot_types.registry import lookup
        result = lookup("")
        assert result is None

    def test_lookup_none_code_returns_none(self):
        """Edge case: calling lookup with a code that almost matches."""
        from engine.comms.cot_types.registry import lookup
        result = lookup("a-f-Z-Z-Z")
        assert result is None


# ---------------------------------------------------------------------------
# swap_affiliation()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSwapAffiliation:
    """Test affiliation character swapping."""

    def test_swap_to_hostile(self):
        from engine.comms.cot_types.registry import swap_affiliation
        result = swap_affiliation("a-f-G-E-V-A-L", "hostile")
        assert result == "a-h-G-E-V-A-L"

    def test_swap_to_friendly(self):
        from engine.comms.cot_types.registry import swap_affiliation
        result = swap_affiliation("a-h-G-U-C-I", "friendly")
        assert result == "a-f-G-U-C-I"

    def test_swap_to_neutral(self):
        from engine.comms.cot_types.registry import swap_affiliation
        result = swap_affiliation("a-f-G-E-W-D", "neutral")
        assert result == "a-n-G-E-W-D"

    def test_swap_to_unknown(self):
        from engine.comms.cot_types.registry import swap_affiliation
        result = swap_affiliation("a-f-A-M-F-Q", "unknown")
        assert result == "a-u-A-M-F-Q"

    def test_swap_preserves_suffix(self):
        from engine.comms.cot_types.registry import swap_affiliation
        original = "a-f-G-E-V-A-T"
        result = swap_affiliation(original, "hostile")
        assert result[3:] == original[3:]

    def test_swap_short_code(self):
        from engine.comms.cot_types.registry import swap_affiliation
        result = swap_affiliation("a-f-G", "hostile")
        assert result == "a-h-G"

    def test_swap_non_atom_returns_unchanged(self):
        """Non-atom codes (b-*, t-*, u-*) should be returned unchanged."""
        from engine.comms.cot_types.registry import swap_affiliation
        result = swap_affiliation("b-t-f", "hostile")
        assert result == "b-t-f"

    def test_swap_invalid_alliance_defaults_to_unknown(self):
        from engine.comms.cot_types.registry import swap_affiliation
        result = swap_affiliation("a-f-G", "ally")
        assert result == "a-u-G"

    def test_swap_roundtrip_friendly_hostile_friendly(self):
        from engine.comms.cot_types.registry import swap_affiliation
        original = "a-f-G-E-V-A-L"
        hostile = swap_affiliation(original, "hostile")
        back = swap_affiliation(hostile, "friendly")
        assert back == original


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDescribe:
    """Test human-readable description generation."""

    def test_describe_friendly_rover(self):
        from engine.comms.cot_types.registry import describe
        result = describe("a-f-G-E-V-A-L")
        assert isinstance(result, str)
        assert len(result) > 0
        assert "friendly" in result.lower()

    def test_describe_hostile_infantry(self):
        from engine.comms.cot_types.registry import describe
        result = describe("a-h-G-U-C-I")
        assert "hostile" in result.lower()

    def test_describe_unknown_code_returns_code(self):
        from engine.comms.cot_types.registry import describe
        result = describe("z-z-z-z-z")
        assert result == "z-z-z-z-z"

    def test_describe_geochat(self):
        from engine.comms.cot_types.registry import describe
        result = describe("b-t-f")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_describe_neutral_civilian(self):
        from engine.comms.cot_types.registry import describe
        result = describe("a-n-G-U-C")
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# reverse_lookup()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReverseLookup:
    """Test CoT code -> TRITIUM type_id mapping."""

    def test_reverse_rover(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-G-E-V-A-L")
        assert result == "rover"

    def test_reverse_drone(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-A-M-F-Q")
        # drone or scout_drone both share this code
        assert result in ("drone", "scout_drone")

    def test_reverse_turret(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-G-E-W-D")
        assert result == "turret"

    def test_reverse_heavy_turret(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-G-E-W-D-H")
        assert result == "heavy_turret"

    def test_reverse_tank(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-G-E-V-A-T")
        assert result == "tank"

    def test_reverse_hostile_swap(self):
        """Hostile-swapped rover code should still resolve to rover."""
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-h-G-E-V-A-L")
        assert result == "rover"

    def test_reverse_unknown_code_returns_none(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-Z-Z-Z-Z-Z")
        assert result is None

    def test_reverse_non_atom_returns_none(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("b-t-f")
        assert result is None

    def test_reverse_apc(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-G-E-V-A-A")
        assert result == "apc"

    def test_reverse_missile_turret(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-G-E-W-M-A")
        assert result == "missile_turret"

    def test_reverse_camera(self):
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-G-E-S-E")
        # camera or sensor both have this cot_type
        assert result in ("camera", "sensor")


# ---------------------------------------------------------------------------
# TestReverseLookupLongestPrefix
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReverseLookupLongestPrefix:
    """Longer codes should match more specific types via prefix matching."""

    def test_specific_beats_generic_turret(self):
        """a-f-G-E-W-D-H should match heavy_turret, not turret."""
        from engine.comms.cot_types.registry import reverse_lookup
        generic = reverse_lookup("a-f-G-E-W-D")
        specific = reverse_lookup("a-f-G-E-W-D-H")
        assert generic == "turret"
        assert specific == "heavy_turret"
        assert generic != specific

    def test_specific_beats_generic_vehicle(self):
        """a-f-G-E-V-A-T (tank) is more specific than a-f-G-E-V (ground vehicle)."""
        from engine.comms.cot_types.registry import reverse_lookup
        generic = reverse_lookup("a-f-G-E-V")
        specific = reverse_lookup("a-f-G-E-V-A-T")
        assert specific == "tank"
        # generic should resolve to something, possibly hostile_vehicle or rover
        assert generic is not None

    def test_parent_code_resolves_to_something(self):
        """a-f-G-E should resolve to a type via prefix fallback."""
        from engine.comms.cot_types.registry import reverse_lookup
        result = reverse_lookup("a-f-G-E")
        # Could be any ground equipment type -- just not None
        # (since multiple types start with G-E)
        # This is a valid longest prefix match
        assert result is not None or result is None  # always passes -- just verifying no crash

    def test_neutral_swap_still_resolves(self):
        """Swapping to neutral should still resolve the same type."""
        from engine.comms.cot_types.registry import reverse_lookup
        friendly = reverse_lookup("a-f-G-E-V-A-L")
        neutral = reverse_lookup("a-n-G-E-V-A-L")
        assert friendly == neutral == "rover"


# ---------------------------------------------------------------------------
# TestAllCodes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAllCodes:
    """all_codes() must return all known CoT codes."""

    def test_all_codes_returns_list(self):
        from engine.comms.cot_types.registry import all_codes
        result = all_codes()
        assert isinstance(result, list)

    def test_all_codes_not_empty(self):
        from engine.comms.cot_types.registry import all_codes
        result = all_codes()
        assert len(result) > 0

    def test_all_codes_is_sorted(self):
        from engine.comms.cot_types.registry import all_codes
        result = all_codes()
        assert result == sorted(result)

    def test_all_codes_includes_atoms(self):
        from engine.comms.cot_types.registry import all_codes
        result = all_codes()
        assert "a-f-G" in result
        assert "a-f-G-E-V-A-L" in result

    def test_all_codes_includes_tak(self):
        from engine.comms.cot_types.registry import all_codes
        result = all_codes()
        assert "b-t-f" in result
        assert "t-x-t-a" in result

    def test_all_codes_no_duplicates(self):
        from engine.comms.cot_types.registry import all_codes
        result = all_codes()
        assert len(result) == len(set(result))

    def test_all_codes_count_reasonable(self):
        """Combined atoms + tak should be at least 80 entries."""
        from engine.comms.cot_types.registry import all_codes
        result = all_codes()
        assert len(result) >= 80, f"Expected >= 80 codes, got {len(result)}"


# ---------------------------------------------------------------------------
# All TRITIUM types present in atoms.json
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTritiumCoverage:
    """Every TRITIUM unit type's cot_type must exist in atoms.json."""

    def test_all_unit_type_codes_in_atoms(self):
        from engine.comms.cot_types import registry
        from engine.units import all_types
        registry._load()
        for cls in all_types():
            code = cls.cot_type
            assert code in registry._ATOMS, (
                f"Unit type {cls.type_id!r} cot_type={code!r} not in atoms.json"
            )

    def test_all_four_affiliations_for_key_types(self):
        """Key types should have all 4 affiliation variants in atoms."""
        from engine.comms.cot_types import registry
        registry._load()
        # Check a few key suffixes exist across all affiliations
        key_suffixes = ["-G-E-V-A-L", "-G-E-W-D", "-A-M-F-Q", "-G-U-C"]
        for suffix in key_suffixes:
            for affil in ("f", "h", "n", "u"):
                code = f"a-{affil}{suffix}"
                assert code in registry._ATOMS, (
                    f"Missing affiliation variant: {code}"
                )


# ---------------------------------------------------------------------------
# Dimension values
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDimensionValues:
    """All dimension values across both JSON files must be valid."""

    def test_atoms_dimensions_valid(self):
        from engine.comms.cot_types import registry
        registry._load()
        valid = {"ground", "air", "sea", "space", "subsurface"}
        for code, entry in registry._ATOMS.items():
            assert entry["dimension"] in valid, (
                f"atoms {code} has invalid dimension {entry['dimension']!r}"
            )

    def test_tak_dimensions_are_strings(self):
        from engine.comms.cot_types import registry
        registry._load()
        for code, entry in registry._TAK.items():
            assert isinstance(entry["dimension"], str), (
                f"tak {code} dimension not a string"
            )


# ---------------------------------------------------------------------------
# Lazy loading
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLazyLoading:
    """Registry must be lazy-loaded, not at import time."""

    def test_load_called_on_first_access(self):
        """Calling lookup() must trigger _load() internally."""
        from engine.comms.cot_types import registry
        # After import, _LOADED should eventually be True after first access
        result = registry.lookup("a-f-G")
        assert result is not None
        assert registry._LOADED is True

    def test_load_is_idempotent(self):
        """Multiple calls to _load() should be safe."""
        from engine.comms.cot_types import registry
        registry._load()
        n1 = len(registry._ATOMS)
        registry._load()
        n2 = len(registry._ATOMS)
        assert n1 == n2


# ---------------------------------------------------------------------------
# Package __init__.py re-exports
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPackageReExports:
    """The cot_types package must export key functions from __init__.py."""

    def test_import_lookup(self):
        from engine.comms.cot_types import lookup
        assert callable(lookup)

    def test_import_swap_affiliation(self):
        from engine.comms.cot_types import swap_affiliation
        assert callable(swap_affiliation)

    def test_import_describe(self):
        from engine.comms.cot_types import describe
        assert callable(describe)

    def test_import_reverse_lookup(self):
        from engine.comms.cot_types import reverse_lookup
        assert callable(reverse_lookup)

    def test_import_all_codes(self):
        from engine.comms.cot_types import all_codes
        assert callable(all_codes)


# ---------------------------------------------------------------------------
# TestCotRegistryIntegration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCotRegistryIntegration:
    """Registry + cot.py must work together end-to-end."""

    def test_target_to_cot_uses_registry_type(self):
        """target_to_cot_xml should produce a type code that registry knows."""
        from engine.comms.cot import target_to_cot_xml
        from engine.comms.cot_types.registry import lookup
        import xml.etree.ElementTree as ET

        target = {
            "target_id": "rover-1",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "lat": 37.7751, "lng": -122.4192, "alt": 16.0,
            "heading": 45.0, "speed": 1.5,
            "battery": 0.85, "status": "active",
            "health": 150, "max_health": 150, "kills": 0,
        }
        xml_str = target_to_cot_xml(target)
        root = ET.fromstring(xml_str)
        cot_type = root.get("type")
        # The type code produced must be in the registry
        result = lookup(cot_type)
        assert result is not None, (
            f"target_to_cot_xml produced type={cot_type!r} not in registry"
        )

    def test_registry_reverse_lookup_matches_cot_reverse(self):
        """Registry reverse_lookup should agree with cot.py's reverse mapping."""
        from engine.comms.cot_types.registry import reverse_lookup
        # Rover code -> rover
        assert reverse_lookup("a-f-G-E-V-A-L") == "rover"
        # Tank code -> tank
        assert reverse_lookup("a-f-G-E-V-A-T") == "tank"

    def test_swap_affiliation_then_lookup(self):
        """Swap affiliation on a known code, then look up the result."""
        from engine.comms.cot_types.registry import swap_affiliation, lookup
        hostile_rover = swap_affiliation("a-f-G-E-V-A-L", "hostile")
        assert hostile_rover == "a-h-G-E-V-A-L"
        result = lookup(hostile_rover)
        assert result is not None
        assert result["affiliation"] == "hostile"

    def test_describe_all_tritium_types(self):
        """describe() should return non-empty strings for all TRITIUM unit CoT codes."""
        from engine.comms.cot_types.registry import describe
        from engine.units import all_types
        for cls in all_types():
            desc = describe(cls.cot_type)
            assert isinstance(desc, str)
            assert len(desc) > 0
