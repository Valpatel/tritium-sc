"""Intercept prediction — proportional navigation and lead targeting.

Provides three functions used by the behavior and combat systems:

  - ``predict_intercept()`` — optimal intercept point for a pursuer
    chasing a moving target (classic proportional navigation).
  - ``lead_target()`` — where to aim a projectile to hit a moving target.
  - ``time_to_intercept()`` — estimated seconds until intercept.

The math is a closed-form solution to the "pursuit on a straight line"
problem.  Given a target at position P_t moving with velocity V_t, and a
pursuer at position P_p with scalar speed S_p, we solve for the time T
when the pursuer can reach the target:

    |P_t + V_t * T - P_p| = S_p * T

Squaring both sides yields a quadratic in T:

    (|V_t|^2 - S_p^2) * T^2 + 2 * dot(D, V_t) * T + |D|^2 = 0

where D = P_t - P_p.  The smallest positive root T gives the intercept
time; the intercept point is P_t + V_t * T.

If the quadratic has no positive real roots (target is uncatchable), we
fall back to the target's current position.
"""

from __future__ import annotations

import math

# Sentinel for "uncatchable" intercept time
_UNCATCHABLE_TIME = 9999.0


def predict_intercept(
    pursuer_pos: tuple[float, float],
    pursuer_speed: float,
    target_pos: tuple[float, float],
    target_vel: tuple[float, float],
) -> tuple[float, float]:
    """Compute the optimal intercept point where pursuer meets target.

    Uses the quadratic intercept equation (proportional navigation).
    If interception is impossible (target too fast / running away),
    falls back to the target's current position.

    Args:
        pursuer_pos: (x, y) position of the pursuer.
        pursuer_speed: Scalar speed of the pursuer (m/s).
        target_pos: (x, y) current position of the target.
        target_vel: (vx, vy) velocity of the target (m/s).

    Returns:
        (x, y) predicted intercept point.
    """
    t = _solve_intercept_time(pursuer_pos, pursuer_speed, target_pos, target_vel)
    if t is None or t >= _UNCATCHABLE_TIME:
        return (float(target_pos[0]), float(target_pos[1]))
    return (
        float(target_pos[0] + target_vel[0] * t),
        float(target_pos[1] + target_vel[1] * t),
    )


def lead_target(
    shooter_pos: tuple[float, float],
    target_pos: tuple[float, float],
    target_vel: tuple[float, float],
    projectile_speed: float,
) -> tuple[float, float]:
    """Compute where to aim ahead of a moving target for projectile fire.

    Same quadratic solution as ``predict_intercept`` but from the
    perspective of a projectile (fixed speed, fired from shooter_pos).

    Args:
        shooter_pos: (x, y) position of the shooter.
        target_pos: (x, y) current position of the target.
        target_vel: (vx, vy) velocity of the target (m/s).
        projectile_speed: Speed of the projectile (m/s).

    Returns:
        (x, y) lead point to fire at.
    """
    t = _solve_intercept_time(shooter_pos, projectile_speed, target_pos, target_vel)
    if t is None or t >= _UNCATCHABLE_TIME:
        return (float(target_pos[0]), float(target_pos[1]))
    return (
        float(target_pos[0] + target_vel[0] * t),
        float(target_pos[1] + target_vel[1] * t),
    )


def time_to_intercept(
    pursuer_pos: tuple[float, float],
    pursuer_speed: float,
    target_pos: tuple[float, float],
    target_vel: tuple[float, float],
) -> float:
    """Estimate seconds until the pursuer can reach the moving target.

    Returns ``_UNCATCHABLE_TIME`` (9999.0) if interception is impossible.

    Args:
        pursuer_pos: (x, y) position of the pursuer.
        pursuer_speed: Scalar speed of the pursuer (m/s).
        target_pos: (x, y) current position of the target.
        target_vel: (vx, vy) velocity of the target (m/s).

    Returns:
        Estimated intercept time in seconds (>= 0).
    """
    t = _solve_intercept_time(pursuer_pos, pursuer_speed, target_pos, target_vel)
    if t is None:
        return _UNCATCHABLE_TIME
    return t


def target_velocity(heading: float, speed: float) -> tuple[float, float]:
    """Convert a target's heading+speed into a (vx, vy) velocity vector.

    The game coordinate system uses heading in degrees where 0=north (+y)
    and angles increase clockwise.  This matches ``atan2(dx, dy)`` used
    in ``SimulationTarget._tick_legacy``.

    Args:
        heading: Heading in degrees (0=north, clockwise).
        speed: Scalar speed (m/s).

    Returns:
        (vx, vy) velocity vector.
    """
    if speed <= 0.0:
        return (0.0, 0.0)
    rad = math.radians(heading)
    return (math.sin(rad) * speed, math.cos(rad) * speed)


# ---------------------------------------------------------------------------
# Internal solver
# ---------------------------------------------------------------------------

def _solve_intercept_time(
    pursuer_pos: tuple[float, float],
    pursuer_speed: float,
    target_pos: tuple[float, float],
    target_vel: tuple[float, float],
) -> float | None:
    """Solve the quadratic intercept equation for the smallest positive T.

    The equation is:
        |P_t + V_t * T - P_p|^2 = (S_p * T)^2

    Expanding:
        (Vx^2 + Vy^2 - S_p^2) * T^2 + 2*(Dx*Vx + Dy*Vy) * T + (Dx^2 + Dy^2) = 0

    where D = P_t - P_p.

    Returns the smallest positive T, or None if no positive root exists.
    """
    dx = target_pos[0] - pursuer_pos[0]
    dy = target_pos[1] - pursuer_pos[1]
    dist_sq = dx * dx + dy * dy

    # Already at target
    if dist_sq < 0.01:
        return 0.0

    # Pursuer can't move
    if pursuer_speed <= 0.0:
        return None

    vx, vy = target_vel
    v_sq = vx * vx + vy * vy

    # Target is stationary — simple distance / speed
    if v_sq < 1e-10:
        return math.sqrt(dist_sq) / pursuer_speed

    a = v_sq - pursuer_speed * pursuer_speed
    b = 2.0 * (dx * vx + dy * vy)
    c = dist_sq

    # Solve quadratic a*T^2 + b*T + c = 0
    if abs(a) < 1e-10:
        # Linear case: pursuer and target have nearly the same speed
        if abs(b) < 1e-10:
            return None  # Degenerate
        t = -c / b
        return t if t > 0.0 else None

    discriminant = b * b - 4.0 * a * c
    if discriminant < 0.0:
        return None  # No real solution — can't intercept

    sqrt_disc = math.sqrt(discriminant)
    t1 = (-b + sqrt_disc) / (2.0 * a)
    t2 = (-b - sqrt_disc) / (2.0 * a)

    # Pick the smallest positive root
    candidates = [t for t in (t1, t2) if t > 0.0]
    if not candidates:
        return None
    return min(candidates)
