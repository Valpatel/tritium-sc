# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Task-aware model routing with fleet fallback.

Classifies inference tasks and routes to appropriate models. Supports
multi-host Ollama fleet with automatic failover inspired by Open Claw's
two-stage pattern: host rotation → model fallback.

When no fleet is configured, falls back to static single-host mode
(backwards compatible with current Amy behavior).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.perception.vision import ollama_chat


# ---------------------------------------------------------------------------
# Task classification
# ---------------------------------------------------------------------------

class TaskType(Enum):
    """Classification of an inference task for model routing."""
    SIMPLE_THINK = "simple_think"
    COMPLEX_REASON = "complex_reason"
    VISION = "vision"
    CODE_GEN = "code_gen"
    CHAT = "chat"


# ---------------------------------------------------------------------------
# Model profiles
# ---------------------------------------------------------------------------

@dataclass
class ModelProfile:
    """Metadata about a model's capabilities and cost/speed tradeoffs."""

    name: str
    capabilities: set[str] = field(default_factory=lambda: {"text"})
    speed: str = "fast"           # "fast", "medium", "slow"
    context_length: int = 4096
    priority: int = 10            # lower = preferred

    def has_capability(self, cap: str) -> bool:
        return cap in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capabilities": sorted(self.capabilities),
            "speed": self.speed,
            "context_length": self.context_length,
            "priority": self.priority,
        }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AllHostsFailedError(Exception):
    """All hosts/models in the fallback chain failed."""

    def __init__(self, task_type: TaskType, last_error: Exception | None = None):
        self.task_type = task_type
        self.last_error = last_error
        super().__init__(
            f"All hosts failed for task type '{task_type.value}'"
            f"{f': {last_error}' if last_error else ''}"
        )


# ---------------------------------------------------------------------------
# Capability requirements per task type
# ---------------------------------------------------------------------------

_TASK_REQUIRED_CAPS: dict[TaskType, set[str]] = {
    TaskType.SIMPLE_THINK: {"text"},
    TaskType.COMPLEX_REASON: {"text"},
    TaskType.VISION: {"vision"},
    TaskType.CODE_GEN: {"code"},
    TaskType.CHAT: {"text"},
}

# Tasks that prefer quality (larger models) over speed
_QUALITY_TASKS = {TaskType.COMPLEX_REASON, TaskType.CODE_GEN}


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------

class ModelRouter:
    """Task-aware model selection with fleet fallback.

    Classifies inference tasks and selects the best model/host combination.
    Supports multi-host Ollama fleet with automatic failover.
    """

    def __init__(
        self,
        profiles: list[ModelProfile] | None = None,
        fleet: Any | None = None,
        default_host: str = "http://localhost:11434",
    ):
        self._profiles: dict[str, ModelProfile] = {}
        self._fleet = fleet
        self._default_host = default_host

        if profiles:
            for p in profiles:
                self._profiles[p.name] = p

    @property
    def profiles(self) -> list[ModelProfile]:
        return list(self._profiles.values())

    def register(self, profile: ModelProfile) -> None:
        """Register or replace a model profile."""
        self._profiles[profile.name] = profile

    def unregister(self, name: str) -> None:
        """Remove a model profile (no error if missing)."""
        self._profiles.pop(name, None)

    def get_profile(self, name: str) -> ModelProfile | None:
        return self._profiles.get(name)

    # ----- Classification -----

    def classify_task(
        self,
        messages: list[dict] | None = None,
        context: dict | None = None,
        has_images: bool = False,
    ) -> TaskType:
        """Classify an inference request into a TaskType."""
        ctx = context or {}

        # Vision takes priority — images require multimodal model
        if has_images:
            return TaskType.VISION

        # Explicit flags from caller
        if ctx.get("code_gen_requested"):
            return TaskType.CODE_GEN
        if ctx.get("is_chat"):
            return TaskType.CHAT

        # Infer complexity from battlespace state
        hostile_count = ctx.get("hostile_count", 0)
        active_threats = ctx.get("active_threats", 0)
        if hostile_count > 0 or active_threats > 0:
            return TaskType.COMPLEX_REASON

        return TaskType.SIMPLE_THINK

    # ----- Selection -----

    def select_chain(self, task_type: TaskType) -> list[ModelProfile]:
        """Return ordered list of models suitable for this task type.

        Models are filtered by required capabilities, then sorted:
        - Quality tasks (complex, code): prefer slower/larger models (high priority number)
        - Speed tasks (simple, chat): prefer faster/smaller models (low priority number)
        """
        required_caps = _TASK_REQUIRED_CAPS.get(task_type, {"text"})

        candidates = [
            p for p in self._profiles.values()
            if required_caps.issubset(p.capabilities)
        ]

        if not candidates:
            return []

        if task_type in _QUALITY_TASKS:
            # Prefer quality: sort by priority descending (largest/slowest first)
            candidates.sort(key=lambda p: p.priority, reverse=True)
        else:
            # Prefer speed: sort by priority ascending (smallest/fastest first)
            candidates.sort(key=lambda p: p.priority)

        return candidates

    # ----- Inference -----

    def infer(
        self,
        task_type: TaskType,
        messages: list[dict],
        **kwargs,
    ) -> dict:
        """Run inference with automatic fallback.

        Two-stage failover (Open Claw pattern):
        1. Try each host for the preferred model
        2. Fall back to next model in the chain
        """
        chain = self.select_chain(task_type)

        if not chain:
            # No matching profiles — try first available model
            if self._profiles:
                chain = sorted(self._profiles.values(), key=lambda p: p.priority)
            else:
                raise AllHostsFailedError(task_type)

        last_error: Exception | None = None

        for profile in chain:
            hosts = self._get_hosts_for_model(profile.name)

            for host_url in hosts:
                try:
                    result = ollama_chat(
                        model=profile.name,
                        messages=messages,
                        base_url=host_url,
                    )
                    # Tag result with routing metadata
                    if "_routing" not in result:
                        result["_routing"] = {}
                    result["_routing"]["model"] = profile.name
                    result["_routing"]["host"] = host_url
                    result["_routing"]["task_type"] = task_type.value
                    return result
                except Exception as e:
                    last_error = e
                    continue

        raise AllHostsFailedError(task_type, last_error)

    def _get_hosts_for_model(self, model_name: str) -> list[str]:
        """Get available host URLs for a model.

        With fleet: query fleet for hosts that have this model.
        Without fleet: return default host.
        """
        if self._fleet is not None:
            try:
                fleet_hosts = self._fleet.hosts_with_model(model_name)
                if fleet_hosts:
                    return [h.url for h in fleet_hosts]
            except Exception:
                pass

        return [self._default_host]

    # ----- Factory methods -----

    @classmethod
    def from_static(
        cls,
        chat_model: str = "gemma3:4b",
        deep_model: str = "llava:7b",
        ollama_host: str = "http://localhost:11434",
    ) -> ModelRouter:
        """Create a router from static config (backwards compatible).

        Mirrors current Amy behavior: fixed models, single host.
        """
        profiles = [
            ModelProfile(
                name=chat_model,
                capabilities={"text"},
                speed="fast",
                priority=1,
            ),
            ModelProfile(
                name=deep_model,
                capabilities={"text", "vision"},
                speed="medium",
                priority=2,
            ),
        ]
        return cls(profiles=profiles, default_host=ollama_host)
