"""NPC Intelligence Plugin — behavioral AI for neutral simulation entities.

Adds FSMs, LLM-powered thinking, event reactions, crowd dynamics, and
alliance transitions to pedestrians, vehicles, and animals.
"""

from .alliance import AllianceManager
from .brain import NPCBrain, NPCMemory, NPCPersonality
from .crowd import CrowdDynamics
from .event_reactor import EventReactor
from .fallback import BehaviorTreeFallback
from .npc_fsm import (
    create_animal_fsm,
    create_civilian_pedestrian_fsm,
    create_civilian_vehicle_fsm,
    create_npc_fsm,
)
from .mob import MobFormation, MobManager, RiotLevel
from .npc_router import NPCRouter
from .prompts import build_npc_prompt, parse_npc_response
from .routine import NPCRoutine, RoutineActivity, RoutineScheduler, VehicleRoutine
from .think_scheduler import LLMThinkScheduler
from .thought_registry import ThoughtRegistry, UnitThought
from .world_bridge import NPCWorldBridge
from .world_model import (
    WorldModel,
    BuildingInfo,
    CrosswalkPoint,
    DoorPoint,
    POI,
)

__all__ = [
    "AllianceManager",
    "BehaviorTreeFallback",
    "BuildingInfo",
    "CrosswalkPoint",
    "CrowdDynamics",
    "DoorPoint",
    "EventReactor",
    "LLMThinkScheduler",
    "MobFormation",
    "MobManager",
    "NPCBrain",
    "NPCMemory",
    "NPCPersonality",
    "NPCRouter",
    "NPCRoutine",
    "NPCWorldBridge",
    "POI",
    "RoutineActivity",
    "RoutineScheduler",
    "ThoughtRegistry",
    "UnitThought",
    "VehicleRoutine",
    "WorldModel",
    "build_npc_prompt",
    "create_animal_fsm",
    "create_civilian_pedestrian_fsm",
    "create_civilian_vehicle_fsm",
    "create_npc_fsm",
    "parse_npc_response",
]
