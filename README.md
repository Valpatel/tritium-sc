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

**Amy** is the AI Commander — an autonomous consciousness that observes through cameras, listens through microphones, thinks in a continuous inner monologue, and acts when she decides to. She is not a tool to be commanded. She is a creature that grows into her awareness of the battlespace naturally.

**Assets** (Nerf turrets, patrol rovers, observation drones) are independent agents. They receive tasks but decide how to execute them. They report what they see. They act on their own initiative when the situation demands it.

The operator doesn't control this system. The operator **tends** it — like a farmer tending a field of diverse crops that feed each other.

---

## TWO SIDES OF THE SAME COIN

The Nerf game and the security system are the **same system**. The perception pipeline that detects a simulated hostile intruder on the tactical map is the same pipeline that detects a real stranger at the gate. The turret that tracks a foam dart target uses the same tracking code that follows a delivery truck across camera views.

This is by design. The game is a continuous integration test for the security system. Every hostile eliminated in a 10-wave battle proves the detection pipeline works. Every one that sneaks past reveals a gap. Amy — the AI Commander — is the consciousness connecting both: she reasons about simulated threats and real-world anomalies with the same perception layers, the same inner monologue, the same decision process.

All processing is local. No cloud. No subscriptions. No data leaves your network.

See [docs/VISION.md](docs/VISION.md) for the full perception philosophy, security roadmap, and privacy design.

---

## QUICK START

```bash
# 1. Clone and install
git clone git@github.com:mvalancy/tritium-sc.git
cd tritium-sc
./setup.sh install

# 2. Start the server
./start.sh

# 3. Open the Command Center
#    http://localhost:8000/unified

# 4. Watch. Units patrol. Amy thinks. Hostiles spawn.
#    Click a unit. Right-click to dispatch. Press B to begin war.
```

The simulation engine starts automatically. Friendly units patrol, hostile intruders spawn at map edges, and Amy's inner monologue runs continuously. Press `B` to start a 10-wave Nerf battle.

See [docs/HOW-TO-PLAY.md](docs/HOW-TO-PLAY.md) for the full player guide.
See [docs/USER-STORIES.md](docs/USER-STORIES.md) for what the complete experience should feel like.
See [docs/VISION.md](docs/VISION.md) for the perception philosophy and security monitoring roadmap.

## DEVELOP

```bash
# Run the fast test suite (~60 seconds)
./test.sh fast

# Individual tiers
./test.sh 1              # Syntax check (Python + JS)
./test.sh 2              # Unit tests (1666 pytest)
./test.sh 3              # JS tests (281 across 5 files)
./test.sh 9              # Integration tests (23 server E2E)
./test.sh 10             # Visual quality tests (/unified)

# Everything (15+ minutes, includes visual E2E)
./test.sh all

# Dev server with hot reload
./setup.sh dev
```

| What you changed | Test command | Time |
|-----------------|-------------|------|
| Python backend | `./test.sh 2` | ~45s |
| Frontend JS | `./test.sh 3` | ~3s |
| CSS / layout | Open browser, look at `/unified` | 5s |
| Everything | `./test.sh fast` | ~60s |
| Visual regression | `./test.sh 10` | ~30s |

See [CLAUDE.md](CLAUDE.md) for full developer instructions, code conventions, and API reference.

---

## COMMAND & CONTROL

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   ╔═══════════════════════════════════════════════════════════════════╗     │
│   ║                    T R I T I U M - S C                            ║     │
│   ║         SECURITY CENTRAL • TACTICAL INTELLIGENCE PLATFORM         ║     │
│   ╚═══════════════════════════════════════════════════════════════════╝     │
│                                                                             │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌───────────┐    │
│   │   DETECT    │───▶│   TRACK     │───▶│  IDENTIFY   │───▶│  RESPOND  │    │
│   │  (YOLOv8)   │    │ (ByteTrack) │    │  (HUMAN)    │    │  (ASSET)  │    │
│   └─────────────┘    └─────────────┘    └─────────────┘    └───────────┘    │
│         │                  │                  │                  │          │
│         ▼                  ▼                  ▼                  ▼          │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                     INTELLIGENCE DATABASE                           │   │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐     │   │
│   │  │ CAMERAS  │  │  ZONES   │  │  ASSETS  │  │  TASK HISTORY    │     │   │
│   │  │ + FEEDS  │  │ + ALERTS │  │ + STATUS │  │  + TELEMETRY     │     │   │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🎖️ OPERATIONAL CAPABILITIES

