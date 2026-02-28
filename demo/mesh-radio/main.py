#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo mesh radio node entry point.

Simulates a Meshtastic or MeshCore LoRa mesh radio node that
publishes position and text messages via MQTT.

Usage:
    python main.py --node-id "!aabbccdd" --name "Hilltop Node" \
        --protocol meshtastic --lat 37.7749 --lng -122.4194 \
        --mqtt-host localhost --mqtt-port 1883 --site home
"""

import argparse
import logging
import signal
import time

from config import MeshRadioConfig
from mqtt_client import MeshMQTTClient
from node import MeshNode

logger = logging.getLogger(__name__)

TICK_INTERVAL = 0.1  # 10 Hz tick loop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Demo mesh radio node -- publishes position and text via MQTT",
    )
    parser.add_argument("--node-id", default="!aabbccdd", help="Node ID (hex with ! prefix)")
    parser.add_argument("--name", default="Demo Node", help="Long node name")
    parser.add_argument("--short-name", default="", help="Short name (auto-generated if empty)")
    parser.add_argument(
        "--protocol",
        default="meshtastic",
        choices=["meshtastic", "meshcore"],
        help="Mesh protocol",
    )
    parser.add_argument("--lat", type=float, default=0.0, help="Latitude")
    parser.add_argument("--lng", type=float, default=0.0, help="Longitude")
    parser.add_argument("--alt", type=float, default=0.0, help="Altitude in meters")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--site", default="home", help="Site ID for MQTT topic prefix")
    parser.add_argument("--hardware", default="heltec_v3", help="Hardware type")
    parser.add_argument(
        "--movement",
        default="stationary",
        choices=["stationary", "random_walk", "waypoint"],
        help="Movement pattern",
    )
    parser.add_argument("--position-interval", type=float, default=15.0,
                        help="Position broadcast interval (seconds)")
    parser.add_argument("--telemetry-interval", type=float, default=60.0,
                        help="Telemetry broadcast interval (seconds)")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    # Legacy CLI compat: --position-x / --position-y map to lat/lng
    parser.add_argument("--position-x", type=float, default=None,
                        help="Alias for --lat (legacy compat)")
    parser.add_argument("--position-y", type=float, default=None,
                        help="Alias for --lng (legacy compat)")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> MeshRadioConfig:
    lat = args.lat
    lng = args.lng
    if args.position_x is not None:
        lat = args.position_x
    if args.position_y is not None:
        lng = args.position_y

    return MeshRadioConfig(
        node_id=args.node_id,
        long_name=args.name,
        short_name=args.short_name,
        protocol=args.protocol,
        lat=lat,
        lng=lng,
        alt=args.alt,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        site=args.site,
        hardware=args.hardware,
        movement=args.movement,
        position_interval=args.position_interval,
        telemetry_interval=args.telemetry_interval,
    )


def run(config: MeshRadioConfig) -> None:
    """Main mesh node loop."""
    node = MeshNode(
        node_id=config.node_id,
        long_name=config.long_name,
        short_name=config.short_name if config.short_name else "",
        protocol=config.protocol,
        lat=config.lat,
        lng=config.lng,
        alt=config.alt,
        hardware=config.hardware,
        movement=config.movement,
    )

    mqtt_client = MeshMQTTClient(config)

    running = True

    def handle_command(cmd: dict) -> None:
        command = cmd.get("command", "")
        if command == "send_text":
            text = cmd.get("text", "")
            to = cmd.get("to", "^all")
            msg = node.create_text_message(text, to=to)
            mqtt_client.publish_text(msg)
            logger.info("Sent text to %s: %s", to, text)
        elif command == "set_channel":
            channel = cmd.get("channel", 0)
            node.set_channel(channel)
            logger.info("Channel set to %d", channel)
        elif command == "reboot":
            node.reboot()
            logger.info("Node rebooted")
            mqtt_client.publish_status(node.status_payload("online"))
        else:
            logger.warning("Unknown command: %s", command)

    def handle_text(msg_data: dict) -> None:
        node.record_rx()
        logger.info(
            "Received text from %s: %s",
            msg_data.get("from", "?"),
            msg_data.get("text", ""),
        )

    mqtt_client.on_command = handle_command
    mqtt_client.on_text = handle_text

    def shutdown(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        mqtt_client.connect()
        mqtt_client.subscribe_commands()
        mqtt_client.publish_status(node.status_payload("online"))
        mqtt_client.publish_position(node.position_payload())

        logger.info(
            "Mesh node %s (%s) running -- protocol=%s lat=%.6f lng=%.6f",
            config.node_id,
            config.long_name,
            config.protocol,
            config.lat,
            config.lng,
        )

        last_tick = time.monotonic()
        last_position = time.monotonic()
        last_telemetry = time.monotonic()

        while running:
            now = time.monotonic()
            dt = now - last_tick
            last_tick = now

            node.tick(dt)

            # Periodic position broadcast
            if now - last_position >= config.position_interval:
                mqtt_client.publish_position(node.position_payload())
                node.record_tx()
                last_position = now

            # Periodic telemetry broadcast
            if now - last_telemetry >= config.telemetry_interval:
                mqtt_client.publish_telemetry(node.telemetry_payload())
                node.record_tx()
                last_telemetry = now

            time.sleep(TICK_INTERVAL)

    except Exception:
        logger.exception("Mesh node error")
    finally:
        mqtt_client.disconnect()
        logger.info("Mesh node %s shut down", config.node_id)


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
