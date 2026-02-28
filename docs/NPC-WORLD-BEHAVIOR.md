# NPC World Behavior Architecture

## Overview

NPCs in TRITIUM-SC are not background decorations — they are inhabitants of a
real neighborhood with 227 buildings, 770 road network nodes, 444 footway
segments, and a 400m x 400m operational area centered on Amy's property.

This document specifies the architecture for realistic NPC behavior: pedestrians
who walk on sidewalks, cross at crosswalks, enter and exit buildings on daily
routines; vehicles that follow traffic rules; animals that roam yards; and all
of them reacting intelligently to combat, danger, and social pressure.

**Coordinate system**: +X = East, +Y = North, origin = Amy's house (37.7069N,
121.9387W). 1 unit = 1 meter.

## Current State (What Exists)

| System | File | What It Does | Gap |
|--------|------|-------------|-----|
| BuildingObstacles | `tactical/obstacles.py` | 227 building polygons, point-in-building, path-crosses-building | No doors, no building types, no interior |
| StreetGraph | `tactical/street_graph.py` | 770-node road network, A* pathfinding, `footway`/`residential`/`service` road classes | No crosswalks, no traffic rules, no sidewalk-vs-road distinction in routing |
| Pathfinder | `simulation/pathfinding.py` | Routes by unit type (road, flying, hostile) | No neutral pedestrian routing, no building avoidance for neutrals |
| NPCManager | `simulation/npc.py` | Spawns vehicles (roads) and pedestrians (sidewalk offset), missions, bind_to_track | Edge-to-edge only, no building interaction, no intelligence plugin integration |
| AmbientSpawner | `simulation/ambient.py` | 8 simple background entities | Minimal, no FSM, no awareness |
| NPC Intelligence | `simulation/npc_intelligence/` | FSMs (7/5/5 states), personality, memory, LLM think, event reactions, crowd dynamics | Zero spatial awareness, disconnected from NPCManager |
| TerrainMap | `simulation/terrain.py` | 5m grid, movement costs, Bresenham LOS | No sidewalk/crosswalk data |

**Critical problem**: NPCManager and NPC Intelligence Plugin are completely
separate systems. NPCManager creates targets with waypoints. NPC Intelligence
creates brains with FSMs. They don't know about each other.

## Architecture

```
                           ┌─────────────────────────┐
                           │   SimulationEngine       │
                           │   (10Hz tick loop)       │
                           └──────────┬──────────────┘
                                      │
                    ┌─────────────────┼──────────────────┐
                    │                 │                   │
            ┌───────▼────────┐ ┌─────▼───────┐ ┌────────▼──────────┐
            │  NPCManager    │ │ EventBus    │ │ NPC Intelligence  │
            │  (spawn/despawn│ │ (pub/sub)   │ │ Plugin            │
            │   waypoints)   │ │             │ │ (brains/FSMs)     │
            └───────┬────────┘ └─────┬───────┘ └────────┬──────────┘
                    │                │                   │
                    └────────┬───────┘                   │
                             │                           │
                    ┌────────▼───────────────────────────▼──┐
                    │         NPCWorldBridge                │
                    │  (connects NPCManager ↔ Intelligence) │
                    │  - Attaches brains when NPCs spawn    │
                    │  - Routes FSM decisions to waypoints  │
                    │  - Spatial context for LLM prompts    │
                    └────────┬──────────────────────────────┘
                             │
              ┌──────────────┼──────────────────┐
              │              │                  │
     ┌────────▼───────┐ ┌───▼──────────┐ ┌─────▼─────────────┐
     │ WorldModel      │ │ NPCRouter    │ │ RoutineScheduler  │
     │ (spatial data)  │ │ (pathfinding │ │ (daily schedules)  │
     │ - buildings     │ │  for NPCs)   │ │ - home/work/shop   │
     │ - doors         │ │ - pedestrian │ │ - building enter/  │
     │ - crosswalks    │ │   routing    │ │   exit timing      │
     │ - road types    │ │ - vehicle    │ │ - personality-     │
     │ - POIs          │ │   routing    │ │   driven choices   │
     └────────────────┘ │ - flee paths │ └────────────────────┘
                        └──────────────┘
```

