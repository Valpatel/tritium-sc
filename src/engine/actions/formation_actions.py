# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Lua formation actions for Amy's tactical command system.

Registers Lua actions that allow Amy (and operators) to issue tactical
formation orders to friendly units.  All actions are registered on the
LuaActionRegistry and executed against the SimulationEngine's SquadManager.

Actions:
  formation(type, id1, id2, ...)  -- group units into a squad formation
  set_formation(squad_id, type)   -- change formation for existing squad
  squad_order(squad_id, order)    -- issue tactical order to squad
  squad_dispatch(squad_id, x, y)  -- dispatch entire squad to position
  rally(x, y, alliance)           -- rally nearby units to a point
  scatter(squad_id)               -- scatter squad to reduce AOE vulnerability

Usage:
  from engine.actions.formation_actions import register_formation_actions
  register_formation_actions(registry, engine)
"""

from __future__ import annotations

import math
import random
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.actions.lua_registry import LuaActionRegistry
    from engine.simulation.engine import SimulationEngine

# Valid formation types
VALID_FORMATIONS = {"wedge", "line", "column", "circle"}

# Valid squad orders
VALID_ORDERS = {"advance", "hold", "flank_left", "flank_right", "retreat"}

# Rally radius in meters
RALLY_RADIUS = 30.0

# Minimum scatter distance from squad center
SCATTER_MIN_DISTANCE = 8.0
SCATTER_MAX_DISTANCE = 15.0

# Module-level handler registry: maps action name -> callable
_handlers: dict[str, Any] = {}


def _get_handler(name: str):
    """Get a registered handler by name (used by tests)."""
    return _handlers[name]


def register_formation_actions(
    registry: LuaActionRegistry,
    engine: SimulationEngine,
) -> None:
    """Register all formation-related Lua actions on the registry.

    Args:
        registry: The LuaActionRegistry to register actions on.
        engine: The SimulationEngine providing squad_manager and targets.
    """
    from engine.actions.lua_registry import ActionDef
    from engine.simulation.squads import Squad

    # -- formation(type, id1, id2, ...) --------------------------------

    def cmd_formation(formation_type: str, *unit_ids: str) -> dict:
        """Group units into a formation squad.

        Args:
            formation_type: One of "wedge", "line", "column", "circle".
            *unit_ids: Two or more target IDs to group.  First is the leader.

        Returns:
            dict with status and squad_id, or error.
        """
        if formation_type not in VALID_FORMATIONS:
            return {
                "status": "error",
                "error": f"Invalid formation '{formation_type}'. "
                         f"Valid: {', '.join(sorted(VALID_FORMATIONS))}",
            }

        if len(unit_ids) < 2:
            return {
                "status": "error",
                "error": "formation() requires at least 2 unit IDs",
            }

        # Validate all units exist
        targets = {}
        for uid in unit_ids:
            t = engine.get_target(uid)
            if t is None:
                return {
                    "status": "error",
                    "error": f"Unit '{uid}' not found in simulation",
                }
            targets[uid] = t

        # Create squad
        squad_id = f"squad-{uuid.uuid4().hex[:8]}"
        squad = Squad(
            squad_id=squad_id,
            member_ids=list(unit_ids),
            leader_id=unit_ids[0],
            formation=formation_type,
        )

        # Register in squad manager
        engine.squad_manager._squads[squad_id] = squad

        # Set squad_id on all targets
        for uid in unit_ids:
            targets[uid].squad_id = squad_id

        return {"status": "ok", "squad_id": squad_id}

    _handlers["formation"] = cmd_formation
    registry.register(ActionDef(
        name="formation",
        min_params=3,   # type + at least 2 unit IDs
        max_params=20,  # up to 20 units in a formation
        param_types=[str, str, str],
        description="Group units into a formation (wedge/line/column/circle)",
        source="amy",
    ))

    # -- set_formation(squad_id, type) ---------------------------------

    def cmd_set_formation(squad_id: str, formation_type: str) -> dict:
        """Change formation for an existing squad."""
        squad = engine.squad_manager.get_squad(squad_id)
        if squad is None:
            return {
                "status": "error",
                "error": f"Squad '{squad_id}' not found",
            }

        if formation_type not in VALID_FORMATIONS:
            return {
                "status": "error",
                "error": f"Invalid formation '{formation_type}'. "
                         f"Valid: {', '.join(sorted(VALID_FORMATIONS))}",
            }

        squad.formation = formation_type
        return {"status": "ok", "squad_id": squad_id, "formation": formation_type}

    _handlers["set_formation"] = cmd_set_formation
    registry.register(ActionDef(
        name="set_formation",
        min_params=2,
        max_params=2,
        param_types=[str, str],
        description="Change formation type for existing squad",
        source="amy",
    ))

    # -- squad_order(squad_id, order) ----------------------------------

    def cmd_squad_order(squad_id: str, order: str) -> dict:
        """Issue a tactical order to a squad."""
        squad = engine.squad_manager.get_squad(squad_id)
        if squad is None:
            return {
                "status": "error",
                "error": f"Squad '{squad_id}' not found",
            }

        if order not in VALID_ORDERS:
            return {
                "status": "error",
                "error": f"Invalid order '{order}'. "
                         f"Valid: {', '.join(sorted(VALID_ORDERS))}",
            }

        engine.squad_manager.issue_order(squad_id, order)
        return {"status": "ok", "squad_id": squad_id, "order": order}

    _handlers["squad_order"] = cmd_squad_order
    registry.register(ActionDef(
        name="squad_order",
        min_params=2,
        max_params=2,
        param_types=[str, str],
        description="Issue tactical order to squad (advance/hold/flank/retreat)",
        source="amy",
    ))

    # -- squad_dispatch(squad_id, x, y) --------------------------------

    def cmd_squad_dispatch(squad_id: str, x: float, y: float) -> dict:
        """Dispatch entire squad to a position, maintaining formation offsets."""
        squad = engine.squad_manager.get_squad(squad_id)
        if squad is None:
            return {
                "status": "error",
                "error": f"Squad '{squad_id}' not found",
            }

        offsets = squad.get_formation_offsets()
        center = (float(x), float(y))

        for mid in squad.member_ids:
            offset = offsets.get(mid, (0.0, 0.0))
            dest = (center[0] + offset[0], center[1] + offset[1])
            engine.dispatch_unit(mid, dest)

        return {
            "status": "ok",
            "squad_id": squad_id,
            "target": {"x": x, "y": y},
            "dispatched": len(squad.member_ids),
        }

    _handlers["squad_dispatch"] = cmd_squad_dispatch
    registry.register(ActionDef(
        name="squad_dispatch",
        min_params=3,
        max_params=3,
        param_types=[str, float, float],
        description="Dispatch entire squad to position with formation",
        source="amy",
    ))

    # -- rally(x, y, alliance) ----------------------------------------

    def cmd_rally(x: float, y: float, alliance: str = "friendly") -> dict:
        """Rally nearby units of the given alliance to a point.

        All units within RALLY_RADIUS (30m) of the point converge on it.
        """
        rally_point = (float(x), float(y))
        rallied = 0

        for t in engine.get_targets():
            if t.alliance != alliance:
                continue
            if t.status not in ("active", "idle", "stationary"):
                continue
            dx = t.position[0] - rally_point[0]
            dy = t.position[1] - rally_point[1]
            dist = math.hypot(dx, dy)
            if dist <= RALLY_RADIUS:
                engine.dispatch_unit(t.target_id, rally_point)
                rallied += 1

        return {
            "status": "ok",
            "rally_point": {"x": x, "y": y},
            "alliance": alliance,
            "rallied": rallied,
        }

    _handlers["rally"] = cmd_rally
    registry.register(ActionDef(
        name="rally",
        min_params=2,
        max_params=3,
        param_types=[float, float, str],
        description="Rally nearby units to a point (within 30m)",
        source="amy",
    ))

    # -- scatter(squad_id) ---------------------------------------------

    def cmd_scatter(squad_id: str) -> dict:
        """Scatter squad members to reduce AOE vulnerability.

        Each member is dispatched to a random point at least
        SCATTER_MIN_DISTANCE from the squad center.
        """
        squad = engine.squad_manager.get_squad(squad_id)
        if squad is None:
            return {
                "status": "error",
                "error": f"Squad '{squad_id}' not found",
            }

        # Compute squad center
        positions = []
        for mid in squad.member_ids:
            t = engine.get_target(mid)
            if t is not None:
                positions.append(t.position)

        if not positions:
            return {"status": "ok", "scattered": 0}

        cx = sum(p[0] for p in positions) / len(positions)
        cy = sum(p[1] for p in positions) / len(positions)

        scattered = 0
        for i, mid in enumerate(squad.member_ids):
            # Each member gets a unique direction away from center
            angle = (2.0 * math.pi * i) / max(len(squad.member_ids), 1)
            angle += random.uniform(-0.3, 0.3)  # jitter
            dist = random.uniform(SCATTER_MIN_DISTANCE, SCATTER_MAX_DISTANCE)
            dest = (cx + math.cos(angle) * dist, cy + math.sin(angle) * dist)
            engine.dispatch_unit(mid, dest)
            scattered += 1

        return {"status": "ok", "squad_id": squad_id, "scattered": scattered}

    _handlers["scatter"] = cmd_scatter
    registry.register(ActionDef(
        name="scatter",
        min_params=1,
        max_params=1,
        param_types=[str],
        description="Scatter squad members to reduce AOE vulnerability",
        source="amy",
    ))
