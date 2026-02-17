# UI View Specifications

Canonical reference for what each TRITIUM-SC view **should** look like.
Used by humans for design review and by automated vision tests
(`tests/ui/test_vision.py`) to compare intent vs. reality.

> **Maintaining this document**: When you add or change a UI panel, button,
> or layout, update this file first.  The vision audit prompts in
> `tests/ui/test_vision.py` are derived from these specs.  If the spec
> here is wrong, the tests will flag false positives.

## Vision Audit System Architecture

```
┌──────────────────────┐
│  docs/UI-VIEWS.md    │  ← SOURCE OF TRUTH (this file)
│  (View Specs)        │     Humans edit this when UI changes
└──────────┬───────────┘
           │ derives from
           ▼
┌──────────────────────┐
│  test_vision.py      │  ← AUDIT TOOL
│  VIEWS[].audit_prompt│     Each view has an intent prompt
└──────────┬───────────┘
           │ feeds into
           ▼
┌──────────────────────┐
│  Ollama Vision Model │  ← ANALYSIS ENGINE
│  (llava / qwen3-vl)  │     Compares screenshot vs prompt
└──────────┬───────────┘
           │ produces
           ▼
┌──────────────────────┐
│  audit_report.md     │  ← OUTPUT
│  (Findings)          │     PRESENT / MISSING / WRONG / BROKEN
└──────────────────────┘
```

### Prompt Engineering Methodology

Each view's `audit_prompt` in `test_vision.py` follows a strict template:

```
1. ROLE:     "You are a UI auditor comparing a screenshot against its design specification."
2. INTENT:   "DESIGN INTENT — {View Name}:" followed by what the view SHOULD show
3. ELEMENTS: For each panel/section, list:
             - Exact header text and color (e.g. "'ALERTS' in magenta")
             - Element types and positions (e.g. "Bottom-right, 300px wide")
             - Expected content (e.g. "Timestamped entries color-coded by type")
             - Visual styling (e.g. "Cyan border, dark background")
4. COMPARE:  Ask the model to classify each element as:
             - PRESENT: Element matches spec
             - MISSING: Element not found
             - WRONG:   Element differs from spec
             - BROKEN:  Element has rendering issues
             - EXTRA:   Unexpected element not in spec
5. CONTEXT:  Resolution-specific addendum (added automatically):
             - Mobile:  "check touch targets ≥44px, vertical stacking"
             - Tablet:  "check layout adaptation, panel spacing"
             - Desktop: "check multi-panel layout, no empty space"
```

### How to Update When the UI Changes

**Adding a new panel to an existing view:**
1. Edit the view's spec table in this doc (add the new panel)
2. Edit the view's `audit_prompt` in `test_vision.py` to mention it
3. Run `python3 tests/ui/test_vision.py --view {view} --quick` to verify

**Adding a new view:**
1. Add the full spec to this doc (see "Adding a New View" at bottom)
2. Add a `VIEWS` entry in `test_vision.py` with prompt derived from spec
3. Run audit to verify

**Changing an element's styling:**
1. Update this doc's spec table
2. Update the `audit_prompt` (e.g. change "cyan" to "green" if color changed)
3. The next audit run will validate the new style

**Key principle:** The spec in this doc is the truth.  If the UI looks
wrong but matches this doc, the doc needs updating.  If the UI looks right
but the audit flags it, the prompt needs updating to match the doc.

### Prompt Quality Guidelines

- **Be specific about text:** Use exact strings like `'MONITORING ZONES'`
  not vague "a header"
- **Be specific about colors:** Use `cyan (#00f0ff)` not just "blue-ish"
- **Be specific about positions:** Use `top-left`, `bottom-right (300px wide)`
- **Mention empty states:** What does the view show when there's no data?
- **Mention game states:** War Room has setup/active/gameover states
- **Don't ask open-ended questions:** The model should compare, not explore
- **Use the 5-category framework:** PRESENT/MISSING/WRONG/BROKEN/EXTRA

