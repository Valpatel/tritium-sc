# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""AcousticPlugin — ML sound classification + source localization.

Subscribes to audio events from edge devices (ESP32 I2S microphones,
IP camera audio channels, dedicated acoustic sensors). Classifies sounds
using MFCC-based KNN (when features available) or rule-based fallback.

Sound source localization: when 2+ edge nodes detect the same acoustic
event, triangulates position from time-of-arrival differences.

Classified events appear on the tactical map as expanding ring targets
and feed into the event timeline.

MQTT topics:
    IN:  tritium/{site}/audio/{device}/raw       — raw audio features
    IN:  tritium/{site}/audio/{device}/features   — MFCC feature vectors
    OUT: tritium/{site}/audio/{device}/event      — classified events
    OUT: tritium/{site}/acoustic/localization      — triangulated positions
"""

from __future__ import annotations

import logging
import math
import queue as queue_mod
import threading
import time
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface
from engine.audio.acoustic_classifier import (
    AcousticClassifier,
    AcousticEvent,
    AcousticEventType,
    AudioFeatures,
)

log = logging.getLogger("acoustic")

# How often to run the cleanup loop (seconds)
DEFAULT_POLL_INTERVAL = 2.0

# Stale timeout for acoustic targets in TargetTracker
ACOUSTIC_TARGET_TTL = 30.0

# Maximum event history for the plugin
MAX_EVENT_HISTORY = 500

# Maximum time window (seconds) to correlate events for localization
LOCALIZATION_WINDOW_S = 2.0

# Severity classification for alert routing
HIGH_SEVERITY_EVENTS = {
    AcousticEventType.GUNSHOT,
    AcousticEventType.EXPLOSION,
    AcousticEventType.GLASS_BREAK,
}
MEDIUM_SEVERITY_EVENTS = {
    AcousticEventType.SIREN,
    AcousticEventType.ALARM,
    AcousticEventType.VEHICLE,
}

# Severity colors for map rendering (CSS color values)
SEVERITY_COLORS = {
    "high": "#ff2a6d",
    "medium": "#fcee0a",
    "low": "#00f0ff",
}


class AcousticPlugin(PluginInterface):
    """Acoustic classification plugin with ML + source localization."""

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None

        self._classifier = AcousticClassifier(enable_ml=True)

        self._running = False
        self._poll_interval = DEFAULT_POLL_INTERVAL
        self._cleanup_thread: Optional[threading.Thread] = None
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None

        # Plugin-level event history (timeline data)
        self._event_history: list[dict] = []
        self._lock = threading.Lock()

        # Active acoustic targets (target_id -> expiry time)
        self._active_targets: dict[str, float] = {}

        # Sensor positions for localization (sensor_id -> (lat, lon))
        self._sensor_positions: dict[str, tuple[float, float]] = {}

        # Recent detections for cross-node correlation
        # Key: event_type, Value: list of (timestamp, sensor_id, lat, lon, confidence)
        self._recent_detections: dict[str, list[tuple[float, str, float, float, float]]] = {}

        # Localization results
        self._localization_history: list[dict] = []

        # TDoA observation buffer: event_type -> list of observations
        self._tdoa_buffer: dict[str, list[Any]] = {}
        self._tdoa_results: list[dict] = []
        self._tdoa_window_s = LOCALIZATION_WINDOW_S

        # Statistics
        self._stats = {
            "events_processed": 0,
            "events_classified": 0,
            "high_severity_count": 0,
            "targets_created": 0,
            "localizations": 0,
            "tdoa_localizations": 0,
            "tdoa_observations": 0,
            "ml_classifications": 0,
            "rule_classifications": 0,
        }

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.acoustic"

    @property
    def name(self) -> str:
        return "Acoustic Intelligence"

    @property
    def version(self) -> str:
        return "2.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "background", "localization"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        # Apply settings
        settings = ctx.settings or {}
        if "poll_interval" in settings:
            self._poll_interval = float(settings["poll_interval"])
        if "target_ttl" in settings:
            global ACOUSTIC_TARGET_TTL
            ACOUSTIC_TARGET_TTL = float(settings["target_ttl"])

        # Sensor positions for localization
        if "sensor_positions" in settings:
            self._sensor_positions = settings["sensor_positions"]

        # Configure classifier thresholds
        if "gunshot_energy_threshold" in settings:
            self._classifier.GUNSHOT_ENERGY_THRESHOLD = float(
                settings["gunshot_energy_threshold"]
            )
        if "voice_centroid_min_hz" in settings:
            self._classifier.VOICE_CENTROID_MIN_HZ = float(
                settings["voice_centroid_min_hz"]
            )

        # Register routes
        self._register_routes()

        ml_status = "ML+rules" if self._classifier.ml_available else "rules-only"
        self._logger.info("Acoustic plugin configured (%s)", ml_status)

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Start cleanup thread (removes stale acoustic targets)
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="acoustic-cleanup",
        )
        self._cleanup_thread.start()

        # Subscribe to EventBus for audio data from edge devices
        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="acoustic-events",
            )
            self._event_thread.start()

        self._logger.info(
            "Acoustic plugin started (poll=%.1fs)", self._poll_interval
        )

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=3.0)

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._logger.info("Acoustic plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Classification API ------------------------------------------------

    def classify_audio(
        self,
        features: dict,
        device_id: str = "",
        location: Optional[tuple[float, float]] = None,
    ) -> dict:
        """Classify audio features and return the event.

        Supports both basic features (spectral centroid, energy) and
        MFCC features for ML classification.
        """
        audio_features = AudioFeatures(
            rms_energy=features.get("rms_energy", 0.0),
            peak_amplitude=features.get("peak_amplitude", 0.0),
            zero_crossing_rate=features.get("zero_crossing_rate", 0.0),
            spectral_centroid=features.get("spectral_centroid", 0.0),
            spectral_bandwidth=features.get("spectral_bandwidth", 0.0),
            duration_ms=features.get("duration_ms", 0),
            mfcc=features.get("mfcc"),
            spectral_rolloff=features.get("spectral_rolloff", 0.0),
            spectral_flatness=features.get("spectral_flatness", 0.0),
        )

        event = self._classifier.classify(audio_features)
        event.device_id = device_id
        event.location = location

        # Track ML vs rule-based
        with self._lock:
            if hasattr(event, "model_version") and "knn" in event.model_version:
                self._stats["ml_classifications"] += 1
            else:
                self._stats["rule_classifications"] += 1

        self._on_classified(event)

        # Try localization if we have sensor position
        if location and event.event_type != AcousticEventType.UNKNOWN:
            self._try_localize(event, device_id, location)

        return self._event_to_dict(event)

    def register_sensor(self, sensor_id: str, lat: float, lon: float) -> None:
        """Register a sensor's position for acoustic localization."""
        self._sensor_positions[sensor_id] = (lat, lon)

    def get_recent_events(self, count: int = 50) -> list[dict]:
        """Get the most recent classified events."""
        with self._lock:
            return list(self._event_history[-count:])

    def get_timeline(self, count: int = 100) -> list[dict]:
        """Get acoustic event timeline with severity and location data.

        Returns events sorted by time, suitable for timeline rendering.
        """
        with self._lock:
            events = list(self._event_history[-count:])
        # Add severity to each event
        for e in events:
            et = e.get("event_type", "unknown")
            try:
                etype = AcousticEventType(et)
            except ValueError:
                etype = AcousticEventType.UNKNOWN
            if etype in HIGH_SEVERITY_EVENTS:
                e["severity"] = "high"
            elif etype in MEDIUM_SEVERITY_EVENTS:
                e["severity"] = "medium"
            else:
                e["severity"] = "low"
            e["color"] = SEVERITY_COLORS.get(e["severity"], "#00f0ff")
        return events

    def get_localizations(self, count: int = 50) -> list[dict]:
        """Get recent source localization results."""
        with self._lock:
            return list(self._localization_history[-count:])

    def get_stats(self) -> dict:
        """Get plugin statistics."""
        with self._lock:
            return {
                **self._stats,
                "active_targets": len(self._active_targets),
                "history_size": len(self._event_history),
                "classifier_history": len(
                    self._classifier.get_recent_events()
                ),
                "ml_available": self._classifier.ml_available,
                "sensors_registered": len(self._sensor_positions),
            }

    def get_event_counts(self) -> dict[str, int]:
        """Get count of each event type."""
        return self._classifier.get_event_counts()

    # -- TDoA (Time Difference of Arrival) ---------------------------------

    def submit_tdoa_observation(
        self,
        sensor_id: str,
        arrival_time_ms: float,
        signal_strength: float = 0.0,
        event_type: str = "unknown",
        confidence: float = 1.0,
        ntp_sync_quality: float = 0.0,
        lat: float = 0.0,
        lon: float = 0.0,
    ) -> Optional[dict]:
        """Submit a TDoA observation from an edge node.

        Buffers the observation and attempts TDoA localization when 3+
        sensors have reported the same event type within the time window.

        Returns:
            TDoA result dict if localization succeeded, None otherwise.
        """
        try:
            from tritium_lib.models.acoustic_tdoa import TDoAObservation, compute_tdoa_position
        except ImportError:
            log.debug("tritium_lib.models.acoustic_tdoa not available")
            return None

        obs = TDoAObservation(
            sensor_id=sensor_id,
            arrival_time_ms=arrival_time_ms,
            signal_strength=signal_strength,
            event_type=event_type,
            confidence=confidence,
            ntp_sync_quality=ntp_sync_quality,
            lat=lat,
            lon=lon,
        )

        now_ms = time.time() * 1000.0
        cutoff_ms = now_ms - (self._tdoa_window_s * 1000.0)

        with self._lock:
            self._stats["tdoa_observations"] += 1

            # Use sensor position from registry if not provided
            if lat == 0.0 and lon == 0.0 and sensor_id in self._sensor_positions:
                sp = self._sensor_positions[sensor_id]
                obs = obs.model_copy(update={"lat": sp[0], "lon": sp[1]})

            # Buffer observation
            if event_type not in self._tdoa_buffer:
                self._tdoa_buffer[event_type] = []
            self._tdoa_buffer[event_type].append(obs)

            # Prune old observations
            self._tdoa_buffer[event_type] = [
                o for o in self._tdoa_buffer[event_type]
                if o.arrival_time_ms > cutoff_ms
            ]

            # Check if we have 3+ unique sensors
            buffer = self._tdoa_buffer[event_type]
            unique_sensors = set(o.sensor_id for o in buffer)
            if len(unique_sensors) < 3:
                return None

            # De-dup: keep latest observation per sensor
            latest: dict[str, TDoAObservation] = {}
            for o in buffer:
                if o.sensor_id not in latest or o.arrival_time_ms > latest[o.sensor_id].arrival_time_ms:
                    latest[o.sensor_id] = o
            observations = list(latest.values())

        # Run TDoA computation outside lock
        result = compute_tdoa_position(observations)

        if result:
            result_dict = result.model_dump()
            with self._lock:
                self._tdoa_results.append(result_dict)
                if len(self._tdoa_results) > MAX_EVENT_HISTORY:
                    self._tdoa_results = self._tdoa_results[-MAX_EVENT_HISTORY:]
                self._stats["tdoa_localizations"] += 1

            # Publish event
            if self._event_bus:
                self._event_bus.publish("acoustic:tdoa_localized", data=result_dict)

            # Create target
            loc_event = {
                "event_type": result.event_type,
                "estimated_lat": result.lat,
                "estimated_lon": result.lon,
                "confidence": result.confidence,
                "observers": len(result.sensors_used),
                "timestamp": time.time(),
            }
            self._create_localized_target(loc_event)

            return result_dict

        return None

    def get_tdoa_results(self, count: int = 50) -> list[dict]:
        """Get recent TDoA localization results."""
        with self._lock:
            return list(self._tdoa_results[-count:])

    # -- Sound source localization -----------------------------------------

    def _try_localize(
        self,
        event: AcousticEvent,
        sensor_id: str,
        location: tuple[float, float],
    ) -> None:
        """Try to localize the sound source using multi-node TDoA.

        When multiple sensors detect the same event type within a time
        window, we estimate the source position.
        """
        now = time.time()
        evt_key = event.event_type.value

        with self._lock:
            # Add detection
            if evt_key not in self._recent_detections:
                self._recent_detections[evt_key] = []
            self._recent_detections[evt_key].append(
                (now, sensor_id, location[0], location[1], event.confidence)
            )

            # Prune old detections
            cutoff = now - LOCALIZATION_WINDOW_S
            self._recent_detections[evt_key] = [
                d for d in self._recent_detections[evt_key]
                if d[0] > cutoff
            ]

            # Need 2+ unique sensors
            detections = self._recent_detections[evt_key]
            unique_sensors = set(d[1] for d in detections)
            if len(unique_sensors) < 2:
                return

            # Build observers for localization
            observers = []
            seen_sensors = set()
            for ts, sid, lat, lon, conf in detections:
                if sid in seen_sensors:
                    continue
                seen_sensors.add(sid)
                observers.append({
                    "sensor_id": sid,
                    "lat": lat,
                    "lon": lon,
                    "arrival_time": ts,
                    "confidence": conf,
                })

        # Localize using TDoA weighted centroid
        try:
            from tritium_lib.models.acoustic_intelligence import acoustic_trilaterate
            result = acoustic_trilaterate(observers)
        except ImportError:
            result = self._simple_localize(observers)

        if result:
            loc_event = {
                "event_type": evt_key,
                "estimated_lat": result.get("estimated_lat", 0),
                "estimated_lon": result.get("estimated_lon", 0),
                "confidence": result.get("confidence", 0),
                "observers": len(observers),
                "timestamp": now,
            }

            with self._lock:
                self._localization_history.append(loc_event)
                if len(self._localization_history) > MAX_EVENT_HISTORY:
                    self._localization_history = self._localization_history[-MAX_EVENT_HISTORY:]
                self._stats["localizations"] += 1

            # Publish localization event
            if self._event_bus:
                self._event_bus.publish(
                    "acoustic:localized",
                    data=loc_event,
                )

            # Create/update target at localized position
            self._create_localized_target(loc_event)

    def _simple_localize(self, observers: list[dict]) -> Optional[dict]:
        """Simple weighted centroid fallback when tritium_lib unavailable."""
        if len(observers) < 2:
            return None

        observers_sorted = sorted(observers, key=lambda o: o["arrival_time"])
        t0 = observers_sorted[0]["arrival_time"]

        total_w = 0.0
        wlat = 0.0
        wlon = 0.0
        for obs in observers_sorted:
            dt = obs["arrival_time"] - t0
            w = obs.get("confidence", 1.0) / max(dt + 0.001, 0.001)
            wlat += obs["lat"] * w
            wlon += obs["lon"] * w
            total_w += w

        if total_w <= 0:
            return None

        return {
            "estimated_lat": round(wlat / total_w, 8),
            "estimated_lon": round(wlon / total_w, 8),
            "confidence": min(1.0, 0.3 + (len(observers) - 2) * 0.2),
        }

    def _create_localized_target(self, loc_event: dict) -> None:
        """Create a map target at the localized sound source position."""
        if self._tracker is None:
            return

        target_id = f"acoustic_loc_{loc_event['event_type']}_{int(loc_event['timestamp'])}"
        position = (loc_event["estimated_lat"], loc_event["estimated_lon"])

        with self._lock:
            self._active_targets[target_id] = (
                time.monotonic() + ACOUSTIC_TARGET_TTL
            )

        try:
            from tritium_lib.tracking.target_tracker import TrackedTarget

            severity = "low"
            try:
                etype = AcousticEventType(loc_event["event_type"])
                if etype in HIGH_SEVERITY_EVENTS:
                    severity = "high"
                elif etype in MEDIUM_SEVERITY_EVENTS:
                    severity = "medium"
            except ValueError:
                pass

            with self._tracker._lock:
                self._tracker._targets[target_id] = TrackedTarget(
                    target_id=target_id,
                    name=f"Sound: {loc_event['event_type']} (localized)",
                    alliance="unknown",
                    asset_type="acoustic_localized",
                    position=position,
                    last_seen=time.monotonic(),
                    source="acoustic",
                    position_source="tdoa_trilateration",
                    position_confidence=loc_event.get("confidence", 0.5),
                    status=f"{loc_event['event_type']}:{severity}:localized",
                )
        except Exception as exc:
            log.error("Failed to create localized acoustic target: %s", exc)

    # -- Internal event handling -------------------------------------------

    def _on_classified(self, event: AcousticEvent) -> None:
        """Handle a newly classified acoustic event."""
        event_dict = self._event_to_dict(event)

        with self._lock:
            self._event_history.append(event_dict)
            if len(self._event_history) > MAX_EVENT_HISTORY:
                self._event_history = self._event_history[-MAX_EVENT_HISTORY:]
            self._stats["events_classified"] += 1

        # Determine severity
        severity = "low"
        if event.event_type in HIGH_SEVERITY_EVENTS:
            severity = "high"
            with self._lock:
                self._stats["high_severity_count"] += 1
        elif event.event_type in MEDIUM_SEVERITY_EVENTS:
            severity = "medium"

        # Publish to EventBus
        if self._event_bus:
            self._event_bus.publish(
                "acoustic:classified",
                data={**event_dict, "severity": severity},
            )

            # High severity events get an additional alert
            if severity == "high":
                self._event_bus.publish(
                    "acoustic:alert",
                    data={
                        "type": event.event_type.value,
                        "confidence": event.confidence,
                        "device_id": event.device_id,
                        "location": event.location,
                        "severity": severity,
                        "timestamp": event.timestamp,
                    },
                )

        # Create target in tracker
        if event.event_type != AcousticEventType.UNKNOWN:
            self._create_acoustic_target(event, severity)

    def _create_acoustic_target(
        self, event: AcousticEvent, severity: str
    ) -> None:
        """Create a temporary target in TargetTracker for the acoustic event."""
        if self._tracker is None:
            return

        target_id = f"acoustic_{event.event_type.value}_{event.device_id or 'unknown'}"

        with self._lock:
            self._active_targets[target_id] = (
                time.monotonic() + ACOUSTIC_TARGET_TTL
            )
            self._stats["targets_created"] += 1

        try:
            from tritium_lib.tracking.target_tracker import TrackedTarget

            with self._tracker._lock:
                if target_id in self._tracker._targets:
                    t = self._tracker._targets[target_id]
                    t.last_seen = time.monotonic()
                    t.status = f"{event.event_type.value}:{severity}"
                    if event.location:
                        t.position = event.location
                else:
                    self._tracker._targets[target_id] = TrackedTarget(
                        target_id=target_id,
                        name=f"Acoustic: {event.event_type.value}",
                        alliance="unknown",
                        asset_type="acoustic_detection",
                        position=event.location or (0.0, 0.0),
                        last_seen=time.monotonic(),
                        source="acoustic",
                        position_source="microphone",
                        position_confidence=event.confidence,
                        status=f"{event.event_type.value}:{severity}",
                    )
        except Exception as exc:
            log.error("Failed to create acoustic target: %s", exc)

    # -- Cleanup loop (remove stale targets) --------------------------------

    def _cleanup_loop(self) -> None:
        """Background loop: remove expired acoustic targets."""
        while self._running:
            try:
                now = time.monotonic()
                expired = []

                with self._lock:
                    for tid, expiry in self._active_targets.items():
                        if now > expiry:
                            expired.append(tid)
                    for tid in expired:
                        del self._active_targets[tid]

                # Remove from tracker
                if self._tracker and expired:
                    try:
                        with self._tracker._lock:
                            for tid in expired:
                                self._tracker._targets.pop(tid, None)
                    except Exception:
                        pass

            except Exception as exc:
                log.error("Acoustic cleanup error: %s", exc)

            # Sleep in small increments for responsive shutdown
            deadline = time.monotonic() + self._poll_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    # -- Event bus listener (incoming audio data) --------------------------

    def _event_drain_loop(self) -> None:
        """Background loop: drain EventBus for audio data from edge."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._handle_event(event)
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("Acoustic event error: %s", exc)

    def _handle_event(self, event: dict) -> None:
        """Process incoming events for audio data."""
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        with self._lock:
            self._stats["events_processed"] += 1

        if event_type in ("audio:features", "audio:mfcc"):
            # MFCC + spectral features from edge
            self.classify_audio(
                features=data.get("features", data),
                device_id=data.get("device_id", ""),
                location=data.get("location"),
            )
        elif event_type == "audio:raw":
            # Raw audio data — extract features if possible
            features = data.get("features")
            if features:
                self.classify_audio(
                    features=features,
                    device_id=data.get("device_id", ""),
                    location=data.get("location"),
                )
        elif event_type == "acoustic:sensor_register":
            # Register sensor position for localization
            sid = data.get("sensor_id", "")
            lat = data.get("lat", 0.0)
            lon = data.get("lon", 0.0)
            if sid:
                self.register_sensor(sid, lat, lon)

    # -- Routes ------------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router

        router = create_router(self)
        self._app.include_router(router)

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _event_to_dict(event: AcousticEvent) -> dict:
        """Convert an AcousticEvent to a serializable dict."""
        return {
            "event_type": event.event_type.value,
            "confidence": event.confidence,
            "timestamp": event.timestamp,
            "duration_ms": event.duration_ms,
            "peak_frequency_hz": event.peak_frequency_hz,
            "peak_amplitude_db": event.peak_amplitude_db,
            "device_id": event.device_id,
            "location": event.location,
            "model_version": getattr(event, "model_version", "rule_based_v1"),
        }
