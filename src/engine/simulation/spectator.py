# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SpectatorMode -- replay playback controller for post-game analysis.

Architecture
------------
SpectatorMode provides VCR-style playback controls over recorded game data
from a ReplayRecorder.  It is strictly read-only: it reads frames and events
from the recorder but never writes to it.

Playback model:
  - Frame rate is 2Hz (matching the replay recording rate).
  - Speed is a multiplier on dt: at 2x, tick(0.5) advances 1.0 effective
    seconds = 2 frames.
  - The internal _elapsed accumulator tracks sub-frame fractional time.
    When _elapsed exceeds 0.5s (one frame at 2Hz), _frame_index increments.
  - Playback auto-pauses when it reaches the last frame.

Seek model:
  - seek(frame) jumps to a specific frame index, clamping to [0, total-1].
  - seek_time(seconds) converts to frame index: frame = seconds * 2.
  - seek_wave(wave_num) scans events for a wave_start event with the
    matching wave_number, then maps its timestamp to the nearest frame.

Data flow:
  Frontend (JS) --|POST /api/game/spectator/play|--> game.py router
  game.py --|engine.spectator.play()|--> SpectatorMode
  Frontend polls --|GET /api/game/spectator/state|--> SpectatorMode.get_state()
  Frontend renders frame data from get_frame() or tick() return value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .replay import ReplayRecorder

# Playback frame rate (Hz) -- matches ReplayRecorder snapshot rate.
FRAME_RATE = 2.0

# Seconds per frame at 1x speed.
FRAME_INTERVAL = 1.0 / FRAME_RATE

# Speed bounds.
MIN_SPEED = 0.25
MAX_SPEED = 4.0


