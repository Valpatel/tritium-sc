# Panel & Addon Architecture Consolidation Plan

**Problem:** The Windows dropdown has 99 panels in a flat list with 9 category headers. Each panel is a standalone floating window. This doesn't scale — the user can't find what they need, and new plugins/addons keep adding more panels. The city sim alone could justify 5+ panels (sim control, NPC inspector, protest timeline, traffic stats, event log) which would further bloat the list.

**Root cause:** There's no concept of a "tabbed container" panel. Every feature gets its own window. Plugins declare `'ui'` capability but there's no mechanism for a plugin to contribute a tab to an existing panel rather than creating a new one.

**User's concern:** "This should be consolidated into fewer windows with tabs and addon driven."

---

## Current Architecture

### Panel System
- `PanelManager` — registers, opens, closes floating panels
- Each panel: `{ id, title, category, create(panel), unmount() }`
- 99 panel files in `panels/` directory
- 9 categories in `PANEL_CATEGORIES` (Tactical, Intelligence, Sensors, Fleet, AI & Comms, Collaboration, Map & GIS, Simulation, System)
- Uncategorized panels go to "Other" at the bottom

### Plugin System
- `PluginInterface` — `plugin_id, name, version, capabilities, start(), stop()`
- Plugins declare `capabilities: {'routes', 'ui', 'data_source'}`
- But `'ui'` capability is just a flag — no mechanism to contribute tabs
- 25 backend plugins in `plugins/` directory
- Plugins register FastAPI routers but don't directly register frontend panels

### The Gap
Plugins and panels are disconnected. A plugin can add API routes but there's no standard way for it to:
1. Add a tab to an existing panel
2. Declare which category/container its UI belongs to
3. Provide a frontend component that integrates with the panel system

---

## Proposed Architecture: Tabbed Container Panels

### Concept
Replace the flat panel list with **8-10 container panels**, each containing **tabs** contributed by core and plugins. The Windows dropdown shows containers, not individual panels.

### Container Definitions

| Container | Tabs (Core) | Tabs (Addon-Contributed) |
|-----------|------------|--------------------------|
| **Tactical** | Units, Alerts, Escalation, Missions, Patrol, Zones | Geofence, Watchlist, Swarm |
| **Intelligence** | Search, Dossiers, Timeline, Heatmap, Analytics | Graph Explorer, Behavioral, Fusion, Reid |
| **Sensors** | Edge Tracker, Cameras, Sensor Health | Meshtastic, SDR, Radar, WiFi, Acoustic, LPR |
| **Fleet** | Fleet Dashboard, Device Manager, Assets | Edge Diagnostics, Federation |
| **Amy** | Amy Chat, Thoughts, Voice | Amy Conversation |
| **Simulation** | City Sim (with sub-tabs: Control, NPCs, Traffic, Events, Protest) | Game, Scenarios, Replay |
| **Map** | Layers, GIS, Floorplan, Weather | Building Occupancy, Grid |
| **System** | System Health, Deployment, Events, Config | Testing, Security Audit |
| **Minimap** | (stays as standalone — special purpose) | |

### How It Works

1. **Container Panel** — a new panel type with a tab bar at the top
   ```js
   export class TabbedPanel {
       constructor(containerId, title) { ... }
       addTab(tabId, tabTitle, createFn, unmountFn) { ... }
       removeTab(tabId) { ... }
       selectTab(tabId) { ... }
   }
   ```

2. **Plugin Tab Registration** — plugins declare tabs, not panels
   ```python
   class CitySimPlugin(PluginInterface):
       capabilities = {'routes', 'ui'}
       ui_tabs = [
           { 'container': 'simulation', 'tab_id': 'city-sim', 'title': 'City Sim' },
           { 'container': 'simulation', 'tab_id': 'protest', 'title': 'Protest' },
       ]
   ```

3. **Frontend Tab Loader** — at startup, collects tabs from all plugins and adds them to containers
   ```js
   // Plugin declares its tab
   EventBus.emit('panel:register-tab', {
       container: 'simulation',
       id: 'city-sim',
       title: 'CITY SIM',
       create: (el) => { /* build city sim UI */ },
       unmount: () => { /* cleanup */ },
   });
   ```

4. **Windows Dropdown** — now shows only 8-10 containers
   ```
   WINDOWS ▾
   ├── Tactical          (12 tabs)
   ├── Intelligence       (8 tabs)
   ├── Sensors            (9 tabs)
   ├── Fleet              (4 tabs)
   ├── Amy                (3 tabs)
   ├── Simulation         (5 tabs)
   ├── Map & GIS          (4 tabs)
   ├── System             (5 tabs)
   └── Minimap
   ```