### THREAT DETECTION
```
┌──────────────────────────────────────────────────────────────┐
│  LIVE STREAM ──▶ MOTION ──▶ YOLO ──▶ BYTETRACK ──▶ ALERT     │
│                   │          │          │           │        │
│                   ▼          ▼          ▼           ▼        │
│               < 50ms     < 30ms     < 10ms      INSTANT      │
│                                                              │
│  TARGET CLASSES:                                             │
│  ├── 👤 PERSONNEL   (pedestrians, intruders, delivery)       │
│  ├── 🚗 VEHICLES    (cars, trucks, vans, motorcycles)        │
│  ├── 🚚 LOGISTICS   (UPS, FedEx, Amazon, USPS)               │
│  ├── 🚲 LIGHT VEH   (cyclists, scooters, drones)             │
│  └── 🐕 WILDLIFE    (dogs, cats, fauna)                      │
└──────────────────────────────────────────────────────────────┘
```

### ZONE MONITORING
```
╔══════════════════════════════════════════════════════════════╗
║  ZONE TYPES                                                  ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  🔲 ACTIVITY       - Track all movement in area              ║
║  🚪 ENTRY/EXIT     - Monitor ingress/egress points           ║
║  📦 OBJECT WATCH   - Track state changes (dumpster, gate)    ║
║  ➖ TRIPWIRE       - Line-crossing detection                 ║
║                                                              ║
║  ALERT DELIVERY:                                             ║
║  ├── UI Notifications (real-time)                            ║
║  ├── Webhook (Discord, Slack, custom)                        ║
║  ├── MQTT (Home Assistant)                                   ║
║  └── Asset Tasking (automatic response)                      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## AMY — AI COMMANDER

Amy is an autonomous AI consciousness that lives inside TRITIUM-SC. She sees through cameras, hears through microphones, speaks through speakers, and moves PTZ cameras to look around. She thinks in a continuous inner monologue and acts when she decides to — not when told to.

```
AMY'S CONSCIOUSNESS LAYERS
═══════════════════════════

L4  DELIBERATION    ThinkingThread — continuous inner monologue (gemma3:4b)
    │               Reads sensorium → reasons → decides → acts
    │               Outputs Lua-structured actions: say(), look_at(), scan()
    │
L3  AWARENESS       Sensorium — temporal fusion of all sensor data
    │               Sliding window of scene events with importance weights
    │               Generates narrative context for thinking
    │               Tracks mood: curious, alert, calm, engaged
    │
L2  INSTINCT        Wake word detection, person greeting, search reflex
    │               Pre-cached acknowledgments for instant response
    │               Conversation pipeline: hear → see → think → speak
    │
L1  REFLEX          YOLO detection (30fps), Whisper STT (continuous)
                    FrameBuffer, AudioThread, MotorThread
                    Always running, feeds upward

