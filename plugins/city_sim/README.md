# City Simulation Plugin

OSM-based city simulation with NPC daily routines, vehicle traffic, protest engine, and event director.

## Architecture Layers

### Layer 1: Pure Simulation Engine (No Rendering)
**Location:** `src/frontend/js/command/sim/` (25 ES modules)

Pure logic — no Three.js, no DOM, no browser APIs. Can run in Node.js for testing.

| Module | Purpose |
|--------|---------|
| road-network.js | Dijkstra graph from OSM roads |
| idm.js | Intelligent Driver Model car-following |
| mobil.js | MOBIL lane change evaluation |
| vehicle.js | Vehicle agent with intent, mass, routing |
| pedestrian.js | NPC with identity, role, daily routine, mood |
| traffic-controller.js | Signal phase cycling, adaptive timing |
| spatial-grid.js | O(1) proximity queries |
| weather.js | Day/night cycle, weather state |
| anomaly-detector.js | Z-Score + Markov anomaly detection |
| sensor-bridge.js | Synthetic BLE/YOLO data generation |
| identity.js | Deterministic NPC names/traits (from tritium-lib) |
| daily-routine.js | Role-based schedules (from tritium-lib) |
| schedule-executor.js | SimClock + schedule tick (from tritium-lib) |
| protest-engine.js | Epstein civil unrest model (from tritium-lib) |
| protest-scenario.js | 8-phase protest scenario goals (from tritium-lib) |
| protest-manager.js | Wires protest engine to NPC system |
| event-director.js | Scheduled/random city events |
| scenario-loader.js | Built-in scenarios + load/export |
| procedural-city.js | Offline city generation (no OSM needed) |
| city-sim-manager.js | Central orchestrator (ticks all systems) |
| rl-hooks.js | RL observation/action/reward interface |
| ambient-sound.js | Audio event bridge |
| lod-manager.js | Building LOD (requires THREE) |
| facade-shader.js | Building window shader (requires THREE) |
| weather-vfx.js | Rain/street light particles (requires THREE) |

### Layer 2: Backend Plugin (Python)
**Location:** `plugins/city_sim/`

API routes, configuration, telemetry broadcasting. Implements PluginInterface.

| File | Purpose |
|------|---------|
| plugin.py | CitySimPlugin lifecycle (start/stop/configure) |
| routes.py | FastAPI routes: /config, /status, /scenarios, /demo-city, /telemetry, /protest, /event |
| tritium_addon.toml | Addon manifest for UI integration |

### Layer 3: Frontend Integration (MapLibre + Three.js)
**Location:** `src/frontend/js/command/map-maplibre.js` (integration points)

Wires the sim engine into the Command Center map. This layer:
- Creates/updates MapLibre 2D markers (circles, heading lines, heatmap)
- Creates/updates Three.js 3D InstancedMesh (vehicles, pedestrians, signals)
- Handles EventBus integration (start/stop, protest, events)
- Manages the standalone sim tick interval
- Provides the onscreen HUD overlay

### Layer 4: Panel UI
**Location:** `src/frontend/js/command/panels/city-sim.js`

Control panel with stats, sparklines, scenario selector, protest section.
Contributes a tab to the Simulation container via `simulation-container.js`.

## Separation Rules

1. **Layer 1 never imports from Layers 2-4.** Sim modules are pure logic.
2. **Layer 2 never imports frontend code.** Python backend is headless.
3. **Layer 3 imports Layer 1** (CitySimManager) but Layer 1 doesn't know about Layer 3.
4. **Layer 4 reads stats** from Layer 3's exports but doesn't directly access Layer 1.
5. **EventBus is the glue** — all inter-layer communication uses EventBus events, not direct imports.

## Commander Integration

The city sim emits generic events:
- `alert:new` — any commander plugin (Amy, Sentinel, etc.) can subscribe
- `city-sim:protest-phase` — commander narrates phase transitions
- `city-sim:collision` — commander reports incidents
- `city-sim:anomaly` — commander flags anomalies

The city sim does NOT depend on Amy or any specific commander.

## Testing

```bash
# JS tier 3 tests (structural + inline physics)
./test.sh 3

# Protest lifecycle (Node.js, all 8 phases)
node tests/js/test_protest_lifecycle.mjs

# Python backend tests
.venv/bin/python3 -m pytest tests/engine/api/test_city_sim.py -v

# Browser integration (65 tests)
# Requires running server on port 8000
python3 -m pytest tests/visual/test_city_sim_visual.py -v

# OpenCV road alignment
python3 -m pytest tests/visual/test_city_sim_road_alignment.py -v
```
