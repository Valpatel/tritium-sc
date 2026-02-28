# GRAND PLAN: Overnight Autonomous Build

**Date**: 2026-02-22
**Branch**: dev
**Goal**: Make the neighborhood Nerf battle simulator feel real — streets, scale, pathfinding, graphics, fake camera feeds, and a polished UI — all driven by tests that prove it works.

---

## Philosophy

Every feature below is defined by what the **test report** shows when it passes. If there's no test, the feature doesn't exist. Agent teams work autonomously, save status to `docs/overnight-status/`, and commit frequently to dev so progress is never lost.

---

## WORKSTREAM 1: Street-Aware Navigation

**Current state**: Units move in straight lines through buildings. No pathfinding, no obstacles, no street data.

**Target state**: Units follow real streets from OpenStreetMap. Rovers drive on roads. Drones fly direct. Hostiles approach via streets and cut through yards. Buildings are obstacles.

### 1A. Extract Street Graph from OSM

Pull road segments from Overpass API for the configured geo-reference, build a NetworkX graph with intersections as nodes and road segments as edges.

**File**: `src/engine/tactical/street_graph.py`

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_street_graph_loads` | Graph has >= 10 nodes and >= 8 edges for neighborhood_default geo |
| `test_street_graph_nearest_node` | Given a point, nearest road node is within 50m |
| `test_street_graph_shortest_path` | A* path between two road nodes has >= 2 segments |
| `test_street_graph_path_follows_roads` | Every waypoint in path is within 5m of a road segment |
| `test_street_graph_caching` | Second load uses disk cache, completes in < 10ms |
| `test_street_graph_no_network` | Gracefully falls back to direct waypoints when offline |

### 1B. Building Footprints as Obstacles

Pull building polygons from Overpass API. Units cannot path through buildings.

**File**: `src/engine/tactical/obstacles.py`

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_buildings_loaded` | >= 5 building polygons within 200m of center |
| `test_point_inside_building` | Known building center returns True |
| `test_point_outside_building` | Known street point returns False |
| `test_path_avoids_buildings` | Path from A to B does not cross any building polygon |

### 1C. A* Pathfinding on Street Graph

Replace straight-line waypoint following with A* on the street graph. Different unit types use different strategies.

**File**: `src/engine/simulation/pathfinding.py`

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_rover_follows_roads` | Rover path stays within 3m of road centerline |
| `test_drone_flies_direct` | Drone path is straight line (ignores roads) |
| `test_hostile_approaches_via_street` | Hostile enters on road, then cuts through yard near objective |
| `test_turret_no_path` | Turret has empty path (stationary) |
| `test_path_distance_realistic` | A 100m straight-line trip becomes ~120-180m on roads |
| `test_path_recalculation` | When dispatch target changes, path recalculates within 1 tick |
| `test_unit_turns_at_intersections` | Heading changes smoothly at waypoints, not instant snap |

### 1D. Wire Pathfinding into SimulationEngine

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_sim_engine_uses_pathfinder` | Engine tick moves rover along road path, not straight line |
| `test_hostile_spawns_on_road_edge` | Hostile spawn position is on a road at map boundary |
| `test_dispatch_generates_road_path` | POST /api/game/place produces road-following waypoints |
| `test_integration_10_wave_with_roads` | Full 10-wave battle completes; all unit movements follow roads |

---

## WORKSTREAM 2: Realistic Scale and Layout

**Current state**: 19 objects in a 400m x 400m box. Patrol routes are rectangles that don't match real streets.

**Target state**: Layout matches the actual neighborhood. Units patrol real streets. Turrets are placed at real intersections.

### 2A. Neighborhood Layout Overhaul

