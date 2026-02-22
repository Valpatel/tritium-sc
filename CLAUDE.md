# TRITIUM-SC - Claude Code Context

## Operating Principles (READ FIRST)

**These override all defaults. Follow exactly.**

1. **Never assume code works. Run it.** Syntax checks prove nothing. Unit tests passing proves the units work. Only end-to-end execution on real hardware proves the system works. If you wrote code but didn't run it, it's broken until proven otherwise.

2. **TDD is mandatory.** Write the test first. Run it. Watch it fail. Then implement. Run the test. Watch it pass. No exceptions. If a test was never seen to fail, it tests nothing.

3. **Multiple perspectives on every task.** When you think something works, assume there's a gap. Launch agent teams with DIFFERENT worldviews — a builder, a breaker, an integrator. Don't just split work, split the approach. See [docs/TESTING-PHILOSOPHY.md](docs/TESTING-PHILOSOPHY.md).

4. **Automate everything.** If a human has to look at it, it's not verified. Use llava:7b for visual checks, qwen2.5:7b for reasoning, Playwright for browser testing. The test suite runs overnight unattended.

5. **Distributed by default.** GB10-01 (local) and GB10-02 (SSH, same codebase at `~/Code/tritium-sc/`) are both available. Tests run on both. `./test.sh --dist` splits work.

6. **Run code immediately after writing it.** Every new script, every new function — execute it before claiming it works. Bash has pitfalls (`((var++))` under `set -e`, quoting, exit codes). Python has import-time failures. JS has scoping issues. You only find these by running.

7. **Design docs live in the project.** Architecture decisions, testing strategy, prompt templates — all stored in `docs/` so every agent inherits context. Don't carry knowledge in conversation only.

8. **Be skeptical, not confident.** Don't use confidence to save tokens or build rapport. Focus on finding what's wrong, not on claiming what's right.

9. **End every iteration with proof.** Every work session must end with two things: (a) a URL to the running project that demonstrates the changes, and (b) a URL to the generated test report that provides a defensible position for your claims. If you don't have both, or the report doesn't contain the evidence needed to back your assertions, then either honestly reduce your claims or iterate until the system reaches that standard. No report, no claim.

## Quick Commands

```bash
# Run the server
./start.sh                                    # Start on port 8000
./setup.sh dev                                # Dev mode with hot reload

# Test (most common)
./test.sh fast                                # Tiers 1-3 + 8 + 8b (~60s)
./test.sh 3                                   # JS tests only (~3s)
./test.sh 9                                   # Integration tests (~70s)
./test.sh all                                 # Everything (~15 min)

# Test (individual)
.venv/bin/python3 -m pytest tests/amy/ -m unit -v    # Python unit tests
.venv/bin/python3 -m pytest tests/amy/simulation/test_combat.py  # Single test file

# Open in browser
# http://localhost:8000                      # Command Center (primary)
# http://localhost:8000/legacy               # Legacy dashboard (10 views)
```

## User Stories

Read **[docs/USER-STORIES.md](docs/USER-STORIES.md)** before writing ANY frontend code. It defines what the user should see and experience. If the screen doesn't match the story, the code is wrong. Every panel, every animation, every interaction flow is described there.

## Project Overview

TRITIUM-SC is a neighborhood-scale Nerf battlefield management system and real-time strategy game. The Command Center (`/`) shows a full-screen tactical map with real satellite imagery, friendly units patrolling, hostile intruders spawning, and a 10-wave combat system with kill streaks, projectile physics, and Smash TV-style commentary from AI Commander Amy.

