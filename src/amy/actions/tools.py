# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tool dispatch for LLM-driven camera control.

Uses the SensorNode interface instead of BCC950Controller directly.
The commander's primary_camera node is used for PTZ operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..commander import Commander

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "pan_camera",
            "description": "Pan the camera left or right for a specified duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["left", "right"],
                        "description": "Direction to pan.",
                    },
                    "duration": {
                        "type": "number",
                        "description": "How long to pan in seconds (0.1 to 5.0).",
                        "default": 0.3,
                    },
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tilt_camera",
            "description": "Tilt the camera up or down for a specified duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "Direction to tilt.",
                    },
                    "duration": {
                        "type": "number",
                        "description": "How long to tilt in seconds (0.1 to 5.0).",
                        "default": 0.3,
                    },
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_camera",
            "description": "Combined pan and tilt movement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pan_dir": {
                        "type": "integer",
                        "enum": [-1, 0, 1],
                        "description": "-1 for left, 0 for none, 1 for right.",
                    },
                    "tilt_dir": {
                        "type": "integer",
                        "enum": [-1, 0, 1],
                        "description": "-1 for down, 0 for none, 1 for up.",
                    },
                    "duration": {
                        "type": "number",
                        "description": "Movement duration in seconds.",
                        "default": 0.3,
                    },
                },
                "required": ["pan_dir", "tilt_dir"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_camera_status",
            "description": "Get the camera's current estimated position.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reset_camera",
            "description": "Reset the camera to its default center position.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def dispatch_tool_call(commander: Commander, name: str, args: dict) -> dict:
    """Execute a tool call via the commander's primary camera node."""
    node = commander.primary_camera
    if node is None:
        return {"status": "error", "message": "No camera connected"}

    pos = node.get_position()

    if name == "pan_camera":
        duration = float(args.get("duration", 0.3))
        pan_dir = -1 if args["direction"] == "left" else 1
        pan_moved, _ = node.move(pan_dir, 0, duration)
        return {
            "status": "ok",
            "action": f"panned {args['direction']} for {duration}s",
            "moved": pan_moved,
            "at_limit": not pan_moved,
            "can_pan_left": pos.can_pan_left,
            "can_pan_right": pos.can_pan_right,
        }

    elif name == "tilt_camera":
        duration = float(args.get("duration", 0.3))
        tilt_dir = 1 if args["direction"] == "up" else -1
        _, tilt_moved = node.move(0, tilt_dir, duration)
        return {
            "status": "ok",
            "action": f"tilted {args['direction']} for {duration}s",
            "moved": tilt_moved,
            "at_limit": not tilt_moved,
            "can_tilt_up": pos.can_tilt_up,
            "can_tilt_down": pos.can_tilt_down,
        }

    elif name == "move_camera":
        pan_moved, tilt_moved = node.move(
            int(args["pan_dir"]),
            int(args["tilt_dir"]),
            float(args.get("duration", 0.3)),
        )
        return {
            "status": "ok",
            "pan_moved": pan_moved,
            "tilt_moved": tilt_moved,
            "can_pan_left": pos.can_pan_left,
            "can_pan_right": pos.can_pan_right,
            "can_tilt_up": pos.can_tilt_up,
            "can_tilt_down": pos.can_tilt_down,
        }

    elif name == "get_camera_status":
        return {
            "pan": pos.pan,
            "tilt": pos.tilt,
            "zoom": pos.zoom,
            "can_pan_left": pos.can_pan_left,
            "can_pan_right": pos.can_pan_right,
            "can_tilt_up": pos.can_tilt_up,
            "can_tilt_down": pos.can_tilt_down,
        }

    elif name == "reset_camera":
        node.reset_position()
        return {"status": "ok"}

    return {"status": "error", "message": f"Unknown tool: {name}"}
