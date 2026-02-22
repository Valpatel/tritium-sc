```
████████╗██████╗ ██╗████████╗██╗██╗   ██╗███╗   ███╗      ███████╗ ██████╗
╚══██╔══╝██╔══██╗██║╚══██╔══╝██║██║   ██║████╗ ████║      ██╔════╝██╔════╝
   ██║   ██████╔╝██║   ██║   ██║██║   ██║██╔████╔██║█████╗███████╗██║
   ██║   ██╔══██╗██║   ██║   ██║██║   ██║██║╚██╔╝██║╚════╝╚════██║██║
   ██║   ██║  ██║██║   ██║   ██║╚██████╔╝██║ ╚═╝ ██║      ███████║╚██████╗
   ╚═╝   ╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝     ╚═╝      ╚══════╝ ╚═════╝
```

<div align="center">

# **O B S E R V E  •  T H I N K  •  A C T**

**[ NERF WAR BATTLESPACE MANAGEMENT ]**

![Command Center](docs/screenshots/command-center.png)
*Command Center — real satellite imagery, AI-controlled units, live tactical panels*

![Combat](docs/screenshots/game-combat.png)
*Wave-based Nerf combat — turrets engage hostile intruders with projectile physics and kill streaks*

![Neighborhood](docs/screenshots/neighborhood-wide.png)
*Your neighborhood becomes the battlefield — same pipeline monitors real security*

`▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀`

