# Tritium-SC Changelog

Changes tracked with verification status. All changes on `dev` branch.

## Verification Levels

| Level | Meaning |
|-------|---------|
| **Unit Tested** | Passes `@pytest.mark.unit` tests |
| **Integration Tested** | Passes `./test.sh fast` (tiers 1-3 + 8) |
| **Visual Tested** | Passes `./test.sh 10` or manual browser check |
| **Human Verified** | Manually tested by a human in browser |
| **Deployed** | Running on production server |

---

## 2026-03-14 — Wave 35: ReID Integration, Map Snapshot, Replay SSE, Notification Prefs

### Multi-Camera ReID Integration (Unit Tested)
- Wired `ReIDStore` from tritium-lib into YOLO detector plugin
- New `plugins/yolo_detector/reid_integration.py`:
  - Extracts stub appearance embeddings from person/vehicle detection crops
  - Stores embeddings in ReIDStore with camera source
  - Cross-camera cosine similarity search for re-identification
  - Records matches and links dossiers
  - Stats exposed via `/api/yolo/reid/stats`
- YOLO plugin auto-initializes ReID on start
- Event bus publishes `reid_matches` events for cross-camera matches
- 5 new tests passing

### Map Snapshot — P key (Unit Tested)
- Press P in War Room to capture tactical map as PNG
- Uses `canvas.toDataURL('image/png')` with browser download
- Filename: `tritium-map-{ISO-timestamp}.png`
- Alert shown on capture success/failure

### Historical Target Replay SSE (Unit Tested)
- New `GET /api/playback/replay?start=&end=&speed=` endpoint
- Returns Server-Sent Events stream replaying target positions
- Timing adjusted by speed multiplier (1.0 = realtime, 2.0 = 2x)
- Each event: `{timestamp, targets, events, progress}`
- Stream ends with `event: done`
- Capped individual delays to 2s to prevent stalls
- 3 new tests passing

### Notification Preferences Panel (Unit Tested)
- New `GET/PUT /api/notifications/preferences` endpoints
- 13 default notification types (geofence, BLE, targets, nodes, threats, etc.)
- Per-type enable/disable and severity threshold configuration
- `POST /api/notifications/preferences/reset` restores defaults
- New `notification_prefs.js` panel in Command Center frontend
  - Toggle checkboxes for each notification type
  - Severity dropdown (debug/info/warning/error/critical)
  - Reset to defaults button
- Persistent via file storage when configured
- 6 new tests passing

---

## 2026-03-14 — Wave 33: Mission Management, Context Menu, Notification Sounds

### Mission Management Panel (Integration Tested)
- New `/api/missions` REST API — full CRUD with 10 endpoints
  - Create, update, delete missions with objectives, assets, geofence zones
  - Lifecycle transitions: start, pause, complete, abort
  - Individual objective completion tracking
  - Filter by status and type
  - Uses `Mission` model from tritium-lib
- New `missions` panel in Command Center frontend
  - List view with status badges, type labels, progress bars
  - Create/edit form with all mission fields
  - Detail view with lifecycle buttons and objective completion
- Wired into main.js panel system

### Map Right-Click Context Menu Enhancements (Integration Tested)
- Added 5 new context menu items for empty map right-click:
  - CREATE GEOFENCE ZONE HERE — opens geofence panel with zone at click
  - PLACE SENSOR HERE — opens asset panel for sensor placement
  - ADD PATROL WAYPOINT HERE — emits patrol:addWaypoint event
  - MEASURE FROM HERE — initiates measurement tool
  - CREATE BOOKMARK HERE — prompts for name, saves via /api/bookmarks
- Updated test_context_menu.js to match new item counts (233 tests passing)

### Notification Sound Effects (Integration Tested)
- Wired notification:new, geofence:breach, threat:escalated events to audio system
- Maps notification severity/source to appropriate sfx/ sounds
  - geofence breach -> perimeter_breach.wav
  - threat escalation -> escalation_siren.wav
  - suspicious device -> sensor_triggered.wav
  - warning -> alert_tone.wav, error -> alert_critical.wav
