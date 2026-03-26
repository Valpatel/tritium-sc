# TRITIUM-SC Documentation

**Where you are:** `tritium-sc/docs/` — design documents, specs, and guides for the Command Center.

**Parent:** [../CLAUDE.md](../CLAUDE.md) | [../../CLAUDE.md](../../CLAUDE.md) (tritium root)

## Navigation

```
tritium/
└── tritium-sc/               ← YOU ARE HERE
    ├── CLAUDE.md             # Dev conventions, operating principles, API reference
    ├── README.md             # Project overview, quick start
    ├── docs/                 # ← This index
    ├── src/
    │   ├── engine/README.md  # System infrastructure subsystems
    │   ├── amy/README.md     # AI commander architecture
    │   ├── app/README.md     # FastAPI backend
    │   └── frontend/README.md # Vanilla JS frontend
    ├── tests/README.md       # Test suite guide
    ├── plugins/README.md     # Plugin system
    └── examples/README.md    # Reference implementations
```

```mermaid
graph TB
    docs["docs/ (you are here)"]
    arch["Architecture & Design<br/>16 documents"]
    testing["Testing<br/>4 documents"]
    users["User Guides<br/>4 documents"]
    game["Game Design<br/>4 documents"]
    ops["Operations<br/>4 documents"]

    docs --> arch
    docs --> testing
    docs --> users
    docs --> game
    docs --> ops

    src["../src/ READMEs"]
    docs -.-> src
```

## For Users

| Document | Description |
|----------|-------------|
| [USER-STORIES.md](USER-STORIES.md) | Player experience stories and UI intent |
| [HOW-TO-PLAY.md](HOW-TO-PLAY.md) | Player guide: setup, gameplay, controls, strategy tips |
| [CONTROLS.md](CONTROLS.md) | Complete keyboard and gamepad control reference |
| [GAMEPAD.md](GAMEPAD.md) | Gamepad setup, calibration, and troubleshooting |

## Architecture

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture: layers, boot sequence, event flow, thread model |
| [PLAN.md](PLAN.md) | Development roadmap: phases, progress, technical architecture |
| [SIMULATION.md](SIMULATION.md) | Simulation engine: target lifecycle, spawners, tick loop |
| [SIMULATION-ARCHITECTURE.md](SIMULATION-ARCHITECTURE.md) | Simulation pipeline and data flow |
| [ESCALATION.md](ESCALATION.md) | Threat escalation: state machine, zones, dispatch decision tree |
| [MQTT.md](MQTT.md) | MQTT communication: topic hierarchy, payloads, device integration |
| [COORDINATE-SYSTEM.md](COORDINATE-SYSTEM.md) | Local coordinate transforms and geo-reference |
| [UNIFIED-SPEC.md](UNIFIED-SPEC.md) | Command Center data flow, render pipeline, API list |
| [UI-REDESIGN.md](UI-REDESIGN.md) | Command Center plugin architecture and layout |
| [WINDOW-MANAGER.md](WINDOW-MANAGER.md) | dockview-core window manager integration plan |
| [MODEL-ROUTING.md](MODEL-ROUTING.md) | Task-aware model selection and fleet discovery |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | MTIG monitoring stack (Mosquitto, Telegraf, InfluxDB, Grafana) |
| [MESHTASTIC.md](MESHTASTIC.md) | Mesh radio integration for outdoor operations |
| [LANDSCAPE-SURVEY.md](LANDSCAPE-SURVEY.md) | ML model evaluation and alternatives survey |
| [VISION.md](VISION.md) | Perception philosophy, dual-use design, privacy tiers, roadmap |
| [PLUGIN-SPEC.md](PLUGIN-SPEC.md) | Plugin system: interface, lifecycle, discovery, dependencies |
| [NPC-INTELLIGENCE.md](NPC-INTELLIGENCE.md) | NPC brain, FSM, personality, crowd dynamics, thought registry |
| [NPC-WORLD-BEHAVIOR.md](NPC-WORLD-BEHAVIOR.md) | NPC world population: routing, buildings, daily routines |
| [TAK.md](TAK.md) | TAK/ATAK integration and CoT protocol bridge |
| [TERRAIN-PLAN.md](TERRAIN-PLAN.md) | DEM terrain elevation and 3D terrain rendering plan |

