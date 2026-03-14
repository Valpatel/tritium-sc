# RF Motion Detection Plugin

Passive motion detection using RSSI variance analysis between stationary
radios. No cameras needed — uses the radios already deployed as part of
the tritium-edge mesh network.

## Theory

When a person or object moves through the RF path between two stationary
radios, the received signal strength (RSSI) fluctuates due to:

- **Absorption** — the human body absorbs 2.4 GHz energy
- **Reflection** — moving surfaces create new multipath components
- **Shadowing** — large objects block line-of-sight temporarily

By monitoring RSSI variance over a sliding window:

- **Low variance** (< 2 dBm) = static environment, no motion
- **High variance** (> 5 dBm) = motion detected in the RF path

## Modes

### Pair Mode
Monitors RSSI between two fixed radios (node-to-node). Best for
detecting motion in hallways, doorways, and corridors where the
RF path is well-defined.

### Device Mode
Monitors RSSI from a single observer watching a device. Detects
when a specific device (phone, BLE beacon, etc.) has moved.

## Zones

Group radio pairs into named zones for area-level occupancy tracking.
Motion in any pair within a zone triggers zone occupancy.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/rf-motion/events` | Current motion events |
| POST | `/api/rf-motion/detect` | Trigger detection cycle |
| GET | `/api/rf-motion/baselines` | Pair baseline stats |
| GET | `/api/rf-motion/zones` | List all zones |
| POST | `/api/rf-motion/zones` | Create a zone |
| GET | `/api/rf-motion/active` | Active motion summary |
| GET | `/api/rf-motion/config` | Detector config |
| PUT | `/api/rf-motion/config` | Update config |
| POST | `/api/rf-motion/rssi/pair` | Record pair RSSI |
| POST | `/api/rf-motion/rssi/device` | Record device RSSI |

## EventBus Events

- `rf_motion:detected` — motion detected in a radio pair or device
- `rf_motion:zone_occupied` — zone became occupied
- `rf_motion:zone_vacant` — zone became vacant

## TargetTracker Integration

Motion events create temporary `motion_detected` targets on the tactical
map at the midpoint of the radio pair where motion was detected.