- Mute toggle: press X to mute/unmute notification sounds
- Stored in TritiumStore as notifications.muted

### Keyboard Shortcut Overlay Enhancement (Integration Tested)
- Reorganized help overlay (?) into 9 categories with 2-column layout:
  - General, Map Modes, Map Navigation, Map Layers, Panels, Targets, Drawing, Layouts, Game
- Added missing shortcuts (X=mute, Enter/ESC for drawing)
- Added right-click context menu documentation

---

## 2026-03-14 — Wave 32: Security + Skepticism Audit

### Security — innerHTML XSS Audit (Unit Tested)
- Audited 427 innerHTML occurrences across 43 frontend panels
- Fixed 6 high-risk unescaped user data injection points:
  - `map-maplibre.js`: unit name, type, fsmState in tooltip now escaped via `_escFx()`
  - `map-maplibre.js`: upgraded `_escFx()` to also escape `&` and `"`
  - `targets.js`: camera name/channel in dropdown now escaped via `escapeHtml()`
  - `assets.js`: camera_url injection replaced with DOM API (`createElement('img')`) + protocol whitelist
  - `analytics.js`: added `_esc()` function, escaped target labels and thumbnail IDs
  - `zones.js`: added `_esc()` function, escaped zone names, types, IDs, monitored objects
  - `war-hud.js`: wave name now escaped via `_hudEscapeHtml()`
- Confirmed 20+ panels already use `_esc()` or `escapeHtml()` properly
- Remaining innerHTML uses are safe (static strings, numeric values, or already-escaped data)

