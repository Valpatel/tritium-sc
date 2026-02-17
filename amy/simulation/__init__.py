"""Backward-compatible re-export — canonical location is simulation/."""
from simulation.ambient import AmbientSpawner
from simulation.engine import SimulationEngine
from simulation.loader import load_layout
from simulation.target import SimulationTarget

__all__ = ["SimulationEngine", "SimulationTarget", "AmbientSpawner", "load_layout"]
