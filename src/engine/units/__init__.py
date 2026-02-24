"""Unit type registry with auto-discovery.

Import this package to access the full registry::

    from engine.units import get_type, all_types, mobile_type_ids

    rover_cls = get_type("rover")   # -> Rover class
    print(rover_cls.speed)          # 2.0
    print(len(all_types()))         # 19

The registry is populated at import time by walking every submodule
under ``amy.units`` and collecting concrete ``UnitType`` subclasses.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Optional

from engine.units.base import CombatStats, MovementCategory, UnitType

__all__ = [
    "UnitType",
    "CombatStats",
    "MovementCategory",
    "get_type",
    "all_types",
    "mobile_type_ids",
    "static_type_ids",
    "flying_type_ids",
    "ground_type_ids",
    "foot_type_ids",
    "dispatchable_type_ids",
    "get_cot_type",
    "cot_type_for_target",
]

# ---------------------------------------------------------------------------
# Internal registry
# ---------------------------------------------------------------------------
_registry: dict[str, type[UnitType]] = {}

# Aliases: legacy engine uses "person_hostile" / "person_neutral" strings.
_ALIASES: dict[str, str] = {
    "person_hostile": "hostile_person",
    "person_neutral": "person",
}


def _discover() -> None:
    """Walk all subpackages and register concrete UnitType subclasses."""
    package = importlib.import_module("engine.units")
    _walk(package.__path__, package.__name__)


def _walk(path: list[str], prefix: str) -> None:
    for importer, modname, ispkg in pkgutil.walk_packages(path, prefix + "."):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, UnitType)
                and obj is not UnitType
                and hasattr(obj, "type_id")
            ):
                _registry[obj.type_id] = obj


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_type(type_id: str) -> Optional[type[UnitType]]:
    """Return the UnitType class for *type_id*, or ``None``."""
    resolved = _ALIASES.get(type_id, type_id)
    return _registry.get(resolved)


def all_types() -> list[type[UnitType]]:
    """Return every registered UnitType class (stable order by type_id)."""
    return [_registry[k] for k in sorted(_registry)]


def mobile_type_ids() -> set[str]:
    """type_ids where ``is_mobile()`` is True."""
    return {tid for tid, cls in _registry.items() if cls.is_mobile()}


def static_type_ids() -> set[str]:
    """type_ids where ``is_mobile()`` is False."""
    return {tid for tid, cls in _registry.items() if not cls.is_mobile()}


def flying_type_ids() -> set[str]:
    """type_ids where category is AIR."""
    return {tid for tid, cls in _registry.items() if cls.is_flying()}


def ground_type_ids() -> set[str]:
    """type_ids where category is GROUND."""
    return {tid for tid, cls in _registry.items() if cls.is_ground()}


def foot_type_ids() -> set[str]:
    """type_ids where category is FOOT."""
    return {tid for tid, cls in _registry.items() if cls.is_foot()}


def get_cot_type(type_id: str) -> Optional[str]:
    """Return the CoT type code for *type_id*, or ``None``."""
    cls = get_type(type_id)
    if cls is not None:
        return cls.cot_type
    return None


def cot_type_for_target(type_id: str, alliance: str) -> Optional[str]:
    """Return alliance-swapped CoT code for a target.

    When a more specific variant exists (e.g. person+hostile -> hostile_person),
    its code is used directly.  Otherwise swaps the affiliation character at
    position 2: ``f`` = friendly, ``h`` = hostile, ``n`` = neutral, ``u`` = unknown.
    """
    # Check for specific alliance variants first
    _VARIANTS: dict[tuple[str, str], str] = {
        ("person", "hostile"): "hostile_person",
        ("vehicle", "hostile"): "hostile_vehicle",
    }
    variant_id = _VARIANTS.get((type_id, alliance))
    if variant_id is not None:
        code = get_cot_type(variant_id)
        if code is not None:
            return code
    # Standard lookup + affiliation swap
    code = get_cot_type(type_id)
    if code is None or len(code) < 3:
        return None
    _AFFIL = {"friendly": "f", "hostile": "h", "neutral": "n", "unknown": "u"}
    affil = _AFFIL.get(alliance, "u")
    return f"a-{affil}{code[3:]}"


def dispatchable_type_ids() -> set[str]:
    """type_ids that are mobile AND placeable (operator-controlled assets).

    These are the types that AutoDispatcher can send to intercept threats.
    Excludes people, animals, and hostile types.
    """
    return {
        tid for tid, cls in _registry.items()
        if cls.is_mobile() and cls.placeable
    }


# ---------------------------------------------------------------------------
# Auto-discover on import
# ---------------------------------------------------------------------------
_discover()