## Component Specifications

### 1. WorldModel (`npc_intelligence/world_model.py`)

Aggregates all spatial data into a single queryable model that NPC brains
can use for decision-making.

```python
class WorldModel:
    """Unified spatial model for NPC decision-making."""

    def __init__(
        self,
        buildings: BuildingObstacles,
        street_graph: StreetGraph,
    ) -> None: ...

    # -- Building queries --
    def nearest_building(self, x: float, y: float) -> BuildingInfo | None
    def nearest_door(self, x: float, y: float) -> DoorPoint | None
    def buildings_in_radius(self, x: float, y: float, r: float) -> list[BuildingInfo]
    def is_inside_building(self, x: float, y: float) -> bool

    # -- Road queries --
    def road_type_at(self, x: float, y: float) -> str | None
    def nearest_crosswalk(self, x: float, y: float) -> CrosswalkPoint | None
    def nearest_sidewalk_node(self, x: float, y: float) -> tuple[float, float] | None
    def is_on_road(self, x: float, y: float) -> bool
    def is_on_sidewalk(self, x: float, y: float) -> bool

    # -- Points of interest --
    def nearest_poi(self, x: float, y: float, poi_type: str | None = None) -> POI | None
    def pois_in_radius(self, x: float, y: float, r: float) -> list[POI]

    # -- Safety queries (for flee routing) --
    def nearest_cover(self, x: float, y: float, threat_pos: tuple[float, float]) -> tuple[float, float] | None
    def safe_direction(self, x: float, y: float, threat_pos: tuple[float, float]) -> tuple[float, float]
```

**Data structures**:

```python
@dataclass
class BuildingInfo:
    polygon: list[tuple[float, float]]
    center: tuple[float, float]
    building_type: str          # residential, commercial, school, church, etc.
    doors: list[DoorPoint]
    area_m2: float

@dataclass
class DoorPoint:
    position: tuple[float, float]
    facing: float              # heading the door faces (degrees)
    building_idx: int          # which building this door belongs to
    accessible: bool = True    # can NPCs enter here?

@dataclass
class CrosswalkPoint:
    position: tuple[float, float]
    road_node_a: int           # street graph node on one side
    road_node_b: int           # street graph node on other side
    width: float = 3.0

@dataclass
class POI:
    position: tuple[float, float]
    poi_type: str              # home, work, shop, park, school, church
    name: str
    building_idx: int | None   # associated building, if any
    capacity: int = 10         # max NPCs inside at once
```

**Door generation**: Since OSM building data doesn't include doors, we
generate them procedurally:
1. For each building polygon, find the edge closest to a road/footway
2. Place a door at the midpoint of that edge
3. For large buildings (>200m²), place doors on multiple edges
4. Door faces outward (perpendicular to building edge, toward road)

**Crosswalk generation**: Since OSM doesn't provide crosswalk data:
1. Find all intersections in the street graph (nodes with degree >= 3)
2. For each intersection, identify road-type edges vs footway edges
3. Place crosswalk points where footways connect to road intersections
4. If no explicit footway, place crosswalks at T-intersections and
   4-way intersections on residential streets

**POI classification**: Buildings are classified by size and proximity:
- Small (<100m²) near residential roads → `home`
- Large (>300m²) near secondary/tertiary roads → `commercial`
- Medium near schools (if OSM tags available) → `school`
- Others → `home` (residential neighborhood default)

### 2. NPCRouter (`npc_intelligence/npc_router.py`)

Replaces direct pathfinding with NPC-type-aware routing that respects
spatial rules.