Regenerate `neighborhood_default.json` with positions that match real satellite imagery.

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_layout_units_on_roads` | All rover/drone spawn positions are within 10m of a road |
| `test_layout_turrets_at_intersections` | Turrets are within 15m of an intersection node |
| `test_patrol_routes_follow_roads` | Patrol waypoints all lie on road segments |
| `test_layout_covers_neighborhood` | Units spread across >= 60% of the 400m operational area |
| `test_layout_cameras_face_roads` | Camera positions have line-of-sight to a road |
| `test_no_units_inside_buildings` | No unit spawn point falls inside a building polygon |

### 2B. Scale Verification

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_rover_traversal_time` | Rover at 3 m/s crosses 200m patrol in ~80-120 seconds |
| `test_drone_traversal_time` | Drone at 5 m/s crosses 400m map in ~80-100 seconds |
| `test_hostile_approach_time` | Hostile at 2 m/s takes 60-150 seconds from edge to objective |
| `test_intercept_range_realistic` | Interception happens at 2m (~1 body length) |
| `test_turret_range_realistic` | Turret engagement range is 30-50m (~1 house lot) |
| `test_visual_scale_pixel_ratio` | At default zoom, 1 house lot (20m) is 50-80 pixels wide |

---

## WORKSTREAM 3: Unit Graphics and Visual Polish

**Current state**: Units are colored circles/rectangles. No sprites, no rotation, no distinct silhouettes.

**Target state**: Each unit type has a recognizable icon that rotates with heading. Hostiles look different from friendlies at a glance.

### 3A. Unit Icon System

Replace geometric shapes with purpose-drawn Canvas 2D icons (not image sprites — procedural drawing for crisp scaling).

**File**: `frontend/js/command/unit-icons.js`

**Test report shows** (Playwright screenshot + OpenCV):
| Test | Assertion |
|------|-----------|
| `test_rover_icon_distinct` | Rover pixels form a rounded rectangle with wheels (>= 40 green pixels) |
| `test_drone_icon_distinct` | Drone pixels form an X-shape with rotors (>= 30 green pixels) |
| `test_turret_icon_distinct` | Turret pixels show a barrel pointing in heading direction |
| `test_hostile_icon_red_diamond` | Hostile pixels form a filled red diamond (>= 20 red pixels) |
| `test_icons_rotate_with_heading` | Screenshot at heading=0 differs from heading=90 by > 10% pixels |
| `test_icons_scale_with_zoom` | Icons at zoom 2x are larger than at zoom 0.5x |
| `test_neutral_visually_distinct` | Neutral (blue) is clearly different from friendly (green) in pixel analysis |

### 3B. Combat Visual Improvements

**Test report shows** (Playwright screenshot during active battle):
| Test | Assertion |
|------|-----------|
| `test_projectile_trails_visible` | During combat, orange/yellow trail pixels detected (>= 50) |
| `test_explosion_particles_visible` | After elimination, red/orange particles detected within 500ms |
| `test_muzzle_flash_visible` | Frame captured during fire shows bright pixel cluster at turret |
| `test_health_bars_update` | Damaged unit has shorter green bar than undamaged |
| `test_kill_feed_entries` | Kill feed DOM element has >= 1 entry during active wave |
| `test_wave_banner_appears` | "WAVE" text visible in screenshot during wave transition |

### 3C. Fog of War on Command Center

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_fog_covers_unseen_areas` | Areas > 50m from any friendly are darker (mean brightness < 40) |
| `test_vision_cones_visible` | Friendly units have brighter circle around them (mean brightness > 80) |
| `test_fog_updates_with_movement` | Fog boundary moves as rover patrols |

---

## WORKSTREAM 4: Synthetic Camera Feeds

**Current state**: Procedural OpenCV renderers exist (bird_eye, street_cam, battle, neighborhood). No real images.

**Target state**: Fake security camera feeds using AI-generated or composited images that look like real CCTV. Both static snapshots and 5-second clips.

### 4A. AI-Generated Security Camera Stills

Use Ollama vision models on GB10-01 and GB10-02 to generate scene descriptions, then use OpenCV + procedural rendering to create convincing CCTV-style frames with:
- Perspective ground plane
- Time-of-day lighting (day/dusk/night)
- Camera overlay (timestamp, REC indicator, camera name)
- Realistic noise grain
- Occasional "person" or "car" blob composited in

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_synthetic_cctv_resolution` | Generated frame is 640x480 or 1280x720 |
| `test_synthetic_cctv_has_timestamp` | OCR or pixel check finds timestamp text in top-left |
| `test_synthetic_cctv_has_noise` | Frame std deviation > 5 (not perfectly clean CG) |
| `test_synthetic_cctv_day_vs_night` | Day frame mean brightness > 80; night frame < 40 |
| `test_synthetic_cctv_unique_frames` | 10 generated frames are all different (SSIM < 0.95 between pairs) |
| `test_mjpeg_stream_delivers_frames` | GET /api/synthetic/cameras/{id}/mjpeg returns >= 5 frames in 2 seconds |

