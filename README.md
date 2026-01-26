```
████████╗██████╗ ██╗████████╗██╗██╗   ██╗███╗   ███╗      ███████╗ ██████╗
╚══██╔══╝██╔══██╗██║╚══██╔══╝██║██║   ██║████╗ ████║      ██╔════╝██╔════╝
   ██║   ██████╔╝██║   ██║   ██║██║   ██║██╔████╔██║█████╗███████╗██║
   ██║   ██╔══██╗██║   ██║   ██║██║   ██║██║╚██╔╝██║╚════╝╚════██║██║
   ██║   ██║  ██║██║   ██║   ██║╚██████╔╝██║ ╚═╝ ██║      ███████║╚██████╗
   ╚═╝   ╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝     ╚═╝      ╚══════╝ ╚═════╝
```

<div align="center">

**[ SECURITY CAMERA INTELLIGENCE PLATFORM ]**

`▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀`

*Real-time object tracking • Historical analysis • Human-in-the-loop learning*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-00f0ff?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-ff2a6d?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![YOLO](https://img.shields.io/badge/YOLO-v8-05ffa1?style=flat-square)](https://ultralytics.com)
[![License](https://img.shields.io/badge/license-MIT-fcee0a?style=flat-square)](LICENSE)

</div>

---

## ⚡ SYSTEM OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   ╔═══════════════════════════════════════════════════════════════════╗    │
│   ║                    T R I T I U M - S C                            ║    │
│   ║            SECURITY CAMERA INTELLIGENCE PLATFORM                  ║    │
│   ╚═══════════════════════════════════════════════════════════════════╝    │
│                                                                             │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌───────────┐  │
│   │   CAMERA    │───▶│   DETECT    │───▶│    TRACK    │───▶│  IDENTIFY │  │
│   │   STREAMS   │    │  (YOLOv8)   │    │ (ByteTrack) │    │  (HUMAN)  │  │
│   └─────────────┘    └─────────────┘    └─────────────┘    └───────────┘  │
│         │                  │                  │                  │         │
│         ▼                  ▼                  ▼                  ▼         │
│   ┌─────────────────────────────────────────────────────────────────────┐ │
│   │                     INTELLIGENCE DATABASE                           │ │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │ │
│   │  │ TIMELINE │  │ THUMBNAILS│  │  LABELS  │  │ FEEDBACK HISTORY │   │ │
│   │  │  EVENTS  │  │ + VECTORS │  │ + MERGES │  │ (REINFORCEMENT)  │   │ │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘   │ │
│   └─────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 MISSION OBJECTIVES

### REAL-TIME THREAT DETECTION
```
┌──────────────────────────────────────────────────────────────┐
│  LIVE STREAM ──▶ MOTION ──▶ YOLO ──▶ BYTETRACK ──▶ ALERT   │
│                   │          │          │           │        │
│                   ▼          ▼          ▼           ▼        │
│               < 50ms     < 30ms     < 10ms      INSTANT     │
│                                                              │
│  TARGET CLASSES:                                             │
│  ├── 👤 PERSON    (pedestrians, intruders, delivery)        │
│  ├── 🚗 VEHICLE   (cars, trucks, vans, motorcycles)         │
│  ├── 🚚 DELIVERY  (UPS, FedEx, Amazon, USPS)                │
│  ├── 🚲 BICYCLE   (cyclists, scooters)                      │
│  └── 🐕 ANIMAL    (dogs, cats, wildlife)                    │
└──────────────────────────────────────────────────────────────┘
```

### HISTORICAL INTELLIGENCE
```
╔══════════════════════════════════════════════════════════════╗
║  QUERY: "Show me all people who visited last Tuesday"        ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  TIMELINE: 2026-01-21                                        ║
║  ════════════════════════════════════════════════            ║
║  06:00 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░             ║
║  08:00 ░░░░████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  [2 people] ║
║  10:00 ░░░░░░░░░░░░██░░░░░░░░░░░░░░░░░░░░░░░░░░  [1 person] ║
║  12:00 ░░░░░░░░░░░░░░░░░░████████░░░░░░░░░░░░░░  [4 people] ║
║  14:00 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░             ║
║  16:00 ░░░░░░░░░░░░░░░░░░░░░░░░░░██░░░░░░░░░░░░  [1 person] ║
║  18:00 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░             ║
║                                                              ║
║  UNIQUE INDIVIDUALS: 6    TOTAL APPEARANCES: 8               ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 🧠 HUMAN-IN-THE-LOOP LEARNING

TRITIUM-SC doesn't just detect—it **learns from you**.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     CONSOLIDATION INTERFACE                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   DETECTED VEHICLES (24 thumbnails)                                 │
│   ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐                 │
│   │ 🚗  │ │ 🚗  │ │ 🚗  │ │ 🚙  │ │ 🚗  │ │ 🚗  │                 │
│   │ #1  │ │ #2  │ │ #3  │ │ #4  │ │ #5  │ │ #6  │                 │
│   └──┬──┘ └──┬──┘ └──┬──┘ └─────┘ └──┬──┘ └──┬──┘                 │
│      │       │       │               │       │                      │
│      └───────┴───────┴───────────────┴───────┘                      │
│                      │                                              │
│                      ▼                                              │
│              ┌──────────────┐                                       │
│              │  SAME CAR    │  ◀── USER MERGES                     │
│              │  "My Honda"  │  ◀── USER LABELS                     │
│              └──────────────┘                                       │
│                      │                                              │
│                      ▼                                              │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  FEEDBACK LOGGED FOR REINFORCEMENT LEARNING                 │  │
│   │  ├── merge_action: [#1, #2, #3, #5, #6] → "my_honda"       │  │
│   │  ├── visual_similarity: 0.94                                │  │
│   │  ├── position_pattern: "driveway_spot_1"                    │  │
│   │  └── timestamp: 2026-01-25T18:42:07Z                        │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Feedback Types Captured

| Action | Purpose | Future Use |
|--------|---------|------------|
| **MERGE** | "These are the same vehicle" | Train ReID embeddings |
| **LABEL** | "This is the mailman" | Named entity recognition |
| **CORRECT** | "This is a truck, not a car" | Fine-tune detector |
| **REJECT** | "This is a false positive" | Improve confidence thresholds |

---

## 🌐 3D PROPERTY VISUALIZATION

```
                        ╔═══════════════════════════════════╗
                        ║   PROPERTY MAP - BIRD'S EYE VIEW  ║
                        ╚═══════════════════════════════════╝

                                    N
                                    ▲
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
               ◄────┤    [CAM 1]    │    [CAM 2]    ├────►
              W     │       ◢       │       ◣       │     E
                    │        ╲     │     ╱         │
                    │         ╲    │    ╱          │
                    │    ┌─────────────────┐       │
                    │    │                 │       │
                    │    │     HOUSE       │       │
                    │    │                 │       │
                    │    └─────────────────┘       │
                    │         ╱    │    ╲          │
                    │        ╱     │     ╲         │
                    │       ◥      │      ◤        │
                    │    [CAM 3]   │   [CAM 4]     │
                    │              │               │
                    └──────────────┼───────────────┘
                                   │
                                   ▼
                                   S

    ◢◣◤◥ = Camera field of view
    [  ] = Draggable camera position
    ──── = Property boundary
```

**Features:**
- 📍 Drag cameras to match real-world positions
- 👁️ View cones show camera coverage
- 🖼️ Live preview thumbnails on each camera card
- 💾 Positions persist across sessions
- 🗺️ *Coming soon: Satellite imagery overlay*

---

## 🔧 QUICK START

```bash
# Clone the repository
git clone git@github.com:mvalancy/tritium-sc.git
cd tritium-sc

# Run setup
./setup.sh install    # Create venv + install dependencies
./setup.sh ml         # Install PyTorch + YOLO (downloads models)

# Configure environment
cp .env.example .env
# Edit .env with your NVR credentials

# Launch
./setup.sh dev        # Development mode with auto-reload
# or
./setup.sh prod       # Production mode
```

**Access the dashboard:** http://localhost:8000

---

## 📡 API ENDPOINTS

```
┌────────────────────────────────────────────────────────────────────┐
│  TRITIUM-SC API v0.1.0                                             │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  CAMERAS                                                           │
│  ├── GET  /api/cameras              List all cameras               │
│  ├── GET  /api/cameras/{id}         Get camera details             │
│  └── GET  /api/discovery/scan       Discover NVR cameras           │
│                                                                    │
│  VIDEOS                                                            │
│  ├── GET  /api/videos/channels      List channels with recordings  │
│  ├── GET  /api/videos/{ch}/dates    List dates for channel         │
│  ├── GET  /api/videos/{ch}/{date}   List videos for date           │
│  ├── GET  /api/videos/stream/...    Stream video file              │
│  └── GET  /api/videos/thumbnail/... Get video thumbnail            │
│                                                                    │
│  AI ANALYSIS                                                       │
│  ├── POST /api/ai/analyze           Start day analysis             │
│  ├── GET  /api/ai/analyze/{id}      Check analysis status          │
│  ├── GET  /api/ai/timeline/{ch}/{d} Get analyzed timeline          │
│  ├── GET  /api/ai/detect/frame/...  Detect on single frame         │
│  └── GET  /api/ai/status            AI module status (GPU info)    │
│                                                                    │
│  SEARCH & INTELLIGENCE                                             │
│  ├── GET  /api/search/people        List detected people           │
│  ├── GET  /api/search/vehicles      List detected vehicles         │
│  ├── GET  /api/search/thumbnail/{id} Get detection thumbnail       │
│  ├── GET  /api/search/similar/{id}  Find similar objects           │
│  ├── POST /api/search/merge         Merge duplicate detections     │
│  ├── POST /api/search/label         Label an object                │
│  ├── POST /api/search/feedback      Submit correction feedback     │
│  └── GET  /api/search/stats         Detection statistics           │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 🏗️ ARCHITECTURE

```
tritium-sc/
├── app/
│   ├── ai/
│   │   ├── detector.py      # YOLO object detection
│   │   ├── tracker.py       # ByteTrack integration
│   │   ├── analyzer.py      # Video analysis pipeline
│   │   ├── mapper.py        # Timeline & content mapping
│   │   ├── thumbnails.py    # Detection thumbnail extraction
│   │   └── embeddings.py    # Visual similarity (CLIP)
│   ├── routers/
│   │   ├── cameras.py       # Camera CRUD
│   │   ├── videos.py        # Video browsing & streaming
│   │   ├── ai.py            # Analysis endpoints
│   │   ├── search.py        # Search & labeling
│   │   └── discovery.py     # NVR auto-discovery
│   ├── discovery/
│   │   └── nvr.py           # Reolink NVR API client
│   ├── main.py              # FastAPI application
│   ├── config.py            # Pydantic settings
│   ├── database.py          # Async SQLite + FTS5
│   └── models.py            # SQLAlchemy models
├── frontend/
│   ├── index.html           # Main SPA
│   ├── css/
│   │   ├── cybercore.css    # Cyberpunk effects
│   │   └── tritium.css      # Custom styles
│   └── js/
│       ├── app.js           # Main application
│       ├── grid.js          # Three.js 3D view
│       └── player.js        # Video player
└── tests/
```

---

## 🎨 TECH STACK

```
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║   BACKEND                          FRONTEND                      ║
║   ════════                         ════════                      ║
║   ▪ Python 3.11+                   ▪ Vanilla JS (no framework)   ║
║   ▪ FastAPI                        ▪ Three.js (3D rendering)     ║
║   ▪ SQLAlchemy + aiosqlite         ▪ CYBERCORE CSS               ║
║   ▪ Pydantic                       ▪ JetBrains Mono font         ║
║                                                                  ║
║   AI/ML                            INTEGRATIONS                  ║
║   ═════                            ════════════                  ║
║   ▪ Ultralytics YOLOv8             ▪ Reolink NVR API             ║
║   ▪ ByteTrack (multi-object)       ▪ RTSP streams                ║
║   ▪ OpenCV                         ▪ MQTT (planned)              ║
║   ▪ PyTorch + CUDA                 ▪ Home Assistant (planned)    ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 🚀 ROADMAP

```
PHASE 1 ████████████████████ COMPLETE
├── Cyberpunk UI shell
├── Video browsing by channel/date
├── YOLO object detection
├── ByteTrack unique counting
└── Thumbnail extraction

PHASE 2 ████████░░░░░░░░░░░░ IN PROGRESS
├── Person/vehicle search UI
├── Manual merge & labeling
├── Feedback collection
└── 3D property editor

PHASE 3 ░░░░░░░░░░░░░░░░░░░░ PLANNED
├── Live RTSP stream analysis
├── Real-time WebSocket alerts
├── Satellite imagery overlay
└── Zone-based alerting

PHASE 4 ░░░░░░░░░░░░░░░░░░░░ FUTURE
├── ReID model training from feedback
├── Delivery truck classification
├── Cross-camera tracking
├── Natural language search
└── MQTT/Home Assistant integration
```

---

## 📜 LICENSE

MIT License - See [LICENSE](LICENSE) for details.

---

<div align="center">

```
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║   "THE FUTURE OF HOME SECURITY IS INTELLIGENT, NOT INTRUSIVE" ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

**Built with 🔋 TRITIUM power**

*Designed for privacy-conscious homeowners who want AI-powered security without cloud dependencies.*

</div>
