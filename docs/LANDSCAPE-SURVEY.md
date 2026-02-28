# TRITIUM-SC Landscape Survey

**Date**: 2026-02-21 | **Scope**: 12 research domains, 150+ projects evaluated

> This document is the result of a comprehensive market research survey across 12 domains relevant to TRITIUM-SC. Each section identifies what exists, what to adopt, what to skip, and why. The goal: don't reinvent worse versions of components — use what's available to leapfrog.

---

## Table of Contents

1. [NVR/DVR & Camera Systems](#1-nvrdvr--camera-systems)
2. [OSINT & Intelligence Platforms](#2-osint--intelligence-platforms)
3. [AI Vision & Activity Recognition](#3-ai-vision--activity-recognition)
4. [Person & Vehicle Re-Identification](#4-person--vehicle-re-identification)
5. [Anomaly Detection & Pattern-of-Life](#5-anomaly-detection--pattern-of-life)
6. [Smart Home & Automation Platforms](#6-smart-home--automation-platforms)
7. [Three.js UIs & 3D Visualization](#7-threejs-uis--3d-visualization)
8. [Browser RTS Games & C2 Interfaces](#8-browser-rts-games--c2-interfaces)
9. [Operational Dashboards](#9-operational-dashboards)
10. [Simulation & Digital Twins](#10-simulation--digital-twins)
11. [LLM Agents & Cognitive Architectures](#11-llm-agents--cognitive-architectures)
12. [MQTT & IoT Mesh Patterns](#12-mqtt--iot-mesh-patterns)
13. [Master Adoption Plan](#13-master-adoption-plan)
14. [What TRITIUM-SC Has That Nobody Else Does](#14-what-tritium-sc-has-that-nobody-else-does)

---

## 1. NVR/DVR & Camera Systems

### Gold Standard: Frigate NVR

| | |
|---|---|
| **GitHub** | [blakeblackshear/frigate](https://github.com/blakeblackshear/frigate) |
| **Stars** | 30,400 |
| **License** | MIT |
| **Stack** | TypeScript (52%), Python (46%) |

Frigate is the uncontested leader. Its architecture is the single most relevant reference for TRITIUM-SC.

**What Frigate does that we should adopt:**

| Capability | How Frigate Does It | TRITIUM-SC Status |
|---|---|---|
| Motion pre-filter | OpenCV MOG2 before YOLO — 90% reduction in inference | Missing |
| Per-camera process isolation | Multiprocessing + SharedMemory ring buffer | Missing (single-threaded) |
| Object lifecycle events | `new` → `update` → `end` over MQTT with full state | Partial (TrackedTarget) |
| Zone-based counting | Per-zone object counts on dedicated MQTT topics | Partial (zones exist) |
| Stationary object optimization | Skip detection on motionless objects | Missing |
| PTZ auto-tracking | Track detected objects with PTZ camera | Missing |
| Audio detection | Classify audio events (speech, bark, alarm) | Missing |
| GenAI intent analysis | Multi-frame lifecycle sent to LLM, not single snapshot | Missing (single frame) |
| Camera watchdog | Auto-restart crashed FFmpeg/capture processes | Missing |
| Review timeline | Browsable event timeline with thumbnails | Missing |

**Other NVR projects evaluated:**

| Project | Stars | Verdict |
|---|---|---|
| Shinobi | 4,000 | Feature-complete but messy codebase, unmaintained plugin system |
| ZoneMinder | 5,200 | Legacy (Perl/C++), declining community, dated UI |
| Viseron | 1,100 | Python NVR, interesting but much smaller community than Frigate |
| Moonfire NVR | 600 | Rust-based, excellent performance, but recording-only (no AI) |

### Recommendation

Study Frigate's `video_processing_pipeline` architecture. Adopt: motion pre-filter, per-camera process isolation, multi-frame GenAI analysis, object lifecycle MQTT events. Don't wholesale adopt Frigate — our real+virtual entity fusion is something Frigate cannot do.

---

## 2. OSINT & Intelligence Platforms

### The Reality: No "Free Palantir" Exists

Every project claiming to be a "free Palantir" falls short. The actual need is 3-5 specialized components:

| Component | Recommended | Stars | License | What It Does |
|---|---|---|---|---|
| **Graph DB** | Memgraph or Neo4j CE | 4k / 14k | BSL / GPL | Entity relationships (POLE model) |
| **Event Storage** | OpenSearch | 11k | Apache 2.0 | Events + built-in anomaly detection (RCF) |
| **Intelligence Framework** | OpenCTI | 8,800 | Apache 2.0 | STIX 2.1 entity model, GraphQL API |
| **License Plate** | fast-alpr | 500+ | MIT | ONNX-based, actively maintained |
| **Link Analysis** | Gephi / Cytoscape.js | 6k / 10k | GPL / MIT | Visual graph exploration |

**Evaluated and rejected:**

| Project | Stars | Why Skip |
|---|---|---|
| SpiderFoot | 13,000 | OSINT aggregator, not intelligence platform. Stale |
| Maltego | N/A | Proprietary. Expensive |
| FIWARE | 1,500 | Enterprise IoT middleware, wrong domain |
| TheHive | 10,000 | Incident response, not intelligence analysis |
| Shuffle | 1,200 | SOAR workflow, not relevant |

### POLE Model (Person-Object-Location-Event)

The law enforcement standard for entity resolution. Nodes: Person, Object (vehicle, phone), Location, Event. Edges: "was seen at", "drives", "called", "lives at". Neo4j or Memgraph handles this natively with Cypher queries.

**Integration path for TRITIUM-SC:**
- Detection events → Entity DB (person/vehicle embeddings with timestamps + locations)
- Recurring entity detection → Link analysis (co-occurrence graphs)
- Pattern queries: "Who was seen at Location X more than 3 times this week?"

---

## 3. AI Vision & Activity Recognition

### Detection: Upgrade Path

| Model | COCO mAP | Latency | License | Migration |
|---|---|---|---|---|
| YOLOv8n (current) | 37.3% | ~1.3ms | AGPL-3.0 | — |
| **YOLO11n** | 39.5% | ~1.5ms | AGPL-3.0 | 1-line change |
| YOLOv12n | 40.6% | ~1.6ms | AGPL-3.0 | New repo |
| YOLO26n | ~40% | 43% faster CPU | AGPL-3.0 | Same Ultralytics API |
| **RF-DETR-B** | 53.3% | ~4.5ms | **Apache 2.0** | Different API |
| RF-DETR-L | **60.5%** | ~40ms | Apache 2.0 | SOTA accuracy |

**Immediate action**: `yolov8n.pt` → `yolo11n.pt` — same API, better mAP, one-line change.

### Tracking: Upgrade Path

| Tracker | HOTA (MOT17) | Re-ID | Migration |
|---|---|---|---|
| ByteTrack (current) | 63.1 | No | — |
| **BoT-SORT** | 64.6 | Yes | 1-line change (`botsort.yaml`) |
| Deep OC-SORT | 64.9 | Yes | Separate library |

**Immediate action**: `bytetrack.yaml` → `botsort.yaml` — built into Ultralytics. Enable `with_reid: True` in `botsort.yaml` for free within-camera track recovery (reuses YOLO features, zero additional compute). Cross-camera Re-ID requires separate OSNet model (see Section 4).

### Activity Recognition: 3-Layer Architecture

| Layer | What | Model | Cost | When |
|---|---|---|---|---|
| L1: Rule-based | Loitering, speed, zone dwell | None (tracker data) | Zero GPU | Always on |
| L2: Pose-based | Standing/walking/running/falling | **RTMPose-m** (430 FPS) | Low | On detected persons |
| L3: Video LLM | "What is this person doing?" | **Qwen3-VL-8B** via Ollama | High | On alert only |

**Key models:**

| Model | What | Stars | License | Speed | Jetson |
|---|---|---|---|---|---|
| **RTMPose-m** (MMPose) | Pose estimation | 5,600 | Apache 2.0 | 430 FPS GPU | Yes |
| **X3D-M** (MMAction2) | Activity classification | 4,700 | Apache 2.0 | 4.97 GFLOPs | Yes |
| **YOLO-World** | Open-vocabulary detection | 5,100 | GPL-3.0 | 52 FPS | Yes |
| **Grounding DINO 1.5** | Text-prompted detection | 9,700 | Apache 2.0 | 75 FPS Edge | Yes |
| **Qwen3-VL-8B** | Video understanding LLM | — | Apache 2.0 | Via Ollama | 8GB VRAM |

### Open-Vocabulary Detection (Game Changer)

**YOLO-World** detects objects by text description without retraining: "person carrying backpack near fence", "delivery truck stopped", "open gate". Deploy alongside standard YOLO for contextual queries triggered by events.

### Video Analytics Toolkit

**Supervision** (Roboflow) — 25k stars, MIT license. Wraps trackers with zone counting, line crossing, heatmaps. Replace our custom `SimpleTracker`.

### Production Edge Budget

YOLO11n + BoT-SORT + RTMPose-m = ~10ms/frame = **100 FPS capacity** on Jetson Orin. TensorRT FP16 export via `model.export(format="engine", half=True)` for 2-4x additional speedup.

---

## 4. Person & Vehicle Re-Identification

### The Problem

Track the same person across multiple cameras and over days/weeks. Know who the "regulars" are.

### Recommended Models

| Model | Params | Market1501 Rank-1 | License | Edge-Ready |
|---|---|---|---|---|
| **OSNet x1.0** (Torchreid) | 2.2M | 94.8% | MIT | Yes |
| ResNet50 (FastReID) | 25M | 95.4% | Apache 2.0 | Yes (TensorRT) |
| TransReID | ~87M | 95.1% | MIT | Server only |

### Architecture

```
Camera 1 → YOLO + BoT-SORT → Local tracks → OSNet embedding ─┐
Camera 2 → YOLO + BoT-SORT → Local tracks → OSNet embedding ─┤→ Cosine match → Global ID
Camera 3 → YOLO + BoT-SORT → Local tracks → OSNet embedding ─┘
```

### Privacy-Preserving Approach (Critical for Neighborhood Use)

Don't store faces. Use **soft biometrics**:
- Clothing color histogram (upper/lower body)
- Height estimate from skeleton
- Gait signature (stride length, arm swing frequency)
- Body shape ratio (shoulder width / height)

These enable re-ID without facial recognition. Combine with zone+time correlation for higher accuracy.

### Vehicle Re-ID

- **fast-alpr** (MIT, ONNX) — license plate recognition, actively maintained
- VehicleNet / VeRi models — appearance-based vehicle matching
- Color + make + model classification via fine-tuned YOLO or CLIP

### Gallery Architecture (FAISS + SQLite)

The production pattern for cross-camera Re-ID is a **gallery database**:

```
Camera N → YOLO → Crop → Re-ID embedding → Gallery Search
                                                  │
                                    sim > 0.7 → Match (update entity)
                                    sim < 0.5 → New entity
                                    0.5-0.7  → Hold for multi-observation confirmation
```

| Vector Search | Stars | Type | Fit |
|---|---|---|---|
| **FAISS** | 33,000 | In-memory index | Best for <100K entities (neighborhood scale) |
| sqlite-vss | ~1,000 | SQLite extension | Pairs with existing SQLite DB |
| Qdrant | 23,000 | Vector DB server | Overkill for our scale |

**Recommendation**: FAISS (`pip install faiss-cpu`) with SQLite for metadata. Add `reid_gallery` table: `entity_id, embedding BLOB, entity_type, first_seen, last_seen, sighting_count, cameras_seen, description TEXT`. At neighborhood scale, brute-force FAISS search is <1ms per query.

### Optional: Face + License Plate Recognition

| System | Stars | License | Use Case |
|---|---|---|---|
| **InsightFace-REST** | 601 | Apache 2.0 | GPU-accelerated face recognition as Docker sidecar |
| **DeepFace** | 22,200 | MIT | Richest features + homomorphic encryption for privacy |
| **fast-alpr** | 414 | MIT | ONNX license plate recognition |

Face recognition OFF by default — opt-in only for consenting household members.

### Privacy Tiers (Critical for Neighborhood Deployment)

| Level | What | Legal Risk |
|---|---|---|
| **L0 (default)** | YOLO detection + per-camera tracking only | Minimal |
| **L1 (opt-in)** | Body Re-ID embeddings (OSNet), auto-expire 7 days | Low |
| **L2 (owner)** | Face recognition for consenting household members | Moderate |
| **L3 (disabled)** | Full biometric tracking — requires legal review | High |

All levels: local storage only, auto-expire, audit logging, "forget entity" for GDPR right to erasure.

### Reference System: SharpAI DeepCamera

[SharpAI/DeepCamera](https://github.com/SharpAI/DeepCamera) (2,300 stars, MIT) — closest existing project to our Re-ID architecture. YOLOv7 + FastReID + Milvus gallery + self-supervised learning. Runs on Jetson Nano. Study this closely for implementation patterns.

### Integration with TRITIUM-SC

Add `reid_embedding: list[float]` to `TrackedTarget`. Extend MQTT detection messages with embedding field. Cross-camera matching in `TargetTracker` using cosine similarity > 0.7 threshold. Natural integration point: `TargetTracker.update_from_detection()` in `src/engine/tactical/target_tracker.py`.

---

## 5. Anomaly Detection & Pattern-of-Life

### What "Normal" Means

Build a per-zone, per-time baseline of activity:
- **Frequency baseline**: Poisson model — "5 people/hour is normal for this sidewalk at 3pm"
- **Trajectory baseline**: MovingPandas clusters — "people normally walk north-south on this path"
- **Appearance baseline**: Co-occurrence graph — "this person walks the dog here every morning"

### Detection Methods

| Method | Training Data | GPU | Best For |
|---|---|---|---|
| Poisson baseline | 1 week of counts | None | Frequency anomalies |
| **AnyAnomaly** (WACV 2026) | **None (zero-shot)** | LVLM | Custom text-defined anomalies |
| Anomalib (Intel, PatchCore) | Normal images only | Moderate | Frame-level visual anomaly |
| STG-NF | Skeleton sequences | Moderate | Behavioral anomaly (privacy-preserving) |
| MovingPandas | GPS/position tracks | None | Trajectory clustering |

### AnyAnomaly — Zero-Shot Anomaly Detection

Define anomalies as text: "person climbing fence", "car driving on sidewalk". Feed video segments + prompts to LVLM. No training data required. Maps directly to Amy's existing Ollama integration.

### Concrete Pipeline

```
1. Detection → YOLO + BoT-SORT
2. Soft Re-ID → OSNet embedding → Entity DB
3. Frequency Counting → Poisson baseline per zone per hour
4. Trajectory Analysis → MovingPandas clustering
5. Co-occurrence → NetworkX graph with Louvain community detection
6. Anomaly Scoring → Deviation from baselines
7. Alert → Only when anomaly score exceeds threshold
```

### Key Library

| Library | Stars | License | What |
|---|---|---|---|
| **Anomalib** (Intel) | 4,000 | Apache 2.0 | Unified anomaly detection (PaDiM, PatchCore, CFlow) |
| **MovingPandas** | 1,400 | BSD | Trajectory analysis on GeoPandas |
| **NetworkX** | 15,000 | BSD | Graph analysis for co-occurrence patterns |

---

## 6. Smart Home & Automation Platforms

### Patterns to Adopt (Not Platforms)

We don't need Home Assistant — we need its **patterns**:

#### Pattern 1: Entity Registry (from HA)

Persistent registry with `unique_id + device_info + area + category`. State changes fire `state_changed` events. JSON persistence with debounced writes. Hierarchy: Floor → Area → Device → Entity.

**TRITIUM-SC integration**: Wrap `TargetTracker` in an `EntityRegistry` that persists to `data/registry.json`.

#### Pattern 2: MQTT Auto-Discovery (from HA + Zigbee2MQTT)

Devices publish retained config to `tritium/{site}/discovery/{id}/config`:
```json
{
  "device_id": "rover-alpha",
  "device_type": "robot",
  "capabilities": ["telemetry", "camera", "turret"],
  "topics": {
    "telemetry": "tritium/home/robots/rover-alpha/telemetry",
    "command": "tritium/home/robots/rover-alpha/command"
  }
}
```

Robots self-register. No manual configuration.

#### Pattern 3: Trigger-Condition-Action Rules (from HA)

User-configurable JSON rules evaluated by a `RuleEngine` on EventBus:
```json
{
  "triggers": [{"type": "zone_enter", "zone": "perimeter", "alliance": "hostile"}],
  "conditions": [{"type": "game_state", "state": "active"}],
  "actions": [{"type": "lua_command", "command": "dispatch('rover_01', target.x, target.y)"}]
}
```

#### Pattern 4: Device Capability Exposes (from Zigbee2MQTT)

Structured capability advertisement: what can this device read/write? What actions does it support?

#### Pattern 5: MixinProvider (from Scrypted)

Composable device enhancement: add AI analysis to any camera without modifying node code.

#### Pattern 6: Motion Pre-Filter (from Frigate)

OpenCV MOG2 before YOLO. 90%+ reduction in inference cost.

### Priority Ranking

1. MQTT Discovery Protocol — plug-and-play robots/sensors
2. Entity Registry — persistent queryable entity management
3. Trigger-Condition-Action rules — user automation
4. Motion pre-filter — GPU cost reduction
5. Multi-frame GenAI — lifecycle analysis, not single snapshots

---

## 7. Three.js UIs & 3D Visualization

### Drop-In Libraries (Vanilla JS, No React)

| Library | Stars | License | What | Priority |
|---|---|---|---|---|
| **troika-three-text** | 1,900 | MIT | SDF text for unit labels, health bars | High |
| **drei-vanilla** | 592 | MIT | Billboard, Trail, Outlines, Grid helpers | High |
| **Tweakpane** | 4,400 | MIT | Debug/config panels (zero deps) | High |
| **postprocessing** (pmndrs) | 2,700 | Zlib | Bloom/glow for cyberpunk aesthetic | High |
| **Dockview Core** | 3,000 | MIT | Dockable panel layout (vanilla TS, v5.0) | High |
| **three.quarks** | 761 | MIT | Particle VFX (projectiles, explosions) | Medium |
| **@pmndrs/uikit** | 3,100 | MIT | 3D UI components (flexbox in Three.js) | Medium |
| **stats-gl** | 259 | MIT | GPU/CPU perf monitor (replaces stats.js) | Medium |
| **Theatre.js** | 12,200 | Apache 2.0 | Cinematic camera sequences | Future |

### Aesthetic Reference: Arwes (7.5k stars, MIT)

[Arwes](https://github.com/arwes/arwes) is the closest existing open source project to our CYBERCORE visual language — SVG-based frame components (corners, hexagons, pentagons), animation orchestration, and built-in bleeps/sound effects. Still in alpha — **study source code for SVG frame generation patterns but do not take a dependency**. The vanilla packages (`@arwes/frames`, `@arwes/animator`, `@arwes/bleeps`) have no React dependency.

### 3D Map Layer Architecture

For the Three.js upgrade, the recommended stack is:

| Layer | Solution | What It Does |
|---|---|---|
| Map tiles | **geo-three** or **MapLibre GL** custom layer | Satellite tile LOD on flat plane |
| 3D helpers | **drei-vanilla** | Billboard labels, Trail paths, Outlines, Grid |
| HTML overlays | **CSS2DRenderer** (built-in) | Unit labels positioned in 3D, styled with CYBERCORE CSS |
| Panel layout | **Dockview Core** | Drag-and-drop panel docking, layout save/load |
| Debug | **Tweakpane** + **stats-gl** | Dev overlay (sim tick rate, camera state, GPU timing) |

### Architecture Patterns

- **ProtectWise/Troika** (by TRON: Legacy FX artist) — "entities as buildings" metaphor, data-driven 3D mapping
- **deck.gl** (13.9k stars) — composable layer architecture. TripsLayer for movement animation
- **globe.gl** — independently data-bound layers (points + arcs + custom). Pattern for overlaying units/threats/waypoints

### Map Viewers for Three.js

| Library | Stars | License | Best For |
|---|---|---|---|
| **geo-three** | 815 | MIT | Satellite tile LOD + terrain for Three.js |
| **iTowns** | 1,200 | MIT | Full 3D geospatial on Three.js |
| **three-geo** | 500 | MIT | One-liner GPS-to-3D terrain |
| **Threebox** | — | — | Three.js ↔ Mapbox camera sync |

### WebGPU Status

Three.js r171+ (Sep 2025) supports WebGPU with auto WebGL2 fallback. TSL (Three Shading Language) replaces GLSL. Compute shaders: 100k+ particles at <2ms (150x over CPU particles). Production-deployed at Expo 2025 Osaka.

---

## 8. Browser RTS Games & C2 Interfaces

### Closest Reference Projects

| Project | Stars | License | Why It Matters |
|---|---|---|---|
| **CloudTAK** | 85 | AGPL-3.0 | Browser TAK client — closest thing to what we're building |
| **GoATAK** | 178 | AGPL-3.0 | "Big screen" command center with Milsymbol + video feeds |
| **NASA OpenMCT** | 12,800 | Apache 2.0 | Gold standard drag-and-drop panel composition |
| **Panopticon AI** | 68 | Apache 2.0 | Military wargaming + OpenAI Gym RL training |

### Drop-In Libraries

| Library | Stars | License | What | Priority |
|---|---|---|---|---|
| **Milsymbol** | 715 | MIT | NATO MIL-STD-2525 symbol rendering | High |
| **geo-three** | 815 | MIT | Three.js satellite tile LOD + terrain | High |
| **PathFinding.js** | 8,700 | MIT | 10 pathfinding algorithms | Medium |
| **node-CoT** | ~30 | MIT | CoT/TAK protocol bridge | Future |

### RTS Game References

| Game | Stars | License | Key Pattern |
|---|---|---|---|
| **SC_Js** (StarCraft) | 590 | MIT | Complete RTS in vanilla JS + Canvas 2D. Fog of war, minimap, replay |
| **Voidcall** | 380 | MIT | RTS in 13KB. Zero-allocation A* with TypedArrays |
| **Freeciv-Web** | 2,100 | GPL/AGPL | Dual renderer (Canvas 2D + Three.js) — same pattern as us |
| **C&C HTML5** | 797 | — | Unit AI FSM patterns for behaviors |

### TAK Interoperability (Future)

```
ATAK device → CoT XML → FreeTAKServer → node-CoT → GeoJSON → TRITIUM-SC WebSocket → War Room
```

The entire chain is open source.

---

## 9. Operational Dashboards

### NASA OpenMCT (12.8k stars, Apache 2.0)

The gold standard for mission control dashboards. Used for real Mars missions (InSight, Mars Cube One).

**Key architecture patterns:**

| Pattern | What | TRITIUM-SC Application |
|---|---|---|
| **Domain Object Model** | Every entity is a typed object with composite identifier | Map robots/cameras/targets to domain objects in unified tree nav |
| **Time Conductor** | Centralized temporal state — all views share time range | Switch between live sim and historical replay simultaneously |
| **Telemetry Provider** | `subscribe()` for real-time, `request()` for historical | Matches our WebSocket + REST API dual approach |
| **LAD Table** | "Latest Available Data" — always shows most recent value per point | Exactly what our unit status panel needs |
| **Display Layout** | Pixel-based absolute positioning for wall displays | For tactical map overlay precision |
| **Flexible Layout** | Resizable rows/columns (flexbox as UX) | For general panel arrangement |

### Cockpit Channel Multiplexing (12.7k stars, LGPL)

Cockpit's **single-WebSocket channel protocol** is directly relevant:

```json
{"channel": "sim_telemetry", "data": {...}}
{"channel": "amy_events", "data": {...}}
{"channel": "game_state", "data": {...}}
{"channel": "alerts", "data": {...}}
```

Enables: per-channel subscribe/unsubscribe, priority, flow control (ping/pong window), new data types without protocol changes. Our `/ws/live` currently mixes all data on one unstructured stream.

### Uptime Kuma Notification Provider Pattern (71k+ stars, MIT)

Clean plugin architecture for notification channels:

```python
class NotificationProvider(ABC):
    @abstractmethod
    async def send(self, alert, context): ...

class DiscordProvider(NotificationProvider):
    async def send(self, alert, context):
        # Post to Discord webhook
```

90+ providers built on this pattern. Adopt for our `escalation.py` alert routing.

### Other Dashboard References

| Project | Stars | Key Pattern | Relevance |
|---|---|---|---|
| **Grafana** | 72,300 | 24-column grid layout JSON, data frame abstraction, alert rule evaluation | HIGH |
| **Uptime Kuma** | 71,000+ | Socket.IO bidirectional events, heartbeat bar visualization | HIGH |
| **Cockpit** | 12,700 | WebSocket channel multiplexing, bridge pattern, zero-idle design | HIGH |
| **Tactical RMM** | 4,100 | Go agent + NATS messaging (maps to MQTT), live command streaming | MEDIUM-HIGH |
| **Netdata** | 76,300 | Edge-first agent architecture, 1s collection, streaming hierarchy | MEDIUM |
| **Dashy** | 24,000 | CSS variable theming system, 25+ built-in themes | LOW-MEDIUM |

---

## 10. Simulation & Digital Twins

### Verdict: Keep Custom SimulationEngine

Our ~2,000 lines of purpose-built Python outperform any framework adoption:

| Framework | Why Skip |
|---|---|
| Mesa (Python ABM) | Same architecture as ours. Adds abstraction, loses EventBus integration |
| Gazebo + ROS2 | Physics overkill. Our entities aren't rigid bodies |
| MuJoCo / PyBullet | Joint dynamics we don't need |
| Isaac Sim | Requires RTX GPU, massive footprint |
| Eclipse Ditto | Java/Akka enterprise middleware for millions of devices |
| FIWARE | AGPL, MongoDB, 10+ containers for what we do in one process |
| Godot (web) | Full rewrite in GDScript, 20-40MB WASM |

### Visualization Upgrade Path

| Option | Bundle Size | Terrain | Best For |
|---|---|---|---|
| **Canvas 2D** (current) | 0 | No | Maximum VFX control, cyberpunk aesthetic |
| **MapLibre GL** | ~300KB | Yes | Next upgrade: satellite + 3D terrain + Three.js plugin |
| **CesiumJS** | ~4MB | Yes | Multi-site strategic globe view |

**Recommendation**: Stay with Canvas 2D. Keep **MapLibre GL JS** (BSD, 7.5k stars) as upgrade path.

---

## 11. LLM Agents & Cognitive Architectures

### Amy's Architecture is Validated

Amy maps to established cognitive science patterns:

| Amy Component | Classical Pattern | Theory |
|---|---|---|
| Sensorium | Global Workspace | LIDA / Global Workspace Theory |
| Perception L0-L4 | Observe-Decide-Act | ACT-R buffer model |
| ThinkingThread | Deliberation | SOAR decision cycle |
| GoalStack | Goal buffer | ACT-R goal management |
| EventBus + Sensorium | Blackboard | HEARSAY-II architecture |

### Verdict: Do NOT Adopt a Framework

No framework supports continuous 10Hz perception + sensor fusion + physics sim + embodied motor control:

| Framework | Stars | Why Skip |
|---|---|---|
| LangGraph | 24,900 | Request/response, no continuous loop |
| CrewAI | 44,400 | Task-based execution, no sensor integration |
| AutoGen | 54,700 | Conversation-turn based, CC-BY-4.0 license |
| MetaGPT | 64,300 | Software engineering automation, wrong domain |
| smolagents (HF) | 25,500 | Code-as-action validates our Lua approach, but step-based |

### What to Borrow

| Component | Source | Why |
|---|---|---|
| **Structured memory** | ChromaDB / Qdrant | Replace JSON file memory with semantic search for `recall()` |
| **MCP tool definitions** | Standard protocol | Future-proof Amy's Lua actions |
| **Replanning** | Embodied AI research | Verify if dispatched actions succeeded (closed-loop) |

### Key Gap: Replanning

Amy doesn't verify action outcomes. She dispatches a rover but never checks if the intercept succeeded. Closed-loop outcome verification would be the most impactful upgrade to her cognitive loop.

---

## 12. MQTT & IoT Mesh Patterns

### Broker: Keep Mosquitto

Our peak load (~38 KB/s, 20 robots + 10 cameras) is <1% of Mosquitto's capacity. No reason to switch.

### Topic Design: Our Convention is Validated

The `tritium/{site}/{category}/{device_id}/{action}` hierarchy follows AWS IoT Core best practices.

### What to Add

| Addition | Effort | Impact |
|---|---|---|
| **MQTT Discovery topic** (retained config) | 1-2 days | Plug-and-play device registration |
| **UUID command IDs** | 2 hours | Robust ACK correlation |
| **Telemetry buffer** (store-and-forward) | 4 hours | No data loss during WiFi dropouts |
| **TLS on Mosquitto** | 4 hours | Encrypted transport |
| **ACLs** | 1 day | Topic-level authorization |

### What NOT to Adopt

| Thing | Why |
|---|---|
| Sparkplug B | Protobuf + SCADA model, overkill for JSON system |
| EMQX / NanoMQ | Mosquitto handles our load at 1% capacity |
| EdgeX / K3s / KubeEdge | Container orchestration for 50+ nodes, we have 1-2 |
| aiomqtt | Architecture mismatch (threads, not asyncio) |
| QoS 2 | Our commands are idempotent, QoS 1 sufficient |

---

## 13. Master Adoption Plan

### Key Architectural Patterns to Adopt

| # | Pattern | Source | Impact |
|---|---|---|---|
| 1 | Domain object model — typed entities with composite IDs | OpenMCT | Unified entity tree nav |
| 2 | Time conductor — centralized temporal state manager | OpenMCT | Live/replay mode sync |
| 3 | Grid layout JSON — `gridPos` (x,y,w,h) panel persistence | Grafana | Save/load/share layouts |
| 4 | WebSocket channel multiplexing — channel IDs per data stream | Cockpit | Priority, subscribe/unsubscribe |
| 5 | Notification provider plugins — `send()` base class | Uptime Kuma | Extensible alert routing |
| 6 | Motion pre-filter — MOG2 before YOLO | Frigate | 90% GPU reduction |
| 7 | MQTT discovery — retained config for auto-registration | HA | Plug-and-play devices |
| 8 | Gallery probe/match — FAISS + cosine similarity > threshold | SharpAI | Cross-camera Re-ID |

### Phase 1: One-Line Changes (This Week)

| Change | File | Current | New |
|---|---|---|---|
| Detection model | `src/app/ai/detector.py` | `yolov8n.pt` | `yolo11n.pt` |
| Tracker | `src/app/ai/detector.py` | `bytetrack.yaml` | `botsort.yaml` |
| TensorRT export | — | PyTorch | `model.export(format="engine", half=True)` |

### Phase 2: Low-Effort High-Value (1-2 Weeks)

| Addition | Effort | Impact |
|---|---|---|
| Loitering detection in TargetTracker | 50 lines | Dwell time per zone alerts |
| MQTT Discovery protocol | 1-2 days | Plug-and-play robots/sensors |
| UUID command IDs | 2 hours | Robust ACK correlation |
| Telemetry buffer in robot template | 4 hours | WiFi dropout resilience |
| TLS on Mosquitto | 4 hours | Transport encryption |
| Milsymbol for NATO icons | 20 lines | Toggle cyberpunk/NATO display |

### Phase 3: Behavioral Layer (2-4 Weeks)

| Addition | Model/Library | Where |
|---|---|---|
| Pose estimation | RTMPose-m (Apache 2.0) | New: `src/amy/brain/pose.py` |
| Rule-based behaviors | Tracker data (no model) | `src/engine/tactical/escalation.py` |
| Statistical baseline | Poisson counts per zone/hour | New: `src/engine/tactical/baseline.py` |
| Entity Registry | HA-inspired pattern | Wrap `TargetTracker` |
| Supervision library | Roboflow (MIT) | Replace `SimpleTracker` |
| Motion pre-filter | OpenCV MOG2 | `src/app/ai/detector.py` |

### Phase 4: Video Understanding (2-4 Weeks)

| Addition | Model/Library | Where |
|---|---|---|
| Video LLM | Qwen3-VL-8B via Ollama | `src/amy/brain/vision.py` |
| Multi-frame analysis | Frigate lifecycle pattern | `src/amy/brain/sensorium.py` |
| YOLO-World | Open-vocab detection | Event-triggered |
| Activity classification | X3D-M via MMAction2 + TensorRT | New: `src/amy/brain/activity.py` |
| Trigger-Condition-Action rules | HA-inspired JSON rules | New: `src/engine/tactical/rules.py` |

### Phase 5: Re-Identification (4-8 Weeks)

| Addition | Model/Library | Where |
|---|---|---|
| Person ReID embeddings | OSNet (MIT, 2.2M params) | New: `src/engine/tactical/reid.py` |
| Cross-camera matching | Cosine similarity | `src/engine/tactical/target_tracker.py` |
| Vehicle LPR | fast-alpr (MIT, ONNX) | New integration |
| Entity graph | Neo4j CE or Memgraph | New: entity persistence |
| Trajectory clustering | MovingPandas | New: pattern analysis |

### Phase 6: 3D Visualization (When Ready)

| Addition | Library | Priority |
|---|---|---|
| SDF text rendering | troika-three-text | High |
| Bloom/glow effects | pmndrs/postprocessing | High |
| Particle VFX | three.quarks | Medium |
| Satellite tile LOD | geo-three | Medium |
| 3D terrain | three-geo or MapLibre GL | Medium |
| 3D UI panels | @pmndrs/uikit | Low |

---

## 14. What TRITIUM-SC Has That Nobody Else Does

After surveying 150+ projects across 12 domains, here's what makes TRITIUM-SC unique:

| Capability | TRITIUM-SC | Closest Alternative | Gap |
|---|---|---|---|
| **Real + virtual entity fusion** | Same tactical map, same APIs, same event bus | None | Nobody else does this |
| **Autonomous AI Commander** | Amy: 4-layer cognition, continuous inner monologue, Lua dispatch | CrewAI (task-based) | Amy is continuous, not task-based |
| **Simulation-driven security** | Nerf battlefield game drives real security capabilities | None | Unique framing |
| **LLM-powered robot thinking** | RobotThinker generates Lua actions via small local models | SayCan (Google) | We run on edge with 7B models |
| **Integrated combat system** | 10-wave game with projectile physics, kill streaks, commentary | Browser RTS games | No game integrates real sensors |
| **Multi-model routing** | ModelRouter with fleet fallback, task-aware selection | Open Claw | Our fleet is MQTT-connected |
| **Privacy-preserving design** | All local, no cloud, soft biometrics | Gladys (basic) | We have full AI pipeline locally |

The landscape survey confirms: **no single project covers what TRITIUM-SC does**. The closest analogs are CloudTAK (tactical map) + Frigate (camera AI) + Home Assistant (automation) + a browser RTS game — but nobody has combined them into a unified system with an autonomous AI commander. The path forward is to adopt the best patterns from each domain while preserving the unique integration that makes TRITIUM-SC what it is.

---

## Sources

Full source URLs are documented in each agent's research transcript. Key repositories:

- [Frigate NVR](https://github.com/blakeblackshear/frigate) — Camera architecture reference
- [Home Assistant](https://github.com/home-assistant/core) — Entity model, MQTT discovery, automation
- [Ultralytics](https://github.com/ultralytics/ultralytics) — YOLO11, BoT-SORT, pose estimation
- [NASA OpenMCT](https://github.com/nasa/openmct) — Dashboard panel composition
- [Supervision](https://github.com/roboflow/supervision) — Video analytics toolkit
- [Torchreid](https://github.com/KaiyangZhou/deep-person-reid) — OSNet person re-ID
- [MMAction2](https://github.com/open-mmlab/mmaction2) — Activity recognition
- [MMPose](https://github.com/open-mmlab/mmpose) — RTMPose pose estimation
- [OpenCTI](https://github.com/OpenCTI-Platform/opencti) — STIX 2.1 intelligence
- [CloudTAK](https://github.com/dfpc-coe/CloudTAK) — Browser tactical awareness
- [Milsymbol](https://github.com/spatialillusions/milsymbol) — NATO military symbology
- [Anomalib](https://github.com/openvinotoolkit/anomalib) — Visual anomaly detection
- [troika](https://github.com/protectwise/troika) — Three.js text + data visualization
- [geo-three](https://github.com/tentone/geo-three) — Three.js satellite tiles
- [fast-alpr](https://github.com/ankandrew/fast-alpr) — License plate recognition
