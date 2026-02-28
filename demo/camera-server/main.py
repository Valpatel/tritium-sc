#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo Camera Server — standalone process that simulates an IP camera.

Produces MJPEG video over HTTP, publishes YOLO-style detections via MQTT,
and responds to camera commands.

Usage:
  python main.py --camera-id demo-cam-01 --port 8081 \\
      --mqtt-host localhost --mqtt-port 1883 --site home \\
      --fps 10 --width 640 --height 480 --mode procedural
"""
import argparse
import logging
import signal
import sys
import threading
import time

from config import CameraConfig
from camera import FrameGenerator
from detector import DetectionGenerator
from mqtt_publisher import MQTTPublisher
from mjpeg_server import MJPEGServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("demo-camera")


def parse_args() -> CameraConfig:
    """Parse CLI arguments into CameraConfig."""
    parser = argparse.ArgumentParser(
        description="Demo Camera Server -- simulates an IP camera with MJPEG + MQTT",
    )
    parser.add_argument("--camera-id", default="demo-cam-01",
                        help="Unique camera identifier (default: demo-cam-01)")
    parser.add_argument("--port", type=int, default=8081,
                        help="HTTP server port (default: 8081)")
    parser.add_argument("--mqtt-host", default="localhost",
                        help="MQTT broker hostname (default: localhost)")
    parser.add_argument("--mqtt-port", type=int, default=1883,
                        help="MQTT broker port (default: 1883)")
    parser.add_argument("--site", default="home",
                        help="Site identifier for MQTT topics (default: home)")
    parser.add_argument("--fps", type=int, default=10,
                        help="Target frames per second (default: 10)")
    parser.add_argument("--width", type=int, default=640,
                        help="Frame width in pixels (default: 640)")
    parser.add_argument("--height", type=int, default=480,
                        help="Frame height in pixels (default: 480)")
    parser.add_argument("--mode", default="procedural",
                        choices=["procedural", "noise", "video"],
                        help="Frame generation mode (default: procedural)")
    parser.add_argument("--file", default="",
                        help="Video file path (for --mode video)")

    args = parser.parse_args()

    return CameraConfig(
        camera_id=args.camera_id,
        port=args.port,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        site=args.site,
        fps=args.fps,
        width=args.width,
        height=args.height,
        mode=args.mode,
        video_file=args.file,
    )


class DemoCameraServer:
    """Orchestrates frame generation, MJPEG serving, detection, and MQTT."""

    def __init__(self, config: CameraConfig):
        self.config = config
        self._running = False

        # Frame generator
        self.frame_gen = FrameGenerator(
            mode=config.mode,
            width=config.width,
            height=config.height,
            video_file=config.video_file if config.video_file else None,
        )

        # Detection generator
        self.detector = DetectionGenerator(
            camera_id=config.camera_id,
            detection_rate=0.3,
        )

        # MQTT publisher
        self.mqtt = MQTTPublisher(
            camera_id=config.camera_id,
            mqtt_host=config.mqtt_host,
            mqtt_port=config.mqtt_port,
            site=config.site,
        )
        self.mqtt.on_command = self._handle_command

        # MJPEG HTTP server
        self.http_server = MJPEGServer(
            frame_generator=self.frame_gen,
            port=config.port,
            camera_id=config.camera_id,
            fps=config.fps,
        )

    def start(self):
        """Start all services."""
        self._running = True

        log.info(
            "Starting demo camera: id=%s port=%d mode=%s %dx%d@%dfps",
            self.config.camera_id,
            self.config.port,
            self.config.mode,
            self.config.width,
            self.config.height,
            self.config.fps,
        )

        # Connect MQTT (non-blocking)
        self.mqtt.connect()
        self.mqtt.publish_status("online")

        # Start MJPEG server in background thread
        http_thread = threading.Thread(
            target=self.http_server.serve_forever,
            daemon=True,
        )
        http_thread.start()
        log.info("MJPEG server listening on http://0.0.0.0:%d", self.config.port)

        # Detection publishing loop (main thread)
        frame_interval = 1.0 / max(1, self.config.fps)
        try:
            while self._running:
                # Generate detection for current frame
                detection = self.detector.generate(
                    frame_id=self.frame_gen.frame_count,
                )
                if detection["boxes"]:
                    self.mqtt.publish_detection(detection)

                time.sleep(frame_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        """Stop all services."""
        self._running = False
        log.info("Shutting down demo camera %s", self.config.camera_id)
        self.mqtt.disconnect()
        self.http_server.shutdown()

    def _handle_command(self, payload: dict):
        """Handle incoming MQTT commands."""
        cmd = payload.get("command", "")
        log.info("Command received: %s", cmd)

        if cmd == "camera_off":
            log.info("Camera OFF -- stopping frame generation")
            self._running = False
        elif cmd == "camera_on":
            log.info("Camera ON")
        elif cmd == "set_fps":
            new_fps = payload.get("fps", self.config.fps)
            log.info("Setting FPS to %d", new_fps)
            self.config.fps = new_fps
        else:
            log.warning("Unknown command: %s", cmd)


def main():
    config = parse_args()

    server = DemoCameraServer(config)

    # Handle SIGTERM/SIGINT gracefully
    def signal_handler(sig, frame):
        log.info("Signal %d received, shutting down", sig)
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    server.start()


if __name__ == "__main__":
    main()
