# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
LLM Client -- Ollama API wrapper for hostile agent decision-making.

Uses local LLM (qwen2.5:7b by default) via Ollama's HTTP API.
Falls back to a random action if Ollama is unreachable.
"""

import random

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Fallback actions when LLM is unavailable
FALLBACK_ACTIONS = [
    "ADVANCE toward the target",
    "FLANK to the side",
    "HIDE and wait for an opening",
    "ATTACK the nearest defender",
    "ADVANCE carefully",
]


class LLMClient:
    """Wrapper around Ollama's /api/generate endpoint."""

    def __init__(self, host: str = "http://localhost:11434",
                 model: str = "qwen2.5:7b", timeout: float = 10.0):
        self.host = host.rstrip('/')
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        """Send prompt to Ollama and return the response text.

        Falls back to a random action string if the LLM is unreachable.
        """
        if not HAS_REQUESTS:
            return random.choice(FALLBACK_ACTIONS)

        try:
            resp = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.8,
                        "num_predict": 64,
                    },
                },
                timeout=self.timeout,
            )
            if resp.ok:
                data = resp.json()
                return data.get("response", random.choice(FALLBACK_ACTIONS))
            else:
                return random.choice(FALLBACK_ACTIONS)
        except Exception:
            return random.choice(FALLBACK_ACTIONS)
