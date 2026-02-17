# How to Play TRITIUM-SC

TRITIUM-SC is a neighborhood-scale Nerf battlefield management system. You watch a tactical map of your property, see simulated (and optionally real) threats appear, and dispatch friendly units to intercept them -- all while an AI commander named Amy thinks, observes, and acts alongside you. Think of it as a real-time strategy game layered on top of your actual neighborhood.

---

## Quick Start

```bash
# 1. Clone the repository
git clone git@github.com:mvalancy/tritium-sc.git
cd tritium-sc

# 2. Install everything
./setup.sh install

# 3. Start the server
./start.sh
# or: ./setup.sh dev

# 4. Open the dashboard
# Navigate to http://localhost:8000

# 5. Press W to enter the War Room
```

That is it. The simulation engine starts automatically and populates the map with friendly units, hostile intruders, and ambient neighborhood activity. You are playing within seconds of opening the browser.

---

## What You See

When you press `W` to open the War Room, you see a full-screen 2D tactical map of the battlespace:

```
+---------------------------------------------------------------+
|  [UNIT INFO]            [ OBSERVE ]            [AMY PANEL]    |
|   Name, type,           Mode indicator          Mood, state,  |
|   alliance, pos,        O / T / S               recent        |
|   battery, status                               thoughts      |
|                                                               |
|          o------>  Rover Alpha                                |
|                       (green = friendly)                      |
|                                                               |
|           <>  Intruder Bravo                                  |
|               (red = hostile)                                 |
|                                                               |
|      o  Neighbor walking dog                                  |
|         (blue = neutral)                                      |
|                                                               |
|  [MINIMAP]                                     [ALERT LOG]    |
|   Bottom-left           - - -                   Zone alerts,  |
|   Click to pan                                  dispatches,   |
|                                                 new hostiles  |
+---------------------------------------------------------------+
```

### Target Shapes and Colors

