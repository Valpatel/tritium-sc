"""Motor programs and motor thread for autonomous camera movement.

Motor programs are generators that yield MotorCommand dataclasses.
Uses the SensorNode interface for position checks and movement.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Generator

from .nodes.base import SensorNode

MotorProgram = Generator["MotorCommand", None, None]


@dataclass
class MotorCommand:
    """A single motor step for the motor thread to execute."""

    pan_dir: int = 0       # -1 left, 0 none, 1 right
    tilt_dir: int = 0      # -1 down, 0 none, 1 up
    duration: float = 0.1  # how long to move
    pause_after: float = 0.0  # how long to pause after the move


def idle_scan(node: SensorNode) -> MotorProgram:
    """Smooth random scanning — sweeping the room."""
    pan = random.choice([-1, 1])
    while True:
        pos = node.get_position()

        roll = random.random()
        if roll < 0.50:
            if pan == -1 and not pos.can_pan_left:
                pan = 1
            elif pan == 1 and not pos.can_pan_right:
                pan = -1
            yield MotorCommand(
                pan_dir=pan,
                duration=random.uniform(0.3, 0.8),
                pause_after=random.uniform(0.2, 0.6),
            )
        elif roll < 0.75:
            tilt = random.choice([-1, 1])
            if tilt == 1 and not pos.can_tilt_up:
                tilt = -1
            elif tilt == -1 and not pos.can_tilt_down:
                tilt = 1
            if pan == -1 and not pos.can_pan_left:
                pan = 1
            elif pan == 1 and not pos.can_pan_right:
                pan = -1
            yield MotorCommand(
                pan_dir=pan,
                tilt_dir=tilt,
                duration=random.uniform(0.2, 0.5),
                pause_after=random.uniform(0.3, 0.8),
            )
        elif roll < 0.88:
            tilt = random.choice([-1, 1])
            if tilt == 1 and not pos.can_tilt_up:
                tilt = -1
            elif tilt == -1 and not pos.can_tilt_down:
                tilt = 1
            yield MotorCommand(
                tilt_dir=tilt,
                duration=random.uniform(0.1, 0.25),
                pause_after=random.uniform(0.3, 0.8),
            )
        else:
            yield MotorCommand(pause_after=random.uniform(1.0, 3.0))

        if random.random() < 0.2:
            pan = -pan


def breathe() -> MotorProgram:
    """Imperceptible micro-tilt oscillations — keeps alive."""
    while True:
        yield MotorCommand(tilt_dir=1, duration=0.05, pause_after=2.0)
        yield MotorCommand(tilt_dir=-1, duration=0.05, pause_after=2.0)


def nod() -> MotorProgram:
    """Small up-down nod for acknowledgment."""
    yield MotorCommand(tilt_dir=1, duration=0.12, pause_after=0.15)
    yield MotorCommand(tilt_dir=-1, duration=0.12, pause_after=0.15)
    yield MotorCommand(tilt_dir=1, duration=0.08, pause_after=0.1)
    yield MotorCommand(tilt_dir=-1, duration=0.08)


def search_scan(node: SensorNode) -> MotorProgram:
    """Quick wide sweeps to find the source of a sound."""
    for pan_dir in [-1, 1, -1, 1]:
        pos = node.get_position()
        if pan_dir == -1 and not pos.can_pan_left:
            pan_dir = 1
        elif pan_dir == 1 and not pos.can_pan_right:
            pan_dir = -1
        yield MotorCommand(pan_dir=pan_dir, duration=0.5, pause_after=0.4)
    pan = 1
    while True:
        pos = node.get_position()
        if pan == -1 and not pos.can_pan_left:
            pan = 1
        elif pan == 1 and not pos.can_pan_right:
            pan = -1
        yield MotorCommand(pan_dir=pan, duration=0.6, pause_after=0.3)
        pan = -pan


def track_person(target_fn) -> MotorProgram:
    """Track a person detected by YOLO — keeps camera centered.

    Uses adaptive motor speed: gentle corrections when nearly centered,
    aggressive when far off-center.
    """
    while True:
        target = target_fn()
        if target is None:
            yield MotorCommand(tilt_dir=1, duration=0.05, pause_after=0.3)
            yield MotorCommand(tilt_dir=-1, duration=0.05, pause_after=0.3)
            continue

        cx, cy = target
        pan = 0
        if cx < 0.35:
            pan = -1
        elif cx > 0.65:
            pan = 1
        tilt = 0
        if cy < 0.30:
            tilt = 1
        elif cy > 0.70:
            tilt = -1

        if pan != 0 or tilt != 0:
            offset = max(abs(cx - 0.5), abs(cy - 0.5))
            # Adaptive speed: gentle near center, aggressive at edges
            duration = 0.03 + offset * 0.35
            pause = 0.08 + (1.0 - offset) * 0.12
            yield MotorCommand(pan_dir=pan, tilt_dir=tilt, duration=duration, pause_after=pause)
        else:
            yield MotorCommand(pause_after=0.3)


def head_shake(node: SensorNode) -> MotorProgram:
    """Two pan left-right cycles — disagreement or disbelief."""
    for _ in range(2):
        pos = node.get_position()
        if pos.can_pan_left:
            yield MotorCommand(pan_dir=-1, duration=0.25, pause_after=0.1)
        if pos.can_pan_right:
            yield MotorCommand(pan_dir=1, duration=0.5, pause_after=0.1)
        if pos.can_pan_left:
            yield MotorCommand(pan_dir=-1, duration=0.25, pause_after=0.15)


def double_take(node: SensorNode) -> MotorProgram:
    """Quick pan right, slow pan left, slight tilt up — surprise."""
    pos = node.get_position()
    if pos.can_pan_right:
        yield MotorCommand(pan_dir=1, duration=0.3, pause_after=0.1)
    if pos.can_pan_left:
        yield MotorCommand(pan_dir=-1, duration=0.6, pause_after=0.2)
    if pos.can_tilt_up:
        yield MotorCommand(tilt_dir=1, duration=0.1, pause_after=0.3)


def curious_tilt() -> MotorProgram:
    """Slow tilt up, pause, small tilt down — curiosity."""
    yield MotorCommand(tilt_dir=1, duration=0.2, pause_after=0.8)
    yield MotorCommand(tilt_dir=-1, duration=0.1, pause_after=0.3)


def emphasis_look(node: SensorNode, direction: int = 1) -> MotorProgram:
    """Sharp pan in direction, return — drawing attention to something."""
    yield MotorCommand(pan_dir=direction, duration=0.4, pause_after=0.5)
    yield MotorCommand(pan_dir=-direction, duration=0.3, pause_after=0.2)


def survey_room(node: SensorNode) -> MotorProgram:
    """Systematic pan sweep for room zone discovery.

    Sweeps left to right in steps, pausing at each position
    for observation. Finite program — ends after one full sweep.
    """
    # Reset to left limit
    yield MotorCommand(pan_dir=-1, duration=2.0, pause_after=0.5)

    # Sweep right in 8 steps
    for _ in range(8):
        pos = node.get_position()
        if not pos.can_pan_right:
            break
        yield MotorCommand(pan_dir=1, duration=0.6, pause_after=2.0)

    # Sweep back to center
    yield MotorCommand(pan_dir=-1, duration=1.5, pause_after=0.5)

    # Tilt up, sweep, tilt down
    yield MotorCommand(tilt_dir=1, duration=0.4, pause_after=1.5)
    yield MotorCommand(tilt_dir=-1, duration=0.8, pause_after=1.5)


_MOOD_SPEED: dict[str, float] = {
    "calm": 0.7,
    "content": 0.7,
    "melancholy": 0.7,
    "neutral": 1.0,
    "attentive": 1.0,
    "contemplative": 0.8,
    "engaged": 1.2,
    "curious": 1.3,
    "excited": 1.5,
    "uneasy": 1.3,
}


def auto_track(
    node: SensorNode,
    target_fn,
    mood: str = "neutral",
    complexity_fn=None,
) -> MotorProgram:
    """Track person when visible, scan when not. Default behavior.

    The mood parameter scales movement speed — calm moods are slower,
    excited moods are faster.

    The complexity_fn callback returns the current frame complexity
    (0.0-1.0). When scanning (no person target), the motor dwells
    longer on complex/interesting views and passes quickly over
    blank walls.
    """
    pan_dir = random.choice([-1, 1])
    scan_hold = 0
    speed = _MOOD_SPEED.get(mood, 1.0)

    while True:
        target = target_fn()

        if target is not None:
            cx, cy = target
            pan = 0
            if cx < 0.35:
                pan = -1
            elif cx > 0.65:
                pan = 1
            tilt = 0
            if cy < 0.30:
                tilt = 1
            elif cy > 0.70:
                tilt = -1

            if pan != 0 or tilt != 0:
                offset = max(abs(cx - 0.5), abs(cy - 0.5))
                duration = (0.05 + offset * 0.15) * speed
                yield MotorCommand(pan_dir=pan, tilt_dir=tilt,
                                   duration=duration, pause_after=0.1)
            else:
                yield MotorCommand(pause_after=0.25)
        else:
            pos = node.get_position()
            if pan_dir == -1 and not pos.can_pan_left:
                pan_dir = 1
            elif pan_dir == 1 and not pos.can_pan_right:
                pan_dir = -1

            if scan_hold > 0:
                scan_hold -= 1
                yield MotorCommand(pause_after=1.0)
            else:
                # Complexity-aware pause: dwell on interesting views,
                # pass quickly over blank walls.
                c = complexity_fn() if complexity_fn else 0.05
                if c < 0.03:
                    # Blank wall — short pause, keep moving
                    pause = random.uniform(0.3, 0.6)
                elif c > 0.10:
                    # Interesting view — dwell to observe
                    pause = random.uniform(2.0, 4.0)
                else:
                    # Default behavior
                    pause = random.uniform(1.0, 2.0)

                yield MotorCommand(
                    pan_dir=pan_dir,
                    duration=random.uniform(0.15, 0.35) * speed,
                    pause_after=pause,
                )
                if random.random() < 0.30:
                    scan_hold = random.randint(3, 6)
                if random.random() < 0.2:
                    pan_dir = -pan_dir


class MotorThread:
    """Daemon thread that iterates a motor program, executing commands."""

    SLEEP_GRANULARITY = 0.05

    def __init__(self, node: SensorNode):
        self.node = node
        self._program: MotorProgram | None = None
        self._program_lock = threading.Lock()
        self._paused = threading.Event()
        self._paused.set()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def set_program(self, program: MotorProgram | None) -> None:
        with self._program_lock:
            self._program = program

    def pause(self) -> None:
        self._paused.clear()

    def resume(self) -> None:
        self._paused.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._paused.set()
        self._thread.join(timeout=3)

    def _interruptible_sleep(self, seconds: float) -> bool:
        remaining = seconds
        while remaining > 0 and not self._stop_event.is_set():
            chunk = min(remaining, self.SLEEP_GRANULARITY)
            time.sleep(chunk)
            remaining -= chunk
        return not self._stop_event.is_set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._paused.wait()
            if self._stop_event.is_set():
                break

            with self._program_lock:
                program = self._program

            if program is None:
                if not self._interruptible_sleep(0.1):
                    break
                continue

            try:
                cmd = next(program)
            except StopIteration:
                with self._program_lock:
                    self._program = None
                continue

            if cmd.pan_dir != 0 or cmd.tilt_dir != 0:
                pos = self.node.get_position()
                pan = cmd.pan_dir
                tilt = cmd.tilt_dir
                if pan == -1 and not pos.can_pan_left:
                    pan = 0
                if pan == 1 and not pos.can_pan_right:
                    pan = 0
                if tilt == -1 and not pos.can_tilt_down:
                    tilt = 0
                if tilt == 1 and not pos.can_tilt_up:
                    tilt = 0

                if pan != 0 or tilt != 0:
                    self.node.move(pan, tilt, cmd.duration)
                elif cmd.duration > 0:
                    if not self._interruptible_sleep(cmd.duration):
                        break

            if cmd.pause_after > 0:
                if not self._interruptible_sleep(cmd.pause_after):
                    break
