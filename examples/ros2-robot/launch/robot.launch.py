# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ROS2 launch file for TRITIUM-SC robot.

Usage:
    ros2 launch ros2_robot robot.launch.py
    ros2 launch ros2_robot robot.launch.py use_sim_odom:=false
    ros2 launch ros2_robot robot.launch.py mqtt_host:=192.168.1.100
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration

from launch_ros.actions import Node


def generate_launch_description():
    # Locate default params file
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_params = os.path.join(pkg_dir, "config", "robot_params.yaml")

    return LaunchDescription([
        # Launch arguments (override via CLI or env)
        DeclareLaunchArgument(
            "params_file",
            default_value=default_params,
            description="Path to robot_params.yaml",
        ),
        DeclareLaunchArgument(
            "use_sim_odom",
            default_value="true",
            description="Launch simulated odometry (false for real hardware)",
        ),
        DeclareLaunchArgument(
            "mqtt_host",
            default_value=os.environ.get("MQTT_HOST", "localhost"),
            description="MQTT broker hostname (no hardcoded IPs)",
        ),
        DeclareLaunchArgument(
            "mqtt_port",
            default_value=os.environ.get("MQTT_PORT", "1883"),
            description="MQTT broker port",
        ),
        DeclareLaunchArgument(
            "site_id",
            default_value=os.environ.get("MQTT_SITE_ID", "home"),
            description="TRITIUM-SC site identifier",
        ),

        # Simulated odometry (for testing without hardware)
        Node(
            package="ros2_robot",
            executable="simulated_odom",
            name="simulated_odom",
            condition=IfCondition(LaunchConfiguration("use_sim_odom")),
            output="screen",
        ),

        # MQTT bridge node
        Node(
            package="ros2_robot",
            executable="mqtt_bridge",
            name="mqtt_bridge",
            parameters=[
                LaunchConfiguration("params_file"),
                {
                    "mqtt_host": LaunchConfiguration("mqtt_host"),
                    "mqtt_port": LaunchConfiguration("mqtt_port"),
                    "site_id": LaunchConfiguration("site_id"),
                },
            ],
            output="screen",
        ),

        # Telemetry publisher
        Node(
            package="ros2_robot",
            executable="telemetry_publisher",
            name="telemetry_publisher",
            parameters=[LaunchConfiguration("params_file")],
            output="screen",
        ),
    ])