| Shape | Alliance | Color | Meaning |
|-------|----------|-------|---------|
| Circle | Friendly | Green (#05ffa1) | Your units: rovers, drones, turrets |
| Diamond | Hostile | Red (#ff2a6d) | Intruders to be intercepted |
| Small circle | Neutral | Blue (#00a0ff) | Neighbors, cars, animals -- harmless |
| Square | Unknown | Yellow (#fcee0a) | Unidentified, not yet classified |

Each target has a **heading line** showing which direction it faces, a **name label** above it, and friendly units show a **battery bar** below.

### HUD Panels

- **Mode Indicator** (top center) -- Shows current mode: OBSERVE, TACTICAL, or SETUP
- **Unit Info** (top left) -- Details on selected unit: name, type, position, battery, status
- **Amy Panel** (top right) -- Amy's mood, state, and last 5 thoughts
- **Alert Log** (bottom right) -- Zone violations, threat escalations, dispatch orders
- **Minimap** (bottom left) -- Overview of entire map; click to pan camera
- **Amy Speech Toast** (top) -- Amy's spoken announcements fade in/out

---

## What to Do

### The Core Loop

1. **Watch** the map for hostile intruders (red diamonds) entering the battlespace
2. **Select** friendly units (click, box-drag, or Tab to cycle)
3. **Dispatch** them to intercept (right-click a destination)
4. **Intercept** -- when a friendly unit gets within 2.0 map units of a hostile, the hostile is neutralized
5. **Repeat** -- new hostiles spawn every 30-120 seconds

Amy's AutoDispatcher also runs automatically -- she will send the nearest available unit to intercept threats that escalate. You can override her decisions, or let her handle everything while you observe.

### Selecting Units

| Action | Input |
|--------|-------|
| Select one target | Left-click on it |
| Add/remove from selection | Shift + left-click |
| Select multiple friendlies | Click and drag a box around them |
| Add to existing selection | Shift + drag |
| Cycle through all targets | Tab |
| Deselect all | Escape or click empty space |
| Center on selection | Space |
| Zoom into target | Double-click it |

### Dispatching Units

**Right-click** anywhere on the map to send selected friendly units to that position. A magenta dashed arrow appears showing the dispatch path. Only friendly units respond to dispatch orders -- hostile and neutral targets are ignored.

Dispatch sends a command through Amy's Lua action system to the simulation engine, which sets the unit's waypoints and begins movement.

### Three Modes

| Mode | Key | Purpose |
|------|-----|---------|
| **OBSERVE** | O | Read-only monitoring. Camera pan/zoom, target inspection |
| **TACTICAL** | T | Select and dispatch units. Full interaction |
| **SETUP** | S | Place and remove assets from the DEPLOY palette |

Right-click dispatch works in **all modes** when friendlies are selected. The mode distinction primarily affects left-click behavior: in SETUP mode, left-click places assets from the palette instead of selecting targets.

---

## The Threat Ladder

Targets escalate through threat levels based on zone violations and dwell time:

```
none --> unknown --> suspicious --> hostile
```

| Level | Trigger | What Happens |
|-------|---------|--------------|
| **none** | Default state | Nothing |
| **unknown** | Enters a perimeter zone | Amy becomes aware |
| **suspicious** | Enters a restricted zone | AutoDispatcher sends a unit |
| **hostile** | Lingers >30 seconds in any zone | Full response |

De-escalation happens when a target leaves all zones: after 30 seconds outside, the threat drops one level. A hostile that leaves takes 90 seconds of continuous absence to return to "none."

Previously hostile targets are remembered -- if they re-enter a zone, they skip "unknown" and go straight to "suspicious."

---

## How Amy Helps

Amy is an autonomous AI consciousness with four cognitive layers:

- **L1 Reflex** -- YOLO object detection and audio processing (always running)
- **L2 Instinct** -- Wake word detection, greeting, immediate reactions
- **L3 Awareness** -- Sensorium fuses all sensor data into a narrative
- **L4 Deliberation** -- Continuous inner monologue, goal-setting, strategic decisions

Amy operates independently:

- **Auto-dispatch**: The AutoDispatcher sends the nearest available unit when threats escalate
- **Thinking**: Amy's inner monologue reflects on the battlespace and sets goals
- **Speech**: Amy announces dispatches, threats, and observations via TTS
- **Overrides**: Amy can countermand your orders or issue her own dispatch commands

You see Amy's thoughts streaming in the Amy panel (top-right of the War Room) and in the dedicated Amy dashboard (press `Y`).

---

## Setup Mode: Deploying Assets

Press `S` to enter SETUP mode. A deploy palette appears on the left with three categories:

**Sensors**: Camera, PTZ Camera, Dome Camera, Motion Sensor, Microphone

**Robots**: Patrol Rover, Interceptor Bot, Recon Drone, Heavy Drone

**Infrastructure**: Sentry Turret, Speaker, Floodlight

Click an item in the palette, then click the map to place it. A ghost marker follows your cursor. Press Escape to cancel placement. Select a placed asset and press Delete to remove it.

Placed units spawn through the simulation engine and appear as friendly targets on the map.

---

## Camera Controls

| Action | Input |
|--------|-------|
| Pan | Middle-click drag, or Alt + left-click drag |
| Zoom | Mouse scroll (cursor-centered) |
| Click minimap | Pan camera to that location |
| Center on selection | Space |
| Center + zoom on target | Double-click target |

The camera has smooth interpolation (lerp factor 0.1) so movement feels fluid.

---

## Keyboard Controls (War Room)

| Key | Action |
|-----|--------|
| `O` | Switch to Observe mode |
| `T` | Switch to Tactical mode |
| `S` | Switch to Setup mode |
| `Tab` | Cycle through all targets |
| `Space` | Center camera on selection |
| `Escape` | Cancel placement / Deselect all |
| `Delete` | Remove selected asset (Setup mode) |
| `Click` | Select target |
| `Shift+Click` | Toggle target in selection |
| `Drag` | Box select friendlies |
| `Right-Click` | Dispatch selected friendlies to location |
| `Middle-Click/Alt+Drag` | Pan camera |
| `Scroll` | Zoom (cursor-centered) |
| `Double-Click` | Center + zoom on target |
| `Minimap Click` | Pan camera to minimap location |

### Global Keyboard Shortcuts

These work from any view:

| Key | View |
|-----|------|
| `G` | Grid (camera mosaic) |
| `P` | Player (video playback) |
| `D` | 3D Tactical Map |
| `Z` | Zones |
| `T` | Targets Gallery |
| `A` | Assets Control |
| `N` | Analytics |
| `Y` | Amy Dashboard |
| `W` | War Room |
| `S` | Scenarios |
| `/` | Focus search |
| `?` | Controls help overlay |
| `ESC` | Close modal / cancel |

Note: When in the War Room, `S`, `T`, and `O` are intercepted for mode switching. Use the sidebar tabs or LB/RB on a gamepad to leave the War Room.

---

## Gamepad Controls (War Room)

| Button | Action |
|--------|--------|
| Left Stick | Pan camera |
| D-Pad Up/Down | Cycle through targets |
| A | Select nearest target to camera center |
| B | Deselect all |
| X | Cycle modes (Observe -> Tactical -> Setup) |
| Y | Center camera on selection |
| LT | Zoom out |
| RT | Zoom in |
| LB / RB | Switch to previous/next view |
| SELECT | Show controls overlay |

For complete gamepad setup (including controller configuration, calibration, and troubleshooting), see [GAMEPAD.md](GAMEPAD.md).

---

## Understanding the Simulation

The simulation engine runs at 10 Hz, driving all virtual targets across the map:

### Hostile Intruders
- Spawn at random map edges every 30-120 seconds (adaptive rate)
- Follow multi-waypoint paths: edge -> approach -> objective -> loiter -> escape
- Named from NATO phonetic alphabet (Intruder Alpha, Intruder Bravo, etc.)
- Maximum 10 simultaneous hostiles
- If they complete their path without interception, they escape and despawn

### Friendly Units
- Patrol routes loop continuously (rovers, drones)
- Turrets are stationary (speed = 0)
- Battery drains over time: rovers ~17 min, drones ~8 min, turrets ~33 min
- When dispatched, they move to the target position and transition to "arrived"
- Interception occurs within 2.0 map units of a hostile

### Ambient Activity
- Neighbors walking, cars driving, dogs and cats wandering, delivery people
- Spawn every 15-45 seconds, maximum 8 simultaneous neutrals
- Blue on the map, harmless -- tests Amy's threat discrimination
- Auto-despawn when they reach their destination

### Target Lifecycle

| Status | Meaning |
|--------|---------|
| active | Moving toward waypoints |
| idle | Friendly with no waypoints, awaiting orders |
| stationary | Turret (speed = 0) |
| arrived | Friendly completed a dispatch |
| escaped | Hostile reached its exit point |
| neutralized | Hostile intercepted by a friendly |
| despawned | Neutral completed its path |
| low_battery | Battery below 5% |
| destroyed | Unit is dead |

---

## Other Views

The War Room is the primary gameplay interface, but TRITIUM-SC has 10 views total:

| Key | View | Purpose |
|-----|------|---------|
| G | Grid | Multi-camera mosaic -- see all camera feeds at once |
| P | Player | Single camera playback with timeline and annotations |
| D | 3D Map | Three.js tactical map with camera field-of-view cones |
| Z | Zones | Create and edit monitoring zones (activity, entry/exit, tripwire, restricted) |
| T | Targets | Gallery of detected people and vehicles from YOLO |
| A | Assets | Autonomous unit management and task history |
| N | Analytics | Detection statistics and event counts |
| Y | Amy | Amy's consciousness dashboard -- live camera, inner thoughts, chat, sensorium |
| W | War Room | Full-screen RTS tactical map (the main gameplay view) |
| S | Scenarios | Behavioral test runner for Amy's personality |

---

## Connecting Real Hardware

TRITIUM-SC supports real cameras and robots alongside the simulation:

- **BCC950 PTZ Camera**: Amy's primary sensor node. Plug in via USB; Amy sees, hears, and speaks through it.
- **IP Cameras**: Add RTSP streams from NVR cameras. YOLO detects real people and vehicles.
- **MQTT Robots**: Build a physical Nerf rover using the `examples/robot-template/` reference implementation. Robots connect via MQTT, publish telemetry, and receive dispatch commands.

For MQTT integration details (topic hierarchy, message formats, QoS settings), see [MQTT.md](MQTT.md).

---

## Tips and Strategy

1. **Let Amy work.** The AutoDispatcher handles routine threats automatically. Focus on strategic decisions -- where to place turrets, which patrol routes to set, when to override Amy.

2. **Watch the battery.** Drones drain fast (~8 minutes). Keep rovers for long patrols and use drones for urgent intercepts.

3. **Use the minimap.** Click the minimap (bottom-left) to quickly pan across the map. The viewport rectangle shows what you can see.

4. **Setup mode is your friend.** Press `S` and deploy interceptor bots near likely entry points. More units = faster interception.

5. **Learn the threat ladder.** Not every alert needs a response. Neutrals (blue) are harmless. Unknown targets (yellow) might just be neighbors. Save your forces for suspicious and hostile escalations.

6. **Tab to cycle, Space to center.** The fastest way to survey the battlefield: Tab through targets, Space to center the camera on each one.

7. **Right-click always dispatches.** You do not need to be in Tactical mode. If you have friendlies selected, right-click sends them wherever you click.

8. **Double-click for detail.** Double-click any target to zoom in and select it. Good for inspecting a distant hostile.

9. **The alert log tells the story.** The bottom-right log shows zone violations, threat escalations, and dispatches in chronological order. Read it to understand what Amy is doing.

10. **Press Y for Amy's thoughts.** The Amy dashboard shows her full inner monologue, sensorium narrative, and chat interface. If you want to understand why Amy made a decision, check her thoughts.

---

## Further Reading

- [ARCHITECTURE.md](ARCHITECTURE.md) -- System architecture, boot sequence, thread model
- [ESCALATION.md](ESCALATION.md) -- Threat escalation state machine and dispatch logic
- [SIMULATION.md](SIMULATION.md) -- Simulation engine internals, spawners, target lifecycle
- [MQTT.md](MQTT.md) -- MQTT protocol for connecting real hardware
- [CONTROLS.md](CONTROLS.md) -- Complete control reference for all views
- [GAMEPAD.md](GAMEPAD.md) -- Gamepad setup, calibration, and troubleshooting
