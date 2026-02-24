"""Engine perception pipeline — frame analysis and fact extraction.

L0: Quality gate (sharpness, brightness)
L1: Complexity (edge density)
L2: Motion (frame diff)
Plus: Ollama vision API, fact extraction from conversation.
"""

from engine.perception.perception import (
    CameraPose,
    FrameAnalyzer,
    FrameMetrics,
    PoseEstimator,
)
from engine.perception.extraction import extract_facts, extract_person_name
from engine.perception.vision import ollama_chat, set_ollama_host

__all__ = [
    "CameraPose",
    "FrameAnalyzer",
    "FrameMetrics",
    "PoseEstimator",
    "extract_facts",
    "extract_person_name",
    "ollama_chat",
    "set_ollama_host",
]
