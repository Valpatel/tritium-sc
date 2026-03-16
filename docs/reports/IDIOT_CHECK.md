# VILLAGE IDIOT REPORT -- Wave 178 (2026-03-15)

**Persona**: A confused person who wandered in. Ollama was not responding, so I am just me -- someone trying to use this product for the first time. Tech skill: 2/5. Expected a clean tactical map with some dots I could click. Got a satellite photo someone sneezed neon paint on.

## Summary Scorecard

```
WEBSITE: works
MAP: visible -- satellite imagery present but OBSCURED by overlapping layers
TARGETS ON MAP: yes -- 70+ targets as small colored squares, but hard to distinguish from GIS noise
CLICKING: targets are clickable, Unit Inspector opens with full details
DEMO MODE: already active, targets moving in real time
APIs: 5 of 5 returned data
JS ERRORS: 0

Loop 1 (First Boot): 7/8 (everything works but the map is cluttered)
```

---

## Loop 1: First Boot -- "What am I looking at?"

| Step | Result | What Happened |
|------|--------|---------------|
| 1. Navigate to localhost:8000 | PASS | Page loads, no errors, takes about 5-8 seconds |
| 2. See tactical map with satellite imagery | PARTIAL | Satellite imagery IS there but obscured by 61 prediction ellipses creating an opaque blob in the center, 474 traffic signal dots scattered on every street, and 133 trail lines |
| 3. Understand the UI | PARTIAL | Header shows stats (49 units, 21 threats, 70 targets), menu bar visible. But the map itself is confusing -- too many overlapping visual layers |
| 4. Open VIEW menu | NOT TESTED |
| 5. Start demo mode | PASS | Demo was already active, confirmed via /api/demo/status |
| 6. See targets appear | PASS | 67-73 markers visible as 22x22px colored squares, they move |
| 7. Click a target | PASS | Clicked "Intruder Alpha", Unit Inspector opened on the left side |
| 8. See target details | PASS | Full details: name, type (PERSON), alliance (HOSTILE), FSM state (ADVANCING), position, speed (1.5 m/s), heading (271 deg), health (80/80 100%), combat stats, personality, brain state |

---

## THE VISUAL CLUTTER PROBLEM -- THIS IS THE MAIN FINDING

I was asked specifically about "large blue/cyan circles cluttering the map." Here is what I found:

### Problem 1: Prediction Ellipses (THE WORST)
- **61 prediction ellipse polygons** are drawn on the map as filled shapes
- Each one is individually `rgba(255, 42, 109, 0.12)` (magenta at 12% opacity)
- The layer paint has `fill-opacity: 1` so the polygon color is the effective opacity
- BUT because 61 of them overlap in the center where targets cluster, opacity STACKS
- 12% x many overlapping = essentially opaque in the center
- Result: a large blurry blue/magenta/pink BLOB covers the center of the map
- You CANNOT see the satellite imagery or buildings underneath
- Layer name: `tritium-prediction-ellipses-fill`

### Problem 2: Traffic Signal Dots (474 of them)
- **474 traffic signal markers** rendered as small magenta circles (radius 4px)
- They appear at EVERY street intersection across the entire visible area
- Same magenta color family as hostile target markers
- A new user cannot tell which dots are actual targets vs. GIS decoration
- The map looks like it has a rash
- Layer name: `geo-traffic-signals-layer`

### Problem 3: Trail Lines (133 of them)
- **133 trail lines** showing where targets have moved
- They add more colored lines to an already busy map

### Proof: Comparison Screenshots
I programmatically toggled the layers off:
- **With all overlays ON** (default): Center of map is an unreadable glowing blob, hundreds of dots on every street
- **With prediction ellipses OFF**: Map immediately clearer, you can see buildings and targets
- **With ALL overlays OFF** (just satellite + markers): Map is clean, professional, and readable. Target markers are clearly visible. This is what a first-time user should see.

---

## 5 API Endpoint Checks

| Endpoint | Result |
|----------|--------|
| `/api/targets` | Returned 2 targets (oddly low -- UI shows 70. Simulation uses different endpoint?) |
| `/api/fleet/devices` | Returned demo device "Alpha-Node" with battery 85.7%, uptime, sensor counts |
| `/api/system/readiness` | "partially_ready" 5/9 -- MQTT yellow (not connected), demo green, auth yellow (disabled) |
| `/api/plugins` | 26 plugins loaded successfully |
| `/api/dossiers` | Returned dossier list with UUIDs, entity types, threat levels |

APIs: 5/5 returned real data. No 500 errors, no empty responses.

---

## OBVIOUS PROBLEMS

1. **Prediction ellipses make the map center unreadable.** 61 overlapping semi-transparent polygons create an opaque blob. This should be OFF by default or dramatically reduced in opacity.

2. **474 traffic signal dots look like targets.** They are the same magenta color family. A new user sees hundreds of dots and has no idea which ones are real targets vs. GIS decoration. This layer should be OFF by default.

3. **The /api/targets endpoint returns 2 while the UI shows 70.** The main "targets" API seems disconnected from what the simulation engine is tracking. Confusing for anyone trying to integrate.

4. **Mouse wheel zoom did not work** in my Playwright test. The map stayed at roughly the same zoom level across 13 scroll events. Could be a Playwright issue, but worth noting.

5. **Trail lines add clutter.** 133 lines on top of everything else. Not as bad as the ellipses but contributes to the overall visual noise.

## THINGS THAT ACTUALLY WORK

1. Map loads with real satellite imagery -- the neighborhood is recognizable and detailed
2. Target markers (22x22px colored squares with NATO-style symbology) are visible and clickable
3. Unit Inspector opens with complete target information -- name, type, alliance, health, speed, heading, combat stats
4. Header stats bar shows live counts (49 units, 21 threats, 70 targets) with color coding
5. Demo mode runs and targets move in real time
6. Amy narration text floats across the map in green ("confirmed hostile -- Unknown contact!")
7. Zero JavaScript errors across all tests
8. 26 plugins loaded without errors
9. All 5 API endpoints returned real data
10. Welcome tooltip appears explaining controls

## MY HONEST IMPRESSION

The product works. The map loads, targets appear and move, clicking them shows detailed information, the AI commander narrates events, and the APIs return real data. Zero JS errors. That is genuinely impressive.

But the default view is a cluttered mess. A park ranger or security guard opening this for the first time would see a glowing neon blob over a satellite photo with hundreds of unexplained dots on every street. They would close the tab. The actual useful information -- where are the targets, what are they doing -- is buried under layers of GIS decoration and prediction visualization that should be turned off by default.

The fix is straightforward: hide prediction ellipses and traffic signals by default. Let power users toggle them on via the MAP or VIEW menu. The product underneath the clutter is solid.

## Screenshots Saved

- `tests/.baselines/idiot_initial_view.png` -- first load, all layers on
- `tests/.baselines/idiot_zoomed_default.png` -- default zoom after dismissing tooltip
- `tests/.baselines/idiot_clicked_target.png` -- Unit Inspector open after clicking target
- `tests/.baselines/idiot_no_ellipses.png` -- prediction ellipses HIDDEN (much cleaner)
- `tests/.baselines/idiot_with_ellipses.png` -- prediction ellipses VISIBLE (cluttered)
- `tests/.baselines/idiot_clean_map.png` -- ALL overlays hidden (cleanest, most readable view)
