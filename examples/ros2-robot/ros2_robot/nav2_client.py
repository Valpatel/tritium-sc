# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Nav2 action client for ROS2 robot navigation.

Wraps Nav2's NavigateToPose and FollowWaypoints action servers.
Reports navigation status for telemetry publishing.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import rclpy
from rclpy.action import ActionClient
from rclpy.action.client import ClientGoalHandle

from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose, FollowWaypoints

if TYPE_CHECKING:
    from rclpy.node import Node


class Nav2Client:
    """Action client for Nav2 NavigateToPose and FollowWaypoints."""

    def __init__(self, node: Node) -> None:
        self._node = node
        self._nav_to_pose_client = ActionClient(
            node, NavigateToPose, "navigate_to_pose"
        )
        self._follow_waypoints_client = ActionClient(
            node, FollowWaypoints, "follow_waypoints"
        )
        self._current_goal_handle: ClientGoalHandle | None = None
        self._status = "idle"
        self._feedback_distance: float = 0.0
        self._feedback_eta: float = 0.0

    @property
    def status(self) -> str:
        """Current navigation status: idle, navigating, arrived, cancelled, failed."""
        return self._status

    @property
    def feedback_distance(self) -> float:
        """Distance remaining to goal (from last feedback)."""
        return self._feedback_distance

    @property
    def feedback_eta(self) -> float:
        """Estimated time to arrival in seconds (from last feedback)."""
        return self._feedback_eta

    def navigate_to(self, x: float, y: float, theta: float = 0.0) -> None:
        """Send a single-point navigation goal to Nav2.

        Args:
            x: Target X position in map frame (meters).
            y: Target Y position in map frame (meters).
            theta: Target heading in radians (default 0).
        """
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = self._make_pose(x, y, theta)

        self._status = "navigating"
        self._feedback_distance = 0.0
        self._feedback_eta = 0.0

        self._node.get_logger().info(f"Nav2: navigate_to ({x:.1f}, {y:.1f})")

        self._nav_to_pose_client.wait_for_server(timeout_sec=5.0)
        future = self._nav_to_pose_client.send_goal_async(
            goal_msg, feedback_callback=self._nav_feedback_cb
        )
        future.add_done_callback(self._goal_response_cb)

    def follow_waypoints(self, waypoints: list[tuple[float, float]]) -> None:
        """Send a waypoint sequence to Nav2 FollowWaypoints.

        Args:
            waypoints: List of (x, y) tuples in map frame (meters).
        """
        if not waypoints:
            return

        goal_msg = FollowWaypoints.Goal()
        goal_msg.poses = [self._make_pose(x, y) for x, y in waypoints]

        self._status = "navigating"
        self._feedback_distance = 0.0

        self._node.get_logger().info(
            f"Nav2: follow_waypoints ({len(waypoints)} points)"
        )

        self._follow_waypoints_client.wait_for_server(timeout_sec=5.0)
        future = self._follow_waypoints_client.send_goal_async(
            goal_msg, feedback_callback=self._waypoint_feedback_cb
        )
        future.add_done_callback(self._goal_response_cb)

    def cancel_goal(self) -> None:
        """Cancel the current navigation goal."""
        if self._current_goal_handle is not None:
            self._node.get_logger().info("Nav2: cancelling goal")
            self._current_goal_handle.cancel_goal_async()
            self._current_goal_handle = None
        self._status = "cancelled"

    # --- Internal callbacks ---

    def _make_pose(self, x: float, y: float, theta: float = 0.0) -> PoseStamped:
        """Create a PoseStamped message in the map frame."""
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = self._node.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.position.z = 0.0
        # Convert heading to quaternion (rotation around Z axis)
        pose.pose.orientation.z = math.sin(theta / 2.0)
        pose.pose.orientation.w = math.cos(theta / 2.0)
        return pose

    def _goal_response_cb(self, future) -> None:
        """Handle goal acceptance/rejection from Nav2."""
        goal_handle = future.result()
        if not goal_handle.accepted:
            self._node.get_logger().warn("Nav2: goal rejected")
            self._status = "failed"
            self._current_goal_handle = None
            return

        self._node.get_logger().info("Nav2: goal accepted")
        self._current_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._goal_result_cb)

    def _goal_result_cb(self, future) -> None:
        """Handle navigation result (success/failure)."""
        result = future.result()
        status = result.status
        # GoalStatus values: STATUS_SUCCEEDED=4, STATUS_CANCELED=5, STATUS_ABORTED=6
        if status == 4:  # SUCCEEDED
            self._node.get_logger().info("Nav2: goal reached")
            self._status = "arrived"
        elif status == 5:  # CANCELED
            self._node.get_logger().info("Nav2: goal cancelled")
            self._status = "cancelled"
        else:
            self._node.get_logger().warn(f"Nav2: goal failed (status={status})")
            self._status = "failed"
        self._current_goal_handle = None

    def _nav_feedback_cb(self, feedback_msg) -> None:
        """Handle NavigateToPose feedback (distance, ETA)."""
        feedback = feedback_msg.feedback
        self._feedback_distance = feedback.distance_remaining
        self._feedback_eta = feedback.estimated_time_remaining.sec

    def _waypoint_feedback_cb(self, feedback_msg) -> None:
        """Handle FollowWaypoints feedback (current waypoint index)."""
        feedback = feedback_msg.feedback
        current_wp = feedback.current_waypoint
        self._node.get_logger().debug(f"Nav2: at waypoint {current_wp}")
