# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for Civil Unrest mission type — data model extensions.

Tests from spec section 2.8 covering SimulationTarget fields, combat profiles,
GameMode scoring, and defeat conditions. Mission Director registration tests
are in test_mission_director_modes.py.
"""

from __future__ import annotations

import math
import queue
import threading

import pytest

from engine.simulation.target import SimulationTarget, _COMBAT_PROFILES
from engine.simulation.game_mode import GameMode
from engine.simulation.combat import CombatSystem
from engine.simulation.engine import SimulationEngine


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(topic, []).append(q)
        return q


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Test 4: crowd_role field on SimulationTarget
# --------------------------------------------------------------------------

class TestCrowdRoleField:
    def test_crowd_role_field_on_target(self):
        """SimulationTarget accepts crowd_role field (None by default)."""
        t = SimulationTarget(
            target_id="civ-1",
            name="Civilian",
            alliance="neutral",
            asset_type="person",
            position=(50.0, 50.0),
            speed=1.0,
            is_combatant=False,
        )
        assert t.crowd_role is None

    def test_crowd_role_accepts_civilian(self):
        t = SimulationTarget(
            target_id="civ-2",
            name="Civilian",
            alliance="neutral",
            asset_type="person",
            position=(50.0, 50.0),
            speed=1.0,
            crowd_role="civilian",
        )
        assert t.crowd_role == "civilian"

    def test_crowd_role_accepts_instigator(self):
        t = SimulationTarget(
            target_id="ins-1",
            name="Instigator",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 50.0),
            speed=1.5,
            crowd_role="instigator",
        )
        assert t.crowd_role == "instigator"

    def test_crowd_role_accepts_rioter(self):
        t = SimulationTarget(
            target_id="riot-1",
            name="Rioter",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 50.0),
            speed=1.0,
            crowd_role="rioter",
        )
        assert t.crowd_role == "rioter"


# --------------------------------------------------------------------------
# Test 5: civilian not combatant
# --------------------------------------------------------------------------

class TestCivilianProfile:
    def test_civilian_not_combatant(self):
        """crowd_role='civilian' + apply_combat_profile() -> is_combatant=False."""
        t = SimulationTarget(
            target_id="civ-3",
            name="Civilian",
            alliance="neutral",
            asset_type="person",
            position=(50.0, 50.0),
            speed=1.0,
            crowd_role="civilian",
        )
        t.apply_combat_profile()
        assert t.is_combatant is False
        assert t.health == 50.0
        assert t.max_health == 50.0
        assert t.weapon_range == 0.0
        assert t.weapon_damage == 0.0


# --------------------------------------------------------------------------
# Test 6: instigator is combatant
# --------------------------------------------------------------------------

class TestInstigatorProfile:
    def test_instigator_is_combatant(self):
        """crowd_role='instigator' -> is_combatant=True."""
        t = SimulationTarget(
            target_id="ins-2",
            name="Instigator",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 50.0),
            speed=1.5,
            crowd_role="instigator",
        )
        t.apply_combat_profile()
        assert t.is_combatant is True
        assert t.health == 60.0
        assert t.max_health == 60.0
        assert t.weapon_range == 15.0
        assert t.weapon_cooldown == 3.0
        assert t.weapon_damage == 5.0


# --------------------------------------------------------------------------
# Test 7: rioter is combatant with low damage
# --------------------------------------------------------------------------

class TestRioterProfile:
    def test_rioter_is_combatant(self):
        """crowd_role='rioter' -> is_combatant=True, low damage stats."""
        t = SimulationTarget(
            target_id="riot-2",
            name="Rioter",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 50.0),
            speed=1.0,
            crowd_role="rioter",
        )
        t.apply_combat_profile()
        assert t.is_combatant is True
        assert t.health == 50.0
        assert t.max_health == 50.0
        assert t.weapon_range == 3.0  # melee only
        assert t.weapon_cooldown == 2.0
        assert t.weapon_damage == 3.0


# --------------------------------------------------------------------------
# Test 8: civilian harm penalty
# --------------------------------------------------------------------------

class TestCivilianHarmPenalty:
    def _make_game_mode(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.game_mode_type = "civil_unrest"
        return gm, bus

    def test_civilian_harm_penalty(self):
        """-500 de_escalation_score on civilian harm."""
        gm, bus = self._make_game_mode()
        gm.de_escalation_score = 1000
        gm.on_civilian_harmed()
        assert gm.civilian_harm_count == 1
        assert gm.de_escalation_score == 500  # 1000 - 500


# --------------------------------------------------------------------------
# Test 9: excessive force defeat
# --------------------------------------------------------------------------

class TestExcessiveForceDefeat:
    def _make_game_mode(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.game_mode_type = "civil_unrest"
        return gm, bus

    def test_excessive_force_defeat(self):
        """5 civilian harms triggers defeat state."""
        gm, bus = self._make_game_mode()
        q = bus.subscribe("game_over")
        gm.state = "active"
        for _ in range(5):
            gm.on_civilian_harmed()
        assert gm.civilian_harm_count == 5
        assert gm.state == "defeat"
        # Verify game_over event was published
        event = q.get(timeout=1.0)
        assert event["result"] == "defeat"
        assert event["reason"] == "excessive_force"


# --------------------------------------------------------------------------
# Test 10: de_escalation_score tracking
# --------------------------------------------------------------------------

class TestDeEscalationScoreTracking:
    def test_de_escalation_score_tracking(self):
        """GameMode tracks de_escalation_score separately from score."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.game_mode_type = "civil_unrest"
        assert gm.de_escalation_score == 0
        assert gm.score == 0
        # They are independent
        gm.score = 500
        gm.de_escalation_score = 1200
        assert gm.score == 500
        assert gm.de_escalation_score == 1200


# --------------------------------------------------------------------------
# Test 11: weighted final score
# --------------------------------------------------------------------------

class TestWeightedFinalScore:
    def test_weighted_final_score(self):
        """Final score = combat_score * 0.3 + de_escalation_score * 0.7."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.game_mode_type = "civil_unrest"
        gm.score = 1000  # combat score
        gm.de_escalation_score = 2000
        state = gm.get_state()
        expected = int(1000 * 0.3 + 2000 * 0.7)  # 300 + 1400 = 1700
        assert state["weighted_total_score"] == expected


# Mission Director registration tests (tests 1-3, 12-15) are in
# tests/engine/simulation/test_mission_director_modes.py
