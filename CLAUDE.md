# TRITIUM-SC - Claude Code Context

## Project Overview

TRITIUM-SC (Security Central) is a cyberpunk-themed security camera intelligence platform that combines AI-powered detection with a futuristic Three.js + CYBERCORE CSS interface. Inspired by Frigate and Viseron, it features motion-first detection, YOLO inference, and comprehensive event search.

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy, aiosqlite
- **Frontend**: Vanilla JavaScript, Three.js, CYBERCORE CSS (no frameworks)
- **Database**: SQLite with FTS5 for full-text search
- **AI/ML**: YOLOv8, ByteTrack (object tracking), PyTorch/CUDA
- **Streaming**: go2rtc integration for RTSP/WebRTC

## Key Directories

```
sec-cameras/
├── app/                    # FastAPI backend
│   ├── routers/           # API endpoints
│   ├── ai/                # Detection pipeline (YOLO, tracker, embeddings)
│   ├── zones/             # Zone management and alerting
│   ├── discovery/         # NVR auto-discovery
│   └── models.py          # SQLAlchemy models
├── frontend/              # Static frontend (no build step)
│   ├── index.html         # Main SPA shell
│   ├── js/                # Modular JavaScript
│   │   ├── app.js        # Main app, view switching, shortcuts
│   │   ├── input.js      # Input handling (keyboard + gamepad)
│   │   ├── grid.js       # 3D property view (Three.js)
│   │   ├── player.js     # Video playback
│   │   ├── zones.js      # Zone management UI
│   │   ├── targets.js    # Detection gallery
│   │   ├── assets.js     # Autonomous unit control
│   │   └── analytics.js  # Detection statistics
│   └── css/
│       ├── cybercore.css # CYBERCORE CSS framework
│       └── tritium.css   # Custom styles
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
| `app/main.py` | FastAPI app entry point, lifespan, routes |
| `app/config.py` | Pydantic settings from environment |
| `app/models.py` | SQLAlchemy models (Camera, Event, Zone, Asset, etc.) |
| `app/database.py` | Async database setup, FTS5 tables |
| `app/routers/videos.py` | Video browsing, streaming, thumbnails |
| `app/routers/ai.py` | AI analysis endpoints |
| `app/routers/zones.py` | Zone CRUD and event queries |
| `app/routers/search.py` | Full-text search, analytics |
| `app/routers/assets.py` | Autonomous asset management |
| `app/ai/detector.py` | YOLO detection wrapper |
| `app/ai/tracker.py` | ByteTrack object tracking |
| `frontend/js/app.js` | Main app state, WebSocket, keyboard shortcuts |
| `frontend/js/input.js` | Gamepad/keyboard unified input system |
| `frontend/js/grid.js` | Three.js 3D property visualization |

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
- `GET /api/videos/channels/{ch}/dates` - Dates with recordings
- `GET /api/videos/stream/{ch}/{date}/{file}` - Stream video
- `POST /api/ai/analyze` - Run AI analysis on video
- `GET /api/search/query` - Full-text search events
- `GET /api/zones` - List zones
- `WS /ws/live` - WebSocket for real-time updates

## Keyboard Shortcuts

Press `?` in the UI for full list. Main shortcuts:
- `G/P/D/Z/T/A/N` - Switch views (Grid, Player, 3D, Zones, Targets, Assets, aNalytics)
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