```python
class NPCRouter:
    """NPC-aware pathfinding that respects spatial rules."""

    def __init__(self, world: WorldModel, street_graph: StreetGraph) -> None: ...

    def route_pedestrian(
        self, start: tuple[float, float], end: tuple[float, float],
        urgent: bool = False,
    ) -> list[tuple[float, float]]:
        """Route a pedestrian using sidewalks and crosswalks.

        Normal mode:
        - Walk on footway/pedestrian paths
        - Cross roads at crosswalk points
        - Avoid walking through buildings

        Urgent mode (fleeing):
        - Can cross roads anywhere
        - Can cut through yards (but still not through buildings)
        - Shortest path to safety
        """

    def route_vehicle(
        self, start: tuple[float, float], end: tuple[float, float],
        vehicle_type: str = "sedan",
    ) -> list[tuple[float, float]]:
        """Route a vehicle on roads only.

        - Uses only road-class edges (residential, secondary, service)
        - Never uses footway/pedestrian/cycleway
        - Respects one-way (if data available)
        """

    def route_to_building(
        self, start: tuple[float, float], building: BuildingInfo,
    ) -> list[tuple[float, float]]:
        """Route to the nearest door of a building."""

    def route_flee(
        self, position: tuple[float, float],
        threat_position: tuple[float, float],
        npc_type: str,
    ) -> list[tuple[float, float]]:
        """Emergency flee route away from threat.

        Pedestrians: run to nearest building door, or away on sidewalks
        Vehicles: speed away on roads (opposite direction from threat)
        Animals: bolt in a random safe direction (not through buildings)
        """
```

**Pedestrian routing algorithm**:
1. Snap start/end to nearest footway node
2. A* on subgraph of footway + pedestrian + path edges only
3. Where path crosses a road-class edge, insert crosswalk waypoint:
   a. Find nearest crosswalk point
   b. Route: ... → crosswalk approach → wait point → crosswalk exit → ...
4. Validate result with `path_crosses_building()` — if it does, reroute
5. Fallback: if no footway path exists, use road path with 2m offset

**Vehicle routing algorithm**:
1. Snap start/end to nearest road node (exclude footway/pedestrian/cycleway)
2. A* on subgraph of road-class edges only
3. Apply speed limits based on road class:
   - residential: 25 mph (11 m/s)
   - service: 15 mph (7 m/s)
   - secondary/tertiary: 35 mph (16 m/s)

### 3. RoutineScheduler (`npc_intelligence/routine.py`)

Gives NPCs daily schedules so they have purposes and destinations.

```python
class NPCRoutine:
    """A daily schedule for an NPC."""

    def __init__(self, npc_id: str, home: POI, personality: NPCPersonality) -> None: ...

    def current_activity(self, sim_time: float) -> RoutineActivity
    def next_activity(self, sim_time: float) -> RoutineActivity
    def time_until_next(self, sim_time: float) -> float

@dataclass
class RoutineActivity:
    activity_type: str         # home, commute, work, shop, walk, park, idle
    location: POI | None       # destination POI
    start_time: float          # sim time when this activity starts
    duration: float            # expected duration in seconds
    priority: int = 0          # higher = harder to interrupt
```

**Daily routine template for pedestrians**:
```
06:00-07:00  home (wake up, prepare)
07:00-07:30  commute → work
07:30-12:00  work (inside building)
12:00-12:30  walk → lunch spot
12:30-13:00  shop/eat (inside building)
13:00-17:00  work (inside building)
17:00-17:30  commute → home
17:30-19:00  home (dinner)
19:00-20:00  walk (evening stroll) or park
20:00-06:00  home (sleep)
```

Personality influences schedule:
- High sociability → more walking, park visits, longer lunch
- High curiosity → more exploring, varied routes
- High caution → stays home more, shorter walks
- High aggression → stays out later, visits more locations

**Vehicle routines**:
- Commuters: home → work → home (twice daily)
- Delivery vans: hub → stop → stop → hub (continuous)
- Police: patrol loops (continuous)
- School buses: morning/afternoon runs (time-based)

### 4. NPCWorldBridge (`npc_intelligence/world_bridge.py`)

The critical integration point connecting NPCManager and the Intelligence Plugin.