## Global Design Language

| Property | Value |
|----------|-------|
| Background | `#0a0a0f` (near-black) |
| Panel background | `rgba(26, 26, 46, 0.6)` or `#12121a` |
| Panel border | `1px solid rgba(0, 240, 255, 0.2)` |
| Primary color (cyan) | `#00f0ff` |
| Secondary (magenta) | `#ff2a6d` |
| Success (green) | `#05ffa1` |
| Warning (yellow) | `#fcee0a` |
| Font | JetBrains Mono, monospace |
| Display font | Orbitron, sans-serif |
| Border radius | 4px |
| Spacing | `--space-sm` 8px, `--space-md` 16px, `--space-lg` 24px |
| Hover | Cyan border glow |
| Selected/Active | Magenta border glow |

All views share a top toolbar (`view-controls`) with view-switching
buttons: GRID, PLAYER, 3D, ZONES, TARGETS, ASSETS, ANALYTICS, AMY, SCENARIOS, WAR ROOM.
Keyboard shortcuts: G, P, D, Z, T, A, N, Y, S, W.

---

## Grid View (G)

**File**: `frontend/js/grid.js`
**Container**: `#view-grid`

### Layout
CSS Grid of camera feed tiles.  Default 2x2 (4 tiles).

### Elements
| Element | Location | Spec |
|---------|----------|------|
| Video tile | Grid cells | 16:9 aspect, dark (#12121a) bg, subtle cyan border |
| Channel label | Bottom of each tile | Cyan, uppercase, 0.75rem monospace |
| Status indicator | Bottom-right of tile | Green 0.625rem, shows "LIVE" or timestamp |
| Grid size selector | Toolbar | Dropdown: 1x1, 2x2, 3x3 |

### Responsive
- Mobile: single column, tiles stack
- Tablet: 2 columns
- Desktop: 2-3 columns depending on selector

---

## Player View (P)

**File**: `frontend/js/player.js`
**Container**: `#view-player`

### Layout
Vertical stack: large video area fills most of screen, controls below.

### Elements
| Element | Location | Spec |
|---------|----------|------|
| Video player | Main area | HTML5 `<video>` with native controls, fills container |
| Play/Pause button | Controls bar | Triangle/pause icon |
| DETECTIONS toggle | Controls bar | Cyan button, toggles YOLO bounding box overlay |
| Timeline | Below controls | Clickable progress bar with detection event markers |
| Time display | Controls bar | Current time / Duration in HH:MM:SS |
| Annotation canvas | Over video | Transparent overlay for YOLO boxes |

### Empty State
Dark empty area when no video loaded.

---

## 3D Camera Grid (D)

**File**: `frontend/js/grid.js` (Three.js init section)
**Container**: `#view-3d`

### Layout
Full-screen Three.js WebGL canvas with a small overlay panel.

### Elements
| Element | Location | Spec |
|---------|----------|------|
| Three.js canvas | Full view | `<canvas id="three-canvas">`, fills container |
| "3D CAMERA GRID" label | Top-left overlay | Cyan text in a panel, absolutely positioned |
| Camera markers | 3D scene | Objects representing physical camera positions |
| Grid/floor | 3D scene | Grid lines or ground plane |

### Interaction
- Click+drag to orbit (OrbitControls)
- Scroll to zoom
- Right-drag to pan
- Click camera marker to select
- Double-click to view camera feed

### Responsive
- Mobile: canvas fills screen, overlay may need smaller text
- Tablet: same as desktop
- Desktop: full 3D scene with ample space

---

## Zone Manager (Z)

**File**: `frontend/js/zones.js`
**Container**: `#view-zones`

### Layout
2-column grid: `300px 1fr`.

### Elements
| Element | Location | Spec |
|---------|----------|------|
| "MONITORING ZONES" header | Left panel top | Cyan text |
| "+ DRAW" button | Left panel top-right | Creates new zone |
| Zone list | Left panel | Zone name (colored by type), type badge, event count |
| Zone canvas | Right panel | Drawing area for zone polygons |
| Empty state | Right panel | "SELECT A CAMERA" + pin icon when no camera chosen |
| "ZONE EVENTS" header | Bottom panel | Magenta text with count |
| Event list | Bottom panel (200px max) | Timestamps, target types, scrollable |

### Zone Type Colors
- `activity` = cyan
- `entry_exit` = green
- `object_monitor` = yellow
- `tripwire` = magenta

### Responsive
- Mobile: panels stack vertically (left panel on top, canvas below)
- Tablet: 2-column holds but may feel cramped
- Desktop: full 2-column with ample space

---

## Target Tracker (T)

**File**: `frontend/js/targets.js`
**Container**: `#view-targets`

### Layout
Vertical flex stack with padding.

### Elements
| Element | Location | Spec |
|---------|----------|------|
| PEOPLE / VEHICLES tabs | Top | Toggle buttons with icons |
| Channel filter | Top | Dropdown selector |
| Date filter | Top | HTML date input |
| REFRESH button | Top | Cyan button |
| Target count | Top-right | "N targets" text |
| Target gallery | Middle (flex:1) | CSS Grid, auto-fill min 180px, target cards |
| Target card | Gallery cells | Square thumbnail, channel (cyan), confidence %, timestamp |
| Empty state | Gallery | Magnifying glass + "NO TARGETS FOUND" when empty |
| Detail panel | Bottom | 200x200 image, title (cyan), LABEL / FIND SIMILAR / CLOSE buttons |

### Responsive
- Mobile: gallery 1-2 columns, cards may be smaller
- Tablet: 3-4 columns
- Desktop: 5-6 columns with detail panel alongside

---

## Asset Manager (A)

**File**: `frontend/js/assets.js`
**Container**: `#view-assets`

### Layout
2-column grid: `350px 1fr`.

### Left Panel
| Element | Spec |
|---------|------|
| "OPERATIONAL ASSETS" header | Cyan bold |
| "+ REGISTER" button | 0.7rem |
| Asset cards | Icon (emoji by type), name (cyan), status badge, ID (muted monospace), battery %, task type (yellow) |
| Summary | Total (cyan), Active (green), Offline (magenta) |

### Right Panel
| Element | Spec |
|---------|------|
| Stat boxes (4-col grid) | BATTERY, ORDNANCE, POSITION, HEADING — label + large value |
| ONBOARD CAMERA | Left of 2-col sub-grid, MJPEG feed or placeholder |
| TACTICAL MAP canvas | Right of 2-col sub-grid: grid lines (30px), property outline, unit markers (friendly=green circle, hostile=magenta diamond, unknown=yellow square), patrol paths (dashed cyan), dispatch arrows (magenta), battery bars, HOME marker |
| "TASK ASSIGNMENT" header | Magenta bold |
| Task buttons (4-col grid) | PATROL, TRACK, ENGAGE, LOITER, INVESTIGATE, RECALL, REARM, CANCEL (red-tinted) |

### Responsive
- Mobile: panels stack, asset list on top, map and controls below
- Tablet: narrow 2-column
- Desktop: full 2-column with ample detail space

---

## Analytics (N)

**File**: `frontend/js/analytics.js`
**Container**: `#view-analytics`

### Layout
Scrollable vertical stack.

### Sections (top to bottom)
| Section | Spec |
|---------|------|
| Header | "DETECTION ANALYTICS" (cyan h2), period dropdown (7/14/30 days), REFRESH button |
| Stats row (4-col) | TOTAL DETECTIONS (cyan number), PEOPLE (magenta), VEHICLES (yellow), PEAK HOUR (green) |
| Charts (2-col) | Daily Detections (stacked bars: magenta+yellow), Hourly Distribution (24 cyan bars) |
| Recent Targets | "RECENT TARGETS (TODAY)" (magenta), "VIEW ALL" link, thumbnail gallery grid |
| Channel Breakdown | Per-channel: name (cyan), count, progress bar, percentage |

### Empty State
Stats show "0", charts empty, no targets.  This is expected when no
detection data exists.

---

## Amy AI Commander (Y)

**File**: `frontend/js/amy.js`
**Container**: `#view-amy`

### Layout
2x2 grid of panels (top-left, top-right, bottom-left, bottom-right)
plus a BATTLESPACE section.

### Top-Left: PRIMARY OPTICS
| Element | Spec |
|---------|------|
| Header | "PRIMARY OPTICS" (cyan) |
| Tab buttons | "LIVE" (active default), "GALLERY" |
| Node label | e.g. "BCC950", "SCENARIO", or "--" |
| LIVE tab | MJPEG `<img>` feed, OR placeholder: circle icon + "NO CAMERA CONNECTED" + "Waiting for sensor node..." |
| GALLERY tab | Photo thumbnail grid with metadata |

### Top-Right: COMMANDER STATUS
| Element | Spec |
|---------|------|
| Header | "COMMANDER STATUS" |
| State badge | Colored by state (idle/thinking/speaking) |
| Stat boxes (6) | STATE, MOOD, THINKING, NODES, PAN, TILT |
| Sensor Nodes list | Node ID, name, capability badges (CAM, PTZ, MIC, SPK) |
| Command buttons (6) | SCAN, OBSERVE, ATTEND, IDLE, AUTO-CHAT, NOD |

### Bottom-Left: INNER THOUGHTS
| Element | Spec |
|---------|------|
| Header | "INNER THOUGHTS" + count |
| Stream | Scrollable thought entries: time (24h), type label (uppercase), text |
| Types | thought, speech, transcript, observation, action, deep_look (color-coded) |

### Bottom-Right: SENSORIUM + CHAT
| Element | Spec |
|---------|------|
| Sensorium header | "SENSORIUM", people count |
| Narrative | Scrollable text |
| Chat header | "TALK TO AMY" |
| Chat log | Messages: Amy (left), User (right) |
| Input row | Text field ("Say something to Amy...") + SEND button |

### BATTLESPACE
| Element | Spec |
|---------|------|
| Header | "BATTLESPACE" + target count summary |
| Spawn buttons | "SPAWN HOSTILE" (magenta border), "SPAWN FRIENDLY" (green border) |
| Target list | Alliance dot + name (colored) + position + battery % + remove (X) |
| Dispatch log | Max 20 entries: "TIME DISPATCH name -> (x,y)" |

### Responsive
- Desktop: 2x2 grid with all panels visible
- Tablet: may need to scroll, panels narrower
- Mobile: panels stack vertically, chat input needs full-width

---

## Scenarios (S)

**File**: `frontend/js/scenarios.js`
**Container**: `#view-scenarios`

### Layout
2x2 panel grid: scenario library + camera, live feed + evaluation.

### Top-Left: SCENARIO LIBRARY
| Element | Spec |
|---------|------|
| Header | "SCENARIO LIBRARY" with cache badge and count |
| Scenario list | Scrollable, each item shows name + metadata |
| Empty state | "Loading scenarios..." when fetching |

### Top-Right: SYNTHETIC CAMERA
| Element | Spec |
|---------|------|
| Header | "SYNTHETIC CAMERA" with run badge ("IDLE" default) |
| Video feed | MJPEG `<img>`, or overlay: circle icon + "NO FEED" + "Select a scenario and click RUN" |
| Speech bubble | Overlay for Amy's TTS output |
| Run controls | Buttons below video |

### Bottom-Left: LIVE FEED
| Element | Spec |
|---------|------|
| Header | "LIVE FEED" with action count ("0 actions") |
| Voice selector | Dropdown for TTS voice selection |
| TTS toggle | Checkbox to enable/disable |
| Timeline | "Run a scenario to see live events..." when idle |

### Bottom-Right: EVALUATION
| Element | Spec |
|---------|------|
| Header | "EVALUATION" |
| Score grid | SCORE, MATCHED, DETECTION, LATENCY (all "--" when idle) |
| Star rating | 5 stars for human rating (hidden until run completes) |
| Score details | Detailed breakdown area |

### Responsive
- Desktop: 2x2 grid with all panels visible
- Tablet: panels may be narrower, still 2x2
- Mobile: panels stack vertically

---

## War Room (W)

**Files**: `frontend/js/war.js`, `frontend/js/war3d.js`
**Container**: `#view-war`

### Layout
Full-screen Three.js WebGL canvas with absolutely-positioned HUD overlays.
The canvas sits at z-index 1; the HUD container (`#war-hud`) is at z-index 10.

### 3D Canvas
| Element | Spec |
|---------|------|
| Ground plane | Satellite imagery tiles at 0.7 opacity |
| Grid | Cyan lines, 5-unit spacing |
| Unit markers | Friendly=green circle, hostile=red diamond, neutral=blue, unknown=yellow |
| Zone polygons | Colored by escalation level |
| Dispatch arrows | Magenta dashed lines, 3s fade |
| Weapon ranges | Dashed rings |

### HUD Panels
| Panel | Location | Spec |
|-------|----------|------|
| Address bar | Top-left | Input "Enter address..." + GEOCODE button + status text |
| Mode selector | Top-center | SIM / LIVE toggle buttons + mode label |
| BEGIN WAR | Center | Large cyan-bordered button (visible in setup state) |
| Amy Status | Right (280px) | "AMY STATUS" header, mood, state, scrollable thoughts |
| Alert Log | Bottom-right (300px) | "ALERTS" (magenta), timestamped entries by type |
| Minimap | Bottom-left (150x150) | Scaled map with unit dots, cyan border |
| Score | Top-center | Score, Kills, Accuracy, Wave (visible during active game) |
| Kill feed | Right | Recent eliminations (visible during active game) |
| Countdown | Center overlay | "WAVE STARTING IN 3... 2... 1..." (during transitions) |
| Wave banner | Center overlay | "WAVE 3 START" (during wave transitions) |
| Game over | Center modal | Final score + stats + RESTART button |

### Game States
1. **Setup**: BEGIN WAR button visible, score hidden
2. **Countdown**: 5-4-3-2-1 overlay, BEGIN WAR hidden
3. **Active**: Score + kill feed visible, units fighting
4. **Wave Complete**: Brief pause, next wave countdown
5. **Victory/Defeat**: Game over modal

### Responsive
- Desktop: full-screen canvas fills viewport, HUD panels well-spaced
- Tablet: HUD panels may overlap, text may be small
- Mobile: canvas fills screen but HUD panels likely need rearrangement

---

## Adding a New View

When adding a new view:

1. Add the HTML container in `index.html` (id: `view-{name}`)
2. Add the JS file in `frontend/js/{name}.js`
3. Add keyboard shortcut in `frontend/js/app.js` (switchView)
4. **Add the view spec to this document** with all panels and elements
5. Add an entry to `VIEWS` dict in `tests/ui/test_vision.py` with:
   - `shortcut`, `settle_ms`, `label`, `description`
   - `audit_prompt` derived from the spec in this document
6. Run the full audit: `python3 tests/ui/test_vision.py`
7. Update CLAUDE.md Keyboard Shortcuts section

## Running the Vision Audit

```bash
# Full audit: all views, all resolutions (mobile/tablet/desktop)
python3 tests/ui/test_vision.py

# Quick desktop-only pass
python3 tests/ui/test_vision.py --quick

# Single view
python3 tests/ui/test_vision.py --view war

# With deep model analysis (qwen3-vl:32b, slow but thorough)
python3 tests/ui/test_vision.py --deep

# Single resolution
python3 tests/ui/test_vision.py --resolution mobile
```

Reports saved to `/tmp/tritium-ui-audit/audit_report.md` (human-readable)
and `audit_report.json` (machine-readable).