### 4B. Parallel Generation on GB10 Fleet

Distribute frame generation across GB10-01 and GB10-02 via SSH.

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_gb10_02_ssh_reachable` | SSH to GB10-02 succeeds with no password |
| `test_parallel_generation_faster` | 100 frames on 2 machines < 1.5x time of 50 frames on 1 machine |
| `test_generated_frames_valid` | All frames from both machines decode as valid JPEG |

### 4C. Video Clip Generation (5-second loops)

Generate 5-second looping clips at 10 FPS using OpenCV VideoWriter.

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_clip_duration` | Generated clip is 4.5-5.5 seconds |
| `test_clip_fps` | Clip has 10 FPS (48-52 frames total) |
| `test_clip_has_motion` | Frame diff between first and last > 0 (something moved) |
| `test_clip_loops_cleanly` | Frame 0 and frame 49 are similar (SSIM > 0.7) |

### 4D. Camera Feeds Visible in UI

**Test report shows** (Playwright):
| Test | Assertion |
|------|-----------|
| `test_synthetic_camera_panel_shows_feed` | Pressing V shows PIP with non-black image |
| `test_synthetic_camera_switches_scenes` | Different scene types produce visually different feeds |

---

## WORKSTREAM 5: UI Completeness

**Current state**: Core gameplay loop works. Some panels are stubs, some features from USER-STORIES.md are unverified.

**Target state**: Every feature in USER-STORIES.md works and is tested.

### 5A. Setup Mode Polish

**Test report shows** (Playwright):
| Test | Assertion |
|------|-----------|
| `test_setup_mode_palette_visible` | Pressing S shows deploy palette with >= 3 categories |
| `test_ghost_turret_follows_cursor` | Mouse move in setup mode shows ghost marker at cursor position |
| `test_place_turret_creates_unit` | Click in setup mode creates new unit in TritiumStore |
| `test_delete_placed_unit` | Select + Delete removes the unit |
| `test_range_circle_visible` | Ghost turret shows range circle (cyan circle pixels detected) |

### 5B. Chat Overlay

**Test report shows** (Playwright):
| Test | Assertion |
|------|-----------|
| `test_chat_opens_with_c_key` | Pressing C makes chat overlay visible |
| `test_chat_input_accepts_text` | Typing in chat input field works |
| `test_chat_sends_to_api` | Submitting chat sends POST to /api/amy/chat |
| `test_chat_closes_with_escape` | Pressing Escape hides chat overlay |