```python
class NPCWorldBridge:
    """Bridges NPCManager (spawn/movement) with NPC Intelligence (brains/FSMs).

    When NPCManager spawns an NPC, this bridge:
    1. Attaches a brain via the Intelligence Plugin
    2. Assigns a daily routine
    3. Routes the NPC to its first destination
    4. Listens for FSM state changes and translates them to movement commands

    When the Intelligence Plugin decides an NPC should change behavior:
    1. Bridge translates the FSM state to a routing request
    2. NPCRouter generates appropriate waypoints
    3. Bridge updates the target's waypoints in the engine
    """

    def __init__(
        self,
        npc_manager: NPCManager,
        intelligence: NPCIntelligencePlugin,
        world: WorldModel,
        router: NPCRouter,
        scheduler: RoutineScheduler,
    ) -> None: ...

    def on_npc_spawned(self, target: SimulationTarget) -> None:
        """Called when NPCManager creates a new NPC."""

    def on_fsm_state_changed(self, target_id: str, old_state: str, new_state: str) -> None:
        """Called when an NPC's FSM transitions."""

    def tick(self, dt: float) -> None:
        """Per-tick update: check routines, update paths, sync state."""
```

**FSM State → Movement mapping**:

| FSM State | Movement Behavior |
|-----------|------------------|
| `walking` | Follow routine route on sidewalks |
| `pausing` | Stop in place for 3-15s |
| `observing` | Stop, face direction of interest |
| `fleeing` | Urgent route away from danger |
| `hiding` | Route to nearest building door, enter building |
| `curious` | Route toward point of interest |
| `panicking` | Run erratically (random direction changes, avoid buildings) |
| `driving` | Follow road route at speed limit |
| `stopped` | Vehicle stopped (traffic, obstacle) |
| `yielding` | Vehicle slowing/stopping for emergency |
| `evading` | Vehicle speeds away on roads |
| `parked` | Vehicle stopped at destination |
| `wandering` | Animal follows random yard waypoints |
| `resting` | Animal stopped |
| `startled` | Animal runs short distance |
| `following` | Animal follows nearest person |

### 5. Pedestrian Sub-States

The existing 7-state pedestrian FSM is the "behavior" layer. Below it,
we add a "movement" sub-state machine for spatial awareness:

```
BEHAVIOR FSM (existing):
  walking → pausing → observing → fleeing → hiding → curious → panicking

MOVEMENT SUB-FSM (new):
  walking_on_sidewalk
  approaching_crosswalk
  waiting_at_crosswalk
  crossing_road
  approaching_building
  entering_building
  inside_building
  exiting_building
  running_on_sidewalk     (urgent)
  running_off_road        (urgent/flee)
  taking_cover            (urgent/hide)
```

The behavior FSM sets the intent. The movement sub-FSM handles the spatial
execution. For example:
- `behavior=walking` + `movement=walking_on_sidewalk` → normal walk
- `behavior=walking` + `movement=approaching_crosswalk` → slow down at crosswalk
- `behavior=fleeing` + `movement=running_off_road` → run through yards
- `behavior=hiding` + `movement=entering_building` → rush into building
- `behavior=walking` + `movement=inside_building` → at destination

### 6. Vehicle Sub-States

```
BEHAVIOR FSM (existing):
  driving → stopped → yielding → evading → parked

MOVEMENT SUB-FSM (new):
  cruising              (normal speed on road)
  approaching_stop      (decelerating for stop sign/intersection)
  stopped_at_sign       (waiting at intersection)
  turning               (executing turn at intersection)
  yielding_to_pedestrian (stopping for crosswalk)
  pulling_over          (moving to road edge)
  accelerating          (leaving stop, speeding up)
  parking               (executing parking maneuver at destination)
  speeding_away         (urgent/evade, high speed)
```

### 7. Riot/Mob Behavior

When NPC radicalization occurs, nearby NPCs can be recruited into a mob:

```python
class MobFormation:
    """Tracks a group of radicalized NPCs acting together."""

    leader_id: str
    member_ids: set[str]
    rally_point: tuple[float, float]
    target_point: tuple[float, float] | None
    formation_time: float
    aggression_level: float    # 0-1, affects behavior intensity
```

**Mob formation flow**:
1. NPC radicalizes (existing alliance manager)
2. Radicalized NPC emits `rally` signal via crowd dynamics
3. Nearby NPCs with aggression > 0.5 and in `observing`/`curious` state
   may join (probability based on aggression, sociability, crowd_size)
