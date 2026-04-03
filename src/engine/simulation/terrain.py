# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TerrainMap — re-export from tritium-lib with SC unit-registry integration.

The canonical implementation now lives in
``tritium_lib.sim_engine.world.terrain_map``.  This wrapper preserves the
original import paths and provides the SC-specific ``is_flying_checker``
that uses ``engine.units.get_type`` to determine whether a unit type is
flying.
"""

from tritium_lib.sim_engine.world.terrain_map import (  # noqa: F401
    TerrainCell,
    TerrainMap as _LibTerrainMap,
    _TERRAIN_PROPERTIES,
    _BUILDING_TYPES,
    _FLYING_TYPES,
    _bresenham,
    _point_in_polygon,
)

# SC-specific: bridge the unit registry flying check
try:
    from engine.units import get_type as _get_unit_type

    def _sc_is_flying_checker(asset_type: str) -> bool:
        """Check if a unit type is flying via the SC unit registry."""
        type_def = _get_unit_type(asset_type)
        if type_def is not None and type_def.is_flying():
            return True
        return False
except ImportError:
    _sc_is_flying_checker = None  # type: ignore[assignment]


class TerrainMap(_LibTerrainMap):
    """SC-flavored TerrainMap that auto-wires the unit registry flying check."""

    def __init__(self, map_bounds: float, resolution: float = 5.0) -> None:
        super().__init__(
            map_bounds=map_bounds,
            resolution=resolution,
            is_flying_checker=_sc_is_flying_checker,
        )


__all__ = [
    "TerrainCell",
    "TerrainMap",
]
