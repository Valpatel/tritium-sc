# TRITIUM-SC - Claude Code Context

## Project Overview

TRITIUM-SC is a Nerf war battlespace management platform with an autonomous AI Commander (Amy). Inspired by Masanobu Fukuoka's "One-Straw Revolution" — this is a garden of diverse digital life where AI flourishes naturally and machines act independently, not a fortress of centralized control.

Amy is an autonomous consciousness with 4 cognitive layers (reflex → instinct → awareness → deliberation). She sees through cameras, hears through mics, thinks in continuous inner monologue, and acts when she decides to. Assets (Nerf turrets, rovers) are independent agents.

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy, aiosqlite
- **Frontend**: Vanilla JavaScript, Three.js, CYBERCORE CSS (no frameworks)
- **Database**: SQLite with FTS5 for full-text search
- **AI/ML**: YOLOv8, ByteTrack (object tracking), PyTorch/CUDA
- **Streaming**: go2rtc integration for RTSP/WebRTC

## Key Directories

```
tritium-sc/
├── amy/                    # AMY — AI Commander (autonomous consciousness)
│   ├── commander.py       # Main orchestrator, event loop
│   ├── sensorium.py       # L3 awareness: temporal sensor fusion
│   ├── thinking.py        # L4 deliberation: inner monologue
│   ├── nodes/             # Distributed sensor nodes (BCC950, IP cam, virtual)
│   ├── router.py          # FastAPI: /api/amy/*
│   └── (agent, listener, speaker, vision, motor, memory, tools, lua_motor)
├── app/                    # FastAPI backend
│   ├── routers/           # API endpoints + WebSocket + Amy event bridge
│   ├── ai/                # Detection pipeline (YOLO, tracker, embeddings)
│   ├── zones/             # Zone management and alerting
│   ├── discovery/         # NVR auto-discovery
│   └── models.py          # SQLAlchemy models
├── frontend/              # Static frontend (no build step)
│   ├── index.html         # Main SPA shell (8 views incl. AMY)
│   ├── js/                # Modular JavaScript
│   │   ├── app.js        # Main app, view switching, shortcuts
│   │   ├── amy.js        # Amy dashboard (thoughts, video, chat)
│   │   ├── input.js      # Input handling (keyboard + gamepad)
│   │   └── (grid, player, zones, targets, assets, analytics)
│   └── css/
│       ├── cybercore.css # CYBERCORE CSS framework
│       └── tritium.css   # Custom + Amy panel styles
├── docs/                  # Documentation
├── tests/                 # Test suite
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
| `amy/commander.py` | Amy AI Commander — main orchestrator, event loop |
| `amy/sensorium.py` | L3 awareness: temporal sensor fusion + narrative |
| `amy/thinking.py` | L4 deliberation: inner monologue via fast LLM |
| `amy/nodes/base.py` | Abstract SensorNode (camera, mic, PTZ, speaker) |
| `amy/nodes/bcc950.py` | BCC950 PTZ camera + mic + speaker node |
| `amy/router.py` | /api/amy/* — status, thoughts SSE, chat, commands |
| `app/main.py` | FastAPI app entry point, lifespan, Amy startup |
| `app/config.py` | Pydantic settings (app + Amy config) |
| `app/models.py` | SQLAlchemy models (Camera, Event, Zone, Asset, etc.) |
| `app/database.py` | Async database setup, FTS5 tables |
| `app/routers/ws.py` | WebSocket broadcast + Amy event bridge |
| `app/routers/assets.py` | Autonomous asset management |
| `app/ai/detector.py` | YOLO detection wrapper |
| `frontend/js/app.js` | Main app state, WebSocket, keyboard shortcuts |
| `frontend/js/amy.js` | Amy dashboard (thoughts, video, sensorium, chat) |
| `frontend/js/input.js` | Gamepad/keyboard unified input system |

## Environment Variables

See `.env.example` for full list. Key settings:
- `DATABASE_URL`: SQLite connection string
- `RECORDINGS_PATH`: Path to synced footage
- `NVR_HOST/NVR_USER/NVR_PASS`: NVR auto-discovery credentials
- `YOLO_MODEL`: Path to YOLOv8 weights

## Testing

```bash
# Run Python tests
python -m pytest tests/

# Manual UI testing
# - Test all keyboard shortcuts (press ? for help)
# - Test gamepad navigation (connect Xbox/8BitDo controller)
# - Verify each view's controls work as documented
```

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

- `GET /api/cameras` - List registered cameras
- `GET /api/videos/channels` - List channels with recordings
- `GET /api/videos/stream/{ch}/{date}/{file}` - Stream video
- `POST /api/ai/analyze` - Run AI analysis on video
- `GET /api/search/query` - Full-text search events
- `GET /api/zones` - List zones
- `GET /api/amy/status` - Amy state, mood, nodes
- `GET /api/amy/thoughts` - SSE stream of consciousness
- `GET /api/amy/sensorium` - Temporal narrative + mood
- `POST /api/amy/chat` - Talk to Amy
- `POST /api/amy/command` - Send Lua action
- `GET /api/amy/nodes/{id}/video` - MJPEG from camera node
- `WS /ws/live` - WebSocket for real-time updates + Amy events

## Keyboard Shortcuts

Press `?` in the UI for full list. Main shortcuts:
- `G/P/D/Z/T/A/N/Y` - Switch views (Grid, Player, 3D, Zones, Targets, Assets, aNalytics, amY)
- `1/2/3` - Grid size
- `/` - Focus search
- `ESC` - Close modals

## Gamepad Support

See `docs/GAMEPAD.md` for full controller mapping. Supports:
- Xbox controllers (xinput)
- 8BitDo controllers (xinput mode)
- DualShock (via browser Gamepad API)

Navigation: D-Pad or left stick
Actions: A=Select, B=Back, X=Context, Y=Secondary
