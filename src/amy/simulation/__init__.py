"""Simulation subsystem — battlespace engine, combat, game modes."""
from .ambient import AmbientSpawner
from .behaviors import UnitBehaviors
from .combat import CombatSystem, Projectile
from .engine import SimulationEngine
from .game_mode import GameMode, WaveConfig, WAVE_CONFIGS
from .loader import load_layout, load_zones
from .target import SimulationTarget

__all__ = [
    "AmbientSpawner",
    "CombatSystem",
    "GameMode",
    "Projectile",
    "SimulationEngine",
    "SimulationTarget",
    "UnitBehaviors",
    "WaveConfig",
    "WAVE_CONFIGS",
    "load_layout",
    "load_zones",
]
