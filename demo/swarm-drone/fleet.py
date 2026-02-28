#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Fleet launcher -- spawns N swarm drone subprocesses.

Usage:
    python fleet.py --count 4 --prefix swarm --mqtt-host localhost
"""

import argparse
import math
import os
import signal
import subprocess
import sys
import time


def build_drone_args(
    drone_id: str,
    mqtt_host: str,
    mqtt_port: int,
    site: str,
    start_x: float,
    start_y: float,
) -> list[str]:
    """Build CLI argument list for a single drone subprocess."""
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    return [
        sys.executable,
        main_py,
        "--drone-id", drone_id,
        "--mqtt-host", mqtt_host,
        "--mqtt-port", str(mqtt_port),
        "--site", site,
        "--start-x", str(start_x),
        "--start-y", str(start_y),
    ]


def generate_start_positions(
    count: int,
    center_x: float = 0.0,
    center_y: float = 0.0,
    radius: float = 10.0,
) -> list[tuple[float, float]]:
    """Generate evenly-spaced start positions in a circle."""
    if count == 0:
        return []
    if count == 1:
        return [(center_x, center_y)]
    positions = []
    for i in range(count):
        angle = 2.0 * math.pi * i / count
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        positions.append((x, y))
    return positions


def validate_fleet_args(count: int, prefix: str, mqtt_host: str) -> list[str]:
    """Validate fleet parameters. Returns list of error strings (empty = valid)."""
    errors = []
    if count <= 0:
        errors.append(f"count must be positive, got {count}")
    if not prefix:
        errors.append("prefix must not be empty")
    if not mqtt_host:
        errors.append("mqtt_host must not be empty")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TRITIUM-SC Swarm Drone Fleet Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fleet.py --count 4 --prefix swarm --mqtt-host localhost
  python fleet.py --count 8 --prefix alpha --center-x 50 --center-y 50 --radius 20
""",
    )
    parser.add_argument("--count", type=int, default=4, help="Number of drones to launch")
    parser.add_argument("--prefix", default="swarm", help="Drone ID prefix (e.g. swarm -> swarm-01)")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--site", default="home", help="Site ID for MQTT topics")
    parser.add_argument("--center-x", type=float, default=0.0, help="Fleet center X")
    parser.add_argument("--center-y", type=float, default=0.0, help="Fleet center Y")
    parser.add_argument("--radius", type=float, default=10.0, help="Fleet spawn radius")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    errors = validate_fleet_args(args.count, args.prefix, args.mqtt_host)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)

    positions = generate_start_positions(
        count=args.count,
        center_x=args.center_x,
        center_y=args.center_y,
        radius=args.radius,
    )

    print(f"{'=' * 50}")
    print(f"  TRITIUM-SC Swarm Fleet Launcher")
    print(f"  Drones: {args.count}")
    print(f"  Prefix: {args.prefix}")
    print(f"  MQTT: {args.mqtt_host}:{args.mqtt_port}")
    print(f"  Site: {args.site}")
    print(f"  Center: ({args.center_x}, {args.center_y})")
    print(f"  Radius: {args.radius}")
    print(f"{'=' * 50}")

    procs: list[subprocess.Popen] = []

    for i, (sx, sy) in enumerate(positions):
        drone_id = f"{args.prefix}-{i + 1:02d}"
        cmd = build_drone_args(
            drone_id=drone_id,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
            site=args.site,
            start_x=sx,
            start_y=sy,
        )
        print(f"  Launching {drone_id} at ({sx:.1f}, {sy:.1f})")
        proc = subprocess.Popen(cmd)
        procs.append(proc)

    print(f"\n  {len(procs)} drones launched. Ctrl+C to stop all.")

    # Wait for Ctrl+C, then kill all
    running = True

    def shutdown(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while running:
            time.sleep(0.5)
            # Check if any died
            for p in procs:
                if p.poll() is not None:
                    pass  # Process exited
    finally:
        print("\n  Shutting down fleet...")
        for p in procs:
            if p.poll() is None:
                p.terminate()
        # Wait for all to exit
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        print(f"  {len(procs)} drones stopped.")


if __name__ == "__main__":
    main()
