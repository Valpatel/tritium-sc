# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Simulation subsystem — battlespace engine, combat, game modes."""
from .ambient import AmbientSpawner
from .backstory import BackstoryGenerator
from tritium_lib.sim_engine.behavior.behaviors import UnitBehaviors
from tritium_lib.sim_engine.combat.combat import CombatSystem, Projectile
from .comms import Signal, UnitComms
from tritium_lib.sim_engine.world.cover import CoverObject, CoverSystem
from .degradation import DegradationSystem
from .difficulty import DifficultyScaler, WaveRecord
from .engine import SimulationEngine
from .fake_robot import FakeRobot, FakeRobotFleet
from .game_mode import GameMode, InfiniteWaveMode, WaveConfig, WAVE_CONFIGS
from .hazards import Hazard, HazardManager
from .intercept import lead_target, predict_intercept, target_velocity, time_to_intercept
from tritium_lib.sim_engine.core.inventory import InventoryItem, UnitInventory, ITEM_CATALOG, build_loadout, select_best_weapon
from .loader import load_layout, load_zones
from .lod import LODSystem, LODTier, ViewportState
from .morale import MoraleSystem
from .objectives import ObjectiveTracker
from tritium_lib.sim_engine.core.movement import MovementController, smooth_path
from tritium_lib.sim_engine.world.grid_pathfinder import MovementProfile, PROFILES, grid_find_path, profile_for_unit, smooth_path as grid_smooth_path
from tritium_lib.sim_engine.world.pathfinding import plan_path
from .pursuit import PursuitSystem
from .replay import ReplayRecorder
from .scenario import BattleScenario, DefenderConfig, SpawnGroup, WaveDefinition, load_battle_scenario, spread_defenders
from tritium_lib.sim_engine.world.sensors import SensorDevice, SensorSimulator
from tritium_lib.sim_engine.core.spatial import SpatialGrid
from .spectator import SpectatorMode
from tritium_lib.sim_engine.combat.squads import Squad, SquadManager
from tritium_lib.sim_engine.core.state_machine import State, StateMachine, Transition
from .stats import StatsTracker, UnitStats, WaveStats
from tritium_lib.sim_engine.core.entity import SimulationTarget
from .terrain import TerrainCell, TerrainMap
from tritium_lib.sim_engine.behavior.unit_states import create_turret_fsm, create_rover_fsm, create_drone_fsm, create_hostile_fsm, create_fsm_for_type
from .upgrades import Upgrade, Ability, ActiveEffect, UpgradeSystem
from .battle_integration import AutomationEngine, AutomationRule, BattleIntegration, default_combat_rules
from .combat_bridge import CombatBridge
from .poi_data import POI, MissionArea, fetch_pois, pick_mission_center, build_mission_area, get_poi_context_text, get_street_names, place_defenders_around_buildings, load_cached
from tritium_lib.sim_engine.world.vision import SightingReport, VisibilityState, VisionSystem
from tritium_lib.sim_engine.combat.weapons import Weapon, WeaponSystem

__all__ = [
    "AmbientSpawner",
    "BackstoryGenerator",
    "AutomationEngine",
    "AutomationRule",
    "BattleIntegration",
    "CombatBridge",
    "CombatSystem",
    "CoverObject",
    "CoverSystem",
    "DegradationSystem",
    "DifficultyScaler",
    "FakeRobot",
    "FakeRobotFleet",
    "GameMode",
    "Hazard",
    "HazardManager",
    "InfiniteWaveMode",
    "InventoryItem",
    "ITEM_CATALOG",
    "MoraleSystem",
    "ObjectiveTracker",
    "MovementController",
    "Projectile",
    "PursuitSystem",
    "ReplayRecorder",
    "SensorDevice",
    "SensorSimulator",
    "Signal",
    "BattleScenario",
    "DefenderConfig",
    "SpawnGroup",
    "WaveDefinition",
    "SimulationEngine",
    "SpatialGrid",
    "load_battle_scenario",
    "spread_defenders",
    "SimulationTarget",
    "SpectatorMode",
    "Squad",
    "SquadManager",
    "State",
    "StateMachine",
    "StatsTracker",
    "TerrainCell",
    "TerrainMap",
    "Transition",
    "UnitBehaviors",
    "UnitComms",
    "UnitInventory",
    "UnitStats",
    "Upgrade",
    "Ability",
    "ActiveEffect",
    "UpgradeSystem",
    "WaveConfig",
    "WaveRecord",
    "WaveStats",
    "WAVE_CONFIGS",
    "SightingReport",
    "VisibilityState",
    "VisionSystem",
    "Weapon",
    "WeaponSystem",
    "create_turret_fsm",
    "create_rover_fsm",
    "create_drone_fsm",
    "create_hostile_fsm",
    "create_fsm_for_type",
    "lead_target",
    "load_layout",
    "load_zones",
    "MovementProfile",
    "PROFILES",
    "grid_find_path",
    "grid_smooth_path",
    "plan_path",
    "profile_for_unit",
    "predict_intercept",
    "smooth_path",
    "target_velocity",
    "time_to_intercept",
    "POI",
    "MissionArea",
    "fetch_pois",
    "pick_mission_center",
    "build_mission_area",
    "get_poi_context_text",
    "get_street_names",
    "place_defenders_around_buildings",
    "load_cached",
    "build_loadout",
    "select_best_weapon",
]
