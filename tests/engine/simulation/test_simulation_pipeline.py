"""Simulation integration tests — full Amy+Robot pipeline without hardware.

Exercises the complete pipeline: SimulationEngine spawns robots, robots
think via RobotThinker (mocked Ollama), VisionBridge converts YOLO
detections, NavPlanner transforms coordinates, and TargetTracker unifies
all targets into Amy's battlespace view.

No real LLM calls, no MQTT broker, no hardware. Everything is mocked at
the boundary (Ollama HTTP, MQTT publish). Real logic runs end-to-end.
"""

from __future__ import annotations

import importlib
import math
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget
from engine.tactical.target_tracker import TargetTracker, TrackedTarget

# Robot template lives under examples/robot-template/ (hyphen in dir name).
# Add it to sys.path so `brain.thinker` etc. resolve, same approach as
# the template's own tests.
_ROBOT_TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "examples", "robot-template"
)
_ROBOT_TEMPLATE_DIR = os.path.abspath(_ROBOT_TEMPLATE_DIR)
if _ROBOT_TEMPLATE_DIR not in sys.path:
    sys.path.insert(0, _ROBOT_TEMPLATE_DIR)

from brain.thinker import (  # noqa: E402
    RobotThinker,
    parse_lua_call,
    extract_lua_calls,
)
from brain.vision_bridge import VisionBridge  # noqa: E402
from brain.nav_planner import (  # noqa: E402
    WorldPosition,
    GpsPosition,
    NavWaypoint,
    NavPath,
    StraightLinePlanner,
    WaypointPlanner,
    gps_to_world,
    world_to_gps,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> SimulationEngine:
    """Create a SimulationEngine with a fresh EventBus (no threads)."""
    bus = EventBus()
    engine = SimulationEngine(bus)
    return engine


def _make_thinker(**overrides) -> RobotThinker:
    """Create a RobotThinker with sensible test defaults."""
    config = {
        "robot_id": overrides.get("robot_id", "rover-01"),
        "robot_name": overrides.get("robot_name", "Scout Alpha"),
        "asset_type": overrides.get("asset_type", "rover"),
        "site_id": overrides.get("site_id", "home"),
        "thinker": {
            "enabled": True,
            "model": "gemma3:4b",
            "ollama_host": "http://localhost:11434",
            "think_interval": 5.0,
            "actions": overrides.get("extra_actions", []),
        },
    }
    return RobotThinker(config)


def _mock_ollama_response(content: str) -> MagicMock:
    """Create a mock requests.Response with Ollama chat format."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": content},
        "done": True,
    }
    return mock_resp


# ===========================================================================
# TestSimRobotSpawn
# ===========================================================================

class TestSimRobotSpawn:
    """Spawn a simulated robot and verify it appears in TargetTracker."""

    def test_spawn_rover_appears_in_engine(self):
        """A rover added to the engine is retrievable by ID."""
        engine = _make_engine()
        rover = SimulationTarget(
            target_id="rover-01",
            name="Scout Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(5.0, 10.0),
            speed=2.0,
        )
        engine.add_target(rover)
        found = engine.get_target("rover-01")
        assert found is rover
        assert found.alliance == "friendly"
        assert found.asset_type == "rover"

    def test_spawn_rover_telemetry_reaches_tracker(self):
        """Sim telemetry published to EventBus propagates to TargetTracker."""
        bus = EventBus()
        engine = SimulationEngine(bus)
        tracker = TargetTracker()

        rover = SimulationTarget(
            target_id="rover-01",
            name="Scout Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(5.0, 10.0),
            speed=2.0,
        )
        engine.add_target(rover)

        # Simulate one tick manually: advance target, publish telemetry
        rover.tick(0.1)
        sim_data = rover.to_dict()
        tracker.update_from_simulation(sim_data)

        # Verify tracker sees the rover
        all_targets = tracker.get_all()
        assert len(all_targets) == 1
        tracked = all_targets[0]
        assert tracked.target_id == "rover-01"
        assert tracked.name == "Scout Alpha"
        assert tracked.alliance == "friendly"
        assert tracked.source == "simulation"

    def test_spawn_hostile_appears_in_tracker(self):
        """Spawning a hostile via the engine and feeding telemetry to tracker."""
        engine = _make_engine()
        tracker = TargetTracker()

        hostile = engine.spawn_hostile(
            name="Intruder Alpha",
            position=(20.0, 0.0),
        )
        sim_data = hostile.to_dict()
        tracker.update_from_simulation(sim_data)

        hostiles = tracker.get_hostiles()
        assert len(hostiles) == 1
        assert hostiles[0].alliance == "hostile"
        assert hostiles[0].asset_type == "person"

    def test_multiple_targets_tracked(self):
        """Multiple robots and hostiles all appear in tracker."""
        engine = _make_engine()
        tracker = TargetTracker()

        # Add 2 friendlies and 2 hostiles
        for i in range(2):
            rover = SimulationTarget(
                target_id=f"rover-{i}",
                name=f"Rover {i}",
                alliance="friendly",
                asset_type="rover",
                position=(float(i * 5), 0.0),
                speed=2.0,
            )
            engine.add_target(rover)
            tracker.update_from_simulation(rover.to_dict())

        for i in range(2):
            h = engine.spawn_hostile(position=(20.0 + i * 5, 0.0))
            tracker.update_from_simulation(h.to_dict())

        all_t = tracker.get_all()
        assert len(all_t) == 4
        assert len(tracker.get_friendlies()) == 2
        assert len(tracker.get_hostiles()) == 2

    def test_tracker_summary_with_targets(self):
        """Tracker summary includes battlespace overview text."""
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "rover-01",
            "name": "Scout Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 0.0, "y": 0.0},
            "heading": 0.0,
            "speed": 2.0,
            "battery": 0.95,
            "status": "active",
        })
        tracker.update_from_simulation({
            "target_id": "hostile-01",
            "name": "Intruder Alpha",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 15.0, "y": 0.0},
            "heading": 180.0,
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        })
        summary = tracker.summary()
        assert "friendly" in summary.lower() or "BATTLESPACE" in summary
        assert "hostile" in summary.lower()


# ===========================================================================
# TestSimRobotNavigation
# ===========================================================================

class TestSimRobotNavigation:
    """Give a robot waypoints, tick the engine, verify it moves."""

    def test_rover_moves_toward_waypoint(self):
        """A rover with waypoints moves closer each tick."""
        rover = SimulationTarget(
            target_id="rover-01",
            name="Scout Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=2.0,
            waypoints=[(10.0, 0.0)],
        )
        initial_x = rover.position[0]
        for _ in range(10):
            rover.tick(0.1)
        # After 10 ticks (1s), should have moved toward waypoint.
        # With smooth acceleration and turn ramp-up, distance is less
        # than ideal (2.0m) but should be significant.
        assert rover.position[0] > initial_x
        assert rover.position[0] > 0.5  # meaningful progress toward waypoint

    def test_rover_reaches_waypoint(self):
        """A rover reaches its waypoint and changes status."""
        rover = SimulationTarget(
            target_id="rover-01",
            name="Scout Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=2.0,
            waypoints=[(3.0, 0.0)],
        )
        # With smooth movement controller, acceleration and turn rate
        # slow the rover down compared to legacy instant-speed movement.
        # Give enough ticks for acceleration ramp-up and arrival.
        for _ in range(80):
            rover.tick(0.1)
        assert rover.status == "arrived"

    def test_rover_follows_multi_waypoint_path(self):
        """A rover follows a multi-waypoint path in order."""
        rover = SimulationTarget(
            target_id="rover-01",
            name="Scout Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=3.0,
            waypoints=[(5.0, 0.0), (5.0, 5.0), (0.0, 5.0)],
        )
        # Run enough ticks to traverse the L-shaped path
        # Total distance: 5 + 5 + 5 = 15m at 3m/s = 5s = 50 ticks
        for _ in range(80):
            rover.tick(0.1)
        # Should have arrived at final waypoint
        assert rover.status == "arrived"

    def test_hostile_walks_toward_origin(self):
        """A hostile spawned at an edge walks toward (0,0)."""
        hostile = SimulationTarget(
            target_id="hostile-01",
            name="Intruder",
            alliance="hostile",
            asset_type="person",
            position=(15.0, 0.0),
            speed=1.5,
            waypoints=[(0.0, 0.0)],
        )
        initial_dist = math.hypot(*hostile.position)
        for _ in range(50):
            hostile.tick(0.1)
        current_dist = math.hypot(*hostile.position)
        assert current_dist < initial_dist, "Hostile should be closer to origin"

    def test_patrol_loops_waypoints(self):
        """A friendly rover with loop_waypoints=True loops its patrol."""
        rover = SimulationTarget(
            target_id="rover-01",
            name="Patrol Rover",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=5.0,
            waypoints=[(3.0, 0.0), (0.0, 0.0)],
            loop_waypoints=True,
        )
        # Run many ticks — should keep looping, never reach "arrived"
        for _ in range(200):
            rover.tick(0.1)
        assert rover.status == "active"

    def test_heading_updates_during_movement(self):
        """Heading updates to face the current waypoint."""
        rover = SimulationTarget(
            target_id="rover-01",
            name="Scout",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=2.0,
            waypoints=[(10.0, 0.0)],  # East
        )
        # With MovementController, heading turns gradually (limited by turn_rate).
        # Run enough ticks for the heading to converge toward the target.
        for _ in range(10):
            rover.tick(0.1)
        # heading = atan2(dx, dy) in target convention: east is 90 degrees
        # After 1s of turning at 180 deg/s, should be close to 90
        assert abs(rover.heading - 90.0) < 5.0


# ===========================================================================
# TestSimRobotThinker
# ===========================================================================

class TestSimRobotThinker:
    """Create a RobotThinker with mocked Ollama, verify it generates Lua actions."""

    def test_thinker_init(self):
        """Thinker initializes with correct config values."""
        thinker = _make_thinker()
        assert thinker.robot_id == "rover-01"
        assert thinker.model == "gemma3:4b"
        assert thinker.enabled is True
        assert "think" in thinker.actions
        assert "say" in thinker.actions

    def test_build_context_includes_identity(self):
        """build_context includes robot name, position, battery."""
        thinker = _make_thinker()
        telemetry = {
            "position": {"x": 5.0, "y": 10.0},
            "battery": 0.85,
            "status": "active",
        }
        context = thinker.build_context(telemetry=telemetry)
        assert "Scout Alpha" in context
        assert "rover-01" in context
        assert "5.0" in context
        assert "10.0" in context
        assert "85%" in context

    def test_build_context_includes_targets(self):
        """build_context includes nearby targets."""
        thinker = _make_thinker()
        targets = [
            {"name": "Intruder Alpha", "alliance": "hostile", "position": {"x": 15.0, "y": 0.0}},
        ]
        context = thinker.build_context(nearby_targets=targets)
        assert "Intruder Alpha" in context
        assert "hostile" in context

    def test_build_context_includes_commands(self):
        """build_context includes recent commands from Amy."""
        thinker = _make_thinker()
        commands = [{"command": "dispatch", "x": 10, "y": 20}]
        context = thinker.build_context(recent_commands=commands)
        assert "dispatch" in context

    @patch("brain.thinker.requests.post")
    def test_think_once_returns_action(self, mock_post):
        """think_once calls Ollama and returns a parsed Lua action."""
        mock_post.return_value = _mock_ollama_response('think("Scanning sector north")')

        thinker = _make_thinker()
        result = thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "active"},
        )

        assert result is not None
        assert result["action"] == "think"
        assert result["params"] == ["Scanning sector north"]
        assert thinker.think_count == 1

    @patch("brain.thinker.requests.post")
    def test_think_once_say_action(self, mock_post):
        """Thinker can produce say() actions for Amy communication."""
        mock_post.return_value = _mock_ollama_response('say("Hostile detected at north sector")')

        thinker = _make_thinker()
        result = thinker.think_once()

        assert result is not None
        assert result["action"] == "say"
        assert "Hostile detected" in result["params"][0]

    @patch("brain.thinker.requests.post")
    def test_think_once_custom_action(self, mock_post):
        """Thinker can call custom registered actions."""
        mock_post.return_value = _mock_ollama_response('fire_nerf()')

        thinker = _make_thinker(extra_actions=[
            {"name": "fire_nerf", "description": "Fire the nerf turret"},
        ])
        result = thinker.think_once()

        assert result is not None
        assert result["action"] == "fire_nerf"

    @patch("brain.thinker.requests.post")
    def test_thought_history_accumulates(self, mock_post):
        """Each think_once call appends to thought history."""
        mock_post.return_value = _mock_ollama_response('think("First thought")')

        thinker = _make_thinker()
        thinker.think_once()

        mock_post.return_value = _mock_ollama_response('think("Second thought")')
        thinker.think_once()

        assert thinker.think_count == 2
        assert len(thinker.thought_history) == 2
        assert thinker.thought_history[0]["text"] == "First thought"
        assert thinker.thought_history[1]["text"] == "Second thought"

    @patch("brain.thinker.requests.post")
    def test_think_once_ollama_failure_returns_none(self, mock_post):
        """If Ollama is unreachable, think_once returns None."""
        mock_post.side_effect = Exception("Connection refused")

        thinker = _make_thinker()
        result = thinker.think_once()

        assert result is None
        assert thinker.think_count == 0

    def test_dispatch_action_calls_handler(self):
        """dispatch_action invokes registered handler."""
        thinker = _make_thinker()
        fired = []
        thinker.on_action("fire_nerf", lambda params: fired.append(params))
        thinker.register_action("fire_nerf", "Fire the nerf turret")

        thinker.dispatch_action("fire_nerf", [])
        assert len(fired) == 1

    def test_mqtt_topic_format(self):
        """MQTT topic follows the expected convention."""
        thinker = _make_thinker(robot_id="rover-01", site_id="home")
        assert thinker.mqtt_topic == "tritium/home/robots/rover-01/thoughts"

    def test_to_mqtt_message_format(self):
        """to_mqtt_message returns well-formed message dict."""
        thinker = _make_thinker()
        thinker._record_thought("think", ["Scanning perimeter"])
        msg = thinker.to_mqtt_message()
        assert msg["robot_id"] == "rover-01"
        assert msg["type"] == "thought"
        assert msg["text"] == "Scanning perimeter"
        assert msg["think_count"] == 0  # _record_thought doesn't increment think_count


# ===========================================================================
# TestSimVisionBridge
# ===========================================================================

class TestSimVisionBridge:
    """Push mock YOLO detections, verify they appear as nearby targets."""

    def test_push_detection_increases_count(self):
        """Pushing detections increases detection_count."""
        bridge = VisionBridge()
        bridge.push_detections([
            {"label": "person", "confidence": 0.9, "center_x": 0.5, "center_y": 0.5},
        ])
        assert bridge.detection_count >= 1

    def test_person_detection_classified_hostile(self):
        """Person detections are classified as hostile targets."""
        bridge = VisionBridge()
        bridge.push_detections([
            {"label": "person", "confidence": 0.85, "center_x": 0.6, "center_y": 0.4},
        ])
        targets = bridge.get_nearby_targets(robot_position=(5.0, 10.0))
        assert len(targets) >= 1
        target = targets[0]
        assert target["alliance"] == "hostile"
        assert target["label"] == "person"
        assert "position" in target

    def test_robot_detection_classified_friendly(self):
        """Robot detections are classified as friendly."""
        bridge = VisionBridge()
        bridge.push_detections([
            {"label": "robot", "confidence": 0.75, "center_x": 0.5, "center_y": 0.5},
        ])
        targets = bridge.get_nearby_targets()
        assert len(targets) >= 1
        assert targets[0]["alliance"] == "friendly"

    def test_detection_position_relative_to_robot(self):
        """Target position is offset from robot position based on image coords."""
        bridge = VisionBridge()
        bridge.push_detections([
            {"label": "person", "confidence": 0.9, "center_x": 0.5, "center_y": 0.5},
        ])
        robot_pos = (10.0, 20.0)
        targets = bridge.get_nearby_targets(robot_position=robot_pos)
        # center_x=0.5, center_y=0.5 maps to (0, 0) offset from robot
        target_pos = targets[0]["position"]
        assert abs(target_pos["x"] - robot_pos[0]) < 1.0
        assert abs(target_pos["y"] - robot_pos[1]) < 1.0

    def test_multiple_detections(self):
        """Multiple detections of different classes produce multiple targets."""
        bridge = VisionBridge()
        bridge.push_detections([
            {"label": "person", "confidence": 0.9, "center_x": 0.3, "center_y": 0.5},
            {"label": "car", "confidence": 0.8, "center_x": 0.7, "center_y": 0.5},
        ])
        targets = bridge.get_nearby_targets()
        assert len(targets) == 2
        labels = {t["label"] for t in targets}
        assert "person" in labels
        assert "car" in labels

    def test_stale_detections_pruned(self):
        """Detections older than max_age are pruned."""
        bridge = VisionBridge(config={"max_detection_age": 0.1})
        bridge.push_detections([
            {"label": "person", "confidence": 0.9, "center_x": 0.5, "center_y": 0.5},
        ])
        assert bridge.detection_count >= 1
        # Wait for detections to go stale
        time.sleep(0.15)
        targets = bridge.get_nearby_targets()  # triggers prune
        assert len(targets) == 0

    def test_max_targets_limit(self):
        """get_nearby_targets respects max_targets config."""
        bridge = VisionBridge(config={"max_targets": 2})
        # Push many distinct detections (different labels so they don't dedupe)
        dets = [
            {"label": f"type_{i}", "confidence": 0.9, "center_x": i * 0.1, "center_y": 0.5}
            for i in range(5)
        ]
        bridge.push_detections(dets)
        targets = bridge.get_nearby_targets()
        assert len(targets) <= 2

    def test_vision_bridge_feeds_thinker(self):
        """VisionBridge targets can be passed directly to thinker.build_context."""
        bridge = VisionBridge()
        bridge.push_detections([
            {"label": "person", "confidence": 0.9, "center_x": 0.6, "center_y": 0.4},
        ])
        targets = bridge.get_nearby_targets(robot_position=(5.0, 10.0))

        thinker = _make_thinker()
        context = thinker.build_context(nearby_targets=targets)
        assert "hostile" in context.lower()


# ===========================================================================
# TestSimCoordinateTransform
# ===========================================================================

class TestSimCoordinateTransform:
    """Verify GPS<->game coordinate roundtrips using nav_planner transforms."""

    # Reference point: a neighborhood in Austin, TX
    ORIGIN_LAT = 30.2672
    ORIGIN_LNG = -97.7431

    def test_gps_to_world_at_origin(self):
        """GPS at the origin converts to (0, 0) world position."""
        gps = GpsPosition(lat=self.ORIGIN_LAT, lng=self.ORIGIN_LNG)
        world = gps_to_world(gps, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert abs(world.x) < 0.01
        assert abs(world.y) < 0.01

    def test_gps_to_world_north_is_positive_y(self):
        """Moving north (higher lat) increases Y."""
        gps = GpsPosition(lat=self.ORIGIN_LAT + 0.001, lng=self.ORIGIN_LNG)
        world = gps_to_world(gps, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert world.y > 0, "North should be positive Y"
        assert abs(world.x) < 0.5, "No east-west displacement"

    def test_gps_to_world_east_is_positive_x(self):
        """Moving east (higher lng) increases X."""
        gps = GpsPosition(lat=self.ORIGIN_LAT, lng=self.ORIGIN_LNG + 0.001)
        world = gps_to_world(gps, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert world.x > 0, "East should be positive X"
        assert abs(world.y) < 0.5, "No north-south displacement"

    def test_world_to_gps_roundtrip(self):
        """gps_to_world -> world_to_gps should return the original GPS position."""
        original = GpsPosition(lat=self.ORIGIN_LAT + 0.002, lng=self.ORIGIN_LNG - 0.001)
        world = gps_to_world(original, self.ORIGIN_LAT, self.ORIGIN_LNG)
        recovered = world_to_gps(world, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert abs(recovered.lat - original.lat) < 1e-7
        assert abs(recovered.lng - original.lng) < 1e-7

    def test_roundtrip_at_multiple_offsets(self):
        """Roundtrip accuracy at various distances from origin."""
        for dx, dy in [(100, 0), (0, 100), (50, 50), (-30, 70), (0, 0)]:
            wp = WorldPosition(x=float(dx), y=float(dy))
            gps = world_to_gps(wp, self.ORIGIN_LAT, self.ORIGIN_LNG)
            wp_back = gps_to_world(gps, self.ORIGIN_LAT, self.ORIGIN_LNG)
            assert abs(wp_back.x - wp.x) < 0.01, f"X mismatch at offset ({dx},{dy})"
            assert abs(wp_back.y - wp.y) < 0.01, f"Y mismatch at offset ({dx},{dy})"

    def test_world_position_distance_to(self):
        """WorldPosition.distance_to computes Euclidean distance."""
        a = WorldPosition(x=0.0, y=0.0)
        b = WorldPosition(x=3.0, y=4.0)
        assert abs(a.distance_to(b) - 5.0) < 1e-6

    def test_world_position_bearing_to(self):
        """WorldPosition.bearing_to returns compass bearing."""
        a = WorldPosition(x=0.0, y=0.0)
        # Due north (0, +y) should be ~0 degrees
        north = WorldPosition(x=0.0, y=10.0)
        bearing = a.bearing_to(north)
        assert abs(bearing - 0.0) < 1.0 or abs(bearing - 360.0) < 1.0

        # Due east (+x, 0) should be ~90 degrees
        east = WorldPosition(x=10.0, y=0.0)
        bearing = a.bearing_to(east)
        assert abs(bearing - 90.0) < 1.0

    def test_straight_line_planner(self):
        """StraightLinePlanner creates a 2-waypoint path."""
        planner = StraightLinePlanner()
        start = WorldPosition(x=0, y=0)
        goal = WorldPosition(x=10, y=10)
        path = planner.plan(start, goal)
        assert len(path.waypoints) == 2
        assert path.waypoints[0].position.x == 0
        assert path.waypoints[1].position.x == 10

    def test_nav_path_total_distance(self):
        """NavPath computes total distance correctly."""
        path = NavPath(waypoints=[
            NavWaypoint(position=WorldPosition(x=0, y=0)),
            NavWaypoint(position=WorldPosition(x=3, y=0)),
            NavWaypoint(position=WorldPosition(x=3, y=4)),
        ])
        # 3 + 4 = 7
        assert abs(path.total_distance - 7.0) < 1e-6

    def test_waypoint_planner_uses_predefined_route(self):
        """WaypointPlanner follows predefined waypoints."""
        route = [
            WorldPosition(x=0, y=0),
            WorldPosition(x=10, y=0),
            WorldPosition(x=10, y=10),
        ]
        planner = WaypointPlanner(waypoints=route)
        start = WorldPosition(x=0, y=0)
        goal = WorldPosition(x=10, y=10)
        path = planner.plan(start, goal)
        assert len(path.waypoints) == 3

    def test_neighborhood_scale_accuracy(self):
        """At neighborhood scale (~500m), GPS<->world accuracy is sub-meter."""
        # 500m north, 500m east
        wp = WorldPosition(x=500.0, y=500.0)
        gps = world_to_gps(wp, self.ORIGIN_LAT, self.ORIGIN_LNG)
        wp_back = gps_to_world(gps, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert abs(wp_back.x - 500.0) < 0.1
        assert abs(wp_back.y - 500.0) < 0.1


# ===========================================================================
# TestLuaParsing
# ===========================================================================

class TestLuaParsing:
    """Verify the standalone Lua parser in thinker.py."""

    def test_parse_think_call(self):
        """Parse a simple think() call."""
        result = parse_lua_call('think("Hello world")')
        assert result is not None
        assert result[0] == "think"
        assert result[1] == ["Hello world"]

    def test_parse_empty_params(self):
        """Parse a call with no params."""
        result = parse_lua_call("fire_nerf()")
        assert result is not None
        assert result[0] == "fire_nerf"
        assert result[1] == []

    def test_parse_multiple_params(self):
        """Parse a call with multiple params."""
        result = parse_lua_call('dispatch("rover-01", 10, 20)')
        assert result is not None
        assert result[0] == "dispatch"
        assert len(result[1]) == 3

    def test_parse_invalid_returns_none(self):
        """Non-Lua text returns None."""
        assert parse_lua_call("just some text") is None
        assert parse_lua_call("") is None
        assert parse_lua_call(None) is None

    def test_extract_from_code_block(self):
        """extract_lua_calls handles code blocks."""
        response = '```lua\nthink("I see something")\n```'
        calls = extract_lua_calls(response)
        assert len(calls) >= 1
        assert "think" in calls[0]

    def test_extract_with_thinking_tags(self):
        """extract_lua_calls strips thinking tags."""
        response = '<think>internal reasoning</think>\nsay("Hostile spotted")'
        calls = extract_lua_calls(response)
        assert len(calls) >= 1
        assert "say" in calls[0]

    def test_extract_known_actions_filter(self):
        """extract_lua_calls filters to known actions when provided."""
        response = 'think("hello")\nunknown_func("test")'
        calls = extract_lua_calls(response, known_actions={"think"})
        assert len(calls) == 1
        assert "think" in calls[0]


# ===========================================================================
# TestSimFullPipeline
# ===========================================================================

class TestSimFullPipeline:
    """Full pipeline: spawn robot + hostile, feed detections, thinker responds."""

    @patch("brain.thinker.requests.post")
    def test_robot_detects_hostile_and_thinks(self, mock_post):
        """Robot sees hostile via VisionBridge, thinker generates response."""
        # 1. Set up the simulation
        engine = _make_engine()
        tracker = TargetTracker()

        # 2. Spawn a friendly rover
        rover = SimulationTarget(
            target_id="rover-01",
            name="Scout Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=2.0,
            waypoints=[(10.0, 0.0)],
        )
        engine.add_target(rover)

        # 3. Spawn a hostile
        hostile = engine.spawn_hostile(name="Intruder Alpha", position=(15.0, 0.0))

        # 4. Feed both to tracker
        tracker.update_from_simulation(rover.to_dict())
        tracker.update_from_simulation(hostile.to_dict())

        # 5. Verify battlespace state
        assert len(tracker.get_friendlies()) == 1
        assert len(tracker.get_hostiles()) == 1

        # 6. Robot's camera detects the hostile (YOLO detection)
        bridge = VisionBridge()
        bridge.push_detections([
            {"label": "person", "confidence": 0.92, "center_x": 0.7, "center_y": 0.5},
        ])
        nearby = bridge.get_nearby_targets(robot_position=rover.position)

        # 7. Robot thinker processes the detection
        mock_post.return_value = _mock_ollama_response(
            'say("Hostile detected at bearing 90, moving to intercept")'
        )
        thinker = _make_thinker()
        telemetry = {
            "position": {"x": rover.position[0], "y": rover.position[1]},
            "battery": rover.battery,
            "status": rover.status,
        }
        result = thinker.think_once(
            telemetry=telemetry,
            nearby_targets=nearby,
        )

        # 8. Verify thinker produced a say action
        assert result is not None
        assert result["action"] == "say"
        assert "Hostile detected" in result["params"][0]

        # 9. Verify the Ollama call included target info in the context
        call_args = mock_post.call_args
        messages = call_args.kwargs.get("json", call_args[1].get("json", {}))["messages"]
        system_prompt = messages[0]["content"]
        assert "hostile" in system_prompt.lower()

    @patch("brain.thinker.requests.post")
    def test_robot_low_battery_returns_home(self, mock_post):
        """Robot with low battery generates a return-home action."""
        mock_post.return_value = _mock_ollama_response(
            'think("Battery critical at 5%. Returning to base immediately.")'
        )

        thinker = _make_thinker()
        result = thinker.think_once(
            telemetry={"position": {"x": 20, "y": 15}, "battery": 0.05, "status": "active"},
        )

        assert result is not None
        # The context should have included low battery info
        call_args = mock_post.call_args
        messages = call_args.kwargs.get("json", call_args[1].get("json", {}))["messages"]
        system_prompt = messages[0]["content"]
        assert "5%" in system_prompt

    @patch("brain.thinker.requests.post")
    def test_robot_follows_command_from_amy(self, mock_post):
        """Robot receives dispatch command and thinker references it."""
        mock_post.return_value = _mock_ollama_response(
            'think("Dispatch order received, moving to (10, 20)")'
        )

        thinker = _make_thinker()
        commands = [{"command": "dispatch", "x": 10, "y": 20}]
        result = thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 0.9, "status": "active"},
            recent_commands=commands,
        )

        assert result is not None
        # Context should include the dispatch command
        call_args = mock_post.call_args
        messages = call_args.kwargs.get("json", call_args[1].get("json", {}))["messages"]
        system_prompt = messages[0]["content"]
        assert "dispatch" in system_prompt.lower()

    def test_eventbus_propagates_sim_to_tracker(self):
        """Full event flow: engine publishes telemetry -> tracker receives it."""
        bus = EventBus()
        engine = SimulationEngine(bus)
        tracker = TargetTracker()
        sub = bus.subscribe()

        # Add rover and hostile
        rover = SimulationTarget(
            target_id="rover-01",
            name="Scout Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=2.0,
        )
        engine.add_target(rover)
        hostile = engine.spawn_hostile(name="Intruder", position=(20.0, 0.0))

        # Simulate what the tick loop does: tick targets + publish telemetry
        for target in engine.get_targets():
            target.tick(0.1)
            bus.publish("sim_telemetry", target.to_dict())

        # Drain bus and feed to tracker (mimics Commander._sim_bridge_loop)
        events_processed = 0
        while True:
            try:
                msg = sub.get_nowait()
                if msg.get("type") == "sim_telemetry":
                    tracker.update_from_simulation(msg["data"])
                    events_processed += 1
            except Exception:
                break

        assert events_processed >= 2  # rover + hostile
        assert len(tracker.get_all()) == 2

    def test_action_dispatch_wires_to_handler(self):
        """Full dispatch: think -> parse -> dispatch -> handler fires."""
        thinker = _make_thinker()
        alerts = []
        thinker.register_action("alert", "Send alert to Amy")
        thinker.on_action("alert", lambda params: alerts.append(params))

        # Simulate a parsed action
        thinker.dispatch_action("alert", ["Hostile spotted at sector NE"])
        assert len(alerts) == 1
        assert alerts[0] == ["Hostile spotted at sector NE"]

    @patch("brain.thinker.requests.post")
    def test_multi_robot_scenario(self, mock_post):
        """Multiple robots thinking concurrently about the same battlespace."""
        engine = _make_engine()
        tracker = TargetTracker()

        # Spawn 3 rovers
        thinkers = []
        for i in range(3):
            rover = SimulationTarget(
                target_id=f"rover-{i:02d}",
                name=f"Rover {i}",
                alliance="friendly",
                asset_type="rover",
                position=(float(i * 10), 0.0),
                speed=2.0,
            )
            engine.add_target(rover)
            tracker.update_from_simulation(rover.to_dict())
            thinkers.append(_make_thinker(
                robot_id=f"rover-{i:02d}",
                robot_name=f"Rover {i}",
            ))

        # Spawn a hostile
        hostile = engine.spawn_hostile(name="Intruder", position=(15.0, 5.0))
        tracker.update_from_simulation(hostile.to_dict())

        assert len(tracker.get_all()) == 4

        # Each robot thinks
        mock_post.return_value = _mock_ollama_response('think("Monitoring sector")')

        for i, thinker in enumerate(thinkers):
            rover_target = engine.get_target(f"rover-{i:02d}")
            tel = {
                "position": {"x": rover_target.position[0], "y": rover_target.position[1]},
                "battery": rover_target.battery,
                "status": rover_target.status,
            }
            result = thinker.think_once(telemetry=tel)
            assert result is not None
            assert result["action"] == "think"

        # All 3 robots should have thought
        assert all(t.think_count == 1 for t in thinkers)

    def test_coordinate_transform_in_pipeline(self):
        """Coordinate transforms work end-to-end in the pipeline context."""
        # Robot has GPS, needs to convert to game coords for thinker context
        origin_lat, origin_lng = 30.2672, -97.7431

        # Robot GPS position: 100m north, 50m east of origin
        robot_world = WorldPosition(x=50.0, y=100.0)
        robot_gps = world_to_gps(robot_world, origin_lat, origin_lng)

        # Convert back (as would happen in robot firmware)
        robot_recovered = gps_to_world(robot_gps, origin_lat, origin_lng)

        # Should be accurate to sub-meter
        assert abs(robot_recovered.x - 50.0) < 0.1
        assert abs(robot_recovered.y - 100.0) < 0.1

        # Hostile at known GPS position
        hostile_gps = GpsPosition(
            lat=origin_lat + 0.0005,  # ~55m north
            lng=origin_lng + 0.0003,  # ~26m east
        )
        hostile_world = gps_to_world(hostile_gps, origin_lat, origin_lng)

        # Distance calculation in game coords
        dist = robot_world.distance_to(hostile_world)
        assert dist > 0

        # Bearing to hostile
        bearing = robot_world.bearing_to(hostile_world)
        assert 0 <= bearing < 360
