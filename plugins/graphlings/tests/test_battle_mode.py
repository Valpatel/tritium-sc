# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GraphlingBattleMode — the creature battle scenario.

Uses stub bridge/factory/tracker — no SDK dependency.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from graphlings.battle_mode import (
    BattleParticipant,
    BattleState,
    GraphlingBattleMode,
)
from graphlings.config import GraphlingsConfig


# ── Stub simulation objects ───────────────────────────────────────


@dataclass
class StubTarget:
    """Minimal SimulationTarget stub."""
    target_id: str = ""
    name: str = ""
    alliance: str = "friendly"
    asset_type: str = "graphling"
    position: tuple = (100.0, 200.0)
    heading: float = 0.0
    status: str = "active"
    waypoints: list = field(default_factory=list)
    is_combatant: bool = False


class StubFactory:
    """Minimal EntityFactory stub."""
    def __init__(self):
        self._counter = 0
        self._spawned: dict[str, str] = {}

    def spawn(self, soul_id, name, position, is_combatant=False, role_config=None):
        self._counter += 1
        target_id = f"graphling_{soul_id}_{self._counter}"
        self._spawned[soul_id] = target_id
        return target_id

    def despawn(self, soul_id):
        return self._spawned.pop(soul_id, None) is not None


class StubBridge:
    """Minimal AgentBridge stub returning dict responses."""
    def __init__(self):
        self.deployed: dict[str, dict] = {}
        self.recalled: list[str] = []
        self.think_calls: list[str] = []

    def deploy(self, soul_id, config):
        self.deployed[soul_id] = config
        return {
            "soul_id": soul_id,
            "deployment_id": f"dep_{soul_id}",
            "status": "deployed",
            "name": soul_id,
        }

    def recall(self, soul_id, reason="manual"):
        self.recalled.append(soul_id)
        return {"soul_id": soul_id, "status": "recalled"}

    def think(self, soul_id, perception, current_state, available_actions, urgency, preferred_layer=None):
        self.think_calls.append(soul_id)
        return {
            "thought": f"{soul_id} is thinking...",
            "action": 'say("Hello from battle!")',
            "emotion": "excited",
            "layer": 3,
            "model_used": "stub",
            "confidence": 0.8,
        }

    def list_active(self):
        return [{"soul_id": sid} for sid in self.deployed]

    def record_experiences(self, soul_id, experiences):
        return len(experiences)

    def heartbeat(self, soul_id):
        return {"status": "alive"}

    def feedback(self, soul_id, action, success, outcome=""):
        return {"status": "ok"}


class StubTracker:
    """Minimal TargetTracker stub."""
    def __init__(self):
        self._targets: dict[str, StubTarget] = {}

    def add(self, target):
        self._targets[target.target_id] = target

    def get_target(self, target_id):
        return self._targets.get(target_id)

    def get_all(self):
        return list(self._targets.values())


class StubPerception:
    """Minimal PerceptionEngine stub."""
    def build_perception(self, target_id, position, heading):
        return {
            "nearby_entities": [],
            "own_position": list(position),
            "own_heading": heading,
            "danger_level": 0.3,
            "noise_level": 0.1,
            "nearby_friendlies": 1,
            "nearby_hostiles": 1,
            "recent_events": [],
        }


class StubMotor:
    """Minimal MotorOutput stub."""
    def __init__(self):
        self.executed: list[tuple[str, str]] = []

    def execute(self, target_id, action):
        self.executed.append((target_id, action))
        return True


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def config():
    return GraphlingsConfig(dry_run=True)


@pytest.fixture
def bridge():
    return StubBridge()


@pytest.fixture
def factory():
    return StubFactory()


@pytest.fixture
def battle(bridge, factory, config):
    return GraphlingBattleMode(
        bridge=bridge,
        factory=factory,
        config=config,
        available_soul_ids=["twilight_001", "ember_001", "dewdrop_001"],
    )


# ── Tests ─────────────────────────────────────────────────────────


class TestBattleMode:
    """Verify the graphling battle mode lifecycle."""

    def test_start_deploys_graphlings(self, battle, bridge):
        ok = battle.start()
        assert ok is True
        assert battle.running is True
        assert len(battle.state.participants) == 3
        assert len(bridge.deployed) == 3

    def test_start_prevents_double_start(self, battle):
        battle.start()
        ok = battle.start()
        assert ok is False  # Already running

    def test_stop_recalls_all(self, battle, bridge):
        battle.start()
        summary = battle.stop(reason="test_done")
        assert battle.running is False
        assert len(bridge.recalled) == 3
        assert "participants" in summary

    def test_duration_tracking(self, battle):
        battle.start()
        assert battle.state.duration >= 0
        battle.stop()
        assert battle.state.duration >= 0

    def test_tick_runs_think_cycles(self, battle, bridge):
        battle.start()
        tracker = StubTracker()
        perception = StubPerception()
        motor = StubMotor()

        battle.tick(perception, tracker, motor)
        assert len(bridge.think_calls) == 3  # All 3 graphlings think

    def test_tick_rate_limits(self, battle, bridge):
        battle.start()
        tracker = StubTracker()
        perception = StubPerception()
        motor = StubMotor()

        # First tick -- all 3 think
        battle.tick(perception, tracker, motor)
        assert len(bridge.think_calls) == 3

        # Immediate second tick -- no new thinks (rate limited)
        bridge.think_calls.clear()
        battle.tick(perception, tracker, motor)
        assert len(bridge.think_calls) == 0

    def test_tick_executes_actions(self, battle):
        battle.start()
        motor = StubMotor()
        battle.tick(StubPerception(), StubTracker(), motor)
        assert len(motor.executed) == 3  # All 3 got actions

    def test_tick_increments_think_count(self, battle):
        battle.start()
        battle.tick(StubPerception(), StubTracker(), StubMotor())
        for p in battle.state.participants.values():
            assert p.think_count == 1

    def test_state_to_dict(self, battle):
        battle.start()
        d = battle.state.to_dict()
        assert d["running"] is True
        assert "participants" in d
        assert len(d["participants"]) == 3
        assert "event_count" in d

    def test_insufficient_souls_fails(self, bridge, factory, config):
        mode = GraphlingBattleMode(
            bridge=bridge,
            factory=factory,
            config=config,
            available_soul_ids=["only_one"],
        )
        # Only 1 soul ID available, need at least 2
        ok = mode.start()
        assert ok is False

    def test_custom_soul_ids(self, bridge, factory, config):
        mode = GraphlingBattleMode(
            bridge=bridge,
            factory=factory,
            config=config,
        )
        ok = mode.start(soul_ids=["a", "b", "c"])
        assert ok is True
        assert set(mode.state.participants.keys()) == {"a", "b", "c"}


class TestBattleState:
    """Verify BattleState tracking."""

    def test_empty_state(self):
        state = BattleState()
        assert state.duration == 0
        assert not state.running
        d = state.to_dict()
        assert d["running"] is False
        assert d["event_count"] == 0

    def test_participant_defaults(self):
        p = BattleParticipant(
            soul_id="test", target_id="t1",
            role_name="scout", alliance="friendly",
            is_combatant=False,
        )
        assert p.think_count == 0
        assert p.last_action == ""
        assert p.status == "active"
