"""Unit-type FSM factories -- create behavior state machines for each unit type.

Each unit type has a characteristic set of states and transitions driven by
a context dict that the engine passes on each tick.  Context keys include:

    enemies_in_range:   list of enemy targets in detection range
    enemy_in_weapon_range: bool -- at least one enemy within weapon distance
    aimed_at_target:    bool -- turret has lock on target
    just_fired:         bool -- weapon just discharged
    weapon_ready:       bool -- weapon off cooldown
    has_waypoints:      bool -- unit has patrol/dispatch waypoints
    health_pct:         float 0.0-1.0 -- unit health fraction
    nearest_enemy_stationary: bool -- closest enemy is a turret/static
    degradation:        float 0.0-1.0 -- weapon degradation level

Turret FSM:
  idle -> scanning -> tracking -> engaging -> cooldown -> scanning
  Turrets scan for targets, track when found, engage when aimed, cooldown after firing.

Rover FSM:
  idle -> patrolling -> pursuing -> engaging -> retreating -> rtb
  Rovers patrol, pursue hostiles, engage at range, retreat if damaged.

Drone FSM:
  idle -> scouting -> orbiting -> engaging -> rtb
  Drones scout ahead, orbit enemies, engage when in weapon range, RTB if damaged.

Hostile FSM:
  spawning -> advancing -> engaging/flanking -> fleeing
  Hostiles spawn in, advance on objective, engage or flank defenders, flee if hurt.
"""

from __future__ import annotations

from .state_machine import State, StateMachine, Transition


# ============================================================================
# Turret FSM
# ============================================================================

def create_turret_fsm() -> StateMachine:
    """Create a turret behavior FSM.

    States: idle, scanning, tracking, engaging, cooldown

    Also includes legacy state names (reloading) as aliases so that
    old tests referencing state_names work.
    """

    class IdleState(State):
        """Turret powers up, brief delay before scanning."""
        def tick(self, dt: float, ctx: dict) -> str | None:
            # After ~1s, start scanning
            if self._sm_time_in_state and self._sm_time_in_state() >= 1.0:
                return "scanning"
            return None

    class ScanningState(State):
        """Turret rotates looking for targets."""
        def tick(self, dt: float, ctx: dict) -> str | None:
            enemies = ctx.get("enemies_in_range", [])
            if enemies:
                return "tracking"
            return None

    class TrackingState(State):
        """Turret has a target, slewing to aim."""
        def tick(self, dt: float, ctx: dict) -> str | None:
            enemies = ctx.get("enemies_in_range", [])
            if not enemies:
                return "scanning"
            if ctx.get("aimed_at_target", False):
                return "engaging"
            return None

    class EngagingState(State):
        """Turret is firing at target."""
        def tick(self, dt: float, ctx: dict) -> str | None:
            enemies = ctx.get("enemies_in_range", [])
            if not enemies:
                return "scanning"
            if ctx.get("just_fired", False):
                return "cooldown"
            return None

    class CooldownState(State):
        """Weapon cooling down after firing."""
        def tick(self, dt: float, ctx: dict) -> str | None:
            # Brief cooldown (~1s), then back to scanning
            if self._sm_time_in_state and self._sm_time_in_state() >= 1.0:
                return "scanning"
            return None

    sm = StateMachine("idle")

    idle = IdleState("idle")
    scanning = ScanningState("scanning", min_duration=0.5)
    tracking = TrackingState("tracking")
    engaging = EngagingState("engaging")
    cooldown = CooldownState("cooldown")
    # Legacy alias
    reloading = State("reloading")

    # Wire up time_in_state access via closure
    for s in (idle, scanning, tracking, engaging, cooldown):
        s._sm_time_in_state = lambda: sm.time_in_state

    sm.add_state(idle)
    sm.add_state(scanning)
    sm.add_state(tracking)
    sm.add_state(engaging)
    sm.add_state(cooldown)
    sm.add_state(reloading)

    # Condition-based transitions (used by engine context)
    # scanning -> tracking when enemies detected
    sm.add_transition(
        "scanning", "tracking",
        condition=lambda ctx: bool(ctx.get("enemies_in_range")),
    )
    # tracking -> engaging when aimed and not jammed
    sm.add_transition(
        "tracking", "engaging",
        condition=lambda ctx: (
            ctx.get("aimed_at_target", False)
            and bool(ctx.get("enemies_in_range"))
        ),
        guard=lambda ctx: ctx.get("degradation", 0.0) < 0.8,
    )
    # engaging -> cooldown on fire
    sm.add_transition(
        "engaging", "cooldown",
        condition=lambda ctx: ctx.get("just_fired", False),
    )
    # Any combat state -> scanning when no enemies
    for src in ("tracking", "engaging", "cooldown"):
        sm.add_transition(
            src, "scanning",
            condition=lambda ctx: not ctx.get("enemies_in_range"),
        )
    # cooldown -> scanning after time (handled by tick return)
    # reloading -> scanning (legacy compat)
    sm.add_transition("reloading", "scanning", condition=lambda ctx: True)
    # idle -> scanning (also handled by tick return, but add condition too)
    sm.add_transition(
        "idle", "scanning",
        condition=lambda ctx: True,  # always transition out of idle
    )

    return sm


