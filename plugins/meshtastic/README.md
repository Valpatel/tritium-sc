# Meshtastic Bridge Plugin

**Where you are:** `tritium-sc/plugins/meshtastic/` — LoRa mesh radio bridge for long-range command and control.

**Parent:** [../../CLAUDE.md](../../CLAUDE.md) | [../../../CLAUDE.md](../../../CLAUDE.md) (tritium root)

## What This Does

Bridges Meshtastic LoRa mesh radios into the Tritium Command Center. Each Meshtastic node appears as a tracked target on the tactical map with real GPS coordinates. Commands, waypoints, and text messages can be sent from SC to any mesh node.

This extends Tritium's range from WiFi (~100m) to LoRa (~10km line of sight).

## Connection Methods

| Method | Env Var | Use Case |
|--------|---------|----------|
| Serial | `MESHTASTIC_SERIAL_PORT=/dev/ttyUSB0` | USB-connected radio |
| TCP | `MESHTASTIC_TCP_HOST=radio.local` | Network radio or meshtastic-web |
| MQTT | (planned) | Meshtastic MQTT gateway |

## Configuration

```bash
MESHTASTIC_ENABLED=true          # Enable the bridge (default: false)
MESHTASTIC_CONNECTION=serial     # serial, tcp, or mqtt
MESHTASTIC_SERIAL_PORT=/dev/ttyUSB0
MESHTASTIC_TCP_HOST=localhost
MESHTASTIC_TCP_PORT=4403
MESHTASTIC_POLL_INTERVAL=5.0     # Seconds between node polls
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/meshtastic/status` | GET | Bridge status and node count |
| `/api/meshtastic/nodes` | GET | List all known mesh nodes |
| `/api/meshtastic/nodes/{id}` | GET | Single node details |
| `/api/meshtastic/send` | POST | Send text message (max 228 bytes) |
| `/api/meshtastic/waypoint` | POST | Send waypoint (lat, lng, name) |

## Data Flow

```
Meshtastic Radio ←→ Serial/TCP
    ↕
MeshtasticPlugin (poll loop, 5s)
    ↓                    ↑
TargetTracker           send_text() / send_waypoint()
(nodes on map)          (commands from SC)
    ↓
EventBus → WebSocket → Browser
```

## Dependencies

```bash
pip install meshtastic    # Required for radio connection
```

The plugin starts in disconnected mode if meshtastic is not installed.

## Related

- [../../docs/MESHTASTIC.md](../../docs/MESHTASTIC.md) — Integration design doc
- [../../../tritium-edge/docs/MESHTASTIC_INTEGRATION.md](../../../tritium-edge/docs/MESHTASTIC_INTEGRATION.md) — Edge-side LoRa integration
- [../edge_tracker/](../edge_tracker/) — BLE/WiFi presence tracking (similar pattern)
