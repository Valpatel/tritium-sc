# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Multi-action Lua parser for compound behavior sequences.

Extends the single-action lua_motor parser to handle multiple Lua
function calls in a single LLM response. Enables Amy and robots to
generate compound behaviors like:

    escalate("h-1", "hostile")
    dispatch("rover-01", 5.0, 10.0)
    battle_cry("Contact!")

Validates the full sequence before execution.
"""
from __future__ import annotations

import re
from typing import Any

from .lua_motor import (  # same subpackage
    MotorOutput,
    extract_lua_from_response,
    parse_function_call,
    validate_action,
    VALID_ACTIONS,
)

# Maximum actions in a single sequence
MAX_SEQUENCE_LENGTH = 10

# Maximum speech actions per sequence
MAX_SAY_PER_SEQUENCE = 1

# Pattern to match Lua function calls
_ACTION_NAMES = "|".join(VALID_ACTIONS.keys())
_FUNC_PATTERN = re.compile(
    rf'({_ACTION_NAMES})\s*\([^)]*\)',
    re.IGNORECASE,
)


def extract_multi_actions(response: str) -> list[str]:
    """Extract multiple Lua function calls from an LLM response.

    Handles:
    - Newline-separated calls
    - Code blocks (```lua ... ```)
    - Mixed text and code
    - Comments (-- ...)
    - Think tags (<think>...</think>)

    Returns list of individual Lua function call strings.
    """
    if not response or not response.strip():
        return []

    response = response.strip()

    # Strip thinking tags
    think_pattern = r'<think>.*?</think>\s*'
    response = re.sub(think_pattern, '', response, flags=re.DOTALL | re.IGNORECASE)

    # Handle unclosed think tags
    if '<think>' in response.lower():
        think_start = response.lower().find('<think>')
        response = response[:think_start].strip()

    # Extract from code blocks first
    lua_block = re.search(r'```(?:lua)?\s*\n?(.*?)\n?```', response, re.DOTALL | re.IGNORECASE)
    if lua_block:
        response = lua_block.group(1)

    # Remove Lua comments
    lines = []
    for line in response.split('\n'):
        stripped = line.strip()
        if stripped.startswith('--'):
            continue
        # Remove inline comments
        comment_idx = stripped.find('--')
        if comment_idx > 0:
            stripped = stripped[:comment_idx].strip()
        if stripped:
            lines.append(stripped)

    # Find all function calls
    text = '\n'.join(lines)
    matches = list(_FUNC_PATTERN.finditer(text))

    if not matches:
        return []

    # Extract the full function call for each match
    result = []
    for match in matches:
        start = match.start()
        # Find the closing paren
        depth = 0
        i = start
        while i < len(text):
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
                if depth == 0:
                    result.append(text[start:i + 1])
                    break
            i += 1

    return result


def parse_multi_actions(response: str) -> list[MotorOutput]:
    """Parse and validate multiple Lua actions from one response.

    Returns a list of MotorOutput objects, one per action found.
    Invalid actions are included with valid=False and an error message.
    """
    calls = extract_multi_actions(response)

    if not calls:
        return []

    results = []
    for call in calls:
        output = MotorOutput(raw_response=call, raw_lua=call)
        parsed = parse_function_call(call)

        if parsed is None:
            output.error = f"Invalid Lua syntax: {call[:80]}"
            results.append(output)
            continue

        action, params = parsed
        output.action = action
        output.params = params

        error = validate_action(action, params)
        if error:
            output.error = error
        else:
            output.valid = True

        results.append(output)

    return results


def validate_action_sequence(actions: list[MotorOutput]) -> list[str]:
    """Validate a sequence of actions for safety and sanity.

    Returns list of error strings. Empty list = valid sequence.
    """
    errors: list[str] = []

    if not actions:
        return errors

    # Check sequence length
    if len(actions) > MAX_SEQUENCE_LENGTH:
        errors.append(
            f"Sequence too long: {len(actions)} actions "
            f"(max {MAX_SEQUENCE_LENGTH})"
        )

    # Check for invalid actions
    invalid = [a for a in actions if not a.valid]
    if invalid:
        for a in invalid:
            errors.append(f"Invalid action: {a.error}")

    # Check speech limit
    say_count = sum(1 for a in actions if a.action == "say")
    if say_count > MAX_SAY_PER_SEQUENCE:
        errors.append(
            f"Too many say() actions: {say_count} "
            f"(max {MAX_SAY_PER_SEQUENCE})"
        )

    return errors