# ============================================================================
# Rover FSM
# ============================================================================

def create_rover_fsm() -> StateMachine:
    """Create a rover behavior FSM.

    States: idle, patrolling, pursuing, engaging, retreating, rtb
    """

    sm = StateMachine("idle")

    sm.add_state(State("idle"))
    sm.add_state(State("patrolling"))
    sm.add_state(State("pursuing", max_duration=20.0, max_duration_target="patrolling"))
    sm.add_state(State("engaging"))
    sm.add_state(State("retreating", min_duration=2.0))
    sm.add_state(State("rtb"))

    # idle -> engaging when enemy in weapon range (highest priority from idle)
    sm.add_transition(
        "idle", "engaging",
        condition=lambda ctx: (
            bool(ctx.get("enemies_in_range"))
            and ctx.get("enemy_in_weapon_range", False)
        ),
        guard=lambda ctx: ctx.get("degradation", 0.0) < 0.8,
        priority=5,
    )

    # idle -> pursuing when enemy in range (higher priority than patrolling)
    sm.add_transition(
        "idle", "pursuing",
        condition=lambda ctx: bool(ctx.get("enemies_in_range")),
        priority=3,
    )

    # idle -> patrolling when waypoints available (lowest priority from idle)
    sm.add_transition(
        "idle", "patrolling",
        condition=lambda ctx: ctx.get("has_waypoints", False),
        priority=1,
    )

    # patrolling -> pursuing when enemies spotted
    sm.add_transition(
        "patrolling", "pursuing",
        condition=lambda ctx: bool(ctx.get("enemies_in_range")),
    )

    # pursuing -> engaging when in weapon range
    sm.add_transition(
        "pursuing", "engaging",
        condition=lambda ctx: ctx.get("enemy_in_weapon_range", False),
        guard=lambda ctx: ctx.get("degradation", 0.0) < 0.8,
    )

    # engaging -> retreating when low health (high priority)
    sm.add_transition(
        "engaging", "retreating",
        condition=lambda ctx: ctx.get("health_pct", 1.0) < 0.3,
        priority=10,
    )

    # engaging -> pursuing when enemy leaves weapon range
    sm.add_transition(
        "engaging", "pursuing",
        condition=lambda ctx: (
            bool(ctx.get("enemies_in_range"))
            and not ctx.get("enemy_in_weapon_range", False)
        ),
    )

    # engaging -> patrolling when no enemies
    sm.add_transition(
        "engaging", "patrolling",
        condition=lambda ctx: not ctx.get("enemies_in_range"),
    )

    # retreating -> rtb when enemies leave
    sm.add_transition(
        "retreating", "rtb",
        condition=lambda ctx: (
            not ctx.get("enemies_in_range")
            and ctx.get("health_pct", 1.0) < 0.5
        ),
    )

    # retreating -> rtb when still low health and enemies gone
    sm.add_transition(
        "retreating", "rtb",
        condition=lambda ctx: not ctx.get("enemies_in_range"),
    )

    # pursuing -> patrolling when enemies disappear
    sm.add_transition(
        "pursuing", "patrolling",
        condition=lambda ctx: (
            not ctx.get("enemies_in_range")
            and ctx.get("has_waypoints", False)
        ),
    )

    return sm


