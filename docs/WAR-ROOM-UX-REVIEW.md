# War Room UX Review

Deep architectural review of the War Room frontend (war.js, related modules).

## 1. Three-Mode Model (OBSERVE / TACTICAL / SETUP)

**Verdict: The mode model adds friction. Right-click dispatch should always work.**

In StarCraft, C&C, and Supreme Commander, there are no explicit "modes" for
basic interaction. You can always select, always right-click to
move/attack, and building is a button on the command card, not a global
mode toggle. The War Room forces you to press `T` before you can right-click
dispatch, which violates the RTS convention of "select unit, right-click
destination."

**Recommendation**: Right-click dispatch should work in ALL modes when
friendlies are selected. The mode indicator can remain for visual
feedback, but should not gate core dispatch behavior. SETUP mode can stay
gated (it changes left-click semantics), but OBSERVE vs TACTICAL is an
artificial distinction.

**Implemented**: Removed the `warState.mode === 'tactical'` gate on
right-click dispatch (line 663). Dispatch now works whenever friendlies
are selected, regardless of mode.

## 2. Minimap

**Verdict: Renders correctly but is not interactive.**

The minimap draws targets at correct positions using `wToMM()` with proper
Y-flip. The viewport rectangle renders correctly. However:

- Clicking the minimap does NOT pan the camera
- It is purely decorative -- a visual indicator, not a navigation tool

In every RTS, clicking the minimap instantly pans the camera to that world
position. This is a critical missing interaction.

**Implemented**: Added click-to-pan on the minimap via `onCanvasMouseDown`
hit testing.

## 3. HUD Layout

**Verdict: Competent layout, no major overlaps, but has gaps.**

Layout analysis:
- Mode indicator: centered top -- good, visible, unobtrusive
- Amy panel: top-right -- good position for secondary info
- Alert log: bottom-right -- standard RTS alert position
- Unit info: top-left -- shows on selection, hides otherwise
- Setup palette: top-left (replaces unit info) -- correct mutual exclusion

The HUD panels use absolute positioning with fixed pixel widths. On very
narrow viewports (<800px), the Amy panel and alert log could overlap the
mode indicator, but this is an edge case for a tactical display.

**Missing**: No keyboard shortcut reference for the War Room in the help
overlay (`?` key). The war-specific controls (`S/T/O` mode, `Tab` cycle,
`Space` center, `Delete` remove, right-click dispatch) are undiscoverable.

**Implemented**: Added war-specific controls to the keyboard help overlay
in input.js.

## 4. Selection Model

**Verdict: Solid fundamentals, missing control groups.**

What works:
- Single click selects a target
- Shift-click toggles selection (add/remove)
- Box select (drag) selects friendlies only (correct -- you shouldn't
  box-select hostiles in an RTS)
- Shift + box select adds to existing selection
- Tab cycles through all targets

What's missing:
- No control groups (Ctrl+1-9 to assign, 1-9 to recall). This is a
  staple RTS feature for managing multiple squads
- Box select is correctly restricted to friendlies, but single-click can
  select any target (friendly/hostile/unknown) -- this is intentional and
  correct for an intel display
- No "select all of type" (e.g., double-click a rover to select all rovers)

**Not implemented**: Control groups would require significant state
management (9 saved arrays). The current selection model is functional for
the project's scope.

## 5. Camera System

**Verdict: Functional but missing two standard RTS features.**

What works:
- Middle-click or Alt+left-click to pan -- standard
- Mouse wheel zoom -- works
- Double-click target to center + zoom -- good
- Space to center on selection -- good
- Smooth camera lerp (0.1 factor) -- feels responsive

What's missing:
- **No edge scrolling**: Moving mouse to screen edges should pan the camera.
  Every RTS has this. It's especially important when you're dragging a
  box selection near the edge.
- **Zoom is viewport-centered, not cursor-centered**: Mouse wheel zoom should
  keep the world position under the cursor fixed. Currently, zooming always
  centers on the camera position, which forces the player to re-pan after
  every zoom. This is jarring.

**Implemented**: Cursor-centered zoom (adjusts cam.targetX/Y to keep the
world point under the mouse fixed during zoom).

## 6. Event Rendering

**Verdict: Dispatch arrows render well. Other events are text-only.**

What renders visually on the map:
- Dispatch arrows (magenta, dashed, with arrowhead, fade over 3s) -- good
- Waypoint patrol paths (dashed lines) -- good
- Selection indicators (cyan glow ring) -- good

What is text-only (alert log):
- Zone violations -- no visual pulse on the map
- Threat escalations -- no visual indicator on the target
- New hostile detection -- alert text, but no map flash/pulse
- Amy speech -- toast at top, but no map marker showing "Amy is speaking"

The dispatch arrows are the strongest visual event. The hostile detection
alert in the log is useful. The main gap is that zone violations and
threat escalations have no map-level visual feedback.

**Not implemented**: Map-level pulse effects would require a render queue
for transient animations. The current alert log approach is adequate for
the project scope.

## 7. Data Sharing with assets.js

**Verdict: Clean, no mismatch.**

- `war.js` reads from `assetState.simTargets` via `getTargets()` -- single
  source of truth
- `updateSimTarget()` in assets.js flattens `position.{x,y}` to `t.x/t.y`
- `getTargetPosition()` in war.js handles both `t.position.x` and `t.x` --
  belt and suspenders, no bugs here
- Both files use the same coordinate system (-30 to 30 map bounds)
- Heading conversion differs in math approach but produces identical visual
  results (verified algebraically)
- Both files render battery bars with the same green-to-red formula

**No changes needed.**

## 8. Additional Findings

### 8a. Keyboard shortcut conflicts
Global `S` key switches to Scenarios view. War Room `S` key switches to
SETUP mode. The global handler in app.js has a guard:
```js
if (state.currentView === 'war' && ['s', 't', 'o'].includes(e.key)) return;
```
This correctly prevents the conflict. However, `T` for Targets view is also
blocked when in the War Room -- this is intentional (War Room uses `T` for
TACTICAL mode). The user must click the view tab or use gamepad LB/RB to
leave. This is documented nowhere.

### 8b. Gamepad support is absent for War Room
`input.js` includes 'war' in VIEW_ORDER (LB/RB can navigate to it), but
there is no war-specific gamepad handling. The gamepad cannot:
- Pan the camera
- Select targets
- Dispatch units
- Switch modes

This is a significant gap for a project that emphasizes gamepad support.

**Implemented**: Added war-specific gamepad controls in input.js
(D-pad/stick for camera pan, A to select nearest target, B to deselect,
Y to center on selection, LT/RT for zoom, and war-specific help text).

### 8c. Amy thought stream is fetch-only
`fetchAmyStatus()` fetches once on init. After that, Amy thoughts are
pushed via WebSocket event handlers. The initial fetch is correct but the
Amy panel will be empty until the first WebSocket event arrives. This is
fine -- no change needed.

### 8d. No "follow selected unit" camera mode
In many RTS games, pressing a key (often F or Home) locks the camera to
follow the selected unit. This would be useful for watching a patrol rover
during its route. Not implemented, noted as a future enhancement.

## Summary of Changes Made

1. **Right-click dispatch works in all modes** (war.js line 663)
2. **Minimap click-to-pan** (war.js mousedown handler)
3. **Cursor-centered zoom** (war.js wheel handler)
4. **War-specific keyboard controls in help overlay** (input.js)
5. **War-specific gamepad controls** (input.js)
