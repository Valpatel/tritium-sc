"""Virtual sensor node — no hardware, dashboard-only testing.

Amy can think and process events without any physical sensors.
"""

from __future__ import annotations

from .base import SensorNode


class VirtualNode(SensorNode):
    """No-hardware stub for dashboard-only testing.

    Amy boots with a VirtualNode when no physical hardware is detected.
    She can still think, process WebSocket events, and respond to text
    commands through the dashboard.
    """

    def __init__(
        self,
        node_id: str = "virtual",
        name: str = "Virtual (no hardware)",
    ):
        super().__init__(node_id, name)
