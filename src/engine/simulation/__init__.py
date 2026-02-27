"""Simulation subsystem — battlespace engine, combat, game modes."""
from .ambient import AmbientSpawner
from .behaviors import UnitBehaviors
from .combat import CombatSystem, Projectile
from .comms import Signal, UnitComms
from .cover import CoverObject, CoverSystem
from .degradation import DegradationSystem
from .difficulty import DifficultyScaler, WaveRecord
from .engine import SimulationEngine
from .fake_robot import FakeRobot, FakeRobotFleet
from .game_mode import GameMode, InfiniteWaveMode, WaveConfig, WAVE_CONFIGS
from .hazards import Hazard, HazardManager
from .intercept import lead_target, predict_intercept, target_velocity, time_to_intercept
from .loader import load_layout, load_zones
from .morale import MoraleSystem
from .movement import MovementController, smooth_path
from .pathfinding import plan_path
from .pursuit import PursuitSystem
from .replay import ReplayRecorder
from .scenario import BattleScenario, DefenderConfig, SpawnGroup, WaveDefinition, load_battle_scenario
from .sensors import SensorDevice, SensorSimulator
from .spatial import SpatialGrid
from .spectator import SpectatorMode
from .squads import Squad, SquadManager
from .state_machine import State, StateMachine, Transition
from .stats import StatsTracker, UnitStats, WaveStats
from .target import SimulationTarget
from .terrain import TerrainCell, TerrainMap
from .unit_states import create_turret_fsm, create_rover_fsm, create_drone_fsm, create_hostile_fsm, create_fsm_for_type
from .upgrades import Upgrade, Ability, ActiveEffect, UpgradeSystem
from .weapons import Weapon, WeaponSystem

__all__ = [
    "AmbientSpawner",
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
    "MoraleSystem",
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
    "UnitStats",
    "Upgrade",
    "Ability",
    "ActiveEffect",
    "UpgradeSystem",
    "WaveConfig",
    "WaveRecord",
    "WaveStats",
    "WAVE_CONFIGS",
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
    "plan_path",
    "predict_intercept",
    "smooth_path",
    "target_velocity",
    "time_to_intercept",
]
