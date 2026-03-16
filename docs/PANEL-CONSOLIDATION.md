# Panel Consolidation Plan

## Problem

100 separate floating windows. Users can't find what they need. Screen gets cluttered instantly.

## Current Panel Count: 100

## Proposed Consolidation: 100 → ~15 tabbed windows

Each consolidated window contains related panels as **tabs**. The underlying code stays modular (each tab is still a plugin/panel definition). Only the UI presentation changes.

### Proposed Windows

| Window | Tabs (current panels merged) | Shortcut |
|--------|------------------------------|----------|
| **AMY** | Amy Commander, Amy Monologue, Command History, Voice Command | 1 |
| **UNITS** | Units, Unit Inspector, Target Search, Target Compare, Target Merge, Dossiers, Dossier Groups, Dossier Timeline, Target Timeline | 2 |
| **MAP** | Layers, Layer Switcher, Map Bookmarks, Map Center, Map Grid, Map Replay, Map Share, Minimap, Annotations | 3 |
| **SENSORS** | Edge Tracker, Fleet Dashboard, Fleet Nodes, Sensor Net, Sensor Health, Device Manager, Device Capabilities, Edge Diagnostics, Edge Intelligence, MQTT Broker, MQTT Inspector | 4 |
| **INTELLIGENCE** | Alerts, Unified Alerts, Threat Level, Behavioral Intel, Fusion Pipeline, Graph Explorer, ML Training, Intel, Watch List, Security Audit | 5 |
| **CAMERAS** | Camera Feeds, Multi-Cam View, REID Tracking, LPR/Plate Reader, Indoor Positioning, Floor Plans | 6 |
| **TACTICAL** | Patrol Routes, Geofence, Zones, Missions, Swarm Coordination, Scenarios, Automation, Deployment | 7 |
| **COMBAT** | Game Status, Battle Stats, Heatmap, Heatmap Timeline, Combat Heatmap, Replay | 8 |
| **RADIO** | Meshtastic, TAK, Federation Sites, SDR Spectrum, Radar PPI, ADS-B Aircraft, RF Motion, WiFi Fingerprint, Acoustic Intel | 9 |
| **SYSTEM** | System, System Health, OPS Dashboard, Operator Activity, Operator Cursors, Notifications, Notification Prefs | 0 |
| **DATA** | Activity Feed, Events Timeline, Export Scheduler, Trail Export, Recordings | — |
| **WEATHER** | Weather, Weather Overlay, Building Occupancy, Dwell Monitor, Convoys | — |
| **SETUP** | Setup Wizard, Quick Start, Welcome, Demo Mode, Keyboard Macros, Testing | — |
| **COLLABORATION** | Collaboration Hub, Map Share, Operator Cursors, Graphlings | — |
| **ECONOMY** | Analytics Dashboard, Activity Heatmap, Sensor Coverage | — |

### Architecture: Plugin-Driven Windows (Blender-style)

```
Plugin (Python backend)
  ├── router.py          — API endpoints
  ├── service.py         — business logic
  └── panel_def.js       — UI definition (exported PanelDef)
        ├── id, title
        ├── category       — which consolidated window to join
        ├── icon           — tab icon
        ├── create()       — builds DOM
        ├── mount()        — starts subscriptions
        └── unmount()      — cleanup

Window (frontend container)
  ├── Tab bar at top (one tab per plugin panel in this category)
  ├── Active tab content area
  ├── Shared close/minimize/resize controls
  └── Remembers which tab was last active
```

### Key Changes

1. **PanelDef gets a `category` field** — determines which window it joins
2. **WindowManager** replaces PanelManager for grouping — panels within the same category share a window
3. **Tabs** — each panel becomes a tab within its category window
4. **Plugins register panels** — a plugin declares `category: 'sensors'` and it automatically appears as a tab in the SENSORS window
5. **Dynamic tabs** — new plugins add tabs without touching the window code
6. **Tab order** — plugins can specify `tabOrder: 5` to control position within the window

### Migration Path

1. Add `category` field to all 100 PanelDefs (default: own window for backward compat)
2. Build TabContainer component that renders multiple panels as tabs
3. WindowManager wraps PanelManager — groups panels by category
4. Gradually assign categories to panels (can be done per-plugin)
5. Old PanelDefs without category still work as standalone windows

### What Stays the Same

- Each panel's `create()`, `mount()`, `unmount()` — no change
- Each plugin's backend — no change
- Keyboard shortcuts — now open the consolidated window
- Panel state persistence (which tabs are open) — stored per-window

### What Changes

- WINDOWS menu shows ~15 items instead of 100
- Opening "SENSORS" gives you a tabbed window with 11 tabs
- Each tab loads on demand (mount on tab switch, unmount on tab away)
- Close button closes the window (all tabs)
- Individual tabs can't be dragged out (initially; maybe later)

### Benefits

- **Discoverability**: 15 windows vs 100. Users can actually find things.
- **Organization**: Related features are together. No hunting for "where's the fleet dashboard?"
- **Performance**: Only active tab is mounted. 99 idle panels consume zero resources.
- **Extensibility**: New plugin = new tab in existing window. No UI code to write.
- **Screen real estate**: One window with tabs instead of 5 overlapping panels.
