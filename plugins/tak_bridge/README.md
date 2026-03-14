# TAK Bridge Plugin

Publishes Tritium tracked targets as Cursor on Target (CoT) events for
ATAK/WinTAK/WebTAK interoperability.

## Transports

1. **Multicast UDP** — Standard TAK SA broadcast (default `239.2.3.1:6969`)
2. **TCP to TAK Server** — Configurable host:port for TAK Server connections
3. **MQTT** — Publishes to `tritium/{site}/cot` topic via EventBus

## Configuration

Set environment variables before starting tritium-sc:

| Variable | Default | Description |
|----------|---------|-------------|
| `TAK_ENABLED` | `false` | Master enable for the TAK bridge |
| `TAK_SERVER_HOST` | *(empty)* | TAK server TCP host |
| `TAK_SERVER_PORT` | `8087` | TAK server TCP port |
| `TAK_MULTICAST_ADDR` | `239.2.3.1` | Multicast group address |
| `TAK_MULTICAST_PORT` | `6969` | Multicast port |
| `TAK_CALLSIGN` | `TRITIUM-SC` | Our callsign on the TAK network |
| `TAK_PUBLISH_INTERVAL` | `5` | Seconds between target publishes |
| `TAK_STALE_SECONDS` | `120` | CoT stale timeout |
| `MQTT_SITE_ID` | `home` | MQTT topic prefix site ID |

## API Endpoints

- `GET /api/tak/status` — Bridge status and statistics
- `GET /api/tak/clients` — Connected TAK clients
- `GET /api/tak/config` — Current configuration

## Mapping

### Alliance to CoT Affiliation
- `friendly` -> `f` (friend)
- `hostile` -> `h` (hostile)
- `neutral` -> `n` (neutral)
- `unknown` -> `u` (unknown)

### Asset Type to CoT Type Code
Uses the engine's unit type registry for dynamic mapping. Fallback codes:
- `person` -> `a-f-G` (ground unit)
- `vehicle` -> `a-f-G-E-V` (ground equipment vehicle)
- `drone` -> `a-f-A` (airborne)

## Inbound

Incoming CoT events from TAK devices (via multicast or TCP) are parsed and
injected into the TargetTracker with `tak_` prefix to prevent echo loops.