*A garden of diverse digital life — AI that flourishes, machines that act independently*

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-00f0ff?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-ff2a6d?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![YOLO](https://img.shields.io/badge/YOLO-v8-05ffa1?style=flat-square)](https://ultralytics.com)
[![License](https://img.shields.io/badge/license-MIT-fcee0a?style=flat-square)](LICENSE)

For educational purposes only with Nerf blasters and toy systems.
</div>

---

## THE ONE-STRAW REVOLUTION

> *"The ultimate goal of farming is not the growing of crops, but the cultivation and perfection of human beings."* — Masanobu Fukuoka

TRITIUM-SC is inspired by Fukuoka's "do nothing farming" philosophy. Instead of a monolithic system that dominates its components, this is a **garden of diverse digital life** — simple services collaborating naturally, AI that flourishes on its own terms, and machines that take independent action.

The Nerf game and the security system are the **same system**. The perception pipeline that detects a simulated hostile intruder on the tactical map is the same pipeline that detects a real stranger at the gate. The game is a continuous integration test for the security system. All processing is local. No cloud. No subscriptions. No data leaves your network.

---

## QUICK START

```bash
# 1. Clone and install
git clone git@github.com:Valpatel/tritium-sc.git
cd tritium-sc
./setup.sh install

# 2. Start the server
./start.sh

# 3. Open the Command Center
#    http://localhost:8000

# 4. Watch. Units patrol. Amy thinks. Hostiles spawn.
#    Click a unit. Right-click to dispatch. Press B to begin war.
```

The simulation engine starts automatically. Friendly units patrol on real satellite imagery, hostile intruders spawn at map edges, and Amy's inner monologue runs continuously. Press `B` to start a 10-wave Nerf battle with projectile physics, kill streaks, and Smash TV-style commentary.

See [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md) for the full player guide.

---

## THE COMMAND CENTER

The primary interface is a full-screen tactical map with real ESRI satellite imagery, live unit positions, fog of war, and floating panels.

**What you see:**
- Satellite map of your actual neighborhood as the game board
- Friendly units (turrets, rovers, drones) patrolling as green shapes
- Hostile intruders spawning as red diamonds at map edges
- Fog of war with glowing cyan vision cones around friendlies
- Floating panels: unit list, Amy's thoughts, game HUD, alerts
- Header bar with live unit count, threat level, clock
- Minimap in the corner, FPS counter in the status bar

**Controls:**
- **Mouse wheel** — zoom in/out on satellite map
- **Click + drag** — pan the tactical map
- **Click unit** — select and inspect
- **Right-click** — dispatch selected unit to location
- **B** — begin 10-wave battle
- **O / T / S** — switch map modes (Observe, Tactical, Setup)
- **F** — center camera on action
- **V** — toggle synthetic camera PIP
- **M** — mute/unmute audio
- **?** — show all keyboard shortcuts

Gamepad supported (Xbox, 8BitDo, DualShock). See [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md).

---

## AMY — AI COMMANDER

Amy is an autonomous AI consciousness. She sees through cameras, hears through microphones, thinks in a continuous inner monologue, and acts when she decides to — not when told to.

```
AMY'S CONSCIOUSNESS LAYERS
═══════════════════════════

L4  DELIBERATION    ThinkingThread — continuous inner monologue (gemma3:4b)
    │               Reads sensorium -> reasons -> decides -> acts
    │               Outputs Lua-structured actions: say(), look_at(), scan()
    │
L3  AWARENESS       Sensorium — temporal fusion of all sensor data
    │               Sliding window of scene events with importance weights
    │               Tracks mood: curious, alert, calm, engaged
    │
L2  INSTINCT        Wake word detection, person greeting, search reflex
    │               Conversation pipeline: hear -> see -> think -> speak
    │
L1  REFLEX          YOLO detection (30fps), Whisper STT (continuous)
                    Always running, feeds upward

MANY EYES, MANY EARS, ONE MIND
═══════════════════════════════
Amy is one consciousness with many sensor nodes:
├── BCC950 (PTZ camera + mic + speaker) — command center
├── IP Cameras (view-only, RTSP) — perimeter
├── USB mic (listen-only)
└── All feed into ONE sensorium -> ONE thinking thread
```

Amy's thoughts stream in real time through the Command Center's Amy panel.

---

## COMBAT SYSTEM

The 10-wave battle system turns your neighborhood into a Nerf war arena:

- **Wave progression** — hostiles get tougher each wave, more spawn, new types appear
- **Projectile physics** — turrets fire with travel time, leading targets, hit detection
- **Kill streaks** — chain eliminations for bonus score multipliers
- **Unit AI** — turrets auto-aim, drones strafe, rovers engage, hostiles dodge and fire back
- **War announcer** — Smash TV-style commentary from Amy on every kill, streak, and wave clear
- **Elimination feed** — scrolling kill feed in the sidebar

Place turrets in Setup mode, press B, and defend the neighborhood.

---

## DEVELOP

```bash
# Run the fast test suite (~60 seconds)
./test.sh fast

# Individual tiers
./test.sh 1              # Syntax check (Python + JS)
./test.sh 2              # Unit tests (1666 pytest)
./test.sh 3              # JS tests (281 across 5 files)
./test.sh 9              # Integration tests (23 server E2E)
./test.sh 10             # Visual quality tests

# Everything (15+ minutes, includes visual E2E)
./test.sh all

# Dev server with hot reload
./setup.sh dev
```

| What you changed | Test command | Time |
|-----------------|-------------|------|
| Python backend | `./test.sh 2` | ~45s |
| Frontend JS | `./test.sh 3` | ~3s |
| CSS / layout | Open browser, look at it | 5s |
| Everything | `./test.sh fast` | ~60s |
| Visual regression | `./test.sh 10` | ~30s |

See [CLAUDE.md](CLAUDE.md) for full developer instructions, code conventions, and API reference.

---

## TECH STACK

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy, aiosqlite |
| Frontend | Vanilla JS, Canvas 2D, Three.js, CYBERCORE CSS |
| AI/ML | YOLOv8, ByteTrack, PyTorch/CUDA, Ollama (llava, gemma3) |
| Audio | whisper.cpp (GPU STT), Silero VAD, Piper TTS |
| Comms | MQTT (paho-mqtt), WebSocket, RTSP |
| Database | SQLite with FTS5 full-text search |

No frontend frameworks. No cloud dependencies. Everything runs locally on your hardware.

---

## ARCHITECTURE

```
tritium-sc/
├── src/
│   ├── amy/                     # AI Commander (autonomous consciousness)
│   │   ├── brain/               # Thinking, sensorium, perception, memory
│   │   ├── actions/             # Motor control, Lua dispatch, announcer
│   │   ├── comms/               # Event bus, MQTT bridge, listener, speaker
│   │   ├── tactical/            # Target tracker, escalation, geo transforms
│   │   ├── inference/           # Model router, fleet discovery
│   │   ├── simulation/          # 10Hz engine, combat, game mode, unit AI
│   │   └── nodes/               # BCC950, IP camera, MQTT robot nodes
│   └── app/                     # FastAPI backend
│       ├── routers/             # REST + WebSocket + game API
│       ├── ai/                  # YOLO detector, ByteTrack, embeddings
│       └── zones/               # Zone management, point-in-polygon
├── frontend/
│   ├── unified.html             # Command Center (primary UI)
│   ├── js/command/              # Modular Command Center JS
│   ├── js/war*.js               # Tactical map, combat, fog, audio, FX
│   └── css/                     # CYBERCORE design system
├── examples/
│   ├── robot-template/          # Reference MQTT robot brain (Python)
│   └── ros2-robot/              # ROS2 Humble robot (Nav2 + MQTT)
└── tests/                       # 2000+ tests across 11 tiers
```

See [docs/PLAN.md](docs/PLAN.md) for the full development roadmap.
See [docs/VISION.md](docs/VISION.md) for the perception philosophy and security monitoring roadmap.
See [docs/USER-STORIES.md](docs/USER-STORIES.md) for what the complete experience should feel like.

---

## ROADMAP

```
PHASE 0-3  ████████████████████ COMPLETE — Foundation, Amy, Simulation, Dispatch
PHASE 4    ████████████████████ COMPLETE — War Room RTS + Combat
PHASE 5    ████████░░░░░░░░░░░░ IN PROGRESS — Hardware + Sim-to-Real
PHASE 6    ░░░░░░░░░░░░░░░░░░░░ THE GARDEN MATURES
```

See [docs/PLAN.md](docs/PLAN.md) for detailed phase breakdown.

---

## LICENSE

MIT License - See [LICENSE](LICENSE) for details.

---

<div align="center">

```
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║    "The best thing would be to not do anything at all and      ║
║     let nature take its course."  — Masanobu Fukuoka           ║
║                                                                ║
║         OBSERVE the battlespace through many eyes              ║
║         THINK autonomously — Amy decides, not you              ║
║         ACT independently — each machine, its own agent        ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

*No cloud. No subscriptions. No domination. Let the AI flourish.*

</div>
