#!/usr/bin/env python3
"""TRITIUM-SC Robot Template — standalone robot brain.

Connects to TRITIUM-SC via MQTT. Publishes telemetry, receives commands.
Runs completely independently on any Python-capable hardware.

Usage:
    python robot.py --simulate          # Simulated hardware (testing)
    python robot.py --config config.yaml  # Real hardware
"""

import argparse
import signal
import sys
import time

import yaml

from brain.mqtt_client import RobotMQTTClient
from brain.navigator import Navigator
from brain.turret import TurretController
from brain.telemetry import TelemetryPublisher


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def create_hardware(config: dict):
    mode = config.get("hardware", {}).get("mode", "simulated")
    if mode == "simulated":
        from hardware.simulated import SimulatedHardware
        return SimulatedHardware(config)
    elif mode == "gpio":
        from hardware.gpio_rc import GPIOHardware
        return GPIOHardware(config)
    else:
        raise ValueError(f"Unknown hardware mode: {mode}")


def main():
    parser = argparse.ArgumentParser(description="TRITIUM-SC Robot Brain")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--simulate", action="store_true", help="Force simulated hardware")
    parser.add_argument("--robot-id", default=None, help="Override robot ID")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.simulate:
        config.setdefault("hardware", {})["mode"] = "simulated"
    if args.robot_id:
        config["robot_id"] = args.robot_id

    robot_id = config.get("robot_id", "rover-alpha")
    robot_name = config.get("robot_name", robot_id)
    site_id = config.get("site_id", "home")
    home_pos = config.get("home_position", {"x": 0, "y": 0})

    print(f"{'=' * 50}")
    print(f"  TRITIUM-SC Robot: {robot_name}")
    print(f"  ID: {robot_id}  Site: {site_id}")
    print(f"  Hardware: {config.get('hardware', {}).get('mode', 'simulated')}")
    print(f"{'=' * 50}")

    # Create hardware backend
    hw = create_hardware(config)
    hw.initialize()

    # Create brain components
    mqtt = RobotMQTTClient(config)
    navigator = Navigator(hw, config)
    turret = TurretController(hw, config)
    telemetry = TelemetryPublisher(mqtt, hw, navigator, turret, config)

    # Wire command handler
    def handle_command(command: dict):
        cmd = command.get("command", "")
        cmd_ts = command.get("timestamp", "")
        if cmd == "dispatch":
            x, y = command.get("x", 0), command.get("y", 0)
            print(f"  [CMD] Dispatch to ({x:.1f}, {y:.1f})")
            navigator.go_to(x, y)
            mqtt.publish_command_ack(cmd, cmd_ts, "accepted")
        elif cmd == "patrol":
            waypoints = command.get("waypoints", [])
            wps = [(w["x"], w["y"]) for w in waypoints]
            print(f"  [CMD] Patrol {len(wps)} waypoints")
            navigator.patrol(wps)
            mqtt.publish_command_ack(cmd, cmd_ts, "accepted")
        elif cmd == "recall":
            hx, hy = home_pos.get("x", 0), home_pos.get("y", 0)
            print(f"  [CMD] Recall to home ({hx:.1f}, {hy:.1f})")
            navigator.go_to(hx, hy)
            mqtt.publish_command_ack(cmd, cmd_ts, "accepted")
        elif cmd == "turret_aim":
            pan = command.get("pan", 0)
            tilt = command.get("tilt", 0)
            turret.aim(pan, tilt)
            mqtt.publish_command_ack(cmd, cmd_ts, "accepted")
        elif cmd == "fire":
            turret.fire()
            mqtt.publish_command_ack(cmd, cmd_ts, "accepted")
        elif cmd == "stop":
            navigator.stop()
            turret.stop()
            mqtt.publish_command_ack(cmd, cmd_ts, "accepted")
        else:
            print(f"  [CMD] Unknown command: {cmd}")
            mqtt.publish_command_ack(cmd, cmd_ts, "rejected")

    mqtt.on_command = handle_command

    # Start everything
    mqtt.connect()
    navigator.start()
    telemetry.start()
    print("  Robot brain online. Ctrl+C to stop.")

    # Graceful shutdown
    running = True
    def shutdown(sig, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while running:
            time.sleep(0.1)
    finally:
        print("\n  Shutting down...")
        telemetry.stop()
        navigator.stop()
        mqtt.disconnect()
        hw.shutdown()
        print("  Robot offline.")


if __name__ == "__main__":
    main()
