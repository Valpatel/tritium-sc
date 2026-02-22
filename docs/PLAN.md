# TRITIUM-SC Development Plan

```
  _____ ___ ___ _____ ___ _   _ __  __     ___  ___
 |_   _| _ \_ _|_   _|_ _| | | |  \/  |   / __|/ __|
   | | |   /| |  | |  | || |_| | |\/| |___\__ \ (__
   |_| |_|_\___| |_| |___|\___/|_|  |_|___|___/\___|
       SECURITY CENTRAL -- BATTLESPACE MANAGEMENT
```

## Vision

TRITIUM-SC (Tritium-Security Central) manages real Nerf battles with real
robots, real turrets, and real people on a real neighborhood map. Amy is the AI
commander who watches through cameras, listens through microphones, understands
the neighborhood, and commands the fleet.

When no battle is running, Amy operates as neighborhood awareness — tracking
who comes and goes, learning the rhythms, noticing when something is off. The
simulated battle mode exercises the exact same detection pipeline, target
registry, threat classifier, and event bus that Amy uses in normal operation.
Every wave cleared is proof the system works.

Inspired by Masanobu Fukuoka's "One-Straw Revolution" — the operator tends the
system like a garden, not a factory. Amy thinks, observes, and acts on her own.
Assets patrol autonomously. The human plants seeds and watches what grows.

---

## Three Layers

```
+---------------------------------------------------------------+
|                  TRUSTED ACCESS TERMINAL                      |
|  Frontend SPA -- 8 views, keyboard/gamepad, cyberpunk UI      |
|  Grid | Player | 3D Map | Zones | Targets | Assets | Amy     |
+---------------------------------------------------------------+
        |               |                |
        v               v                v
+---------------------------------------------------------------+
|                    AI COMMANDER AMY                            |
|  4 cognitive layers: reflex -> instinct -> awareness ->       |
|  deliberation. Continuous inner monologue. Sees, hears,       |
|  speaks, moves cameras, dispatches assets, sets goals.        |
+---------------------------------------------------------------+
        |               |                |
        v               v                v
+---------------------------------------------------------------+
|                      BATTLESPACE                              |
|  Real sensors: BCC950 PTZ, NVR cameras, RTSP, USB mics       |
|  Virtual units: simulated rovers, drones, turrets, hostiles   |
|  Both produce events, detections, tracks on same map          |
+---------------------------------------------------------------+
```

