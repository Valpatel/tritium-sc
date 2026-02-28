# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""NPC FSM factories — state machines for civilian pedestrians, vehicles, animals.

Each factory creates a StateMachine using the builder API. The FSMs are
driven by a context dict with keys like ``danger_nearby``, ``interest_nearby``,
``cover_available``, etc. — set by the NPCBrain on each tick.

These FSMs are simpler than combatant FSMs (no weapon/health checks) because
NPCs don't fight. Their states model *civilian reactions*: flee, hide, observe,
rubberneck, panic.
"""

from __future__ import annotations

from engine.simulation.state_machine import State, StateMachine


# ============================================================================
# Civilian Pedestrian FSM (7 states)
# ============================================================================

def create_civilian_pedestrian_fsm() -> StateMachine:
    """Create a civilian pedestrian behavior FSM.

    States: walking, pausing, observing, fleeing, hiding, curious, panicking

    Priority transitions:
    - danger_nearby -> fleeing (priority 20, overrides all)
    - cover_available while fleeing -> hiding (priority 10)
    - close danger + no cover while fleeing -> panicking (priority 15)
    - interest + high curiosity -> curious (priority 5)
    - curious + close interest -> observing (priority 3)
    - Timed states auto-return to walking via max_duration
    """
    sm = StateMachine("walking")

    sm.add_state(State("walking"))
    sm.add_state(State("pausing", max_duration=15.0, max_duration_target="walking"))
    sm.add_state(State("observing", max_duration=10.0, max_duration_target="walking"))
    sm.add_state(State("fleeing", max_duration=20.0, max_duration_target="walking"))
    sm.add_state(State("hiding", max_duration=30.0, max_duration_target="walking"))
    sm.add_state(State("curious", max_duration=15.0, max_duration_target="walking"))
    sm.add_state(State("panicking", max_duration=15.0, max_duration_target="fleeing"))

    # -- Danger overrides (from any state) --

    for src in ("walking", "pausing", "observing", "curious", "hiding"):
        sm.add_transition(
            src, "fleeing",
            condition=lambda ctx: ctx.get("danger_nearby", False),
            priority=20,
        )

    # panicking -> fleeing also possible via max_duration

    # -- Fleeing transitions --

    # fleeing -> panicking when close danger and no cover (higher priority than hiding)
    sm.add_transition(
        "fleeing", "panicking",
        condition=lambda ctx: (
            ctx.get("danger_nearby", False)
            and ctx.get("danger_distance", 999.0) < 8.0
            and not ctx.get("cover_available", False)
        ),
        priority=15,
    )

    # fleeing -> hiding when cover available
    sm.add_transition(
        "fleeing", "hiding",
        condition=lambda ctx: (
            ctx.get("danger_nearby", False)
            and ctx.get("cover_available", False)
        ),
        priority=10,
    )

    # -- Interest transitions --

    # walking -> curious when interest + high curiosity
    sm.add_transition(
        "walking", "curious",
        condition=lambda ctx: (
            ctx.get("interest_nearby", False)
            and ctx.get("curiosity", 0.0) > 0.5
            and not ctx.get("danger_nearby", False)
        ),
        priority=5,
    )

    # curious -> observing when close to interest source
    sm.add_transition(
        "curious", "observing",
        condition=lambda ctx: (
            ctx.get("interest_nearby", False)
            and ctx.get("interest_distance", 999.0) < 10.0
            and not ctx.get("danger_nearby", False)
        ),
        priority=3,
    )

    return sm


# ============================================================================
# Civilian Vehicle FSM (5 states)
# ============================================================================

def create_civilian_vehicle_fsm() -> StateMachine:
    """Create a civilian vehicle behavior FSM.

    States: driving, stopped, yielding, evading, parked

    Priority transitions:
    - danger_nearby -> evading (priority 20, overrides all)
    - obstacle_ahead -> stopped (priority 5)
    - emergency_nearby -> yielding (priority 10)
    - Timed states auto-return to driving via max_duration
    """
    sm = StateMachine("driving")

    sm.add_state(State("driving"))
    sm.add_state(State("stopped", max_duration=8.0, max_duration_target="driving"))
    sm.add_state(State("yielding", max_duration=10.0, max_duration_target="driving"))
    sm.add_state(State("evading", max_duration=15.0, max_duration_target="driving"))
    sm.add_state(State("parked", max_duration=30.0, max_duration_target="driving"))

    # -- Danger overrides (from any state) --

    for src in ("driving", "stopped", "yielding", "parked"):
        sm.add_transition(
            src, "evading",
            condition=lambda ctx: ctx.get("danger_nearby", False),
            priority=20,
        )

    # -- Driving transitions --

    # driving -> yielding for emergency (higher priority than stopped)
    sm.add_transition(
        "driving", "yielding",
        condition=lambda ctx: (
            ctx.get("emergency_nearby", False)
            and not ctx.get("danger_nearby", False)
        ),
        priority=10,
    )

    # driving -> stopped for obstacle
    sm.add_transition(
        "driving", "stopped",
        condition=lambda ctx: (
            ctx.get("obstacle_ahead", False)
            and not ctx.get("danger_nearby", False)
        ),
        priority=5,
    )

    # driving -> parked for high interest + curiosity
    sm.add_transition(
        "driving", "parked",
        condition=lambda ctx: (
            ctx.get("interest_nearby", False)
            and ctx.get("curiosity", 0.0) > 0.5
            and not ctx.get("danger_nearby", False)
            and not ctx.get("obstacle_ahead", False)
        ),
        priority=3,
    )

    return sm


# ============================================================================
# Animal FSM (5 states)
# ============================================================================

def create_animal_fsm() -> StateMachine:
    """Create an animal behavior FSM.

    States: wandering, resting, startled, fleeing, following

    Priority transitions:
    - loud_noise -> startled (priority 15)
    - startled auto-transitions to fleeing (max_duration 3s)
    - dog + person_nearby -> following (priority 5)
    - Timed states auto-return to wandering via max_duration
    """
    sm = StateMachine("wandering")

    sm.add_state(State("wandering"))
    sm.add_state(State("resting", max_duration=15.0, max_duration_target="wandering"))
    sm.add_state(State("startled", max_duration=3.0, max_duration_target="fleeing"))
    sm.add_state(State("fleeing", max_duration=15.0, max_duration_target="wandering"))
    sm.add_state(State("following", max_duration=30.0, max_duration_target="wandering"))

    # -- Noise overrides --

    for src in ("wandering", "resting", "following"):
        sm.add_transition(
            src, "startled",
            condition=lambda ctx: ctx.get("loud_noise", False),
            priority=15,
        )

    # -- Dog following --

    sm.add_transition(
        "wandering", "following",
        condition=lambda ctx: (
            ctx.get("is_dog", False)
            and ctx.get("person_nearby", False)
            and not ctx.get("loud_noise", False)
        ),
        priority=5,
    )

    return sm


# ============================================================================
# Factory router
# ============================================================================

def create_npc_fsm(asset_type: str, alliance: str) -> StateMachine | None:
    """Create the appropriate NPC FSM for neutral entities.

    Returns None for combatant types or hostile alliance (those use
    the existing create_hostile_fsm / create_turret_fsm etc.).
    """
    if alliance == "hostile":
        return None

    if asset_type == "person" and alliance in ("neutral", "friendly"):
        return create_civilian_pedestrian_fsm()
    if asset_type == "vehicle":
        return create_civilian_vehicle_fsm()
    if asset_type == "animal":
        return create_animal_fsm()

    return None