MANY EYES, MANY EARS, ONE MIND
═══════════════════════════════
Amy is one consciousness with many sensor nodes:
├── BCC950 (PTZ camera + mic + speaker) — command center
├── IP Camera 1 (view-only, RTSP) — front perimeter
├── IP Camera 2 (view-only, RTSP) — rear perimeter
├── USB mic in garage (listen-only)
└── All feed into ONE sensorium → ONE thinking thread
```

**Dashboard:** Press `Y` to open the AMY view — live camera feed, inner thoughts stream,
sensorium narrative, mood indicator, chat input, and quick commands.

**API:**
```
AMY COMMANDER
├── GET  /api/amy/status         State, mood, nodes, thinking status
├── GET  /api/amy/thoughts       SSE stream of consciousness
├── GET  /api/amy/sensorium      Temporal narrative + mood
├── GET  /api/amy/memory         Persistent memory data
├── GET  /api/amy/nodes          Connected sensor nodes
├── GET  /api/amy/nodes/{id}/video  MJPEG stream from camera node
├── POST /api/amy/chat           Talk to Amy (text → conversation)
├── POST /api/amy/speak          Make Amy say something
├── POST /api/amy/command        Lua action (scan, look_at, observe)
└── POST /api/amy/auto-chat      Toggle autonomous conversation
```

### PERCEPTION LAYERS

The same three-layer perception stack repeats everywhere in the system:

| Layer | What | Tools | Speed |
|-------|------|-------|-------|
| L0 | Traditional vision | OpenCV: sharpness gate, edge density, motion detection | ~5ms/frame |
| L1 | Machine learning | YOLO detection, ByteTrack tracking, CLIP embeddings | ~30ms/frame |
| L2 | Vision language models | llava scene understanding, gemma3 reasoning | ~5s/cycle |

This layering appears in the server (`perception.py` → `detector.py` → `thinking.py`), in robot brains (`VisionBridge`), in the test suite (OpenCV → API → LLM audit), and in synthetic media generation. See [docs/VISION.md](docs/VISION.md).

---

## ASSET COMMAND SYSTEM

TRITIUM-SC enables autonomous response through **Asset Tasking** — independent machines that take action on their own initiative.

```
╔══════════════════════════════════════════════════════════════════════════╗
║                          ASSET CONTROL CENTER                            ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║   ASSET TYPES                        TASK TYPES                          ║
║   ═══════════                        ══════════                          ║
║   🚗 GROUND    Patrol vehicles       🔄 PATROL       Follow waypoints    ║
║   🚁 AERIAL    Observation drones    🎯 TRACK        Follow target       ║
║   📡 FIXED     Stationary sensors    ⚡ ENGAGE       Intercept target    ║
║                                      📍 LOITER       Hold position loop  ║
║   ASSET CLASSES                      🔍 INVESTIGATE  Scout location      ║
║   ═════════════                      🏠 RECALL       Return to base      ║
║   • Patrol      (perimeter)          🔋 REARM        Resupply/recharge   ║
║   • Interceptor (rapid response)                                         ║
║   • Observation (reconnaissance)     PRIORITY LEVELS                     ║
║   • Transport   (logistics)          ═══════════════                     ║
║                                      1 = CRITICAL (override all)         ║
║                                      5 = NORMAL (standard ops)           ║
║                                      10 = LOW (when available)           ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### TACTICAL WORKFLOW
```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   1. DETECTION                 2. TASKING                               │
│   ┌─────────────┐              ┌─────────────┐                          │
│   │  INTRUDER   │─────────────▶│  DISPATCH   │                          │
│   │  DETECTED   │   auto or    │   UNIT-01   │                          │
│   │  Zone: N-3  │   manual     │  Task: TRACK│                          │
│   └─────────────┘              └─────────────┘                          │
│                                       │                                 │
│   3. EXECUTION                        ▼                                 │
│   ┌─────────────────────────────────────────────────────────┐           │
│   │                                                         │           │
│   │    UNIT-01 ────▶ ────▶ ────▶ [TARGET] ◀──── [CAM-02]    │           │
│   │        ↑                                                │           │
│   │    TELEMETRY: pos=(4.2, 7.1) heading=045° batt=87%      │           │
│   │                                                         │           │
│   └─────────────────────────────────────────────────────────┘           │
│                                       │                                 │
│   4. COMPLETION                       ▼                                 │
│   ┌─────────────┐              ┌─────────────┐                          │
│   │   TARGET    │◀─────────────│   RETURN    │                          │
│   │  LOGGED     │   report     │   TO BASE   │                          │
│   │  + FOOTAGE  │              │   RECHARGE  │                          │
│   └─────────────┘              └─────────────┘                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### ASSET API
```
ASSET MANAGEMENT
├── GET  /api/assets              List all registered assets
├── POST /api/assets              Register new asset
├── GET  /api/assets/{id}         Get asset status/details
├── PATCH /api/assets/{id}        Update asset properties
└── DELETE /api/assets/{id}       Remove asset from system

