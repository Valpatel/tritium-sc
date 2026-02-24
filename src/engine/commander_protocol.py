"""CommanderProtocol — the interface any commander plugin must implement.

This is the contract between the engine and a personality plugin.
Amy implements this. A different commander ("Bob") would implement
the same interface with different brains/personality.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.tactical.target_tracker import TargetTracker
    from engine.simulation.engine import SimulationEngine


@runtime_checkable
class CommanderProtocol(Protocol):
    """Interface every commander plugin must satisfy."""

    event_bus: EventBus
    target_tracker: TargetTracker
    simulation_engine: SimulationEngine | None
    mode: str  # "sim" or "live"

    def set_mode(self, mode: str) -> str:
        """Switch between 'sim' and 'live' mode. Returns the new mode."""
        ...

    def say(self, text: str) -> None:
        """Speak text via TTS."""
        ...

    def run(self) -> None:
        """Start the commander's main loop (blocking)."""
        ...

    def shutdown(self) -> None:
        """Gracefully stop all threads and release resources."""
        ...

    def grab_mjpeg_frame(self) -> bytes | None:
        """Return the latest camera frame as JPEG bytes, or None."""
        ...
