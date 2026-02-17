"""Unit tests for Amy's Lua motor parser."""

from __future__ import annotations

import pytest

from amy.lua_motor import (
    MotorOutput,
    VALID_ACTIONS,
    VALID_DIRECTIONS,
    extract_lua_from_response,
    parse_function_call,
    parse_lua_number,
    parse_lua_string,
    parse_lua_value,
    parse_motor_output,
    split_arguments,
    validate_action,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# parse_lua_string
# ---------------------------------------------------------------------------

class TestParseLuaString:
    def test_double_quoted(self):
        assert parse_lua_string('"hello"') == "hello"

    def test_single_quoted(self):
        assert parse_lua_string("'hello'") == "hello"

    def test_escaped_quote(self):
        assert parse_lua_string('"say \\"hi\\""') == 'say "hi"'

    def test_escape_sequences(self):
        assert parse_lua_string(r'"line1\nline2"') == "line1\nline2"
        assert parse_lua_string(r'"col1\tcol2"') == "col1\tcol2"
        assert parse_lua_string(r'"back\\"') == "back\\"

    def test_not_a_string(self):
        assert parse_lua_string("42") is None
        assert parse_lua_string("hello") is None

    def test_empty_string(self):
        assert parse_lua_string('""') == ""


# ---------------------------------------------------------------------------
# parse_lua_number
# ---------------------------------------------------------------------------

class TestParseLuaNumber:
    def test_integer(self):
        assert parse_lua_number("42") == 42
        assert isinstance(parse_lua_number("42"), int)

    def test_float(self):
        assert parse_lua_number("3.14") == 3.14
        assert isinstance(parse_lua_number("3.14"), float)

    def test_negative(self):
        assert parse_lua_number("-7") == -7

    def test_not_a_number(self):
        assert parse_lua_number("abc") is None
        assert parse_lua_number('"42"') is None


# ---------------------------------------------------------------------------
# parse_lua_value
# ---------------------------------------------------------------------------

class TestParseLuaValue:
    def test_string(self):
        assert parse_lua_value('"hello"') == "hello"

    def test_number(self):
        assert parse_lua_value("10") == 10

    def test_boolean_true(self):
        assert parse_lua_value("true") is True

    def test_boolean_false(self):
        assert parse_lua_value("false") is False

    def test_nil(self):
        assert parse_lua_value("nil") is None

    def test_identifier(self):
        assert parse_lua_value("some_var") == "some_var"

    def test_whitespace_stripped(self):
        assert parse_lua_value("  42  ") == 42


# ---------------------------------------------------------------------------
# split_arguments
# ---------------------------------------------------------------------------

class TestSplitArguments:
    def test_single_string(self):
        assert split_arguments('"hello"') == ['"hello"']

    def test_two_strings(self):
        assert split_arguments('"key", "value"') == ['"key"', '"value"']

    def test_string_with_comma(self):
        assert split_arguments('"hello, world"') == ['"hello, world"']

    def test_mixed_types(self):
        assert split_arguments('"msg", 42, true') == ['"msg"', '42', 'true']

    def test_empty(self):
        assert split_arguments("") == []

    def test_escaped_quote_in_string(self):
        result = split_arguments(r'"say \"hi\"", "ok"')
        assert len(result) == 2


# ---------------------------------------------------------------------------
# parse_function_call
# ---------------------------------------------------------------------------

class TestParseFunctionCall:
    def test_no_args(self):
        result = parse_function_call("scan()")
        assert result == ("scan", [])

    def test_single_string_arg(self):
        result = parse_function_call('say("Hello world")')
        assert result is not None
        assert result[0] == "say"
        assert result[1] == ["Hello world"]

    def test_two_string_args(self):
        result = parse_function_call('remember("mood", "happy")')
        assert result is not None
        assert result[0] == "remember"
        assert result[1] == ["mood", "happy"]

    def test_numeric_arg(self):
        result = parse_function_call("wait(5)")
        assert result is not None
        assert result[0] == "wait"
        assert result[1] == [5]

    def test_not_a_function(self):
        assert parse_function_call("just some text") is None

    def test_case_insensitive_name(self):
        result = parse_function_call('Say("hi")')
        assert result is not None
        assert result[0] == "say"


# ---------------------------------------------------------------------------
# extract_lua_from_response
# ---------------------------------------------------------------------------

class TestExtractLua:
    def test_bare_function_call(self):
        assert extract_lua_from_response('say("Hello")') == 'say("Hello")'

    def test_lua_code_block(self):
        response = '```lua\nsay("Hello")\n```'
        assert extract_lua_from_response(response) == 'say("Hello")'

    def test_generic_code_block(self):
        response = '```\nscan()\n```'
        assert extract_lua_from_response(response) == 'scan()'

    def test_strip_complete_think_tags(self):
        response = '<think>I should greet them.</think>\nsay("Hi")'
        result = extract_lua_from_response(response)
        assert "think>" not in result.lower()
        assert 'say("Hi")' == result

    def test_strip_incomplete_think_tag(self):
        response = 'say("Hi")\n<think>I wonder if'
        result = extract_lua_from_response(response)
        assert 'say("Hi")' == result

    def test_auto_complete_truncated_say(self):
        response = 'say("Hello there'
        result = extract_lua_from_response(response)
        assert result == 'say("Hello there")'

    def test_auto_complete_truncated_think(self):
        response = 'think("Hmm interesting'
        result = extract_lua_from_response(response)
        assert result == 'think("Hmm interesting")'

    def test_function_in_surrounding_text(self):
        response = 'I will greet the user. say("Hello") and be nice.'
        result = extract_lua_from_response(response)
        assert result == 'say("Hello")'

    def test_empty_response(self):
        assert extract_lua_from_response("") == ""

    def test_plain_text_passthrough(self):
        result = extract_lua_from_response("just some words")
        assert result == "just some words"


# ---------------------------------------------------------------------------
# validate_action
# ---------------------------------------------------------------------------

class TestValidateAction:
    def test_valid_say(self):
        assert validate_action("say", ["Hello"]) is None

    def test_unknown_action(self):
        err = validate_action("dance", [])
        assert err is not None
        assert "Unknown action" in err

    def test_too_few_params(self):
        err = validate_action("say", [])
        assert err is not None
        assert "at least" in err

    def test_too_many_params(self):
        err = validate_action("scan", ["extra"])
        assert err is not None
        assert "at most" in err

    def test_say_rejects_assistant_pattern(self):
        err = validate_action("say", ["How can I assist you today?"])
        assert err is not None
        assert "assistant" in err.lower()

    def test_say_rejects_code_fragment(self):
        err = validate_action("say", ['actions: - say("hi")'])
        assert err is not None
        assert "code/prompt" in err.lower()

    def test_say_rejects_multiline(self):
        err = validate_action("say", ["line one\nline two"])
        assert err is not None
        assert "multi-line" in err.lower()

    def test_say_rejects_non_string(self):
        err = validate_action("say", [42])
        assert err is not None
        assert "string" in err.lower()

    def test_look_at_valid_direction(self):
        params = ["person"]
        assert validate_action("look_at", params) is None

    def test_look_at_alias_mapping(self):
        params = ["the person"]
        assert validate_action("look_at", params) is None
        assert params[0] == "person"

    def test_look_at_speaker_alias(self):
        params = ["speaker"]
        assert validate_action("look_at", params) is None
        assert params[0] == "person"

    def test_look_at_monitor_alias(self):
        params = ["monitor"]
        assert validate_action("look_at", params) is None
        assert params[0] == "screen"

    def test_look_at_straight_alias(self):
        params = ["straight"]
        assert validate_action("look_at", params) is None
        assert params[0] == "center"

    def test_look_at_unknown_multi_word_defaults_to_center(self):
        """Unknown multi-word directions gracefully default to center."""
        params = ["the kitchen sink"]
        err = validate_action("look_at", params)
        assert err is None
        assert params[0] == "center"

    def test_look_at_multi_word_extracts_known_direction(self):
        """Multi-word directions containing a known keyword extract it."""
        params = ["the coffee mug on the desk"]
        err = validate_action("look_at", params)
        assert err is None
        assert params[0] == "desk"

    def test_wait_clamps_to_max(self):
        params = [300]
        assert validate_action("wait", params) is None
        assert params[0] == 120

    def test_wait_rejects_negative(self):
        err = validate_action("wait", [-5])
        assert err is not None
        assert "positive" in err.lower()

    def test_wait_rejects_zero(self):
        err = validate_action("wait", [0])
        assert err is not None
        assert "positive" in err.lower()

    def test_remember_valid(self):
        assert validate_action("remember", ["mood", "happy"]) is None

    def test_remember_rejects_non_strings(self):
        err = validate_action("remember", [42, "val"])
        assert err is not None
        assert "two strings" in err.lower()

    def test_think_rejects_non_string(self):
        err = validate_action("think", [123])
        assert err is not None
        assert "string" in err.lower()

    def test_zero_arg_actions_valid(self):
        for action in ("scan", "nod", "observe", "attend"):
            assert validate_action(action, []) is None


# ---------------------------------------------------------------------------
# parse_motor_output (integration)
# ---------------------------------------------------------------------------

class TestParseMotorOutput:
    def test_simple_say(self):
        out = parse_motor_output('say("Hello")')
        assert out.valid is True
        assert out.action == "say"
        assert out.params == ["Hello"]

    def test_empty_response(self):
        out = parse_motor_output("")
        assert out.valid is False
        assert out.error == "Empty response"

    def test_whitespace_only(self):
        out = parse_motor_output("   \n  ")
        assert out.valid is False
        assert out.error == "Empty response"

    def test_scan_no_args(self):
        out = parse_motor_output("scan()")
        assert out.valid is True
        assert out.action == "scan"
        assert out.params == []

    def test_think_via_code_block(self):
        out = parse_motor_output('```lua\nthink("I wonder...")\n```')
        assert out.valid is True
        assert out.action == "think"
        assert out.params == ["I wonder..."]

    def test_bare_short_string_becomes_think(self):
        out = parse_motor_output("Hmm, interesting")
        assert out.valid is True
        assert out.action == "think"
        assert "interesting" in out.params[0]

    def test_bare_quoted_string_becomes_think(self):
        out = parse_motor_output('"Something on my mind"')
        assert out.valid is True
        assert out.action == "think"
        assert out.params[0] == "Something on my mind"

    def test_invalid_action_propagates_error(self):
        out = parse_motor_output('dance("funky")')
        assert out.valid is False
        assert out.error is not None

    def test_raw_response_preserved(self):
        raw = 'say("test")'
        out = parse_motor_output(raw)
        assert out.raw_response == raw

    def test_raw_lua_preserved(self):
        out = parse_motor_output('say("test")')
        assert out.raw_lua == 'say("test")'

    def test_with_think_tags_and_lua(self):
        response = '<think>Deciding what to say...</think>\nsay("Greetings!")'
        out = parse_motor_output(response)
        assert out.valid is True
        assert out.action == "say"
        assert out.params == ["Greetings!"]

    def test_remember_two_args(self):
        out = parse_motor_output('remember("user_name", "Alice")')
        assert out.valid is True
        assert out.action == "remember"
        assert out.params == ["user_name", "Alice"]

    def test_wait_with_float(self):
        out = parse_motor_output("wait(3.5)")
        assert out.valid is True
        assert out.action == "wait"
        assert out.params == [3.5]

    def test_look_at_with_alias_in_full_parse(self):
        out = parse_motor_output('look_at("speaker")')
        assert out.valid is True
        assert out.action == "look_at"
        assert out.params == ["person"]

    def test_assistant_pattern_rejected_in_full_parse(self):
        out = parse_motor_output('say("How can I help you today?")')
        assert out.valid is False
        assert "assistant" in out.error.lower()

    def test_motor_output_defaults(self):
        out = MotorOutput()
        assert out.action == ""
        assert out.params == []
        assert out.raw_lua == ""
        assert out.valid is False
        assert out.error is None
        assert out.raw_response == ""


# ---------------------------------------------------------------------------
# Phase 3 actions: map_room, goal, complete_goal
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPhase3Actions:
    def test_map_room_valid(self):
        out = parse_motor_output("map_room()")
        assert out.valid is True
        assert out.action == "map_room"

    def test_goal_with_description(self):
        out = parse_motor_output('goal("observe the desk area")')
        assert out.valid is True
        assert out.action == "goal"
        assert out.params[0] == "observe the desk area"

    def test_goal_with_priority(self):
        out = parse_motor_output('goal("check the door", 5)')
        assert out.valid is True
        assert out.params[0] == "check the door"
        assert out.params[1] == 5

    def test_goal_with_string_priority(self):
        """LLMs sometimes output goal("desc", "high") — should convert gracefully."""
        out = parse_motor_output('goal("investigate the noise", "high")')
        assert out.valid is True
        assert out.params[0] == "investigate the noise"
        assert out.params[1] == 5  # "high" -> 5

    def test_goal_with_unknown_string_priority(self):
        """Unknown string priority defaults to 3."""
        out = parse_motor_output('goal("check door", "important")')
        assert out.valid is True
        assert out.params[1] == 3

    def test_goal_rejects_non_string(self):
        out = parse_motor_output("goal(42)")
        assert out.valid is False

    def test_complete_goal_no_args(self):
        out = parse_motor_output("complete_goal()")
        assert out.valid is True
        assert out.action == "complete_goal"

    def test_complete_goal_with_description(self):
        out = parse_motor_output('complete_goal("check the door")')
        assert out.valid is True
        assert out.params[0] == "check the door"

    def test_new_actions_in_valid_actions(self):
        assert "map_room" in VALID_ACTIONS
        assert "goal" in VALID_ACTIONS
        assert "complete_goal" in VALID_ACTIONS


# ---------------------------------------------------------------------------
# Phase 4 actions: note_about_self, recall
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPhase4Actions:
    def test_note_about_self_valid(self):
        out = parse_motor_output('note_about_self("I like mornings")')
        assert out.valid is True
        assert out.action == "note_about_self"
        assert out.params[0] == "I like mornings"

    def test_note_about_self_rejects_non_string(self):
        out = parse_motor_output("note_about_self(42)")
        assert out.valid is False

    def test_recall_valid(self):
        out = parse_motor_output('recall("meeting schedule")')
        assert out.valid is True
        assert out.action == "recall"
        assert out.params[0] == "meeting schedule"

    def test_recall_rejects_non_string(self):
        out = parse_motor_output("recall(42)")
        assert out.valid is False

    def test_new_v4_actions_in_valid_actions(self):
        assert "note_about_self" in VALID_ACTIONS
        assert "recall" in VALID_ACTIONS


# ---------------------------------------------------------------------------
# Aliveness actions: progress_goal, head_shake, double_take, curious_tilt
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAlivenessActions:
    def test_progress_goal_valid(self):
        out = parse_motor_output('progress_goal(0.5)')
        assert out.valid is True
        assert out.action == "progress_goal"
        assert out.params[0] == 0.5

    def test_progress_goal_with_note(self):
        out = parse_motor_output('progress_goal(0.7, "checked east side")')
        assert out.valid is True
        assert out.params[0] == 0.7
        assert out.params[1] == "checked east side"

    def test_progress_goal_clamps_value(self):
        out = parse_motor_output('progress_goal(1.5)')
        assert out.valid is True
        assert out.params[0] == 1.0

    def test_progress_goal_rejects_non_number(self):
        out = parse_motor_output('progress_goal("half")')
        assert out.valid is False

    def test_head_shake_valid(self):
        out = parse_motor_output('head_shake()')
        assert out.valid is True
        assert out.action == "head_shake"

    def test_double_take_valid(self):
        out = parse_motor_output('double_take()')
        assert out.valid is True
        assert out.action == "double_take"

    def test_curious_tilt_valid(self):
        out = parse_motor_output('curious_tilt()')
        assert out.valid is True
        assert out.action == "curious_tilt"

    def test_new_aliveness_actions_in_valid_actions(self):
        assert "progress_goal" in VALID_ACTIONS
        assert "head_shake" in VALID_ACTIONS
        assert "double_take" in VALID_ACTIONS
        assert "curious_tilt" in VALID_ACTIONS