**Real sensors today:**
- Logitech BCC950 PTZ camera + mic + speaker (Amy's body)
- NVR IP cameras via RTSP
- USB microphones (Silero VAD + whisper.cpp GPU STT)

**Virtual units (operational):**
- Simulated rovers with patrol routes
- Automated Nerf turrets (stationary)
- Recon/scout/heavy drones
- Hostile intruders with multi-waypoint paths
- Ambient neighborhood activity (neighbors, cars, dogs, cats, delivery people)

Both real and virtual coexist: same tactical map, same WebSocket events,
same YOLO detection pipeline, same zone alerts.

---

## Scale Progression

```
COMPLETE (Phase 0-4)      PHASE 5 (Active)          FUTURE (Phase 6+)
1 real cam                ROS2 mini robot            Isaac Lab sim-to-real
+ Amy consciousness       + Robot LLM thinker        + synthetic camera imagery
+ simulation engine       + Vision bridge (YOLO→LLM) + target re-identification
+ threat escalation       + Nav planner (GPS↔game)   + pattern recognition
+ auto dispatch           + Extended telemetry        + multi-agent coordination
+ MQTT distributed bus    + Model router + fleet      + historical replay
+ ambient activity        + Lua registry + multi-act  + pursuit intercept
+ War Room RTS + combat   + any Tailscale host        + force reserve
+ 10-wave game mode       + synthetic video/audio     + mesh radio network
```

---

## Implementation Phases

### Phase 0: Foundation [COMPLETE]
- [x] FastAPI backend with async SQLite + FTS5
- [x] YOLO v8 detection with ByteTrack tracking
- [x] Video browsing, streaming, channel discovery
- [x] NVR auto-discovery (ONVIF)
- [x] 3D tactical map (Three.js, 30 asset types)
- [x] Zone system: CRUD, polygon editor, 4 zone types
- [x] Zone events: enter/exit, activity, state change, tripwire
- [x] Asset management: CRUD, type taxonomy, status tracking
- [x] WebSocket live event bus
- [x] Keyboard + gamepad navigation (8 views)
- [x] CYBERCORE CSS framework (cyberpunk aesthetic)
- [x] Playwright E2E test suite

### Phase 1: Amy Consciousness [COMPLETE]
- [x] Commander event loop with 4 cognitive layers
- [x] BCC950 sensor node (PTZ + mic + speaker)
- [x] Sensorium: temporal sensor fusion, narrative generation
- [x] Thinking thread: continuous inner monologue via LLM
- [x] Vision thread: YOLO detection, layered perception (L0-L2)
- [x] Listener: Silero VAD + whisper.cpp GPU STT
- [x] Speaker: TTS with BCC950 ALSA output
- [x] Memory system: v3 schema, people, facts, self-model
- [x] Lua action system: motor control, goals, memory, speech
- [x] Chat agent: contextual dialogue with scene awareness
- [x] Goal stack: priority queue, 5min expiry, LLM-driven
- [x] Behavioral scoring: 7 metrics + composite (33 scenarios, 208 runs)
- [x] Scenario framework: JSON scenarios, automated runner, results
- [x] Layered perception: quality gate, complexity, motion detection
- [x] Auto-tracking: complexity-weighted camera movement
- [x] Motion events: reflex snap-to-motion with debounce
- [x] Adversarial resistance: prompt injection defense, safety 100%

### Phase 2: Simulation Engine [COMPLETE]
- [x] SimulationTarget flat dataclass (all entity types share fields)
- [x] SimulationEngine: 10Hz tick loop with EventBus telemetry
- [x] Virtual unit spawning: rovers, turrets, drones, hostiles
- [x] Patrol route system: waypoints, loiter, multi-waypoint paths
- [x] TargetTracker: unified registry of real (YOLO) + virtual (sim) targets
- [x] Hostile spawner: adaptive rate (30-120s), NATO phonetic names, cap at 10
- [x] AmbientSpawner: neutral neighborhood activity (neighbors, cars, dogs, cats)
- [x] TritiumLevelFormat JSON loader (targets + zones + waypoint assignment)
- [x] Battery drain per asset type, lifecycle state machine
- [x] API: spawn, list, remove simulation targets

### Phase 3: Amy Dispatches + Threat Escalation [COMPLETE]
- [x] Amy awareness of virtual units (sensorium battlespace summary)
- [x] Lua actions: dispatch(target_id, x, y), alert(), patrol()
- [x] ThreatClassifier: 2Hz zone-based threat ladder (none/unknown/suspicious/hostile)
- [x] AutoDispatcher: nearest-available friendly dispatch on escalation
- [x] De-escalation: step-down after 30s outside zones
- [x] Zone violation events + escalation events on EventBus
- [x] MQTT bridge: distributed device communication
- [x] MQTT-connected robots publish telemetry, receive dispatch commands
- [x] Robot template: `examples/robot-template/` reference implementation
- [x] Amy speech announcements on dispatch events
- [x] TelemetryBatcher: 100ms batching for WebSocket efficiency

### Phase 4: War Room RTS + Extensible Framework [COMPLETE]
- [x] War Room view: full-screen Canvas 2D tactical map (keyboard: W)
- [x] Three modes: OBSERVE (read-only), TACTICAL (select + dispatch), SETUP (place/remove)
- [x] Target rendering: alliance colors (green/red/yellow), heading indicators
- [x] Camera pan/zoom with smooth interpolation
- [x] Box select and individual target selection
- [x] Dispatch via click-to-move in TACTICAL mode
- [x] HUD panels: mode indicator, Amy speech toast, alert log, unit info
- [x] WebSocket integration: live target updates from sim_telemetry_batch
- [x] Fog of war: areas outside sensor coverage dimmed
- [x] Minimap with alert markers
- [ ] Operator can suggest, Amy can override (One-Straw philosophy)
- [x] Combat system: projectiles, damage, health, weapon stats per unit type
- [x] Game mode: setup → countdown → 10 waves → victory/defeat
- [x] Unit AI: turret auto-aim, drone strafing, rover engage, kid nerf tactics
- [x] Amy war announcer: Smash TV / Unreal Tournament style commentary
- [x] Kill feed, wave banners, score display, kill streak effects
- [x] BEGIN WAR button, countdown sequence, game over screens
- [x] Non-combatants: civilians walk through battle (don't shoot them!)
- [x] Health bars, projectile trails, explosion effects, particle system
- [x] Synthetic video pipeline: 4 procedural scene renderers (OpenCV, no GPU)
- [x] Synthetic audio pipeline: 19 procedural effects (numpy, 16kHz WAV)
- [x] Audio effects API: /api/audio/effects/* with WAV streaming
- [x] War Room audio: Web Audio API, event-to-sound mapping, volume controls
- [x] Synthetic camera PIP: MJPEG feed in War Room (V to toggle, M to mute)
- [x] Synthetic feed manager: MJPEG streaming, snapshot, CRUD API
- [x] ModelRouter: task-aware model selection with two-stage failover (`src/amy/inference/model_router.py`)
- [x] OllamaFleet: multi-host discovery from conf/env/Tailscale (`src/amy/inference/fleet.py`)
- [x] LuaActionRegistry: dynamic action registration for robots/plugins (`src/amy/actions/lua_registry.py`)
- [x] Multi-action Lua: compound behavior parsing + sequence validation (`src/amy/actions/lua_multi.py`)
- [x] RobotThinker (server-side): LLM-powered robot thinking with registry (`src/amy/inference/robot_thinker.py`)

### Phase 5: Hardware Integration + Sim-to-Real [IN PROGRESS]

#### 5a: Robot Intelligence + Extended Telemetry
- [x] Robot LLM thinker — standalone (`examples/robot-template/brain/thinker.py`)
  with built-in Lua parser, action handlers, thought history, MQTT publishing
- [x] Vision bridge — YOLO fast-path (10fps) to LLM slow-path (5s) bridge
  with thread-safe detection accumulation (`brain/vision_bridge.py`)
- [x] Nav planner — GPS↔game coordinate transforms, PathPlanner interface,
  StraightLine/Waypoint/Nav2/SLAM stubs (`brain/nav_planner.py`)
- [x] Extended hardware interface — BatteryState (voltage, current, temperature),
  ImuState (roll, pitch, yaw, acceleration), odometry, motor temps, GPS,
  elevation (`hardware/base.py`)
- [x] Simulated hardware — LiPo 3S voltage curve, current draw model,
  differential drive physics, thermal simulation (`hardware/simulated.py`)
- [x] MQTTSensorNode — wraps MQTT-connected robots as SensorNodes in Amy's
  node system (`src/amy/nodes/mqtt_robot.py`)
- [x] SyntheticCameraNode — renders simulation state as MJPEG camera feed,
  implements SensorNode interface (`src/amy/nodes/synthetic_camera.py`)
- [x] Robot thought MQTT topic — `tritium/{site}/robots/{id}/thoughts`

#### 5b: ROS2 Mini Robot (Config-Driven, Any Tailscale Host)
- [x] ROS2 ↔ MQTT bridge node (`examples/ros2-robot/`) — translates dispatch/patrol commands
- [x] Nav2 waypoint action client — sends goals to Nav2 NavigateToPose / FollowWaypoints
- [x] Telemetry publisher — /odom + /battery_state → MQTT `tritium/{site}/robots/{id}/telemetry`
- [x] Simulated odometry node — fake /odom for testing without hardware
- [x] Config-driven: all hosts/ports via ROS2 parameters + env vars (NO hardcoded IPs)
- [x] Unit tests work without ROS2 installed (mock rclpy)
- [x] Launch file with simulated mode flag
- [x] Synthetic camera node — renders scenes, publishes JPEG frames + detections via MQTT
- [x] Server-side synthetic feed manager — MJPEG streaming, snapshot, CRUD API
- [ ] Gazebo simulation world for hardware-in-the-loop testing
- [ ] URDF robot description for Nerf-equipped rover

#### 5c: Multi-Camera Mesh
- [ ] N real cameras on mesh network (Wi-Fi or mesh radio)
- [ ] go2rtc multi-source aggregation
- [ ] Camera auto-discovery via mDNS/ONVIF
- [ ] Bandwidth-aware quality adaptation

#### 5d: Real Hardware Control
- [ ] Real Nerf turret servo control (pan/tilt/fire via ROS2 joint controllers)
- [ ] Real rover with motor control + onboard camera (ROS2 + Nav2)
- [ ] Drone integration (PX4/MAVLink via MAVROS2)
- [ ] Battery and health monitoring for real assets

#### 5e: Simulation-to-Real Pipeline
- [ ] Isaac Lab integration for high-fidelity physics (motor dynamics, terrain,
  sensor noise). TRITIUM-SC provides tactical layer; Isaac Lab provides physics.
- [ ] Synthetic camera imagery from AI models (DALL-E/SDXL) for testing YOLO
  detection without real cameras
- [ ] Global target tracking with cross-camera re-identification
- [ ] Multi-robot fleet coordination via MQTT mesh

#### Design Principles for Phase 5
- **Config over code**: Every host, port, topic prefix is a parameter. No hardcoded IPs.
- **Simulated by default**: `use_sim_odom: true` lets any computer run the robot stack.
- **Tailscale-friendly**: Robots discover MQTT broker via hostname, not IP. Works across
  Tailscale VPN seamlessly — robot on GB10-02 talks to server on GB10-01 by name.
- **MQTT is the lingua franca**: ROS2 nodes talk to TRITIUM-SC via MQTT, not ROS2 topics.
  This keeps the server ROS2-free. The bridge is on the robot side only.
- **Same protocol**: The ROS2 robot publishes the same MQTT messages as the Python
  `robot-template/`. From TRITIUM-SC's perspective, a ROS2 robot and a Python robot
  are identical.

### Phase 6: Advanced Intelligence [FUTURE]
- [x] Synthetic MJPEG feeds from simulated cameras (moved to Phase 4/5, complete)
- [ ] Synthetic security camera imagery for testing (DALL-E/SDXL prompt templates)
- [ ] Target identification and re-identification across cameras (embedding-based ReID)
- [ ] Pattern recognition: repeated approach vectors, time-of-day correlations,
  behavioral anomalies (loitering, perimeter probing)
- [ ] Multi-agent coordination: Amy commands, robots execute, feedback loop
  (fleet coordinator decomposes tactics into robot-level tasks)
- [ ] Historical replay: load past sessions and replay on tactical map
- [ ] Collision detection with zone boundaries
- [ ] Behavioral memory in ThreatClassifier (suspicion score, hysteresis)
- [ ] Pursuit intercept: dispatcher tracks moving targets, not static positions
- [ ] Force reserve: keep fraction of units uncommitted
- [ ] Unit type awareness in dispatch (rovers for interdiction, drones for recon)

---

## Technical Architecture

See [docs/ARCHITECTURE.md](ARCHITECTURE.md) for detailed diagrams (mermaid).

```mermaid
graph TB
    subgraph "Browser"
        WAR[War Room]
        AMY_UI[Amy Dashboard]
        VIEWS["Grid | Player | 3D | Zones | Targets | Assets | Analytics | Scenarios"]
    end

    subgraph "FastAPI Server"
        subgraph "Amy Commander"
            THINK[Thinking Thread]
            SENSE[Sensorium]
            VISION[Vision + YOLO]
            LISTEN[Listener VAD+STT]
            ROUTER[ModelRouter]
        end

        subgraph "Extensible Framework"
            FLEET[OllamaFleet]
            REGISTRY[LuaActionRegistry]
            RTHINKER[RobotThinker]
            MULTI[MultiAction Lua]
        end

        subgraph "Battlespace"
            SIM[SimulationEngine 10Hz]
            TRACK[TargetTracker]
            CLASS[ThreatClassifier 2Hz]
            DISP[AutoDispatcher]
            AMBIENT[AmbientSpawner]
        end

        BUS[EventBus]
        MQTT[MQTTBridge]
        WS[WebSocket Bridge]
    end

    subgraph "External"
        CAM[BCC950 PTZ]
        ROBOT["MQTT Robots (Python + Thinker)"]
        ROS2[ROS2 Robot Nav2+MQTT]
    end

    WAR & AMY_UI & VIEWS -->|WebSocket| WS
    WS --> BUS
    SIM --> BUS --> TRACK
    CLASS --> TRACK
    DISP --> SIM & MQTT
    MQTT --> ROBOT & ROS2
    ROBOT -->|thoughts| MQTT
    CAM --> VISION --> BUS
    ROUTER --> FLEET
    THINK --> ROUTER
    RTHINKER --> FLEET
    REGISTRY --> THINK & RTHINKER
```

### Component Summary

```
Commander (event loop)
  |-- EventBus (thread-safe pub/sub for all internal events)
  |-- VisionThread (YOLO + layered perception L0-L2)
  |-- ThinkingThread (inner monologue, goal-setting)
  |-- ListenerThread (Silero VAD + whisper.cpp GPU STT)
  |-- Speaker (Piper TTS + BCC950 ALSA)
  |-- Motor (PTZ auto-track, complexity-weighted)
  |-- Sensorium (sensor fusion, narrative, battlespace)
  |-- Memory (v3: people, facts, self-model)
  |-- LuaMotor (action execution)
  |-- LuaActionRegistry (dynamic action registration)
  |-- ModelRouter (task-aware model selection + fleet fallback)
  |-- OllamaFleet (multi-host LLM inference discovery)
  |-- RobotThinker (LLM-powered robot autonomous thinking)
  |-- Agent (chat, tool use)
  |-- Perception (frame analysis: quality, complexity, motion)
  |-- TargetTracker (unified real+virtual registry)

Battlespace
  |-- SimulationEngine (10Hz tick, target registry)
  |-- AmbientSpawner (neutral neighborhood activity)
  |-- ThreatClassifier (2Hz zone-based escalation ladder)
  |-- AutoDispatcher (nearest-unit dispatch on escalation)
  |-- MQTTBridge (distributed device communication)

Frontend (10 views)
  |-- Grid: multi-camera mosaic
  |-- Player: single-camera playback
  |-- 3D Map: Three.js tactical view (30 asset types)
  |-- Zones: polygon editor + event timeline
  |-- Targets: detection gallery
  |-- Assets: autonomous unit management
  |-- Analytics: event statistics
  |-- Amy: consciousness dashboard (thoughts, video, chat)
  |-- War Room: full-screen Canvas 2D RTS map
  |-- Scenarios: behavioral test runner dashboard

Backend (FastAPI)
  |-- /api/cameras, /api/videos, /api/zones, /api/assets
  |-- /api/amy/* (status, thoughts SSE, chat, commands, video)
  |-- /api/amy/simulation/* (targets, spawn, remove)
  |-- /api/targets/* (unified tracker, hostiles, friendlies)
  |-- /api/game/* (begin, state, reset, place)
  |-- /api/ai/analyze (YOLO pipeline)
  |-- /ws/live (WebSocket event bus + TelemetryBatcher)
  |-- SQLite + FTS5 (events, zones, assets, targets)

Robot Templates (examples/)
  |-- robot-template/ (Python + MQTT, any hardware)
  |     |-- brain/ (thinker LLM, vision_bridge YOLO→LLM, nav_planner GPS↔game, MQTT client)
  |     |-- hardware/ (base interface, simulated LiPo+thermal+IMU, GPIO stub)
  |     `-- tests/ (protocol compat, thinker, hardware)
  |-- ros2-robot/ (ROS2 Humble + MQTT, Nav2 navigation)
        |-- ros2_robot/ (MQTT bridge, Nav2 client, telemetry, sim odom, camera node)
        |-- config/ (robot_params.yaml — all configurable)
        |-- launch/ (robot.launch.py)
        `-- tests/
```

---

## Design Principles

1. **Real and virtual are peers.** A simulated rover and a real camera produce
   events through the same pipeline. Amy does not distinguish.

2. **Amy is autonomous.** She observes, thinks, and acts on her own schedule.
   The operator provides guidance, not commands.

3. **One-Straw philosophy.** Tend the garden. Set conditions for emergence.
   Do not micromanage every patrol route and firing solution.

4. **Cyberpunk aesthetic.** Neon on dark. ASCII art. Glitch effects. The
   terminal is a window into a world that feels alive.

5. **No frameworks.** Vanilla JavaScript, raw WebSocket, hand-rolled CSS.
   The system is transparent down to every pixel and packet.
