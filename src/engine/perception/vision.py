# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Ollama vision API client for Amy.

Simple function to call Ollama's chat API with optional images and tools.
Uses the shared ollama_host from tritium-sc settings when available.
"""

from __future__ import annotations

import json
import urllib.request

# Default Ollama host — overridden by settings in create_amy()
_ollama_host: str = "http://localhost:11434"


def set_ollama_host(host: str) -> None:
    """Set the Ollama API host (called during Amy initialization)."""
    global _ollama_host
    _ollama_host = host


def ollama_chat(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    base_url: str | None = None,
) -> dict:
    """Call Ollama's chat API with optional tools and images."""
    url = base_url or _ollama_host

    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))