## Testing

| Document | Description |
|----------|-------------|
| [TESTING-PHILOSOPHY.md](TESTING-PHILOSOPHY.md) | TDD principles and testing tiers |
| [TEST-AUTOMATION.md](TEST-AUTOMATION.md) | E2E automation patterns and visual regression |
| [UI-TESTING.md](UI-TESTING.md) | Visual regression testing with Playwright and OpenCV |
| [ITERATE-PROMPT.md](ITERATE-PROMPT.md) | Agent iteration prompt template |

## Operations

| Document | Description |
|----------|-------------|
| [AUDIT-GAPS.md](AUDIT-GAPS.md) | Infrastructure security audit findings |
| [UI-VIEWS.md](UI-VIEWS.md) | UI view specifications: design intent for every panel, button, and element |
| [WAR-ROOM-UX-REVIEW.md](WAR-ROOM-UX-REVIEW.md) | War Room frontend UX architecture review |
| [DEMO-SPEC.md](DEMO-SPEC.md) | Demo project specifications for MQTT device examples |

## Game Design

| Document | Description |
|----------|-------------|
| [MISSION-TYPES-SPEC.md](MISSION-TYPES-SPEC.md) | Mission types and gameplay mechanics |
| [FLEET-BACKSTORY-SPEC.md](FLEET-BACKSTORY-SPEC.md) | Fleet narrative and faction specifications |
| [GRAND-PLAN.md](GRAND-PLAN.md) | Long-range vision and strategic roadmap |
| [UX-ROADMAP.md](UX-ROADMAP.md) | UX improvements and feature ordering |

## UI Design

| Document | Description |
|----------|-------------|
| [UI-FEATURES-SPEC.md](UI-FEATURES-SPEC.md) | UI panel specifications and features |
| [UI-VIEWS.md](UI-VIEWS.md) | Design intent for every panel, button, and element |
| [UI-REDESIGN.md](UI-REDESIGN.md) | Command Center plugin architecture and layout |
| [WINDOW-MANAGER.md](WINDOW-MANAGER.md) | dockview-core window manager integration plan |
| [WAR-ROOM-UX-REVIEW.md](WAR-ROOM-UX-REVIEW.md) | War Room frontend UX architecture review |

## Quick Links

### For Users
- **How to Play**: [HOW-TO-PLAY.md](HOW-TO-PLAY.md)
- **Controls**: Press `?` in the UI or see [CONTROLS.md](CONTROLS.md)
- **Gamepad**: [GAMEPAD.md](GAMEPAD.md)

### For Developers
- **Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md)
- **Project Context**: [../CLAUDE.md](../CLAUDE.md)
- **API Reference**: CLAUDE.md API Endpoints section
- **MQTT Protocol**: [MQTT.md](MQTT.md)
- **Engine Subsystems**: [../src/engine/README.md](../src/engine/README.md)
- **Amy AI Commander**: [../src/amy/README.md](../src/amy/README.md)
- **Frontend**: [../src/frontend/README.md](../src/frontend/README.md)
- **Robot Integration**: [../examples/robot-template/README.md](../examples/robot-template/README.md)
- **Plugin Development**: [PLUGIN-SPEC.md](PLUGIN-SPEC.md) + [../plugins/README.md](../plugins/README.md)
- **NPC System**: [NPC-INTELLIGENCE.md](NPC-INTELLIGENCE.md)
- **Demo Devices**: [DEMO-SPEC.md](DEMO-SPEC.md) + [../examples/README.md](../examples/README.md)
- **Test Suite**: [../tests/README.md](../tests/README.md)

### Cross-Project
- **Parent System**: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md)
- **System Status**: [../../docs/STATUS.md](../../docs/STATUS.md)
- **Shared Library**: [../../tritium-lib/CLAUDE.md](../../tritium-lib/CLAUDE.md)
- **Edge Integration**: [../../tritium-edge/docs/INTEGRATION.md](../../tritium-edge/docs/INTEGRATION.md)
