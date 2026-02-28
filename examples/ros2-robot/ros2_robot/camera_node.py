# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ROS2 synthetic camera node for TRITIUM-SC.

Generates synthetic video frames using the video_gen renderers and publishes
them via MQTT as JPEG-encoded bytes. Also publishes YOLO-style detection
messages based on the targets visible in the scene.

All configuration via ROS2 parameters -- NO hardcoded IPs or hostnames.

MQTT topics published:
    tritium/{site}/cameras/{robot_id}/frame      — JPEG bytes (QoS 0)
    tritium/{site}/cameras/{robot_id}/detections  — JSON detection payload (QoS 0)

MQTT topics subscribed:
    tritium/{site}/cameras/{robot_id}/command     — camera on/off, scene changes
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

import rclpy
from rclpy.node import Node

import paho.mqtt.client as mqtt

# Add project root to sys.path so we can import engine.synthetic
_project_root = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "..", "src",
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from engine.synthetic.video_gen import (
    render_bird_eye,
    render_street_cam,
    render_battle_scene,
    render_neighborhood,
    _world_to_pixel,
)
from engine.synthetic.video_library import SCENE_TYPES

# Scene type -> renderer mapping
_RENDERERS = {
    "bird_eye": render_bird_eye,
    "street_cam": render_street_cam,
    "battle": render_battle_scene,
    "neighborhood": render_neighborhood,
}


