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

# Default LLM host — overridden by settings in create_amy()
# Uses llama-server (OpenAI-compatible) on port 8081 by default
_ollama_host: str = "http://localhost:8081"

# Radio detection — BLE/WiFi signal-based target detection
_RADIO_DETECTION_RANGE = 50.0  # meters — max BLE/WiFi detection range


def check_radio_detection(target: dict, sensors: list[dict]) -> dict:
    """Check if a target is detected via radio signals (BLE/WiFi).

    Computes radio_detected flag and radio_signal_strength based on
    proximity to sensor nodes with bluetooth_mac or wifi_mac matching.
    """
    radio_detected = False
    radio_signal_strength = 0.0

    tx, ty = target.get("position", (0, 0))
    target_bt = target.get("bluetooth_mac", "")
    target_wifi = target.get("wifi_mac", "")

    if not target_bt and not target_wifi:
        return {"radio_detected": False, "radio_signal_strength": 0.0}

    for sensor in sensors:
        sx, sy = sensor.get("position", (0, 0))
        dist = ((tx - sx) ** 2 + (ty - sy) ** 2) ** 0.5

        if dist <= _RADIO_DETECTION_RANGE:
            # Signal strength degrades with distance (simplified path loss)
            strength = max(0.0, 1.0 - dist / _RADIO_DETECTION_RANGE)
            if strength > radio_signal_strength:
                radio_signal_strength = strength
                radio_detected = True

    return {
        "radio_detected": radio_detected,
        "radio_signal_strength": round(radio_signal_strength, 3),
    }


def set_ollama_host(host: str) -> None:
    """Set the LLM API host (called during Amy initialization)."""
    global _ollama_host
    _ollama_host = host


def _is_llama_server(url: str) -> bool:
    """Check if the host is llama-server (not ollama) by port heuristic."""
    port = url.rstrip("/").split(":")[-1]
    return port in ("8081", "8082", "8083")


def ollama_chat(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    base_url: str | None = None,
) -> dict:
    """Call LLM chat API with optional tools and images.

    Automatically detects llama-server vs ollama by port and uses
    the correct API format:
    - llama-server: /v1/chat/completions (OpenAI-compatible)
    - ollama: /api/chat (legacy)
    """
    url = base_url or _ollama_host
    use_openai = _is_llama_server(url)

    payload: dict = {
        "model": model,
        "messages": messages,
    }
    if use_openai:
        payload["max_tokens"] = 2048
    else:
        payload["stream"] = False
    if tools:
        payload["tools"] = tools

    endpoint = "/v1/chat/completions" if use_openai else "/api/chat"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        if use_openai:
            # Convert OpenAI format to ollama format for backward compat
            choices = result.get("choices", [])
            if choices:
                return {"message": choices[0].get("message", {})}
            return {"message": {"content": ""}}
        return result