class SpectatorMode:
    """Controls replay playback with VCR-style controls.

    Reads from ReplayRecorder data and provides frame-by-frame
    or speed-adjusted playback of recorded game sessions.
    """

    def __init__(self, replay: ReplayRecorder) -> None:
        self._replay = replay
        self._playing: bool = False
        self._speed: float = 1.0
        self._frame_index: int = 0
        self._elapsed: float = 0.0

    # -- Properties ----------------------------------------------------------

    @property
    def total_frames(self) -> int:
        """Total recorded frames."""
        return self._replay.frame_count

    @property
    def current_frame(self) -> int:
        """Current playback position (frame index)."""
        return self._frame_index

    @property
    def duration(self) -> float:
        """Total duration in seconds.

        With N frames at FRAME_RATE Hz, the duration spans from frame 0 to
        frame N-1, which is (N-1) / FRAME_RATE seconds.  Empty replays
        have 0 duration.
        """
        n = self.total_frames
        if n <= 1:
            return 0.0
        return (n - 1) / FRAME_RATE

    @property
    def current_time(self) -> float:
        """Current playback time in seconds."""
        return self._frame_index / FRAME_RATE

    @property
    def progress(self) -> float:
        """Playback progress 0.0-1.0.

        Returns 0.0 for empty replays or when at frame 0.
        Returns 1.0 when at the last frame.
        """
        n = self.total_frames
        if n <= 1:
            return 0.0
        return self._frame_index / (n - 1)

    # -- Transport controls --------------------------------------------------

    def play(self) -> None:
        """Start or resume playback."""
        self._playing = True

    def pause(self) -> None:
        """Pause playback."""
        self._playing = False

    def stop(self) -> None:
        """Stop playback and rewind to the start."""
        self._playing = False
        self._frame_index = 0
        self._elapsed = 0.0

    # -- Seek ----------------------------------------------------------------

    def seek(self, frame: int) -> None:
        """Jump to a specific frame index.

        Clamps to [0, total_frames - 1].  No-op for empty replays.
        """
        n = self.total_frames
        if n == 0:
            self._frame_index = 0
            self._elapsed = 0.0
            return
        self._frame_index = max(0, min(frame, n - 1))
        self._elapsed = 0.0

    def seek_time(self, seconds: float) -> None:
        """Jump to a specific time (seconds).

        Converts time to frame index: frame = int(seconds * FRAME_RATE).
        Clamps to valid range.
        """
        if seconds < 0:
            seconds = 0.0
        frame = int(seconds * FRAME_RATE)
        self.seek(frame)

    def seek_wave(self, wave_number: int) -> None:
        """Jump to the start of a specific wave.

        Scans the replay events for a wave_start event with the matching
        wave_number.  If found, maps the event's timestamp to the nearest
        frame index.  If not found, does nothing (stays at current position).
        """
        events = self._replay.get_events()
        frames = self._replay.get_frames()

        if not frames:
            return

        # Find the wave_start event
        wave_event = None
        for e in events:
            if (
                e["event_type"] == "wave_start"
                and e["data"].get("wave_number") == wave_number
            ):
                wave_event = e
                break

        if wave_event is None:
            return

        # Map event timestamp to the nearest frame
        target_ts = wave_event["timestamp"]
        best_idx = 0
        best_diff = abs(frames[0]["timestamp"] - target_ts)
        for i, f in enumerate(frames):
            diff = abs(f["timestamp"] - target_ts)
            if diff < best_diff:
                best_diff = diff
                best_idx = i

        self.seek(best_idx)

    # -- Speed ---------------------------------------------------------------

    def set_speed(self, speed: float) -> None:
        """Set playback speed.

        Clamps to [MIN_SPEED, MAX_SPEED] (0.25x to 4.0x).
        """
        self._speed = max(MIN_SPEED, min(speed, MAX_SPEED))

    # -- Frame stepping ------------------------------------------------------

    def step_forward(self) -> None:
        """Advance one frame.

        Does not advance past the last frame.
        """
        n = self.total_frames
        if n == 0:
            return
        if self._frame_index < n - 1:
            self._frame_index += 1
            self._elapsed = 0.0

    def step_backward(self) -> None:
        """Go back one frame.

        Does not go before frame 0.
        """
        if self._frame_index > 0:
            self._frame_index -= 1
            self._elapsed = 0.0

    # -- Tick (playback advance) ---------------------------------------------

    def tick(self, dt: float) -> dict | None:
        """Advance playback by *dt* seconds at current speed.

        Returns the current frame data, or None if paused/stopped or if
        the replay is empty.

        The effective time step is ``dt * speed``.  Time is accumulated in
        ``_elapsed``.  Each time _elapsed reaches FRAME_INTERVAL (0.5s at
        2Hz), the frame index advances by one.  If the last frame is
        reached, playback auto-pauses and the last frame is returned.
        """
        if not self._playing:
            return None

        n = self.total_frames
        if n == 0:
            return None

        effective_dt = dt * self._speed
        self._elapsed += effective_dt

        # Convert accumulated time into frame advances
        frames_to_advance = int(self._elapsed / FRAME_INTERVAL)
        if frames_to_advance > 0:
            self._elapsed -= frames_to_advance * FRAME_INTERVAL
            self._frame_index += frames_to_advance

        # Clamp and auto-pause at end
        if self._frame_index >= n - 1:
            self._frame_index = n - 1
            self._playing = False
            self._elapsed = 0.0

        return self.get_frame(self._frame_index)

    # -- Data access ---------------------------------------------------------

    def get_frame(self, index: int) -> dict | None:
        """Get a specific frame by index.

        Returns None if the index is out of bounds or the replay is empty.
        """
        if index < 0:
            return None
        frames = self._replay.get_frames()
        if index >= len(frames):
            return None
        return frames[index]

    def get_events_in_range(
        self, start_frame: int, end_frame: int
    ) -> list[dict]:
        """Get events whose timestamps fall between two frame timestamps.

        Returns events where:
            frames[start_frame].timestamp <= event.timestamp <= frames[end_frame].timestamp

        Returns all events if the replay has no frames.
        """
        frames = self._replay.get_frames()
        events = self._replay.get_events()

        if not frames or not events:
            return []

        # Resolve frame timestamps
        start_idx = max(0, min(start_frame, len(frames) - 1))
        end_idx = max(0, min(end_frame, len(frames) - 1))
        start_ts = frames[start_idx]["timestamp"]
        end_ts = frames[end_idx]["timestamp"]

        # Allow a small epsilon so events recorded at the exact same time
        # as a frame aren't missed due to floating-point comparison.
        eps = 0.01

        return [
            e for e in events
            if start_ts - eps <= e["timestamp"] <= end_ts + eps
        ]

    # -- State serialization -------------------------------------------------

    def get_state(self) -> dict:
        """Current spectator state for API / frontend consumption."""
        return {
            "playing": self._playing,
            "speed": self._speed,
            "current_frame": self._frame_index,
            "total_frames": self.total_frames,
            "duration": round(self.duration, 2),
            "current_time": round(self.current_time, 2),
            "progress": round(self.progress, 4),
        }
