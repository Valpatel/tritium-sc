# TRITIUM-SC UI Redesign — Command Center

**Status**: PLANNING
**Author**: Claude Code + Human Direction
**Date**: 2026-02-20

## 1. Vision

TRITIUM-SC manages real Nerf battles with real robots, turrets, and people on
a real neighborhood map. Amy is the AI commander at the center. The UI should
feel like **commanding a battle**, not browsing a web dashboard.

**Reference points**:
- **StarCraft**: Advisor video box (bottom-left), minimap (bottom-left),
  unit selection panel (bottom-center), resource bar (top), all overlaid on the
  game map. You never leave the map to talk to your advisor.
- **Command & Conquer**: Sidebar with build queue, radar minimap, unit list —
  all persistent while the battlefield is always visible.
- **Valpatel homepage**: Clean panels, tactical canvas as hero element, minimal
  tabs, immersive cyberpunk aesthetic with depth (scanlines, grid background,
  glow effects).

**Visual identity**: Match the Valpatel homepage (`~/Code/homepage-valpatel/`)
exactly — refined cyberpunk with Inter font, thin borders, subtle glows,
grid background, scanlines. NO Orbitron, NO glitch effects, NO chunky neon
buttons. See Section 11 for full style spec.

**Satellite imagery**: The tactical map uses **real ESRI World Imagery tiles**
as the ground layer, not a plain grid. We already have the tile proxy
(`app/routers/geo.py`) caching to `~/.cache/tritium-sc/tiles/` and
coordinate transforms in `frontend/js/geo.js`. The satellite view grounds the
experience in reality — you're commanding actual neighborhood terrain.

