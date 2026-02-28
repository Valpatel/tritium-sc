# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Configuration for the Graphlings plugin."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class GraphlingsConfig:
    """Configuration for graphling agent deployment in tritium-sc."""

    # Graphling home server (GB10-01 via Tailscale)
    server_url: str = "http://100.93.184.1:4774"
    server_timeout: float = 5.0

    # Deployment limits
    max_agents: int = 5

    # Decision timing
    think_interval_seconds: float = 3.0

    # Perception
    perception_radius: float = 50.0

    # Experience sync
    experience_sync_interval: float = 60.0
    heartbeat_interval: float = 300.0  # 5 minutes

    # Default deployment config
    default_context: str = "npc_game"
    default_service_name: str = "tritium-sc"
    default_consciousness_min: int = 2
    default_consciousness_max: int = 5

    # Named spawn locations
    spawn_points: dict[str, tuple[float, float]] = field(default_factory=lambda: {
        "marketplace": (100.0, 200.0),
        "watchtower": (50.0, 150.0),
        "tavern": (180.0, 220.0),
    })

    @classmethod
    def from_env(cls) -> GraphlingsConfig:
        """Load config from environment variables."""
        config = cls()
        config.server_url = os.environ.get(
            "GRAPHLINGS_SERVER_URL", config.server_url
        )
        config.server_timeout = float(
            os.environ.get("GRAPHLINGS_SERVER_TIMEOUT", config.server_timeout)
        )
        config.max_agents = int(
            os.environ.get("GRAPHLINGS_MAX_AGENTS", config.max_agents)
        )
        config.think_interval_seconds = float(
            os.environ.get("GRAPHLINGS_THINK_INTERVAL", config.think_interval_seconds)
        )
        config.perception_radius = float(
            os.environ.get("GRAPHLINGS_PERCEPTION_RADIUS", config.perception_radius)
        )
        return config
