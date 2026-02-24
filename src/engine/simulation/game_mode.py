"""GameMode — state machine, wave controller, and scoring.

Architecture
------------
GameMode manages the flow of a Nerf war session through a linear state
machine:

  setup -> countdown (5s) -> active -> wave_complete -> active -> ... -> victory | defeat

The wave controller defines 10 waves of increasing difficulty.  Each
wave specifies a hostile count, speed multiplier, and health multiplier.
Hostiles are spawned in staggered batches (not all at once) via the
SimulationEngine's ``spawn_hostile()`` method.

Victory is achieved by surviving all 10 waves (all hostiles in the final
wave eliminated).  Defeat occurs when all friendly combatants are
eliminated.

Scoring:
  - 100 points per hostile eliminated
  - 50 point time bonus per wave (decreasing by 5 per 10s elapsed)
  - Wave completion bonuses: wave_number * 200

Events published on EventBus for frontend and announcer:
  - ``game_state_change``: any state transition
  - ``wave_start``: new wave begins
  - ``wave_complete``: wave cleared
  - ``game_over``: victory or defeat
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from .combat import CombatSystem
    from .engine import SimulationEngine


@dataclass
class WaveConfig:
    """Configuration for a single wave of hostiles."""

    name: str
    count: int
    speed_mult: float
    health_mult: float
    # Extended fields for infinite mode
    has_elites: bool = False
    elite_count: int = 0
    elite_health_mult: float = 1.0
    has_boss: bool = False
    boss_health_mult: float = 1.0
    score_mult: float = 1.0


# 10 waves of increasing difficulty
WAVE_CONFIGS: list[WaveConfig] = [
    WaveConfig("Scout Party",    count=3,  speed_mult=0.8, health_mult=0.7),
    WaveConfig("Raiding Party",  count=5,  speed_mult=1.0, health_mult=1.0),
    WaveConfig("Assault Squad",  count=7,  speed_mult=1.0, health_mult=1.2),
    WaveConfig("Heavy Assault",  count=8,  speed_mult=1.1, health_mult=1.5),
    WaveConfig("Blitz Attack",   count=10, speed_mult=1.3, health_mult=1.2),
    WaveConfig("Armored Push",   count=8,  speed_mult=0.9, health_mult=2.0),
    WaveConfig("Swarm",          count=15, speed_mult=1.4, health_mult=0.8),
    WaveConfig("Elite Strike",   count=6,  speed_mult=1.2, health_mult=2.5),
    WaveConfig("Full Invasion",  count=20, speed_mult=1.3, health_mult=1.5),
    WaveConfig("FINAL STAND",    count=25, speed_mult=1.5, health_mult=2.0),
]

# Time between staggered spawns within a wave
_SPAWN_STAGGER = 0.5  # seconds

# Delay before auto-advancing to next wave after wave_complete
_WAVE_ADVANCE_DELAY = 5.0  # seconds

# Countdown duration before wave 1
_COUNTDOWN_DURATION = 5.0  # seconds


class GameMode:
    """Game state machine + wave controller + scoring."""

    STATES = ("setup", "countdown", "active", "wave_complete", "victory", "defeat")

    def __init__(
        self,
        event_bus: EventBus,
        engine: SimulationEngine,
        combat_system: CombatSystem,
        infinite: bool = False,
    ) -> None:
        self._event_bus = event_bus
        self._engine = engine
        self._combat = combat_system
        self.infinite: bool = infinite

        # Adaptive difficulty scaler (always available)
        from .difficulty import DifficultyScaler
        self.difficulty: DifficultyScaler = DifficultyScaler()

        # Infinite wave generator (created once, used when wave > 10)
        self._infinite_wave_mode: InfiniteWaveMode = InfiniteWaveMode(
            difficulty=self.difficulty,
        )

        self.state: str = "setup"
        self.wave: int = 0
        self.score: int = 0
        self.total_eliminations: int = 0
        self.wave_eliminations: int = 0
        self._countdown_remaining: float = _COUNTDOWN_DURATION
        self._wave_start_time: float = 0.0
        self._wave_complete_time: float = 0.0
        self._wave_hostile_ids: set[str] = set()
        self._spawn_thread: threading.Thread | None = None

    # -- Public interface -------------------------------------------------------

    def begin_war(self) -> None:
        """Transition from setup to countdown. Starts the war."""
        if self.state != "setup":
            return
        self.state = "countdown"
        self._countdown_remaining = _COUNTDOWN_DURATION
        self.wave = 1
        self.score = 0
        self.total_eliminations = 0
        self.wave_eliminations = 0
        self._combat.reset_streaks()
        self._publish_state_change()

    def tick(self, dt: float) -> None:
        """Called every engine tick. Manages state transitions."""
        if self.state == "countdown":
            self._tick_countdown(dt)
        elif self.state == "active":
            self._tick_active(dt)
        elif self.state == "wave_complete":
            self._tick_wave_complete(dt)

    def reset(self) -> None:
        """Reset to setup state. Clear game-mode hostiles."""
        self.state = "setup"
        self.wave = 0
        self.score = 0
        self.total_eliminations = 0
        self.wave_eliminations = 0
        self._countdown_remaining = _COUNTDOWN_DURATION
        self._wave_hostile_ids.clear()
        self._combat.reset_streaks()
        self._combat.clear()
        self._publish_state_change()

    def on_target_eliminated(self, target_id: str) -> None:
        """Notify the game mode that a target was eliminated.

        Called by the engine/combat integration to update elimination counts
        and scoring.
        """
        if self.state != "active":
            return
        if target_id in self._wave_hostile_ids:
            self.wave_eliminations += 1
            self.total_eliminations += 1
            self.score += 100  # points per elimination

    def get_state(self) -> dict:
        """Return serializable game state for API/frontend."""
        wave_config = self._current_wave_config()
        total_waves = -1 if self.infinite else len(WAVE_CONFIGS)
        return {
            "state": self.state,
            "wave": self.wave,
            "wave_name": wave_config.name if wave_config else "",
            "total_waves": total_waves,
            "countdown": round(self._countdown_remaining, 1),
            "score": self.score,
            "total_eliminations": self.total_eliminations,
            "wave_eliminations": self.wave_eliminations,
            "wave_hostiles_remaining": self._count_wave_hostiles_alive(),
            "infinite": self.infinite,
        }

    # -- State tick handlers ----------------------------------------------------

    def _tick_countdown(self, dt: float) -> None:
        self._countdown_remaining -= dt
        if self._countdown_remaining <= 0:
            self._countdown_remaining = 0
            self.state = "active"
            self._start_wave(self.wave)
            self._publish_state_change()

    def _tick_active(self, dt: float) -> None:
        # Check defeat: all friendly combatants eliminated
        friendlies_alive = [
            t for t in self._engine.get_targets()
            if t.alliance == "friendly" and t.is_combatant
            and t.status in ("active", "idle", "stationary")
        ]
        if not friendlies_alive:
            self.state = "defeat"
            self._event_bus.publish("game_over", {
                "result": "defeat",
                "final_score": self.score,
                "waves_completed": self.wave - 1,
                "total_eliminations": self.total_eliminations,
            })
            self._publish_state_change()
            return

        # Check wave complete: all wave hostiles eliminated or escaped
        alive = self._count_wave_hostiles_alive()
        if alive == 0 and not self._is_spawning():
            self._on_wave_complete()

    def _tick_wave_complete(self, dt: float) -> None:
        elapsed = time.time() - self._wave_complete_time
        if elapsed >= _WAVE_ADVANCE_DELAY:
            self.wave += 1
            if not self.infinite and self.wave > len(WAVE_CONFIGS):
                # All waves cleared — victory! (finite mode only)
                self.state = "victory"
                self._event_bus.publish("game_over", {
                    "result": "victory",
                    "final_score": self.score,
                    "waves_completed": len(WAVE_CONFIGS),
                    "total_eliminations": self.total_eliminations,
                })
                self._publish_state_change()
            else:
                self.state = "active"
                self._start_wave(self.wave)
                self._publish_state_change()

    # -- Wave management --------------------------------------------------------

    def _current_wave_config(self) -> WaveConfig | None:
        if 1 <= self.wave <= len(WAVE_CONFIGS):
            return WAVE_CONFIGS[self.wave - 1]
        if self.infinite and self.wave > len(WAVE_CONFIGS):
            return self._infinite_wave_mode.get_wave_config(self.wave)
        return None

    def _start_wave(self, wave_num: int) -> None:
        """Spawn hostiles for this wave in a background thread (staggered)."""
        config = self._current_wave_config()
        if config is None:
            return

        self.wave_eliminations = 0
        self._wave_start_time = time.time()
        self._wave_hostile_ids.clear()

        self._event_bus.publish("wave_start", {
            "wave_number": wave_num,
            "wave_name": config.name,
            "hostile_count": config.count,
        })

        # Spawn in background thread to stagger over time
        self._spawn_thread = threading.Thread(
            target=self._spawn_wave_hostiles,
            args=(config,),
            name=f"wave-{wave_num}-spawner",
            daemon=True,
        )
        self._spawn_thread.start()

    def _spawn_wave_hostiles(self, config: WaveConfig) -> None:
        """Spawn hostiles with staggered timing."""
        for i in range(config.count):
            if self.state not in ("active",):
                break
            hostile = self._engine.spawn_hostile()
            # Apply wave multipliers
            hostile.speed *= config.speed_mult
            hostile.health *= config.health_mult
            hostile.max_health *= config.health_mult
            hostile.apply_combat_profile()
            # Override health with multiplied values after profile
            hostile.health = 80.0 * config.health_mult
            hostile.max_health = 80.0 * config.health_mult
            self._wave_hostile_ids.add(hostile.target_id)
            if i < config.count - 1:
                time.sleep(_SPAWN_STAGGER)

    def _is_spawning(self) -> bool:
        """Check if the wave spawner thread is still running."""
        return self._spawn_thread is not None and self._spawn_thread.is_alive()

    def _count_wave_hostiles_alive(self) -> int:
        """Count wave hostiles that are still active threats."""
        count = 0
        for t in self._engine.get_targets():
            if t.target_id in self._wave_hostile_ids and t.status == "active":
                count += 1
        return count

    def _on_wave_complete(self) -> None:
        """Handle wave completion: scoring, events, state transition."""
        elapsed = time.time() - self._wave_start_time
        # Time bonus: starts at 50, decreases by 5 per 10s elapsed
        time_bonus = max(0, 50 - int(elapsed / 10) * 5)
        wave_bonus = self.wave * 200
        self.score += wave_bonus + time_bonus

        self.state = "wave_complete"
        self._wave_complete_time = time.time()

        config = self._current_wave_config()
        self._event_bus.publish("wave_complete", {
            "wave_number": self.wave,
            "wave_name": config.name if config else "",
            "time_elapsed": round(elapsed, 1),
            "eliminations": self.wave_eliminations,
            "score_bonus": wave_bonus + time_bonus,
        })
        self._publish_state_change()

    # -- Event publishing -------------------------------------------------------

    def _publish_state_change(self) -> None:
        self._event_bus.publish("game_state_change", self.get_state())


# ---------------------------------------------------------------------------
# InfiniteWaveMode — procedural wave generation beyond wave 10
# ---------------------------------------------------------------------------

# Scaling constants
_INFINITE_BASE_COUNT = 3
_INFINITE_COUNT_GROWTH = 1.08       # count = base * growth^wave
_INFINITE_SPEED_GROWTH = 0.03       # speed_mult = 1.0 + 0.03 * wave
_INFINITE_HEALTH_BRACKET = 5        # health steps every 5 waves
_INFINITE_HEALTH_STEP = 0.2         # +0.2 per bracket
_INFINITE_ELITE_THRESHOLD = 10      # elites appear after wave 10
_INFINITE_BOSS_THRESHOLD = 20       # bosses appear after wave 20
_INFINITE_BOSS_INTERVAL = 5         # boss every 5 waves after threshold
_INFINITE_ELITE_HEALTH_MULT = 2.0   # elite health multiplier
_INFINITE_BOSS_HEALTH_MULT = 5.0    # boss health multiplier


class InfiniteWaveMode:
    """Procedural wave generation for endless survival mode.

    Generates WaveConfig objects for any wave number using deterministic
    scaling formulas:
      - count:      round(base_count * 1.08^wave_num), minimum 1
      - speed_mult: 1.0 + 0.03 * wave_num
      - health_mult: 1.0 + 0.2 * floor(wave_num / 5)
      - elites:     appear after wave 10 (2x health)
      - bosses:     appear on wave 21, 26, 31, ... (5x health)
      - score_mult: wave_num / 10
    """

    def __init__(
        self,
        base_count: int = _INFINITE_BASE_COUNT,
        difficulty: object | None = None,
    ) -> None:
        self._base_count = base_count
        self._difficulty = difficulty

    def get_wave_config(self, wave_num: int) -> WaveConfig:
        """Generate a WaveConfig for the given wave number.

        Args:
            wave_num: The wave number (1-based). Any positive integer works.

        Returns:
            A WaveConfig with procedurally scaled parameters.
        """
        # Count: exponential growth, minimum 1
        raw_count = self._base_count * (_INFINITE_COUNT_GROWTH ** wave_num)
        count = max(1, round(raw_count))

        # Speed: linear growth
        speed_mult = 1.0 + _INFINITE_SPEED_GROWTH * wave_num

        # Health: step function (increases every 5 waves)
        health_bracket = wave_num // _INFINITE_HEALTH_BRACKET
        health_mult = 1.0 + _INFINITE_HEALTH_STEP * health_bracket

        # Elites: appear after wave 10
        has_elites = wave_num > _INFINITE_ELITE_THRESHOLD
        elite_count = 0
        if has_elites:
            elite_count = max(1, (wave_num - _INFINITE_ELITE_THRESHOLD) // 3)

        # Boss: appears on 21, 26, 31, ... (first at 21, then every 5)
        has_boss = (
            wave_num > _INFINITE_BOSS_THRESHOLD
            and (wave_num - (_INFINITE_BOSS_THRESHOLD + 1)) % _INFINITE_BOSS_INTERVAL == 0
        )

        # Score multiplier: linear with wave number
        score_mult = wave_num / 10.0

        # Wave name
        if has_boss:
            name = f"BOSS WAVE {wave_num}"
        elif has_elites:
            name = f"Elite Assault {wave_num}"
        else:
            name = f"Wave {wave_num}"

        return WaveConfig(
            name=name,
            count=count,
            speed_mult=speed_mult,
            health_mult=health_mult,
            has_elites=has_elites,
            elite_count=elite_count,
            elite_health_mult=_INFINITE_ELITE_HEALTH_MULT,
            has_boss=has_boss,
            boss_health_mult=_INFINITE_BOSS_HEALTH_MULT,
            score_mult=score_mult,
        )
