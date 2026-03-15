# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""YOLODetectorPlugin — object detection as a modular plugin.

Subscribes to camera frame events (from camera_feeds plugin or MQTT),
runs YOLO inference on received frames, and publishes detections to
EventBus and TargetTracker.

Configurable: model path, confidence threshold, inference interval.
Gracefully degrades if ultralytics is not installed.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Optional

import numpy as np

from engine.plugins.base import PluginContext, PluginInterface

from .detector import YOLODetector, FrameResult
from .reid_integration import ReIDIntegration
from .cross_camera_reid import CrossCameraReID

log = logging.getLogger("yolo-detector")


class YOLODetectorPlugin(PluginInterface):
    """YOLO object detection plugin.

    Listens for camera frame events, runs inference, and publishes
    detection results to EventBus and TargetTracker.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._target_tracker: Any = None
        self._app: Any = None
        self._logger: logging.Logger = log
        self._running = False

        # Detector instance (created on start)
        self._detector: Optional[YOLODetector] = None

        # Configuration
        self._model_path: str = "yolov8n.pt"
        self._confidence_threshold: float = 0.5
        self._device: Optional[str] = None
        self._inference_interval: float = 0.5  # seconds between inferences

        # Event bus subscription
        self._event_queue: Optional[queue.Queue] = None
        self._worker_thread: Optional[threading.Thread] = None

        # Frame buffer for direct injection
        self._pending_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()

        # Last result for API access
        self._last_result: Optional[FrameResult] = None

        # ReID integration (created on start if ReIDStore available)
        self._reid: Optional[ReIDIntegration] = None

        # Cross-camera ReID (created on start alongside ReID)
        self._cross_camera_reid: Optional[CrossCameraReID] = None

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.yolo-detector"

    @property
    def name(self) -> str:
        return "YOLO Detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"ai", "data_source", "routes"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Store references, apply settings, register routes."""
        self._event_bus = ctx.event_bus
        self._target_tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        # Apply plugin-specific settings
        settings = ctx.settings or {}
        self._model_path = settings.get("model_path", self._model_path)
        self._confidence_threshold = settings.get(
            "confidence_threshold", self._confidence_threshold,
        )
        self._device = settings.get("device", self._device)
        self._inference_interval = settings.get(
            "inference_interval", self._inference_interval,
        )

        self._register_routes()
        self._logger.info("YOLO Detector plugin configured")

    def start(self) -> None:
        """Initialize detector and start the inference worker."""
        if self._running:
            return

        # Create detector
        self._detector = YOLODetector(
            model_path=self._model_path,
            confidence_threshold=self._confidence_threshold,
            device=self._device,
        )

        self._running = True

        # Initialize ReID integration if ReIDStore is available
        try:
            from tritium_lib.store import ReIDStore
            reid_store = ReIDStore(":memory:")
            self._reid = ReIDIntegration(reid_store)
            self._logger.info("ReID integration enabled (in-memory store)")

            # Wire up cross-camera ReID with handoff tracker
            try:
                from engine.tactical.target_handoff import get_handoff_tracker
                dossier_store = None
                try:
                    from tritium_lib.store import DossierStore
                    dossier_store = DossierStore(":memory:")
                except Exception:
                    pass
                self._cross_camera_reid = CrossCameraReID(
                    reid_store=reid_store,
                    dossier_store=dossier_store,
                    event_bus=self._event_bus,
                    threshold=0.70,
                )
                # Register as handoff callback
                tracker = get_handoff_tracker(
                    on_handoff=self._cross_camera_reid.on_handoff,
                )
                self._logger.info("Cross-camera ReID wired to handoff tracker")
            except Exception as exc2:
                self._logger.debug("Cross-camera ReID not available: %s", exc2)
        except Exception as exc:
            self._logger.debug("ReID integration not available: %s", exc)
            self._reid = None

        # Subscribe to event bus for camera frame events
        if self._event_bus is not None:
            self._event_queue = self._event_bus.subscribe()
            self._worker_thread = threading.Thread(
                target=self._event_worker,
                name="yolo-detector-worker",
                daemon=True,
            )
            self._worker_thread.start()

        self._logger.info(
            "YOLO Detector started (model=%s, threshold=%.2f, stub=%s)",
            self._model_path,
            self._confidence_threshold,
            self._detector.stats.using_stub,
        )

    def stop(self) -> None:
        """Stop the inference worker and clean up."""
        if not self._running:
            return

        self._running = False

        # Unsubscribe from event bus
        if self._event_bus is not None and self._event_queue is not None:
            self._event_bus.unsubscribe(self._event_queue)
            self._event_queue = None

        # Wait for worker thread to finish
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

        self._detector = None
        self._logger.info("YOLO Detector stopped")

    @property
    def healthy(self) -> bool:
        return self._running and self._detector is not None

    # -- Public API --------------------------------------------------------

    def detect_frame(self, frame: np.ndarray) -> FrameResult:
        """Run detection on a single frame directly.

        Args:
            frame: BGR image as numpy array.

        Returns:
            FrameResult with detections.

        Raises:
            RuntimeError: If plugin is not started.
        """
        if self._detector is None:
            raise RuntimeError("YOLO Detector plugin is not started")
        result = self._detector.detect(frame)
        self._last_result = result
        self._publish_detections(result, frame=frame)
        return result

    def submit_frame(self, frame: np.ndarray) -> None:
        """Submit a frame for async detection by the worker thread.

        The latest frame overwrites any pending frame (drop old frames).
        """
        with self._frame_lock:
            self._pending_frame = frame

    @property
    def last_result(self) -> Optional[FrameResult]:
        """Most recent detection result."""
        return self._last_result

    @property
    def stats(self) -> dict:
        """Detection statistics."""
        if self._detector is None:
            return {"status": "not_started"}
        s = self._detector.stats.to_dict()
        if self._reid is not None:
            s["reid"] = self._reid.stats
        if self._cross_camera_reid is not None:
            s["cross_camera_reid"] = self._cross_camera_reid.stats
        return s

    @property
    def confidence_threshold(self) -> float:
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        self._confidence_threshold = max(0.0, min(1.0, value))
        if self._detector is not None:
            self._detector.confidence_threshold = self._confidence_threshold

    # -- Event worker ------------------------------------------------------

    def _event_worker(self) -> None:
        """Background thread: process camera frame events from EventBus."""
        last_inference = 0.0

        while self._running and self._event_queue is not None:
            # Check for frames submitted directly
            frame = None
            with self._frame_lock:
                if self._pending_frame is not None:
                    frame = self._pending_frame
                    self._pending_frame = None

            # Also check event bus for camera_frame events
            if frame is None:
                try:
                    event = self._event_queue.get(timeout=0.1)
                    if event.get("type") == "camera_frame":
                        data = event.get("data", {})
                        frame = data.get("frame")
                except queue.Empty:
                    continue

            if frame is None:
                continue

            # Rate-limit inference
            now = time.monotonic()
            if now - last_inference < self._inference_interval:
                continue

            if self._detector is None:
                continue

            try:
                source_camera = "default"
                result = self._detector.detect(frame)
                self._last_result = result
                self._publish_detections(result, frame=frame, source_camera=source_camera)
                last_inference = time.monotonic()
            except Exception as exc:
                self._logger.error("Detection error: %s", exc)

    # -- Internal ----------------------------------------------------------

    def _publish_detections(self, result: FrameResult, frame: Optional[np.ndarray] = None, source_camera: str = "default") -> None:
        """Publish detection results to EventBus, TargetTracker, and ReID."""
        if not result.detections:
            return

        # Run ReID on person/vehicle detections
        if self._reid is not None and frame is not None:
            try:
                det_dicts = [d.to_dict() for d in result.detections]
                reid_matches = self._reid.process_frame_detections(
                    frame, det_dicts, source_camera,
                )
                if reid_matches and self._event_bus is not None:
                    self._event_bus.publish("reid_matches", {
                        "matches": reid_matches,
                        "camera": source_camera,
                        "timestamp": result.timestamp,
                    })
            except Exception as exc:
                self._logger.debug("ReID processing error: %s", exc)

        # Publish to EventBus
        if self._event_bus is not None:
            self._event_bus.publish("yolo_detections", result.to_dict())

        # Update TargetTracker
        if self._target_tracker is not None:
            for det in result.detections:
                try:
                    self._target_tracker.update_target(
                        target_id=f"yolo-{det.class_name}-{det.center[0]}-{det.center[1]}",
                        target_type=det.class_name,
                        position=det.center,
                        confidence=det.confidence,
                        source="yolo",
                    )
                except Exception:
                    # TargetTracker API may vary — don't crash on mismatch
                    pass

    def _register_routes(self) -> None:
        """Register FastAPI routes for the YOLO detection API."""
        if not self._app:
            return
        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
