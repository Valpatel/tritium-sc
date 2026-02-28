# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""UnitComms -- inter-unit communication signals.

Units can broadcast signals that nearby allies receive:
  - distress: "I'm under fire at position X"
  - contact: "Enemy spotted at position X"
  - regroup: "Rally to position X"

Signals have a range and expire after a TTL.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget

# Signal types
SIGNAL_DISTRESS = "distress"
SIGNAL_CONTACT = "contact"
SIGNAL_REGROUP = "regroup"

# Signal defaults
_DEFAULT_RANGE = 50.0  # meters
_DEFAULT_TTL = 10.0  # seconds


@dataclass
class Signal:
    """A communication signal broadcast by a unit."""

    signal_type: str  # distress, contact, regroup
    sender_id: str
    sender_alliance: str
    position: tuple[float, float]
    target_position: tuple[float, float] | None = None  # where the threat/contact is
    created_at: float = field(default_factory=time.time)
    ttl: float = _DEFAULT_TTL
    signal_range: float = _DEFAULT_RANGE

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


@dataclass
class Message:
    """A simple message broadcast by a unit."""

    sender_id: str
    content: str
    position: tuple[float, float]
    created_at: float = field(default_factory=time.time)
    ttl: float = _DEFAULT_TTL
    msg_range: float = _DEFAULT_RANGE

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


class UnitComms:
    """Manages inter-unit communication signals."""

    def __init__(self) -> None:
        self._signals: list[Signal] = []
        self._messages: list[Message] = []

    def send(self, sender_id: str, content: str, position: tuple[float, float]) -> Message:
        """Send a simple message from a unit.

        Args:
            sender_id: ID of the sender.
            content: Message content string.
            position: Broadcast position (x, y).

        Returns:
            The created Message.
        """
        msg = Message(sender_id=sender_id, content=content, position=position)
        self._messages.append(msg)
        return msg

    def get_messages_for(
        self,
        receiver_id: str,
        position: tuple[float, float],
        asset_type: str,
    ) -> list[Message]:
        """Return messages within comms range of the given position.

        Excludes expired messages and messages sent by the receiver itself.
        """
        results = []
        for msg in self._messages:
            if msg.expired:
                continue
            if msg.sender_id == receiver_id:
                continue
            dx = msg.position[0] - position[0]
            dy = msg.position[1] - position[1]
            dist = math.hypot(dx, dy)
            if dist <= msg.msg_range:
                results.append(msg)
        return results

    def broadcast(
        self,
        signal_type: str,
        sender_id: str,
        sender_alliance: str,
        position: tuple[float, float],
        target_position: tuple[float, float] | None = None,
        signal_range: float = _DEFAULT_RANGE,
        ttl: float = _DEFAULT_TTL,
    ) -> Signal:
        """Broadcast a signal from a unit."""
        sig = Signal(
            signal_type=signal_type,
            sender_id=sender_id,
            sender_alliance=sender_alliance,
            position=position,
            target_position=target_position,
            signal_range=signal_range,
            ttl=ttl,
        )
        self._signals.append(sig)
        return sig

    def emit_distress(
        self,
        sender_id: str,
        position: tuple[float, float],
        alliance: str,
    ) -> Signal:
        """Emit a distress signal ("I'm under fire")."""
        return self.broadcast(
            SIGNAL_DISTRESS, sender_id, alliance, position,
        )

    def emit_contact(
        self,
        sender_id: str,
        position: tuple[float, float],
        alliance: str,
        enemy_pos: tuple[float, float] | None = None,
    ) -> Signal:
        """Emit a contact signal ("enemy spotted at enemy_pos")."""
        return self.broadcast(
            SIGNAL_CONTACT, sender_id, alliance, position,
            target_position=enemy_pos,
        )

    def emit_retreat(
        self,
        sender_id: str,
        position: tuple[float, float],
        alliance: str,
    ) -> Signal:
        """Emit a retreat signal ("I'm pulling back")."""
        return self.broadcast(
            "retreat", sender_id, alliance, position,
        )

    def get_signals_for_unit(
        self,
        unit: SimulationTarget,
        signal_type: str | None = None,
    ) -> list[Signal]:
        """Return active signals within range of *unit* from same alliance.

        Optionally filter by signal_type.
        """
        results = []
        for sig in self._signals:
            if sig.expired:
                continue
            if sig.sender_alliance != unit.alliance:
                continue
            if sig.sender_id == unit.target_id:
                continue  # don't receive your own signals
            if signal_type is not None and sig.signal_type != signal_type:
                continue
            # Range check
            dx = sig.position[0] - unit.position[0]
            dy = sig.position[1] - unit.position[1]
            dist = math.hypot(dx, dy)
            if dist <= sig.signal_range:
                results.append(sig)
        return results

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Remove expired signals and messages."""
        self._signals = [s for s in self._signals if not s.expired]
        self._messages = [m for m in self._messages if not m.expired]

    def reset(self) -> None:
        """Clear all signals and messages."""
        self._signals.clear()
        self._messages.clear()
