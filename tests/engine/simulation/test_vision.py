# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for VisionSystem — TDD: these must fail first, then pass after implementation."""

import math
import time
import pytest

from engine.simulation.target import SimulationTarget
from engine.simulation.terrain import TerrainMap
from engine.simulation.spatial import SpatialGrid
from engine.simulation.vision import SightingReport, VisibilityState, VisionSystem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str,
    alliance: str = "friendly",
    asset_type: str = "turret",
    position: tuple[float, float] = (0.0, 0.0),
    heading: float = 0.0,
    **kwargs,
) -> SimulationTarget:
    """Create a minimal SimulationTarget for vision tests."""
    return SimulationTarget(
        target_id=target_id,
        name=target_id,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        heading=heading,
        speed=0.0 if asset_type == "turret" else 2.0,
        is_combatant=alliance != "neutral",
        **kwargs,
    )


def _build_grid(targets: list[SimulationTarget]) -> SpatialGrid:
    grid = SpatialGrid()
    grid.rebuild(targets)
    return grid


def _targets_dict(targets: list[SimulationTarget]) -> dict[str, SimulationTarget]:
    return {t.target_id: t for t in targets}


# ===========================================================================
# TestAmbientDetection
# ===========================================================================


class TestAmbientDetection:
    """Ambient radius is a 360-degree "close range awareness" check."""

    def test_within_ambient_detected(self):
        """Enemy within ambient_radius is detected regardless of heading."""
        # turret ambient_radius = 8.0
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (5, 0))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible

    def test_beyond_ambient_not_detected_by_ambient(self):
        """Enemy outside ambient_radius but facing away from cone is not seen."""
        # turret ambient_radius=8, cone_range=40, cone_angle=90, heading=0(north)
        # Put enemy at (0, -20) = directly south, outside ambient, outside cone
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, -20))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible

    def test_ambient_blocked_by_building(self):
        """Enemy within ambient radius but LOS blocked by building."""
        terrain = TerrainMap(200.0)
        # Place building between (0,0) and (5,0)
        terrain.set_cell(2.5, 0, "building")
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (5, 0))
        targets = [turret, enemy]
        vs = VisionSystem(terrain_map=terrain)
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible

    def test_ambient_ignores_heading(self):
        """Ambient detection works no matter which direction the unit faces."""
        # Turret facing north (heading=0), enemy behind it (south)
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, -5))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible


# ===========================================================================
# TestConeDetection
# ===========================================================================