# ============================================================================
# Drone FSM
# ============================================================================

def create_drone_fsm() -> StateMachine:
    """Create a drone behavior FSM.

    States: idle, scouting, orbiting, engaging, rtb
    """

    sm = StateMachine("idle")

    sm.add_state(State("idle"))
    sm.add_state(State("scouting"))
    sm.add_state(State("orbiting"))
    sm.add_state(State("engaging"))
    sm.add_state(State("rtb"))
    # Legacy aliases
    sm.add_state(State("strafing"))
    sm.add_state(State("retreating"))

    # idle -> scouting when waypoints
    sm.add_transition(
        "idle", "scouting",
        condition=lambda ctx: ctx.get("has_waypoints", False),
    )

    # scouting -> rtb when critically damaged (high priority)
    sm.add_transition(
        "scouting", "rtb",
        condition=lambda ctx: ctx.get("health_pct", 1.0) < 0.2,
        priority=10,
    )

    # scouting -> orbiting when enemies in range but not in weapon range
    sm.add_transition(
        "scouting", "orbiting",
        condition=lambda ctx: (
            bool(ctx.get("enemies_in_range"))
            and not ctx.get("enemy_in_weapon_range", False)
        ),
    )

    # scouting -> engaging when enemies in weapon range
    sm.add_transition(
        "scouting", "engaging",
        condition=lambda ctx: (
            bool(ctx.get("enemies_in_range"))
            and ctx.get("enemy_in_weapon_range", False)
        ),
    )

    # orbiting -> engaging when in weapon range
    sm.add_transition(
        "orbiting", "engaging",
        condition=lambda ctx: ctx.get("enemy_in_weapon_range", False),
    )

    # orbiting -> scouting when no enemies
    sm.add_transition(
        "orbiting", "scouting",
        condition=lambda ctx: not ctx.get("enemies_in_range"),
    )

    # orbiting -> rtb when critically damaged
    sm.add_transition(
        "orbiting", "rtb",
        condition=lambda ctx: ctx.get("health_pct", 1.0) < 0.2,
        priority=10,
    )

    # engaging -> rtb when critically damaged (high priority)
    sm.add_transition(
        "engaging", "rtb",
        condition=lambda ctx: ctx.get("health_pct", 1.0) < 0.2,
        priority=10,
    )

    # engaging -> orbiting when enemy leaves weapon range
    sm.add_transition(
        "engaging", "orbiting",
        condition=lambda ctx: (
            bool(ctx.get("enemies_in_range"))
            and not ctx.get("enemy_in_weapon_range", False)
        ),
    )

    # engaging -> scouting when no enemies
    sm.add_transition(
        "engaging", "scouting",
        condition=lambda ctx: not ctx.get("enemies_in_range"),
    )

    return sm


# ============================================================================
# Hostile FSM
# ============================================================================

