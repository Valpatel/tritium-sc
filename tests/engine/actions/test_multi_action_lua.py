"""Unit tests for multi-action Lua parsing — compound behavior sequences.

Tests parsing multiple Lua function calls from a single LLM response,
including code blocks, sequences, and validation of action chains.
Written TDD-first.
"""
from __future__ import annotations

import pytest


# ===========================================================================
# Multi-Action Extraction
# ===========================================================================

@pytest.mark.unit
class TestMultiActionExtract:
    """extract_multi_actions — parse multiple Lua calls from one response."""

    def test_single_action(self):
        from engine.actions.lua_multi import extract_multi_actions
        actions = extract_multi_actions('say("Hello!")')
        assert len(actions) == 1
        assert actions[0] == 'say("Hello!")'

    def test_two_actions_newline(self):
        from engine.actions.lua_multi import extract_multi_actions
        actions = extract_multi_actions('escalate("h-1", "hostile")\ndispatch("rover-01", 5.0, 10.0)')
        assert len(actions) == 2

    def test_code_block(self):
        from engine.actions.lua_multi import extract_multi_actions
        code = '''```lua
escalate("h-1", "hostile")
dispatch("rover-01", 5.0, 10.0)
battle_cry("Contact!")
```'''
        actions = extract_multi_actions(code)
        assert len(actions) == 3

    def test_mixed_text_and_code(self):
        from engine.actions.lua_multi import extract_multi_actions
        response = '''I see a hostile approaching. Taking action:
```lua
escalate("h-1", "suspicious")
dispatch("rover-01", 5.0, 10.0)
```'''
        actions = extract_multi_actions(response)
        assert len(actions) == 2

    def test_empty_response(self):
        from engine.actions.lua_multi import extract_multi_actions
        assert extract_multi_actions("") == []

    def test_no_actions(self):
        from engine.actions.lua_multi import extract_multi_actions
        assert extract_multi_actions("I'm just thinking about things.") == []

    def test_comments_ignored(self):
        from engine.actions.lua_multi import extract_multi_actions
        code = '''-- Respond to intruder
escalate("h-1", "hostile")
-- Deploy the rover
dispatch("rover-01", 5.0, 10.0)'''
        actions = extract_multi_actions(code)
        assert len(actions) == 2

    def test_think_tags_stripped(self):
        from engine.actions.lua_multi import extract_multi_actions
        code = '''<think>I need to respond to this threat</think>
escalate("h-1", "hostile")
dispatch("rover-01", 5.0, 10.0)'''
        actions = extract_multi_actions(code)
        assert len(actions) == 2


# ===========================================================================
# Multi-Action Parsing
# ===========================================================================

@pytest.mark.unit
class TestMultiActionParse:
    """parse_multi_actions — parse and validate action sequences."""

    def test_parse_single(self):
        from engine.actions.lua_multi import parse_multi_actions
        results = parse_multi_actions('think("Quiet afternoon.")')
        assert len(results) == 1
        assert results[0].valid
        assert results[0].action == "think"

    def test_parse_sequence(self):
        from engine.actions.lua_multi import parse_multi_actions
        code = 'escalate("h-1", "hostile")\ndispatch("rover-01", 5.0, 10.0)'
        results = parse_multi_actions(code)
        assert len(results) == 2
        assert all(r.valid for r in results)
        assert results[0].action == "escalate"
        assert results[1].action == "dispatch"

    def test_partial_invalid(self):
        from engine.actions.lua_multi import parse_multi_actions
        code = 'say("Hello")\ninvalid_function("bad")\nthink("OK")'
        results = parse_multi_actions(code)
        valid_results = [r for r in results if r.valid]
        assert len(valid_results) >= 2  # say and think should be valid

    def test_all_invalid(self):
        from engine.actions.lua_multi import parse_multi_actions
        results = parse_multi_actions("no valid lua here at all")
        assert len(results) == 0 or all(not r.valid for r in results)


# ===========================================================================
# Multi-Action Validation
# ===========================================================================

@pytest.mark.unit
class TestMultiActionValidation:
    """validate_action_sequence — check a sequence of actions for safety."""

    def test_valid_sequence(self):
        from engine.actions.lua_multi import validate_action_sequence
        from engine.actions.lua_motor import MotorOutput
        actions = [
            MotorOutput(action="escalate", params=["h-1", "hostile"], valid=True),
            MotorOutput(action="dispatch", params=["rover-01", 5.0, 10.0], valid=True),
        ]
        errors = validate_action_sequence(actions)
        assert errors == []

    def test_rejects_too_many_say(self):
        from engine.actions.lua_multi import validate_action_sequence
        from engine.actions.lua_motor import MotorOutput
        actions = [
            MotorOutput(action="say", params=["Hello!"], valid=True),
            MotorOutput(action="say", params=["How are you?"], valid=True),
            MotorOutput(action="say", params=["Nice day!"], valid=True),
        ]
        errors = validate_action_sequence(actions)
        assert len(errors) >= 1  # Too many speech actions

    def test_rejects_invalid_in_sequence(self):
        from engine.actions.lua_multi import validate_action_sequence
        from engine.actions.lua_motor import MotorOutput
        actions = [
            MotorOutput(action="say", params=["Hello!"], valid=True),
            MotorOutput(action="bad", params=[], valid=False, error="Unknown action"),
        ]
        errors = validate_action_sequence(actions)
        assert len(errors) >= 1

    def test_max_sequence_length(self):
        from engine.actions.lua_multi import validate_action_sequence, MAX_SEQUENCE_LENGTH
        from engine.actions.lua_motor import MotorOutput
        actions = [
            MotorOutput(action="think", params=[f"thought {i}"], valid=True)
            for i in range(MAX_SEQUENCE_LENGTH + 5)
        ]
        errors = validate_action_sequence(actions)
        assert len(errors) >= 1  # Sequence too long

    def test_empty_sequence_ok(self):
        from engine.actions.lua_multi import validate_action_sequence
        errors = validate_action_sequence([])
        assert errors == []