class CameraNode(Node):
    """ROS2 node that generates synthetic camera frames and publishes via MQTT."""

    def __init__(self) -> None:
        super().__init__("synthetic_camera")

        # Declare ROS2 parameters with env var overrides
        self.declare_parameter("mqtt_host", os.environ.get("MQTT_HOST", "localhost"))
        self.declare_parameter("mqtt_port", int(os.environ.get("MQTT_PORT", "1883")))
        self.declare_parameter("site_id", os.environ.get("MQTT_SITE_ID", "home"))
        self.declare_parameter("robot_id", "ros2-rover-alpha")
        self.declare_parameter("robot_name", "ROS2 Rover Alpha")
        self.declare_parameter("asset_type", "rover")
        self.declare_parameter("camera_enabled", True)
        self.declare_parameter("camera_scene_type", "bird_eye")
        self.declare_parameter("camera_fps", 10)
        self.declare_parameter("camera_width", 640)
        self.declare_parameter("camera_height", 480)

        # Read parameter values
        self._mqtt_host: str = self.get_parameter("mqtt_host").value
        self._mqtt_port: int = self.get_parameter("mqtt_port").value
        self._site: str = self.get_parameter("site_id").value
        self._robot_id: str = self.get_parameter("robot_id").value
        self._robot_name: str = self.get_parameter("robot_name").value
        self._asset_type: str = self.get_parameter("asset_type").value
        self._camera_enabled: bool = self.get_parameter("camera_enabled").value
        self._scene_type: str = self.get_parameter("camera_scene_type").value
        self._fps: int = self.get_parameter("camera_fps").value
        self._width: int = self.get_parameter("camera_width").value
        self._height: int = self.get_parameter("camera_height").value

        # Validate scene type — fall back to bird_eye if invalid
        if self._scene_type not in SCENE_TYPES:
            self.get_logger().warn(
                f"Invalid scene type '{self._scene_type}', falling back to 'bird_eye'"
            )
            self._scene_type = "bird_eye"

        # State
        self._frame_count: int = 0
        self._targets: list[dict] = []
        self._seed: int = int(time.time() * 1000) % (2**31)

        # MQTT client setup
        client_id = f"ros2-cam-{self._robot_id}-{int(time.time()) % 10000}"
        self._mqtt_client = mqtt.Client(client_id=client_id)
        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_message = self._on_mqtt_message

        # Connect to MQTT broker
        try:
            self._mqtt_client.connect(self._mqtt_host, self._mqtt_port, keepalive=60)
            self._mqtt_client.loop_start()
            self.get_logger().info(
                f"Camera MQTT connecting to {self._mqtt_host}:{self._mqtt_port}"
            )
        except Exception as e:
            self.get_logger().error(f"Camera MQTT connection failed: {e}")

        # Publishing timer
        period = 1.0 / max(self._fps, 1)
        self._publish_timer = self.create_timer(period, self._tick)

        self.get_logger().info(
            f"Synthetic camera node: scene={self._scene_type}, "
            f"fps={self._fps}, res={self._width}x{self._height}"
        )

    def destroy_node(self) -> None:
        """Clean shutdown."""
        try:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
        except Exception:
            pass
        super().destroy_node()

    # --- MQTT callbacks ---

    def _on_mqtt_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            cmd_topic = f"tritium/{self._site}/cameras/{self._robot_id}/command"
            client.subscribe(cmd_topic, qos=1)
            self.get_logger().info(f"Camera MQTT connected. Subscribed to {cmd_topic}")

    def _on_mqtt_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handle incoming camera commands."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return
        self.handle_camera_command(payload)

    # --- Camera command handling ---

    def handle_camera_command(self, payload: dict) -> None:
        """Process a camera command payload.

        Supported commands:
            camera_on  — enable camera publishing
            camera_off — disable camera publishing
            set_scene  — change scene_type (requires 'scene_type' field)
            set_fps    — change FPS (requires 'fps' field)
        """
        command = payload.get("command", "")

        if command == "camera_on":
            self._camera_enabled = True
            self.get_logger().info("Camera enabled")
        elif command == "camera_off":
            self._camera_enabled = False
            self.get_logger().info("Camera disabled")
        elif command == "set_scene":
            new_scene = payload.get("scene_type", "")
            if new_scene in SCENE_TYPES:
                self._scene_type = new_scene
                self.get_logger().info(f"Scene type changed to: {new_scene}")
            else:
                self.get_logger().warn(f"Invalid scene type: {new_scene}")
        elif command == "set_fps":
            new_fps = payload.get("fps", self._fps)
            if isinstance(new_fps, (int, float)) and new_fps > 0:
                self._fps = int(new_fps)
                self.get_logger().info(f"FPS changed to: {self._fps}")
        else:
            self.get_logger().debug(f"Unknown camera command: {command}")

    # --- Frame generation ---

    def generate_frame(self) -> np.ndarray:
        """Generate a single synthetic frame.

        Returns:
            BGR uint8 numpy array of shape (height, width, 3).
        """
        renderer = _RENDERERS.get(self._scene_type, _RENDERERS["bird_eye"])
        resolution = (self._width, self._height)

        # Build kwargs based on scene type
        kwargs: dict[str, Any] = {
            "resolution": resolution,
            "seed": self._seed + self._frame_count,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }

        if self._scene_type == "bird_eye":
            kwargs["targets"] = self._targets if self._targets else None
        elif self._scene_type == "street_cam":
            kwargs["targets"] = self._targets if self._targets else None
            kwargs["camera_name"] = f"CAM-{self._robot_id}"
        elif self._scene_type == "battle":
            friendlies = [t for t in self._targets if t.get("alliance") == "friendly"]
            hostiles = [t for t in self._targets if t.get("alliance") == "hostile"]
            kwargs["friendlies"] = friendlies if friendlies else None
            kwargs["hostiles"] = hostiles if hostiles else None
        elif self._scene_type == "neighborhood":
            kwargs["ambient_targets"] = self._targets if self._targets else None
            kwargs["camera_name"] = f"NBHD-{self._robot_id}"

        frame = renderer(**kwargs)
        self._frame_count += 1
        return frame

    def generate_jpeg(self, quality: int = 80) -> bytes:
        """Generate a JPEG-encoded frame.

        Args:
            quality: JPEG compression quality (0-100).

        Returns:
            JPEG bytes.
        """
        frame = self.generate_frame()
        _, jpeg_buf = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality],
        )
        return jpeg_buf.tobytes()

    # --- Detection generation ---

    def build_detection_payload(self) -> dict:
        """Build a YOLO-style detection payload from current targets.

        Returns:
            Dict with camera_id, frame_id, timestamp, and detections list.
            Each detection has class_name, confidence, bbox [x1, y1, x2, y2].
        """
        detections = []
        view_radius = 35.0
        view_center = (0.0, 0.0)

        for t in self._targets:
            # Extract position
            pos = t.get("position", {})
            if isinstance(pos, dict):
                tx, ty = float(pos.get("x", 0)), float(pos.get("y", 0))
            elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
                tx, ty = float(pos[0]), float(pos[1])
            else:
                continue

            # Convert to pixel coordinates
            px, py = _world_to_pixel(
                tx, ty, self._width, self._height, view_center, view_radius,
            )

            # Skip if off-screen
            if not (0 <= px < self._width and 0 <= py < self._height):
                continue

            asset_type = t.get("asset_type", "person")
            alliance = t.get("alliance", "unknown")

            # Synthetic confidence: friendlies get higher confidence
            confidence = 0.85 if alliance == "friendly" else 0.75

            # Bounding box: center +/- size
            size = 16  # pixels
            bbox = [
                max(0, px - size),
                max(0, py - size),
                min(self._width, px + size),
                min(self._height, py + size),
            ]

            detections.append({
                "class_name": asset_type,
                "confidence": round(confidence, 2),
                "bbox": bbox,
                "target_id": t.get("target_id", ""),
                "alliance": alliance,
            })

        return {
            "camera_id": self._robot_id,
            "frame_id": self._frame_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detections": detections,
        }

    # --- MQTT publishing ---

    def publish_frame(self) -> None:
        """Publish current frame as JPEG to MQTT."""
        if not self._camera_enabled:
            return
        if not self._mqtt_client.is_connected():
            return

        jpeg = self.generate_jpeg()
        topic = f"tritium/{self._site}/cameras/{self._robot_id}/frame"
        self._mqtt_client.publish(topic, jpeg, qos=0)

    def publish_detections(self) -> None:
        """Publish detection payload to MQTT."""
        if not self._camera_enabled:
            return
        if not self._mqtt_client.is_connected():
            return

        payload = self.build_detection_payload()
        topic = f"tritium/{self._site}/cameras/{self._robot_id}/detections"
        self._mqtt_client.publish(topic, json.dumps(payload), qos=0)

    # --- Timer callback ---

    def _tick(self) -> None:
        """Timer callback: generate and publish a frame + detections."""
        if not self._camera_enabled:
            return
        try:
            self.publish_frame()
            # Publish detections at a lower rate (every 5th frame)
            if self._frame_count % 5 == 0:
                self.publish_detections()
        except Exception as e:
            self.get_logger().debug(f"Camera tick error: {e}")

    # --- Target updates ---

    def update_targets(self, targets: list[dict]) -> None:
        """Update the target list for rendering.

        Called externally (e.g., from telemetry or MQTT subscription).

        Args:
            targets: List of target dicts with position, alliance, asset_type.
        """
        self._targets = targets


def main(args=None):
    rclpy.init(args=args)
    node = CameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
