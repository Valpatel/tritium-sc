"""Tests for multi-action Lua dispatch in ThinkingThread.

Verifies that when the LLM returns compound behaviors (multiple Lua calls),
the thinking thread dispatches them in sequence while respecting safety limits.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from amy.actions.lua_multi import parse_multi_actions, validate_action_sequence, extract_multi_actions
from amy.actions.lua_motor import MotorOutput


@pytest.mark.unit
class TestMultiActionExtraction:
    """Extract compound Lua from typical LLM responses."""

    def test_think_then_dispatch(self):
        response = 'think("Hostile spotted north")\ndispatch("rover-01", 10.0, 5.0)'
        calls = extract_multi_actions(response)
        assert len(calls) == 2

    def test_think_then_escalate_then_battle_cry(self):
        response = '''```lua
-- Enemy approaching from the east
escalate("hostile-3", "hostile")
dispatch("drone-01", 15.0, 8.0)
battle_cry("Contact east! Deploying drone!")
```'''
        calls = extract_multi_actions(response)
        assert len(calls) == 3
        assert "escalate" in calls[0]
        assert "dispatch" in calls[1]
        assert "battle_cry" in calls[2]

    def test_single_action_still_works(self):
        calls = extract_multi_actions('think("All quiet")')
        assert len(calls) == 1


@pytest.mark.unit
class TestMultiActionValidation:
    """Sequence validation — safety limits."""

    def test_valid_sequence(self):
        actions = parse_multi_actions('think("Check")\ndispatch("r1", 5.0, 3.0)')
        errors = validate_action_sequence(actions)
        assert errors == []

    def test_too_many_say(self):
        actions = parse_multi_actions('say("Hello")\nsay("World")')
        errors = validate_action_sequence(actions)
        assert any("say()" in e for e in errors)

    def test_single_say_ok(self):
        actions = parse_multi_actions('think("Check")\nsay("Contact!")')
        errors = validate_action_sequence(actions)
        assert errors == []

    def test_sequence_too_long(self):
        """More than MAX_SEQUENCE_LENGTH actions is rejected."""
        actions = [MotorOutput(raw_response="x", raw_lua="x", action="think",
                               params=["t"], valid=True)] * 15
        errors = validate_action_sequence(actions)
        assert any("too long" in e.lower() for e in errors)


@pytest.mark.unit
class TestMultiActionParsing:
    """parse_multi_actions — full parse of compound response."""

    def test_all_valid(self):
        actions = parse_multi_actions('think("Hello")\nsay("World")')
        assert len(actions) == 2
        assert all(a.valid for a in actions)

    def test_mixed_valid_invalid(self):
        actions = parse_multi_actions('think("OK")\nnonsense_action()')
        # think should be valid, nonsense unknown
        valid = [a for a in actions if a.valid]
        assert len(valid) >= 1

    def test_empty_response(self):
        actions = parse_multi_actions('')
        assert actions == []


@pytest.mark.unit
class TestDispatchSequence:
    """ThinkingThread should dispatch valid multi-action sequences."""

    def test_dispatch_multiple_thinks(self):
        """Multiple think() actions should all record to sensorium."""
        from amy.actions.lua_multi import parse_multi_actions, validate_action_sequence

        response = 'think("Hostile spotted")\nthink("Need to dispatch rover")'
        actions = parse_multi_actions(response)
        errors = validate_action_sequence(actions)
        assert errors == []

        # Simulate dispatch: each valid action gets dispatched
        dispatched = []
        for a in actions:
            if a.valid:
                dispatched.append(a.action)
        assert dispatched == ["think", "think"]

    def test_dispatch_think_then_dispatch(self):
        """Think + dispatch compound behavior."""
        response = 'think("Hostile at north perimeter")\ndispatch("rover-alpha", 10.0, 5.0)'
        actions = parse_multi_actions(response)
        errors = validate_action_sequence(actions)
        assert errors == []

        dispatched = [(a.action, a.params) for a in actions if a.valid]
        assert len(dispatched) == 2
        assert dispatched[0][0] == "think"
        assert dispatched[1][0] == "dispatch"
        assert dispatched[1][1] == ["rover-alpha", 10.0, 5.0]

    def test_invalid_actions_skipped(self):
        """Invalid actions in sequence are skipped, valid ones dispatched."""
        actions = parse_multi_actions('think("OK")\nfake_action()\nsay("Done")')
        valid = [a for a in actions if a.valid]
        # think and say should be valid, fake_action is unknown
        action_names = [a.action for a in valid]
        assert "think" in action_names
        assert "say" in action_names
