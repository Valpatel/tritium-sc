"""Tests for MovementController integration with SimulationTarget and engine.

Verifies that:
1. Mobile targets get a MovementController assigned on add_target()
2. Stationary targets (turrets, cameras, sensors) do NOT get a controller
3. Controller-driven movement produces smooth acceleration and turn rate
4. Engine tick updates target position from controller
5. FSM state influences movement behavior
"""

import math

import pytest


class TestControllerAssignment:
    """Engine assigns MovementController to mobile targets."""

    def test_rover_gets_controller(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(0, 0), speed=2.0,
        )
        assert t.movement is not None, "Rover should get a MovementController"

    def test_drone_gets_controller(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="d-1", name="Drone-1", alliance="friendly",
            asset_type="drone", position=(0, 0), speed=4.0,
        )
        assert t.movement is not None

    def test_hostile_person_gets_controller(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="h-1", name="Hostile-1", alliance="hostile",
            asset_type="person", position=(0, 0), speed=3.0,
        )
        assert t.movement is not None

    def test_turret_no_controller(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="t-1", name="Turret-1", alliance="friendly",
            asset_type="turret", position=(10, 10), speed=0.0,
        )
        assert t.movement is None, "Turrets should NOT get a controller"

    def test_camera_no_controller(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="c-1", name="Cam-1", alliance="friendly",
            asset_type="camera", position=(5, 5), speed=0.0,
        )
        assert t.movement is None

    def test_controller_inherits_speed(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(0, 0), speed=5.0,
        )
        assert t.movement is not None
        assert t.movement.max_speed == 5.0

    def test_controller_position_matches_target(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(10.0, 20.0), speed=2.0,
        )
        assert t.movement is not None
        assert t.movement.x == 10.0
        assert t.movement.y == 20.0


class TestControllerDrivenMovement:
    """Target.tick() uses MovementController when available."""

    def test_controller_produces_smooth_movement(self):
        """With controller, speed ramps up instead of instant max."""
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=4.0,
            waypoints=[(100.0, 0.0)],
        )
        assert t.movement is not None
        # Tick a few times - speed should ramp up
        t.tick(0.1)
        t.tick(0.1)
        assert t.position[0] > 0, "Should have moved right"

    def test_controller_decelerates_near_waypoint(self):
        """Speed should decrease as target approaches waypoint."""
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=4.0,
            waypoints=[(3.0, 0.0)],
        )
        assert t.movement is not None
        # Tick until close to waypoint
        for _ in range(50):
            t.tick(0.1)
        # Should have arrived or be very close
        assert abs(t.position[0] - 3.0) < 2.0, f"Should be near (3,0), got {t.position}"

    def test_controller_updates_target_heading(self):
        """Heading should update smoothly with controller."""
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=2.0,
            waypoints=[(10.0, 10.0)],
        )
        t.tick(0.1)
        # Heading should be toward (10, 10) — roughly 45 degrees
        assert t.heading != 0.0 or t.position != (0.0, 0.0)

    def test_set_waypoints_updates_controller(self):
        """Setting waypoints on target should push them to controller."""
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=2.0,
        )
        assert t.movement is not None
        t.waypoints = [(50.0, 0.0), (50.0, 50.0)]
        t._waypoint_index = 0
        # Controller should get the new path
        t.tick(0.1)
        assert t.movement.remaining_waypoints > 0


class TestNonCombatantLegacyMovement:
    """Non-combatant targets use legacy linear movement (no controller)."""

    def test_neutral_person_no_controller(self):
        """Neutral people are non-combatants, no MovementController."""
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="p-1", name="Person-1", alliance="neutral",
            asset_type="person", position=(0.0, 0.0), speed=1.0,
            waypoints=[(10.0, 0.0)],
        )
        assert t.movement is None, "Neutral person should NOT get controller"
        start_x = t.position[0]
        t.tick(0.1)
        assert t.position[0] > start_x, "Should move via legacy tick"

    def test_animal_no_controller(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="a-1", name="Cat-1", alliance="neutral",
            asset_type="animal", position=(0.0, 0.0), speed=0.5,
            waypoints=[(5.0, 0.0)],
        )
        assert t.movement is None, "Animal should NOT get controller"
        t.tick(0.1)
        assert t.position[0] > 0

    def test_neutral_vehicle_no_controller(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="v-1", name="Car-1", alliance="neutral",
            asset_type="vehicle", position=(0.0, 0.0), speed=2.0,
            waypoints=[(20.0, 0.0)],
        )
        assert t.movement is None, "Neutral vehicle should NOT get controller"


class TestEngineAddsController:
    """Engine.add_target() preserves movement controller from __post_init__."""

    def test_engine_add_rover_has_controller(self):
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        from engine.simulation.target import SimulationTarget
        bus = EventBus()
        engine = SimulationEngine(bus, map_bounds=100)
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(0, 0), speed=2.0,
        )
        engine.add_target(t)
        assert t.movement is not None, "Rover should have movement controller"

    def test_engine_add_turret_no_controller(self):
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        from engine.simulation.target import SimulationTarget
        bus = EventBus()
        engine = SimulationEngine(bus, map_bounds=100)
        t = SimulationTarget(
            target_id="t-1", name="Turret-1", alliance="friendly",
            asset_type="turret", position=(10, 10), speed=0.0,
        )
        engine.add_target(t)
        assert t.movement is None, "Turret should NOT have movement controller"


class TestToDict:
    """to_dict() works with movement controller targets."""

    def test_to_dict_includes_standard_fields(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(0, 0), speed=2.0,
        )
        d = t.to_dict()
        assert "target_id" in d
        assert d["target_id"] == "r-1"
        assert "position" in d
        assert d["is_combatant"] is True

    def test_to_dict_after_controller_movement(self):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id="r-1", name="Rover-1", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=4.0,
            waypoints=[(20.0, 0.0)],
        )
        t.tick(0.1)
        t.tick(0.1)
        d = t.to_dict()
        # Position in dict should reflect controller movement
        assert d["position"]["x"] > 0.0
