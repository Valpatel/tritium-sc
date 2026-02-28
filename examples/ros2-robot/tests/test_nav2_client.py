# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the Nav2 action client.

Tests verify goal construction, status tracking, and callback behavior.
All ROS2 dependencies are mocked -- tests work without ROS2 installed.
"""

from __future__ import annotations

import math
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock ROS2 dependencies
# ---------------------------------------------------------------------------

_mock_rclpy = MagicMock()

# Create a mock Node class that the Nav2Client can use
_MockNode = MagicMock()
_MockNode.get_logger.return_value = MagicMock()
_MockNode.get_clock.return_value = MagicMock(
    now=MagicMock(return_value=MagicMock(
        to_msg=MagicMock(return_value=MagicMock())
    ))
)

# Mock PoseStamped to be a real constructable object
class MockPoseStamped:
    def __init__(self):
        self.header = MagicMock()
        self.pose = MagicMock()
        self.pose.position = MagicMock(x=0.0, y=0.0, z=0.0)
        self.pose.orientation = MagicMock(x=0.0, y=0.0, z=0.0, w=1.0)

_mock_geometry = MagicMock()
_mock_geometry.msg.PoseStamped = MockPoseStamped

# Mock Nav2 action types
class MockNavigateToPose:
    class Goal:
        def __init__(self):
            self.pose = None

class MockFollowWaypoints:
    class Goal:
        def __init__(self):
            self.poses = []

_mock_nav2 = MagicMock()
_mock_nav2.action.NavigateToPose = MockNavigateToPose
_mock_nav2.action.FollowWaypoints = MockFollowWaypoints

# Mock ActionClient
class MockActionClient:
    def __init__(self, node, action_type, action_name):
        self.action_type = action_type
        self.action_name = action_name
        self._send_goal_calls = []

    def wait_for_server(self, timeout_sec=5.0):
        return True

    def send_goal_async(self, goal, feedback_callback=None):
        self._send_goal_calls.append(goal)
        future = MagicMock()
        future.add_done_callback = MagicMock()
        return future

_mock_rclpy.action.ActionClient = MockActionClient

for mod_name in [
    "rclpy", "rclpy.node", "rclpy.action", "rclpy.action.client",
    "geometry_msgs", "geometry_msgs.msg",
    "nav_msgs", "nav_msgs.msg",
    "sensor_msgs", "sensor_msgs.msg",
    "nav2_msgs", "nav2_msgs.action",
    "tf2_ros",
]:
    sys.modules[mod_name] = _mock_rclpy

# Override specific mocks
sys.modules["geometry_msgs"] = _mock_geometry
sys.modules["geometry_msgs.msg"] = _mock_geometry.msg
sys.modules["nav2_msgs"] = _mock_nav2
sys.modules["nav2_msgs.action"] = _mock_nav2.action

# Add package to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ros2_robot.nav2_client import Nav2Client


class TestNav2ClientInit:
    """Test Nav2Client initialization."""

    def test_initial_status_is_idle(self):
        node = _MockNode
        client = Nav2Client(node)
        assert client.status == "idle"

    def test_initial_feedback_zeroed(self):
        node = _MockNode
        client = Nav2Client(node)
        assert client.feedback_distance == 0.0
        assert client.feedback_eta == 0.0


class TestNavigateTo:
    """Test single-point navigation."""

    def test_navigate_to_sets_navigating(self):
        node = _MockNode
        client = Nav2Client(node)
        client.navigate_to(10.0, 5.0)
        assert client.status == "navigating"

    def test_navigate_to_with_theta(self):
        node = _MockNode
        client = Nav2Client(node)
        client.navigate_to(10.0, 5.0, theta=1.57)
        assert client.status == "navigating"


class TestFollowWaypoints:
    """Test waypoint sequence navigation."""

    def test_follow_waypoints_sets_navigating(self):
        node = _MockNode
        client = Nav2Client(node)
        client.follow_waypoints([(0, 0), (10, 5), (20, 0)])
        assert client.status == "navigating"

    def test_follow_empty_waypoints_stays_idle(self):
        node = _MockNode
        client = Nav2Client(node)
        client.follow_waypoints([])
        assert client.status == "idle"


class TestCancelGoal:
    """Test goal cancellation."""

    def test_cancel_sets_cancelled(self):
        node = _MockNode
        client = Nav2Client(node)
        client.navigate_to(10.0, 5.0)
        client.cancel_goal()
        assert client.status == "cancelled"

    def test_cancel_without_active_goal(self):
        """Cancelling with no active goal should not raise."""
        node = _MockNode
        client = Nav2Client(node)
        client.cancel_goal()
        assert client.status == "cancelled"


class TestGoalCallbacks:
    """Test goal response and result callbacks."""

    def test_goal_rejected_sets_failed(self):
        node = _MockNode
        client = Nav2Client(node)
        client._status = "navigating"
        # Simulate goal rejection
        future = MagicMock()
        goal_handle = MagicMock()
        goal_handle.accepted = False
        future.result.return_value = goal_handle
        client._goal_response_cb(future)
        assert client.status == "failed"

    def test_goal_accepted_stores_handle(self):
        node = _MockNode
        client = Nav2Client(node)
        client._status = "navigating"
        future = MagicMock()
        goal_handle = MagicMock()
        goal_handle.accepted = True
        goal_handle.get_result_async.return_value = MagicMock(
            add_done_callback=MagicMock()
        )
        future.result.return_value = goal_handle
        client._goal_response_cb(future)
        assert client._current_goal_handle is goal_handle

    def test_goal_succeeded(self):
        node = _MockNode
        client = Nav2Client(node)
        client._status = "navigating"
        future = MagicMock()
        result = MagicMock()
        result.status = 4  # STATUS_SUCCEEDED
        future.result.return_value = result
        client._goal_result_cb(future)
        assert client.status == "arrived"

    def test_goal_canceled(self):
        node = _MockNode
        client = Nav2Client(node)
        client._status = "navigating"
        future = MagicMock()
        result = MagicMock()
        result.status = 5  # STATUS_CANCELED
        future.result.return_value = result
        client._goal_result_cb(future)
        assert client.status == "cancelled"

    def test_goal_aborted(self):
        node = _MockNode
        client = Nav2Client(node)
        client._status = "navigating"
        future = MagicMock()
        result = MagicMock()
        result.status = 6  # STATUS_ABORTED
        future.result.return_value = result
        client._goal_result_cb(future)
        assert client.status == "failed"


class TestPoseConstruction:
    """Test that poses are constructed correctly for Nav2."""

    def test_make_pose_position(self):
        node = _MockNode
        client = Nav2Client(node)
        pose = client._make_pose(3.5, -2.1)
        assert pose.pose.position.x == 3.5
        assert pose.pose.position.y == -2.1
        assert pose.pose.position.z == 0.0

    def test_make_pose_frame(self):
        node = _MockNode
        client = Nav2Client(node)
        pose = client._make_pose(0.0, 0.0)
        assert pose.header.frame_id == "map"

    def test_make_pose_orientation_default(self):
        """Default theta=0 should give identity quaternion (z=0, w=1)."""
        node = _MockNode
        client = Nav2Client(node)
        pose = client._make_pose(0.0, 0.0, theta=0.0)
        assert abs(pose.pose.orientation.z - 0.0) < 1e-6
        assert abs(pose.pose.orientation.w - 1.0) < 1e-6

    def test_make_pose_orientation_90_deg(self):
        """90 degree rotation: z=sin(pi/4), w=cos(pi/4)."""
        node = _MockNode
        client = Nav2Client(node)
        theta = math.pi / 2.0
        pose = client._make_pose(0.0, 0.0, theta=theta)
        expected_z = math.sin(theta / 2.0)
        expected_w = math.cos(theta / 2.0)
        assert abs(pose.pose.orientation.z - expected_z) < 1e-6
        assert abs(pose.pose.orientation.w - expected_w) < 1e-6
