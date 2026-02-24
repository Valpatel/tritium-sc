"""DifficultyScaler — adaptive difficulty for wave-based combat.

Architecture
------------
DifficultyScaler tracks player performance across waves and computes a
``threat_multiplier`` that adjusts the next wave's hostiles.  The goal
is to keep the game in "the zone" — challenging enough for skilled players,
forgiving enough for newcomers.

Performance signals (per wave):
  - elimination_rate:  hostiles eliminated / hostiles spawned
  - wave_time:         seconds to clear the wave
  - friendly_damage_ratio:  total friendly damage / total friendly max health
  - escapes:           hostiles that escaped the map

The multiplier starts at 1.0 and adjusts +/-0.1 per wave based on a
composite performance score.  It is clamped to [0.5, 2.0].

Wave adjustments:
  - hostile_count = round(base_count * multiplier), minimum 1
  - hostile_health_bonus = max(0, (multiplier - 1.0) * 0.3)
  - hostile_speed_bonus  = max(0, (multiplier - 1.0) * 0.15)

Hardened variant (multiplier > 1.5):
  - Increased flank_chance
  - Cover-seeking enabled
  - 1 elite hostile with 2x health

Easy variant (multiplier < 0.7):
  - Flanking disabled
  - Slower hostile speed
  - Fewer hostiles (already via count formula)
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Multiplier bounds
_MIN_MULTIPLIER = 0.5
_MAX_MULTIPLIER = 2.0

# Maximum adjustment per wave
_ADJUSTMENT_STEP = 0.1

# Performance thresholds for the composite score
# A score > 0 means player is doing well (increase difficulty)
# A score < 0 means player is struggling (decrease difficulty)

# Weights for the composite score components
_WEIGHT_ELIMINATION = 0.4   # How many hostiles were killed
_WEIGHT_TIME = 0.2          # How fast the wave was cleared
_WEIGHT_DAMAGE = 0.2        # How little damage friendlies took
_WEIGHT_ESCAPES = 0.2       # How few hostiles escaped

# Reference time for "fast" wave completion (seconds)
_FAST_WAVE_TIME = 20.0

# Hardened variant threshold
_HARDENED_THRESHOLD = 1.5

# Easy variant threshold
_EASY_THRESHOLD = 0.7


@dataclass
class WaveRecord:
    """Record of a single wave's performance metrics."""
    elimination_rate: float
    wave_time: float
    friendly_damage_ratio: float
    escapes: int
    hostiles_spawned: int


