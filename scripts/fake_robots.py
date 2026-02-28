#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Fake MQTT robot fleet for testing.

Spawns N fake robots that publish telemetry and respond to commands.
Uses SimulationTarget for physics (waypoint movement).

Usage:
    python3 scripts/fake_robots.py --count 3 --broker localhost
    python3 scripts/fake_robots.py --count 3 --broker GB10-02
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import signal
import sys
import time
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("fake_robots")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from engine.simulation.target import SimulationTarget

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


class FakeRobot:
    """A simulated robot that publishes MQTT telemetry."""

    def __init__(self, robot_id: str, client: Any, site: str = "home"):
        self.robot_id = robot_id
        self.client = client
        self.site = site
        start_x = random.uniform(-20, 20)
        start_y = random.uniform(-20, 20)
        self.target = SimulationTarget(
            target_id=robot_id,
            name=robot_id,
            asset_type="rover",
            alliance="friendly",
            position=(start_x, start_y),
            speed=2.0,
        )
        self.target.loop_waypoints = True
        self._set_random_patrol()

    def _set_random_patrol(self):
        """Set random patrol waypoints."""
        waypoints = []
        for _ in range(random.randint(3, 6)):
            waypoints.append((random.uniform(-20, 20), random.uniform(-20, 20)))
        self.target.waypoints = waypoints
        self.target._waypoint_index = 0

    def tick(self, dt: float):
        """Update physics."""
        self.target.tick(dt)

    def publish_telemetry(self):
        """Publish current state to MQTT."""
        topic = f"tritium/{self.site}/robots/{self.robot_id}/telemetry"
        payload = {
            "robot_id": self.robot_id,
            "x": round(self.target.position[0], 2),
            "y": round(self.target.position[1], 2),
            "heading": round(self.target.heading, 1),
            "battery": round(self.target.battery, 2),
            "status": self.target.status,
            "timestamp": time.time(),
        }
        self.client.publish(topic, json.dumps(payload))

    def handle_command(self, payload: dict):
        """Handle incoming command."""
        action = payload.get("action")
        logger.info(f"[{self.robot_id}] Command: {action}")

        if action == "dispatch":
            self.target.waypoints = [(payload["x"], payload["y"])]
            self.target._waypoint_index = 0
            self.target.loop_waypoints = False
            self.target.status = "active"
        elif action == "patrol":
            wps = [(w["x"], w["y"]) for w in payload.get("waypoints", [])]
            self.target.waypoints = wps
            self.target._waypoint_index = 0
            self.target.loop_waypoints = True
            self.target.status = "active"
        elif action == "recall":
            self.target.waypoints = [(0, 0)]
            self.target._waypoint_index = 0
            self.target.loop_waypoints = False
            self.target.status = "active"

        # ACK
        ack_topic = f"tritium/{self.site}/robots/{self.robot_id}/command/ack"
        self.client.publish(ack_topic, json.dumps({
            "robot_id": self.robot_id,
            "action": action,
            "status": "acknowledged",
            "timestamp": time.time(),
        }))


def main():
    if mqtt is None:
        logger.error("paho-mqtt not installed: pip install paho-mqtt")
        sys.exit(1)
    parser = argparse.ArgumentParser(description="Fake MQTT robot fleet")
    parser.add_argument("--count", type=int, default=3, help="Number of robots")
    parser.add_argument("--broker", type=str, default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--site", type=str, default="home", help="Site ID")
    args = parser.parse_args()

    client = mqtt.Client(client_id=f"fake-robots-{random.randint(1000, 9999)}")

    robots = {}
    for i in range(args.count):
        rid = f"fake-rover-{i:02d}"
        robots[rid] = FakeRobot(rid, client, args.site)

    def on_connect(c, userdata, flags, rc):
        logger.info(f"Connected to MQTT broker (rc={rc})")
        for rid in robots:
            topic = f"tritium/{args.site}/robots/{rid}/command"
            c.subscribe(topic)
            logger.info(f"Subscribed: {topic}")

    def on_message(c, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            # Extract robot_id from topic
            parts = msg.topic.split("/")
            rid = parts[3] if len(parts) >= 5 else None
            if rid and rid in robots:
                robots[rid].handle_command(payload)
        except Exception as e:
            logger.error(f"Message error: {e}")

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(args.broker, args.port, keepalive=60)
    except Exception as e:
        logger.error(f"Cannot connect to {args.broker}:{args.port}: {e}")
        sys.exit(1)

    client.loop_start()

    running = True
    def sigint_handler(sig, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, sigint_handler)

    logger.info(f"Running {len(robots)} fake robots, publishing at 2Hz")
    tick_interval = 0.1  # 10Hz physics
    publish_interval = 0.5  # 2Hz telemetry
    last_publish = 0

    try:
        while running:
            now = time.monotonic()
            for robot in robots.values():
                robot.tick(tick_interval)

            if now - last_publish >= publish_interval:
                for robot in robots.values():
                    robot.publish_telemetry()
                last_publish = now

            time.sleep(tick_interval)
    finally:
        client.loop_stop()
        client.disconnect()
        logger.info("Fake robots stopped")


if __name__ == "__main__":
    main()
