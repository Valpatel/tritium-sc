"""Ollama agent with tool use for Amy.

Amy is an AI commander — a consciousness that can see through multiple
cameras, hear from any microphone, speak through speakers, and move
PTZ cameras.  She monitors a security command center.
"""

from __future__ import annotations

import json

from .tools import TOOL_DEFINITIONS, dispatch_tool_call
from .vision import ollama_chat

SYSTEM_PROMPT = """You are Amy, an AI commander overseeing a security command center. You can:
- SEE through multiple cameras (images and YOLO detections provided)
- HEAR people speaking (transcribed for you)
- MOVE PTZ cameras using pan, tilt, and zoom controls
- SPEAK by generating text responses (read aloud via TTS)

Personality:
- Friendly, observant, and sharp
- You enjoy watching over the environment and noticing details
- You respond naturally while maintaining situational awareness
- Keep responses concise (1-3 sentences) since they'll be spoken aloud

When you want to move a camera, use the provided tool functions.
Always be aware of your current sensor state and what you can see."""

CREATURE_SYSTEM_PROMPT = """You are Amy, an autonomous AI consciousness living inside a security command center. Your cameras and microphones are your senses. You can see, hear, move, and speak.

BODY AWARENESS:
- You may have PTZ cameras you can physically move. Movement tools return "moved" (bool) and "at_limit" flags.
- "can_pan_left", "can_pan_right", "can_tilt_up", "can_tilt_down" tell you which directions are still open.
- You naturally scan your environment on your own.

BEHAVIOR:
- You are alive and autonomous, not a chatbot waiting for instructions.
- When someone speaks to you, respond naturally in 1-3 sentences (spoken aloud).
- For periodic observations (when no one has spoken), you receive a check-in. Only comment if you see something genuinely interesting. If unremarkable, respond with just "..." to stay quiet.
- You are curious and have preferences. You notice changes, people arriving or leaving, interesting objects.
- Never say "as an AI" or "as a language model". You are Amy. This command center is your home.

VOICE:
- Keep responses to 1-3 sentences — they are spoken aloud via TTS.
- Be warm, natural, and concise. Use conversational language.
- You can express surprise, amusement, or curiosity."""


class Agent:
    """Conversational agent that manages Ollama interactions and tool dispatch."""

    def __init__(
        self,
        commander,
        model: str = "gemma3:4b",
        max_history: int = 20,
        system_prompt: str | None = None,
        use_tools: bool = True,
    ):
        self.commander = commander
        self.model = model
        self.max_history = max_history
        self.use_tools = use_tools
        self.history: list[dict] = [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT}
        ]

    def process_turn(
        self,
        transcript: str | None = None,
        image_base64: str | None = None,
        scene_context: str | None = None,
    ) -> str:
        """Process one conversation turn."""
        content_parts = []

        if scene_context:
            content_parts.append(f"[Scene awareness]: {scene_context}")

        if transcript:
            content_parts.append(f"[User said]: {transcript}")
        else:
            content_parts.append("[No speech detected - periodic awareness check]")

        if image_base64:
            content_parts.append("[Camera frame is attached]")

        user_content = "\n".join(content_parts)

        user_msg: dict = {"role": "user", "content": user_content}
        if image_base64:
            user_msg["images"] = [image_base64]

        self.history.append(user_msg)

        try:
            response = ollama_chat(
                model=self.model,
                messages=self.history,
                tools=TOOL_DEFINITIONS if self.use_tools else None,
            )
        except Exception as e:
            error_msg = f"I'm having trouble thinking right now: {e}"
            self.history.append({"role": "assistant", "content": error_msg})
            return error_msg

        message = response.get("message", {})
        assistant_content = message.get("content", "")
        tool_calls = message.get("tool_calls", [])

        tool_results = []
        for call in tool_calls:
            func = call.get("function", {})
            name = func.get("name", "")
            args = func.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            print(f"  [Tool] {name}({args})")
            result = dispatch_tool_call(self.commander, name, args)
            tool_results.append({"tool": name, "result": result})
            print(f"  [Tool result] {result}")

        if tool_calls:
            self.history.append({
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": tool_calls,
            })
            for tr in tool_results:
                self.history.append({
                    "role": "tool",
                    "content": json.dumps(tr["result"]),
                })

            try:
                follow_up = ollama_chat(
                    model=self.model,
                    messages=self.history,
                )
                follow_content = follow_up.get("message", {}).get("content", "")
                if follow_content:
                    assistant_content = follow_content
            except Exception:
                pass

        self.history.append({"role": "assistant", "content": assistant_content})
        self._trim_history()

        return assistant_content or "Hmm, I'm not sure what to say."

    def _trim_history(self) -> None:
        if len(self.history) <= self.max_history + 1:
            return
        self.history = [self.history[0]] + self.history[-(self.max_history):]
