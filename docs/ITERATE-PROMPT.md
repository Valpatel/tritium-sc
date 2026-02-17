# RTS Battlespace Iteration Prompt

Copy everything below the line and paste it as your prompt to Claude Code.
Each run audits the current state, identifies the highest-impact gaps, and
fixes them.  Run it repeatedly until all phases are solid.

---

## The prompt

Audit and iterate on the TRITIUM-SC RTS battlespace simulation system.
This is a neighborhood-scale Nerf war management platform with AI Commander
Amy, real sensors (BCC950 PTZ, NVR cameras), and a simulation engine that
populates virtual targets (rovers, drones, turrets, hostile intruders)
alongside real detections on the same tactical map.

The system has a games-common level editor (symlinked at frontend/common/)
that provides a full 3D scene editor with 30 asset types defined in
frontend/js/editor/TritiumAssets.js and a pluggable serialization format in
frontend/js/editor/TritiumLevelFormat.js.  The editor plugin is in
frontend/js/editor/TritiumEditorPlugin.js.

### What exists (read before changing)

Backend simulation:
- amy/simulation/target.py — SimulationTarget dataclass with tick(), waypoints, battery
- amy/simulation/engine.py — 10Hz tick loop, hostile spawner, EventBus telemetry
- amy/simulation/loader.py — reads TritiumLevelFormat JSON into simulation targets
- amy/target_tracker.py — unified TargetTracker merging sim + YOLO detections
- amy/commander.py — _sim_bridge_loop feeds EventBus events into TargetTracker
- amy/thinking.py — battlespace context in thinking prompt, dispatch/alert/patrol actions
- amy/lua_motor.py — dispatch(), alert(), patrol() Lua actions
- amy/sensorium.py — battlespace summary in rich_narrative()
- amy/router.py — /api/amy/simulation/* endpoints (list, spawn, remove)
- app/routers/targets_unified.py — /api/targets endpoint
- app/main.py — creates SimulationEngine at startup, wires to Amy EventBus

Frontend:
- frontend/js/assets.js — tactical map canvas rendering sim targets
- frontend/js/app.js — WebSocket handlers for amy_sim_telemetry events
- frontend/js/amy.js — BATTLESPACE panel in Amy dashboard
- frontend/js/editor/TritiumAssets.js — 30 asset type definitions (cameras, robots, drones, zones, sensors, paths)
- frontend/js/editor/TritiumLevelFormat.js — JSON serialization format with structures, environment, amy config, objects
- frontend/js/editor/TritiumEditorPlugin.js — wires editor to tritium app, playtest button

Level editor (games-common at frontend/common/):
- EditorCore.js — generic 3D editor framework
- AssetRegistry.js — pluggable asset types
- LevelSerializer.js — pluggable format system
- TransformGizmo.js, SceneHierarchy.js, RegionTools.js, TerrainSystem.js, etc.

Tests:
- tests/amy/test_simulation_target.py, test_simulation_engine.py, test_simulation_loader.py
- tests/amy/test_target_tracker.py, test_dispatch_actions.py

### Iteration checklist — work through IN ORDER, fix what's broken

1. AUDIT: Run `python3 -m pytest tests/amy/ -m unit -v` and fix any failures first.

2. EDITOR → SIMULATION BRIDGE: The level editor saves layouts to localStorage.
   The simulation loader reads JSON files.  Audit and fix the bridge:
   - Is there an API to save/load layouts to the server?  (There should be)
   - Does the loader properly map ALL 30 TritiumAssets types to SimulationTarget?
   - Do patrol_rover, interceptor_rover, sentry_turret, recon_drone, heavy_drone,
     scout_drone all create correct SimulationTargets with right speeds/types?
   - Do waypoint and observation_point assets become patrol waypoints on nearby units?
   - Does the Amy config section (responseProtocol, escalationDelay, etc.) wire
     into Commander behavior?

3. SIMULATION FIDELITY: Audit the simulation engine for correctness:
   - Does tick() handle edge cases (zero speed, empty waypoints, negative battery)?
   - Does the hostile spawner create interesting behavior (not just random walk)?
   - Do hostiles navigate toward objectives (the property center, high-value areas)?
   - Is target removal clean (removed from engine, tracker, and frontend)?
   - Do battery-dead units get cleaned up or sit as debris?

4. TARGET TRACKER ACCURACY: Audit the tracker:
   - Does update_from_detection() properly match existing detections (not create dupes)?
   - Is the proximity threshold (0.04) reasonable for YOLO bbox centers?
   - Does the stale timeout (30s) make sense for real-world detection gaps?
   - Are simulation targets properly attributed (source="simulation")?
   - Does the summary() output make sense for Amy's thinking context?

5. AMY DISPATCH INTEGRATION: Audit Amy's ability to command units:
   - Does dispatch() actually change target waypoints in the simulation engine?
   - Does patrol() parse the JSON waypoints correctly?
   - Does Amy's thinking prompt give her enough context to make tactical decisions?
   - Are there situations where Amy should auto-dispatch (hostile near a friendly)?
   - Does the thinking prompt include friendly unit capabilities (speed, battery)?

6. FRONTEND TACTICAL MAP: Audit the assets.js tactical map:
   - Do simulation targets actually render on the canvas?
   - Is the coordinate mapping correct (-30 to 30 sim → canvas pixels)?
   - Does smooth interpolation work (or do targets teleport)?
   - Do dispatch arrows render and fade correctly?
   - Does the map update at a reasonable framerate?
   - Is the BATTLESPACE panel in amy.js functional (spawn, remove, list)?

7. EDITOR ↔ TACTICAL MAP: Audit the connection between the 3D editor and 2D tactical map:
   - Can you place assets in the editor and see them appear as simulation targets?
   - Does the playtest button start a simulation with the editor's layout?
   - Do 3D editor positions map correctly to 2D tactical map coordinates?
   - Can you edit a running simulation's targets from the editor?

8. WEBSOCKET FLOW: Audit the full event pipeline:
   - SimulationEngine → EventBus → WebSocket bridge → Frontend
   - Does sim_telemetry flow at 10Hz without overwhelming the WebSocket?
   - Are dispatch/alert events properly forwarded?
   - Does the frontend handle disconnection and reconnection?

9. TESTS: After every change, add or update unit tests.  Target:
   - Every public method on SimulationTarget, SimulationEngine, TargetTracker
   - Every new Lua action (dispatch, alert, patrol)
   - Layout loading with all asset types
   - Edge cases: empty layouts, missing fields, corrupt data

10. WRITE what you changed and what still needs work.

### Rules

- Read existing code before modifying — understand the patterns first
- Run the full test suite after changes: `.venv/bin/python3 -m pytest tests/amy/ -m unit -v`
- Don't break existing functionality (572+ tests must pass)
- Follow existing conventions: type hints, no emojis, async/await, CYBERCORE CSS
- The app name is TRITIUM-SC (Tritium-Security Central)
- Real sensor tracking (people, cars) coexists with virtual targets
- The games-common editor is a SHARED library — never modify files under frontend/common/
- Only modify tritium-sc plugin files: TritiumAssets.js, TritiumLevelFormat.js, TritiumEditorPlugin.js