**Anti-patterns to avoid**:
- Tabbed web app (click tab → see view → click another tab → lose context)
- Dashboard-first design (data tables, charts, settings as primary views)
- Fragmented state (Amy knows things the map doesn't, units exist in 3 places)
- Heavy/flashy UI that distracts from the content (map, units, Amy)

## 2. Core Principles

### 2.1 The Map is the Game

The War Room tactical map is **always visible**. It's the primary stage,
occupying 70-80% of the viewport. Everything else overlays or docks beside it.
You never "switch to" the map — you're always there.

### 2.2 Amy is the Interface

Amy is not a tab. She's a **persistent presence** — like a StarCraft advisor:
- Her portrait/video feed lives in a fixed panel (bottom-left or bottom-right)
- Her thoughts appear as **toast notifications** overlaid on the map
- Her speech is audible (TTS) while you're playing
- Clicking her portrait opens a chat panel (slide-out, not a tab switch)
- When game events happen, she reacts in-context ("Hostile spotted north!")

### 2.3 Robots are Units

Each robot is a unit on the map with:
- A **portrait** that appears when selected (like StarCraft unit selection)
- Status indicators (health, battery, weapon cooldown) as overlay bars
- When a robot "speaks" (via thinker), its portrait flashes and text appears
  in a kill-feed-style log
- Clicking a robot shows its detail panel (docked, not a tab)

### 2.4 Everything in Context

No more context-switching. Instead of 10 tabs:
- **Surveillance cameras** → picture-in-picture windows dragged onto the map
- **Asset management** → unit list in the sidebar (same data as map markers)
- **Analytics** → collapsible stats panel in the sidebar
- **Zones** → drawn directly on the map (always visible, toggleable layer)
- **Historical video** → Amy command ("Amy, search last 24h for person near gate")
- **Scenarios** → developer tools, hidden behind settings menu

### 2.5 Plugin Architecture with Saveable Layouts (CORE FEATURE)

The UI uses a **plugin-based architecture** with a **window manager** and
**saveable layouts**. This is a first-class requirement, not optional.

- Every panel (Amy, Units, Alerts, Camera, 3D View, Game HUD) is a **plugin**
  with a standard lifecycle API (create/mount/unmount/onResize)
- Panels can be docked, tabbed, split, floated, and resized via dockview-core
- Multiple 3D world views, camera streams, and status panels coexist
- Operators **save custom layouts** (which panels, where, what configuration)
  and **recall them** with `Ctrl+1..9` or a layout selector menu
- Built-in layouts ship for common scenarios (Commander, Observer, Battle, Surveillance)
- Layout export/import via JSON for sharing between operators

See `docs/WINDOW-MANAGER.md` for the full specification including:
- Library choice (dockview-core), Three.js multi-viewport architecture
- Plugin definition API, PluginRegistry, LayoutManager
- Migration path from current PanelManager
- Cybercore v2 theme mapping for dockview

## 3. Layout Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  TRITIUM-SC │ ■ LIVE │ 22:15:07 UTC │ ●3 units │ Wave 4/10    │
├──────────┬───────────────────────────────────────────────────────┤
│          │                                                       │
│ SIDEBAR  │     WAR ROOM (Canvas 2D Tactical Map)                │
│ (280px)  │     ┌──────────────────────────────────────────────┐ │
│ toggle ← │     │                                              │ │
│          │     │  Satellite imagery / grid                    │ │
│ ┌──────┐ │     │  Unit markers (friendly green, hostile red)  │ │
│ │UNITS │ │     │  Zone polygons (toggleable layer)            │ │
│ │list  │ │     │  Dispatch arrows, threat indicators          │ │
│ │filter│ │     │  Fog of war                                  │ │
│ └──────┘ │     │                                              │ │
│          │     │  ┌─────────┐              ┌─────────────┐   │ │
│ ┌──────┐ │     │  │ ALERTS  │              │ INTEL       │   │ │
│ │ALERTS│ │     │  │ feed    │              │ kill feed   │   │ │
│ │feed  │ │     │  │ (left)  │              │ (right)     │   │ │
│ └──────┘ │     │  └─────────┘              └─────────────┘   │ │
│          │     │                                              │ │
│ ┌──────┐ │     └──────────────────────────────────────────────┘ │
│ │CAMS  │ │                                                       │
│ │PIP   │ │  ┌───────────┬────────────────────┬────────────────┐ │
│ └──────┘ │  │ AMY       │ SELECTED UNIT      │ GAME STATUS    │ │
│          │  │ portrait  │ portrait + stats    │ score, wave    │ │
│ ┌──────┐ │  │ mood,     │ health, battery    │ kill streak    │ │
│ │STATS │ │  │ thoughts  │ orders, position   │ timer          │ │
│ │panel │ │  │ [CHAT]    │ [DISPATCH] [RECALL]│ [BEGIN WAR]    │ │
│ └──────┘ │  └───────────┴────────────────────┴────────────────┘ │
├──────────┴───────────────────────────────────────────────────────┤
│ MINIMAP (200×200)  │  Status bar: FPS, units alive, threats     │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 Components

| Component | Position | Size | Always Visible | Purpose |
|-----------|----------|------|----------------|---------|
| **Header bar** | Top | Full width, 36px | Yes | Title, mode, time, connection, game score |
| **Sidebar** | Left | 280px, collapsible | Yes (toggle) | Unit list, alerts, camera PIP, stats |
| **Tactical map** | Center | Fills remaining | Yes | RTS Canvas 2D battlefield |
| **Bottom bar** | Bottom | Full width, 160px | Yes | Amy box, selected unit, game controls |
| **Minimap** | Bottom-left | 200×200 | In-game | Fog of war overview |
| **Toast layer** | Top-right | 300px wide | As needed | Amy thoughts, system alerts |
| **Modal layer** | Center | Overlay | As needed | Chat, video review, settings |

### 3.2 The Amy Box (StarCraft Advisor Model)

```
┌───────────────────────────────┐
│ ┌─────────┐  AMY              │
│ │ MJPEG   │  State: OBSERVING │
│ │ or      │  Mood: VIGILANT   │
│ │ Avatar  │                   │
│ │ feed    │  "Movement at the │
│ │ (120px) │   north fence..."  │
│ └─────────┘  [CHAT] [ATTEND]  │
└───────────────────────────────┘
```

- **Video feed**: Amy's camera (MJPEG) or an animated avatar when no camera
- **Status**: Current state + mood, updated in real-time
- **Last thought**: Most recent thought, truncated to 2 lines
- **Actions**: CHAT opens slide-out panel, ATTEND/OBSERVE/IDLE quick commands
- **Speaking indicator**: Glow/pulse effect when Amy is speaking (TTS active)
- Clicking anywhere on the box opens the full Amy chat panel (slide-out from right)

### 3.3 Robot Unit Selection (StarCraft Unit Panel Model)

When a unit is selected on the map (click or keyboard):

```
┌──────────────────────────────────────────┐
│ ┌──────┐  ROVER-ALPHA                    │
│ │icon  │  ████████░░ 150/200 HP          │
│ │(48px)│  ████████████ 87% battery       │
│ └──────┘  Position: (15.2, 8.7)          │
│           Status: PATROLLING              │
│           Last thought: "Area clear"      │
│  [DISPATCH]  [RECALL]  [PATROL]  [FIRE]  │
└──────────────────────────────────────────┘
```

When multiple units selected:

```
┌──────────────────────────────────────────┐
│ ┌──┐ ┌──┐ ┌──┐   3 units selected       │
│ │R │ │D │ │T │   Total HP: 410/460      │
│ └──┘ └──┘ └──┘   [DISPATCH ALL] [GROUP]  │
└──────────────────────────────────────────┘
```

### 3.4 The Sidebar

The sidebar replaces the old tab bar. It's a **persistent column** with
collapsible sections:

```
┌─ SIDEBAR ─────────────────┐
│                            │
│ ▼ UNITS (5)                │
│   ● Rover Alpha   ██ 87%  │
│   ● Drone Bravo   ██ 92%  │
│   ● Turret North   ACTIVE │
│   ▷ [Filter: All ▼]       │
│                            │
│ ▼ ALERTS (3 new)           │
│   ⚠ Hostile N fence  12s  │
│   ⚠ Motion detected  45s  │
│   ℹ Rover dispatch   2m   │
│                            │
│ ▼ CAMERAS                  │
│   ┌──────────┐             │
│   │ PIP cam  │  CH01       │
│   │ feed     │  [EXPAND]   │
│   └──────────┘             │
│   CH02 (offline)           │
│   CH03 (recording)         │
│                            │
│ ▶ ANALYTICS (collapsed)    │
│ ▶ SYSTEM (collapsed)       │
└────────────────────────────┘
```

- **UNITS**: Live unit list, click to select on map (highlight + center camera)
- **ALERTS**: Real-time alert feed (from escalation engine + Amy)
- **CAMERAS**: Mini PIP feeds, click to expand to modal or drag onto map
- **ANALYTICS**: Detection stats, threat history (collapsed by default)
- **SYSTEM**: Zones config, scenario runner, NVR settings (collapsed by default)

### 3.5 Toast Notifications (Amy Thoughts + Events)

Instead of Amy's thoughts being buried in a tab, they appear as toasts:

```
                              ┌────────────────────────┐
                              │ AMY: "Hostile patrol    │
                              │ pattern — they're       │
                              │ circling the south..."  │
                              └────────────────────────┘
                              ┌────────────────────────┐
                              │ ROVER-ALPHA: "Area      │
                              │ clear, returning..."    │
                              └────────────────────────┘
```

- Stack top-right, fade after 5s (configurable)
- Click to pin (stays until dismissed)
- Amy thoughts: cyan border, robot thoughts: green border, alerts: red border
- Announcer messages (kill streaks, wave banners) use center-screen banners

### 3.6 Chat Panel (Slide-Out)

Clicking Amy's portrait or pressing C opens a chat panel that slides in from
the right, **overlaying** the map (not replacing it):

```
                        ┌──────────────────────┐
                        │ ── AMY COMM ───────  │
                        │                      │
                        │  Amy: I see movement │
                        │  at the north fence. │
                        │  Dispatching rover.  │
                        │                      │
                        │  You: Any hostiles?  │
                        │                      │
                        │  Amy: Confirmed, one │
                        │  hostile moving east │
                        │  at 2.3 m/s.         │
                        │                      │
                        │  [________________]  │
                        │  [SEND]              │
                        └──────────────────────┘
```

- 350px wide, right-side slide-out
- Semi-transparent background so map is still visible
- Chat history persists across open/close
- Amy's last thought shown as context above the chat

### 3.7 Historical Video Analysis

Instead of separate Player/Grid tabs:
- **Quick review**: Click a camera in the sidebar → modal video player
- **AI search**: Type in chat: "Amy, search the last 24 hours for anyone near the front gate"
- **Amy routes** to her deep thinking model for video analysis
- Results appear as timeline markers on the map or in a results panel
- Grid view becomes a **camera mosaic modal** (Ctrl+G), not a separate view

## 4. Module Architecture (JavaScript)

### 4.1 Current → New Module Map

```
CURRENT (22 files, 17,578 LOC)         NEW (target ~12 files, ~10,000 LOC)
─────────────────────────────           ────────────────────────────────────
app.js (1101)                    →      core/app.js (~400)        State, init, routing
                                 →      core/websocket.js (~200)  WS connection
                                 →      core/events.js (~150)     Frontend event bus

war.js (2524)                    →      map/tactical-map.js (~1800) Core 2D renderer
war-combat.js (618)              →      map/combat.js (~600)       Kept as-is
war-hud.js (437)                 →      hud/overlays.js (~500)     Generalized overlays
war-fx.js (269)                  →      map/effects.js (~250)      Kept
war-fog.js (442)                 →      map/fog.js (~400)          Kept
war-audio.js (290)               →      map/audio.js (~250)        Kept
war-events.js (294)              →      map/events.js (~250)       Kept

amy.js (761)                     →      panels/amy-box.js (~300)   Amy portrait+status
                                 →      panels/chat.js (~250)      Slide-out chat
                                 →      panels/toasts.js (~200)    Thought toasts

assets.js (848)                  →      panels/sidebar.js (~500)   Unified sidebar
targets.js (882)                 →      (merged into sidebar unit list)
analytics.js (348)               →      panels/analytics.js (~300) Sidebar section
zones.js (380)                   →      map/zones.js (~350)        Map layer (not tab)
scenarios.js (886)               →      admin/scenarios.js (~800)  Hidden admin panel

grid.js (1157)                   →      modal/camera-grid.js (~800) Modal camera mosaic
player.js (675)                  →      modal/video-player.js (~500) Modal player

war3d.js (1375)                  →      editor/war3d.js (~1200)    Editor-only 3D
war-editor.js (1266)             →      editor/setup-mode.js (~800) SETUP mode (simplified)
models.js (932)                  →      editor/models.js (~900)    Kept

input.js (1309)                  →      core/input.js (~800)       Simplified for unified UI
geo.js (321)                     →      core/geo.js (~300)         Kept as-is
```

### 4.2 Shared State Management

Replace scattered global state with a single reactive store:

```javascript
// core/store.js
const TritiumStore = {
    // Map state
    map: { viewport: {}, selectedUnit: null, mode: 'observe' },

    // Game state
    game: { phase: 'idle', wave: 0, score: 0, kills: 0 },

    // Units (single source of truth)
    units: new Map(),  // id → { position, health, battery, alliance, type }

    // Amy state
    amy: { state: 'idle', mood: 'calm', lastThought: '', speaking: false },

    // Alerts
    alerts: [],  // { type, message, time, source }

    // Subscribe/notify
    _listeners: new Map(),
    on(key, fn) { ... },
    set(key, value) { ... notify listeners ... },
};
```

All modules read from and write to `TritiumStore`. WebSocket updates go to
the store, which notifies subscribers. No more scattered `assetState`,
`warState`, `amyState`.

### 4.3 Frontend Event Bus

```javascript
// core/events.js
const EventBus = {
    emit(event, data) { ... },
    on(event, handler) { ... },
    off(event, handler) { ... },
};

// Events:
// 'unit:selected'    — user clicked a unit on map
// 'unit:dispatched'  — dispatch command sent
// 'amy:thought'      — new thought from SSE
// 'amy:speak'        — TTS started
// 'game:state'       — game phase change
// 'alert:new'        — new alert from escalation
// 'camera:frame'     — new MJPEG frame
// 'toast:show'       — show a toast notification
```

### 4.4 ES6 Modules

Move from global `window.functionName` pollution to proper ES6 imports:

```javascript
// map/tactical-map.js
export class TacticalMap {
    constructor(canvas, store) { ... }
    render() { ... }
    selectUnit(id) { ... }
}

// panels/amy-box.js
import { TritiumStore } from '../core/store.js';
export class AmyBox {
    constructor(container) { ... }
    updateState(state) { ... }
}
```

`index.html` uses `<script type="module">` to load the entry point.

## 5. Keyboard & Gamepad (Simplified)

### 5.1 New Shortcuts

The keyboard map simplifies because there's no tab-switching:

| Key | Action |
|-----|--------|
| `SPACE` | Toggle pause (when in game) |
| `C` | Open/close Amy chat panel |
| `TAB` | Toggle sidebar |
| `M` | Toggle minimap |
| `F` | Center camera on action (nearest threat) |
| `G` | Open camera grid modal |
| `ESC` | Close any open panel/modal |
| `1-9` | Quick-select unit groups |
| `D` | Dispatch selected unit to mouse position |
| `R` | Recall selected unit |
| `B` | Begin War (when in setup) |
| `/` | Focus Amy chat input |
| `?` | Help overlay |
| `O/T/S` | Map mode: Observe / Tactical / Setup |
| `[` / `]` | Zoom in/out |

### 5.2 Gamepad

| Button | Action |
|--------|--------|
| A | Select unit / Confirm |
| B | Deselect / Back / Close panel |
| X | Dispatch selected unit |
| Y | Open Amy chat |
| LB/RB | Cycle through units |
| LT/RT | Zoom in/out |
| D-Pad | Pan map |
| Left stick | Pan map (analog) |
| Right stick | Aim dispatch target |
| Start | Begin War / Pause |
| Select | Toggle sidebar |

## 6. Amy Integration Details

### 6.1 Data Flow

```
Backend (src/amy/brain/thinking.py)
  → SSE /api/amy/thoughts
    → Frontend EventBus 'amy:thought'
      → AmyBox.updateLastThought()     (portrait panel)
      → ToastManager.showThought()     (toast notification)
      → TritiumStore.amy.lastThought   (state update)

Backend (src/amy/commander.py say())
  → WebSocket 'amy_speech'
    → AmyBox.setSpeaking(true)         (glow/pulse on portrait)
    → ToastManager.showSpeech()        (speech bubble toast)
    → Audio: play TTS audio
```

### 6.2 Amy Portrait States

| State | Visual |
|-------|--------|
| IDLE | Dim portrait, slow pulse border |
| OBSERVING | Normal portrait, steady cyan border |
| ATTENDING | Bright portrait, yellow border |
| SPEAKING | Glowing portrait, animated cyan border, speech bubble |
| ALERT | Red flash on portrait, alert icon |
| THINKING | Subtle animation (typing dots or brain icon) |

### 6.3 Robot Thought Display

When a robot publishes a thought via MQTT:

```
Backend (comms/mqtt_bridge.py _on_robot_thought)
  → EventBus 'robot_thought'
    → WebSocket 'robot_thought'
      → Frontend EventBus 'unit:thought'
        → Unit portrait flash (if selected)
        → Toast: "ROVER-ALPHA: Movement detected north"
        → Sidebar unit entry pulse
```

## 7. Historical Video Analysis

### 7.1 Integration Strategy

Instead of separate Player/Grid views, historical video is accessed through:

1. **Camera sidebar section**: Click a camera → opens modal video player
2. **Amy chat command**: "Search last 24h for person near front gate"
3. **Timeline view**: Ctrl+T opens a timeline overlay at bottom of map,
   showing events plotted on a time axis with video thumbnails

### 7.2 Video Search via Amy

```
User: "Amy, find any activity near the front gate in the last 6 hours"
Amy: "Scanning 6 hours of footage from CH01 and CH03..."
     (progress bar in chat panel)
Amy: "Found 3 events:
      - 14:23: Person walking past gate (30s clip)
      - 16:45: Vehicle stopped near gate (2m clip)
      - 19:12: Movement detected, no identification (15s clip)"
     [▶ Play 14:23] [▶ Play 16:45] [▶ Play 19:12]
```

Clicking a play button opens the modal video player at that timestamp.

### 7.3 YOLO Processing Pipeline

Real-time and historical video both use the same YOLO pipeline:
- Real-time: YOLO runs on live RTSP streams, detections → EventBus → map markers
- Historical: YOLO runs on recorded footage (batch mode), results stored in SQLite
- Both feed into the same TargetTracker for unified situational awareness

## 8. Testing Strategy

### 8.1 Visual Testing

Existing `tests/ui/test_vision.py` framework adapts to the new layout:
- **Primary view test**: War Room with all panels visible (Amy box, sidebar, HUD)
- **Panel state tests**: Sidebar open/closed, chat panel open/closed
- **Game state tests**: Setup mode, active game, game over
- **Responsive tests**: Full screen, sidebar collapsed, mobile viewport

### 8.2 Unit Tests (New)

Frontend JavaScript unit tests using the existing `tests/js/` Node.js framework:

```javascript
// tests/js/test_store.js — TritiumStore state management
// tests/js/test_events.js — EventBus pub/sub
// tests/js/test_amy_box.js — Amy portrait state transitions
// tests/js/test_sidebar.js — Unit list filtering, alert feed
// tests/js/test_toasts.js — Toast lifecycle (show, timeout, dismiss)
```

### 8.3 Integration Tests

Playwright E2E tests for the unified UI:
- Map renders with units visible
- Clicking a unit opens the selection panel
- Amy thoughts appear as toasts
- Chat panel slides in/out
- Sidebar collapses and expands
- Camera PIP loads MJPEG feed
- Game lifecycle (setup → begin → active → game over)

### 8.4 Layout Drift

Existing `tests/ui/test_layout_drift.py` continues to verify:
- MJPEG panels don't inflate
- Sidebar width stays at 280px
- Amy box dimensions are stable
- Toast notifications don't stack infinitely

## 9. Implementation Phases

### Phase 1: Foundation (Core Layout + Map Always Visible)

**Goal**: Replace the tabbed layout with the unified command center layout.
The map is always visible, sidebar docks on the left, bottom bar holds Amy box
and game controls.

**Files touched**:
- `index.html` — New layout structure (remove tabs, add panels)
- `css/tritium.css` — New layout CSS (flexbox/grid)
- `core/app.js` — New entry point (no more view switching)
- `core/store.js` — New shared state store
- `core/events.js` — New frontend event bus
- `core/websocket.js` — Extracted from app.js

**What works after Phase 1**:
- Map renders as primary view
- Sidebar shows (placeholder unit list)
- Bottom bar shows (placeholder Amy box + game controls)
- WebSocket connection works
- Old tabbed views removed

### Phase 2: Amy Integration (Portrait + Toasts + Chat)

**Goal**: Amy is a persistent presence. Her thoughts appear as toasts, her
portrait shows in the bottom bar, chat slides in from the right.

**Files touched**:
- `panels/amy-box.js` — Amy portrait + status + last thought
- `panels/toasts.js` — Toast notification manager
- `panels/chat.js` — Slide-out chat panel
- Amy SSE connection wired to toast system

**What works after Phase 2**:
- Amy portrait visible with real-time status
- Thoughts appear as cyan-bordered toasts (top-right)
- Chat panel opens with C key, closes with ESC
- Amy speech triggers glow effect on portrait

### Phase 3: Unit Management (Sidebar + Selection + Dispatch)

**Goal**: Units are managed through the sidebar and map selection, not a
separate Assets tab.

**Files touched**:
- `panels/sidebar.js` — Unit list, alerts, cameras sections
- `map/tactical-map.js` — Unit selection, dispatch
- `hud/overlays.js` — Selected unit info panel (bottom bar)

**What works after Phase 3**:
- Sidebar shows live unit list (from TritiumStore)
- Clicking unit on map or sidebar selects it
- Selected unit shows detail panel in bottom bar
- Dispatch/recall buttons work
- Alerts feed in sidebar

### Phase 4: Camera + Video Integration

**Goal**: Cameras are sidebar PIP windows, video review is a modal.

**Files touched**:
- `modal/camera-grid.js` — Camera mosaic modal (Ctrl+G)
- `modal/video-player.js` — Modal video player
- Sidebar camera section with MJPEG thumbnails

**What works after Phase 4**:
- Camera PIP in sidebar shows live feed
- Clicking camera opens expanded modal
- Historical video accessible via modal player
- Camera grid available as modal overlay

### Phase 5: Game Flow + Polish

**Goal**: Full game lifecycle works in the unified UI. HUD overlays, wave
banners, score, kill feed, BEGIN WAR button all integrated.

**Files touched**:
- `hud/overlays.js` — Wave banners, countdown, score, kill feed
- `map/combat.js` — Combat visuals (kept)
- Game controls in bottom bar (BEGIN WAR, reset)

**What works after Phase 5**:
- Full game lifecycle: setup → countdown → active → wave complete → victory/defeat
- Kill feed in right overlay
- Score in header bar
- Announcer messages as center-screen banners
- Game over screen with stats

### Phase 6: Editor + 3D (Optional)

**Goal**: Separate the level editor from gameplay. 3D view is opt-in for
setup mode only.

**Files touched**:
- `editor/setup-mode.js` — Simplified SETUP mode (no 3D required)
- `editor/war3d.js` — 3D view (only loaded when user opts in)
- `editor/models.js` — Kept as-is

### Phase 7: Historical Video + AI Search

**Goal**: Amy can search historical footage via chat command.

**Files touched**:
- `panels/chat.js` — Add video search results display
- `modal/video-player.js` — Timestamp jumping
- Backend: `/api/amy/video-search` endpoint

## 10. Migration Strategy

### 10.1 Parallel Development

The new UI is built alongside the old one:
- `frontend/index.html` → old UI (kept as `frontend/legacy.html`)
- `frontend/command.html` → new command center UI
- Both served by the same FastAPI backend
- Switch between them via URL: `/` (new) vs `/legacy` (old)

### 10.2 Feature Parity Checklist

Before removing the old UI, the new one must support:

- [ ] War Room tactical map (Canvas 2D)
- [ ] Unit markers (friendly, hostile, unknown)
- [ ] Unit selection and dispatch
- [ ] Amy portrait with real-time state
- [ ] Amy thoughts as toasts
- [ ] Amy chat (slide-out panel)
- [ ] Game lifecycle (setup → play → end)
- [ ] Kill feed, score, wave banners
- [ ] Sidebar with unit list
- [ ] Sidebar with alert feed
- [ ] Camera PIP in sidebar
- [ ] Camera grid modal
- [ ] Video player modal
- [ ] Minimap
- [ ] Fog of war
- [ ] Keyboard shortcuts
- [ ] Gamepad support
- [ ] Zone visualization (map layer)
- [ ] WebSocket real-time updates
- [ ] Announcer audio
- [ ] Robot thought display

### 10.3 What Gets Dropped

These features are intentionally **not** carried forward:
- **3D View tab** → 3D is editor-only, not a primary view
- **Targets tab** → unit gallery merged into sidebar search
- **Scenarios tab** → moved to admin settings
- **NVR sidebar** → simplified to camera section in sidebar

## 11. Visual Style — Matching Valpatel Homepage

The UI style MUST match the refined cyberpunk aesthetic from
`~/Code/homepage-valpatel/index.html`. This is a departure from the current
heavy cyberpunk (thick borders, Orbitron font, glitch effects).

### 11.1 Style Reference (Valpatel Homepage)

| Property | Current TRITIUM-SC | Target (Valpatel style) |
|----------|-------------------|------------------------|
| **Body font** | Orbitron (display), JetBrains Mono | **Inter** (body), JetBrains Mono (data/labels) |
| **Background** | `#0a0a0f` | `#0a0a0f` (same void black) |
| **Surface 1** | `#12121a` heavy borders | `#0e0e14` subtle |
| **Surface 2** | `rgba(26,26,46,0.6)` | `#12121a` clean |
| **Surface 3** | — | `#1a1a2e` (for icons/badges) |
| **Borders** | `rgba(0,240,255,0.2)` — visible | `rgba(0,240,255,0.08)` — barely there |
| **Border hover** | thick glow | `rgba(0,240,255,0.15)` subtle |
| **Panels** | Hard borders, chunky | `linear-gradient(135deg, surface-2, surface-1)` + 1px border |
| **Panel hover** | — | `box-shadow: 0 0 20px rgba(0,240,255,0.04)` glow |
| **Buttons** | `.btn-cyber` — chunky neon | Subtle text buttons, bracket styling: `[ ACTION ]` |
| **Headers** | Orbitron, all-caps | Inter 600-700, `text-shadow: 0 0 60px rgba(0,240,255,0.1)` |
| **Labels** | Mixed | JetBrains Mono, `0.6-0.7rem`, `letter-spacing: 0.1-0.15em`, uppercase |
| **Body text** | JetBrains Mono | Inter 400, `#6b7a8d` or `#5a6577` |
| **Accent color** | Cyan `#00f0ff` | Cyan `#00f0ff` (same) |
| **Accent dim** | — | `#0e7490` for labels |
| **Grid background** | None | Subtle grid: `rgba(0,240,255,0.025)` 80px squares |
| **Scanlines** | Heavy | Subtle: `rgba(0,0,0,0.03)` 4px repeat |
| **Interlace** | None | Fine: `rgba(0,240,255,0.008)` 2px horizontal + `rgba(255,255,255,0.006)` 4px vertical |
| **Glitch effects** | Orbitron glitch on logo | **Remove** — too heavy for this aesthetic |
| **Corner marks** | None | Decorative corner brackets on key panels |
| **Status dots** | Connection dot | Pulsing dots: green=active, amber=warning, gray=offline |
| **Animations** | Aggressive | Gentle: 0.25-0.3s ease transitions, 2s pulse |

### 11.2 Key Visual Rules

1. **Restraint over flash**: Less glow, thinner borders, more whitespace.
   The cyberpunk feeling comes from the color palette and scanlines, not from
   thick neon borders and glitch effects.

2. **Typography hierarchy**: Inter for content, JetBrains Mono for data labels
   and status indicators. Orbitron is gone — it's too display-heavy for a
   command center used for hours.

3. **Panel depth**: Panels use gradient backgrounds (surface-2 → surface-1)
   with 1px near-invisible borders. The top edge gets a subtle glow line
   (`linear-gradient(90deg, transparent, cyan-glow, transparent)`) that
   appears on hover.

4. **Corner accents**: Key panels get decorative corner marks (small L-shaped
   lines in the corners, `rgba(0,240,255,0.15)`). Use sparingly — Amy box,
   minimap, selected unit panel.

5. **Satellite imagery**: The tactical map shows **real ESRI satellite tiles**
   as the ground layer (we already have this via `geo.js` tile loader and
   `app/routers/geo.py` tile proxy cached to `~/.cache/tritium-sc/tiles/`).
   The satellite imagery gives the map an immersive, real-world feel that
   matches the refined aesthetic.

6. **Status indicators**: All status uses the Valpatel dot pattern:
   - `background: var(--green); box-shadow: 0 0 6px rgba(5,255,161,0.4)` (active)
   - `background: var(--amber); box-shadow: 0 0 6px rgba(252,238,10,0.3)` (warning)
   - `background: #4a5568` (offline/idle)

### 11.3 CSS Architecture

**Replace** (don't refactor, start fresh):
- `cybercore.css` → `cybercore-v2.css` (new framework matching Valpatel style)
- `tritium.css` → `command.css` (layout + components for command center)

**New file structure**:
```
frontend/css/
  cybercore-v2.css    (~400 LOC) — Variables, reset, base, grid-bg, scanlines
  command.css         (~600 LOC) — Layout, panels, sidebar, bottom-bar, toasts
  map.css             (~300 LOC) — Tactical map overlay elements
  amy.css             (~200 LOC) — Amy box, portrait states, chat panel
```

**CSS Variables** (from Valpatel):
```css
:root {
    --cyan: #00f0ff;
    --cyan-dim: #0e7490;
    --cyan-glow: rgba(0, 240, 255, 0.15);
    --green: #05ffa1;
    --amber: #fcee0a;
    --magenta: #ff2a6d;
    --void: #0a0a0f;
    --surface-1: #0e0e14;
    --surface-2: #12121a;
    --surface-3: #1a1a2e;
    --border: rgba(0, 240, 255, 0.08);
    --text-primary: #c8d0dc;
    --text-secondary: #8892a4;
    --text-muted: #5a6577;
    --text-dim: #4a5568;
    --text-ghost: #3a4250;
}
```

## 12. Performance Considerations

### 12.1 Canvas Rendering

The tactical map Canvas 2D rendering stays the same — it's already efficient.
Key metrics to maintain:
- 60fps render loop
- <16ms per frame
- Dirty rect tracking for partial redraws

### 12.2 DOM Updates

Minimize DOM thrashing:
- Toast notifications: max 5 visible, FIFO queue
- Sidebar unit list: virtual scrolling if >50 units
- Alert feed: max 100 entries, prune oldest
- Amy thoughts: last 20 in memory

### 12.3 WebSocket

No changes needed — the existing WebSocket protocol supports all the data we need.
Just route messages to TritiumStore instead of scattered handlers.

### 12.4 MJPEG

Camera PIP feeds use the same MJPEG approach, but in smaller containers:
- Sidebar PIP: 240×135 (16:9)
- Amy portrait: 120×120 (square crop)
- Camera grid modal: full resolution

The 3-layer MJPEG fix from CLAUDE.md still applies to all MJPEG containers.

## 13. Accessibility

### 13.1 Keyboard Navigation

All interactive elements reachable via keyboard:
- Tab through sidebar sections
- Arrow keys within unit list
- Enter to select, Escape to deselect
- Shortcuts for all common actions (no mouse required)

### 13.2 Screen Reader

- ARIA labels on all panels
- Live regions for toasts and alerts
- Semantic HTML structure within panels

### 13.3 Color

- All information conveyed by color also has an icon or text indicator
- Friendly (green + F icon), Hostile (red + H icon), Unknown (yellow + ? icon)
- Amy moods have both color and text labels
