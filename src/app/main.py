# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TRITIUM-SC - Security Central - Intelligence Platform.

Main FastAPI application.
"""

import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config import settings
from app.database import init_db, async_session
from app.routers import cameras_router, videos_router, ws_router
from app.routers.discovery import router as discovery_router
from app.routers.ai import router as ai_router
from app.routers.search import router as search_router
from app.routers.zones import router as zones_router
from app.routers.assets import router as assets_router

from app.routers.scenarios import router as scenarios_router
from app.routers.tts import router as tts_router
from app.routers.targets_unified import router as targets_unified_router
from app.routers.geo import router as geo_router
from app.routers.game import router as game_router
from app.routers.audio import router as audio_router
from app.routers.synthetic_feed import router as synthetic_feed_router
from app.routers.telemetry import router as telemetry_router
from app.routers.mesh import router as mesh_router
from app.routers.geodata import router as geodata_router
from app.routers.npc import router as npc_router
from app.routers.plugins import router as plugins_router
from app.routers.devices import router as devices_router
from app.routers.tak import router as tak_router
from app.routers.fleet import router as fleet_router
from app.routers.demo import router as demo_router, robots_router
from app.routers.geofence import router as geofence_router
from app.routers.target_search import router as target_search_router
from app.routers.layers import router as layers_router
from app.routers.enrichment import router as enrichment_router
from app.routers.dossiers import router as dossiers_router
from app.routers.investigations import router as investigations_router
from app.routers.ontology import router as ontology_router
from app.routers.patrols import router as patrols_router
from app.routers.timeline import router as timeline_router
from app.routers.notifications import router as notifications_router
from app.routers.testing import router as testing_router
from app.routers.heatmap import router as heatmap_router
from app.routers.device_management import router as device_management_router
from app.routers.auth import router as auth_router
from app.routers.backup import router as backup_router
from app.routers.health import router as health_router
from app.routers.acoustic import router as acoustic_router
from app.routers.recordings import router as recordings_router
from app.routers.lpr import router as lpr_router
from app.routers.transponders import router as transponders_router
from app.routers.terrain import router as terrain_router
from app.routers.behavior import router as behavior_router
from app.routers.bookmarks import router as bookmarks_router
from app.routers.audit import router as audit_router
from app.routers.version import router as version_router
from app.routers.missions import router as missions_router
from app.routers.api_docs import router as api_docs_router
from app.routers.annotations import router as annotations_router
from app.routers.watchlist import router as watchlist_router
from app.routers.sitrep import router as sitrep_router
from app.routers.metrics import router as metrics_router
from app.routers.sessions import router as sessions_router
from app.routers.operator_activity import router as operator_activity_router
from app.routers.briefing import router as briefing_router
from app.routers.map_share import router as map_share_router
from app.routers.classification_override import router as classification_override_router
from app.routers.feedback import router as feedback_router
from app.routers.intelligence import router as intelligence_router
from app.routers.layouts import router as layouts_router
from app.routers.playback import router as playback_router
from app.routers.system_inventory import router as system_inventory_router
from app.routers.models import router as models_router
from app.routers.screenshots import router as screenshots_router
from app.routers.correlations import router as correlations_router
from app.routers.voice import router as voice_router
from app.routers.self_test import router as self_test_router
from app.routers.deployment import router as deployment_router
from app.routers.picture_of_day import router as picture_of_day_router
from app.routers.nearby_targets import router as nearby_targets_router
from app.routers.ollama_health import router as ollama_health_router
from app.routers.movement_analytics import router as movement_analytics_router
from app.routers.amy_briefing import router as amy_briefing_router
from app.routers.ar_export import router as ar_export_router
from app.routers.weather import router as weather_router
from app.routers.history_analytics import router as history_analytics_router
from app.routers.analytics_dashboard import router as analytics_dashboard_router
from app.routers.target_activity_heatmap import router as target_activity_heatmap_router
from app.routers.readiness import router as readiness_router
from app.routers.unified_events import router as unified_events_router
from app.routers.fusion_dashboard import router as fusion_dashboard_router
from app.routers.collaboration import router as collaboration_router
from app.routers.forensics import router as forensics_router
from app.routers.sensor_health import router as sensor_health_router
from app.routers.quick_actions import router as quick_actions_router
from app.routers.proximity import router as proximity_router
from app.routers.target_timeline import router as target_timeline_router
from app.routers.fleet_map import router as fleet_map_router
from app.routers.amy_personality import router as amy_personality_router
from app.routers.rate_limit_dashboard import router as rate_limit_dashboard_router
from app.routers.command_history import router as command_history_router
from app.routers.security_status import router as security_status_router
from app.routers.security_audit import router as security_audit_router
from app.routers.dwell import router as dwell_router
from app.routers.mesh_environment import router as mesh_environment_router
from app.routers.target_groups import router as target_groups_router
from app.routers.reid import router as reid_router
from app.routers.unified_alerts import router as unified_alerts_router


# ---------------------------------------------------------------------------
# Subsystem startup helpers
# ---------------------------------------------------------------------------

async def _discover_cameras() -> None:
    """Auto-discover cameras from NVR and register new ones.

    Runs NVR discovery with a configurable timeout (default 3s) in a
    background thread so it never blocks server startup.  If the NVR
    is unreachable, the server starts immediately and logs a warning.
    """
    try:
        from app.discovery.nvr import discover_cameras
        from app.models import Camera
        from sqlalchemy import select

        timeout = getattr(settings, "nvr_discovery_timeout", 3.0)
        try:
            cameras = await asyncio.wait_for(
                discover_cameras(), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"NVR camera discovery timed out after {timeout}s — "
                "server starting without cameras"
            )
            return

        if cameras:
            async with async_session() as db:
                result = await db.execute(select(Camera.channel))
                existing = {row[0] for row in result.fetchall()}

                added = 0
                for cam in cameras:
                    if cam.online and cam.channel not in existing:
                        db.add(Camera(
                            channel=cam.channel,
                            name=cam.name,
                            rtsp_url=cam.rtsp_main,
                            substream_url=cam.rtsp_sub,
                            enabled=True,
                        ))
                        added += 1
                await db.commit()

            online = sum(1 for c in cameras if c.online)
            logger.info(f"NVR: {len(cameras)} channels, {online} online, {added} auto-registered")
    except Exception as e:
        logger.warning(f"Auto-discovery failed: {e}")


def _create_simulation_engine():
    """Create and optionally load a SimulationEngine. Returns engine or None."""
    if not settings.simulation_enabled:
        return None

    from engine.comms.event_bus import EventBus
    from engine.simulation import SimulationEngine, load_layout

    # Set global Ollama host early so all LLM consumers use fleet
    try:
        from engine.perception.vision import set_ollama_host
        if settings.fleet_enabled:
            from engine.inference.fleet import OllamaFleet
            fleet = OllamaFleet(auto_discover=settings.fleet_auto_discover)
            if fleet.hosts:
                set_ollama_host(fleet.hosts[0].url)
                logger.info(f"Ollama fleet: {len(fleet.hosts)} host(s), primary={fleet.hosts[0].name}")
        else:
            set_ollama_host(settings.ollama_host)
    except Exception:
        logger.debug("Ollama fleet discovery skipped", exc_info=True)

    # Temporary event bus; gets replaced by Amy's actual bus after create_amy
    engine = SimulationEngine(EventBus())

    # Layout is NOT auto-loaded at startup — engine starts with 0 units.
    # Units are only placed by battle scenarios, API calls, or explicit
    # profile/mission loads.  The layout path is still available via
    # settings.simulation_layout for on-demand loading.

    logger.info("Simulation engine created (clean start, 0 units)")
    return engine


def _start_mqtt_bridge(amy_instance) -> object | None:
    """Start MQTT bridge if enabled. Returns bridge or None.

    Graceful: if mosquitto is not running, logs a warning and continues.
    Dev environments without docker will simply run without MQTT.
    """
    if not settings.mqtt_enabled:
        return None

    try:
        from engine.comms.mqtt_bridge import MQTTBridge
        bridge = MQTTBridge(
            event_bus=amy_instance.event_bus,
            target_tracker=amy_instance.target_tracker,
            site_id=settings.mqtt_site_id,
            broker_host=settings.mqtt_host,
            broker_port=settings.mqtt_port,
            username=settings.mqtt_username,
            password=settings.mqtt_password,
        )
        bridge.start()
        amy_instance.mqtt_bridge = bridge
        logger.info(f"MQTT bridge started ({settings.mqtt_host}:{settings.mqtt_port})")
        return bridge
    except ConnectionRefusedError:
        logger.warning(
            f"MQTT broker not reachable at {settings.mqtt_host}:{settings.mqtt_port} "
            "— running without MQTT (start mosquitto to enable fleet communication)"
        )
        return None
    except Exception as e:
        logger.warning(f"MQTT bridge failed to start: {e}")
        return None


def _start_meshtastic_bridge(amy_instance) -> object | None:
    """Start Meshtastic bridge if enabled. Returns bridge or None.

    Graceful: if the radio is not reachable, logs a warning and continues.
    """
    if not settings.meshtastic_enabled:
        return None

    try:
        from engine.comms.meshtastic_bridge import MeshtasticBridge
        bridge = MeshtasticBridge(
            event_bus=amy_instance.event_bus,
            target_tracker=amy_instance.target_tracker,
            host=settings.meshtastic_host,
            port=settings.meshtastic_port,
        )
        bridge.start()
        logger.info(
            f"Meshtastic bridge started "
            f"({settings.meshtastic_host or 'auto'}:{settings.meshtastic_port})"
        )
        return bridge
    except Exception as e:
        logger.warning(f"Meshtastic bridge failed to start: {e}")
        return None


def _start_meshcore_bridge(amy_instance) -> object | None:
    """Start MeshCore serial bridge if enabled. Returns bridge or None.

    Graceful: if the radio is not reachable, logs a warning and continues.
    """
    if not settings.meshcore_enabled:
        return None

    try:
        from engine.comms.meshcore_bridge import MeshCoreBridge
        bridge = MeshCoreBridge(
            event_bus=amy_instance.event_bus,
            target_tracker=amy_instance.target_tracker,
            serial_port=settings.meshcore_serial_port,
        )
        bridge.start()
        logger.info(
            f"MeshCore bridge started "
            f"(serial={settings.meshcore_serial_port or 'none'})"
        )
        return bridge
    except Exception as e:
        logger.warning(f"MeshCore bridge failed to start: {e}")
        return None


def _start_fleet_bridge(amy_instance) -> object | None:
    """Start FleetBridge if enabled. Returns bridge or None.

    Graceful: if the fleet server is not reachable, logs a warning and continues.
    """
    if not settings.fleet_bridge_enabled:
        return None

    try:
        from engine.comms.fleet_bridge import FleetBridge
        bridge = FleetBridge(
            event_bus=amy_instance.event_bus,
            ws_url=settings.fleet_bridge_url,
            rest_url=settings.fleet_server_url,
        )
        bridge.start()
        logger.info(f"Fleet bridge started ({settings.fleet_bridge_url})")
        return bridge
    except Exception as e:
        logger.warning(f"Fleet bridge failed to start: {e}")
        return None


def _start_mesh_web_source(amy_instance) -> object | None:
    """Start mesh web source poller if enabled. Returns source or None.

    Graceful: if the web source is unreachable, logs a warning and continues.
    """
    if not settings.mesh_web_enabled:
        return None

    try:
        from engine.comms.mesh_web_source import MeshWebSource
        source = MeshWebSource(
            event_bus=amy_instance.event_bus,
            target_tracker=amy_instance.target_tracker,
            poll_interval=settings.mesh_web_poll_interval,
            mesh_web_url=settings.mesh_web_url,
        )
        source.start()
        logger.info(
            f"Mesh web source started "
            f"(interval={settings.mesh_web_poll_interval}s, "
            f"url={'configured' if settings.mesh_web_url else 'none'})"
        )
        return source
    except Exception as e:
        logger.warning(f"Mesh web source failed to start: {e}")
        return None


def _start_plugins(app, amy_instance, sim_engine) -> object | None:
    """Discover, configure, and start all plugins. Returns PluginManager or None."""
    try:
        from engine.plugins.manager import PluginManager
        from engine.plugins.base import PluginContext
        import logging

        mgr = PluginManager()

        # Track discovery report for system health panel
        discovery_report: dict = {
            "scan_paths": [],
            "files_scanned": [],
            "plugins_found": [],
            "plugins_registered": [],
            "plugins_started": [],
            "plugins_failed": [],
            "plugins_skipped": [],
        }

        # Register built-in plugins first (so external plugins can depend on them)
        try:
            from engine.simulation.npc_intelligence.plugin import NPCIntelligencePlugin
            npc_intel = NPCIntelligencePlugin()
            mgr.register(npc_intel)
            discovery_report["plugins_registered"].append({
                "id": npc_intel.plugin_id,
                "name": npc_intel.name,
                "source": "built-in",
            })
        except Exception as e:
            logger.warning(f"NPC Intelligence plugin failed to register: {e}")
            npc_intel = None

        # Discover from plugins/ directory and env var
        plugins_dir = Path(__file__).parent.parent.parent / "plugins"
        scan_paths = []
        if plugins_dir.exists():
            scan_paths.append(str(plugins_dir))
            discovery_report["scan_paths"].append(str(plugins_dir))

            # Log files found in plugins directory
            for py_file in sorted(plugins_dir.glob("*.py")):
                if not py_file.name.startswith("_"):
                    discovery_report["files_scanned"].append(py_file.name)

        # Log scan start
        logger.info(f"Plugin discovery: scanning {len(scan_paths)} path(s)")

        found = mgr.discover(paths=scan_paths)
        for p in found:
            discovery_report["plugins_found"].append({
                "id": p.plugin_id,
                "name": p.name,
                "version": p.version,
            })
            try:
                mgr.register(p)
                discovery_report["plugins_registered"].append({
                    "id": p.plugin_id,
                    "name": p.name,
                    "source": "directory",
                })
            except ValueError:
                discovery_report["plugins_skipped"].append({
                    "id": p.plugin_id,
                    "reason": "duplicate",
                })

        if not mgr.list_plugins() and not found:
            logger.info("No plugins found")
            app.state.plugin_discovery_report = discovery_report
            return mgr

        # Build context factory
        event_bus = amy_instance.event_bus if amy_instance else None
        if event_bus is None and sim_engine is not None:
            event_bus = sim_engine.event_bus
        target_tracker = amy_instance.target_tracker if amy_instance else None

        def ctx_factory(plugin_id: str) -> PluginContext:
            return PluginContext(
                event_bus=event_bus,
                target_tracker=target_tracker,
                simulation_engine=sim_engine,
                settings={},
                app=app,
                logger=logging.getLogger(f"plugin.{plugin_id}"),
                plugin_manager=mgr,
            )

        mgr.configure_all(ctx_factory)
        results = mgr.start_all()

        # Wire NPC intelligence into the engine tick loop and app state
        if npc_intel is not None and sim_engine is not None:
            if results.get("tritium.npc-intelligence"):
                sim_engine.set_npc_intelligence(npc_intel)
                app.state.npc_intelligence_plugin = npc_intel
                logger.info("NPC Intelligence wired into engine tick loop")

        started = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)

        # Build detailed start report
        for pid, success in results.items():
            entry = {"id": pid}
            plugin = mgr.get_plugin(pid)
            if plugin:
                entry["name"] = plugin.name
                entry["version"] = plugin.version
            if success:
                discovery_report["plugins_started"].append(entry)
            else:
                discovery_report["plugins_failed"].append(entry)

        # Log summary with individual plugin status
        if started > 0 or failed > 0:
            logger.info(f"Plugins: {started} started, {failed} failed out of {len(results)} total")
            for pid, success in results.items():
                status = "OK" if success else "FAILED"
                plugin = mgr.get_plugin(pid)
                pname = plugin.name if plugin else pid
                logger.info(f"  [{status}] {pname} ({pid})")

        # Store report for health panel
        app.state.plugin_discovery_report = discovery_report

        return mgr

    except Exception as e:
        logger.warning(f"Plugin system failed to start: {e}")
        return None


def _start_escalation(amy_instance, sim_engine, mqtt_bridge) -> None:
    """Start threat classifier and auto-dispatcher."""
    try:
        from engine.tactical.escalation import ThreatClassifier, AutoDispatcher

        zones = _load_escalation_zones()

        classifier = ThreatClassifier(
            event_bus=amy_instance.event_bus,
            target_tracker=amy_instance.target_tracker,
            zones=zones,
            linger_threshold=settings.escalation_linger_threshold,
            deescalation_time=settings.escalation_deescalation_time,
        )
        classifier.start()
        amy_instance.threat_classifier = classifier

        dispatcher = AutoDispatcher(
            event_bus=amy_instance.event_bus,
            target_tracker=amy_instance.target_tracker,
            simulation_engine=sim_engine,
            mqtt_bridge=mqtt_bridge,
            threat_classifier=classifier,
            min_battery=settings.escalation_min_battery,
        )
        dispatcher.start()
        amy_instance.auto_dispatcher = dispatcher

        logger.info("Threat escalation system started")

        # System-wide threat level calculator
        try:
            from engine.tactical.threat_level_calculator import ThreatLevelCalculator
            threat_calc = ThreatLevelCalculator(
                event_bus=amy_instance.event_bus,
                target_tracker=amy_instance.target_tracker,
                escalation=classifier,
            )
            threat_calc.start()
            amy_instance.threat_level_calculator = threat_calc
            logger.info("Threat level calculator started")
        except Exception as e2:
            logger.warning(f"Threat level calculator failed: {e2}")

    except Exception as e:
        logger.warning(f"Threat escalation failed to start: {e}")


def _load_escalation_zones() -> list[dict]:
    """Load zones from layout file or return defaults."""
    if settings.simulation_layout:
        try:
            from engine.simulation.loader import load_zones
            layout_path = Path(settings.simulation_layout)
            if layout_path.exists():
                zones = load_zones(str(layout_path))
                logger.info(f"Escalation: loaded {len(zones)} zones from layout")
                return zones
        except Exception as e:
            logger.warning(f"Failed to load escalation zones: {e}")

    logger.info("Escalation: using default zones (perimeter r=25, restricted r=12)")
    return [
        {
            "name": "perimeter",
            "type": "entry_exit_zone",
            "position": {"x": 0.0, "z": 0.0},
            "properties": {"radius": 25.0},
        },
        {
            "name": "inner_zone",
            "type": "restricted_area",
            "position": {"x": 0.0, "z": 0.0},
            "properties": {"radius": 12.0},
        },
    ]


# ---------------------------------------------------------------------------
# Boot self-test
# ---------------------------------------------------------------------------

def _run_boot_self_test(app: FastAPI) -> dict:
    """Run quick health checks on all subsystems at startup and log results.

    Uses the same logic as /api/system/self-test but runs synchronously at
    boot time so the operator sees a clear pass/fail summary in the console.
    Returns the result dict (also stored in app.state.boot_self_test).
    """
    import time as _bt
    import socket as _socket

    start = _bt.monotonic()
    checks: list[dict] = []

    def _check(name: str, fn) -> dict:
        t0 = _bt.monotonic()
        try:
            detail = fn()
            return {"name": name, "status": "pass", "elapsed_ms": round((_bt.monotonic() - t0) * 1000, 1), "details": detail}
        except Exception as exc:
            return {"name": name, "status": "fail", "elapsed_ms": round((_bt.monotonic() - t0) * 1000, 1), "error": str(exc)}

    # 1. Amy
    def _amy():
        amy = getattr(app.state, "amy", None)
        if amy is not None:
            return {"running": getattr(amy, "_running", False), "mode": getattr(amy, "mode", "?")}
        return {"status": "disabled"}
    checks.append(_check("amy", _amy))

    # 2. Simulation engine
    def _sim():
        amy = getattr(app.state, "amy", None)
        sim = getattr(app.state, "simulation_engine", None)
        if sim is None and amy is not None:
            sim = getattr(amy, "simulation_engine", None)
        if sim is not None:
            return {"running": getattr(sim, "_running", False), "tick_rate": getattr(sim, "tick_rate", None)}
        return {"status": "disabled"}
    checks.append(_check("simulation", _sim))

    # 3. MQTT broker connectivity (probe TCP port even if bridge not enabled)
    def _mqtt():
        mqtt = getattr(app.state, "mqtt_bridge", None)
        if mqtt is not None:
            return {"bridge": "started", "connected": getattr(mqtt, "connected", False)}
        # Probe broker TCP port to report availability
        host = settings.mqtt_host or "localhost"
        port = settings.mqtt_port or 1883
        try:
            s = _socket.create_connection((host, port), timeout=2)
            s.close()
            return {"bridge": "disabled", "broker_reachable": True, "hint": "Set MQTT_ENABLED=true to activate"}
        except (ConnectionRefusedError, OSError):
            return {"bridge": "disabled", "broker_reachable": False, "hint": f"Start mosquitto on {host}:{port}"}
    checks.append(_check("mqtt_broker", _mqtt))

    # 4. Plugin manager + auto-discovery verification
    def _plugins():
        pm = getattr(app.state, "plugin_manager", None)
        report = getattr(app.state, "plugin_discovery_report", None)
        if pm is not None:
            plugins = pm.list_plugins()
            running = sum(1 for p in plugins if p.get("status") == "running")
            result = {"total": len(plugins), "running": running}
            if report:
                result["files_scanned"] = len(report.get("files_scanned", []))
                result["found"] = len(report.get("plugins_found", []))
                result["started"] = len(report.get("plugins_started", []))
                result["failed"] = len(report.get("plugins_failed", []))
                # List failed plugins by name for quick diagnosis
                failed_names = [p.get("name", p.get("id", "?"))
                                for p in report.get("plugins_failed", [])]
                if failed_names:
                    result["failed_plugins"] = failed_names
            return result
        return {"status": "not_initialized"}
    checks.append(_check("plugins", _plugins))

    # 5. Database
    def _db():
        from pathlib import Path as _P
        db_path = _P("tritium.db")
        if db_path.exists():
            size_kb = db_path.stat().st_size // 1024
            return {"exists": True, "size_kb": size_kb}
        return {"exists": False}
    checks.append(_check("database", _db))

    # 6. Notification manager
    def _notif():
        nm = getattr(app.state, "notification_manager", None)
        if nm is not None:
            return {"running": True, "unread": nm.count_unread()}
        return {"status": "disabled"}
    checks.append(_check("notifications", _notif))

    # 7. DossierManager
    def _dossier():
        dm = getattr(app.state, "dossier_manager", None)
        if dm is not None:
            return {"running": True}
        return {"status": "disabled"}
    checks.append(_check("dossier_manager", _dossier))

    # 8. Enrichment pipeline
    def _enrich():
        ep = getattr(app.state, "enrichment_pipeline", None)
        if ep is not None:
            names = ep.get_provider_names()
            return {"providers": len(names)}
        return {"status": "disabled"}
    checks.append(_check("enrichment", _enrich))

    # Aggregate and log
    total_ms = round((_bt.monotonic() - start) * 1000, 1)
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    total = len(checks)

    logger.info("")
    logger.info("=" * 60)
    logger.info("  BOOT SELF-TEST")
    logger.info("=" * 60)
    for c in checks:
        icon = "PASS" if c["status"] == "pass" else "FAIL"
        detail_str = ""
        if c["status"] == "pass" and c.get("details"):
            d = c["details"]
            if isinstance(d, dict):
                parts = []
                for k, v in d.items():
                    parts.append(f"{k}={v}")
                detail_str = f" ({', '.join(parts)})"
            elif isinstance(d, str):
                detail_str = f" ({d})"
        elif c["status"] == "fail":
            detail_str = f" ({c.get('error', '?')})"
        logger.info(f"  [{icon}] {c['name']}{detail_str}  ({c['elapsed_ms']}ms)")
    logger.info(f"  ---")
    logger.info(f"  {passed}/{total} passed, {failed} failed  ({total_ms}ms total)")
    logger.info("=" * 60)
    logger.info("")

    return {
        "passed": passed,
        "failed": failed,
        "total": total,
        "elapsed_ms": total_ms,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Shutdown helpers
# ---------------------------------------------------------------------------

def _shutdown_subsystems(amy_instance, sim_engine, mqtt_bridge, app: FastAPI) -> None:
    """Shut down all subsystems in reverse startup order."""
    # 1. Escalation (depends on everything)
    if amy_instance is not None:
        classifier = getattr(amy_instance, "threat_classifier", None)
        if classifier is not None:
            logger.info("Stopping threat classifier...")
            classifier.stop()
        dispatcher = getattr(amy_instance, "auto_dispatcher", None)
        if dispatcher is not None:
            logger.info("Stopping auto-dispatcher...")
            dispatcher.stop()

    # 1.5. Announcer
    announcer = getattr(app, "state", None) and getattr(app.state, "announcer", None)
    if announcer is not None:
        logger.info("Stopping war announcer...")
        announcer.stop()

    # 2. MQTT bridge
    if mqtt_bridge is not None:
        logger.info("Stopping MQTT bridge...")
        mqtt_bridge.stop()

    # 2.1. Meshtastic bridge
    mesh_bridge = getattr(getattr(app, "state", None), "meshtastic_bridge", None)
    if mesh_bridge is not None:
        logger.info("Stopping Meshtastic bridge...")
        mesh_bridge.stop()

    # 2.2. MeshCore bridge
    meshcore_bridge = getattr(getattr(app, "state", None), "meshcore_bridge", None)
    if meshcore_bridge is not None:
        logger.info("Stopping MeshCore bridge...")
        meshcore_bridge.stop()

    # 2.3. Mesh web source
    mesh_web = getattr(getattr(app, "state", None), "mesh_web_source", None)
    if mesh_web is not None:
        logger.info("Stopping mesh web source...")
        mesh_web.stop()

    # 2.4. Demo mode
    demo_ctrl = getattr(getattr(app, "state", None), "demo_controller", None)
    if demo_ctrl is not None and demo_ctrl.active:
        logger.info("Stopping demo mode...")
        demo_ctrl.stop()

    # 2.4b. Fleet bridge
    fleet_br = getattr(getattr(app, "state", None), "fleet_bridge", None)
    if fleet_br is not None:
        logger.info("Stopping fleet bridge...")
        fleet_br.stop()

    # 2.5. Synthetic camera
    syn_cam = getattr(getattr(app, "state", None), "syn_cam", None)
    if syn_cam is not None:
        logger.info("Stopping synthetic camera...")
        syn_cam.stop()

    # 3. Simulation engine
    if sim_engine is not None:
        logger.info("Stopping simulation engine...")
        sim_engine.stop()

    # 4. Amy (shuts down all internal threads)
    if amy_instance is not None:
        logger.info("Shutting down Amy...")
        amy_instance.shutdown()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("=" * 60)
    logger.info("  TRITIUM-SC v0.1.0 - INITIALIZING")
    logger.info("=" * 60)

    # Authentication
    from app.auth import init_default_admin
    init_default_admin()

    # Database
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    # Database migrations (versioned schema upgrades)
    try:
        from app.migrations import MigrationManager
        from app.database import engine as _db_engine
        _migrator = MigrationManager(engine=_db_engine)
        applied = await _migrator.migrate()
        if applied > 0:
            logger.info(f"Applied {applied} database migration(s)")
    except Exception as e:
        logger.warning(f"Migration check failed (non-fatal): {e}")

    # Recordings path
    if settings.recordings_path.exists():
        logger.info(f"Recordings path: {settings.recordings_path}")
    else:
        logger.warning(f"Recordings path not found: {settings.recordings_path}")

    # Geo reference — anchor local coordinates to real-world lat/lng
    from engine.tactical.geo import init_reference
    init_reference(settings.map_center_lat, settings.map_center_lng, settings.map_center_alt)
    if settings.map_center_lat == 0.0 and settings.map_center_lng == 0.0:
        logger.info("Geo reference: initialized at origin (use /api/geo/reference to set location)")
    else:
        logger.info(
            f"Geo reference: {settings.map_center_lat:.7f}, "
            f"{settings.map_center_lng:.7f}, alt={settings.map_center_alt:.1f}"
        )

    # NVR camera discovery — run in background so server starts immediately
    asyncio.create_task(_discover_cameras())

    # Amy + subsystems
    amy_instance = None
    sim_engine = None
    mqtt_bridge = None

    if settings.amy_enabled:
        try:
            from amy import create_amy
            from app.routers.ws import start_amy_event_bridge

            logger.info("Initializing Amy AI Commander...")

            # Simulation engine (created before Amy so she can reference it)
            sim_engine = _create_simulation_engine()

            # Amy commander
            amy_instance = create_amy(settings, simulation_engine=sim_engine)

            # Re-wire simulation engine to Amy's actual event bus and start
            if sim_engine is not None:
                sim_engine.set_event_bus(amy_instance.event_bus)
                sim_engine.start()
                # If initial mode is "live", pause spawners immediately
                if amy_instance.mode == "live":
                    sim_engine.pause_spawners()
                    logger.info("Simulation engine started (10Hz tick, spawners paused — LIVE mode)")
                else:
                    logger.info("Simulation engine started (10Hz tick)")

                # Register formation Lua actions against this engine instance
                try:
                    from engine.actions.lua_registry import LuaActionRegistry
                    from engine.actions.formation_actions import register_formation_actions
                    _formation_registry = LuaActionRegistry.with_core_actions()
                    register_formation_actions(_formation_registry, sim_engine)
                    logger.info("Formation Lua actions registered")
                except Exception as e:
                    logger.warning(f"Formation actions registration failed: {e}")

            # Synthetic camera node (overhead view of simulation)
            if sim_engine is not None:
                try:
                    from engine.nodes.synthetic_camera import SyntheticCameraNode
                    syn_cam = SyntheticCameraNode(sim_engine)
                    syn_cam.start()
                    amy_instance.nodes[syn_cam.node_id] = syn_cam
                    app.state.syn_cam = syn_cam
                    logger.info("Synthetic camera started (syn-cam-0)")
                except Exception as e:
                    logger.warning(f"Synthetic camera failed: {e}")

            # Run Amy in a background thread
            amy_thread = threading.Thread(
                target=amy_instance.run, daemon=True, name="amy"
            )
            amy_thread.start()
            app.state.amy = amy_instance
            logger.info("Amy AI Commander started")

            # Bridge Amy events to WebSocket
            start_amy_event_bridge(amy_instance, asyncio.get_event_loop())
            logger.info("Amy event bridge started")

            # Load real-world geo data (roads + buildings) for 3D renderer
            try:
                from engine.tactical.street_graph import StreetGraph
                from engine.tactical.obstacles import BuildingObstacles

                if settings.map_center_lat != 0.0 or settings.map_center_lng != 0.0:
                    sg = StreetGraph()
                    sg.load(settings.map_center_lat, settings.map_center_lng, radius_m=300)
                    if sg.graph:
                        if sim_engine is not None:
                            sim_engine.set_street_graph(sg)
                        app.state.road_polylines = sg.to_polylines()
                        logger.info(f"Road polylines: {len(app.state.road_polylines)} segments")

                    obs = BuildingObstacles()
                    obs.load(settings.map_center_lat, settings.map_center_lng, radius_m=300)
                    if obs.polygons:
                        if sim_engine is not None:
                            sim_engine.set_obstacles(obs)
                        app.state.building_dicts = obs.to_dicts()
                        logger.info(f"Building data: {len(app.state.building_dicts)} buildings")
            except Exception:
                logger.warning("Geo data unavailable", exc_info=True)

            # MQTT bridge
            mqtt_bridge = _start_mqtt_bridge(amy_instance)
            if mqtt_bridge is not None:
                app.state.mqtt_bridge = mqtt_bridge

            # Meshtastic mesh radio bridge
            mesh_bridge = _start_meshtastic_bridge(amy_instance)
            if mesh_bridge is not None:
                app.state.meshtastic_bridge = mesh_bridge

            # MeshCore serial radio bridge
            meshcore_bridge = _start_meshcore_bridge(amy_instance)
            if meshcore_bridge is not None:
                app.state.meshcore_bridge = meshcore_bridge

            # Mesh web source (public mesh network maps)
            mesh_web = _start_mesh_web_source(amy_instance)
            if mesh_web is not None:
                app.state.mesh_web_source = mesh_web

            # Fleet bridge (tritium-edge fleet server WebSocket)
            fleet_bridge = _start_fleet_bridge(amy_instance)
            if fleet_bridge is not None:
                app.state.fleet_bridge = fleet_bridge

            # Threat escalation
            _start_escalation(amy_instance, sim_engine, mqtt_bridge)

            # War announcer (subscribes to game events on EventBus)
            if sim_engine is not None:
                try:
                    from amy.actions.announcer import WarAnnouncer
                    announcer = WarAnnouncer(
                        amy_instance.event_bus,
                        speaker=getattr(amy_instance, "speaker", None),
                    )
                    announcer.start()
                    app.state.announcer = announcer
                    logger.info("War announcer started")
                except Exception as e:
                    logger.warning(f"War announcer failed to start: {e}")

        except Exception as e:
            logger.warning(f"Amy AI Commander failed to start: {e}")
            app.state.amy = None
    else:
        app.state.amy = None

        # Headless simulation: run game engine without Amy (for testing)
        if settings.simulation_enabled:
            from app.routers.ws import start_headless_event_bridge

            sim_engine = _create_simulation_engine()
            if sim_engine is not None:
                sim_engine.start()
                app.state.simulation_engine = sim_engine

                # Bridge sim events to WebSocket so the browser canvas renders targets
                start_headless_event_bridge(
                    sim_engine.event_bus, asyncio.get_event_loop(),
                    simulation_engine=sim_engine,
                )
                logger.info("Headless simulation engine + event bridge started (no Amy)")

                # Register formation Lua actions against this engine instance
                try:
                    from engine.actions.lua_registry import LuaActionRegistry
                    from engine.actions.formation_actions import register_formation_actions
                    _formation_registry = LuaActionRegistry.with_core_actions()
                    register_formation_actions(_formation_registry, sim_engine)
                    logger.info("Formation Lua actions registered (headless)")
                except Exception as e:
                    logger.warning(f"Formation actions registration failed: {e}")

    # Demo mode auto-start (TRITIUM_DEMO=true)
    if settings.tritium_demo and amy_instance is not None:
        try:
            from engine.synthetic.demo_mode import DemoController
            demo = DemoController(
                event_bus=amy_instance.event_bus,
                target_tracker=amy_instance.target_tracker,
            )
            demo.start()
            app.state.demo_controller = demo
            logger.info("Demo mode auto-started (TRITIUM_DEMO=true)")
        except Exception as e:
            logger.warning(f"Demo mode auto-start failed: {e}")

    # Enrichment pipeline — auto-query intelligence providers on new targets
    try:
        from engine.tactical.enrichment import EnrichmentPipeline
        _enrich_bus = amy_instance.event_bus if amy_instance else None
        enrichment_pipeline = EnrichmentPipeline(event_bus=_enrich_bus)
        app.state.enrichment_pipeline = enrichment_pipeline
        logger.info("Enrichment pipeline started with %d providers",
                     len(enrichment_pipeline.get_provider_names()))
    except Exception as e:
        logger.warning(f"Enrichment pipeline failed to start: {e}")

    # DossierManager — bridges TargetTracker (real-time) and DossierStore (persistent)
    try:
        from engine.tactical.dossier_manager import DossierManager
        from tritium_lib.store.dossiers import DossierStore
        _dossier_db = Path("data/dossiers.db")
        _dossier_db.parent.mkdir(parents=True, exist_ok=True)
        _dossier_store = DossierStore(_dossier_db)
        _dossier_tracker = amy_instance.target_tracker if amy_instance else None
        _dossier_bus = amy_instance.event_bus if amy_instance else None
        dossier_manager = DossierManager(
            store=_dossier_store,
            tracker=_dossier_tracker,
            event_bus=_dossier_bus,
        )
        dossier_manager.start()
        app.state.dossier_manager = dossier_manager
        logger.info("DossierManager started")
    except Exception as e:
        logger.warning(f"DossierManager failed to start: {e}")

    # Notification manager — collects alerts from all plugins via EventBus
    try:
        from engine.comms.notifications import NotificationManager
        from app.routers.notifications import set_manager as set_notification_manager
        from app.routers.ws import manager as _ws_manager
        import asyncio as _notif_asyncio

        _notif_bus = amy_instance.event_bus if amy_instance else None
        _notif_loop = _notif_asyncio.get_event_loop()

        def _ws_notif_broadcast(msg: dict) -> None:
            """Thread-safe broadcast of notification events to WebSocket clients."""
            try:
                _notif_asyncio.run_coroutine_threadsafe(
                    _ws_manager.broadcast(msg), _notif_loop
                )
            except Exception:
                pass

        notification_manager = NotificationManager(
            event_bus=_notif_bus,
            ws_broadcast=_ws_notif_broadcast,
        )
        set_notification_manager(notification_manager)
        app.state.notification_manager = notification_manager
        logger.info("NotificationManager started")
    except Exception as e:
        logger.warning(f"NotificationManager failed to start: {e}")
        notification_manager = None

    # Wire geofence engine to EventBus so enter/exit events reach notifications
    try:
        from app.routers.geofence import get_engine as _get_geofence_engine, set_engine as _set_geofence_engine
        from engine.tactical.geofence import GeofenceEngine as _GeofenceEngine
        _geo_bus = amy_instance.event_bus if amy_instance else (
            sim_engine.event_bus if sim_engine is not None else None
        )
        _geofence_eng = _GeofenceEngine(event_bus=_geo_bus)
        _set_geofence_engine(_geofence_eng)
        app.state.geofence_engine = _geofence_eng
        # Wire to target tracker so position updates trigger zone checks
        _tracker = amy_instance.target_tracker if amy_instance else None
        if _tracker:
            _tracker.set_geofence_engine(_geofence_eng)
            logger.info("GeofenceEngine wired to TargetTracker + EventBus")
        else:
            logger.info("GeofenceEngine wired to EventBus (no tracker yet)")
    except Exception as e:
        logger.warning(f"GeofenceEngine wiring failed: {e}")

    # Plugin system — discover, configure, and start all plugins
    plugin_manager = _start_plugins(app, amy_instance, sim_engine)
    if plugin_manager is not None:
        app.state.plugin_manager = plugin_manager
        if sim_engine is not None:
            sim_engine.set_plugin_manager(plugin_manager)

    # Addon system — discover and enable addons from addons/ directory
    try:
        from engine.addons.loader import AddonLoader
        addon_loader = AddonLoader(
            addon_dirs=["addons/", str(Path.home() / ".tritium" / "addons")],
            app=app,
        )
        found = addon_loader.discover()
        if found:
            logger.info(f"Discovered {len(found)} addon(s): {', '.join(found)}")
            for addon_id in found:
                try:
                    ok = await addon_loader.enable(addon_id)
                    if ok:
                        logger.info(f"Enabled addon: {addon_id}")
                    else:
                        logger.warning(f"Failed to enable addon: {addon_id}")
                except Exception as e:
                    logger.warning(f"Addon enable error for {addon_id}: {e}")
        app.state.addon_loader = addon_loader
        logger.info(f"Addon system: {len(addon_loader.enabled)} addon(s) active")
    except Exception as e:
        logger.warning(f"Addon system init failed (non-fatal): {e}")

    # Include addon API routes
    try:
        from app.routers.addons import router as addons_router
        app.include_router(addons_router)
    except Exception as e:
        logger.warning(f"Addon routes failed (non-fatal): {e}")

    # RL auto-retrain scheduler — retrains correlation model every 6h or
    # after 50 new feedback entries. Pushes results to Amy's sensorium.
    try:
        from engine.intelligence.correlation_learner import start_retrain_scheduler

        def _on_retrain(result: dict) -> None:
            """Push retrain results into Amy's sensorium for narration."""
            _amy = getattr(app.state, "amy", None)
            if _amy is None or not hasattr(_amy, "sensorium"):
                return
            success = result.get("success", False)
            accuracy = result.get("accuracy", 0.0)
            count = result.get("training_count", 0)
            if success:
                if accuracy < 0.70:
                    _amy.sensorium.push(
                        "tactical",
                        f"Correlation model retrained but accuracy is low: "
                        f"{accuracy:.0%} on {count} examples. Needs more feedback.",
                        importance=0.8,
                    )
                else:
                    _amy.sensorium.push(
                        "tactical",
                        f"Correlation model retrained: {accuracy:.0%} accuracy "
                        f"on {count} examples. Target fusion improving.",
                        importance=0.5,
                    )
            else:
                error = result.get("error", "unknown")
                if "Insufficient" not in str(error):
                    _amy.sensorium.push(
                        "tactical",
                        f"Correlation model retrain failed: {error}",
                        importance=0.6,
                    )

        _retrain_sched = start_retrain_scheduler(on_retrain=_on_retrain)
        app.state.retrain_scheduler = _retrain_sched
        logger.info("RL retrain scheduler started (6h interval, 50-entry threshold)")
    except Exception as e:
        logger.warning(f"Retrain scheduler failed to start: {e}")

    # Record startup time for /api/health uptime calculation
    from app.routers.health import reset_start_time
    reset_start_time()

    # -----------------------------------------------------------------------
    # Boot self-test — run quick checks on all subsystems and log summary
    # -----------------------------------------------------------------------
    _boot_results = _run_boot_self_test(app)
    app.state.boot_self_test = _boot_results

    # Start session timeout sweep (broadcasts WS warnings before expiry)
    from app.routers.sessions import session_timeout_sweep
    _session_sweep_task = asyncio.create_task(session_timeout_sweep(app))

    logger.info("=" * 60)
    logger.info("  TRITIUM-SC ONLINE")
    logger.info("=" * 60)

    yield

    # Cancel session sweep
    _session_sweep_task.cancel()

    # Stop plugins first (they may depend on subsystems)
    if plugin_manager is not None:
        logger.info("Stopping plugins...")
        plugin_manager.stop_all()

    # Stop dossier manager
    _dossier_mgr = getattr(app.state, "dossier_manager", None)
    if _dossier_mgr is not None:
        logger.info("Stopping DossierManager...")
        _dossier_mgr.stop()

    # Stop notification manager
    _notif_mgr = getattr(app.state, "notification_manager", None)
    if _notif_mgr is not None:
        _notif_mgr.stop()

    # Stop enrichment pipeline listener
    _enrich_pipe = getattr(app.state, "enrichment_pipeline", None)
    if _enrich_pipe is not None:
        _enrich_pipe.stop()

    # Stop retrain scheduler
    _retrain = getattr(app.state, "retrain_scheduler", None)
    if _retrain is not None:
        _retrain.stop()

    _shutdown_subsystems(amy_instance, sim_engine, mqtt_bridge, app)
    logger.info("TRITIUM-SC shutting down...")


