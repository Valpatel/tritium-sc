#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo motion sensor entry point.

Simulates a PIR, microwave, acoustic, or tripwire motion sensor
that publishes detection events via MQTT.

Usage:
    python main.py --sensor-id demo-pir-01 --type pir --zone front_door \
        --mqtt-host localhost --mqtt-port 1883 --site home \
        --position-x 25.0 --position-y -10.0 --pattern random --rate 0.5
"""

import argparse
import logging
import signal
import sys
import time

from config import SensorConfig
from mqtt_client import SensorMQTTClient
from patterns import RandomPattern, ScheduledPattern, BurstPattern, WalkByPattern
from sensor import MotionSensor

logger = logging.getLogger(__name__)

PATTERN_MAP = {
    "random": RandomPattern,
    "scheduled": ScheduledPattern,
    "burst": BurstPattern,
    "walk_by": WalkByPattern,
}

TICK_INTERVAL = 0.1  # 10 Hz tick loop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Demo motion sensor — publishes detection events via MQTT",
    )
    parser.add_argument("--sensor-id", default="demo-pir-01", help="Sensor ID")
    parser.add_argument(
        "--type",
        default="pir",
        choices=["pir", "microwave", "acoustic", "tripwire"],
        help="Sensor type",
    )
    parser.add_argument("--zone", default="default", help="Zone name")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--site", default="home", help="Site ID for MQTT topic prefix")
    parser.add_argument("--position-x", type=float, default=0.0, help="X position")
    parser.add_argument("--position-y", type=float, default=0.0, help="Y position")
    parser.add_argument(
        "--pattern",
        default="random",
        choices=list(PATTERN_MAP.keys()),
        help="Trigger pattern",
    )
    parser.add_argument("--rate", type=float, default=0.5, help="Trigger rate (Hz)")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> SensorConfig:
    return SensorConfig(
        sensor_id=args.sensor_id,
        sensor_type=args.type,
        zone=args.zone,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        site=args.site,
        position_x=args.position_x,
        position_y=args.position_y,
        pattern=args.pattern,
        rate=args.rate,
    )


def run(config: SensorConfig) -> None:
    """Main sensor loop."""
    sensor = MotionSensor(
        sensor_id=config.sensor_id,
        sensor_type=config.sensor_type,
        zone=config.zone,
        position_x=config.position_x,
        position_y=config.position_y,
    )

    pattern_cls = PATTERN_MAP[config.pattern]
    if config.pattern == "scheduled":
        pattern = pattern_cls(interval=1.0 / max(config.rate, 0.001))
    else:
        pattern = pattern_cls(rate=config.rate)

    mqtt_client = SensorMQTTClient(config)

    running = True

    def handle_command(cmd: dict) -> None:
        command = cmd.get("command", "")
        if command == "enable":
            sensor.enabled = True
            logger.info("Sensor enabled via MQTT command")
        elif command == "disable":
            sensor.enabled = False
            logger.info("Sensor disabled via MQTT command")
        else:
            logger.warning("Unknown command: %s", command)

    mqtt_client.on_command = handle_command

    def shutdown(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        mqtt_client.connect()
        mqtt_client.subscribe_commands()
        mqtt_client.publish_status("online")

        logger.info(
            "Sensor %s (%s) running — zone=%s pattern=%s rate=%.2f",
            config.sensor_id,
            config.sensor_type,
            config.zone,
            config.pattern,
            config.rate,
        )

        last_tick = time.monotonic()

        while running:
            now = time.monotonic()
            dt = now - last_tick
            last_tick = now

            sensor.tick()

            if pattern.should_trigger(dt):
                event = sensor.trigger()
                if event is not None:
                    mqtt_client.publish_event(event)
                    logger.info(
                        "TRIGGERED — confidence=%.2f zone=%s",
                        event["confidence"],
                        event["zone"],
                    )
                    # Auto-clear after a short delay (simulates detection end)
                    sensor.clear()

            time.sleep(TICK_INTERVAL)

    except Exception:
        logger.exception("Sensor error")
    finally:
        mqtt_client.disconnect()
        logger.info("Sensor %s shut down", config.sensor_id)


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    config = build_config(args)
    run(config)


if __name__ == "__main__":
    main()