### 5C. Audio System End-to-End

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_audio_effects_api_returns_list` | GET /api/audio/effects returns >= 5 effects |
| `test_audio_effect_plays` | GET /api/audio/effects/{name} returns valid WAV bytes |
| `test_mute_toggle_works` | Pressing M toggles mute state in UI |

### 5D. Full Battle Proof Test

A single end-to-end test that runs a complete 10-wave battle in headless Playwright and captures proof at every stage.

**Test report shows** (comprehensive proof):
| Test | Assertion |
|------|-----------|
| `test_proof_00_server_starts` | Health check passes |
| `test_proof_01_map_renders` | Canvas has non-black pixels |
| `test_proof_02_units_patrol_roads` | Units visible on satellite imagery, positions change over 5s |
| `test_proof_03_setup_mode_works` | Place 3 turrets, verify in store |
| `test_proof_04_battle_starts` | Press B, countdown appears, wave 1 starts |
| `test_proof_05_combat_active` | Hostiles visible (red pixels), projectiles firing |
| `test_proof_06_elimination_happens` | Kill feed has >= 1 entry |
| `test_proof_07_wave_progresses` | Wave number increases after clearing hostiles |
| `test_proof_08_battle_ends` | Victory or defeat screen appears |
| `test_proof_09_roads_respected` | Unit trail positions correlate with road overlay pixels |
| `test_proof_10_synthetic_camera` | PIP shows non-black synthetic feed |

Each test saves a timestamped screenshot to `tests/.test-results/proof/`. The test report includes all screenshots in a timeline view.

---

## WORKSTREAM 6: Test Infrastructure

### 6A. Overnight Status Files

Each agent writes status to `docs/overnight-status/{workstream}-{timestamp}.md` with:
- What was attempted
- What passed / failed
- What's left
- Commit hashes

### 6B. New Test Tier

Add `./test.sh 12` (or `--battle-proof`) that runs the full battle proof test from 5D.

**Test report shows**:
| Test | Assertion |
|------|-----------|
| `test_tier_12_exists` | `./test.sh 12` exits 0 |
| `test_tier_12_produces_screenshots` | >= 10 screenshots in proof directory |
| `test_tier_12_produces_report` | HTML report generated with screenshot timeline |

---

## Agent Team Structure

| Agent | Workstream | Focus | Validates With |
|-------|-----------|-------|---------------|
| **Navigator** | 1 (Streets) | Street graph, pathfinding, SimEngine integration | `pytest tests/amy/simulation/` |
| **Cartographer** | 2 (Scale) | Layout overhaul, position verification | `pytest tests/amy/simulation/` |
| **Artist** | 3 (Graphics) | Unit icons, combat visuals, fog | `./test.sh 10` + Playwright |
| **Cameraman** | 4 (Feeds) | Synthetic CCTV, parallel generation | `pytest tests/amy/synthetic/` |
| **Polisher** | 5 (UI) | Setup mode, chat, audio, proof test | `./test.sh 10` + Playwright |

Each agent:
1. Writes tests FIRST (TDD)
2. Implements until tests pass
3. Commits to dev with descriptive message
4. Writes status to `docs/overnight-status/`
5. Moves to next task

---

## Execution Order

```
Hour 0-1:   Navigator starts (1A street graph extraction)
            Cartographer starts (2A layout overhaul)
            Artist starts (3A unit icons)

Hour 1-2:   Navigator continues (1B buildings, 1C pathfinding)
            Cameraman starts (4A synthetic CCTV)
            Artist continues (3B combat visuals)

Hour 2-4:   Navigator wires pathfinding into engine (1D)
            Cartographer verifies scale (2B)
            Cameraman does parallel gen (4B) + clips (4C)
            Polisher starts (5A setup mode)

Hour 4-6:   All agents finish primary tasks
            Polisher runs full battle proof (5D)
            Everyone fixes failures from proof test

Hour 6-8:   Polish, fix edge cases, final commit
            Generate comprehensive test report
```

---

## Success Criteria

When the operator wakes up and runs `./test.sh fast`, all tiers pass. When they open `http://localhost:8000` and press B:

1. Units patrol along real streets on satellite imagery
2. Hostiles approach via roads, then cut through yards
3. Turrets engage with visible projectile trails and explosions
4. Kill feed, wave banners, and score all work
5. Synthetic camera PIP shows a convincing CCTV feed
6. Amy announces battle start, wave clears, and victory/defeat
7. The test report at `tests/.test-results/reports/` has timestamped screenshots proving every stage

---

## Files Created/Modified

**New files**:
- `src/engine/tactical/street_graph.py` — OSM street graph extraction
- `src/engine/tactical/obstacles.py` — Building footprint obstacles
- `src/engine/simulation/pathfinding.py` — A* on street graph
- `frontend/js/command/unit-icons.js` — Procedural unit icon drawing
- `tests/amy/simulation/test_pathfinding.py` — Pathfinding tests
- `tests/amy/simulation/test_street_graph.py` — Street graph tests
- `tests/amy/simulation/test_scale.py` — Scale verification tests
- `tests/visual/test_battle_proof.py` — Full battle proof test
- `docs/overnight-status/*.md` — Agent status files

**Modified files**:
- `src/engine/simulation/engine.py` — Use pathfinder for unit movement
- `src/engine/simulation/behaviors.py` — Road-aware hostile approach
- `src/engine/simulation/target.py` — Smooth heading interpolation
- `scenarios/neighborhood_default.json` — Road-aligned positions
- `frontend/js/command/map.js` — Unit icon rendering, fog of war
- `test.sh` — Add tier 12
