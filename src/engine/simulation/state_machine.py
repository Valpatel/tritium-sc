# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""State machine infrastructure for unit behavior FSMs.

Provides generic State, Transition, and StateMachine classes that can be
composed into per-unit-type behavior FSMs.

Architecture:
  - State: named state with on_enter/on_exit/tick callbacks (subclassable)
  - Transition: condition-based edge between states (kept as dataclass for compat)
  - StateMachine: builder-pattern FSM with add_state/add_transition

The FSM is driven by the engine's tick loop.  Each tick:
  1. Accumulate time_in_state
  2. Call current state's tick() — if it returns a state name, transition
  3. If no tick-return, evaluate condition-based transitions (first match wins)
  4. If a transition fires, call on_exit -> set new state -> call on_enter
  5. Call current state's on_tick callback (if set)

Supports both the new builder API::

    sm = StateMachine("idle")
    sm.add_state(State("idle"))
    sm.add_transition("idle", "alert", lambda ctx: ctx.get("enemy"))
    sm.tick(0.1, {"enemy": True})

And the legacy constructor API (backward compatible)::

    sm = StateMachine(states=[State("a"), State("b")],
                      transitions=[Transition("a", "b", lambda: True)],
                      initial_state="a")
    sm.tick(0.1)
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Callable


class State:
    """A named state in a finite state machine.

    Can be used directly with callback arguments, or subclassed with
    on_enter/on_exit/tick methods overridden.

    Args:
        name: Unique state identifier.
        on_enter: Callback when entering this state. Signature: (ctx: dict) -> None.
                  For legacy compat, also accepts () -> None.
        on_exit: Callback when leaving this state. Signature: (ctx: dict) -> None.
                 For legacy compat, also accepts () -> None.
        on_tick: Callback called each tick while in this state.
                 Signature: (ctx: dict, dt: float) -> None.
                 For legacy compat, also accepts (dt: float) -> None.
        min_duration: Minimum time (seconds) before any transition can fire.
        max_duration: Maximum time (seconds) before auto-transitioning.
        max_duration_target: State name to auto-transition to after max_duration.
    """

    def __init__(
        self,
        name: str,
        on_enter: Callable | None = None,
        on_exit: Callable | None = None,
        on_tick: Callable | None = None,
        min_duration: float = 0.0,
        max_duration: float = 0.0,
        max_duration_target: str | None = None,
    ) -> None:
        self.name = name
        self._on_enter_cb = on_enter
        self._on_exit_cb = on_exit
        self._on_tick_cb = on_tick
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.max_duration_target = max_duration_target

    def on_enter(self, ctx: dict) -> None:
        """Called when entering this state. Override in subclasses."""
        if self._on_enter_cb is not None:
            _safe_call_ctx(self._on_enter_cb, ctx)

    def on_exit(self, ctx: dict) -> None:
        """Called when leaving this state. Override in subclasses."""
        if self._on_exit_cb is not None:
            _safe_call_ctx(self._on_exit_cb, ctx)

    def tick(self, dt: float, ctx: dict) -> str | None:
        """Called each tick. Return a state name to trigger transition, or None.

        Override in subclasses for custom per-tick logic.
        """
        if self._on_tick_cb is not None:
            _safe_call_on_tick(self._on_tick_cb, ctx, dt)
        return None


