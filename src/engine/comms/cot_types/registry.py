# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CoT type data registry.

Loads curated MIL-STD-2525 atom types and TAK extension types from JSON,
provides lookup, affiliation swap, description, and reverse-lookup to
TRITIUM unit type IDs.

Data is lazy-loaded on first access to avoid slowing down import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).parent

# Lazy-loaded data stores
_ATOMS: dict[str, dict] = {}
_TAK: dict[str, dict] = {}
_LOADED = False

# Affiliation labels
_AFFIL_LABELS: dict[str, str] = {
    "f": "Friendly",
    "h": "Hostile",
    "n": "Neutral",
    "u": "Unknown",
}

_ALLIANCE_TO_CHAR: dict[str, str] = {
    "friendly": "f",
    "hostile": "h",
    "neutral": "n",
    "unknown": "u",
}


def _load() -> None:
    """Load JSON data files on first access."""
    global _ATOMS, _TAK, _LOADED
    if _LOADED:
        return
    with open(_DIR / "atoms.json") as f:
        _ATOMS = json.load(f)
    with open(_DIR / "tak.json") as f:
        _TAK = json.load(f)
    _LOADED = True


def lookup(cot_code: str) -> dict | None:
    """Return name, dimension, etc. for a CoT code, or None.

    Returns a copy so callers cannot mutate the registry.
    """
    _load()
    if not cot_code:
        return None
    entry = _ATOMS.get(cot_code) or _TAK.get(cot_code)
    if entry is not None:
        return dict(entry)
    return None


def swap_affiliation(cot_code: str, alliance: str) -> str:
    """Change the affiliation char (position 2) to match alliance.

    Only applies to atom codes (starting with 'a-').  Non-atom codes
    are returned unchanged.
    """
    if not cot_code.startswith("a-") or len(cot_code) < 3:
        return cot_code
    affil = _ALLIANCE_TO_CHAR.get(alliance, "u")
    return f"a-{affil}{cot_code[3:]}"


def describe(cot_code: str) -> str:
    """Human-readable description.

    For atom codes, builds from affiliation + name.
    For TAK codes, returns the name directly.
    For unknown codes, returns the code itself.
    """
    _load()
    entry = _ATOMS.get(cot_code) or _TAK.get(cot_code)
    if entry is None:
        return cot_code

    name = entry["name"]

    # For atom codes, prepend affiliation if not already in the name
    if cot_code.startswith("a-") and len(cot_code) >= 3:
        affil_char = cot_code[2]
        affil_label = _AFFIL_LABELS.get(affil_char, "")
        if affil_label and affil_label.lower() not in name.lower():
            return f"{affil_label} {name}"

    return name


def reverse_lookup(cot_code: str) -> Optional[str]:
    """CoT code -> TRITIUM type_id via unit type registry.

    Tries exact cot_type match first, then longest prefix match.
    Only works for atom codes (a-*).  Returns None for non-atom codes
    or codes with no matching TRITIUM type.
    """
    if not cot_code.startswith("a-"):
        return None

    from engine.units import all_types

    # Normalize: strip affiliation to get a canonical suffix for matching
    suffix = cot_code[3:]  # everything after "a-X"

    # Build a map of suffix -> type_id (longest suffix wins)
    # Exact match first
    for cls in all_types():
        cls_suffix = cls.cot_type[3:]
        if cls_suffix == suffix:
            return cls.type_id

    # Longest prefix match: try progressively shorter suffixes of the input
    # by checking which type codes are prefixes of the input suffix
    best_match: Optional[str] = None
    best_len = 0
    for cls in all_types():
        cls_suffix = cls.cot_type[3:]
        if suffix.startswith(cls_suffix) and len(cls_suffix) > best_len:
            best_match = cls.type_id
            best_len = len(cls_suffix)

    return best_match


def all_codes() -> list[str]:
    """Return all known CoT type codes (atoms + TAK), sorted."""
    _load()
    return sorted(set(list(_ATOMS.keys()) + list(_TAK.keys())))