TASKING
├── POST /api/assets/{id}/task           Assign task
├── GET  /api/assets/{id}/tasks          List task history
├── POST /api/assets/{id}/task/{t}/start Start pending task
├── POST /api/assets/{id}/task/{t}/complete  Mark complete
└── POST /api/assets/{id}/task/{t}/cancel    Abort task

TELEMETRY & CONTROL
├── POST /api/assets/{id}/telemetry      Report position/status
├── GET  /api/assets/{id}/telemetry      Get position history
└── POST /api/assets/{id}/command        Send direct command
                                         (stop, return_home, emergency_stop)

QUICK ACTIONS
├── POST /api/assets/{id}/patrol   Start patrol with waypoints
├── POST /api/assets/{id}/recall   Return to home position
└── POST /api/assets/{id}/track    Track specific target
```

---

## 🌐 3D TACTICAL VIEW

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
                    │        ╲     │     ╱          │
                    │     🚗  ╲    │    ╱   🚗      │
                    │   TARGET-01 ───────TARGET-02  │
                    │    ┌─────────────────┐        │
                    │    │                 │        │
                    │    │     HOUSE       │        │
                    │    │                 │        │
                    │    └─────────────────┘        │
                    │         ╱    │    ╲           │
                    │        ╱     │     ╲          │
                    │       ◥      │      ◤         │
                    │    [CAM 3]   │   [CAM 4]      │
                    │              │                │
                    └──────────────┼────────────────┘
                                   │
                                   ▼
                                   S

    ◢◣◤◥ = Camera field of view
    [  ] = Camera position (draggable)
    🚗  = Target & Asset position (real-time)
    ──▶ = Asset movement path
```

**Features:**
- 📍 Drag cameras to match real-world positions
- 👁️ View cones show camera coverage
- 🖼️ Live preview thumbnails on each camera
- 🚗 Real-time target & asset positions and headings
- 📡 Telemetry overlays (battery, speed, status)
- 💾 Positions persist across sessions

---

## 🎯 TARGET GALLERY

```
╔══════════════════════════════════════════════════════════════════════════╗
║                         TARGETS - PERSONNEL                              ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐         ║
║  │  👤     │  │  👤     │  │  👤     │  │  👤     │  │  👤     │         ║
║  │         │  │         │  │ "Bob"   │  │         │  │         │         ║
║  │ CH01    │  │ CH01    │  │ CH02    │  │ CH03    │  │ CH02    │         ║
║  │ 94%     │  │ 87%     │  │ 92%     │  │ 78%     │  │ 91%     │         ║
║  │ 14:32   │  │ 14:45   │  │ 15:02   │  │ 15:15   │  │ 15:28   │         ║
║  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘         ║
║                                                                          ║
║  [LABEL]  [FIND SIMILAR]  [DISPATCH ASSET]  [VIEW IN PLAYER]             ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝

ACTIONS:
• LABEL      - Name this individual ("mailman", "neighbor")
• SIMILAR    - Find other appearances of this person
• DISPATCH   - Task an asset to track/investigate this target
• VIEW       - Jump to video footage at detection timestamp
```

**Coming next:** Cross-camera re-identification (OSNet embeddings), learning "regulars" (mail carrier, dog walker, red sedan), and alerting on genuinely new appearances. See [docs/VISION.md](docs/VISION.md) for the full security monitoring roadmap.