class TestConeDetection:
    """Cone-based directional detection for units with cone_range > 0."""

    def test_in_cone_detected(self):
        """Enemy directly in front of turret within cone range is detected."""
        # turret: cone_range=40, cone_angle=90, heading=0(north)
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))  # north, within 40m cone
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible

    def test_out_of_arc_missed(self):
        """Enemy directly behind turret (outside 90 degree cone) is missed."""
        # turret heading=0(north), cone_angle=90 => +-45 degrees from north
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, -30))  # south, outside cone
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible

    def test_beyond_range_missed(self):
        """Enemy in front but beyond cone_range is not detected."""
        # turret cone_range=40, enemy at 50m north
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 50))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible

    def test_heading_matters(self):
        """Same enemy position — detected when turret faces it, missed when away."""
        enemy_pos = (30, 0)  # east
        enemy = _make_target("h1", "hostile", "person", enemy_pos)

        # Heading east (90 degrees) — should see
        turret_east = _make_target("t1", "friendly", "turret", (0, 0), heading=90)
        targets = [turret_east, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible

        # Heading west (270) — should not see
        turret_west = _make_target("t2", "friendly", "turret", (0, 0), heading=270)
        targets2 = [turret_west, enemy]
        state2 = vs.tick(0.1, _targets_dict(targets2), _build_grid(targets2))
        assert "h1" not in state2.friendly_visible

    def test_wide_cone_angle(self):
        """APC has 120-degree cone — enemy at 55 degrees off-axis seen."""
        # apc cone_range=25, cone_angle=120 => half=60
        apc = _make_target("a1", "friendly", "apc", (0, 0), heading=0)
        # 55 degrees east of north: x = 20*sin(55), y = 20*cos(55)
        ex = 20 * math.sin(math.radians(55))
        ey = 20 * math.cos(math.radians(55))
        enemy = _make_target("h1", "hostile", "person", (ex, ey))
        targets = [apc, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible

    def test_narrow_cone_misses_oblique(self):
        """Drone has 45-degree cone — enemy at 30 degrees off-axis is missed."""
        # drone cone_angle=45, so half=22.5; ambient_radius=20
        drone = _make_target("d1", "friendly", "drone", (0, 0), heading=0)
        # 30 degrees east of north at 35m (beyond ambient_radius=20, within cone_range=45)
        ex = 35 * math.sin(math.radians(30))
        ey = 35 * math.cos(math.radians(30))
        enemy = _make_target("h1", "hostile", "person", (ex, ey))
        targets = [drone, enemy]
        # Disable sweeping by using a fresh system and single tick
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible

    def test_edge_of_cone_detected(self):
        """Enemy exactly at half_angle - 1 degree should be detected."""
        # turret cone_angle=90, half=45. Enemy at 44 degrees off heading
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        ex = 30 * math.sin(math.radians(44))
        ey = 30 * math.cos(math.radians(44))
        enemy = _make_target("h1", "hostile", "person", (ex, ey))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible


# ===========================================================================
# TestOmnidirectional
# ===========================================================================


class TestOmnidirectional:
    """Units with cone_range==0 use 360-degree vision_radius."""

    def test_omni_within_radius_detected(self):
        """Person has cone_range=0, so uses vision_radius=15 as 360-degree."""
        # hostile_person: vision_radius=20, cone_range=0
        person = _make_target("p1", "friendly", "person", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (10, 0))
        targets = [person, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible

    def test_omni_beyond_radius_not_detected(self):
        """Enemy beyond vision_radius not detected for omni unit."""
        # person vision_radius=15
        person = _make_target("p1", "friendly", "person", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (20, 0))
        targets = [person, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible

    def test_omni_behind_unit_detected(self):
        """Omni vision sees targets behind the unit."""
        person = _make_target("p1", "friendly", "person", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, -10))  # south
        targets = [person, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible


# ===========================================================================
# TestLOSObstruction
# ===========================================================================


class TestLOSObstruction:
    """Line-of-sight blocked by buildings in terrain map."""

    def test_clear_los(self):
        """No buildings between observer and target — detected."""
        terrain = TerrainMap(200.0)
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [turret, enemy]
        vs = VisionSystem(terrain_map=terrain)
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible

    def test_building_blocks_cone(self):
        """Building between turret and enemy blocks cone detection."""
        terrain = TerrainMap(200.0)
        terrain.set_cell(0, 15, "building")
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [turret, enemy]
        vs = VisionSystem(terrain_map=terrain)
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible

    def test_building_blocks_ambient(self):
        """Building between observer and close enemy blocks ambient detection."""
        terrain = TerrainMap(200.0)
        terrain.set_cell(2.5, 0, "building")
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (5, 0))
        targets = [turret, enemy]
        vs = VisionSystem(terrain_map=terrain)
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible

    def test_no_terrain_means_clear_los(self):
        """Without a terrain map, LOS is always clear."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [turret, enemy]
        vs = VisionSystem()  # no terrain_map
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible

    def test_building_behind_target_no_block(self):
        """Building beyond the target does not block LOS to the target."""
        terrain = TerrainMap(200.0)
        terrain.set_cell(0, 40, "building")  # building at y=40, target at y=30
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [turret, enemy]
        vs = VisionSystem(terrain_map=terrain)
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible


# ===========================================================================
# TestSweepingCones
# ===========================================================================


class TestSweepingCones:
    """Sweeping cones rotate over time (drones, cameras)."""

    def test_sweep_rotation_updates(self):
        """After tick, sweep angle changes for sweeping unit."""
        # drone: cone_sweeps=True, cone_sweep_rpm=2.0
        drone = _make_target("d1", "friendly", "drone", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (30, 0))
        targets = [drone, enemy]
        vs = VisionSystem()
        vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        # After one tick at rpm=2.0, angle should change: 2 * 360 * 0.1 / 60 = 1.2 degrees
        assert "d1" in vs._sweep_angles
        assert abs(vs._sweep_angles["d1"]) > 0

    def test_periodic_reveal_as_sweep_passes(self):
        """Sweeping cone reveals target when facing it."""
        # Place enemy directly east at 30m, drone heading north
        drone = _make_target("d1", "friendly", "drone", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (30, 0))  # east
        targets = [drone, enemy]
        vs = VisionSystem()

        # Tick many times to rotate through 360 degrees
        # drone rpm=2.0, so full rotation = 60/2 = 30 seconds
        # We need about 90 degrees worth of rotation (quarter turn to face east)
        # 90 degrees / (2*360/60) = 90 / 12 = 7.5 seconds
        seen = False
        for _ in range(100):
            state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
            if "h1" in state.friendly_visible:
                seen = True
                break
        assert seen, "Sweeping cone should reveal target as it passes"

    def test_rpm_affects_speed(self):
        """Higher RPM causes faster sweep."""
        drone = _make_target("d1", "friendly", "drone", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (30, 0))
        targets = [drone, enemy]
        vs = VisionSystem()
        vs.tick(1.0, _targets_dict(targets), _build_grid(targets))
        angle1 = vs._sweep_angles.get("d1", 0)

        # drone rpm=2.0, so 1s tick = 2*360*1/60 = 12 degrees
        assert abs(angle1 - 12.0) < 0.5, f"Expected ~12 degrees, got {angle1}"

    def test_non_sweeping_unit_no_sweep_angle(self):
        """Turret (cone_sweeps=False) does not get a sweep angle."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [turret, enemy]
        vs = VisionSystem()
        vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "t1" not in vs._sweep_angles


# ===========================================================================
# TestDroneRelay
# ===========================================================================


class TestDroneRelay:
    """Drones share their vision with all friendlies."""

    def test_drone_seen_visible_to_all(self):
        """Target seen by drone is in friendly_visible and drone_relayed."""
        drone = _make_target("d1", "friendly", "drone", (0, 0), heading=0)
        # turret can't see enemy (behind it), but drone can
        turret = _make_target("t1", "friendly", "turret", (100, 100), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [drone, turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible
        assert "h1" in state.drone_relayed

    def test_non_drone_sighting_not_relayed(self):
        """Turret sighting is not in drone_relayed."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible
        assert "h1" not in state.drone_relayed

    def test_scout_drone_also_relays(self):
        """Scout drone relay works same as regular drone."""
        scout = _make_target("sd1", "friendly", "scout_drone", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [scout, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.drone_relayed

    def test_drone_relayed_targets_visible_even_to_blind_turret(self):
        """Turret with no direct LOS still benefits from drone relay."""
        # drone at (0,0) heading north sees enemy at (0,30)
        drone = _make_target("d1", "friendly", "drone", (0, 0), heading=0)
        # turret at (200, 200) can't see the enemy
        turret = _make_target("t1", "friendly", "turret", (200, 200), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [drone, turret, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        # The enemy should be in friendly_visible because drone relayed it
        assert "h1" in state.friendly_visible


# ===========================================================================
# TestExternalSightings
# ===========================================================================


class TestExternalSightings:
    """External (camera/robot) sighting reports."""

    def test_camera_sighting_adds_to_visible(self):
        """add_sighting from a camera makes target visible."""
        enemy = _make_target("h1", "hostile", "person", (50, 50))
        targets = [enemy]
        vs = VisionSystem()
        vs.add_sighting(SightingReport(
            observer_id="cam1",
            target_id="h1",
            observer_type="camera",
            confidence=0.9,
            position=(50, 50),
            timestamp=time.time(),
        ))
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible

    def test_robot_sighting_adds_to_visible(self):
        """add_sighting from a robot works the same."""
        enemy = _make_target("h1", "hostile", "person", (50, 50))
        targets = [enemy]
        vs = VisionSystem()
        vs.add_sighting(SightingReport(
            observer_id="robot1",
            target_id="h1",
            observer_type="robot",
            confidence=1.0,
        ))
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible

    def test_sighting_cleared_after_tick(self):
        """External sightings are consumed and cleared after each tick."""
        enemy = _make_target("h1", "hostile", "person", (200, 200))
        targets = [enemy]
        vs = VisionSystem()
        vs.add_sighting(SightingReport(
            observer_id="cam1",
            target_id="h1",
            observer_type="camera",
        ))
        state1 = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state1.friendly_visible
        # Second tick without new sighting — should not be visible
        state2 = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state2.friendly_visible

    def test_multiple_sightings_same_target(self):
        """Multiple sighting reports for same target are fine."""
        enemy = _make_target("h1", "hostile", "person", (50, 50))
        targets = [enemy]
        vs = VisionSystem()
        vs.add_sighting(SightingReport(observer_id="cam1", target_id="h1", observer_type="camera"))
        vs.add_sighting(SightingReport(observer_id="cam2", target_id="h1", observer_type="camera"))
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" in state.friendly_visible
        assert "cam1" in state.visible_to.get("h1", set())
        assert "cam2" in state.visible_to.get("h1", set())


# ===========================================================================
# TestPerformance
# ===========================================================================


class TestPerformance:
    """VisionSystem must handle realistic unit counts quickly."""

    def test_50_units_under_5ms(self):
        """50 units (25 friendly + 25 hostile) complete tick in <5ms."""
        targets = []
        for i in range(25):
            targets.append(_make_target(
                f"f{i}", "friendly", "turret", (i * 10, 0), heading=0
            ))
        for i in range(25):
            targets.append(_make_target(
                f"h{i}", "hostile", "person", (i * 10, 50)
            ))
        grid = _build_grid(targets)
        tdict = _targets_dict(targets)
        vs = VisionSystem()

        start = time.perf_counter()
        vs.tick(0.1, tdict, grid)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.005, f"Took {elapsed*1000:.1f}ms, expected <5ms"

    def test_empty_targets_no_crash(self):
        """Empty targets dict does not crash."""
        vs = VisionSystem()
        state = vs.tick(0.1, {}, SpatialGrid())
        assert len(state.friendly_visible) == 0

    def test_friendly_only_no_crash(self):
        """Friendly-only targets does not crash (no hostiles to detect)."""
        turret = _make_target("t1", "friendly", "turret", (0, 0))
        targets = [turret]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert len(state.friendly_visible) == 0


# ===========================================================================
# TestCanSee
# ===========================================================================


class TestCanSee:
    """Direct can_see() queries between specific units."""

    def test_can_see_in_range(self):
        """can_see returns True for in-range visible pair."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [turret, enemy]
        vs = VisionSystem()
        vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert vs.can_see("t1", "h1")

    def test_can_see_out_of_range(self):
        """can_see returns False for out-of-range pair."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 500))
        targets = [turret, enemy]
        vs = VisionSystem()
        vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert not vs.can_see("t1", "h1")

    def test_can_see_unknown_ids(self):
        """can_see returns False for IDs that don't exist."""
        vs = VisionSystem()
        vs.tick(0.1, {}, SpatialGrid())
        assert not vs.can_see("x", "y")


# ===========================================================================
# TestVisibilityState
# ===========================================================================


class TestVisibilityState:
    """VisibilityState data structure correctness."""

    def test_visible_to_tracks_observers(self):
        """visible_to maps target to all observers who see it."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        rover = _make_target("r1", "friendly", "rover", (5, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (3, 5))  # within ambient of both
        targets = [turret, rover, enemy]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        observers = state.visible_to.get("h1", set())
        assert "t1" in observers
        assert "r1" in observers

    def test_can_see_lists_targets(self):
        """can_see maps observer to list of targets it can see."""
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        e1 = _make_target("h1", "hostile", "person", (0, 5))  # in ambient
        e2 = _make_target("h2", "hostile", "person", (0, 30))  # in cone
        targets = [turret, e1, e2]
        vs = VisionSystem()
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        seen_by_turret = state.can_see.get("t1", [])
        assert "h1" in seen_by_turret
        assert "h2" in seen_by_turret

    def test_set_terrain_method(self):
        """set_terrain() updates the terrain map used for LOS."""
        vs = VisionSystem()
        terrain = TerrainMap(200.0)
        terrain.set_cell(0, 15, "building")
        vs.set_terrain(terrain)
        turret = _make_target("t1", "friendly", "turret", (0, 0), heading=0)
        enemy = _make_target("h1", "hostile", "person", (0, 30))
        targets = [turret, enemy]
        state = vs.tick(0.1, _targets_dict(targets), _build_grid(targets))
        assert "h1" not in state.friendly_visible