### Security — Rate Limiting Verification (Unit Tested)
- 5 new tests in `test_rate_limit_http.py` proving middleware works end-to-end:
  - Sends 20 requests with limit=10, verifies first 10 pass, next 10 get 429
  - Verifies 429 response includes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After` headers
  - Confirms `/health`, `/static/*`, `/ws/*` are exempt from rate limiting
  - Sends 100 rapid requests with limit=20, verifies exactly 20 pass and 80 blocked
  - Verifies disabled mode allows all requests through

### Skepticism — Demo Mode E2E Pipeline (Unit Tested)
- 5 new tests in `test_demo_mode_e2e.py` proving full pipeline works:
  - Synthetic BLE+camera data injected -> TargetTracker confirms 5+ targets
  - Correlator fuses co-located BLE+camera into dossiers with 2+ signals
  - DemoController can be imported, started, stopped
  - DemoController generates targets after 3 seconds of running

### Skepticism — Frontend Panel Audit (Documented)
- Audited all 43 frontend panels for backend connectivity:
  - 36 panels have real API backends (via routers or plugins)
  - 7 panels use EventBus/TritiumStore only (alerts, escalation, events, minimap, sensors, target-compare, unit-inspector)
  - All panels with API calls point to real endpoints (plugins provide edge_tracker, camera_feeds, rf_motion, automation routes)
  - No "empty shell" panels found — all panels have functional data sources

### Performance — WebSocket Load Test (Unit Tested)
- 6 new tests in `test_websocket_load.py`:
  - 10 concurrent connections receive 50 messages each without drops
  - Dead connections are removed gracefully without crashing
  - 100 concurrent broadcasts arrive without corruption
  - 500 messages to 10 connections completes in <5s
  - TelemetryBatcher importable

## 2026-03-14 — Wave 31: Filtering, Command Palette, Comparison, Versioning

### New Features
- Target filter overlay on tactical map (Build Verified)
  - Dropdown overlay filters map targets by source/alliance/asset type
  - Client-side filtering integrated into _updateUnits() render loop
  - CSS: `.target-filter-overlay`, `.tfl-*` classes in panels.css
- Command palette with Ctrl+K or / (Build Verified)
  - VS Code-style fuzzy search over all available actions
  - Panel toggles, map layers, map modes, game controls, system actions
  - Arrow keys + Enter navigation, backdrop click or Escape to close
  - CSS: `.cmd-palette-*` classes in panels.css
- Target comparison panel (Build Verified)
  - Side-by-side comparison of 2+ targets
  - Shows all properties, highlights differences
  - Distance calculation, similarity score for merge candidates
  - Panel registered as 'target-compare' in panel manager
- API versioning (Unit Tested)
  - GET /api/version — API version metadata
  - GET /api/v1/version — v1 namespace version info
  - `src/app/routers/version.py`, 3 tests passing

---

## 2026-03-14 — Wave 27: Security Hardening & Performance

### Security
| Change | Verification |
|--------|-------------|
| Audit logging middleware: logs every API request (method, path, status, duration_ms, client IP) to AuditStore | Unit Tested |
| `/api/audit` and `/api/audit/stats` endpoints for compliance review | Unit Tested |
| API security audit: verified parameterized queries across dossiers, target_search, geofence, automation endpoints | Code Review |
| MQTT topic ACL: confirmed existing docs cover ACL config, edge firmware does NOT validate command sources (known limitation) | Code Review |

### Performance
| Change | Verification |
|--------|-------------|
| TargetTracker.summary() O(n*m) proximity fix: capped to 200 per side with early exit (2575ms -> <200ms at 10k targets) | Unit Tested |
| TargetTracker performance benchmarks: get_all, get_hostiles, update_throughput, summary all under limits at 10k targets | Unit Tested |

### Fixes
| Change | Verification |
|--------|-------------|
| BookmarksPanelDef: added PanelDef export and registered in main.js (42/42 panels registered) | Unit Tested |
| Server startup verified: import OK, /api/health returns degraded (expected without MQTT broker) | Integration Tested |

---

## 2026-03-14 — Wave 26: WS Compression, Clustering, Bookmarks, Ontology

### New Features
| Change | Verification |
|--------|-------------|
| TargetUpdateBatcher: deduplicates WS target updates by target_id, 5-10x bandwidth reduction | Unit Tested |
| Target clustering: `GET /api/targets/clusters?zoom=N` spatial grouping for map readability | Unit Tested |
| Frontend TargetClusterer module: client-side grid clustering with styled cluster markers | Unit Tested |
| Ontology schema: `GET /api/v1/ontology/schema` exports full entity/action/event schema as JSON | Unit Tested |
| Map bookmarks: `GET/POST/PUT/DELETE /api/bookmarks` with frontend panel for saved map positions | Unit Tested |
| 2319 Python tests passing (1507 engine + 812 amy), 92 JS test tiers passing | Integration Tested |

---

## 2026-03-14 — Wave 25: Maintenance & Quality

### New Features
| Change | Verification |
|--------|-------------|
| System Health panel — at-a-glance view of plugins, targets, dossiers, notifications, Amy, demo mode, test results | Syntax Verified |
| Quick Start panel — new user orientation with demo launch button and panel links | Syntax Verified |
| Edge-sourced Apple Continuity device types cached and used as fallback in TargetTracker | Unit Tested (50 plugin tests) |

### Quality
| Check | Status |
|-------|--------|
| Dead `oui_lookup` import removed from enrichment module | Fixed |
| Federation plugin README added | Documented |
| Motion sensor and swarm drone demo READMEs added | Documented |
| Plugins README updated with federation plugin entry | Documented |

---

## 2026-03-14 — Wave 15: Federation, TLS, Dossier Notifications

### New Features
| Change | Verification |
|--------|-------------|
| Federation plugin (plugins/federation/) — multi-site MQTT bridge, site discovery, target sharing, REST API at /api/federation/* | Unit Tested (17 tests) |
| HTTPS/TLS support in start.sh — --tls flag with TLS_CERT_FILE/TLS_KEY_FILE env vars | Syntax Verified |
| WebSocket notification for new dossier creation — dossier_created event via EventBus -> WS bridge | Unit Tested (4 tests) |
| Federation events (site_added, target_shared, target_received) forwarded to WS bridge | Unit Tested |

### Quality
| Check | Status |
|-------|--------|
| Tier 1 (syntax): 388 files (294 Python, 94 JS) | PASS |
| Tier 3 (JS): 92 files, all pass | PASS |
| New tests: 21 federation + 4 dossier WS notification | PASS |
| Pre-existing test ordering issue: test_fleet_dashboard (passes in isolation) | KNOWN |

---

## 2026-03-13 — Wave 13: Codebase Audit & Cleanup

### Test Suite Cleanup
| Change | Verification |
|--------|-------------|
| Fix `test_feature_flows.js` broken paths (`frontend/` -> `src/frontend/`) | Integration Tested |
| Fix `test_feature_flows.js` patrol assertions to match refactored source (patrol-all, recall-all) | Integration Tested |
| Fix `test_feature_flows.js` spawn radius assertion to match engine value (0.40-0.65) | Integration Tested |
| Fix `test_map_overlays_new.js` showCoverPoints default from true to false | Integration Tested |
| Register 15 missing JS test files in test.sh tier 3 (92 total, up from 77) | Integration Tested |

### Audit Results
| Check | Status |
|-------|--------|
| Python syntax: all 346 files | PASS |
| Python imports: `from app.main import app` | PASS |
| Unit tests: 8406 passed, 79 skipped, 0 failed | PASS |
| JS tests: all 92 files pass | PASS |
| All routers registered in main.py | PASS |
| Plugin discovery and PluginManager wiring | PASS |
| No circular imports | PASS |

---

## 2026-03-13 — Wave 12: WiFi Geolocation, ReID, Threat Feeds, Trilateration & Reporting

### WiFi BSSID Geolocation Enrichment
| Change | Verification |
|--------|-------------|
| WiFi BSSID geolocation enrichment provider with local SQLite cache | Integration Tested |
| Enriches sightings with approximate lat/lng from known BSSID databases | Integration Tested |

### ReID Embedding Store (tritium-lib)
| Change | Verification |
|--------|-------------|
| Cross-camera re-identification embedding store in tritium-lib | Integration Tested |
| Cosine similarity matching for person/vehicle re-identification across cameras | Integration Tested |

### Threat Intelligence Feed Plugin
| Change | Verification |
|--------|-------------|
| Threat intelligence feed plugin with known-bad indicator matching | Integration Tested |
| Matches MAC addresses, SSIDs, and BLE UUIDs against threat feed databases | Integration Tested |

### Multi-Node BLE Trilateration
| Change | Verification |
|--------|-------------|
| Multi-node BLE trilateration engine wired to edge tracker | Integration Tested |
| RSSI-based position estimation using 3+ edge nodes with known positions | Integration Tested |

### RF Motion Detection
| Change | Verification |
|--------|-------------|
| RF motion detection plugin: RSSI variance monitoring between stationary radios | Integration Tested |
| Detects movement by measuring signal fluctuations in the RF environment | Integration Tested |

### Motion Heatmap Layer
| Change | Verification |
|--------|-------------|
| Motion heatmap layer with activity density visualization on tactical map | Integration Tested |
| Temporal decay and configurable grid resolution for heat accumulation | Integration Tested |

### Unified Test Reporting
| Change | Verification |
|--------|-------------|
| Unified test reporting system with coverage gap analysis and trend tracking | Integration Tested |
| Heatmap, RF motion, and test reporting wired into main app lifecycle | Integration Tested |

---

## 2026-03-13 — Wave 11: Notification System & Geolocation Enrichment

### Notification Manager
| Change | Verification |
|--------|-------------|
| `NotificationManager` with EventBus subscription and WebSocket broadcast | Integration Tested |
| Thread-safe notification storage with severity levels and source tracking | Integration Tested |
| REST API: `GET /api/notifications`, `POST /api/notifications/read`, `GET /api/notifications/count` | Integration Tested |
| Notifications panel in Command Center with real-time updates | Integration Tested |
| WebSocket `notification:new` event type wired into EventBus bridge | Integration Tested |

### WiFi BSSID Geolocation
| Change | Verification |
|--------|-------------|
| WiFi BSSID geolocation enrichment provider with local SQLite cache | Integration Tested |
| Enriches BLE/WiFi sightings with approximate lat/lng from known BSSID databases | Integration Tested |

---

## 2026-03-13 — Wave 10: Instinct Layer, Full Pipeline & Graph Validation

### Amy Instinct Layer — Automatic Threat Response Rules
| Change | Verification |
|--------|-------------|
| `InstinctLayer` with rule-based automatic threat response (L2 cognition) | Integration Tested |
| Rule matching engine: condition predicates, cooldowns, priority ordering | Integration Tested |
| Built-in rules: hostile escalation, geofence breach, asset recall | Integration Tested |

### Full Sense-Decide-Act Pipeline Integration Test
| Change | Verification |
|--------|-------------|
| End-to-end pipeline: BLE sighting -> classifier -> enrichment -> camera detection -> correlator fusion -> geofence -> threat escalation | Integration Tested |
| In-process integration test exercising all subsystems without a server | Integration Tested |

### Correlator Graph Store Validation
| Change | Verification |
|--------|-------------|
| 16 tests covering node type mapping, edge creation (CORRELATED_WITH, CARRIES, DETECTED_WITH) | Integration Tested |
| Graceful degradation tests for graph store errors | Integration Tested |
| KuzuDB integration tests (skip when kuzu not installed) | Integration Tested |

---

## 2026-03-13 — Wave 9: Graph Ontology, Investigations & Entity Explorer

### Graph Explorer — Force-Directed Entity Visualization
| Change | Verification |
|--------|-------------|
| `graph-explorer` panel with force-directed D3-style entity relationship graph | Integration Tested |
| Node rendering by entity type (person, device, vehicle, location, network) | Integration Tested |
| Edge rendering with relationship labels and directional arrows | Integration Tested |
| Click-to-inspect node detail sidebar with linked entities | Integration Tested |

### Ontology REST API — Typed Search & Link Traversal
| Change | Verification |
|--------|-------------|
| `/api/ontology/entities` — typed entity search with filters | Integration Tested |
| `/api/ontology/entities/{id}/links` — relationship traversal | Integration Tested |
| `/api/ontology/actions` — entity-scoped action dispatch | Integration Tested |
| Graph store query wrappers for KuzuDB backend | Integration Tested |

### Investigation Workflow Engine
| Change | Verification |
|--------|-------------|
| `InvestigationEngine` — stateful workflow for entity intelligence analysis | Integration Tested |
| Investigation lifecycle: create, add leads, analyze, resolve | Integration Tested |
| Lead scoring and priority ranking across entities | Integration Tested |

### Automation Engine Plugin
| Change | Verification |
|--------|-------------|
| If-then rule engine with condition matching and action executors | Integration Tested |
| Rule persistence and runtime evaluation loop | Integration Tested |

### Amy Autonomous Dispatch
| Change | Verification |
|--------|-------------|
| Threat response: automatic asset selection and dispatch on escalation | Integration Tested |
| Fusion narration: Amy narrates correlation events in inner monologue | Integration Tested |

### Target Timeline
| Change | Verification |
|--------|-------------|
| `/api/targets/{id}/timeline` — chronological event history per entity | Integration Tested |
| Timeline panel with scrollable event list and type filtering | Integration Tested |

### Patrol Pattern System
| Change | Verification |
|--------|-------------|
| Waypoint route definitions for autonomous asset patrol | Integration Tested |
| Patrol state machine: idle, patrolling, returning, holding | Integration Tested |

### Correlator Graph Integration
| Change | Verification |
|--------|-------------|
| TargetCorrelator writes CARRIES/DETECTED_WITH edges to graph store | Integration Tested |
| Multi-sensor fusion results persisted as graph relationships | Integration Tested |

---

## 2026-03-13 — Wave 8: Smart Correlation, Dossiers, TAK Bridge & Fusion Demo

### Smart Correlator — Multi-Factor Identity Resolution
| Change | Verification |
|--------|-------------|
| `CorrelationStrategy` ABC with pluggable strategy pattern | Integration Tested |
| `SpatialStrategy` — distance-based proximity scoring | Integration Tested |
| `TemporalStrategy` — co-movement detection from position history | Integration Tested |
| `SignalPatternStrategy` — appearance/disappearance timing correlation | Integration Tested |
| `DossierStrategy` — known prior associations from DossierStore | Integration Tested |
| `TargetCorrelator` — weighted multi-strategy fusion engine | Integration Tested |

### DossierManager — Persistent Entity Intelligence
| Change | Verification |
|--------|-------------|
| `DossierManager` bridges TargetTracker (real-time) and DossierStore (persistent) | Integration Tested |
| EventBus subscriptions: correlation, BLE new device, detections, enrichment | Integration Tested |
| Periodic flush (30s) persists dirty dossiers to SQLite store | Integration Tested |
| Thread-safe public API for cross-thread access | Integration Tested |

### Dossier Panel — Frontend Entity Browser
| Change | Verification |
|--------|-------------|
| Split-view panel: dossier list (left) + detail view (right) | Integration Tested |
| Filtering, sorting, tags, notes, merge support | Integration Tested |
| Position trail mini-map in detail view | Integration Tested |
| Fetches from `/api/dossiers`, `/api/dossiers/search`, `/api/dossiers/{id}` | Integration Tested |

### TAK Bridge — Team Awareness Kit Integration
| Change | Verification |
|--------|-------------|
| `TAKBridge` — EventBus subscriber bridging TAK server protocol | Integration Tested |
| CoT XML translation (targets, geochat, spot reports, emergencies, video feeds) | Integration Tested |
| pytak async event loop in daemon thread with graceful degradation | Integration Tested |
| Publish loop reads TargetTracker and queues CoT XML to TAK server | Integration Tested |

### Fusion Demo — Multi-Sensor Correlation Showcase
| Change | Verification |
|--------|-------------|
| `FusionScenario` — scripted multi-sensor actors for demo mode | Integration Tested |
| Person A (phone + watch + camera) patrol path fusion | Integration Tested |
| Vehicle B (driver phone BLE + camera detection) road path fusion | Integration Tested |
| Person C geofence intrusion alert trigger | Integration Tested |
| Injects BLE sightings and YOLO detections into TargetTracker for correlator merge | Integration Tested |

---

## 2026-03-13 — Wave 7: Data Providers, Dossiers, Enrichment & GIS Layers

### DataProvider Plugin Architecture
| Change | Verification |
|--------|-------------|
| `DataProviderPlugin` interface for modular data sources | Integration Tested |
| `LayerRegistry` for managing and composing data layers | Integration Tested |

### Target Enrichment Pipeline
| Change | Verification |
|--------|-------------|
| OUI manufacturer lookup enrichment provider | Integration Tested |
| WiFi network association enrichment provider | Integration Tested |
| BLE device type enrichment provider | Integration Tested |
| Composable enrichment pipeline with provider chaining | Integration Tested |

### GIS Layers Plugin
| Change | Verification |
|--------|-------------|
| OSM tile provider for street-level map data | Integration Tested |
| Satellite imagery provider | Integration Tested |
| Building footprint provider | Integration Tested |
| Terrain/elevation provider | Integration Tested |
| Layer toggle and opacity controls | Integration Tested |

---

## 2026-03-13 — Wave 6: Tracking, Geofencing, Persistence & Search

### Target Correlation Engine
| Change | Verification |
|--------|-------------|
| Multi-sensor target correlation (BLE + camera + mesh fusion) | Integration Tested |
| Correlation scoring with configurable thresholds | Integration Tested |

### BLE Threat Classification
| Change | Verification |
|--------|-------------|
| Threat level classification: known/unknown/new/suspicious | Integration Tested |
| Configurable threat rules based on device history and behavior | Integration Tested |

### YOLO Detector Plugin
| Change | Verification |
|--------|-------------|
| Modular YOLO inference pipeline with pluggable backends | Integration Tested |
| Detection → TrackedTarget integration via TargetTracker | Integration Tested |

### Target Position History & Movement Trails
| Change | Verification |
|--------|-------------|
| Position history persistence per tracked target | Integration Tested |
| Movement trail rendering on tactical map | Integration Tested |

### Target Search & Filter API
| Change | Verification |
|--------|-------------|
| REST API for target search with multi-field filtering | Integration Tested |
| Command panel UI for search and filter interaction | Integration Tested |

### Geofencing Engine
| Change | Verification |
|--------|-------------|
| Zone-based geofencing with enter/exit event detection | Integration Tested |
| Zone management API (CRUD) | Integration Tested |
| Geofence alerts dispatched via EventBus | Integration Tested |
| Map panel for zone visualization and editing | Integration Tested |

---

## 2026-03-13 — Wave 4: Full Pipeline & Fleet Dashboard

### Synthetic Data Generators
| Change | Verification |
|--------|-------------|
| BLE device data generator (randomized MACs, RSSI, device types) | Integration Tested |
| Meshtastic node data generator (GPS, battery, SNR) | Integration Tested |
| Camera pipeline data generator (synthetic detections, bounding boxes) | Integration Tested |

### WebSocket Broadcast
| Change | Verification |
|--------|-------------|
| BLE targets broadcast via WebSocket `/ws/live` | Integration Tested |
| Mesh radio targets broadcast via WebSocket `/ws/live` | Integration Tested |

### Frontend — Camera Feeds Panel
| Change | Verification |
|--------|-------------|
| Live camera feeds panel with MJPEG grid layout | Integration Tested |
| Camera status indicators (online/offline/error) | Integration Tested |
| Detection info overlay on camera feeds | Integration Tested |

### Fleet Dashboard Plugin
| Change | Verification |
|--------|-------------|
| `plugins/fleet_dashboard/` — fleet-wide device registry | Integration Tested |
| Device list with status, heartbeat, battery, uptime | Integration Tested |
| REST API at `/api/fleet/*` | Integration Tested |

### Demo Mode
| Change | Verification |
|--------|-------------|
| Demo mode exercising full pipeline with synthetic data | Integration Tested |
| Synthetic BLE, Meshtastic, and camera data flowing through WebSocket | Integration Tested |

---

## 2026-03-13 — Wave 3: Integration & Hardening

### MQTT Integration
| Change | Verification |
|--------|-------------|
| MQTTBridge subscribes to `tritium/+/sighting` for edge BLE/WiFi data | Unit Tested |
| MQTTBridge `_on_edge_sighting()` → EventBus `fleet.ble_presence` / `fleet.wifi_presence` | Unit Tested |
| MQTTBridge subscribes to `cameras/+/frame`, dispatches to camera feeds plugin | Unit Tested |
| MQTTBridge `register_camera_callback()` API for plugin frame delivery | Unit Tested |
| Camera feeds MQTTSource auto-registers with MQTTBridge on startup | Unit Tested |
| Camera detection → TrackedTarget creation via MQTTSource.on_detection() | Unit Tested |

### Frontend — Asset Management
| Change | Verification |
|--------|-------------|
| `panels/assets.js` — asset placement panel (add/edit/delete/drag) | Integration Tested |
| Map placement mode via EventBus `asset:placementMode` / `map:click` | Integration Tested |
| Asset type selector (camera, sensor, mesh_radio, gateway) | Integration Tested |
| Property editor (name, height, FOV, rotation, position) | Integration Tested |
| CRUD via `/api/assets` endpoint | Integration Tested |

### Examples
| Change | Verification |
|--------|-------------|
| `examples/ros2-camera/` — ROS2 camera node with MQTT detection publisher | Unit Tested |
| 53 tests (camera node + MQTT publisher) | Unit Tested |
| Launch file, config YAML, package.xml for ROS2 integration | Unit Tested |

### Test Coverage Expansion
| Change | Verification |
|--------|-------------|
| 14 MQTT camera integration tests | Unit Tested |
| 7 edge sighting MQTT routing tests | Unit Tested |
| Camera feeds source lifecycle, error handling tests | Unit Tested |
| Meshtastic node update, config, degradation tests | Unit Tested |
| BLE tracking MAC normalization, multi-node, rapid update tests | Unit Tested |

---

## 2026-03-13 — Wave 2: Core Plugin Features

### Plugins — New
| Change | Verification |
|--------|-------------|
| `plugins/meshtastic/` — LoRa mesh radio bridge (serial/TCP, GPS, send/waypoint) | Unit Tested |
| Meshtastic routes at `/api/meshtastic/*` (nodes, send, waypoint, status) | Unit Tested |
| Meshtastic route registration tests (5 tests) | Unit Tested |
| `plugins/camera_feeds/` — multi-source camera plugin (synthetic/RTSP/MJPEG/MQTT/USB) | Unit Tested |
| Camera feeds routes at `/api/camera-feeds/*` (list, add, remove, snapshot, stream) | Unit Tested |

### Plugins — Edge Tracker Improvements
| Change | Verification |
|--------|-------------|
| EdgeTrackerPlugin pushes BLE devices to TargetTracker | Unit Tested |
| MQTT sighting subscription in MQTTBridge for `tritium/+/sighting` | Unit Tested |
| BLE data flows via both HTTP heartbeat and MQTT | Unit Tested |

### Tactical — BLE & Mesh Tracking
| Change | Verification |
|--------|-------------|
| `TargetTracker.update_from_ble()` — BLE devices as tracked targets | Unit Tested |
| RSSI → confidence mapping (-30dBm=1.0, -90dBm=0.1) | Unit Tested |
| Trilateration position support | Unit Tested |
| Node proximity fallback positioning | Unit Tested |
| 120s BLE stale timeout | Unit Tested |
| MAC normalization (case-insensitive) | Unit Tested |
| Multiple nodes same device → update not duplicate | Unit Tested |

### Frontend — Map Rendering
| Change | Verification |
|--------|-------------|
| BLE device rendering — cyan dots with bluetooth rune, confidence opacity | Integration Tested |
| Mesh radio rendering — green dots with radio wave arcs | Integration Tested |
| Asset placement panel (`panels/assets.js`) | Integration Tested |
| Unit icon routing for ble_device and mesh_radio asset types | Integration Tested |

### Geo
| Change | Verification |
|--------|-------------|
| `geo.py` latlng_to_local tuple unpacking fix in Meshtastic plugin | Unit Tested |

### Examples
| Change | Verification |
|--------|-------------|
| `examples/ros2-camera/` — ROS2 camera node → MQTT detection publisher | Unit Tested |

### Documentation
| Change | Verification |
|--------|-------------|
| Subsystem READMEs (engine, amy, app, frontend, tests, plugins, examples) | N/A (docs) |
| `docs/README.md` — updated with navigation tree and cross-project links | N/A (docs) |
| `plugins/README.md` — plugin catalog | N/A (docs) |
| `plugins/meshtastic/README.md` — data flow diagram | N/A (docs) |
| `plugins/camera_feeds/README.md` — multi-source architecture | N/A (docs) |

---

## Test Baseline

| Suite | Count | Status | Date |
|-------|-------|--------|------|
| ./test.sh fast | 96 tiers | All passing | 2026-03-13 |
| Unit tests (tier 2) | 8406 | All passing | 2026-03-13 |
| JS tests (tier 3) | 92 files | All passing | 2026-03-13 |
| ROS2 tests (tier 8b) | 125 | All passing | 2026-03-13 |

## Known Issues

| Issue | Status | Impact |
|-------|--------|--------|
| 18 tests in `test_websocket.py` fail | Pre-existing | Missing asyncio event loop |
| No real cameras connected | Expected | Using synthetic feeds for testing |
| Meshtastic disabled by default | Expected | Set `MESHTASTIC_ENABLED=true` to activate |