4. Mob forms around rally point
5. Mob advances toward target (property, turret, etc.) in loose formation
6. Individual members use combat FSM (from `create_hostile_fsm()`)
7. If mob drops below 3 members, remaining scatter

**Riot escalation levels**:
- Level 1 (3-5): Shouting, throwing objects, advance slowly
- Level 2 (6-10): Aggressive advance, attempt to overwhelm defenses
- Level 3 (10+): Full assault, coordinate flanking

## LLM Prompt Design (with World Awareness)

The NPC's LLM prompt now includes spatial context:

```
You are {name}, a {asset_type} in a residential neighborhood.
You are a {alliance} civilian.

PERSONALITY:
  curiosity: {curiosity}  caution: {caution}
  sociability: {sociability}  aggression: {aggression}

CURRENT STATE: {fsm_state}
LOCATION: On {location_description}
DESTINATION: {routine_destination} ({distance}m away)

WHAT YOU SEE:
{visible_entities}

WHAT YOU HEARD RECENTLY:
{recent_events}

NEARBY BUILDINGS:
{nearby_buildings}

CURRENT SITUATION:
{situation_summary}

What do you do? Choose ONE action:
  WALK - continue to your destination
  PAUSE - stop and wait
  OBSERVE - watch something interesting
  FLEE - run away from danger
  HIDE - go inside the nearest building
  APPROACH - move toward something interesting
  IGNORE - keep doing what you're doing
  ENTER - go into a building
  CROSS - cross the street at the crosswalk

Respond with ONE word:
```

Key additions vs. current prompt:
- **Location description**: "sidewalk on Oak Street", "inside Safeway", "crossing Main & Elm"
- **Destination awareness**: NPC knows where it's going
- **Building awareness**: Lists nearest 3 buildings with types
- **Situation summary**: Combines danger level, interest, and routine status

## Performance Budget

| Component | Budget | Expected |
|-----------|--------|----------|
| WorldModel queries (per NPC) | 0.02ms | Cached lookups |
| NPCRouter (per route) | 0.5ms | A* on subgraph |
| RoutineScheduler (per tick) | 0.01ms | Time comparison |
| NPCWorldBridge (per tick) | 0.05ms | State sync |
| Total per NPC per tick | 0.1ms | Well within 5ms for 70 NPCs |

Path routing is amortized — NPCs only reroute when:
- Reaching destination (routine change)
- FSM state change (e.g., walking → fleeing)
- Path becomes invalid (building entered, road blocked)

## New Files

| File | Lines | Purpose |
|------|-------|---------|
| `npc_intelligence/world_model.py` | ~300 | Unified spatial queries |
| `npc_intelligence/npc_router.py` | ~250 | NPC-type-aware pathfinding |
| `npc_intelligence/routine.py` | ~200 | Daily schedule system |
| `npc_intelligence/world_bridge.py` | ~250 | NPCManager ↔ Intelligence connector |
| `npc_intelligence/movement_fsm.py` | ~200 | Movement sub-state machines |
| `npc_intelligence/mob.py` | ~150 | Riot/mob formation |

## Implementation Order

1. **WorldModel** — spatial queries, door/crosswalk generation (TDD)
2. **NPCRouter** — pedestrian/vehicle routing with spatial rules (TDD)
3. **Movement sub-FSMs** — spatial execution layer (TDD)
4. **RoutineScheduler** — daily schedules (TDD)
5. **NPCWorldBridge** — connect everything (TDD)
6. **Mob formation** — riot behavior (TDD)
7. **LLM prompts** — upgrade with world awareness (TDD)
8. **Integration test** — full stack validation

## Test Strategy

Each component gets its own test file following TDD:
- Write tests first → watch fail → implement → watch pass
- Performance tests for 70 NPCs within budget
- Integration tests for complete flows:
  - Pedestrian walks on sidewalk, crosses at crosswalk, enters building
  - Vehicle follows road, stops at intersection, parks at destination
  - NPC flees to nearest building when combat starts
  - Mob forms from radicalized NPCs, advances, scatters when defeated
