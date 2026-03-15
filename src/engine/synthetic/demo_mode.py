# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo mode controller — exercises the full pipeline with synthetic data.

Activates synthetic BLE, Meshtastic, and camera generators that publish
events through the real EventBus, proving end-to-end data flow without
any hardware.  Includes a FusionScenario that generates correlated
multi-sensor targets to demonstrate Tritium's core fusion capability.

Usage::

    from engine.synthetic.demo_mode import DemoController

    controller = DemoController(event_bus=bus, target_tracker=tracker)
    controller.start()
    print(controller.status())
    controller.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.synthetic.data_generators import (
    BLEScanGenerator,
    CameraDetectionGenerator,
    MeshtasticNodeGenerator,
    TrilaterationDemoGenerator,
)
from engine.synthetic.fusion_scenario import FusionScenario
from engine.synthetic.reid_demo_generator import ReIDDemoGenerator
from engine.synthetic.rl_training_generator import RLTrainingGenerator
from engine.synthetic.robot_demo_generator import RobotDemoGenerator

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.tactical.geofence import GeofenceEngine
    from engine.tactical.target_tracker import TargetTracker

logger = logging.getLogger("synthetic.demo_mode")


@dataclass
class GeneratorStats:
    """Snapshot of a running generator's state."""
    name: str
    running: bool
    started_at: float | None = None


