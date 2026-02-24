"""TAKBridge — bridges TAK server to internal EventBus + TargetTracker.

Follows the MQTTBridge/MeshtasticBridge pattern: EventBus subscriber that
translates between TRITIUM's internal event model and an external protocol.

Architecture:
    - pytak runs in its own asyncio event loop in a daemon thread
    - A publish thread reads TargetTracker every N seconds and queues CoT XML
    - Thread-to-async: asyncio.run_coroutine_threadsafe() to put into tx_queue
    - Async-to-thread: receiver calls EventBus.publish() directly (thread-safe)

Graceful degradation:
    - pytak not installed -> warning, bridge disabled
    - TAK server unreachable -> warning, connected=False, publish loop pauses
    - Malformed CoT -> logged, skipped
    - Queue full (500) -> oldest dropped
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .cot import (
    cot_xml_to_emergency,
    cot_xml_to_geochat,
    cot_xml_to_sensor_reading,
    cot_xml_to_spot_report,
    cot_xml_to_target,
    cot_xml_to_tasking,
    cot_xml_to_video_feed,
    emergency_to_cot,
    geochat_to_cot_xml,
    make_sa_cot,
    sensor_reading_to_cot,
    spot_report_to_cot,
    target_to_cot_xml,
    tasking_to_cot,
    video_feed_to_cot,
)

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.tactical.target_tracker import TargetTracker

logger = logging.getLogger("amy.tak")

# Maximum messages in the outbound queue before oldest are dropped
_TX_QUEUE_MAX = 500


class TAKBridge:
    """Bridges TAK server <-> internal EventBus via CoT XML over pytak.

    Outbound: TRITIUM targets -> CoT XML -> TAK Server -> ATAK/WinTAK/WebTAK
    Inbound:  ATAK phone users -> TAK Server -> CoT XML -> TargetTracker + EventBus
    """

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker,
        cot_url: str = "tcp://localhost:8088",
        callsign: str = "TRITIUM-SC",
        team: str = "Cyan",
        role: str = "HQ",
        publish_interval: float = 5.0,
        stale_seconds: int = 120,
        tls_client_cert: str = "",
        tls_client_key: str = "",
        tls_ca_cert: str = "",
        sensorium=None,
    ) -> None:
        self._event_bus = event_bus
        self._tracker = target_tracker
        self._cot_url = cot_url
        self._callsign = callsign
        self._team = team
        self._role = role
        self._publish_interval = publish_interval
        self._stale_seconds = stale_seconds
        self._tls_client_cert = tls_client_cert
        self._tls_client_key = tls_client_key
        self._tls_ca_cert = tls_ca_cert
        self._sensorium = sensorium

        self._running = False
        self._connected = False
        self._lock = threading.Lock()

        # Outbound queue: CoT XML strings to send
        self._tx_queue: queue.Queue = queue.Queue(maxsize=_TX_QUEUE_MAX)

        # Reconnect backoff (seconds)
        self._reconnect_delay: float = 2.0

        # Stats
        self._messages_sent: int = 0
        self._messages_received: int = 0
        self._last_error: str = ""

        # Discovered TAK clients: uid -> {callsign, lat, lng, last_seen, ...}
        self._clients: dict[str, dict] = {}

        # GeoChat message history (in-memory ring buffer)
        self._chat_history: list[dict] = []
        self._chat_history_max = 100

        # asyncio loop for pytak (set during start)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pytak_thread: threading.Thread | None = None
        self._publish_thread: threading.Thread | None = None

    # -----------------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def running(self) -> bool:
        return self._running

    @property
    def callsign(self) -> str:
        return self._callsign

    @property
    def clients(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._clients)

    @property
    def stats(self) -> dict:
        return {
            "connected": self._connected,
            "cot_url": self._cot_url,
            "callsign": self._callsign,
            "team": self._team,
            "role": self._role,
            "messages_sent": self._messages_sent,
            "messages_received": self._messages_received,
            "clients": len(self._clients),
            "last_error": self._last_error,
            "tx_queue_size": self._tx_queue.qsize(),
        }

    @property
    def chat_history(self) -> list[dict]:
        with self._lock:
            return list(self._chat_history)

    # -----------------------------------------------------------------------
    # GeoChat
    # -----------------------------------------------------------------------

    def send_geochat(
        self,
        message: str,
        to_callsign: str = "All Chat Rooms",
        to_uid: str = "All Chat Rooms",
    ) -> None:
        """Send a GeoChat message to the TAK network."""
        from engine.tactical.geo import get_reference

        lat, lng, alt = 0.0, 0.0, 0.0
        try:
            ref = get_reference()
            if ref.initialized:
                lat, lng, alt = ref.lat, ref.lng, ref.alt
        except Exception:
            pass

        xml = geochat_to_cot_xml(
            sender_uid=self._callsign,
            sender_callsign=self._callsign,
            message=message,
            lat=lat,
            lng=lng,
            alt=alt,
            to_callsign=to_callsign,
            to_uid=to_uid,
        )
        self.send_cot(xml)

        now = datetime.now(timezone.utc).isoformat()
        record = {
            "sender_callsign": self._callsign,
            "message": message,
            "direction": "outbound",
            "to_callsign": to_callsign,
            "timestamp": now,
        }
        with self._lock:
            self._chat_history.append(record)
            if len(self._chat_history) > self._chat_history_max:
                self._chat_history = self._chat_history[-self._chat_history_max:]

        self._event_bus.publish("tak_geochat", {
            "sender_callsign": self._callsign,
            "message": message,
            "direction": "outbound",
            "to_callsign": to_callsign,
            "timestamp": now,
        })

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return recent chat + event history."""
        with self._lock:
            return list(self._chat_history[-limit:])

    # -----------------------------------------------------------------------
    # Outbound filter
    # -----------------------------------------------------------------------

    def _should_publish(self, target_dict: dict) -> bool:
        """Return True if this target should be published to TAK.

        Targets that originated FROM TAK (prefixed 'tak_') are skipped
        to prevent echo loops.
        """
        tid = target_dict.get("target_id", "")
        return not tid.startswith("tak_")

    # -----------------------------------------------------------------------
    # Send raw CoT
    # -----------------------------------------------------------------------

    def send_cot(self, xml_string: str) -> None:
        """Queue a raw CoT XML string for transmission."""
        try:
            self._tx_queue.put_nowait(xml_string)
        except queue.Full:
            # Drop oldest to make room
            try:
                self._tx_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._tx_queue.put_nowait(xml_string)
            except queue.Full:
                pass

    # -----------------------------------------------------------------------
    # Inbound handling
    # -----------------------------------------------------------------------

    def _handle_inbound(self, xml_string: str) -> None:
        """Process an inbound CoT XML message from the TAK server.

        Routes by CoT type prefix:
        - b-t-f      -> GeoChat
        - t-x-t      -> Tasking
        - b-a-o      -> Emergency
        - b-s-r      -> Sensor reading
        - b-i-v      -> Video feed
        - b-m-p-s-m  -> Spot report
        - a-*        -> Atom position (target tracker)
        """
        try:
            root = ET.fromstring(xml_string)
        except ET.ParseError:
            return

        cot_type = root.get("type", "")

        # GeoChat
        if cot_type == "b-t-f":
            geochat = cot_xml_to_geochat(xml_string)
            if geochat is not None:
                self._handle_geochat(geochat)
            return

        # Tasking
        if cot_type.startswith("t-x-t"):
            tasking = cot_xml_to_tasking(xml_string)
            if tasking is not None:
                self._handle_tasking(tasking)
            return

        # Emergency
        if cot_type.startswith("b-a-o"):
            emergency = cot_xml_to_emergency(xml_string)
            if emergency is not None:
                self._handle_emergency(emergency)
            return

        # Sensor reading
        if cot_type.startswith("b-s-r"):
            sensor = cot_xml_to_sensor_reading(xml_string)
            if sensor is not None:
                self._handle_sensor_reading(sensor)
            return

        # Video feed
        if cot_type == "b-i-v":
            video = cot_xml_to_video_feed(xml_string)
            if video is not None:
                self._handle_video_feed(video)
            return

        # Spot report
        if cot_type == "b-m-p-s-m":
            spotrep = cot_xml_to_spot_report(xml_string)
            if spotrep is not None:
                self._handle_spot_report(spotrep)
            return

        # Default: atom position
        target = cot_xml_to_target(xml_string)
        if target is None:
            return

        self._messages_received += 1
        original_id = target["target_id"]

        # Prefix with tak_ to distinguish from TRITIUM-native targets
        target["target_id"] = f"tak_{original_id}"
        target["source"] = "tak"

        # Track as a TAK client
        with self._lock:
            self._clients[original_id] = {
                "callsign": target.get("name", original_id),
                "uid": original_id,
                "lat": target.get("lat", 0.0),
                "lng": target.get("lng", 0.0),
                "alt": target.get("alt", 0.0),
                "alliance": target.get("alliance", "unknown"),
                "asset_type": target.get("asset_type", "person"),
                "speed": target.get("speed", 0.0),
                "heading": target.get("heading", 0.0),
                "last_seen": time.time(),
            }

        # Inject into TargetTracker
        self._tracker.update_from_simulation(target)

        # Publish event for WebSocket consumers
        self._event_bus.publish("tak_client_update", {
            "uid": original_id,
            "target_id": target["target_id"],
            "callsign": target.get("name", original_id),
            "alliance": target.get("alliance", "unknown"),
            "lat": target.get("lat", 0.0),
            "lng": target.get("lng", 0.0),
        })

        callsign = target.get("name", original_id)
        lat = target.get("lat", 0.0)
        lng = target.get("lng", 0.0)

        # Hostile marker -> escalation wiring
        if target.get("alliance") == "hostile":
            self._event_bus.publish("tak_threat_marker", {
                "target_id": target["target_id"],
                "callsign": callsign,
                "lat": lat,
                "lng": lng,
                "source": "tak",
            })
            if self._sensorium is not None:
                self._sensorium.push(
                    "tak_threat",
                    f"TAK hostile marker: {callsign} at ({lat:.4f}, {lng:.4f})",
                    importance=0.9,
                )
        else:
            # Position update -> sensorium
            if self._sensorium is not None:
                self._sensorium.push(
                    "tak_position",
                    f"TAK user {callsign} at ({lat:.4f}, {lng:.4f})",
                    importance=0.3,
                )

    def _handle_geochat(self, geochat: dict) -> None:
        """Process a parsed GeoChat message."""
        self._messages_received += 1

        record = {
            "sender_callsign": geochat.get("sender_callsign", ""),
            "sender_uid": geochat.get("sender_uid", ""),
            "message": geochat.get("message", ""),
            "direction": "inbound",
            "lat": geochat.get("lat", 0.0),
            "lng": geochat.get("lng", 0.0),
            "chatroom": geochat.get("chatroom", ""),
            "timestamp": geochat.get("timestamp", ""),
        }

        with self._lock:
            self._chat_history.append(record)
            if len(self._chat_history) > self._chat_history_max:
                self._chat_history = self._chat_history[-self._chat_history_max:]

        self._event_bus.publish("tak_geochat", {
            "sender_callsign": geochat.get("sender_callsign", ""),
            "sender_uid": geochat.get("sender_uid", ""),
            "message": geochat.get("message", ""),
            "direction": "inbound",
            "lat": geochat.get("lat", 0.0),
            "lng": geochat.get("lng", 0.0),
        })

        # Push to sensorium
        if self._sensorium is not None:
            sender = geochat.get("sender_callsign", "unknown")
            msg = geochat.get("message", "")
            self._sensorium.push(
                "tak_chat",
                f"TAK chat from {sender}: {msg[:80]}",
                importance=0.5,
            )

        logger.debug(
            f"GeoChat from {geochat.get('sender_callsign')}: "
            f"{geochat.get('message', '')[:60]}"
        )

    def _handle_tasking(self, tasking: dict) -> None:
        """Process inbound tasking from TAK."""
        self._messages_received += 1
        self._event_bus.publish("tak_tasking", tasking)

    def _handle_emergency(self, emergency: dict) -> None:
        """Process inbound emergency from TAK."""
        self._messages_received += 1
        self._event_bus.publish("tak_emergency", emergency)
        if self._sensorium:
            self._sensorium.push(
                "tak_emergency",
                f"EMERGENCY from {emergency.get('callsign', 'unknown')}: {emergency.get('remarks', '')}",
                importance=1.0,
            )

    def _handle_sensor_reading(self, sensor: dict) -> None:
        """Process inbound sensor reading from TAK."""
        self._messages_received += 1
        self._event_bus.publish("tak_sensor", sensor)
        if self._sensorium:
            self._sensorium.push(
                "tak_sensor",
                f"Sensor {sensor.get('sensor_id', 'unknown')}: {sensor.get('detection_type', '')} "
                f"({sensor.get('sensor_type', '')}, confidence={sensor.get('confidence', 0.0):.2f})",
                importance=0.6,
            )

    def _handle_video_feed(self, video: dict) -> None:
        """Process inbound video feed advertisement from TAK."""
        self._messages_received += 1
        self._event_bus.publish("tak_video_feed", video)
        if self._sensorium:
            self._sensorium.push(
                "tak_video_feed",
                f"Video feed advertised: {video.get('callsign', video.get('feed_id', 'unknown'))}",
                importance=0.3,
            )

    def _handle_spot_report(self, spotrep: dict) -> None:
        """Process inbound spot report from TAK."""
        self._messages_received += 1
        self._event_bus.publish("tak_spot_report", spotrep)
        if self._sensorium:
            self._sensorium.push(
                "tak_spot_report",
                f"SPOTREP from {spotrep.get('callsign', 'unknown')}: {spotrep.get('description', '')[:80]}",
                importance=0.7,
            )

    # -----------------------------------------------------------------------
    # Outbound: extended event types
    # -----------------------------------------------------------------------

    def send_tasking(
        self,
        task_id: str,
        assignee_uid: str,
        task_type: str,
        lat: float = 0.0,
        lng: float = 0.0,
        remarks: str = "",
    ) -> None:
        """Send a tasking CoT message to the TAK network."""
        xml = tasking_to_cot(task_id, assignee_uid, task_type, lat, lng, remarks)
        self.send_cot(xml)

    def send_emergency(self, emergency_type: str, remarks: str = "") -> None:
        """Send an emergency CoT message to the TAK network."""
        from engine.tactical.geo import get_reference

        lat, lng, alt = 0.0, 0.0, 0.0
        try:
            ref = get_reference()
            if ref.initialized:
                lat, lng, alt = ref.lat, ref.lng, ref.alt
        except Exception:
            pass

        xml = emergency_to_cot(self._callsign, emergency_type, lat, lng, alt, remarks)
        self.send_cot(xml)

    def send_video_feed(self, feed_id: str, feed_url: str) -> None:
        """Send a video feed advertisement to the TAK network."""
        from engine.tactical.geo import get_reference

        lat, lng, alt = 0.0, 0.0, 0.0
        try:
            ref = get_reference()
            if ref.initialized:
                lat, lng, alt = ref.lat, ref.lng, ref.alt
        except Exception:
            pass

        xml = video_feed_to_cot(feed_id, feed_url, lat, lng, alt)
        self.send_cot(xml)

    def send_sensor_reading(
        self,
        sensor_id: str,
        lat: float = 0.0,
        lng: float = 0.0,
        alt: float = 16.0,
        sensor_type: str = "motion",
        detection_type: str = "human",
        confidence: float = 0.8,
    ) -> None:
        """Send a sensor reading CoT message to the TAK network."""
        xml = sensor_reading_to_cot(
            sensor_id, lat, lng, alt, sensor_type, detection_type, confidence,
        )
        self.send_cot(xml)

    def send_spot_report(
        self,
        callsign: str,
        lat: float = 0.0,
        lng: float = 0.0,
        alt: float = 16.0,
        category: str = "hostile",
        description: str = "",
    ) -> None:
        """Send a spot report CoT message to the TAK network."""
        xml = spot_report_to_cot(
            callsign, lat, lng, alt, category, description,
        )
        self.send_cot(xml)

    # -----------------------------------------------------------------------
    # Publish loop (runs in daemon thread)
    # -----------------------------------------------------------------------

    def _cleanup_stale_clients(self) -> None:
        """Prune clients not seen for 5x stale_seconds."""
        cutoff = time.time() - (self._stale_seconds * 5)
        with self._lock:
            stale = [uid for uid, info in self._clients.items()
                     if info.get("last_seen", 0) < cutoff]
            for uid in stale:
                del self._clients[uid]
                logger.debug(f"Pruned stale TAK client: {uid}")

    def _publish_loop(self) -> None:
        """Periodically read targets and queue CoT XML for transmission."""
        logger.info("TAK publish loop started")
        cleanup_counter = 0
        while self._running:
            try:
                if not self._connected:
                    time.sleep(self._reconnect_delay)
                    # Exponential backoff: double up to 30s max
                    self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)
                    continue

                # Connected — reset backoff
                self._reconnect_delay = 2.0

                targets = self._tracker.get_all()
                for target in targets:
                    d = target.to_dict()
                    if self._should_publish(d):
                        xml = target_to_cot_xml(d, stale_seconds=self._stale_seconds)
                        self.send_cot(xml)
                        self._messages_sent += 1

                # Also send our own SA position
                from engine.tactical.geo import get_reference
                ref = get_reference()
                if ref.initialized:
                    sa = make_sa_cot(
                        self._callsign, ref.lat, ref.lng, ref.alt,
                        self._team, self._role, self._stale_seconds,
                    )
                    self.send_cot(sa)

                # Periodic stale client cleanup
                cleanup_counter += 1
                if cleanup_counter >= 6:  # every ~6 publish intervals
                    cleanup_counter = 0
                    self._cleanup_stale_clients()

            except Exception as e:
                logger.debug(f"TAK publish loop error: {e}")
                self._last_error = str(e)

            time.sleep(self._publish_interval)

        logger.info("TAK publish loop stopped")

    # -----------------------------------------------------------------------
    # pytak asyncio loop (runs in daemon thread)
    # -----------------------------------------------------------------------

    def _run_pytak(self) -> None:
        """Run the pytak event loop in a dedicated thread."""
        try:
            import pytak
        except ImportError:
            logger.warning("pytak not installed -- TAK bridge disabled")
            self._last_error = "pytak not installed"
            self._running = False
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._pytak_main(pytak))
        except Exception as e:
            logger.error(f"pytak loop error: {e}")
            self._last_error = str(e)
        finally:
            self._connected = False
            self._loop.close()
            self._loop = None

    async def _pytak_main(self, pytak_module) -> None:
        """Main pytak coroutine — connects, sends, receives."""
        config = {
            "COT_URL": self._cot_url,
            "CALLSIGN": self._callsign,
        }
        if self._tls_client_cert:
            config["PYTAK_TLS_CLIENT_CERT"] = self._tls_client_cert
        if self._tls_client_key:
            config["PYTAK_TLS_CLIENT_KEY"] = self._tls_client_key
        if self._tls_ca_cert:
            config["PYTAK_TLS_CLIENT_CAFILE"] = self._tls_ca_cert

        # Create pytak CLITool
        clitool = pytak_module.CLITool(config)
        await clitool.setup()

        # Wire up sender and receiver workers
        sender = _TritiumCoTSender(clitool.tx_queue, self._tx_queue, self)
        receiver = _TritiumCoTReceiver(clitool.rx_queue, self)

        clitool.add_task(sender)
        clitool.add_task(receiver)

        self._connected = True
        self._event_bus.publish("tak_connected", {
            "cot_url": self._cot_url,
            "callsign": self._callsign,
        })
        logger.info(f"TAK connected to {self._cot_url}")

        try:
            await clitool.run()
        finally:
            self._connected = False
            self._event_bus.publish("tak_disconnected", {
                "cot_url": self._cot_url,
            })

    # -----------------------------------------------------------------------
    # Start / Stop
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Start the TAK bridge (pytak loop + publish loop)."""
        if self._running:
            return

        # Check pytak availability at import time
        try:
            import pytak  # noqa: F401
        except ImportError:
            logger.warning("pytak not installed -- TAK bridge disabled")
            self._last_error = "pytak not installed"
            return

        self._running = True

        # pytak asyncio thread
        self._pytak_thread = threading.Thread(
            target=self._run_pytak, daemon=True, name="tak-pytak"
        )
        self._pytak_thread.start()

        # Publish loop thread
        self._publish_thread = threading.Thread(
            target=self._publish_loop, daemon=True, name="tak-publish"
        )
        self._publish_thread.start()

        logger.info(f"TAK bridge started ({self._cot_url})")

    def stop(self) -> None:
        """Stop the TAK bridge."""
        self._running = False
        self._connected = False

        # Signal the asyncio loop to stop
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        # Wait for threads
        if self._pytak_thread is not None and self._pytak_thread.is_alive():
            self._pytak_thread.join(timeout=5.0)
        if self._publish_thread is not None and self._publish_thread.is_alive():
            self._publish_thread.join(timeout=5.0)

        logger.info("TAK bridge stopped")


# ---------------------------------------------------------------------------
# pytak worker classes
# ---------------------------------------------------------------------------

class _TritiumCoTSender:
    """Reads CoT XML from bridge's tx_queue and feeds pytak's tx_queue."""

    def __init__(self, pytak_tx_queue, bridge_tx_queue: queue.Queue, bridge: TAKBridge):
        self._pytak_tx = pytak_tx_queue
        self._bridge_tx = bridge_tx_queue
        self._bridge = bridge

    async def run(self, number_of_iterations=-1):
        """pytak worker protocol: called by CLITool.run()."""
        while self._bridge.running:
            try:
                # Non-blocking check of our thread-safe queue
                try:
                    xml_bytes = self._bridge_tx.get_nowait()
                    if isinstance(xml_bytes, str):
                        xml_bytes = xml_bytes.encode("utf-8")
                    await self._pytak_tx.put(xml_bytes)
                except queue.Empty:
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.debug(f"TAK sender error: {e}")
                await asyncio.sleep(1.0)


class _TritiumCoTReceiver:
    """Reads CoT XML from pytak's rx_queue and calls bridge._handle_inbound()."""

    def __init__(self, pytak_rx_queue, bridge: TAKBridge):
        self._pytak_rx = pytak_rx_queue
        self._bridge = bridge

    async def run(self, number_of_iterations=-1):
        """pytak worker protocol: called by CLITool.run()."""
        while self._bridge.running:
            try:
                data = await asyncio.wait_for(self._pytak_rx.get(), timeout=1.0)
                if data:
                    xml_str = data.decode("utf-8") if isinstance(data, bytes) else data
                    self._bridge._handle_inbound(xml_str)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.debug(f"TAK receiver error: {e}")
                await asyncio.sleep(1.0)