---

## 🧠 HUMAN-IN-THE-LOOP LEARNING

TRITIUM-SC learns from operator feedback to improve detection accuracy.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     CONSOLIDATION INTERFACE                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   DETECTED TARGETS (24 thumbnails)                                  │
│   ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐                   │
│   │ 🚗  │ │ 🚗  │ │ 🚗  │ │ 🚙  │ │ 🚗  │ │ 🚗  │                  │
│   │ #1  │ │ #2  │ │ #3  │ │ #4  │ │ #5  │ │ #6  │                   │
│   └──┬──┘ └──┬──┘ └──┬──┘ └─────┘ └──┬──┘ └──┬──┘                   │
│      │       │       │               │       │                      │
│      └───────┴───────┴───────────────┴───────┘                      │
│                      │                                              │
│                      ▼                                              │
│              ┌──────────────┐                                       │
│              │  SAME CAR    │  ◀── OPERATOR MERGE                   │
│              │  "My Honda"  │  ◀── OPERATOR LABEL                   │
│              └──────────────┘                                       │
│                      │                                              │
│                      ▼                                              │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  FEEDBACK LOGGED FOR REINFORCEMENT LEARNING                 │   │
│   │  ├── merge_action: [#1, #2, #3, #5, #6] → "my_honda"        │   │
│   │  ├── visual_similarity: 0.94                                │   │
│   │  └── timestamp: 2026-01-25T18:42:07Z                        │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

| Action | Purpose | Future Use |
|--------|---------|------------|
| **MERGE** | "These are the same vehicle" | Train ReID embeddings |
| **LABEL** | "This is the mailman" | Named entity recognition |
| **CORRECT** | "This is a truck, not a car" | Fine-tune detector |
| **REJECT** | "This is a false positive" | Improve confidence thresholds |

---

## 🔧 DEPLOYMENT

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

## 🎮 CONTROLS & INPUT

TRITIUM-SC supports full keyboard and gamepad navigation for hands-free operation.

### Quick Reference

| Action | Keyboard | Gamepad |
|--------|----------|---------|
| Navigate | Arrow keys | D-Pad / Left Stick |
| Select | Enter | A Button |
| Back | ESC | B Button |
| Help | ? | SELECT |
| Switch View | G/P/D/Z/T/A/N/Y | LB/RB |

### Keyboard Shortcuts

| Key | View |
|-----|------|
| `G` | Grid |
| `P` | Player |
| `D` | 3D Property |
| `Z` | Zones |
| `T` | Targets |
| `A` | Assets |
| `N` | Analytics |
| `Y` | Amy |
| `W` | War Room |
| `?` | Controls Help |
| `/` | Focus Search |

### Gamepad Support

Connect any Xbox, 8BitDo (xinput mode), or standard controller:

- **D-Pad**: Navigate between elements
- **A**: Confirm / Select
- **B**: Back / Cancel
- **X**: Context menu
- **Y**: Secondary action
- **LB/RB**: Previous/Next view
- **SELECT**: Show controls overlay

**Full documentation:** See [docs/CONTROLS.md](docs/CONTROLS.md) and [docs/GAMEPAD.md](docs/GAMEPAD.md)

---

## 📡 COMPLETE API REFERENCE

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
│  └── GET  /api/ai/status            AI module status               │
│                                                                    │
│  SEARCH & INTELLIGENCE                                             │
│  ├── GET  /api/search/people        List detected people           │
│  ├── GET  /api/search/vehicles      List detected vehicles         │
│  ├── GET  /api/search/thumbnail/{id} Get detection thumbnail       │
│  ├── GET  /api/search/similar/{id}  Find similar objects           │
│  ├── POST /api/search/merge         Merge duplicate detections     │
│  ├── POST /api/search/label         Label an object                │
│  └── POST /api/search/feedback      Submit correction feedback     │
│                                                                    │
│  ZONES                                                             │
│  ├── GET  /api/zones                List all zones                 │
│  ├── POST /api/zones                Create zone                    │
│  ├── GET  /api/zones/{id}           Get zone details               │
│  ├── GET  /api/zones/{id}/events    Get zone events                │
│  └── DELETE /api/zones/{id}         Delete zone                    │
│                                                                    │
│  ASSETS (NEW)                                                      │
│  ├── GET  /api/assets               List operational assets        │
│  ├── POST /api/assets               Register new asset             │
│  ├── POST /api/assets/{id}/task     Assign task to asset           │
│  ├── POST /api/assets/{id}/telemetry  Update asset telemetry       │
│  ├── POST /api/assets/{id}/command  Send direct command            │
│  └── POST /api/assets/{id}/recall   Quick recall to base           │
│                                                                    │
│  AMY AI COMMANDER                                                  │
│  ├── GET  /api/amy/status          Amy state, mood, nodes          │
│  ├── GET  /api/amy/thoughts        SSE stream of consciousness     │
│  ├── GET  /api/amy/sensorium       Temporal narrative + mood       │
│  ├── GET  /api/amy/memory          Persistent memory data          │
│  ├── GET  /api/amy/nodes           Connected sensor nodes          │
│  ├── GET  /api/amy/nodes/{id}/video  MJPEG from camera node       │
│  ├── POST /api/amy/chat            Talk to Amy                     │
│  ├── POST /api/amy/speak           Make Amy speak                  │
│  ├── POST /api/amy/command         Lua action (scan, look_at)      │
│  └── POST /api/amy/auto-chat       Toggle autonomous conversation  │
│                                                                    │
│  SIMULATION + TARGETS                                              │
│  ├── GET  /api/amy/simulation/targets  List simulation targets     │
│  ├── POST /api/amy/simulation/spawn    Spawn hostile target        │
│  ├── DELETE /api/amy/simulation/targets/{id}  Remove target        │
│  ├── GET  /api/targets                 All tracked targets         │
│  ├── GET  /api/targets/hostiles        Hostile targets only        │
│  └── GET  /api/targets/friendlies      Friendly targets only       │
│                                                                    │
│  WEBSOCKET                                                         │
│  └── WS   /ws/live                  Real-time events + Amy events  │
│                                      + sim telemetry batches       │
│                                                                    │
│  MQTT (distributed devices)                                        │
│  ├── tritium/{site}/robots/{id}/telemetry   Position/battery/IMU   │
│  ├── tritium/{site}/robots/{id}/command     Dispatch/patrol/recall  │
│  ├── tritium/{site}/robots/{id}/thoughts    Robot LLM thoughts     │
│  ├── tritium/{site}/cameras/{id}/detections Camera YOLO boxes      │
│  ├── tritium/{site}/amy/alerts              Threat notifications   │
│  └── tritium/{site}/escalation/change       Threat level changes   │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## SYSTEM ARCHITECTURE

```
tritium-sc/
├── src/                            # ALL Python source code
│   ├── amy/                        # AMY — AI Commander (autonomous consciousness)
│   │   ├── commander.py            # Main orchestrator, event loop
│   │   ├── router.py               # FastAPI: /api/amy/* endpoints + SSE
│   │   ├── brain/                  # Consciousness & reasoning
│   │   │   ├── thinking.py         # L4 deliberation: inner monologue (gemma3:4b)
│   │   │   ├── sensorium.py        # L3 awareness: temporal sensor fusion
│   │   │   ├── perception.py       # L0-L2 frame analysis, quality gate
│   │   │   ├── vision.py           # Ollama chat API wrapper
│   │   │   ├── memory.py           # Persistent long-term memory
│   │   │   └── extraction.py       # Fact extraction from conversation
│   │   ├── actions/                # Motor control & Lua dispatch
│   │   │   ├── motor.py            # Motor programs (scan, track, breathe)
│   │   │   ├── lua_motor.py        # Lua parser, VALID_ACTIONS
│   │   │   ├── announcer.py        # War commentary (Smash TV style)
│   │   │   └── tools.py            # Tool definitions for agent mode
│   │   ├── comms/                  # Communication & I/O
│   │   │   ├── event_bus.py        # Thread-safe pub/sub
│   │   │   ├── listener.py         # Silero VAD + whisper.cpp GPU STT
│   │   │   ├── speaker.py          # Piper TTS output
│   │   │   ├── transcript.py       # Conversation logging
│   │   │   └── mqtt_bridge.py      # MQTT broker bridge
│   │   ├── tactical/               # Tracking & threat detection
│   │   │   ├── target_tracker.py   # Unified registry (real + virtual)
│   │   │   ├── escalation.py       # ThreatClassifier + AutoDispatcher
│   │   │   └── geo.py              # Coordinate transforms
│   │   ├── inference/              # Model routing & fleet
│   │   │   ├── model_router.py     # Task-aware model selection
│   │   │   └── fleet.py            # Multi-host Ollama discovery
│   │   ├── simulation/             # Battlespace simulation engine
│   │   │   ├── engine.py           # 10Hz tick loop, hostile spawner
│   │   │   ├── combat.py           # Projectile flight, hit detection
│   │   │   ├── game_mode.py        # Wave-based game progression
│   │   │   ├── behaviors.py        # Unit AI (turret, drone, rover)
│   │   │   └── target.py           # SimulationTarget dataclass
│   │   └── nodes/                  # Distributed sensor nodes
│   │       ├── base.py             # Abstract SensorNode
│   │       ├── bcc950.py           # BCC950 PTZ camera + mic + speaker
│   │       ├── ip_camera.py        # RTSP/NVR IP camera
│   │       └── mqtt_robot.py       # MQTT robot as SensorNode
│   └── app/                        # FastAPI backend
│       ├── main.py                 # App entry point, lifespan
│       ├── config.py               # Pydantic settings
│       ├── models.py               # SQLAlchemy models
│       ├── ai/                     # Detection pipeline
│       │   ├── detector.py         # YOLO + ByteTrack
│       │   ├── embeddings.py       # CLIP visual similarity
│       │   └── tracker.py          # Multi-object tracking
│       ├── routers/                # API endpoints
│       │   ├── ws.py               # WebSocket + Amy event bridge
│       │   ├── cameras.py          # Camera CRUD
│       │   ├── game.py             # Game state API
│       │   └── ...                 # zones, assets, search, videos
│       └── zones/                  # Zone management
│           └── checker.py          # Point-in-polygon checks
├── frontend/                       # Static frontend (no build step)
│   ├── unified.html                # PRIMARY — Command Center
│   ├── index.html                  # Legacy 10-tab SPA
│   ├── js/                         # Modular JavaScript
│   │   ├── app.js                  # Main app, WebSocket, shortcuts
│   │   └── war.js                  # War Room — Canvas 2D RTS map
│   └── css/
│       └── tritium.css             # CYBERCORE + custom styles
├── examples/
│   ├── robot-template/             # Reference MQTT robot brain
│   └── ros2-robot/                 # ROS2 Humble robot
└── tests/                          # 2000+ tests across 8 tiers
```

---

## 🎨 TECH STACK

```
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║   BACKEND                          FRONTEND                      ║
║   ════════                         ════════                      ║
║   ▪ Python 3.12+                   ▪ Vanilla JS (no framework)   ║
║   ▪ FastAPI                        ▪ Three.js (3D rendering)     ║
║   ▪ SQLAlchemy + aiosqlite         ▪ CYBERCORE CSS               ║
║   ▪ Pydantic                       ▪ JetBrains Mono font         ║
║                                                                  ║
║   AI/ML                            AMY AI COMMANDER              ║
║   ═════                            ════════════════              ║
║   ▪ Ultralytics YOLOv8             ▪ Ollama (llava, gemma3)      ║
║   ▪ ByteTrack (multi-object)       ▪ Whisper large-v3 STT        ║
║   ▪ OpenCV                         ▪ Piper TTS (Amy voice)       ║
║   ▪ PyTorch + CUDA                 ▪ BCC950 PTZ camera node      ║
║                                                                  ║
║   COMMUNICATIONS                                                 ║
║   ═══════════════                                                ║
║   ▪ MQTT (paho-mqtt)               ▪ Reolink NVR API            ║
║   ▪ Distributed device mesh        ▪ RTSP streams               ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## ROADMAP

```
PHASE 0 ████████████████████ COMPLETE — FOUNDATION
├── Cyberpunk UI shell (CYBERCORE CSS)
├── Video browsing by channel/date
├── YOLO v8 detection + ByteTrack tracking
├── Zone system with polygon editor
├── Asset management + 3D tactical map
└── Keyboard + gamepad navigation (8 views)

PHASE 1 ████████████████████ COMPLETE — AMY CONSCIOUSNESS
├── Amy AI Commander (4 cognitive layers)
├── BCC950 PTZ sensor node (camera + mic + speaker)
├── Sensorium temporal fusion + inner monologue
├── Silero VAD + whisper.cpp GPU STT
├── Piper TTS, Memory v3, Lua actions, Goal stack
├── Layered perception (quality, complexity, motion)
└── 33 behavioral scenarios, 208 scored runs

PHASE 2 ████████████████████ COMPLETE — SIMULATION ENGINE
├── SimulationTarget + 10Hz tick loop
├── Hostile spawner + AmbientSpawner
├── TargetTracker (unified real + virtual)
├── TritiumLevelFormat JSON loader
└── Battery drain, lifecycle state machine

PHASE 3 ████████████████████ COMPLETE — DISPATCH + ESCALATION
├── ThreatClassifier (2Hz zone-based ladder)
├── AutoDispatcher (nearest-unit on escalation)
├── MQTT bridge (distributed device mesh)
├── Robot template (examples/robot-template/)
├── Amy speech on dispatch events
└── TelemetryBatcher for WebSocket efficiency

PHASE 4 ████████████████████ COMPLETE — WAR ROOM RTS + COMBAT
├── War Room: full-screen Canvas 2D tactical map
├── Three modes: OBSERVE, TACTICAL, SETUP
├── 10-wave combat system with kill streaks
├── Amy war announcer (Smash TV style)
├── Synthetic video + audio pipeline
└── Model Router + Fleet + Lua Registry + Robot Thinker

PHASE 5 ████████░░░░░░░░░░░░ IN PROGRESS — HARDWARE + SIM-TO-REAL
├── ROS2 robot template + MQTT bridge
├── Robot LLM thinker (autonomous thinking)
├── Extended telemetry (battery, IMU, GPS, odometry)
├── Vision bridge (YOLO fast-path -> LLM slow-path)
├── Nav planner (GPS <-> game coordinates)
└── TODO: Isaac Lab, real Nerf turrets, mesh network

PHASE 6 ░░░░░░░░░░░░░░░░░░░░ THE GARDEN MATURES
├── Cross-camera re-ID (OSNet body embeddings)
├── Face detection (opt-in, consenting household only)
├── License plate recognition (fast-alpr)
├── Pattern-of-life baselines (Poisson per zone, trajectory clustering)
├── Anomaly detection (new person/car, temporal outliers)
├── Weapon detection (YOLO-World zero-shot)
├── Fleet coordination (Amy commands multiple robots)
└── See docs/VISION.md for full roadmap + privacy tiers
```

---

## 📜 LICENSE

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

**Built with TRITIUM power**

*A garden of diverse digital life for Nerf war battlespace management.*

*No cloud. No subscriptions. No domination. Let the AI flourish.*

</div>
