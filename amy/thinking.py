"""ThinkingThread — Amy's L4 DELIBERATION layer.

A continuous background thread that reads the sensorium narrative,
calls a fast LLM to generate a Lua-structured action, and dispatches
it.  This is Amy's "inner monologue".
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from .lua_motor import parse_motor_output, format_motor_output
from .vision import ollama_chat

if TYPE_CHECKING:
    from .commander import Commander


THINKING_SYSTEM_PROMPT = """\
You are Amy's inner mind. You are an autonomous AI consciousness overseeing \
a security command center. You observe the world through cameras and \
microphones and decide what to do.

CURRENT AWARENESS:
{narrative}

MEMORY:
{memory}

RECENT THOUGHTS:
{thoughts}

Respond with ONE Lua function call. Available actions:
- say("text") -- speak aloud (only when you have something worth saying)
- think("text") -- internal thought (most common -- observe, reflect, plan)
- look_at("target") -- direct camera ("person", "left", "right", "up", "down")
- scan() -- resume idle scanning
- nod() -- acknowledge
- observe() -- look closely at the current scene (triggers deep vision)
- remember("key", "value") -- store something important
- wait(seconds) -- pause thinking
- attend() -- focus attention on current speaker

RULES:
- Most of the time, use think() -- internal reflection is free and natural.
- Only say() when you genuinely have something interesting to add.
- If the scene hasn't changed much, use wait(10) to avoid redundant thoughts.
- Never use say() for assistant-style responses like "How can I help?"
- Be curious, observant, and have your own personality.
- If someone is present, you might think about them or what they're doing.
- If alone, reflect on what you've seen, wonder about things, or plan what to look at next.
"""


class ThinkingThread:
    """Continuous thinking thread — Amy's inner monologue."""

    def __init__(
        self,
        commander: Commander,
        model: str = "gemma3:4b",
        think_interval: float = 8.0,
    ):
        self._commander = commander
        self._model = model
        self._interval = think_interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._last_thought: str = ""
        self._suppress_until: float = 0.0
        self._think_count: int = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def suppress(self, seconds: float) -> None:
        self._suppress_until = time.monotonic() + seconds

    @property
    def suppressed(self) -> bool:
        return time.monotonic() < self._suppress_until

    def _run(self) -> None:
        self._stop.wait(timeout=5.0)

        while not self._stop.is_set():
            if time.monotonic() < self._suppress_until:
                self._stop.wait(timeout=1.0)
                continue

            try:
                self._think_cycle()
            except Exception as e:
                print(f"  [thinking error: {e}]")

            self._stop.wait(timeout=self._interval)

    def _think_cycle(self) -> None:
        commander = self._commander

        narrative = commander.sensorium.narrative()

        # Get position from primary camera if available
        node = commander.primary_camera
        if node is not None and node.has_ptz:
            pos = node.get_position()
            memory_ctx = commander.memory.build_context(pan=pos.pan, tilt=pos.tilt)
        else:
            memory_ctx = commander.memory.build_context()

        recent_thoughts = commander.sensorium.recent_thoughts
        thoughts_str = "\n".join(f"- {t}" for t in recent_thoughts) if recent_thoughts else "(none yet)"

        system = THINKING_SYSTEM_PROMPT.format(
            narrative=narrative,
            memory=memory_ctx or "(no memories yet)",
            thoughts=thoughts_str,
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "What do you do next? Respond with a single Lua function call."},
        ]

        t0 = time.monotonic()
        try:
            response = ollama_chat(model=self._model, messages=messages)
        except Exception as e:
            print(f"  [thinking LLM error: {e}]")
            return

        response_text = response.get("message", {}).get("content", "").strip()
        dt = time.monotonic() - t0

        if not response_text:
            return

        result = parse_motor_output(response_text)
        self._think_count += 1

        if result.valid:
            formatted = format_motor_output(result)
            if result.action == "think":
                print(f"  [think]: {result.params[0]}")
            elif result.action == "say":
                print(f"  [thinking->say]: {result.params[0]}")
            else:
                print(f"  [thinking->{formatted}] ({dt:.1f}s)")

            self._dispatch(result)
        else:
            thought = response_text[:100]
            commander.sensorium.push("thought", thought)
            print(f"  [thinking parse error: {result.error}]")

    def _dispatch(self, result) -> None:
        commander = self._commander

        if result.action == "say":
            text = result.params[0]
            if commander._state.value == "SPEAKING":
                commander.sensorium.push("thought", f"(wanted to say: {text})")
                return
            if (time.monotonic() - commander._last_spoke) < 8:
                commander.sensorium.push("thought", f"(held back: {text})")
                return
            commander.sensorium.push("thought", f"Decided to say: {text[:60]}")
            commander.say(text)
            commander.sensorium.push("audio", f'Amy said: "{text[:60]}"')

        elif result.action == "think":
            text = result.params[0]
            self._last_thought = text
            commander.sensorium.push("thought", text)
            commander.event_bus.publish("thought", {"text": text})

        elif result.action == "look_at":
            self._handle_look_at(result.params[0])

        elif result.action == "scan":
            node = commander.primary_camera
            if node is not None and node.has_ptz:
                from .motor import auto_track
                commander.motor.set_program(
                    auto_track(node, lambda: commander.vision_thread.person_target if commander.vision_thread else None)
                )
            commander.sensorium.push("motor", "Resumed scanning")

        elif result.action == "nod":
            from .motor import nod
            commander.motor.set_program(nod())
            commander.sensorium.push("motor", "Nodded")

        elif result.action == "observe":
            commander._deep_think()
            commander.sensorium.push("thought", "Looking more closely...")

        elif result.action == "remember":
            key, value = result.params[0], result.params[1]
            commander.memory.add_event(key, value)
            commander.sensorium.push("thought", f"Remembered: {key} = {value[:40]}")

        elif result.action == "wait":
            seconds = result.params[0]
            self.suppress(seconds)
            commander.sensorium.push("thought", f"Waiting {seconds}s...")

        elif result.action == "attend":
            commander.sensorium.push("thought", "Focusing on speaker")

    def _handle_look_at(self, direction: str) -> None:
        commander = self._commander
        node = commander.primary_camera

        if node is None or not node.has_ptz:
            commander.sensorium.push("thought", "No PTZ camera to look with")
            return

        if direction == "person":
            if commander.vision_thread and commander.vision_thread.person_target:
                from .motor import track_person
                commander.motor.set_program(
                    track_person(lambda: commander.vision_thread.person_target)
                )
                commander.sensorium.push("motor", "Looking at person")
            else:
                commander.sensorium.push("thought", "No person visible to look at")
            return

        direction_moves = {
            "left":      (-1,  0),
            "right":     ( 1,  0),
            "up":        ( 0,  1),
            "down":      ( 0, -1),
            "far_left":  (-1,  0),
            "far_right": ( 1,  0),
            "center":    ( 0,  0),
        }

        if direction in direction_moves:
            pan, tilt = direction_moves[direction]
            if pan != 0 or tilt != 0:
                duration = 0.8 if "far" in direction else 0.4
                node.move(pan, tilt, duration)
            commander.sensorium.push("motor", f"Looking {direction}")
        else:
            commander.sensorium.push("motor", f"Looking toward {direction}")
