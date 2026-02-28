# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Tests for hostile agent FSM and decision-making.
TDD: Write tests first, watch them fail, then implement.
"""

import sys
import os
import unittest
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hostile import HostileAgent, HostileState


class TestHostileCreation(unittest.TestCase):
    """Basic hostile agent creation and defaults."""

    def test_create_agent(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=100.0, start_y=50.0)
        self.assertIsNotNone(agent)

    def test_default_state_is_spawning(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        self.assertEqual(agent.state, HostileState.SPAWNING)

    def test_default_health(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        self.assertEqual(agent.health, 100)

    def test_position_set(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=42.0, start_y=-13.5)
        self.assertAlmostEqual(agent.x, 42.0)
        self.assertAlmostEqual(agent.y, -13.5)

    def test_hostile_id(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        self.assertEqual(agent.hostile_id, "hostile-01")

    def test_speed_default(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        self.assertGreater(agent.speed, 0)
        self.assertLessEqual(agent.speed, 5.0)

    def test_alive_on_creation(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        self.assertTrue(agent.alive)


class TestHostileStates(unittest.TestCase):
    """FSM state transitions."""

    def test_spawning_transitions_to_advancing(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.state = HostileState.SPAWNING
        # After spawn delay, should advance
        for _ in range(30):  # 3 seconds at 10Hz
            agent.tick(0.1)
        self.assertEqual(agent.state, HostileState.ADVANCING)

    def test_advancing_moves_toward_target(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.state = HostileState.ADVANCING
        agent.target_x = 100.0
        agent.target_y = 0.0
        old_x = agent.x
        agent.tick(1.0)
        self.assertGreater(agent.x, old_x)

    def test_take_damage_reduces_health(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.take_damage(25)
        self.assertEqual(agent.health, 75)

    def test_fatal_damage_kills(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.take_damage(100)
        self.assertFalse(agent.alive)
        self.assertEqual(agent.state, HostileState.DEAD)

    def test_damage_triggers_fleeing_at_low_health(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.state = HostileState.ADVANCING
        agent.take_damage(80)  # health = 20, should flee
        self.assertEqual(agent.state, HostileState.FLEEING)

    def test_flanking_moves_perpendicular(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.state = HostileState.FLANKING
        agent.target_x = 100.0
        agent.target_y = 0.0
        agent.tick(1.0)
        # Should have some lateral movement (y changed or x changed differently)
        self.assertTrue(abs(agent.y) > 0 or agent.x > 0)

    def test_attacking_state_exists(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.state = HostileState.ATTACKING
        self.assertEqual(agent.state, HostileState.ATTACKING)

    def test_hiding_reduces_visibility(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.state = HostileState.HIDING
        self.assertTrue(agent.is_hidden)

    def test_dead_agent_does_not_move(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=10, start_y=10)
        agent.take_damage(200)  # kill
        old_x, old_y = agent.x, agent.y
        agent.tick(1.0)
        self.assertEqual(agent.x, old_x)
        self.assertEqual(agent.y, old_y)


class TestHostileTelemetry(unittest.TestCase):
    """Telemetry output format."""

    def test_telemetry_has_required_fields(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=10, start_y=20)
        t = agent.get_telemetry()
        required = ['robot_id', 'name', 'asset_type', 'position', 'heading',
                     'health', 'status', 'fsm_state', 'alliance', 'timestamp']
        for field in required:
            self.assertIn(field, t, f"Missing field: {field}")

    def test_telemetry_alliance_is_hostile(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        t = agent.get_telemetry()
        self.assertEqual(t['alliance'], 'hostile')

    def test_telemetry_asset_type_is_person(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        t = agent.get_telemetry()
        self.assertEqual(t['asset_type'], 'person')

    def test_telemetry_position_format(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=10, start_y=20)
        t = agent.get_telemetry()
        self.assertIn('x', t['position'])
        self.assertIn('y', t['position'])
        self.assertAlmostEqual(t['position']['x'], 10.0)
        self.assertAlmostEqual(t['position']['y'], 20.0)

    def test_telemetry_json_serializable(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        t = agent.get_telemetry()
        s = json.dumps(t)
        self.assertIsInstance(s, str)

    def test_telemetry_timestamp_iso8601(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        t = agent.get_telemetry()
        self.assertTrue(t['timestamp'].endswith('Z'))

    def test_telemetry_fsm_state_matches(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.state = HostileState.FLANKING
        t = agent.get_telemetry()
        self.assertEqual(t['fsm_state'], 'flanking')


class TestHostileDecision(unittest.TestCase):
    """LLM decision-making integration."""

    def test_build_decision_prompt(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        prompt = agent.build_decision_prompt()
        self.assertIsInstance(prompt, str)
        self.assertIn("hostile-01", prompt)
        self.assertIn("health", prompt.lower())

    def test_parse_llm_response_advance(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        action = agent.parse_llm_response("ADVANCE toward the nearest defender")
        self.assertEqual(action, "advance")

    def test_parse_llm_response_flank(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        action = agent.parse_llm_response("FLANK to the left side")
        self.assertEqual(action, "flank")

    def test_parse_llm_response_hide(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        action = agent.parse_llm_response("HIDE behind cover and wait")
        self.assertEqual(action, "hide")

    def test_parse_llm_response_attack(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        action = agent.parse_llm_response("ATTACK the turret at position 50,30")
        self.assertEqual(action, "attack")

    def test_parse_llm_response_flee(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        action = agent.parse_llm_response("FLEE from the engagement")
        self.assertEqual(action, "flee")

    def test_parse_llm_response_unknown_defaults_to_advance(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        action = agent.parse_llm_response("I think I should do something creative")
        self.assertEqual(action, "advance")

    def test_apply_action_advance(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.state = HostileState.HIDING
        agent.apply_action("advance")
        self.assertEqual(agent.state, HostileState.ADVANCING)

    def test_apply_action_flank(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.apply_action("flank")
        self.assertEqual(agent.state, HostileState.FLANKING)

    def test_apply_action_hide(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.apply_action("hide")
        self.assertEqual(agent.state, HostileState.HIDING)

    def test_apply_action_attack(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.apply_action("attack")
        self.assertEqual(agent.state, HostileState.ATTACKING)

    def test_apply_action_flee(self):
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.apply_action("flee")
        self.assertEqual(agent.state, HostileState.FLEEING)

    def test_decision_interval(self):
        """Decisions happen every N seconds, not every tick."""
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        self.assertGreater(agent.decision_interval, 1.0)

    def test_situation_awareness(self):
        """Agent can receive information about nearby units."""
        agent = HostileAgent(hostile_id="hostile-01", start_x=0, start_y=0)
        agent.update_situation({
            'nearby_defenders': [
                {'id': 'rover-01', 'type': 'rover', 'x': 50, 'y': 30, 'distance': 58.3}
            ],
            'nearby_hostiles': [],
            'under_fire': False,
        })
        self.assertEqual(len(agent.nearby_defenders), 1)


class TestHostileLLMClient(unittest.TestCase):
    """LLM client for Ollama."""

    def test_llm_client_has_generate(self):
        from llm_client import LLMClient
        client = LLMClient()
        self.assertTrue(hasattr(client, 'generate'))

    def test_llm_client_default_model(self):
        from llm_client import LLMClient
        client = LLMClient()
        self.assertEqual(client.model, 'qwen2.5:7b')

    def test_llm_client_custom_model(self):
        from llm_client import LLMClient
        client = LLMClient(model='llama3.2:3b')
        self.assertEqual(client.model, 'llama3.2:3b')

    def test_llm_client_fallback_on_error(self):
        """If Ollama is unreachable, generate() returns a fallback action."""
        from llm_client import LLMClient
        client = LLMClient(host='http://localhost:99999')
        result = client.generate("What should I do?")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


if __name__ == '__main__':
    unittest.main()
