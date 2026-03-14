# Fleet Dashboard Plugin

Aggregated fleet device monitoring for TRITIUM-SC.

## What it does

- Subscribes to `fleet.heartbeat` and `edge:ble_update` events on the EventBus
- Maintains an in-memory device registry with: id, name, ip, battery, uptime, ble_count, wifi_count, last_seen
- Computes device status: online (<60s), stale (60-180s), offline (>180s)
- Prunes devices not seen in 5 minutes
- Exposes REST API endpoints for the frontend dashboard panel

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/fleet/devices` | List all tracked devices with status |
| GET | `/api/fleet/devices/{device_id}` | Get a single device by ID |
| GET | `/api/fleet/summary` | Fleet summary: counts, avg battery, totals |

## Frontend Panel

The `fleet-dashboard` panel (registered in panel-manager) displays:
- Summary bar: total, online, stale, offline counts + average battery
- Device table: name, status badge, battery bar, uptime, BLE/WiFi sighting counts, last seen
- Auto-refreshes every 10s via fetch to `/api/fleet/devices` and `/api/fleet/summary`

## Configuration

No configuration required. The plugin auto-discovers devices from EventBus events.
