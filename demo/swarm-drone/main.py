#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Swarm Drone -- single drone MQTT agent.

Usage:
    python main.py --drone-id swarm-01 --mqtt-host localhost --start-x 10 --start-y 20
"""

import argparse
import signal
import sys
import time

from drone import SwarmDrone
from mqtt_client import DroneMQTTClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TRITIUM-SC Swarm Drone Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --drone-id swarm-01 --mqtt-host localhost
  python main.py --drone-id swarm-01 --mqtt-host localhost --start-x 10 --start-y 20
""",
    )
    parser.add_argument("--drone-id", default="swarm-01", help="Drone identifier")
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

    # Create drone
    drone = SwarmDrone(
        drone_id=args.drone_id,
        start_x=args.start_x,
        start_y=args.start_y,
    )

    # Create MQTT client
    mqtt_client = DroneMQTTClient(
        drone_id=args.drone_id,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        site=args.site,
    )

    # Command handler
    def handle_command(cmd: dict) -> None:
        command = cmd.get("command", "")
        if command == "dispatch":
            x = cmd.get("x", 0.0)
            y = cmd.get("y", 0.0)
            drone.dispatch(x, y)
            print(f"  [CMD] dispatch to ({x:.1f}, {y:.1f})")
        elif command == "patrol":
            waypoints = cmd.get("waypoints", [])
            drone.patrol(waypoints)
            print(f"  [CMD] patrol {len(waypoints)} waypoints")
        elif command == "recall":
            drone.recall()
            print(f"  [CMD] recall")
        elif command == "stop":
            drone.stop()
            print(f"  [CMD] stop")
        else:
            print(f"  [CMD] unknown: {command}")

    # Elimination handler
    def handle_elimination(data: dict) -> None:
        target_id = data.get("target_id", "")
        if target_id == args.drone_id:
            drone.eliminate()
            print(f"  [ELIMINATED] by {data.get('eliminated_by', 'unknown')}")

    mqtt_client.on_command = handle_command
    mqtt_client.on_elimination = handle_elimination

    # Connect
    print(f"{'=' * 50}")
    print(f"  TRITIUM-SC Swarm Drone")
    print(f"  ID: {args.drone_id}")
    print(f"  Start: ({args.start_x}, {args.start_y})")
    print(f"  MQTT: {args.mqtt_host}:{args.mqtt_port}")
    print(f"  Site: {args.site}")
    print(f"{'=' * 50}")

    mqtt_client.setup()
    mqtt_client.connect()
    print("  Drone online. Ctrl+C to stop.")

    # Graceful shutdown
    running = True

    def shutdown(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Main loop
    tick_interval = 0.05  # 20Hz
    telemetry_timer = 0.0

    try:
        while running:
            telemetry = drone.tick(tick_interval)
            telemetry_timer += tick_interval

            if telemetry_timer >= args.telemetry_interval:
                mqtt_client.publish_telemetry(telemetry)
                telemetry_timer = 0.0

            time.sleep(tick_interval)
    finally:
        print("\n  Shutting down...")
        mqtt_client.disconnect()
        print("  Drone offline.")


if __name__ == "__main__":
    main()
