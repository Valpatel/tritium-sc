# TRITIUM-SC - Claude Code Context

## Project Overview

TRITIUM-SC (Tritium-Security Central) is a neighborhood-scale Nerf battlefield management system and real-time strategy game. It interfaces with real and virtual sensors to provide tactical situational awareness through a trusted access terminal with AI Commander Amy. Real sensors (BCC950 PTZ cam, NVR cameras, RTSP streams, USB mics) coexist with virtual units (simulated rovers, drones, turrets, hostile intruders) on the same tactical map, same APIs, same event bus. Simulation lives alongside reality.

Amy is an autonomous consciousness with 4 cognitive layers (reflex -> instinct -> awareness -> deliberation). She sees through cameras, hears through mics, thinks in continuous inner monologue, dispatches assets, and acts when she decides to. Inspired by Masanobu Fukuoka's "One-Straw Revolution" -- the operator tends the system like a garden, not a factory.

See [docs/PLAN.md](docs/PLAN.md) for the full development roadmap and technical architecture.

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy, aiosqlite
- **Frontend**: Vanilla JavaScript, Three.js, Canvas 2D, CYBERCORE CSS (no frameworks)
- **Database**: SQLite with FTS5 for full-text search
- **AI/ML**: YOLOv8, ByteTrack (object tracking), PyTorch/CUDA
- **Streaming**: go2rtc integration for RTSP/WebRTC
- **Communication**: MQTT (paho-mqtt) for distributed device mesh
- **STT/TTS**: whisper.cpp (GPU), Silero VAD, Piper TTS

## Key Directories

```
tritium-sc/
├── amy/                    # AMY — AI Commander (autonomous consciousness)
│   ├── commander.py       # Main orchestrator, EventBus, VisionThread, AudioThread
│   ├── sensorium.py       # L3 awareness: temporal sensor fusion
│   ├── thinking.py        # L4 deliberation: inner monologue
│   ├── target_tracker.py  # Unified registry of real + virtual targets
│   ├── escalation.py      # ThreatClassifier + AutoDispatcher
│   ├── mqtt_bridge.py     # MQTT broker bridge for distributed devices
│   ├── simulation/        # Battlespace simulation engine
│   │   ├── engine.py     # 10Hz tick loop, hostile spawner
│   │   ├── target.py     # SimulationTarget dataclass
│   │   ├── ambient.py    # AmbientSpawner (neutral neighborhood activity)
│   │   └── loader.py     # TritiumLevelFormat JSON parser
│   ├── scenarios/         # Behavioral test framework (runner, scorer, schema)
│   ├── nodes/             # Distributed sensor nodes (BCC950, IP cam, virtual)
│   ├── router.py          # FastAPI: /api/amy/*
│   └── (agent, listener, speaker, motor, memory, tools, lua_motor)
├── app/                    # FastAPI backend
│   ├── routers/           # API endpoints + WebSocket + Amy event bridge
│   ├── ai/                # Detection pipeline (YOLO, tracker, embeddings)
│   ├── zones/             # Zone management and alerting
│   ├── discovery/         # NVR auto-discovery
│   └── models.py          # SQLAlchemy models
├── frontend/              # Static frontend (no build step)
│   ├── index.html         # Main SPA shell (10 views)
│   ├── js/                # Modular JavaScript
│   │   ├── app.js        # Main app, view switching, shortcuts
│   │   ├── amy.js        # Amy dashboard (thoughts, video, chat)
│   │   ├── war.js        # War Room — Canvas 2D RTS tactical map
│   │   ├── assets.js     # Asset state + tactical map rendering
│   │   ├── input.js      # Input handling (keyboard + gamepad)
│   │   ├── scenarios.js   # Scenario runner dashboard
│   │   └── (grid, player, zones, targets, analytics)
│   └── css/
│       ├── cybercore.css # CYBERCORE CSS framework
│       └── tritium.css   # Custom + Amy + War Room panel styles
├── examples/
│   └── robot-template/   # Reference MQTT robot brain for real hardware
├── docs/                  # Documentation (architecture, escalation, MQTT, simulation)
├── scenarios/             # 33 behavioral test scenarios (JSON)
├── tests/                 # Test suite (572+ unit tests, 11 E2E specs)
└── channel_*/            # Recorded footage by channel/date
```

## Code Conventions

