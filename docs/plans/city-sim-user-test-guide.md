# City Simulation — User Test Guide

How to verify every feature works. Open http://localhost:8000/ in Chrome.

## Quick Start (2 minutes)

1. Press `J` → City sim starts. You should see colored dots appear on roads.
2. Look at z16-z17 zoom: cyan dots = vehicles, green = pedestrians, orange = heading lines
3. Press `\` → Protest starts. 50 NPCs turn orange/red and start moving toward city center.
4. Press `[` to speed up time. Each press: 1x → 10x → 60x → 300x → 1800x → PAUSE
5. Open City Simulation panel from sidebar → see stats, protest timeline

## Feature Verification Checklist

### Vehicles on Roads (VISUALLY-VERIFIED)
- At z17 top-down: cyan dots with heading lines visible on roads
- At z19-z20: 3D box shapes visible on road surface
- Zoom to a road — vehicles should follow road curves, not cut through buildings

### Vehicle Purpose (NEEDS VERIFICATION)
- Console (F12): "Purposes: commute:96, delivery:19, taxi:14, patrol:2"
- Yellow dots = taxis, blue dots = patrol vehicles
- At 8am: commute vehicles unpark and drive
- At night: mostly taxis and patrol vehicles

### Named NPCs (BROWSER-TESTED)
- Console: "Sample: Donna Gutierrez (student) home=Bldg#169036984"
- Hover over a green pedestrian dot → tooltip shows name, role, mood

### Daily Routines (NEEDS VERIFICATION)
- At 6-7am: joggers (bright green dots) should appear in park areas
- At 8-9am: commute traffic increases, NPCs enter commercial buildings
- At 12pm: some NPCs at lunch spots
- At 5-6pm: reverse commute, NPCs heading home
- Use `[` to speed time and watch the cycle

### Protest (8 Phases)
1. Press `\` to start protest
2. 50 NPCs should turn orange and start walking toward (0,0) — city center
3. Console logs phase transitions: CALL_TO_ACTION → MARCHING → ASSEMBLED → ...
4. City Sim panel shows PROTEST section with phase timeline
5. The full lifecycle takes ~155 sim-seconds to complete
6. At 300x time scale, it completes in ~0.5 seconds real time
7. At 60x (default), it takes ~2.5 real minutes

### Police Response (NEEDS VERIFICATION)
- During protest, when active count > 5: police dispatched
- Blue dots should appear and move toward protest area
- Console: "[ProtestManager] Police dispatched: N officers"

### Crowd Heatmap (NEEDS VERIFICATION)
- At z16-z17, look for colored glow around the protest area
- Green = low density, yellow = medium, red = high
- Most visible when 20+ NPCs are clustered at the plaza

### Collisions (VISUALLY-VERIFIED)
- Watch dense traffic — vehicles sometimes collide
- Console: "bump/collision/CRASH" with mass and speed info
- Crashed vehicles flash red/yellow
- Serious crashes auto-dispatch emergency vehicles (magenta)

### Time Scale
- Press `[` repeatedly to cycle: 1x → 10x → 60x → 300x → 1800x → PAUSE
- Console logs current speed
- At 1800x: a full day passes in ~48 seconds

### Dramatic Day Scenario
- In City Simulation panel, select "Dramatic Day" from scenario dropdown
- Schedules: 8:30am accident, 10am medical, 2pm protest, 5:30pm accident
- Use `[` to speed to 300x and watch events trigger

### Taxi System (NEEDS VERIFICATION)
- ~14 taxi vehicles (yellow dots) cruise around
- NPCs with rideshare preference should flag for pickup
- Taxi turns orange when heading to pick up, green when carrying passenger

## Known Issues

- **Playwright can't drive the sim fast enough** — automated tests only verify initial state, not time-dependent features. This guide is for human verification.
- **Protest convergence at z16 may be subtle** — zoom to z17-z18 for clearer view of NPC clustering
- **Time display may lag** — the TIME row in the panel updates every 500ms

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| J | Toggle city sim on/off |
| \ | Start protest at city center |
| [ | Cycle time scale (1x → 10x → 60x → 300x → 1800x → pause) |
| ] | Spawn emergency vehicle |
