"""Battlespace simulation engine — drives simulated targets at 10 Hz.

Package layout:
  target.py   — SimulationTarget dataclass (entity model + tick physics)
  engine.py   — SimulationEngine (10 Hz loop, hostile spawner, lifecycle)
  ambient.py  — AmbientSpawner (neutral neighborhood activity)
  loader.py   — TritiumLevelFormat JSON loader (static level -> engine)

See docs/SIMULATION.md for the full architecture diagram and design rationale.
"""

from .ambient import AmbientSpawner
from .engine import SimulationEngine
from .loader import load_layout
from .target import SimulationTarget

__all__ = ["SimulationEngine", "SimulationTarget", "AmbientSpawner", "load_layout"]
