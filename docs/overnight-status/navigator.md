# Navigator Agent — Overnight Build Status

## Mission: Street-aware navigation for simulation units

## Completed Tasks

### Task 1: Street Graph Extraction (14 tests)
- **File**: `src/engine/tactical/street_graph.py`
- **Tests**: `tests/amy/simulation/test_street_graph.py`
- `StreetGraph` class loads road segments from OSM Overpass API
- Builds NetworkX graph: intersections as nodes, roads as weighted edges (meters)
- Shared lat/lng points between roads create connected intersection nodes
- `nearest_node(x, y)` → (node_id, distance) for snap-to-road
- `shortest_path(start, end)` → A* path as list of (x, y) waypoints
- 24-hour cache with pickle serialization, expiry-based refresh
- Graceful offline fallback: graph stays None, callers use direct waypoints

### Task 2: Building Obstacles (13 tests)
- **File**: `src/engine/tactical/obstacles.py`
- **Tests**: `tests/amy/simulation/test_obstacles.py`
- `BuildingObstacles` class loads building footprints from Overpass API
- Ray-casting point-in-polygon (no Shapely dependency)
- Line segment intersection for `path_crosses_building()`
- JSON cache for building polygon data
- Offline fallback: empty polygon list

### Task 3: A* Pathfinder (12 tests)
- **File**: `src/engine/simulation/pathfinding.py`
- **Tests**: `tests/amy/simulation/test_pathfinding.py`
- `plan_path(start, end, unit_type, street_graph, obstacles)` → waypoints
- Routing rules by unit type:
  - **Rover/Tank/APC**: snap to road → A* on street graph → road waypoints
  - **Drone/Scout drone**: straight line (ignores roads and buildings)
  - **Hostile person**: road approach, then direct for last 30m
  - **Turret**: no path (stationary)
  - **Unknown**: direct fallback
- Falls back to direct waypoints when no street graph available

### Task 4: SimulationEngine Wiring (8 integration tests)
- **Modified**: `src/engine/simulation/engine.py`
- **Tests**: `tests/amy/simulation/test_pathfinding_integration.py`
- `engine.set_street_graph(sg)` and `engine.set_obstacles(obs)`
- `engine.dispatch_unit(target_id, destination)` — routes via pathfinder
- `engine.spawn_hostile()` — uses road-following approach when graph available
- Legacy waypoint fallback preserved when no street graph
- All 3172 existing unit tests pass with 0 regressions

## Test Results
- **Street graph**: 14/14 pass
- **Obstacles**: 13/13 pass
- **Pathfinding**: 12/12 pass
- **Integration**: 8/8 pass
- **All simulation tests**: 429 passed, 2 skipped
- **All unit tests**: 3172 passed, 2 skipped, 0 regressions

## Commits
1. `7afe52b` — Add street graph extraction from OSM Overpass API with 14 unit tests
2. `7511928` — Add building obstacle detection from OSM Overpass with 13 unit tests
3. `709c1c4` — Add A* pathfinder with unit-type routing and 12 unit tests
4. `a7e03f2` — Wire A* pathfinding into SimulationEngine with dispatch_unit() and 8 integration tests

## Architecture Notes
- No new dependencies (networkx was already available)
- Street graph uses same Overpass API pattern as `src/app/routers/geo.py`
- Coordinate system: +X=East, +Y=North, 1 unit=1 meter (same as geo.py)
- All three modules (street_graph, obstacles, pathfinding) have clean offline fallbacks
- Engine changes are backward-compatible: no street graph = same behavior as before