def create_hostile_fsm() -> StateMachine:
    """Create a hostile behavior FSM.

    States: spawning, advancing, reconning, engaging, flanking, suppressing,
            retreating_under_fire, fleeing
    """

    class SpawningState(State):
        """Hostile spawns in, brief invulnerability period."""
        def tick(self, dt: float, ctx: dict) -> str | None:
            # After ~1s, start advancing
            if self._sm_time_in_state and self._sm_time_in_state() >= 1.0:
                return "advancing"
            return None

    sm = StateMachine("spawning")

    spawning = SpawningState("spawning", min_duration=0.8)
    spawning._sm_time_in_state = lambda: sm.time_in_state

    sm.add_state(spawning)
    sm.add_state(State("advancing"))
    sm.add_state(State("reconning"))
    sm.add_state(State("engaging"))
    sm.add_state(State("flanking"))
    sm.add_state(State("suppressing"))
    sm.add_state(State("retreating_under_fire", max_duration=10.0, max_duration_target="advancing"))
    sm.add_state(State("fleeing", max_duration=15.0, max_duration_target="advancing"))
    # Legacy aliases
    sm.add_state(State("approaching"))
    sm.add_state(State("attacking"))
    sm.add_state(State("dodging"))

    # spawning -> advancing after spawn timer (handled by tick return + min_duration)
    sm.add_transition(
        "spawning", "advancing",
        condition=lambda ctx: True,  # tick return handles timing
    )

    # advancing -> fleeing when low health (highest priority)
    sm.add_transition(
        "advancing", "fleeing",
        condition=lambda ctx: ctx.get("health_pct", 1.0) < 0.3,
        priority=20,
    )

    # advancing -> engaging when enemies in range AND in weapon range
    sm.add_transition(
        "advancing", "engaging",
        condition=lambda ctx: (
            bool(ctx.get("enemies_in_range"))
            and ctx.get("enemy_in_weapon_range", False)
        ),
        priority=5,
    )

    # advancing -> flanking when enemies in range AND nearest is stationary
    sm.add_transition(
        "advancing", "flanking",
        condition=lambda ctx: (
            bool(ctx.get("enemies_in_range"))
            and ctx.get("nearest_enemy_stationary", False)
            and not ctx.get("enemy_in_weapon_range", False)
        ),
        priority=3,
    )

    # advancing -> reconning when enemies at recon range but not in weapon range
    # and nearest enemy is NOT stationary (stationary -> flanking instead)
    sm.add_transition(
        "advancing", "reconning",
        condition=lambda ctx: (
            bool(ctx.get("enemies_in_range"))
            and ctx.get("enemies_at_recon_range", False)
            and not ctx.get("enemy_in_weapon_range", False)
            and not ctx.get("nearest_enemy_stationary", False)
        ),
        priority=2,
    )

    # --- Reconning transitions ---

    # reconning -> advancing when detected by sensor (cover blown, highest priority)
    sm.add_transition(
        "reconning", "advancing",
        condition=lambda ctx: ctx.get("detected", False),
        priority=15,
    )

    # reconning -> engaging when in weapon range
    sm.add_transition(
        "reconning", "engaging",
        condition=lambda ctx: ctx.get("enemy_in_weapon_range", False),
        priority=10,
    )

    # reconning -> flanking when nearest enemy is stationary (turret spotted)
    sm.add_transition(
        "reconning", "flanking",
        condition=lambda ctx: ctx.get("nearest_enemy_stationary", False),
        priority=5,
    )

    # reconning -> advancing when no enemies at recon range (all clear)
    sm.add_transition(
        "reconning", "advancing",
        condition=lambda ctx: not ctx.get("enemies_at_recon_range", False),
        priority=1,
    )

    # --- Engaging transitions ---

    # engaging -> retreating_under_fire when low health AND cover available
    sm.add_transition(
        "engaging", "retreating_under_fire",
        condition=lambda ctx: (
            ctx.get("health_pct", 1.0) < 0.3
            and ctx.get("cover_available", False)
        ),
        priority=15,
    )

    # engaging -> fleeing when low health (no cover)
    sm.add_transition(
        "engaging", "fleeing",
        condition=lambda ctx: ctx.get("health_pct", 1.0) < 0.3,
        priority=10,
    )

    # engaging -> suppressing when ally is flanking and enemy is stationary and in weapon range
    sm.add_transition(
        "engaging", "suppressing",
        condition=lambda ctx: (
            ctx.get("ally_is_flanking", False)
            and ctx.get("nearest_enemy_stationary", False)
            and ctx.get("enemy_in_weapon_range", False)
        ),
        priority=3,
    )

    # engaging -> advancing when no enemies
    sm.add_transition(
        "engaging", "advancing",
        condition=lambda ctx: not ctx.get("enemies_in_range"),
    )

    # --- Suppressing transitions ---

    # suppressing -> retreating_under_fire when detected (position compromised)
    sm.add_transition(
        "suppressing", "retreating_under_fire",
        condition=lambda ctx: ctx.get("detected", False),
        priority=20,
    )

    # suppressing -> fleeing/retreating when low health (high priority)
    sm.add_transition(
        "suppressing", "fleeing",
        condition=lambda ctx: ctx.get("health_pct", 1.0) < 0.3,
        priority=15,
    )

    # suppressing -> engaging when ally stops flanking
    sm.add_transition(
        "suppressing", "engaging",
        condition=lambda ctx: not ctx.get("ally_is_flanking", False),
        priority=5,
    )

    # --- Retreating under fire transitions ---

    # retreating_under_fire -> advancing when enemies leave and health recovers
    sm.add_transition(
        "retreating_under_fire", "advancing",
        condition=lambda ctx: (
            not ctx.get("enemies_in_range")
            and ctx.get("health_pct", 1.0) >= 0.3
        ),
        priority=5,
    )

    # retreating_under_fire -> fleeing when no cover left
    sm.add_transition(
        "retreating_under_fire", "fleeing",
        condition=lambda ctx: (
            not ctx.get("cover_available", False)
            and ctx.get("health_pct", 1.0) < 0.3
        ),
        priority=3,
    )

    # --- Flanking transitions ---

    # flanking -> engaging when in weapon range
    sm.add_transition(
        "flanking", "engaging",
        condition=lambda ctx: ctx.get("enemy_in_weapon_range", False),
    )

    # flanking -> fleeing when low health (high priority)
    sm.add_transition(
        "flanking", "fleeing",
        condition=lambda ctx: ctx.get("health_pct", 1.0) < 0.3,
        priority=10,
    )

    # flanking -> advancing when no enemies
    sm.add_transition(
        "flanking", "advancing",
        condition=lambda ctx: not ctx.get("enemies_in_range"),
    )

    # --- Fleeing transitions ---

    # fleeing -> advancing when health recovers (unlikely, but for rally)
    sm.add_transition(
        "fleeing", "advancing",
        condition=lambda ctx: ctx.get("health_pct", 1.0) >= 0.5,
    )

    return sm


# ============================================================================
# Factory router
# ============================================================================

def create_fsm_for_type(asset_type: str, alliance: str = "friendly") -> StateMachine | None:
    """Create the appropriate FSM for a unit type and alliance.

    Returns None for unit types that don't have FSMs (vehicles, animals, etc.)
    """
    # Hostile types
    if asset_type in ("hostile_person", "hostile_leader", "hostile_vehicle"):
        return create_hostile_fsm()
    if asset_type == "person" and alliance == "hostile":
        return create_hostile_fsm()

    # Neutral persons get no FSM
    if asset_type == "person" and alliance in ("neutral", "friendly"):
        return None

    # Friendly/default types
    if asset_type in ("turret", "heavy_turret", "missile_turret"):
        return create_turret_fsm()
    if asset_type in ("rover", "tank", "apc"):
        return create_rover_fsm()
    if asset_type in ("drone", "scout_drone"):
        return create_drone_fsm()

    # No FSM for non-combatant types (vehicle, animal, unknown)
    return None