### Migration Path (Non-Breaking)

1. **Phase 1: Build TabbedPanel component** — new `tabbed-panel.js` that wraps existing panel content with a tab bar. Zero changes to existing panels.

2. **Phase 2: Add `panel:register-tab` EventBus API** — plugins can optionally register tabs instead of standalone panels. Both modes coexist.

3. **Phase 3: Migrate core panels to tabs** — move the most common panels into containers. Start with Simulation (city-sim + game + scenarios + replay).

4. **Phase 4: Update plugin SDK** — add `ui_tabs` to PluginInterface. Plugins can declare where their UI lives.

5. **Phase 5: Update Windows dropdown** — show containers by default, with a "Show All (Legacy)" option for uncollapsed view.

6. **Phase 6: Addon tab discovery** — addons from tritium-addons can contribute tabs to SC containers via the SDK.

### City Sim Specifically

The city sim currently has 1 panel (`city-sim`) that contains: status, entities, infrastructure, anomalies, protest section, scenarios, metrics, and action buttons. This is already overloaded for one panel.

**Proposed: City Sim becomes a tab group inside the Simulation container:**

| Tab | Content |
|-----|---------|
| **Control** | Start/stop, scenario selector, time scale, entity sliders |
| **Traffic** | Vehicle count, avg speed, road stats, congestion sparklines |
| **NPCs** | Pedestrian roles, building occupancy, daily routine progress |
| **Events** | Event director queue, active events, protest phase timeline |
| **Protest** | Epstein phase, active/arrested counts, police dispatch, commander narration |

Each tab is a small focused panel. The Simulation container holds all of them. The user opens one window and tabs between aspects.

---

## What This Does NOT Change

- Backend plugin architecture (PluginInterface stays the same)
- API routes (all `/api/*` endpoints unchanged)
- Panel content (existing `create(panel)` functions reused as tab creators)
- Keyboard shortcuts (still work)
- Layout system (containers are just panels with tabs, saved/restored normally)

## What This DOES Change

- Windows dropdown shrinks from ~99 items to ~10
- Users discover features by category, not by name
- Plugins contribute tabs to existing windows, not new windows
- City sim's 25 modules don't create 25 panels — they contribute tabs to the Simulation container

---

## Implementation Estimate

| Phase | Effort | Risk | Dependency |
|-------|--------|------|------------|
| 1. TabbedPanel component | LOW | LOW | None |
| 2. EventBus tab registration API | LOW | LOW | Phase 1 |
| 3. Migrate core panels to tabs | MEDIUM | MEDIUM | Phase 2 |
| 4. Plugin SDK update | LOW | LOW | Phase 2 |
| 5. Windows dropdown update | LOW | LOW | Phase 3 |
| 6. Addon tab discovery | MEDIUM | MEDIUM | Phase 4 |

Total: ~3-4 work sessions. Non-breaking — can be done incrementally while everything else continues working.

## Agent Audit Findings (2026-03-23)

**Panel auditor found:** 94 core panels (36,353 LOC) + 2 addon panels (meshtastic, hackrf). All floating, no tab groups. Some panels implement internal tabs (meshtastic has 7) but PanelManager doesn't know about them.

**Addon auditor found two separate UI systems:**
1. **Addons** (tritium-addons, TOML manifests, dynamic import via addon-loader.js, hot-reloadable)
2. **Plugins** (tritium-sc built-in, Python PluginInterface, panels hardcoded in panels/ directory)

**Three paths identified:**
- **Path A (Recommended):** Convert city sim to addon pattern with TOML manifest. Split into logical panels. Uses proven addon infrastructure.
- **Path B:** Enhance PluginInterface with panel registration. Backend builds manifest from plugin classes.
- **Path C:** Build consolidated panel container with tabs (the approach in this doc).

**Recommendation:** Combine Path A and C. City sim becomes an addon (using proven TOML manifest pattern), AND we build the TabbedPanel container component so the addon contributes tabs instead of standalone windows. This gives us the best of both: addon hot-reload + consolidated UI.

---

## Decision Points for User

1. **How many containers?** 8-10 seems right. Too few = tabs get long. Too many = same problem as now.
2. **Should legacy standalone panels be preserved?** Recommend yes, with a "Show All (Legacy)" option.
3. **Should the tab order be fixed or user-customizable?** Start fixed, add drag-to-reorder later.
4. **Should plugins be REQUIRED to use tabs, or is it optional?** Optional — both modes coexist.