- **No frontend frameworks**: Vanilla JavaScript only (no React, Vue, etc.)
- **Cyberpunk aesthetic**: Neon colors (cyan #00f0ff, magenta #ff2a6d, green #05ffa1, yellow #fcee0a), ASCII art, glitch effects
- **Modular JS**: Each view has its own JS file with clear exports
- **All UI navigable via keyboard + gamepad**: Full accessibility support
- **No emojis in code comments**: Keep professional
- **Type hints in Python**: Use type annotations
- **Async/await**: Prefer async patterns throughout

## Important Files

| File | Purpose |
|------|---------|
| `amy/commander.py` | Amy AI Commander — main orchestrator, VisionThread, AudioThread |
| `amy/event_bus.py` | EventBus — thread-safe pub/sub for all internal events |
| `amy/sensorium.py` | L3 awareness: temporal sensor fusion + narrative |
| `amy/thinking.py` | L4 deliberation: inner monologue via fast LLM |
| `amy/target_tracker.py` | Unified registry of real (YOLO) + virtual (sim) targets |
| `amy/escalation.py` | ThreatClassifier (2Hz) + AutoDispatcher |
| `amy/mqtt_bridge.py` | MQTT broker bridge — distributed device communication |
| `amy/simulation/engine.py` | SimulationEngine — 10Hz tick loop |
| `amy/simulation/target.py` | SimulationTarget dataclass (all entity types) |
| `amy/simulation/ambient.py` | AmbientSpawner — neutral neighborhood activity |
| `amy/simulation/loader.py` | TritiumLevelFormat JSON parser |
| `amy/perception.py` | Layered perception: quality gate, complexity, motion detection |
| `amy/extraction.py` | Fact extraction from conversation (regex-based) |
| `amy/transcript.py` | Conversation transcript logging |
| `amy/nodes/base.py` | Abstract SensorNode (camera, mic, PTZ, speaker) |
| `amy/nodes/bcc950.py` | BCC950 PTZ camera + mic + speaker node |
| `amy/router.py` | /api/amy/* — status, thoughts SSE, chat, commands |
| `app/main.py` | FastAPI app entry point, lifespan, boot sequence |
| `app/config.py` | Pydantic settings (app + Amy + MQTT + simulation) |
| `app/models.py` | SQLAlchemy models (Camera, Event, Zone, Asset, etc.) |
| `app/database.py` | Async database setup, FTS5 tables |
| `app/routers/ws.py` | WebSocket broadcast + TelemetryBatcher + Amy event bridge |
| `app/routers/assets.py` | Autonomous asset management |
| `app/routers/targets_unified.py` | /api/targets — unified tracker API |
| `app/routers/scenarios.py` | /api/scenarios — behavioral test runner API |
| `app/ai/detector.py` | YOLO detection wrapper |
| `frontend/js/app.js` | Main app state, WebSocket, keyboard shortcuts |
| `frontend/js/amy.js` | Amy dashboard (thoughts, video, sensorium, chat) |
| `frontend/js/war.js` | War Room — Canvas 2D RTS tactical map |
| `frontend/js/assets.js` | Asset state + tactical map target rendering |
| `frontend/js/input.js` | Gamepad/keyboard unified input system |
| `examples/robot-template/` | Reference MQTT robot brain for real hardware |

## Environment Variables

See `.env.example` for full list. Key settings:
- `DATABASE_URL`: SQLite connection string
- `RECORDINGS_PATH`: Path to synced footage
- `NVR_HOST/NVR_USER/NVR_PASS`: NVR auto-discovery credentials
- `YOLO_MODEL`: Path to YOLOv8 weights
- `SIMULATION_ENABLED`: Enable simulation engine (default: true)
- `SIMULATION_LAYOUT`: Path to TritiumLevelFormat JSON
- `MQTT_ENABLED`: Enable MQTT bridge (default: false)
- `MQTT_HOST/MQTT_PORT`: MQTT broker address (default: localhost:1883)
- `MQTT_SITE_ID`: Site identifier in topic prefix (default: home)

## Testing

```bash
# Amy unit tests (572+ tests, 35 test files)
.venv/bin/python3 -m pytest tests/amy/ -m unit -v

# Playwright E2E tests (11 spec files)
cd tests/e2e && npx playwright test

# UI layout drift test (Playwright + OpenCV, 30s observation)
.venv/bin/python3 tests/ui/test_layout_drift.py

# Robot template tests
cd examples/robot-template && python -m pytest tests/

# Manual UI testing
# - Test all keyboard shortcuts (press ? for help)
# - Test gamepad navigation (connect Xbox/8BitDo controller)
# - Verify each view's controls work as documented
```

Key test files:
- `tests/amy/test_escalation.py` — 64 tests: threat ladder, zones, dispatch, events
- `tests/amy/test_mqtt_bridge.py` — 60+ tests: routing, publishing, edge cases
- `tests/amy/test_simulation_*.py` — Target, engine, loader, ambient spawner
- `tests/amy/test_target_tracker.py` — Unified registry, pruning, summary
- `tests/e2e/tests/war-room.spec.ts` — War Room Canvas 2D E2E tests

See [docs/UI-TESTING.md](docs/UI-TESTING.md) for the full methodology on detecting
and fixing visual UI regressions with Playwright and OpenCV.

## Running

```bash
# Development mode (hot reload)
./setup.sh dev

# Production mode
./setup.sh prod

# Or manually
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API Endpoints

### Core
- `GET /api/cameras` - List registered cameras
- `GET /api/videos/channels` - List channels with recordings
- `GET /api/videos/stream/{ch}/{date}/{file}` - Stream video
- `POST /api/ai/analyze` - Run AI analysis on video
- `GET /api/search/query` - Full-text search events
- `GET /api/zones` - List zones

### Amy
- `GET /api/amy/status` - Amy state, mood, nodes
- `GET /api/amy/thoughts` - SSE stream of consciousness
- `GET /api/amy/sensorium` - Temporal narrative + mood
- `POST /api/amy/chat` - Talk to Amy
- `POST /api/amy/command` - Send Lua action
- `GET /api/amy/nodes/{id}/video` - MJPEG from camera node

### Simulation + Targets
- `GET /api/amy/simulation/targets` - List simulation targets
- `POST /api/amy/simulation/spawn` - Spawn hostile target
- `DELETE /api/amy/simulation/targets/{id}` - Remove simulation target
- `GET /api/targets` - All tracked targets (unified registry)
- `GET /api/targets/hostiles` - Hostile targets only
- `GET /api/targets/friendlies` - Friendly targets only

### WebSocket
- `WS /ws/live` - Real-time updates + Amy events + sim telemetry batches

### MQTT Topics (see [docs/MQTT.md](docs/MQTT.md))
- `tritium/{site}/cameras/{id}/detections` - Camera YOLO boxes
- `tritium/{site}/robots/{id}/telemetry` - Robot position/battery
- `tritium/{site}/robots/{id}/command` - Dispatch/patrol/recall
- `tritium/{site}/amy/alerts` - Threat alerts
- `tritium/{site}/escalation/change` - Threat level changes

## Keyboard Shortcuts

Press `?` in the UI for full list. Main shortcuts:
- `G/P/D/Z/T/A/N/Y/W/S` - Switch views (Grid, Player, 3D, Zones, Targets, Assets, aNalytics, amY, War room, Scenarios)
- `1/2/3` - Grid size
- `/` - Focus search
- `ESC` - Close modals
- War Room: `O/T/S` modes (Observe, Tactical, Setup), `F` center on action, `R` reset camera

## Gamepad Support

See `docs/GAMEPAD.md` for full controller mapping. Supports:
- Xbox controllers (xinput)
- 8BitDo controllers (xinput mode)
- DualShock (via browser Gamepad API)

Navigation: D-Pad or left stick
Actions: A=Select, B=Back, X=Context, Y=Secondary

## MJPEG Video Panel Layout Rules

MJPEG `<img>` panels (PRIMARY OPTICS, scenario video) are sensitive to CSS
layout inflation.  The full fix requires **all three layers**:

1. **`.view-content`** — `flex: 1; min-height: 0; overflow: hidden;`
   Gives every view tab a definite height from the flex layout, not from
   content.  Without this, dynamic content (SSE thoughts, chat) inflates
   the entire page.  This was the root cause of the "image grows toward
   infinity" bug.

2. **Video container** — `overflow: clip` (NOT `hidden`).
   `clip` does not create a scroll container, so the browser cannot
   internally increment `scrollTop` on each MJPEG frame delivery.

3. **`<img>` element** — `position: absolute; inset: 0; width: 100%;
   height: 100%; object-fit: contain; display: block;`
   All properties are required.  `inset: 0` alone is NOT sufficient for
   replaced elements — without explicit `width`/`height`, the image
   renders at its natural dimensions (640x480).

**Debugging layout drift**: Run `tests/ui/test_layout_drift.py` — it uses
Playwright to capture 30 frames over 30s and fails if any element drifts
beyond 3px.  See [docs/UI-TESTING.md](docs/UI-TESTING.md).
