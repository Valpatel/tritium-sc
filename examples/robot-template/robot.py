#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TRITIUM-SC Robot Template — standalone robot brain.

Connects to TRITIUM-SC via MQTT. Publishes telemetry, receives commands.
Runs YOLO for fast visual tracking and LLM for deeper autonomous thinking.
Runs completely independently on any Python-capable hardware.

Usage:
    python robot.py --simulate          # Simulated hardware (testing)
    python robot.py --config config.yaml  # Real hardware
"""

import argparse
import signal
import sys
import threading
import time

import yaml

from brain.mqtt_client import RobotMQTTClient
from brain.navigator import Navigator
from brain.turret import TurretController
from brain.telemetry import TelemetryPublisher
from brain.thinker import RobotThinker
from brain.camera import RobotCamera
from brain.vision_bridge import VisionBridge


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
    camera = RobotCamera(mqtt, config)
    vision_bridge = VisionBridge(config.get("camera", {}))
    thinker = RobotThinker(config)

    # Wire YOLO detections → vision bridge (camera detects, thinker reasons)
    _original_publish_detection = mqtt.publish_detection
    def _publish_detection_with_bridge(detections: list[dict]) -> None:
        """Intercept YOLO detections: publish to MQTT AND feed to thinker."""
        _original_publish_detection(detections)
        vision_bridge.push_detections(detections)
    mqtt.publish_detection = _publish_detection_with_bridge

    # Wire thinker action handlers to hardware
    thinker.on_action("say", lambda params: mqtt.publish_thought(
        thinker.to_mqtt_message()
    ))
    thinker.on_action("look_at", lambda params: (
        turret.aim(
            {"left": -45, "right": 45, "up": 0, "down": 0, "center": 0}.get(
                params[0] if params else "center", 0
            ),
            {"up": 30, "down": -15, "center": 0}.get(
                params[0] if params else "center", 0
            ),
        ) if params else None
    ))
    thinker.on_action("fire_nerf", lambda params: turret.fire())

    # Register fire_nerf if not already in config
    if "fire_nerf" not in thinker.actions:
        thinker.register_action("fire_nerf", description="Fire the nerf turret")

    # Wire command handler
    recent_commands: list[dict] = []

    def handle_command(command: dict):
        cmd = command.get("command", "")
        cmd_ts = command.get("timestamp", "")
        recent_commands.append(command)
        if len(recent_commands) > 10:
            recent_commands.pop(0)

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
    camera.start()

    # Start thinker loop (threaded, if enabled)
    think_running = True

    def think_loop():
        """Autonomous thinking loop — YOLO detects fast, LLM decides deep."""
        while think_running and thinker.enabled:
            try:
                pos = hw.get_position()
                tel = {
                    "position": {"x": pos[0], "y": pos[1]},
                    "battery": hw.get_battery(),
                    "status": navigator.status,
                }
                # Feed YOLO detections into thinker context
                nearby = vision_bridge.get_nearby_targets(robot_position=pos)
                result = thinker.think_once(
                    telemetry=tel,
                    nearby_targets=nearby,
                    recent_commands=recent_commands[-3:],
                )
                if result:
                    action = result["action"]
                    params = result["params"]
                    print(f"  [THINK] {action}({', '.join(repr(p) for p in params)})")
                    thinker.dispatch_action(action, params)

                    # Publish thought to Amy
                    if mqtt.connected:
                        mqtt.publish_thought(thinker.to_mqtt_message())
            except Exception as e:
                print(f"  [THINK] Error: {e}")

            time.sleep(thinker.think_interval)

    think_thread = None
    if thinker.enabled:
        print(f"  Thinker: {thinker.model} @ {thinker.ollama_host} (every {thinker.think_interval}s)")
        think_thread = threading.Thread(target=think_loop, daemon=True)
        think_thread.start()
    else:
        print("  Thinker: disabled (enable in config.yaml)")

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
        think_running = False
        if think_thread:
            think_thread.join(timeout=2)
        camera.stop()
        telemetry.stop()
        navigator.stop()
        mqtt.disconnect()
        hw.shutdown()
        print("  Robot offline.")


if __name__ == "__main__":
    main()