# Create FastAPI app
app = FastAPI(
    title="TRITIUM-SC",
    description="Security Central - Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware — restrict origins in production via CORS_ALLOWED_ORIGINS env var
_cors_origins = (
    [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    if settings.cors_allowed_origins
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Requested-With"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# Rate limiting middleware (only active when rate_limit_enabled=True)
from app.rate_limit import RateLimitMiddleware
app.add_middleware(
    RateLimitMiddleware,
    max_requests=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window_seconds,
)

# Content-Security-Policy middleware — prevent XSS
from app.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

# Audit logging middleware — logs every API request for compliance
from app.audit_middleware import AuditLoggingMiddleware
app.add_middleware(AuditLoggingMiddleware)

# Include routers
app.include_router(cameras_router)
app.include_router(videos_router)
app.include_router(ws_router)
app.include_router(discovery_router)
app.include_router(ai_router)
app.include_router(search_router)
app.include_router(zones_router)
app.include_router(assets_router)

app.include_router(scenarios_router)
app.include_router(tts_router)
app.include_router(targets_unified_router)
app.include_router(target_search_router)
app.include_router(geo_router)
app.include_router(game_router)
app.include_router(audio_router)
app.include_router(synthetic_feed_router)
app.include_router(telemetry_router)
app.include_router(mesh_router)
app.include_router(geodata_router)
app.include_router(npc_router)
app.include_router(plugins_router)
app.include_router(devices_router)
app.include_router(tak_router)
app.include_router(fleet_router)
app.include_router(demo_router)
app.include_router(robots_router)
app.include_router(geofence_router)
app.include_router(layers_router)
app.include_router(enrichment_router)
app.include_router(dossiers_router)
app.include_router(investigations_router)
app.include_router(ontology_router)
app.include_router(patrols_router)
app.include_router(timeline_router)
app.include_router(notifications_router)
app.include_router(heatmap_router)
app.include_router(testing_router)
app.include_router(device_management_router)
app.include_router(auth_router)
app.include_router(backup_router)
app.include_router(health_router)
app.include_router(acoustic_router)
app.include_router(recordings_router)
app.include_router(lpr_router)
app.include_router(transponders_router)
app.include_router(terrain_router)
app.include_router(behavior_router)
app.include_router(bookmarks_router)
app.include_router(audit_router)
app.include_router(version_router)
app.include_router(missions_router)
app.include_router(api_docs_router)
app.include_router(annotations_router)
app.include_router(watchlist_router)
app.include_router(sitrep_router)
app.include_router(metrics_router)
app.include_router(sessions_router)
app.include_router(operator_activity_router)
app.include_router(briefing_router)
app.include_router(map_share_router)
app.include_router(classification_override_router)
app.include_router(feedback_router)
app.include_router(intelligence_router)
app.include_router(layouts_router)
app.include_router(playback_router)
app.include_router(system_inventory_router)
app.include_router(models_router)
app.include_router(screenshots_router)
app.include_router(correlations_router)
app.include_router(voice_router)
app.include_router(self_test_router)
app.include_router(deployment_router)
app.include_router(picture_of_day_router)
app.include_router(nearby_targets_router)
app.include_router(ollama_health_router)
app.include_router(movement_analytics_router)
app.include_router(amy_briefing_router)
app.include_router(ar_export_router)
app.include_router(weather_router)
app.include_router(history_analytics_router)
app.include_router(analytics_dashboard_router)
app.include_router(target_activity_heatmap_router)
app.include_router(readiness_router)
app.include_router(unified_events_router)
app.include_router(fusion_dashboard_router)
app.include_router(collaboration_router)
app.include_router(forensics_router)
app.include_router(sensor_health_router)
app.include_router(quick_actions_router)
app.include_router(proximity_router)
app.include_router(target_timeline_router)
app.include_router(fleet_map_router)
app.include_router(amy_personality_router)
app.include_router(rate_limit_dashboard_router)
app.include_router(command_history_router)
app.include_router(security_status_router)
app.include_router(security_audit_router)
app.include_router(dwell_router)
app.include_router(mesh_environment_router)
app.include_router(target_groups_router)
app.include_router(reid_router)
app.include_router(unified_alerts_router)

# Static files — addon frontend files served before main frontend
# so the SPA catch-all doesn't intercept /addons/ requests.
addons_path = Path(__file__).parent.parent.parent / "addons"
if addons_path.exists():
    app.mount("/addons", StaticFiles(directory=addons_path, follow_symlink=True), name="addon-static")

frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=frontend_path, follow_symlink=True), name="static")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Disable caching for static CSS/JS during development."""
    response = await call_next(request)
    if request.url.path.startswith(("/static/", "/addons/")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the Command Center (primary interface)."""
    unified_path = frontend_path / "unified.html"
    if unified_path.exists():
        return FileResponse(unified_path)
    return HTMLResponse(
        content="""
        <html>
            <head><title>TRITIUM-SC</title></head>
            <body style="background: #0a0a0f; color: #00f0ff; font-family: monospace;">
                <h1>TRITIUM-SC v0.1.0</h1>
                <p>Frontend not found. Please check installation.</p>
            </body>
        </html>
        """
    )


@app.get("/unified", response_class=HTMLResponse)
async def unified_redirect():
    """Redirect /unified to / for backwards compatibility."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/", status_code=301)


@app.get("/legacy", response_class=HTMLResponse)
async def legacy_dashboard():
    """Serve the legacy 10-tab SPA dashboard."""
    index_path = frontend_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(content="Legacy dashboard not found")


@app.get("/command", response_class=HTMLResponse)
async def command_center():
    """Serve the command center UI (deprecated, use / instead)."""
    cmd_path = frontend_path / "command.html"
    if cmd_path.exists():
        return FileResponse(cmd_path)
    return HTMLResponse(content="Command center not found")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "operational",
        "version": "0.1.0",
        "system": "TRITIUM-SC",
    }


@app.get("/api/status")
async def status():
    """System status endpoint."""
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "recordings_path": str(settings.recordings_path),
        "recordings_exists": settings.recordings_path.exists(),
        "database": "connected",
    }