def _safe_call_ctx(fn: Callable, ctx: dict) -> None:
    """Call a callback that may accept (ctx) or () for backward compat."""
    import inspect
    try:
        sig = inspect.signature(fn)
        params = [
            p for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        if len(params) == 0:
            fn()
        else:
            fn(ctx)
    except (ValueError, TypeError):
        # Fallback: try with ctx, then without
        try:
            fn(ctx)
        except TypeError:
            fn()


def _safe_call_on_tick(fn: Callable, ctx: dict, dt: float) -> None:
    """Call an on_tick callback that may accept (ctx, dt), (dt,), or (dt) for backward compat."""
    import inspect
    try:
        sig = inspect.signature(fn)
        params = [
            p for p in sig.parameters.values()
            if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        n_params = len(params)
        if n_params >= 2:
            fn(ctx, dt)
        elif n_params == 1:
            fn(dt)
        else:
            fn()
    except (ValueError, TypeError):
        try:
            fn(ctx, dt)
        except TypeError:
            try:
                fn(dt)
            except TypeError:
                fn()


@dataclass
class Transition:
    """A conditional edge between two states.

    Kept as a dataclass for backward compatibility with __init__.py exports
    and the legacy constructor API.

    In legacy mode, condition takes no arguments: () -> bool.
    In builder mode, condition takes ctx: (dict) -> bool.
    """
    from_state: str
    to_state: str
    condition: Callable = field(default_factory=lambda: lambda: False)
    on_transition: Callable | None = None


class _BuilderTransition:
    """Internal transition used by the builder API."""

    __slots__ = ("from_state", "to_state", "condition", "guard", "priority")

    def __init__(
        self,
        from_state: str,
        to_state: str,
        condition: Callable[[dict], bool],
        guard: Callable[[dict], bool] | None = None,
        priority: int = 0,
    ) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.condition = condition
        self.guard = guard
        self.priority = priority


class StateMachine:
    """Generic finite state machine supporting both builder and legacy APIs.

    Builder pattern (new)::

        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("alert"))
        sm.add_transition("idle", "alert", lambda ctx: ctx.get("enemy"))
        sm.tick(0.1, {"enemy": True})

    Legacy constructor pattern::

        sm = StateMachine(
            states=[State("a"), State("b")],
            transitions=[Transition("a", "b", lambda: True)],
            initial_state="a",
        )
        sm.tick(0.1)
    """

    def __init__(
        self,
        initial_state: str | None = None,
        history_limit: int = 20,
        *,
        states: list[State] | None = None,
        transitions: list[Transition] | None = None,
    ) -> None:
        self._history_limit = history_limit
        self._history: list[tuple[float, str, str]] = []
        self._time_in_state: float = 0.0
        self._entered_initial: bool = False

        if states is not None:
            # Legacy constructor mode
            self._states: dict[str, State] = {s.name: s for s in states}
            self._legacy_transitions: list[Transition] = transitions or []
            self._builder_transitions: list[_BuilderTransition] = []
            self._legacy_mode = True
            if initial_state is None:
                raise ValueError("initial_state is required")
            self._current_name: str = initial_state
            if initial_state not in self._states:
                raise ValueError(f"Initial state '{initial_state}' not found in states")
            # Call on_enter for initial state (legacy behavior)
            state = self._states[initial_state]
            state.on_enter({})
            self._entered_initial = True
        else:
            # Builder mode
            self._states = {}
            self._legacy_transitions = []
            self._builder_transitions = []
            self._legacy_mode = False
            if initial_state is None:
                raise ValueError("initial_state is required")
            self._current_name = initial_state
            # Don't call on_enter yet — states haven't been added.
            # on_enter for initial state fires on first tick.

    def add_state(self, state: State) -> None:
        """Register a state object."""
        self._states[state.name] = state

    def add_transition(
        self,
        from_state: str,
        to_state: str,
        condition: Callable[[dict], bool] = lambda ctx: False,
        guard: Callable[[dict], bool] | None = None,
        priority: int = 0,
    ) -> None:
        """Add a conditional transition.

        Args:
            from_state: Source state name.
            to_state: Target state name.
            condition: Function receiving ctx dict, returns bool.
            guard: Optional additional guard; both condition AND guard must
                   return True for the transition to fire.
            priority: Higher priority transitions are evaluated first.
        """
        self._builder_transitions.append(
            _BuilderTransition(from_state, to_state, condition, guard, priority)
        )

    @property
    def current_state(self) -> str:
        """Return the current state NAME (string)."""
        return self._current_name

    @property
    def current(self) -> State:
        """Return the current State object (backward compat)."""
        return self._states[self._current_name]

    @property
    def state_names(self) -> list[str]:
        """Return all registered state names."""
        return list(self._states.keys())

    @property
    def time_in_state(self) -> float:
        """Time spent in the current state (resets on transition)."""
        return self._time_in_state

    @property
    def time_in_current_state(self) -> float:
        """Alias for time_in_state (v2 compat)."""
        return self._time_in_state

    @property
    def history(self) -> list[tuple[float, str, str]]:
        """Return a copy of transition history: [(timestamp, from_state, to_state), ...]."""
        return list(self._history)

    def tick(self, dt: float, ctx: dict | None = None) -> None:
        """Advance the FSM by *dt* seconds.

        Args:
            dt: Time delta in seconds.
            ctx: Context dict passed to conditions, guards, and state callbacks.
                 Optional for backward compat with legacy (no-ctx) mode.
        """
        if ctx is None:
            ctx = {}

        # Accumulate time in state
        self._time_in_state += dt

        # On first tick in builder mode, fire on_enter for initial state
        if not self._entered_initial:
            self._entered_initial = True
            state = self._states.get(self._current_name)
            if state is not None:
                state.on_enter(ctx)

        current_state = self._states.get(self._current_name)

        if self._legacy_mode:
            self._tick_legacy(dt, ctx, current_state)
        else:
            self._tick_builder(dt, ctx, current_state)

    def _tick_legacy(self, dt: float, ctx: dict, current_state: State | None) -> None:
        """Legacy tick: evaluate Transition objects, then call on_tick."""
        # Check max_duration auto-transition
        if current_state is not None and self._check_max_duration(current_state, ctx):
            current_state = self._states.get(self._current_name)

        # Evaluate legacy transitions
        for t in self._legacy_transitions:
            if t.from_state != self._current_name:
                continue
            if t.condition():
                self._do_legacy_transition(t, ctx)
                break

        # Tick current state
        current_state = self._states.get(self._current_name)
        if current_state is not None:
            result = current_state.tick(dt, ctx)
            # Legacy mode: tick return is ignored (old behavior)

    def _do_legacy_transition(self, t: Transition, ctx: dict) -> None:
        """Execute a legacy Transition."""
        old_name = self._current_name
        old_state = self._states.get(old_name)
        if old_state is not None:
            old_state.on_exit(ctx)
        if t.on_transition is not None:
            t.on_transition()
        self._current_name = t.to_state
        self._record_history(old_name, t.to_state)
        self._time_in_state = 0.0
        new_state = self._states.get(self._current_name)
        if new_state is not None:
            new_state.on_enter(ctx)

    def _tick_builder(self, dt: float, ctx: dict, current_state: State | None) -> None:
        """Builder tick: conditions first, then tick-return, with min/max duration.

        Order of operations:
          1. Check min_duration — block all transitions if still in minimum period
          2. Check max_duration — auto-transition if expired
          3. Evaluate condition-based transitions (priority sorted, first match wins)
          4. If a condition fired: transition, skip tick/on_tick on old state
          5. If no condition fired: call state.tick()
          6. If tick() returned a state name: transition
        """
        if current_state is None:
            return

        # Check min_duration — if we haven't been in this state long enough,
        # block all transitions (both tick-return and conditions)
        min_dur = getattr(current_state, "min_duration", 0.0)
        transitions_blocked = min_dur > 0 and self._time_in_state < min_dur

        # Check max_duration auto-transition (only if not blocked)
        if not transitions_blocked:
            if self._check_max_duration(current_state, ctx):
                # State changed via max_duration — tick the new state
                current_state = self._states.get(self._current_name)
                if current_state is not None:
                    current_state.tick(dt, ctx)
                return

        if not transitions_blocked:
            # Evaluate condition-based transitions sorted by priority (desc),
            # then by insertion order (stable sort)
            matching = [
                t for t in self._builder_transitions
                if t.from_state == self._current_name
            ]
            # Sort by priority descending (higher priority first), stable
            matching.sort(key=lambda t: -t.priority)

            for t in matching:
                if t.condition(ctx):
                    if t.guard is not None and not t.guard(ctx):
                        continue
                    self._do_transition(t.to_state, ctx)
                    return

        # No condition-based transition fired — tick the current state
        tick_result = current_state.tick(dt, ctx)

        if not transitions_blocked:
            # State.tick() return can trigger a transition
            if tick_result is not None and tick_result in self._states:
                self._do_transition(tick_result, ctx)
                return

    def _check_max_duration(self, current_state: State, ctx: dict) -> bool:
        """Check if max_duration has expired and auto-transition if so.

        Returns True if a transition occurred.
        """
        max_dur = getattr(current_state, "max_duration", 0.0)
        max_target = getattr(current_state, "max_duration_target", None)
        if max_dur > 0 and max_target is not None and self._time_in_state >= max_dur:
            if max_target in self._states:
                self._do_transition(max_target, ctx)
                return True
        return False

    def _do_transition(self, target_state: str, ctx: dict) -> None:
        """Execute a transition to target_state, calling on_exit/on_enter."""
        old_name = self._current_name
        old_state = self._states.get(old_name)
        if old_state is not None:
            old_state.on_exit(ctx)
        self._current_name = target_state
        self._record_history(old_name, target_state)
        self._time_in_state = 0.0
        new_state = self._states.get(target_state)
        if new_state is not None:
            new_state.on_enter(ctx)

    def _record_history(self, from_state: str, to_state: str) -> None:
        """Record a transition in history, respecting the limit."""
        self._history.append((_time.time(), from_state, to_state))
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit:]

    def force_state(self, state_name: str) -> None:
        """Force a transition to a specific state (skip conditions).

        Backward compatible with legacy API.
        """
        if state_name not in self._states:
            raise ValueError(f"State '{state_name}' not found")
        old_name = self._current_name
        old_state = self._states.get(old_name)
        if old_state is not None:
            old_state.on_exit({})
        self._current_name = state_name
        self._record_history(old_name, state_name)
        self._time_in_state = 0.0
        new_state = self._states[state_name]
        new_state.on_enter({})