class DemoController:
    """Orchestrates synthetic data generators for demo mode.

    Creates BLE, Meshtastic, and camera generators and wires them
    to the EventBus so data flows through the real pipeline.
    Also runs a FusionScenario that produces correlated multi-sensor
    targets for correlator fusion demonstration.
    """

    # Demo camera positions — placed around the demo neighborhood (San Francisco)
    # Demo mode updates the geo reference to center the map here.
    _DEMO_CAMERA_POSITIONS = [
        {"id": "demo-cam-01", "name": "North Gate", "lat": 37.7755, "lng": -122.4185,
         "heading": 180, "scene_type": "street_cam"},
        {"id": "demo-cam-02", "name": "South Lot", "lat": 37.7742, "lng": -122.4200,
         "heading": 45, "scene_type": "bird_eye"},
    ]

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker | None = None,
        geofence_engine: GeofenceEngine | None = None,
        camera_feeds_plugin=None,
        ble_device_count: int = 5,
        mesh_node_count: int = 3,
        camera_count: int = 2,
    ) -> None:
        self._event_bus = event_bus
        self._target_tracker = target_tracker
        self._geofence_engine = geofence_engine
        self._camera_feeds_plugin = camera_feeds_plugin
        self._ble_device_count = ble_device_count
        self._mesh_node_count = mesh_node_count
        self._camera_count = camera_count

        self._active = False
        self._started_at: float | None = None
        self._demo_camera_ids: list[str] = []  # track registered demo camera IDs

        self._ble_gen: BLEScanGenerator | None = None
        self._mesh_gen: MeshtasticNodeGenerator | None = None
        self._camera_gens: list[CameraDetectionGenerator] = []
        self._fusion: FusionScenario | None = None
        self._rl_training: RLTrainingGenerator | None = None
        self._trilat_demo: TrilaterationDemoGenerator | None = None
        self._reid_demo: ReIDDemoGenerator | None = None
        self._robot_demo: RobotDemoGenerator | None = None

        # Fleet heartbeat generator for fleet dashboard demo
        self._fleet_hb_thread: threading.Thread | None = None
        self._fleet_hb_running = False

        # Camera detection -> target tracker bridge
        self._cam_det_thread: threading.Thread | None = None
        self._cam_det_running = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        """Start all synthetic generators."""
        if self._active:
            logger.warning("Demo mode already active")
            return

        logger.info("Starting demo mode...")
        self._started_at = time.monotonic()

        # Update geo reference to demo neighborhood so the map centers on
        # the demo data.  All demo generators use San Francisco coordinates.
        try:
            from engine.tactical.geo import init_reference
            init_reference(37.7749, -122.4194, 10.0)
            logger.info("Geo reference updated to demo neighborhood (37.7749, -122.4194)")
        except Exception as e:
            logger.debug("Could not update geo reference for demo: %s", e)

        # BLE scanner
        self._ble_gen = BLEScanGenerator(
            interval=5.0,
            max_devices=self._ble_device_count,
            node_id="demo-scanner-01",
        )
        self._ble_gen.start(self._event_bus)

        # Meshtastic nodes
        self._mesh_gen = MeshtasticNodeGenerator(
            interval=10.0,
            node_count=self._mesh_node_count,
        )
        self._mesh_gen.start(self._event_bus)

        # Camera detections
        self._camera_gens = []
        for i in range(self._camera_count):
            cam_id = f"demo-cam-{i + 1:02d}"
            cam = CameraDetectionGenerator(
                interval=1.0,
                camera_id=cam_id,
                max_objects=4,
            )
            cam.start(self._event_bus)
            self._camera_gens.append(cam)

        # Register demo cameras with the camera_feeds plugin so they
        # appear on the map with lat/lng positions via /api/camera-feeds/
        self._register_demo_cameras()

        # Bridge camera detections to TargetTracker with geo-positioned coords
        self._start_camera_detection_bridge()

        # Fusion scenario — correlated multi-sensor targets
        self._fusion = FusionScenario(
            event_bus=self._event_bus,
            target_tracker=self._target_tracker,
            geofence_engine=self._geofence_engine,
            interval=2.0,
        )
        self._fusion.start()

        # RL training data generator — produces synthetic correlation
        # and classification decisions that accumulate in TrainingStore.
        # At 3s interval, generates ~100 decisions in 5 minutes, enough
        # to trigger a CorrelationLearner retrain.
        self._rl_training = RLTrainingGenerator(
            interval=3.0,
            event_bus=self._event_bus,
        )
        self._rl_training.start()

        # ReID cross-camera matching demo — simulates persons moving between
        # camera FOVs with similar embeddings for cross-camera identity matching.
        self._reid_demo = ReIDDemoGenerator(
            interval=2.0,
            event_bus=self._event_bus,
            num_persons=2,
        )
        self._reid_demo.start()

        # Multi-node trilateration demo — 3 fixed nodes + 3 moving BLE targets.
        # Feeds fleet.ble_presence events so the trilateration engine computes
        # live positions from 3 RSSI readings per target.
        self._trilat_demo = TrilaterationDemoGenerator(interval=3.0)
        self._trilat_demo.start(self._event_bus)

        # Robot demo — 3 synthetic robots (rover, drone, scout) patrolling
        # waypoint routes. Updates TargetTracker so they appear on the map.
        self._robot_demo = RobotDemoGenerator(interval=5.0)
        self._robot_demo.start(self._event_bus, self._target_tracker)

        # Fleet heartbeats — synthetic sensor nodes so fleet dashboard
        # shows 4 demo devices with realistic telemetry.
        self._start_fleet_heartbeat_generator()

        self._active = True
        self._event_bus.publish("demo:started", {
            "ble_devices": self._ble_device_count,
            "mesh_nodes": self._mesh_node_count,
            "cameras": self._camera_count,
            "fusion_scenario": True,
        })
        logger.info(
            f"Demo mode active: {self._ble_device_count} BLE devices, "
            f"{self._mesh_node_count} mesh nodes, {self._camera_count} cameras, "
            f"fusion scenario running"
        )

    def stop(self) -> None:
        """Stop all synthetic generators."""
        if not self._active:
            logger.warning("Demo mode not active")
            return

        logger.info("Stopping demo mode...")

        if self._ble_gen is not None:
            self._ble_gen.stop()
            self._ble_gen = None

        if self._mesh_gen is not None:
            self._mesh_gen.stop()
            self._mesh_gen = None

        # Stop camera detection bridge first
        self._stop_camera_detection_bridge()

        for cam in self._camera_gens:
            cam.stop()
        self._camera_gens = []

        if self._fusion is not None:
            self._fusion.stop()
            self._fusion = None

        if self._rl_training is not None:
            self._rl_training.stop()
            self._rl_training = None

        if self._reid_demo is not None:
            self._reid_demo.stop()
            self._reid_demo = None

        if self._trilat_demo is not None:
            self._trilat_demo.stop()
            self._trilat_demo = None

        if self._robot_demo is not None:
            self._robot_demo.stop()
            self._robot_demo = None

        # Stop fleet heartbeat generator
        self._stop_fleet_heartbeat_generator()

        # Remove demo cameras from camera_feeds plugin
        self._unregister_demo_cameras()

        self._active = False
        self._event_bus.publish("demo:stopped", {})
        logger.info("Demo mode stopped")

    def _register_demo_cameras(self) -> None:
        """Register synthetic demo cameras with the camera_feeds plugin.

        This ensures GET /api/camera-feeds/ returns cameras with lat/lng
        so the map can render camera markers and FOV cones.
        """
        if self._camera_feeds_plugin is None:
            return

        from plugins.camera_feeds.sources import CameraSourceConfig

        for cam_info in self._DEMO_CAMERA_POSITIONS:
            cam_id = cam_info["id"]
            try:
                config = CameraSourceConfig(
                    source_id=cam_id,
                    source_type="synthetic",
                    name=cam_info.get("name", cam_id),
                    width=640,
                    height=480,
                    fps=5,
                    extra={
                        "lat": cam_info["lat"],
                        "lng": cam_info["lng"],
                        "heading": cam_info.get("heading", 0),
                        "scene_type": cam_info.get("scene_type", "bird_eye"),
                    },
                )
                self._camera_feeds_plugin.register_source(config)
                self._demo_camera_ids.append(cam_id)
                logger.info("Registered demo camera: %s at (%.4f, %.4f)",
                            cam_id, cam_info["lat"], cam_info["lng"])
            except (ValueError, Exception) as e:
                logger.debug("Could not register demo camera %s: %s", cam_id, e)

    def _unregister_demo_cameras(self) -> None:
        """Remove demo cameras from the camera_feeds plugin on stop."""
        if self._camera_feeds_plugin is None:
            return

        for cam_id in self._demo_camera_ids:
            try:
                self._camera_feeds_plugin.remove_source(cam_id)
            except (KeyError, Exception):
                pass
        self._demo_camera_ids = []

    # -- Camera detection -> TargetTracker bridge ----------------------------
    # Subscribes to detection:camera EventBus events and converts normalized
    # pixel coords to local ground coordinates near the camera's geo-position,
    # then feeds them into TargetTracker so YOLO detections appear on the map.

    def _start_camera_detection_bridge(self) -> None:
        """Start a background thread bridging camera detections to targets."""
        if self._target_tracker is None:
            logger.debug("No target_tracker — skipping camera detection bridge")
            return

        # Build camera_id -> (lat, lng) lookup from demo camera positions
        self._cam_geo_positions: dict[str, tuple[float, float]] = {}
        for cam_info in self._DEMO_CAMERA_POSITIONS:
            self._cam_geo_positions[cam_info["id"]] = (
                cam_info["lat"], cam_info["lng"]
            )

        self._cam_det_running = True
        self._cam_det_queue = self._event_bus.subscribe()
        self._cam_det_thread = threading.Thread(
            target=self._camera_detection_loop,
            daemon=True,
            name="demo-cam-det-bridge",
        )
        self._cam_det_thread.start()
        logger.info("Camera detection bridge started for %d cameras",
                     len(self._cam_geo_positions))

    def _stop_camera_detection_bridge(self) -> None:
        """Stop the camera detection bridge thread."""
        self._cam_det_running = False
        if self._cam_det_thread is not None:
            self._cam_det_thread.join(timeout=2.0)
            self._cam_det_thread = None
        if hasattr(self, '_cam_det_queue'):
            self._event_bus.unsubscribe(self._cam_det_queue)

    def _camera_detection_loop(self) -> None:
        """Process detection:camera events and create geo-located targets.

        Uses TargetTracker.update_from_camera_detection() which converts
        normalized pixel coords to game coordinates near the camera lat/lng.
        """
        import queue as _queue

        while self._cam_det_running:
            try:
                msg = self._cam_det_queue.get(timeout=0.5)
            except _queue.Empty:
                continue

            if msg.get("type") != "detection:camera":
                continue

            data = msg.get("data", {})
            camera_id = data.get("camera_id", "")
            detections = data.get("detections", [])

            cam_geo = self._cam_geo_positions.get(camera_id)
            if cam_geo is None:
                continue

            cam_lat, cam_lng = cam_geo

            for det in detections:
                try:
                    self._target_tracker.update_from_camera_detection(
                        detection=det,
                        camera_lat=cam_lat,
                        camera_lng=cam_lng,
                    )
                except Exception as e:
                    logger.debug("Camera detection bridge error: %s", e)

    # -- Fleet heartbeat generator for fleet dashboard demo ----------------

    # 4 synthetic sensor nodes placed around the demo neighborhood
    _DEMO_FLEET_NODES = [
        {"device_id": "demo-node-alpha", "name": "Alpha-Node", "lat": 37.7752, "lng": -122.4190,
         "firmware": "tritium-os-1.4.2", "device_group": "demo-perimeter"},
        {"device_id": "demo-node-bravo", "name": "Bravo-Node", "lat": 37.7746, "lng": -122.4198,
         "firmware": "tritium-os-1.4.2", "device_group": "demo-perimeter"},
        {"device_id": "demo-node-charlie", "name": "Charlie-Node", "lat": 37.7749, "lng": -122.4185,
         "firmware": "tritium-os-1.4.1", "device_group": "demo-interior"},
        {"device_id": "demo-node-delta", "name": "Delta-Node", "lat": 37.7755, "lng": -122.4200,
         "firmware": "tritium-os-1.4.2", "device_group": "demo-interior"},
    ]

    def _start_fleet_heartbeat_generator(self) -> None:
        """Start generating fleet.heartbeat events for demo sensor nodes."""
        self._fleet_hb_running = True
        self._fleet_hb_thread = threading.Thread(
            target=self._fleet_heartbeat_loop,
            daemon=True,
            name="demo-fleet-hb-gen",
        )
        self._fleet_hb_thread.start()
        logger.info("Fleet heartbeat generator started: %d demo nodes",
                     len(self._DEMO_FLEET_NODES))

    def _stop_fleet_heartbeat_generator(self) -> None:
        """Stop the fleet heartbeat generator."""
        self._fleet_hb_running = False
        if self._fleet_hb_thread is not None:
            self._fleet_hb_thread.join(timeout=2.0)
            self._fleet_hb_thread = None

    def _fleet_heartbeat_loop(self) -> None:
        """Emit fleet.heartbeat events every 15s for synthetic sensor nodes.

        Publishes an initial batch immediately so the fleet dashboard
        shows devices right away, then continues at 15s intervals.
        """
        import random as _random
        rng = _random.Random(42)
        # Per-node battery state (starts high, drains slowly)
        batteries = {n["device_id"]: rng.uniform(0.7, 0.98) for n in self._DEMO_FLEET_NODES}
        # Per-node uptime (starts around 1-12 hours)
        uptimes = {n["device_id"]: rng.uniform(3600, 43200) for n in self._DEMO_FLEET_NODES}
        tick = 0
        first_pass = True

        while self._fleet_hb_running:
            for node in self._DEMO_FLEET_NODES:
                did = node["device_id"]
                tick += 1
                # Slowly drain battery
                batteries[did] = max(0.15, batteries[did] - rng.uniform(0.0001, 0.0005))
                uptimes[did] += 15.0  # 15s heartbeat interval

                heartbeat = {
                    "device_id": did,
                    "name": node["name"],
                    "ip": f"10.0.1.{10 + self._DEMO_FLEET_NODES.index(node)}",
                    "battery_pct": round(batteries[did] * 100, 1),
                    "uptime_s": round(uptimes[did]),
                    "free_heap": rng.randint(80000, 140000),
                    "ble_count": rng.randint(2, 12),
                    "wifi_count": rng.randint(3, 8),
                    "version": node["firmware"],
                    "rssi": rng.randint(-75, -35),
                    "lat": node["lat"],
                    "lng": node["lng"],
                    "device_group": node["device_group"],
                    "lifecycle_state": "active",
                }
                self._event_bus.publish("fleet.heartbeat", heartbeat)

            if first_pass:
                first_pass = False
                time.sleep(2.0)  # Short delay on first pass for rapid display
            else:
                time.sleep(15.0)

    def get_scenario_info(self) -> dict:
        """Return fusion scenario description and live dossier state."""
        if self._fusion is not None:
            return self._fusion.get_scenario_info()
        # Return static description even when not running
        from engine.synthetic.fusion_scenario import SCENARIO_DESCRIPTION
        info = dict(SCENARIO_DESCRIPTION)
        info["running"] = False
        info["tick_count"] = 0
        info["dossiers"] = []
        return info

    def status(self) -> dict:
        """Return current demo mode status."""
        generators = []

        if self._ble_gen is not None:
            generators.append({
                "name": "BLEScanGenerator",
                "running": self._ble_gen.running,
                "config": {
                    "max_devices": self._ble_device_count,
                    "interval": 5.0,
                },
            })

        if self._mesh_gen is not None:
            generators.append({
                "name": "MeshtasticNodeGenerator",
                "running": self._mesh_gen.running,
                "config": {
                    "node_count": self._mesh_node_count,
                    "interval": 10.0,
                },
            })

        for i, cam in enumerate(self._camera_gens):
            generators.append({
                "name": "CameraDetectionGenerator",
                "camera_id": f"demo-cam-{i + 1:02d}",
                "running": cam.running,
                "config": {
                    "max_objects": 4,
                    "interval": 1.0,
                },
            })

        if self._fusion is not None:
            generators.append({
                "name": "FusionScenario",
                "running": self._fusion.running,
                "config": {
                    "actors": 3,
                    "interval": 2.0,
                },
            })

        if self._rl_training is not None:
            rl_stats = self._rl_training.get_stats()
            generators.append({
                "name": "RLTrainingGenerator",
                "running": self._rl_training.running,
                "tick_count": self._rl_training.tick_count,
                "config": {
                    "interval": 3.0,
                },
                "training_store": rl_stats.get("training_store"),
            })

        if self._reid_demo is not None:
            reid_stats = self._reid_demo.get_stats()
            generators.append({
                "name": "ReIDDemoGenerator",
                "running": self._reid_demo.running,
                "tick_count": self._reid_demo.tick_count,
                "matches_found": self._reid_demo.matches_found,
                "config": {
                    "num_persons": 2,
                    "interval": 2.0,
                },
                "reid_store": reid_stats.get("reid_store"),
            })

        if self._trilat_demo is not None:
            generators.append({
                "name": "TrilaterationDemoGenerator",
                "running": self._trilat_demo.running,
                "config": {
                    "targets": 3,
                    "nodes": 3,
                    "interval": 3.0,
                },
            })

        if self._robot_demo is not None:
            robot_stats = self._robot_demo.get_stats()
            generators.append({
                "name": "RobotDemoGenerator",
                "running": self._robot_demo.running,
                "tick_count": self._robot_demo.tick_count,
                "config": {
                    "robots": 3,
                    "interval": 5.0,
                },
                "robots": robot_stats.get("robots", []),
            })

        uptime = None
        if self._started_at is not None and self._active:
            uptime = round(time.monotonic() - self._started_at, 1)

        return {
            "active": self._active,
            "uptime_s": uptime,
            "generators": generators,
            "generator_count": len(generators),
        }
