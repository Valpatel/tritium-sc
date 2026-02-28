#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo Robot Server — standalone MQTT robot simulator.

Simulates a mobile robot (rover, drone, turret, tank) that publishes
telemetry via MQTT, receives dispatch/patrol/recall commands, and
simulates physics-based movement.

Usage:
    python main.py --robot-id demo-rover-01 --type rover --name "Rover Alpha" \
        --mqtt-host localhost --mqtt-port 1883 --site home \
        --start-x 0 --start-y 0 --telemetry-interval 0.5
"""

import argparse
import signal
import sys
import time

from config import RobotConfig
from robot import Robot
from mqtt_client import RobotMQTTClient, parse_command, VALID_COMMANDS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TRITIUM-SC Demo Robot Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --robot-id demo-rover-01 --type rover --name "Rover Alpha"
  python main.py --robot-id demo-drone-01 --type drone --name "Drone One" --start-x 5 --start-y 5
  python main.py --robot-id demo-turret-01 --type turret --name "Turret Alpha"
  python main.py --robot-id demo-tank-01 --type tank --name "Tank One"
""",
    )
    parser.add_argument("--robot-id", default="demo-rover-01", help="Robot identifier")
    parser.add_argument("--type", default="rover", choices=["rover", "drone", "turret", "tank"],
                        help="Robot type (default: rover)")
    parser.add_argument("--name", default=None, help="Human-readable name (default: robot-id)")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--site", default="home", help="Site ID for MQTT topics")
    parser.add_argument("--start-x", type=float, default=0.0, help="Start X position")
    parser.add_argument("--start-y", type=float, default=0.0, help="Start Y position")
    parser.add_argument("--telemetry-interval", type=float, default=0.5,
                        help="Telemetry publish interval in seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = RobotConfig(
        robot_id=args.robot_id,
        name=args.name or args.robot_id,
        asset_type=args.type,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        site=args.site,
        start_x=args.start_x,
        start_y=args.start_y,
        telemetry_interval=args.telemetry_interval,
    )

    # Create robot
    robot = Robot(
        robot_id=config.robot_id,
        asset_type=config.asset_type,
        name=config.name,
        start_x=config.start_x,
        start_y=config.start_y,
    )

    # Create MQTT client
    mqtt_client = RobotMQTTClient(config)

    # Command handler
    def handle_command(cmd: dict) -> None:
        command = cmd.get("command", "")
        cmd_ts = cmd.get("timestamp", "")

        if command == "dispatch":
            x = cmd.get("x", 0.0)
            y = cmd.get("y", 0.0)
            robot.dispatch(x, y)
            mqtt_client.publish_ack(command, cmd_ts, "accepted")
            print(f"  [CMD] dispatch to ({x:.1f}, {y:.1f})")

        elif command == "patrol":
            waypoints = cmd.get("waypoints", [])
            robot.patrol(waypoints)
            mqtt_client.publish_ack(command, cmd_ts, "accepted")
            print(f"  [CMD] patrol {len(waypoints)} waypoints")

        elif command == "recall":
            robot.recall()
            mqtt_client.publish_ack(command, cmd_ts, "accepted")
            print(f"  [CMD] recall to start")

        elif command == "fire":
            tx = cmd.get("target_x", 0.0)
            ty = cmd.get("target_y", 0.0)
            robot.fire(tx, ty)
            mqtt_client.publish_ack(command, cmd_ts, "accepted")
            print(f"  [CMD] fire at ({tx:.1f}, {ty:.1f})")

        elif command == "aim":
            pan = cmd.get("pan", 0.0)
            tilt = cmd.get("tilt", 0.0)
            robot.aim(pan, tilt)
            mqtt_client.publish_ack(command, cmd_ts, "accepted")
            print(f"  [CMD] aim pan={pan:.1f} tilt={tilt:.1f}")

        elif command == "stop":
            robot.stop()
            mqtt_client.publish_ack(command, cmd_ts, "accepted")
            print(f"  [CMD] stop")

        else:
            mqtt_client.publish_ack(command, cmd_ts, "rejected")
            print(f"  [CMD] unknown: {command}")

    mqtt_client.on_command = handle_command

    # Connect
    print(f"{'=' * 50}")
    print(f"  TRITIUM-SC Demo Robot Server")
    print(f"  ID: {config.robot_id}")
    print(f"  Name: {config.name}")
    print(f"  Type: {config.asset_type}")
    print(f"  Start: ({config.start_x}, {config.start_y})")
    print(f"  MQTT: {config.mqtt_host}:{config.mqtt_port}")
    print(f"  Site: {config.site}")
    print(f"  Telemetry interval: {config.telemetry_interval}s")
    print(f"{'=' * 50}")

    mqtt_client.setup()
    mqtt_client.connect()
    print("  Robot online. Ctrl+C to stop.")

    # Graceful shutdown
    running = True

    def shutdown(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Main loop: tick physics at 50Hz, publish telemetry at configured interval
    tick_interval = 0.02  # 50Hz internal tick
    telemetry_timer = 0.0

    try:
        while running:
            telemetry = robot.tick(tick_interval)
            telemetry_timer += tick_interval

            if telemetry_timer >= config.telemetry_interval:
                mqtt_client.publish_telemetry(telemetry)
                telemetry_timer = 0.0

            time.sleep(tick_interval)
    finally:
        print("\n  Shutting down...")
        mqtt_client.disconnect()
        print("  Robot offline.")


if __name__ == "__main__":
    main()
