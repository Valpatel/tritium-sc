"""MQTTBridge — bridges MQTT broker to internal EventBus + TargetTracker.

External devices (cameras running YOLO, robots, sensors) publish to MQTT.
This bridge subscribes, injects events into the internal EventBus and
TargetTracker.  Amy's actions (dispatch, alert, speech) are published
back to MQTT so external devices can subscribe.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from comms.event_bus import EventBus
    from tracking.tracker import TargetTracker

logger = logging.getLogger("amy.mqtt")


class MQTTBridge:
    """Bridges MQTT broker <-> internal EventBus.

    MQTT Topic Hierarchy:
        tritium/{site}/cameras/{cam_id}/detections   <- Camera publishes YOLO boxes
        tritium/{site}/cameras/{cam_id}/status        <- Camera online/offline
        tritium/{site}/robots/{robot_id}/telemetry    <- Robot position/battery
        tritium/{site}/robots/{robot_id}/command       -> Robot dispatch/patrol/recall
        tritium/{site}/robots/{robot_id}/command/ack  <- Robot acknowledges command
        tritium/{site}/robots/{robot_id}/status       <- Robot state changes
        tritium/{site}/sensors/{sensor_id}/events     <- Motion/sound detected
        tritium/{site}/sensors/{sensor_id}/status     <- Sensor online/offline
        tritium/{site}/amy/alerts                     <- Amy threat alerts
        tritium/{site}/amy/dispatch                   <- Amy dispatch orders
        tritium/{site}/amy/speech                     <- Amy TTS text
        tritium/{site}/amy/thoughts                   <- Amy thinking stream
        tritium/{site}/targets/update                 <- Unified target updates
        tritium/{site}/escalation/change              <- Threat level changes
    """

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker,
        site_id: str = "home",
        broker_host: str = "localhost",
        broker_port: int = 1883,
        username: str = "",
        password: str = "",
    ) -> None:
        self._event_bus = event_bus
        self._tracker = target_tracker
        self._site = site_id
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._username = username
        self._password = password
        self._client = None
        self._connected = False
        self._running = False
        self._lock = threading.Lock()
        # Stats
        self._messages_received: int = 0
        self._messages_published: int = 0
        self._last_error: str = ""
        # Device liveness: device_id -> monotonic timestamp of last message
        self._device_last_seen: dict[str, float] = {}
        # Command ACK tracking: command_timestamp -> ack payload
        self._pending_commands: dict[str, dict] = {}
        self._command_acks: dict[str, dict] = {}
        # Stale device threshold (seconds). If no message for this long,
        # the device is considered stale (hung process, not disconnected).
        self.device_stale_timeout: float = 30.0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict:
        return {
            "connected": self._connected,
            "broker": f"{self._broker_host}:{self._broker_port}",
            "site_id": self._site,
            "messages_received": self._messages_received,
            "messages_published": self._messages_published,
            "last_error": self._last_error,
            "devices_seen": len(self._device_last_seen),
            "stale_devices": list(self.get_stale_devices()),
        }

    def get_stale_devices(self) -> list[str]:
        """Return device IDs that haven't published in > device_stale_timeout seconds.

        Covers the failure mode where a robot process hangs (still connected
        to the broker, so LWT does not fire) but stops publishing telemetry.
        """
        now = time.monotonic()
        threshold = self.device_stale_timeout
        return [
            did for did, ts in self._device_last_seen.items()
            if (now - ts) > threshold
        ]

    def get_command_ack(self, command_timestamp: str) -> dict | None:
        """Check if a command has been acknowledged by the robot.

        Returns the ACK payload if received, None if still pending.
        """
        return self._command_acks.get(command_timestamp)

    def start(self) -> None:
        """Connect to MQTT broker and start listening."""
        if self._running:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.warning("paho-mqtt not installed — MQTT bridge disabled")
            self._last_error = "paho-mqtt not installed"
            return

        self._running = True
        client_id = f"tritium-{self._site}-{int(time.time()) % 10000}"
        self._client = mqtt.Client(client_id=client_id)

        if self._username:
            self._client.username_pw_set(self._username, self._password)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        try:
            self._client.connect(self._broker_host, self._broker_port, keepalive=60)
            self._client.loop_start()
            logger.info(f"MQTT bridge connecting to {self._broker_host}:{self._broker_port}")
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            self._last_error = str(e)
            self._client = None
            self._running = False

    def stop(self) -> None:
        """Disconnect from MQTT broker."""
        self._running = False
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._connected = False
        logger.info("MQTT bridge stopped")

    # --- Connection callbacks ---

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            logger.info(f"MQTT connected to {self._broker_host}:{self._broker_port}")
            # Subscribe to all device topics
            # QoS 0: high-rate telemetry/detections (fire-and-forget)
            # QoS 1: status/events (at-least-once, important state changes)
            prefix = f"tritium/{self._site}"
            subscriptions = [
                (f"{prefix}/cameras/+/detections", 0),
                (f"{prefix}/cameras/+/status", 1),
                (f"{prefix}/robots/+/telemetry", 0),
                (f"{prefix}/robots/+/status", 1),
                (f"{prefix}/robots/+/command/ack", 1),
                (f"{prefix}/sensors/+/events", 1),
                (f"{prefix}/sensors/+/status", 1),
            ]
            client.subscribe(subscriptions)
            logger.info(f"MQTT subscribed to {len(subscriptions)} topic patterns")
            self._event_bus.publish("mqtt_connected", {"broker": self._broker_host})
        else:
            self._connected = False
            self._last_error = f"Connection refused (rc={rc})"
            logger.error(f"MQTT connection refused: rc={rc}")

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        if rc != 0:
            logger.warning(f"MQTT unexpected disconnect (rc={rc})")
            self._last_error = f"Unexpected disconnect (rc={rc})"
        self._event_bus.publish("mqtt_disconnected", {})

    # --- Message routing ---

    def _on_message(self, client, userdata, msg) -> None:
        """Route incoming MQTT messages to appropriate handlers."""
        self._messages_received += 1
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug(f"MQTT bad payload on {topic}: {e}")
            return

        # Parse topic: tritium/{site}/{category}/{device_id}/{action}[/{sub}]
        parts = topic.split("/")
        if len(parts) < 5:
            return

        category = parts[2]  # cameras, robots, sensors
        device_id = parts[3]
        action = parts[4]    # detections, telemetry, events, status, command
        sub_action = parts[5] if len(parts) > 5 else ""

        # Track device liveness (any message = device is alive)
        self._device_last_seen[device_id] = time.monotonic()

        try:
            if category == "cameras":
                if action == "detections":
                    self._on_camera_detection(device_id, payload)
                elif action == "status":
                    self._on_device_status("camera", device_id, payload)
            elif category == "robots":
                if action == "telemetry":
                    self._on_robot_telemetry(device_id, payload)
                elif action == "status":
                    self._on_device_status("robot", device_id, payload)
                elif action == "command" and sub_action == "ack":
                    self._on_command_ack(device_id, payload)
            elif category == "sensors":
                if action == "events":
                    self._on_sensor_event(device_id, payload)
                elif action == "status":
                    self._on_device_status("sensor", device_id, payload)
        except Exception as e:
            logger.debug(f"MQTT handler error for {topic}: {e}")

    # --- Inbound handlers ---

    def _on_camera_detection(self, cam_id: str, payload: dict) -> None:
        """Camera published YOLO detections -> inject into TargetTracker."""
        boxes = payload.get("boxes", [])
        for det in boxes:
            self._tracker.update_from_detection({
                "class_name": det.get("label", "unknown"),
                "confidence": det.get("confidence", 0.5),
                "center_x": det.get("center_x", 0.5),
                "center_y": det.get("center_y", 0.5),
                "source_camera": cam_id,
            })
        # Forward to EventBus for UI
        self._event_bus.publish("mqtt_camera_detection", {
            "camera_id": cam_id,
            "detection_count": len(boxes),
            "boxes": boxes,
        })

    def _on_robot_telemetry(self, robot_id: str, payload: dict) -> None:
        """Robot published position/battery -> update TargetTracker."""
        position = payload.get("position", {})
        self._tracker.update_from_simulation({
            "target_id": f"mqtt_{robot_id}",
            "name": payload.get("name", robot_id),
            "alliance": "friendly",
            "asset_type": payload.get("asset_type", "rover"),
            "position": position,
            "heading": payload.get("heading", 0),
            "speed": payload.get("speed", 0),
            "battery": payload.get("battery", 1.0),
            "status": payload.get("status", "active"),
        })
        self._event_bus.publish("mqtt_robot_telemetry", {
            **payload,
            "robot_id": robot_id,
        })

    def _on_sensor_event(self, sensor_id: str, payload: dict) -> None:
        """Sensor published event (motion, sound, etc)."""
        event_type = payload.get("event_type", "unknown")
        self._event_bus.publish("mqtt_sensor_event", {
            **payload,
            "sensor_id": sensor_id,
            "event_type": event_type,
        })

    def _on_device_status(self, category: str, device_id: str, payload: dict) -> None:
        """Device published status update (online/offline/battery)."""
        self._event_bus.publish("mqtt_device_status", {
            **payload,
            "category": category,
            "device_id": device_id,
        })

    def _on_command_ack(self, robot_id: str, payload: dict) -> None:
        """Robot acknowledged a command.

        ACK payload: {"command": "dispatch", "command_timestamp": "...", "status": "accepted"}
        Status values: "accepted" (will execute), "rejected" (cannot execute),
                       "completed" (finished executing).
        """
        cmd_ts = payload.get("command_timestamp", "")
        if cmd_ts:
            self._command_acks[cmd_ts] = {
                "robot_id": robot_id,
                "command": payload.get("command", ""),
                "status": payload.get("status", "accepted"),
                "timestamp": payload.get("timestamp", ""),
            }
            # Prune old acks (keep last 100)
            if len(self._command_acks) > 100:
                oldest = sorted(self._command_acks.keys())[:50]
                for k in oldest:
                    del self._command_acks[k]
        self._event_bus.publish("mqtt_command_ack", {
            **payload,
            "robot_id": robot_id,
        })
        logger.debug(f"Command ACK from {robot_id}: {payload.get('command', '?')} -> {payload.get('status', '?')}")

    # --- Outbound publishing ---

    def _publish(self, topic: str, payload: dict, qos: int = 0, retain: bool = False) -> None:
        """Publish a message to MQTT.

        Args:
            topic: MQTT topic string.
            payload: Dict to JSON-encode.
            qos: 0 = fire-and-forget (telemetry), 1 = at-least-once (commands/alerts).
            retain: If True, broker stores last message for new subscribers.
        """
        if not self._connected or self._client is None:
            return
        try:
            self._client.publish(
                topic,
                json.dumps(payload),
                qos=qos,
                retain=retain,
            )
            self._messages_published += 1
        except Exception as e:
            logger.debug(f"MQTT publish error: {e}")

    def publish_dispatch(self, robot_id: str, x: float, y: float) -> None:
        """Amy dispatches a robot -> publish command via MQTT."""
        ts = datetime.now(timezone.utc).isoformat()
        topic = f"tritium/{self._site}/robots/{robot_id}/command"
        self._publish(topic, {
            "command": "dispatch",
            "x": x,
            "y": y,
            "timestamp": ts,
        }, qos=1)
        # Track pending command for ACK correlation
        self._pending_commands[ts] = {
            "robot_id": robot_id,
            "command": "dispatch",
            "x": x,
            "y": y,
        }
        # Also publish to the dispatch topic for monitoring
        self._publish(f"tritium/{self._site}/amy/dispatch", {
            "robot_id": robot_id,
            "destination": {"x": x, "y": y},
            "timestamp": ts,
        })

    def publish_patrol(self, robot_id: str, waypoints: list[tuple[float, float]]) -> None:
        """Publish patrol command to a robot."""
        topic = f"tritium/{self._site}/robots/{robot_id}/command"
        self._publish(topic, {
            "command": "patrol",
            "waypoints": [{"x": wx, "y": wy} for wx, wy in waypoints],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, qos=1)

    def publish_recall(self, robot_id: str) -> None:
        """Publish recall command to a robot."""
        topic = f"tritium/{self._site}/robots/{robot_id}/command"
        self._publish(topic, {
            "command": "recall",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, qos=1)

    def publish_alert(self, alert_data: dict) -> None:
        """Publish Amy's alert to MQTT for speakers/displays."""
        self._publish(f"tritium/{self._site}/amy/alerts", {
            **alert_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, qos=1)

    def publish_speech(self, text: str) -> None:
        """Publish Amy's speech -> external speakers can subscribe."""
        self._publish(f"tritium/{self._site}/amy/speech", {
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def publish_thought(self, text: str) -> None:
        """Publish Amy's thought for monitoring."""
        self._publish(f"tritium/{self._site}/amy/thoughts", {
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def publish_target_update(self, target_data: dict) -> None:
        """Publish unified target update."""
        self._publish(f"tritium/{self._site}/targets/update", {
            **target_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def publish_escalation(self, escalation_data: dict) -> None:
        """Publish escalation change."""
        self._publish(f"tritium/{self._site}/escalation/change", {
            **escalation_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, qos=1, retain=True)