class DifficultyScaler:
    """Tracks performance and computes adaptive difficulty multiplier."""

    def __init__(self) -> None:
        self._multiplier: float = 1.0
        self.wave_history: list[WaveRecord] = []
        self.last_elimination_rate: float = 0.0

    def get_multiplier(self) -> float:
        """Return the current difficulty multiplier, clamped to [0.5, 2.0]."""
        return self._multiplier

    def record_wave(self, stats: dict) -> None:
        """Record wave performance and adjust the multiplier.

        Args:
            stats: Dictionary with keys:
                - eliminations: int
                - hostiles_spawned: int
                - wave_time: float (seconds)
                - friendly_damage_taken: float
                - friendly_max_health: float
                - escapes: int
        """
        eliminations = stats.get("eliminations", 0)
        hostiles_spawned = stats.get("hostiles_spawned", 0)
        wave_time = stats.get("wave_time", 0.0)
        friendly_damage_taken = stats.get("friendly_damage_taken", 0.0)
        friendly_max_health = stats.get("friendly_max_health", 1.0)
        escapes = stats.get("escapes", 0)

        # Compute rates
        if hostiles_spawned > 0:
            elimination_rate = eliminations / hostiles_spawned
            escape_rate = escapes / hostiles_spawned
        else:
            elimination_rate = 0.0
            escape_rate = 0.0

        if friendly_max_health > 0:
            friendly_damage_ratio = friendly_damage_taken / friendly_max_health
        else:
            friendly_damage_ratio = 0.0

        self.last_elimination_rate = elimination_rate

        # Store record
        record = WaveRecord(
            elimination_rate=elimination_rate,
            wave_time=wave_time,
            friendly_damage_ratio=friendly_damage_ratio,
            escapes=escapes,
            hostiles_spawned=hostiles_spawned,
        )
        self.wave_history.append(record)

        # Compute composite performance score in [-1.0, 1.0]
        # Positive = player doing well, negative = struggling
        score = self._compute_performance_score(record)

        # Adjust multiplier: score maps to [-0.1, +0.1]
        adjustment = score * _ADJUSTMENT_STEP
        self._multiplier = max(
            _MIN_MULTIPLIER,
            min(_MAX_MULTIPLIER, self._multiplier + adjustment),
        )

    def get_wave_adjustments(self, base_count: int) -> dict:
        """Compute wave adjustments based on current multiplier.

        Args:
            base_count: The base number of hostiles for this wave.

        Returns:
            Dictionary with adjusted wave parameters:
                - hostile_count: int (adjusted, minimum 1)
                - hostile_health_bonus: float (fractional bonus, >= 0)
                - hostile_speed_bonus: float (fractional bonus, >= 0)
                - hardened: bool (True if multiplier > 1.5)
                - flank_chance_boost: float (0.0 if not hardened)
                - use_cover_seeking: bool
                - elite_count: int (0 normally, 1+ when hardened)
                - easy: bool (True if multiplier < 0.7)
                - disable_flanking: bool
                - speed_reduction: float (0.0 if not easy)
        """
        m = self._multiplier

        # Base adjustments
        hostile_count = max(1, round(base_count * m))
        hostile_health_bonus = max(0.0, (m - 1.0) * 0.3)
        hostile_speed_bonus = max(0.0, (m - 1.0) * 0.15)

        # Hardened variant: multiplier > 1.5 (strictly greater)
        hardened = m > _HARDENED_THRESHOLD
        flank_chance_boost = 0.0
        use_cover_seeking = False
        elite_count = 0
        if hardened:
            flank_chance_boost = (m - _HARDENED_THRESHOLD) * 0.5
            use_cover_seeking = True
            elite_count = 1

        # Easy variant: multiplier < 0.7 (strictly less)
        easy = m < _EASY_THRESHOLD
        disable_flanking = False
        speed_reduction = 0.0
        if easy:
            disable_flanking = True
            speed_reduction = (_EASY_THRESHOLD - m) * 0.3

        return {
            "hostile_count": hostile_count,
            "hostile_health_bonus": hostile_health_bonus,
            "hostile_speed_bonus": hostile_speed_bonus,
            "hardened": hardened,
            "flank_chance_boost": flank_chance_boost,
            "use_cover_seeking": use_cover_seeking,
            "elite_count": elite_count,
            "easy": easy,
            "disable_flanking": disable_flanking,
            "speed_reduction": speed_reduction,
        }

    def reset(self) -> None:
        """Reset all difficulty state to initial values."""
        self._multiplier = 1.0
        self.wave_history.clear()
        self.last_elimination_rate = 0.0

    # -- Internal ---------------------------------------------------------------

    def _compute_performance_score(self, record: WaveRecord) -> float:
        """Compute a composite performance score in [-1.0, 1.0].

        Positive = player doing well (increase difficulty).
        Negative = player struggling (decrease difficulty).
        """
        # Elimination component: 1.0 = all killed, 0.0 = none killed
        # Map to [-1, 1]: rate > 0.5 is positive, < 0.5 is negative
        elim_score = (record.elimination_rate - 0.5) * 2.0

        # Time component: fast waves are positive, slow waves are negative
        # < 20s is fast (score +1), > 60s is slow (score -1)
        if record.wave_time <= _FAST_WAVE_TIME:
            time_score = 1.0
        elif record.wave_time >= 60.0:
            time_score = -1.0
        else:
            # Linear interpolation: 20s -> +1, 60s -> -1
            time_score = 1.0 - 2.0 * (record.wave_time - _FAST_WAVE_TIME) / (60.0 - _FAST_WAVE_TIME)

        # Damage component: no damage is positive, 100% damage is negative
        # damage_ratio 0.0 -> +1, 1.0 -> -1
        damage_score = 1.0 - 2.0 * min(1.0, record.friendly_damage_ratio)

        # Escape component: no escapes is positive, many escapes is negative
        if record.hostiles_spawned > 0:
            escape_rate = record.escapes / record.hostiles_spawned
        else:
            escape_rate = 0.0
        escape_score = 1.0 - 2.0 * min(1.0, escape_rate)

        # Weighted sum
        score = (
            _WEIGHT_ELIMINATION * elim_score
            + _WEIGHT_TIME * time_score
            + _WEIGHT_DAMAGE * damage_score
            + _WEIGHT_ESCAPES * escape_score
        )

        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, score))
