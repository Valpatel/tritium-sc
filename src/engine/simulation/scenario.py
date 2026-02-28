# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BattleScenario — data model for city-scale combat scenarios.

This is SEPARATE from ``engine.scenarios.schema.Scenario`` which defines
Amy's behavioral testing scenarios.  BattleScenario is purely about combat
simulation: wave definitions with mixed hostile types, pre-placed defenders,
and map bounds.

Usage:
    scenario = load_battle_scenario("scenarios/battle/street_combat.json")
    engine.game_mode.load_scenario(scenario)
    engine.game_mode.begin_war()
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpawnGroup:
    """A group of same-type hostiles within a wave."""

    asset_type: str  # "person", "hostile_vehicle", "hostile_leader"
    count: int
    speed: float = 1.5
    health: float = 80.0


@dataclass
class WaveDefinition:
    """Defines a single wave: one or more spawn groups + multipliers."""

    name: str
    groups: list[SpawnGroup]
    speed_mult: float = 1.0
    health_mult: float = 1.0
    briefing: str | None = None
    threat_level: str | None = None
    intel: str | None = None

    @property
    def total_count(self) -> int:
        return sum(g.count for g in self.groups)


@dataclass
class DefenderConfig:
    """A pre-placed friendly defender."""

    asset_type: str  # "turret", "rover", "drone", etc.
    position: tuple[float, float]
    name: str | None = None


@dataclass
class BattleScenario:
    """Complete battle scenario definition."""

    scenario_id: str
    name: str
    description: str
    map_bounds: float
    waves: list[WaveDefinition]
    defenders: list[DefenderConfig] = field(default_factory=list)
    max_hostiles: int = 200
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "map_bounds": self.map_bounds,
            "max_hostiles": self.max_hostiles,
            "tags": self.tags,
            "waves": [
                {
                    "name": w.name,
                    "groups": [
                        {
                            "asset_type": g.asset_type,
                            "count": g.count,
                            "speed": g.speed,
                            "health": g.health,
                        }
                        for g in w.groups
                    ],
                    "speed_mult": w.speed_mult,
                    "health_mult": w.health_mult,
                    **({"briefing": w.briefing} if w.briefing else {}),
                    **({"threat_level": w.threat_level} if w.threat_level else {}),
                    **({"intel": w.intel} if w.intel else {}),
                }
                for w in self.waves
            ],
            "defenders": [
                {
                    "asset_type": d.asset_type,
                    "position": list(d.position),
                    "name": d.name,
                }
                for d in self.defenders
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BattleScenario:
        waves = []
        for w in data["waves"]:
            groups = [
                SpawnGroup(
                    asset_type=g["asset_type"],
                    count=g["count"],
                    speed=g.get("speed", 1.5),
                    health=g.get("health", 80.0),
                )
                for g in w["groups"]
            ]
            waves.append(WaveDefinition(
                name=w["name"],
                groups=groups,
                speed_mult=w.get("speed_mult", 1.0),
                health_mult=w.get("health_mult", 1.0),
                briefing=w.get("briefing"),
                threat_level=w.get("threat_level"),
                intel=w.get("intel"),
            ))

        defenders = []
        for d in data.get("defenders", []):
            pos = d["position"]
            defenders.append(DefenderConfig(
                asset_type=d["asset_type"],
                position=(float(pos[0]), float(pos[1])),
                name=d.get("name"),
            ))

        return cls(
            scenario_id=data["scenario_id"],
            name=data["name"],
            description=data.get("description", ""),
            map_bounds=data.get("map_bounds", 200.0),
            waves=waves,
            defenders=defenders,
            max_hostiles=data.get("max_hostiles", 200),
            tags=data.get("tags", []),
        )


def load_battle_scenario(path: str) -> BattleScenario:
    """Load a BattleScenario from a JSON file.

    Raises:
        FileNotFoundError: If path does not exist.
        json.JSONDecodeError: If file is not valid JSON.
        KeyError/TypeError: If required fields are missing.
    """
    with open(path) as f:
        data = json.load(f)
    return BattleScenario.from_dict(data)
