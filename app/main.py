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
from amy.router import router as amy_router
from app.routers.scenarios import router as scenarios_router
from app.routers.tts import router as tts_router
from app.routers.targets_unified import router as targets_unified_router
from app.routers.geo import router as geo_router


# ---------------------------------------------------------------------------
# Subsystem startup helpers
# ---------------------------------------------------------------------------

async def _discover_cameras() -> None:
    """Auto-discover cameras from NVR and register new ones."""
    try:
        from app.discovery.nvr import discover_cameras
        from app.models import Camera
        from sqlalchemy import select

        cameras = await discover_cameras()
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

    from amy.event_bus import EventBus
    from amy.simulation import SimulationEngine, load_layout

    # Temporary event bus; gets replaced by Amy's actual bus after create_amy
    engine = SimulationEngine(EventBus())

    if settings.simulation_layout:
        layout_path = Path(settings.simulation_layout)
        if layout_path.exists():
            count = load_layout(str(layout_path), engine)
            logger.info(f"Simulation: loaded {count} targets from {layout_path}")
        else:
            logger.warning(f"Simulation layout not found: {layout_path}")

    logger.info("Simulation engine created")
    return engine


def _start_mqtt_bridge(amy_instance) -> object | None:
    """Start MQTT bridge if enabled. Returns bridge or None."""
    if not settings.mqtt_enabled:
        return None

    try:
        from amy.mqtt_bridge import MQTTBridge
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
    except Exception as e:
        logger.warning(f"MQTT bridge failed to start: {e}")
        return None


def _start_escalation(amy_instance, sim_engine, mqtt_bridge) -> None:
    """Start threat classifier and auto-dispatcher."""
    try:
        from amy.escalation import ThreatClassifier, AutoDispatcher

        zones = _load_escalation_zones()

        classifier = ThreatClassifier(
            event_bus=amy_instance.event_bus,
            target_tracker=amy_instance.target_tracker,
            zones=zones,
        )
        classifier.start()
        amy_instance.threat_classifier = classifier

        dispatcher = AutoDispatcher(
            event_bus=amy_instance.event_bus,
            target_tracker=amy_instance.target_tracker,
            simulation_engine=sim_engine,
            mqtt_bridge=mqtt_bridge,
            threat_classifier=classifier,
        )
        dispatcher.start()
        amy_instance.auto_dispatcher = dispatcher

        logger.info("Threat escalation system started")
    except Exception as e:
        logger.warning(f"Threat escalation failed to start: {e}")


def _load_escalation_zones() -> list[dict]:
    """Load zones from layout file or return defaults."""
    if settings.simulation_layout:
        try:
            from amy.simulation.loader import load_zones
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

    # 2. MQTT bridge
    if mqtt_bridge is not None:
        logger.info("Stopping MQTT bridge...")
        mqtt_bridge.stop()

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

    # Database
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    # Recordings path
    if settings.recordings_path.exists():
        logger.info(f"Recordings path: {settings.recordings_path}")
    else:
        logger.warning(f"Recordings path not found: {settings.recordings_path}")

    # Geo reference — anchor local coordinates to real-world lat/lng
    if settings.map_center_lat != 0.0 or settings.map_center_lng != 0.0:
        from amy.geo import init_reference
        init_reference(settings.map_center_lat, settings.map_center_lng, settings.map_center_alt)
        logger.info(
            f"Geo reference: {settings.map_center_lat:.7f}, "
            f"{settings.map_center_lng:.7f}, alt={settings.map_center_alt:.1f}"
        )
    else:
        logger.info("Geo reference: not set (use /api/geo/reference to set)")

    # NVR camera discovery
    await _discover_cameras()

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
                sim_engine._event_bus = amy_instance.event_bus
                sim_engine.start()
                # If initial mode is "live", pause spawners immediately
                if amy_instance.mode == "live":
                    sim_engine.pause_spawners()
                    logger.info("Simulation engine started (10Hz tick, spawners paused — LIVE mode)")
                else:
                    logger.info("Simulation engine started (10Hz tick)")

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

            # MQTT bridge
            mqtt_bridge = _start_mqtt_bridge(amy_instance)
            if mqtt_bridge is not None:
                app.state.mqtt_bridge = mqtt_bridge

            # Threat escalation
            _start_escalation(amy_instance, sim_engine, mqtt_bridge)

        except Exception as e:
            logger.warning(f"Amy AI Commander failed to start: {e}")
            app.state.amy = None
    else:
        app.state.amy = None

    logger.info("=" * 60)
    logger.info("  TRITIUM-SC ONLINE")
    logger.info("=" * 60)

    yield

    _shutdown_subsystems(amy_instance, sim_engine, mqtt_bridge, app)
    logger.info("TRITIUM-SC shutting down...")


# Create FastAPI app
app = FastAPI(
    title="TRITIUM-SC",
    description="Security Central - Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(cameras_router)
app.include_router(videos_router)
app.include_router(ws_router)
app.include_router(discovery_router)
app.include_router(ai_router)
app.include_router(search_router)
app.include_router(zones_router)
app.include_router(assets_router)
app.include_router(amy_router)
app.include_router(scenarios_router)
app.include_router(tts_router)
app.include_router(targets_unified_router)
app.include_router(geo_router)

# Static files
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=frontend_path, follow_symlink=True), name="static")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Disable caching for static CSS/JS during development."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main dashboard."""
    index_path = frontend_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
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