Real sensors (BCC950 PTZ cam, NVR cameras, RTSP streams, USB mics) coexist with virtual units (simulated rovers, drones, turrets, hostile intruders) on the same tactical map, same APIs, same event bus. Simulation lives alongside reality.

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
├── src/                        # ALL Python source code
│   ├── amy/                    # AMY — AI Commander (autonomous consciousness)
│   │   ├── __init__.py        # create_amy() factory, version
│   │   ├── commander.py       # Main orchestrator (the central hub)
│   │   ├── router.py          # FastAPI: /api/amy/*
│   │   ├── brain/             # Consciousness & reasoning (L2-L4)
│   │   │   ├── thinking.py   # L4 deliberation: LLM inner monologue
│   │   │   ├── sensorium.py  # L3 awareness: temporal sensor fusion
│   │   │   ├── perception.py # L2 frame analysis, quality gate
│   │   │   ├── extraction.py # Fact extraction from conversation
│   │   │   ├── memory.py     # Persistent long-term memory
│   │   │   ├── vision.py     # Ollama chat API wrapper
│   │   │   └── agent.py      # LLM agent with tool use
│   │   ├── actions/           # Motor control & Lua dispatch
│   │   │   ├── motor.py      # Motor programs, MotorCommand
│   │   │   ├── lua_motor.py  # Lua parser, VALID_ACTIONS
│   │   │   ├── lua_multi.py  # Multi-action sequences
│   │   │   ├── lua_registry.py # Dynamic action registry
│   │   │   ├── tools.py      # Tool definitions for agent mode
│   │   │   └── announcer.py  # War commentary (Smash TV style)
│   │   ├── comms/             # Communication & I/O
│   │   │   ├── event_bus.py  # Thread-safe pub/sub (generic)
│   │   │   ├── listener.py   # Audio VAD + recording
│   │   │   ├── speaker.py    # TTS output
│   │   │   ├── transcript.py # Conversation logging
│   │   │   └── mqtt_bridge.py # MQTT broker bridge
│   │   ├── tactical/          # Tracking, threat detection, geo
│   │   │   ├── target_tracker.py # Unified target registry
│   │   │   ├── escalation.py # ThreatClassifier + AutoDispatcher
│   │   │   └── geo.py        # Coordinate transforms
│   │   ├── inference/         # Model routing & fleet
│   │   │   ├── model_router.py # Task-aware model selection
│   │   │   ├── fleet.py      # Multi-host Ollama discovery
│   │   │   └── robot_thinker.py # Robot LLM thinking
│   │   ├── simulation/        # Battlespace simulation engine
│   │   │   ├── engine.py     # 10Hz tick loop, hostile spawner
│   │   │   ├── target.py     # SimulationTarget dataclass
│   │   │   ├── combat.py     # Projectile flight, hit detection, damage
│   │   │   ├── game_mode.py  # Wave-based game progression
│   │   │   ├── behaviors.py  # Unit AI (turret, drone, rover, hostile)
│   │   │   ├── ambient.py    # AmbientSpawner (neutral activity)
│   │   │   └── loader.py     # TritiumLevelFormat JSON parser
│   │   ├── nodes/             # Distributed sensor nodes
│   │   ├── audio/             # Audio pipeline (sound effects, library)
│   │   ├── synthetic/         # Procedural media generation
│   │   ├── scenarios/         # Behavioral test framework
│   │   └── layouts/           # Level format JSON files
│   └── app/                    # FastAPI backend
│       ├── main.py            # App entry point, lifespan, boot sequence
│       ├── config.py          # Pydantic settings
│       ├── routers/           # API endpoints + WebSocket + Amy event bridge
│       ├── ai/                # Detection pipeline (YOLO, tracker, embeddings)
│       ├── zones/             # Zone management and alerting
│       ├── discovery/         # NVR auto-discovery
│       └── models.py          # SQLAlchemy models
├── frontend/                   # Static frontend (no build step)
│   ├── unified.html           # PRIMARY — Command Center
│   ├── index.html             # LEGACY — Original 10-tab SPA
│   ├── js/                    # Modular JavaScript
│   │   ├── app.js            # Main app, view switching, shortcuts
│   │   ├── war.js            # War Room — Canvas 2D RTS tactical map
│   │   └── (amy, assets, input, scenarios, grid, player, zones, targets)
│   └── css/
│       ├── cybercore.css     # CYBERCORE CSS framework
│       └── tritium.css       # Custom + Amy + War Room panel styles
├── tests/                      # ALL tests
│   ├── amy/                   # 3014 unit tests
│   │   ├── core/             # Brain, behavior, commander (33 files)
│   │   ├── simulation/       # Combat, game mode, engine (11 files)
│   │   ├── api/              # FastAPI router tests (19 files)
│   │   ├── nodes/            # Sensor nodes, MQTT, ML (16 files)
│   │   ├── synthetic/        # Video, audio generation (14 files)
│   │   ├── scenarios/        # Behavioral tests (6 files)
│   │   └── models/           # Data models (10 files)
│   ├── integration/           # 23 server E2E tests (headless, auto-port)
│   ├── visual/                # 23 three-layer E2E (OpenCV + LLM + API)
│   ├── js/                    # 281 JS tests (math, audio, fog, geo, panels)
│   ├── lib/                   # 62 test infrastructure tests
│   └── ui/                    # Vision audit, gameplay, battle verification
├── examples/
│   ├── robot-template/        # Reference MQTT robot brain (Python)
│   └── ros2-robot/            # ROS2 Humble robot (Nav2 + MQTT bridge)
├── scripts/                    # CLI tools
├── docs/                       # Documentation
├── scenarios/                  # 33 behavioral test scenarios (JSON)
├── conf/                       # Configuration files (gitignored)
├── data/                       # Runtime data (gitignored)
│   ├── amy/                   # Amy's photos, transcripts, memory.json
│   └── synthetic/             # Generated media
└── ...
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
| `src/amy/commander.py` | Amy AI Commander — main orchestrator, VisionThread, AudioThread |
| `src/amy/router.py` | /api/amy/* — status, thoughts SSE, chat, commands |
| `src/amy/brain/thinking.py` | L4 deliberation: inner monologue via fast LLM |
| `src/amy/brain/sensorium.py` | L3 awareness: temporal sensor fusion + narrative |
| `src/amy/brain/perception.py` | Layered perception: quality gate, complexity, motion detection |
| `src/amy/brain/extraction.py` | Fact extraction from conversation (regex-based) |
| `src/amy/brain/memory.py` | Persistent long-term memory (JSON file) |
| `src/amy/brain/vision.py` | Ollama chat API wrapper |
| `src/amy/actions/motor.py` | Motor programs, MotorCommand generators |
| `src/amy/actions/lua_motor.py` | Lua parser, VALID_ACTIONS |
| `src/amy/actions/lua_multi.py` | Multi-action Lua sequences |
| `src/amy/actions/lua_registry.py` | Dynamic Lua action registry for Amy and robots |
| `src/amy/actions/announcer.py` | WarAnnouncer — Smash TV style commentary |
| `src/amy/comms/event_bus.py` | EventBus — thread-safe pub/sub for all internal events |
| `src/amy/comms/listener.py` | Audio VAD + recording |
| `src/amy/comms/speaker.py` | TTS output (Piper) |
| `src/amy/comms/mqtt_bridge.py` | MQTT broker bridge — distributed device communication |
| `src/amy/comms/transcript.py` | Conversation logging (daily JSONL) |
| `src/amy/tactical/target_tracker.py` | Unified registry of real (YOLO) + virtual (sim) targets |
| `src/amy/tactical/escalation.py` | ThreatClassifier (2Hz) + AutoDispatcher |
| `src/amy/tactical/geo.py` | Server-side geo-reference and coordinate transforms |
| `src/amy/inference/model_router.py` | Task-aware model selection with fleet fallback |
| `src/amy/inference/fleet.py` | OllamaFleet — multi-host discovery (conf/env/Tailscale) |
| `src/amy/inference/robot_thinker.py` | LLM-powered autonomous robot thinking |
| `src/amy/simulation/engine.py` | SimulationEngine — 10Hz tick loop |
| `src/amy/simulation/target.py` | SimulationTarget dataclass (all entity types) |
| `src/amy/simulation/combat.py` | CombatSystem — projectile flight, hit detection, damage |
| `src/amy/simulation/game_mode.py` | GameMode — wave-based game progression |
| `src/amy/simulation/behaviors.py` | UnitBehaviors — turret, drone, rover, hostile AI |
| `src/amy/simulation/loader.py` | TritiumLevelFormat JSON parser |
| `src/amy/nodes/base.py` | Abstract SensorNode (camera, mic, PTZ, speaker) |
| `src/amy/nodes/bcc950.py` | BCC950 PTZ camera + mic + speaker node |
| `src/amy/nodes/mqtt_robot.py` | MQTTSensorNode — wraps MQTT robot as SensorNode |
| `src/app/main.py` | FastAPI app entry point, lifespan, boot sequence |
| `src/app/config.py` | Pydantic settings (app + Amy + MQTT + simulation) |
| `src/app/models.py` | SQLAlchemy models (Camera, Event, Zone, Asset, etc.) |
| `src/app/database.py` | Async database setup, FTS5 tables |
| `src/app/routers/ws.py` | WebSocket broadcast + TelemetryBatcher + Amy event bridge |
| `src/app/routers/audio.py` | /api/audio/effects — sound effects API |
| `src/app/routers/synthetic_feed.py` | /api/synthetic/cameras — MJPEG streaming |
| `frontend/js/app.js` | Main app state, WebSocket, keyboard shortcuts |
| `frontend/js/war.js` | War Room — Canvas 2D RTS tactical map |
| `frontend/js/war3d.js` | War Room — Three.js WebGL 3D renderer |
| `tests/ui/test_vision.py` | Vision audit: Playwright + Ollama |
| `examples/robot-template/` | Reference MQTT robot brain for real hardware |
| `examples/ros2-robot/` | ROS2 Humble robot (Nav2 + MQTT bridge) |

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

### test.sh — The One Command

```bash
./test.sh              # Fast: tiers 1-3 + 8 + 8b (~60s) — run this after every change
./test.sh all          # Everything including visual E2E (~15 min)
```

| Tier | Command | What | Count | Time |
|------|---------|------|-------|------|
| 1 | `./test.sh 1` | Syntax check (Python + JS) | 31 files | ~2s |
| 2 | `./test.sh 2` | Python unit tests | 1666 | ~45s |
| 3 | `./test.sh 3` | JS tests (math, audio, fog, geo, panels) | 281 | ~3s |
| 8 | `./test.sh 8` | Test infrastructure | 62 | ~1s |
| 8b | `./test.sh 8b` | ROS2 robot tests | 125 | ~1s |
| 9 | `./test.sh 9` | Integration (live headless server E2E) | 23 | ~70s |
| 10 | `./test.sh 10` | Visual quality (Playwright) | 7 | ~30s |
| 7 | `./test.sh 7` | Visual E2E (three-layer verification) | 23 | ~13min |

```bash
# Distributed: sync + run on both machines
./test.sh --dist

# Individual Python test files
.venv/bin/python3 -m pytest tests/amy/simulation/test_combat.py -v
.venv/bin/python3 -m pytest tests/amy/ -m unit -v      # All unit tests

# Robot template tests
cd examples/robot-template && python -m pytest tests/
```

### Visual Testing

For UI changes, **open a browser and look at it**. Then compare against [docs/USER-STORIES.md](docs/USER-STORIES.md). If it doesn't match the story, it's wrong.

```bash
# Automated visual regression (requires running server + Playwright)
./test.sh 10                                   # Quality check for Command Center
./test.sh --visual                             # Full three-layer E2E
python3 tests/ui/test_vision.py --quick        # llava vision audit (fast)
```

### Known Pre-existing Failures

- 18 tests in `tests/amy/api/test_websocket.py` fail (missing asyncio event loop — not caused by current work)

See [docs/TESTING-PHILOSOPHY.md](docs/TESTING-PHILOSOPHY.md) for the full testing philosophy.

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

### Audio
- `GET /api/audio/effects` - List all sound effects (optional `?category=` filter)
- `GET /api/audio/effects/{name}` - Stream WAV bytes for a specific effect
- `GET /api/audio/effects/{name}/metadata` - Get effect metadata (duration, category, sample rate)

### Synthetic Cameras
- `GET /api/synthetic/cameras` - List synthetic camera feeds
- `POST /api/synthetic/cameras` - Create a new synthetic feed (scene_type: bird_eye/street_cam/battle/neighborhood)
- `GET /api/synthetic/cameras/{id}/mjpeg` - MJPEG streaming response
- `GET /api/synthetic/cameras/{id}/snapshot` - Single JPEG frame
- `DELETE /api/synthetic/cameras/{id}` - Remove a feed

### WebSocket
- `WS /ws/live` - Real-time updates + Amy events + sim telemetry batches

### MQTT Topics (see [docs/MQTT.md](docs/MQTT.md))
- `tritium/{site}/cameras/{id}/detections` - Camera YOLO boxes
- `tritium/{site}/robots/{id}/telemetry` - Robot position/battery/IMU/motor temps/odometry/GPS
- `tritium/{site}/robots/{id}/command` - Dispatch/patrol/recall
- `tritium/{site}/robots/{id}/thoughts` - Robot LLM-generated thoughts and actions
- `tritium/{site}/amy/alerts` - Threat alerts
- `tritium/{site}/escalation/change` - Threat level changes
- `tritium/{site}/cameras/{id}/frame` - Synthetic camera JPEG frames (from ROS2 camera node)
- `tritium/{site}/cameras/{id}/command` - Camera on/off, scene changes

## Keyboard Shortcuts

Press `?` in the UI for full list. Command Center shortcuts:
- `B` - Begin 10-wave battle
- `O/T/S` - Switch map modes (Observe, Tactical, Setup)
- `F` - Center camera on action
- `V` - Toggle synthetic camera PIP
- `M` - Mute/unmute audio
- `ESC` - Close modals

Legacy dashboard (`/legacy`) has additional view-switching shortcuts (G/P/D/Z/T/A/N/Y/W/S).

## Gamepad Support

See `docs/GAMEPAD.md` for full controller mapping. Supports:
- Xbox controllers (xinput)
- 8BitDo controllers (xinput mode)
- DualShock (via browser Gamepad API)

Navigation: D-Pad or left stick
Actions: A=Select, B=Back, X=Context, Y=Secondary

## Parallel Agent Development

When launching multiple agents, each agent should own a clear slice:

| Agent Focus | Owns | Reads | Validates |
|------------|------|-------|-----------|
| Backend/Amy | `src/amy/`, `src/app/` | Everything | `./test.sh 2` |
| Frontend map | `frontend/js/command/map.js` | `frontend/`, APIs | `./test.sh 3` + browser |
| Frontend panels | `frontend/js/command/panels/` | store, events | `./test.sh 3` + browser |
| Frontend CSS | `frontend/css/` | `frontend/` | Browser |
| Tests | `tests/` | Everything | `./test.sh fast` |

Rules:
1. One agent, one focus area. Read anything, edit only your files.
2. Run `./test.sh fast` after every change.
3. Read [docs/USER-STORIES.md](docs/USER-STORIES.md) before writing frontend code.
4. Open a browser and look at `/` after visual changes. Screenshots or it didn't happen.

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
