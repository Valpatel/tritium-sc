"""Lua motor parser for Amy's consciousness layers.

Parses LLM responses to extract and validate Lua-style function calls
that drive Amy's embodied actions.

Amy's thoughts and actions are expressed as simple Lua function calls:
    say("Hello!")       -- speak aloud
    think("Hmm...")     -- internal thought (not spoken)
    look_at("person")   -- direct camera
    scan()              -- resume idle scanning
    nod()               -- acknowledgment gesture
    observe()           -- trigger deep vision analysis
    remember("k", "v")  -- store in long-term memory
    wait(5)             -- pause thinking for N seconds
    attend()            -- focus on current speaker

No Lua runtime needed -- regex parsing only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Amy's valid actions
# ---------------------------------------------------------------------------

VALID_ACTIONS: dict[str, tuple[int, int, list[type]]] = {
    "say":            (1, 1, [str]),
    "think":          (1, 1, [str]),
    "look_at":        (1, 1, [str]),
    "scan":           (0, 0, []),
    "nod":            (0, 0, []),
    "observe":        (0, 0, []),
    "remember":       (2, 2, [str, str]),
    "wait":           (1, 1, [float]),
    "attend":         (0, 0, []),
    "map_room":       (0, 0, []),
    "goal":           (1, 2, [str, int]),
    "complete_goal":  (0, 1, [str]),
    "note_about_self": (1, 1, [str]),
    "recall":          (1, 1, [str]),
    "progress_goal":   (1, 2, [float, str]),
    "head_shake":      (0, 0, []),
    "double_take":     (0, 0, []),
    "curious_tilt":    (0, 0, []),
    "save_photo":      (1, 1, [str]),
    "recall_transcript": (1, 1, [str]),
    "save_observation": (1, 1, [str]),
    "dispatch":          (3, 3, [str, float, float]),
    "alert":             (2, 2, [str, str]),
    "patrol":            (2, 2, [str, str]),
    "escalate":          (2, 2, [str, str]),
    "clear_threat":      (1, 1, [str]),
}

VALID_DIRECTIONS = {
    "person", "left", "right", "up", "down",
    "desk", "door", "window", "screen", "center",
    "far_left", "far_right", "recall",
}

_ACTION_NAMES = "|".join(VALID_ACTIONS.keys())


# ---------------------------------------------------------------------------
# MotorOutput dataclass
# ---------------------------------------------------------------------------

@dataclass
class MotorOutput:
    """Result of parsing a motor cortex LLM response."""

    action: str = ""
    params: list[Any] = field(default_factory=list)
    raw_lua: str = ""
    valid: bool = False
    error: str | None = None
    raw_response: str = ""


# ---------------------------------------------------------------------------
# Lua extraction and parsing
# ---------------------------------------------------------------------------

def extract_lua_from_response(response: str) -> str:
    """Extract Lua code from an LLM response."""
    response = response.strip()

    # Strip thinking tags (DeepSeek-R1, QwQ, etc.)
    think_pattern = r'<think>.*?</think>\s*'
    response = re.sub(think_pattern, '', response, flags=re.DOTALL | re.IGNORECASE)

    if '<think>' in response.lower():
        think_start = response.lower().find('<think>')
        response = response[:think_start].strip()

    response = response.strip()

    # Try to extract from ```lua code block
    lua_block = re.search(r'```(?:lua)?\s*\n?(.*?)\n?```', response, re.DOTALL | re.IGNORECASE)
    if lua_block:
        return lua_block.group(1).strip()

    # Try to find a bare function call
    func_pattern = rf'({_ACTION_NAMES})\s*\([^)]*\)'
    matches = list(re.finditer(func_pattern, response, re.IGNORECASE))
    if matches:
        return matches[0].group(0)

    # Auto-complete truncated say/think output
    for action in ("say", "think"):
        truncated = re.match(rf'^{action}\s*\(\s*["\'](.{{1,200}})$', response, re.IGNORECASE)
        if truncated:
            text = truncated.group(1)
            return f'{action}("{text}")'

    return response


def parse_lua_string(s: str) -> str | None:
    """Parse a Lua string literal, handling quotes and escapes."""
    s = s.strip()
    for q in ('"', "'"):
        if s.startswith(q) and s.endswith(q) and len(s) >= 2:
            inner = s[1:-1]
            inner = inner.replace(f'\\{q}', q)
            inner = inner.replace('\\n', '\n')
            inner = inner.replace('\\t', '\t')
            inner = inner.replace('\\\\', '\\')
            return inner
    return None


def parse_lua_number(s: str) -> float | int | None:
    s = s.strip()
    try:
        return float(s) if '.' in s else int(s)
    except ValueError:
        return None


def parse_lua_value(s: str) -> Any:
    """Parse a single Lua value (string, number, boolean, nil, identifier)."""
    s = s.strip()

    str_val = parse_lua_string(s)
    if str_val is not None:
        return str_val

    num_val = parse_lua_number(s)
    if num_val is not None:
        return num_val

    low = s.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    if low == 'nil':
        return None

    if re.match(r'^[a-zA-Z_][a-zA-Z_0-9]*$', s):
        return s

    return s


def split_arguments(args_str: str) -> list[str]:
    """Split Lua function arguments, respecting quoted strings."""
    args: list[str] = []
    current: list[str] = []
    in_string = False
    string_char: str | None = None
    escape_next = False

    for char in args_str:
        if escape_next:
            current.append(char)
            escape_next = False
            continue

        if char == '\\':
            current.append(char)
            escape_next = True
            continue

        if char in '"\'':
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
                string_char = None
            current.append(char)
            continue

        if char == ',' and not in_string:
            arg = ''.join(current).strip()
            if arg:
                args.append(arg)
            current = []
            continue

        current.append(char)

    arg = ''.join(current).strip()
    if arg:
        args.append(arg)

    return args


def parse_function_call(lua_code: str) -> tuple[str, list[Any]] | None:
    """Parse a Lua function call into (name, [args])."""
    lua_code = lua_code.strip()

    match = re.match(r'^([a-z_][a-z_0-9]*)\s*\((.*)\)$', lua_code,
                     re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    func_name = match.group(1).lower()
    args_str = match.group(2).strip()

    if not args_str:
        return (func_name, [])

    arg_strings = split_arguments(args_str)
    args = [parse_lua_value(arg) for arg in arg_strings]

    return (func_name, args)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_action(action: str, params: list[Any]) -> str | None:
    """Validate an action and its parameters. Returns error string or None."""
    if action not in VALID_ACTIONS:
        valid_names = ", ".join(sorted(VALID_ACTIONS.keys()))
        return f"Unknown action '{action}'. Valid: {valid_names}"

    min_params, max_params, _ = VALID_ACTIONS[action]
    n = len(params)

    if n < min_params:
        return f"'{action}' requires at least {min_params} param(s), got {n}"
    if n > max_params:
        return f"'{action}' accepts at most {max_params} param(s), got {n}"

    if action == "say" and params:
        if not isinstance(params[0], str):
            return f"say() requires a string, got {type(params[0]).__name__}"
        msg_lower = params[0].lower()
        assistant_patterns = [
            "how can i assist", "how can i help", "help you today",
            "what can i do for you", "is there anything",
            "how may i", "i'm here to help", "i'd be happy to help",
        ]
        if any(p in msg_lower for p in assistant_patterns):
            return "Rejected: assistant-style response"
        bad_patterns = [
            "actions:", "action:", "- say(", "- think(", "say(\"", "think(\"",
        ]
        if any(p in msg_lower for p in bad_patterns):
            return "Rejected: contains code/prompt fragment"
        if "\n" in params[0]:
            return "Rejected: multi-line output"

    if action == "think" and params:
        if not isinstance(params[0], str):
            return f"think() requires a string, got {type(params[0]).__name__}"

    if action == "look_at" and params:
        if not isinstance(params[0], str):
            return f"look_at() requires a string direction, got {type(params[0]).__name__}"
        direction = params[0].lower().strip()
        params[0] = direction
        if direction not in VALID_DIRECTIONS:
            direction_map = {
                "the person": "person", "speaker": "person",
                "them": "person", "user": "person",
                "the desk": "desk", "the door": "door",
                "the window": "window", "the screen": "screen",
                "monitor": "screen", "computer": "screen",
                "straight": "center", "ahead": "center",
                "forward": "center", "front": "center",
            }
            if direction in direction_map:
                params[0] = direction_map[direction]
            elif " " in direction:
                # Multi-word direction — try to extract a known direction keyword
                matched = None
                for valid_dir in VALID_DIRECTIONS:
                    if valid_dir in direction:
                        matched = valid_dir
                        break
                params[0] = matched or "center"

    if action == "wait" and params:
        if not isinstance(params[0], (int, float)) or params[0] <= 0:
            return "wait() requires a positive number of seconds"
        if params[0] > 120:
            params[0] = 120

    if action == "remember" and params:
        if not isinstance(params[0], str) or not isinstance(params[1], str):
            return "remember() requires two strings (key, value)"

    if action == "goal" and params:
        if not isinstance(params[0], str):
            return "goal() requires a string description"
        if len(params) > 1:
            if isinstance(params[1], (int, float)):
                params[1] = max(1, min(5, int(params[1])))
            elif isinstance(params[1], str):
                # LLMs sometimes output "high", "low", etc. — convert gracefully
                priority_map = {"high": 5, "medium": 3, "low": 1, "urgent": 5, "normal": 3}
                params[1] = priority_map.get(params[1].lower(), 3)
            else:
                params[1] = 3  # Default priority

    if action == "complete_goal" and params:
        if not isinstance(params[0], str):
            return "complete_goal() description must be a string"

    if action == "note_about_self" and params:
        if not isinstance(params[0], str):
            return "note_about_self() requires a string"

    if action == "recall" and params:
        if not isinstance(params[0], str):
            return "recall() requires a string query"

    if action == "save_photo" and params:
        if not isinstance(params[0], str):
            return "save_photo() requires a string reason"

    if action == "recall_transcript" and params:
        if not isinstance(params[0], str):
            return "recall_transcript() requires a string query"

    if action == "save_observation" and params:
        if not isinstance(params[0], str):
            return "save_observation() requires a string description"

    if action == "progress_goal" and params:
        if not isinstance(params[0], (int, float)):
            return "progress_goal() requires a number (0.0-1.0)"
        params[0] = max(0.0, min(1.0, float(params[0])))
        if len(params) > 1 and not isinstance(params[1], str):
            return "progress_goal() note must be a string"

    if action == "dispatch" and params:
        if not isinstance(params[0], str):
            return "dispatch() requires a string target_id"
        if not isinstance(params[1], (int, float)):
            return "dispatch() x must be a number"
        if not isinstance(params[2], (int, float)):
            return "dispatch() y must be a number"
        params[1] = max(-30.0, min(30.0, float(params[1])))
        params[2] = max(-30.0, min(30.0, float(params[2])))

    if action == "alert" and params:
        if not isinstance(params[0], str):
            return "alert() requires a string target_id"
        if not isinstance(params[1], str):
            return "alert() requires a string message"

    if action == "patrol" and params:
        if not isinstance(params[0], str):
            return "patrol() requires a string target_id"
        if not isinstance(params[1], str):
            return "patrol() requires a JSON waypoints string"
        import json as _json
        try:
            wps = _json.loads(params[1])
            if not isinstance(wps, list) or len(wps) < 1:
                return "patrol() waypoints must be a non-empty JSON array"
            for i, wp in enumerate(wps):
                if not isinstance(wp, (list, tuple)) or len(wp) != 2:
                    return f"patrol() waypoint {i} must be [x, y]"
                if not isinstance(wp[0], (int, float)) or not isinstance(wp[1], (int, float)):
                    return f"patrol() waypoint {i} must contain numbers"
        except (ValueError, TypeError):
            return "patrol() waypoints must be valid JSON"

    if action == "escalate" and params:
        if not isinstance(params[0], str):
            return "escalate() requires a string target_id"
        if not isinstance(params[1], str):
            return "escalate() requires a string level"
        valid_levels = ("unknown", "suspicious", "hostile")
        if params[1] not in valid_levels:
            return f"escalate() level must be one of: {', '.join(valid_levels)}"

    if action == "clear_threat" and params:
        if not isinstance(params[0], str):
            return "clear_threat() requires a string target_id"

    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_motor_output(response: str) -> MotorOutput:
    """Parse and validate an LLM response as Amy's motor output."""
    result = MotorOutput(raw_response=response)

    if not response or not response.strip():
        result.error = "Empty response"
        return result

    lua_code = extract_lua_from_response(response)
    result.raw_lua = lua_code

    if not lua_code:
        result.error = "Could not extract Lua code from response"
        return result

    parsed = parse_function_call(lua_code)

    if parsed is None:
        stripped = lua_code.strip()
        if stripped and len(stripped) < 200:
            if (stripped.startswith('"') and stripped.endswith('"')) or \
               (stripped.startswith("'") and stripped.endswith("'")):
                stripped = stripped[1:-1]
            if stripped:
                result.action = "think"
                result.params = [stripped]
                result.valid = True
                return result

        result.error = f"Invalid Lua syntax: {lua_code[:80]}"
        return result

    action, params = parsed
    result.action = action
    result.params = params

    error = validate_action(action, params)
    if error:
        result.error = error
        return result

    result.valid = True
    return result


def format_motor_output(output: MotorOutput) -> str:
    """Format a MotorOutput as a human-readable string."""
    if not output.valid:
        return f"INVALID: {output.error}"
    params_str = ", ".join(repr(p) for p in output.params)
    return f"{output.action}({params_str})"
