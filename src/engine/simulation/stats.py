"""StatsTracker -- after-action statistics for combat and game analysis.

Architecture
------------
StatsTracker maintains per-unit and per-wave statistics throughout a game
session.  It is designed to be lightweight (called from the 10Hz tick loop)
and backward-compatible (engine works without it).

Per-unit stats (UnitStats):
  Tracks shots fired/hit, damage dealt/taken, kills/deaths/assists,
  distance traveled, max speed, time alive, time in combat, and health
  remaining.  Computed properties: accuracy, KD ratio, damage efficiency.

Per-wave stats (WaveStats):
  Aggregates shots, damage, eliminations, escapes, and friendly losses
  for each wave.  Duration and score are recorded on wave completion.

Assist tracking:
  A deque of recent damage records tracks (timestamp, attacker_id,
  target_id, damage).  When a kill occurs, any attacker who damaged the
  victim within the assist window (5s) gets an assist credit, except the
  killer themselves.

Movement tracking:
  Per-tick position deltas are summed to compute distance_traveled.
  Speed per tick is compared to max_speed_reached.

Time tracking:
  time_alive increments for every tick where status is active/idle/stationary.
  time_in_combat increments when enemies are within weapon_range.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus


@dataclass
class UnitStats:
    """Per-unit combat statistics."""

    target_id: str
    name: str
    alliance: str
    asset_type: str

    # Combat stats
    shots_fired: int = 0
    shots_hit: int = 0
    damage_dealt: float = 0.0
    damage_taken: float = 0.0
    kills: int = 0
    deaths: int = 0
    assists: int = 0  # Damaged a target that someone else killed within 5s

    # Movement stats
    distance_traveled: float = 0.0
    max_speed_reached: float = 0.0

    # Survival stats
    time_alive: float = 0.0
    time_in_combat: float = 0.0  # Time with enemies in weapon_range
    health_remaining: float = 0.0

    # Efficiency metrics (computed)
    @property
    def accuracy(self) -> float:
        """Hit rate: shots_hit / shots_fired.  0 if no shots fired."""
        return self.shots_hit / self.shots_fired if self.shots_fired > 0 else 0.0

    @property
    def kd_ratio(self) -> float:
        """Kill-death ratio.  Returns float(kills) if zero deaths."""
        return self.kills / self.deaths if self.deaths > 0 else float(self.kills)

    @property
    def damage_efficiency(self) -> float:
        """Damage dealt / damage taken.  inf if dealt>0 but taken==0."""
        if self.damage_taken > 0:
            return self.damage_dealt / self.damage_taken
        if self.damage_dealt > 0:
            return float("inf")
        return 0.0

    def to_dict(self) -> dict:
        """Serialize to dict including computed properties."""
        d = {
            "target_id": self.target_id,
            "name": self.name,
            "alliance": self.alliance,
            "asset_type": self.asset_type,
            "shots_fired": self.shots_fired,
            "shots_hit": self.shots_hit,
            "damage_dealt": round(self.damage_dealt, 2),
            "damage_taken": round(self.damage_taken, 2),
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "distance_traveled": round(self.distance_traveled, 2),
            "max_speed_reached": round(self.max_speed_reached, 2),
            "time_alive": round(self.time_alive, 2),
            "time_in_combat": round(self.time_in_combat, 2),
            "health_remaining": round(self.health_remaining, 2),
            "accuracy": round(self.accuracy, 4),
            "kd_ratio": round(self.kd_ratio, 2),
            "damage_efficiency": round(self.damage_efficiency, 2) if math.isfinite(self.damage_efficiency) else "inf",
        }
        return d


@dataclass
class WaveStats:
    """Per-wave aggregate statistics."""

    wave_number: int
    wave_name: str
    duration: float = 0.0
    hostiles_spawned: int = 0
    hostiles_eliminated: int = 0
    hostiles_escaped: int = 0
    friendly_losses: int = 0
    total_damage_dealt: float = 0.0
    total_damage_taken: float = 0.0
    total_shots_fired: int = 0
    total_shots_hit: int = 0
    score_earned: int = 0

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "wave_number": self.wave_number,
            "wave_name": self.wave_name,
            "duration": round(self.duration, 2),
            "hostiles_spawned": self.hostiles_spawned,
            "hostiles_eliminated": self.hostiles_eliminated,
            "hostiles_escaped": self.hostiles_escaped,
            "friendly_losses": self.friendly_losses,
            "total_damage_dealt": round(self.total_damage_dealt, 2),
            "total_damage_taken": round(self.total_damage_taken, 2),
            "total_shots_fired": self.total_shots_fired,
            "total_shots_hit": self.total_shots_hit,
            "score_earned": self.score_earned,
        }


class StatsTracker:
    """Tracks all combat and game statistics.

    Designed to be called from the engine tick loop (10Hz) and from
    combat event handlers.  Lightweight: no threads, no EventBus
    subscription (the engine wires events directly).
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._unit_stats: dict[str, UnitStats] = {}
        self._wave_stats: list[WaveStats] = []
        self._current_wave: WaveStats | None = None
        self._assist_window: float = 5.0  # seconds
        self._recent_damage: deque[tuple[float, str, str, float]] = deque(maxlen=500)
        # (timestamp, attacker_id, target_id, damage)

        # Movement tracking: last known position per unit
        self._last_positions: dict[str, tuple[float, float]] = {}

        # Wave timing
        self._wave_start_time: float = 0.0

        # Game elapsed time
        self._game_elapsed: float = 0.0

    # -- Registration -------------------------------------------------------

    def register_unit(
        self, target_id: str, name: str, alliance: str, asset_type: str
    ) -> None:
        """Register a unit for tracking.  Overwrites if already registered."""
        self._unit_stats[target_id] = UnitStats(
            target_id=target_id,
            name=name,
            alliance=alliance,
            asset_type=asset_type,
        )

    # -- Combat events ------------------------------------------------------

    def record_shot(self, target_id: str) -> None:
        """Record that a unit fired a shot (convenience alias for on_shot_fired).

        Also auto-registers the unit if not already tracked.
        """
        if target_id not in self._unit_stats:
            self._unit_stats[target_id] = UnitStats(
                target_id=target_id,
                name=target_id,
                alliance="unknown",
                asset_type="unknown",
            )
        stats = self._unit_stats[target_id]
        stats.shots_fired += 1
        if self._current_wave is not None:
            self._current_wave.total_shots_fired += 1

    def on_shot_fired(self, shooter_id: str) -> None:
        """Record a shot fired by *shooter_id*."""
        stats = self._unit_stats.get(shooter_id)
        if stats is None:
            return
        stats.shots_fired += 1
        if self._current_wave is not None:
            self._current_wave.total_shots_fired += 1

    def on_shot_hit(
        self,
        shooter_id: str,
        target_id: str,
        damage: float,
        timestamp: float | None = None,
    ) -> None:
        """Record a hit.  Updates shooter's shots_hit + damage_dealt, and
        target's damage_taken.  Stores recent damage for assist tracking.

        Args:
            timestamp: Override for assist-window calculation (monotonic).
                       Defaults to time.monotonic() if not provided.
        """
        ts = timestamp if timestamp is not None else time.monotonic()
        self._recent_damage.append((ts, shooter_id, target_id, damage))

        shooter_stats = self._unit_stats.get(shooter_id)
        if shooter_stats is not None:
            shooter_stats.shots_hit += 1
            shooter_stats.damage_dealt += damage

        target_stats = self._unit_stats.get(target_id)
        if target_stats is not None:
            target_stats.damage_taken += damage

        if self._current_wave is not None:
            self._current_wave.total_shots_hit += 1
            self._current_wave.total_damage_dealt += damage

    def on_kill(self, killer_id: str, victim_id: str) -> None:
        """Record a kill.  Increments killer's kills and victim's deaths.
        Also checks for assists (other units that damaged the victim
        within the assist window).
        """
        killer_stats = self._unit_stats.get(killer_id)
        if killer_stats is not None:
            killer_stats.kills += 1

        victim_stats = self._unit_stats.get(victim_id)
        if victim_stats is not None:
            victim_stats.deaths += 1

        if self._current_wave is not None:
            self._current_wave.hostiles_eliminated += 1

        # Check assists: who damaged the victim recently (excluding killer)?
        now = time.monotonic()
        assisters: set[str] = set()
        for ts, attacker_id, target_id, damage in self._recent_damage:
            if target_id != victim_id:
                continue
            if attacker_id == killer_id:
                continue
            if (now - ts) <= self._assist_window:
                assisters.add(attacker_id)

        for assister_id in assisters:
            assister_stats = self._unit_stats.get(assister_id)
            if assister_stats is not None:
                assister_stats.assists += 1

    def on_damage_taken(self, target_id: str, damage: float) -> None:
        """Record damage received by *target_id*."""
        stats = self._unit_stats.get(target_id)
        if stats is None:
            return
        stats.damage_taken += damage

        if self._current_wave is not None:
            self._current_wave.total_damage_taken += damage

    # -- Wave events --------------------------------------------------------

    def on_wave_start(
        self, wave_number: int, wave_name: str, hostile_count: int
    ) -> None:
        """Start tracking a new wave."""
        wave = WaveStats(
            wave_number=wave_number,
            wave_name=wave_name,
            hostiles_spawned=hostile_count,
        )
        self._current_wave = wave
        self._wave_stats.append(wave)
        self._wave_start_time = time.monotonic()

    def on_wave_complete(self, score: int) -> None:
        """Finalize current wave stats."""
        if self._current_wave is None:
            return
        self._current_wave.score_earned = score
        self._current_wave.duration = time.monotonic() - self._wave_start_time
        self._current_wave = None

    def on_hostile_escaped(self) -> None:
        """Record a hostile escaping during the current wave."""
        if self._current_wave is not None:
            self._current_wave.hostiles_escaped += 1

    def on_friendly_loss(self) -> None:
        """Record a friendly unit being eliminated during the current wave."""
        if self._current_wave is not None:
            self._current_wave.friendly_losses += 1

    # -- Tick ---------------------------------------------------------------

    def tick(self, dt: float, targets: dict | None = None) -> None:
        """Update time-based stats (time_alive, distance_traveled, etc.).

        Called from the engine tick loop at 10Hz.

        Args:
            dt: Time step (typically 0.1s).
            targets: Dict mapping target_id to target objects with
                     .position, .status, .speed, .weapon_range, .alliance.
                     If None, only game_elapsed is updated.
        """
        self._game_elapsed += dt
        if targets is None:
            return
        # Build quick lookup for enemy detection
        friendlies = []
        hostiles = []
        for t in targets.values():
            if not hasattr(t, "alliance"):
                continue
            if t.alliance == "friendly" and getattr(t, "status", "") in ("active", "idle", "stationary"):
                friendlies.append(t)
            elif t.alliance == "hostile" and getattr(t, "status", "") == "active":
                hostiles.append(t)

        for tid, target in targets.items():
            stats = self._unit_stats.get(tid)
            if stats is None:
                continue

            status = getattr(target, "status", "unknown")
            pos = getattr(target, "position", (0.0, 0.0))
            weapon_range = getattr(target, "weapon_range", 0.0)
            alliance = getattr(target, "alliance", "unknown")

            # Time alive: only count active/idle/stationary
            if status in ("active", "idle", "stationary"):
                stats.time_alive += dt

            # Health remaining: snapshot current health
            if hasattr(target, "health"):
                stats.health_remaining = target.health

            # Distance traveled + max speed
            last_pos = self._last_positions.get(tid)
            if last_pos is not None:
                dx = pos[0] - last_pos[0]
                dy = pos[1] - last_pos[1]
                dist = math.hypot(dx, dy)
                if dist > 0.001:  # Ignore floating-point noise
                    stats.distance_traveled += dist
                    speed = dist / dt if dt > 0 else 0.0
                    if speed > stats.max_speed_reached:
                        stats.max_speed_reached = speed
            self._last_positions[tid] = pos

            # Time in combat: enemy within weapon_range
            if status in ("active", "idle", "stationary") and weapon_range > 0:
                enemies = hostiles if alliance == "friendly" else friendlies
                in_combat = False
                for enemy in enemies:
                    ex, ey = enemy.position
                    edist = math.hypot(ex - pos[0], ey - pos[1])
                    if edist <= weapon_range:
                        in_combat = True
                        break
                if in_combat:
                    stats.time_in_combat += dt

    # -- Queries ------------------------------------------------------------

    def get_unit_stats(self, target_id: str) -> UnitStats | None:
        """Get stats for a specific unit, or None if not registered."""
        return self._unit_stats.get(target_id)

    def get_all_unit_stats(self) -> list[UnitStats]:
        """Get stats for all units, sorted by kills descending then accuracy."""
        return sorted(
            self._unit_stats.values(),
            key=lambda s: (s.kills, s.accuracy),
            reverse=True,
        )

    def get_wave_stats(self) -> list[WaveStats]:
        """Get all wave stats in order."""
        return list(self._wave_stats)

    def get_mvp(self) -> UnitStats | None:
        """Get the MVP (highest kills; accuracy tiebreaker).

        Returns None if no units are registered.
        """
        if not self._unit_stats:
            return None
        return max(
            self._unit_stats.values(),
            key=lambda s: (s.kills, s.accuracy),
        )

    def get_summary(self) -> dict:
        """Get game summary suitable for API / frontend consumption."""
        all_stats = list(self._unit_stats.values())
        total_kills = sum(s.kills for s in all_stats)
        total_deaths = sum(s.deaths for s in all_stats)
        total_shots_fired = sum(s.shots_fired for s in all_stats)
        total_shots_hit = sum(s.shots_hit for s in all_stats)
        total_damage_dealt = sum(s.damage_dealt for s in all_stats)
        total_damage_taken = sum(s.damage_taken for s in all_stats)
        overall_accuracy = (
            total_shots_hit / total_shots_fired
            if total_shots_fired > 0
            else 0.0
        )

        mvp = self.get_mvp()
        mvp_dict = mvp.to_dict() if mvp is not None else None

        return {
            "total_kills": total_kills,
            "total_deaths": total_deaths,
            "total_shots_fired": total_shots_fired,
            "total_shots_hit": total_shots_hit,
            "overall_accuracy": round(overall_accuracy, 4),
            "total_damage_dealt": round(total_damage_dealt, 2),
            "total_damage_taken": round(total_damage_taken, 2),
            "waves_completed": len(self._wave_stats),
            "mvp": mvp_dict,
            "unit_count": len(self._unit_stats),
        }

    # -- Lifecycle ----------------------------------------------------------

    def reset(self) -> None:
        """Clear all stats for a new game."""
        self._unit_stats.clear()
        self._wave_stats.clear()
        self._current_wave = None
        self._recent_damage.clear()
        self._last_positions.clear()
        self._wave_start_time = 0.0
        self._game_elapsed = 0.0

    def to_dict(self) -> dict:
        """Serialize full stats to dict."""
        return {
            "units": [s.to_dict() for s in self.get_all_unit_stats()],
            "waves": [w.to_dict() for w in self._wave_stats],
            "summary": self.get_summary(),
        }
