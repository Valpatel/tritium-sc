# TRITIUM-SC Documentation

## Documentation Index

| Document | Description |
|----------|-------------|
| [HOW-TO-PLAY.md](HOW-TO-PLAY.md) | Player guide: setup, gameplay, controls, strategy tips |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture: layers, boot sequence, event flow, thread model |
| [PLAN.md](PLAN.md) | Development roadmap: phases, progress, technical architecture |
| [ESCALATION.md](ESCALATION.md) | Threat escalation: state machine, zones, dispatch decision tree |
| [MQTT.md](MQTT.md) | MQTT communication: topic hierarchy, payloads, device integration |
| [SIMULATION.md](SIMULATION.md) | Simulation engine: target lifecycle, spawners, tick loop |
| [CONTROLS.md](CONTROLS.md) | Complete keyboard and gamepad control reference |
| [GAMEPAD.md](GAMEPAD.md) | Gamepad setup, calibration, and troubleshooting |
| [UI-TESTING.md](UI-TESTING.md) | Visual regression testing with Playwright and OpenCV |
| [WAR-ROOM-UX-REVIEW.md](WAR-ROOM-UX-REVIEW.md) | War Room frontend UX architecture review |

## Quick Links

### For Users
- **How to Play**: See [HOW-TO-PLAY.md](HOW-TO-PLAY.md)
- **Getting Started**: See main [README.md](../README.md)
- **Controls**: Press `?` in the UI or see [CONTROLS.md](CONTROLS.md)
- **Gamepad Setup**: See [GAMEPAD.md](GAMEPAD.md)

### For Developers
- **Architecture**: See [ARCHITECTURE.md](ARCHITECTURE.md)
- **Project Context**: See [CLAUDE.md](../CLAUDE.md)
- **API Reference**: See CLAUDE.md API Endpoints section
- **MQTT Protocol**: See [MQTT.md](MQTT.md)
- **Robot Integration**: See `examples/robot-template/README.md`

### For Amy
- **Threat Model**: See [ESCALATION.md](ESCALATION.md)
- **Simulation**: See [SIMULATION.md](SIMULATION.md)
- **Battlespace Overview**: See [ARCHITECTURE.md](ARCHITECTURE.md)

## Document Conventions

- All diagrams use mermaid syntax
- API documentation uses OpenAPI/Swagger format
- Each document stands alone but cross-references related docs
- Architecture decisions include rationale ("Why X, not Y?")

## Contributing Documentation

When adding new features:
1. Update relevant docs in this folder
2. Add keyboard shortcuts to CONTROLS.md
3. Add gamepad mappings to CONTROLS.md and GAMEPAD.md
4. Add new files to the Important Files table in CLAUDE.md
5. Update the table above if adding new documents
