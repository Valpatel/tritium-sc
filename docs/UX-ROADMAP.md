# TRITIUM-SC UX Improvement Roadmap

**Date**: 2026-02-22 | **Scope**: 200+ actionable items across 15 categories
**Source**: API audit, landscape survey (docs/LANDSCAPE-SURVEY.md), user stories (docs/USER-STORIES.md)

> Every item ties back to an existing API endpoint, missing UI surface, or UX pattern from the landscape survey.
> Priority: P0 = this week, P1 = this sprint, P2 = next sprint, P3 = backlog.
> Effort: S = small (<1hr), M = medium (1-4hr), L = large (4-8hr), XL = multi-day.

---

## 1. Panel System (27 items)

### Existing Panels — Polish
| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 1 | Amy panel: show last 5 thoughts in scrollable feed (not just latest) | P1 | S | Uses `amy.lastThought` store path |
| 2 | Amy panel: add "Talk" button that opens chat overlay | P1 | S | EventBus emit |
| 3 | Amy panel: show node count and active sensors | P2 | S | /api/amy/status returns `nodes` |
| 4 | Units panel: click unit to center map on it | P0 | M | EventBus `map:center` + store unit positions |
| 5 | Units panel: show unit health bars | P1 | S | SimulationTarget has `health` field |
| 6 | Units panel: group by alliance (friendly/hostile/neutral) | P1 | M | Filter + section headers |
| 7 | Units panel: sort options (name, distance, health, alliance) | P2 | M | Dropdown in toolbar |
| 8 | Alerts panel: severity filter (low/medium/high/critical) | P1 | S | CSS filter buttons like audio panel |
| 9 | Alerts panel: click alert to center map on incident location | P1 | M | Need geo coords from alert |
| 10 | Alerts panel: auto-scroll to newest, pause on hover | P1 | S | IntersectionObserver pattern |
| 11 | Game HUD: show current wave timer / countdown | P0 | S | game.countdown store path |
| 12 | Game HUD: kill feed showing last 5 eliminations | P0 | M | Subscribe to game eliminations |
| 13 | Game HUD: turret placement controls (drag-drop or click-to-place) | P1 | L | POST /api/game/place |
| 14 | Mesh panel: connection status indicator in panel title bar | P2 | S | Dynamic title update |
| 15 | Camera Feeds: scene type selector when creating feed | P1 | S | bird_eye/street_cam/battle/neighborhood |
| 16 | Camera Feeds: snapshot download button | P2 | S | GET /api/synthetic/cameras/{id}/snapshot |
| 17 | Audio panel: waveform visualization for playing sounds | P3 | L | AnalyserNode + canvas |
| 18 | Zones panel: inline zone edit (rename, toggle enabled) | P1 | M | PATCH /api/zones/{id} |
| 19 | Zones panel: vertex count + area display | P2 | S | Calculate from points array |
| 20 | Scenarios panel: run history per scenario | P2 | M | GET /api/scenarios/{name} |
| 21 | Scenarios panel: comparison view (before/after scores) | P3 | L | GET /api/scenarios/compare |

### New Panels — Coverage Gaps
| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 22 | Events Timeline panel — chronological event stream with filtering | P1 | L | /api/zones/*/events + alerts |
| 23 | Target Detail panel — click any target for full profile | P1 | M | /api/search/target/{id} |
| 24 | Escalation panel — current threat level, auto-dispatch status | P1 | M | escalation_change WS events |
| 25 | Chat panel — inline Amy conversation without full overlay | P2 | L | POST /api/amy/chat |
| 26 | Performance panel — FPS, WS latency, render stats | P2 | M | window.performance + stats |
| 27 | Robot Detail panel — select robot, see telemetry, thoughts, commands | P2 | L | /api/telemetry/robot/{id} + robot_thought WS |

---

## 2. Map & Tactical Display (28 items)

### Visual Enhancements
| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 28 | Fog of war: adjustable vision radius per unit type | P1 | M | Drone=150m, rover=50m, turret=80m |
| 29 | Fog of war: gradual reveal animation (not instant) | P2 | M | Fade gradient at edge |
| 30 | Unit labels: show name on hover, not just color dot | P0 | S | Canvas text render |
| 31 | Unit health bar rendered below each unit on map | P1 | M | Canvas rect with color gradient |
| 32 | Projectile trails: longer persistence (2s fade, not instant) | P1 | S | Trail array with alpha decay |
| 33 | Explosion effects on target elimination | P1 | M | Particle burst at kill location |
| 34 | Minimap in corner showing full battlefield | P0 | L | Scaled-down canvas overlay |
| 35 | Grid overlay with configurable spacing | P2 | S | Canvas grid lines |
| 36 | Distance measurement tool (click two points) | P3 | M | Haversine formula display |
| 37 | Waypoint markers (user-placed pins on map) | P2 | M | Click to place, right-click to remove |
| 38 | Zone boundaries drawn on map (polygons) | P1 | L | Read zone.points, draw polygon |
| 39 | Zone highlighting on hover/selection from panel | P1 | M | EventBus `zone:selected` listener |

### Interaction
| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 40 | Click-to-select units on map | P0 | M | Hit testing on unit positions |
| 41 | Selected unit details tooltip | P0 | S | Show name, type, health, alliance |
| 42 | Right-click context menu on map | P1 | L | Spawn hostile, place turret, set waypoint |
| 43 | Drag to pan (already works), pinch to zoom on mobile | P1 | M | Touch event handlers |
| 44 | Double-click to center on location | P1 | S | SetView to clicked coords |
| 45 | Keyboard arrow keys for map panning | P2 | S | Already have zoom [/], add pan arrows |
| 46 | Map bookmark locations (save camera position) | P3 | M | localStorage save/recall |
| 47 | Unit patrol path visualization (line segments) | P2 | M | Draw polyline from patrol waypoints |
| 48 | Heat map overlay (detection density) | P3 | L | Canvas overlay with gaussian blur |
| 49 | Sensor coverage overlay (camera FOV cones) | P3 | L | Draw arcs from camera positions |

### Satellite Imagery
| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 50 | Tile loading progress indicator | P2 | S | Count loaded/total tiles |
| 51 | Tile cache in localStorage (offline support) | P2 | M | IndexedDB tile store |
| 52 | Road overlay labels (street names) | P3 | M | ESRI label tile layer |
| 53 | Alternative map providers (OSM fallback) | P3 | M | Configurable tile URL |
| 54 | Day/night satellite toggle | P3 | S | CSS filter invert for night mode |
| 55 | Terrain elevation overlay | P3 | L | DEM data visualization |

---

## 3. Combat & Game System (25 items)

### Combat UX
| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 56 | Wave start countdown banner (3... 2... 1... FIGHT!) | P0 | M | Full-screen overlay, auto-dismiss |
| 57 | Kill streak announcements (DOUBLE KILL, MEGA KILL) | P0 | S | Already in announcer, need UI banner |
| 58 | Score multiplier display during streaks | P1 | S | Overlay text with glow effect |
| 59 | Wave summary screen between waves (kills, accuracy, MVP unit) | P1 | L | Modal with stats from game state |
| 60 | Damage numbers floating up from hit targets | P1 | M | Canvas text animation |
| 61 | Screen shake on nearby explosions | P2 | S | CSS transform: translate jitter |
| 62 | Victory/defeat screen with total stats breakdown | P1 | M | Enhance existing game-over overlay |
| 63 | Replay last 10 seconds button (slow-mo) | P3 | XL | Frame buffer + playback |

### Turret Placement
| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 64 | Visual placement mode: ghost turret follows mouse | P0 | L | Semi-transparent unit at cursor |
| 65 | Placement grid snap | P1 | S | Round to nearest grid cell |
| 66 | Placement cost display | P1 | S | Show cost before confirming |
| 67 | Turret type selector (basic, heavy, sniper) | P2 | M | Toolbar with turret cards |
| 68 | Turret upgrade system | P3 | XL | New API endpoint needed |
| 69 | Undo last placement | P1 | S | DELETE /api/amy/simulation/targets/{id} |
| 70 | Sell turret (click existing turret to remove) | P1 | M | Click handler + confirm |

### Game Flow
| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 71 | Difficulty selector (easy/normal/hard/insane) | P2 | L | Modify spawn rates and health |
| 72 | Pause/resume game | P1 | M | New API endpoint |
| 73 | Fast-forward button (2x, 4x speed) | P2 | M | SimulationEngine tick rate |
| 74 | Game mode selector (endless, timed, survival) | P3 | L | GameMode variants |
| 75 | Leaderboard (high scores in localStorage) | P2 | M | After game over, save to localStorage |
| 76 | Achievement system (first kill, 100 kills, no deaths wave) | P3 | L | Event-driven unlock |
| 77 | Map selection (different neighborhoods/layouts) | P2 | M | Level format JSON picker |
| 78 | Pre-game lobby with setup phase timer | P1 | M | Auto-begin after 60s or button |
| 79 | Spectator mode (watch AI play without interaction) | P3 | M | Auto-place turrets, auto-begin |
| 80 | Post-game stats export (shareable image) | P3 | L | Canvas screenshot with stats overlay |

---

## 4. Audio & Sound Design (18 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 81 | Spatial audio: sounds positioned relative to map camera | P2 | L | Web Audio API panner nodes |
| 82 | Background ambient loop during gameplay | P0 | M | Looping buffer from /api/audio/effects |
| 83 | Distinct sounds per event type (kill, wave start, alert) | P0 | M | Map event→sound in AudioManager |
| 84 | Volume fade during Amy speech | P1 | S | Duck ambient when TTS plays |
| 85 | Sound effect preview on hover in audio panel | P2 | S | Short preview clip |
| 86 | Custom sound upload | P3 | L | POST endpoint needed |
| 87 | Music track system (menu, combat, victory themes) | P2 | L | Crossfade between tracks |
| 88 | Mute keybind (M key) | P0 | S | Check if already wired |
| 89 | Per-category volume sliders | P2 | M | Separate gain nodes per category |
| 90 | Sound notification for new alerts | P1 | S | Play alert.wav on alert event |
| 91 | TTS voice selection | P3 | M | Piper voice model switcher |
| 92 | Audio indicator in status bar (speaker icon) | P1 | S | Show muted/unmuted state |
| 93 | Hit confirmation sound effect | P0 | S | Play on projectile_hit WS event |
| 94 | Kill streak jingle escalation | P1 | M | Different sounds for 2x, 3x, 5x |
| 95 | Environmental audio (wind, crickets, rain) | P3 | L | Time-of-day dependent |
| 96 | Audio diagnostics in system panel | P2 | S | AudioContext state, sample rate |
| 97 | Earcon sounds for panel open/close | P2 | S | Subtle UI feedback |
| 98 | Announcer voice-over for combat commentary | P1 | L | TTS from announcer events |

---

## 5. Accessibility & Input (16 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 99 | Screen reader ARIA landmarks for all panels | P1 | M | role, aria-label already started |
| 100 | Focus trap within open panels | P2 | M | Tab cycles within panel |
| 101 | High contrast mode (toggle) | P2 | M | CSS class swap, localStorage |
| 102 | Font size adjustment (Ctrl+/- or setting) | P2 | S | CSS custom property |
| 103 | Color blind modes (protanopia, deuteranopia, tritanopia) | P2 | L | CSS filter or palette swap |
| 104 | Keyboard shortcuts cheat sheet always visible | P1 | S | Status bar tooltip |
| 105 | Gamepad panel navigation (D-pad moves between panels) | P2 | L | Gamepad API focus manager |
| 106 | Gamepad turret placement | P3 | L | A button to confirm placement |
| 107 | Touch-friendly panel resize handles (larger hit area) | P1 | S | Min 44px touch targets |
| 108 | Reduced motion mode (disable animations) | P2 | S | `prefers-reduced-motion` media query |
| 109 | Voice commands via microphone | P3 | XL | Whisper STT + command parser |
| 110 | Panel tab order follows visual layout | P1 | M | Dynamic tabindex |
| 111 | Skip-to-content link for screen readers | P2 | S | Hidden anchor at top |
| 112 | Announce alerts to screen reader via live region | P1 | S | aria-live="polite" |
| 113 | Tooltip on all icon-only buttons | P0 | M | title attribute audit |
| 114 | Escape key closes any open modal/overlay | P0 | S | Global ESC handler (verify) |

---

## 6. Layout & Workspace (15 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 115 | Named layout save (user types name) | P0 | M | LayoutManager.save(name) |
| 116 | Layout quick-switch (Ctrl+1..9) | P0 | S | Already wired, verify presets |
| 117 | Layout export to JSON file | P1 | M | Download as .json |
| 118 | Layout import from JSON file | P1 | M | File picker + load |
| 119 | Auto-save layout on change | P2 | S | Debounced localStorage write |
| 120 | Layout reset to defaults | P1 | S | Button in menu bar |
| 121 | Panel minimize to title bar only | P1 | M | Collapse body, keep header |
| 122 | Panel maximize (fill viewport) | P1 | M | Double-click title bar |
| 123 | Panel snap to edges and other panels | P2 | L | Magnetic edge detection |
| 124 | Panel z-order: bring to front on click | P0 | S | Already works, verify |
| 125 | Panel opacity/transparency slider | P3 | S | CSS opacity per panel |
| 126 | Multi-monitor support (pop-out panels) | P3 | XL | window.open() with panel content |
| 127 | Panel presets per game phase (auto-switch layout on combat) | P2 | M | Listen to game.phase, apply preset |
| 128 | Workspace tour for first-time users | P3 | L | Step-by-step overlay guide |
| 129 | Panel list dropdown in menu bar (quick open any panel) | P0 | M | Menu bar addition |

---

## 7. Data Visualization & Analytics (20 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 130 | Detection trend sparkline in header | P1 | M | Canvas mini-chart, 24h data |
| 131 | Hourly activity heatmap (in Intel panel) | P1 | M | Already have hourly data |
| 132 | Camera-per-channel detection chart | P2 | L | /api/telemetry/detections |
| 133 | Robot telemetry sparklines (battery, speed over time) | P2 | L | /api/telemetry/robot/{id} |
| 134 | Zone event timeline (vertical timeline widget) | P2 | M | /api/zones/{id}/events |
| 135 | Combat stats dashboard (kills/wave chart) | P1 | M | game_elimination events |
| 136 | Sighting frequency chart per target | P2 | M | /api/search/sightings/{id} |
| 137 | System health gauges (CPU, memory, disk) | P2 | M | /api/telemetry/system |
| 138 | Real-time FPS graph in performance panel | P2 | S | requestAnimationFrame timing |
| 139 | WebSocket message rate indicator | P2 | S | Count messages per second |
| 140 | Network latency display | P2 | M | WS ping/pong timing |
| 141 | Detection accuracy tracking (user feedback loop) | P3 | L | /api/search/feedback |
| 142 | Scenario score trend chart | P2 | M | /api/scenarios/stats history |
| 143 | Unit uptime chart (time alive per unit) | P3 | M | Track spawn/death events |
| 144 | Heat map of elimination locations | P3 | L | Canvas overlay on map |
| 145 | Kill/death ratio per unit type | P2 | S | Aggregate from game events |
| 146 | Detection confidence distribution chart | P3 | M | Histogram of confidence values |
| 147 | Daily report generation (PDF export) | P3 | XL | Server-side report builder |
| 148 | Dashboard widgets (drag-drop chart panels) | P3 | XL | Chart panel plugin type |
| 149 | Export analytics data as CSV | P2 | M | Client-side CSV generator |

---

## 8. Amy AI Commander UX (16 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 150 | Thought stream SSE in panel (continuous, not just latest) | P0 | L | GET /api/amy/thoughts SSE |
| 151 | Mood indicator with color-coded ring around portrait | P0 | S | Already coded, verify visible |
| 152 | Amy speech bubble on map (floating text at Amy's position) | P1 | M | Canvas text near command post |
| 153 | Command input field in Amy panel (Lua dispatch) | P1 | M | POST /api/amy/command |
| 154 | Amy memory viewer (what she remembers) | P2 | M | New API endpoint or read memory.json |
| 155 | Cognitive layer indicator (which layer is active) | P1 | S | L1-L4 badge from status |
| 156 | Amy status history (state changes over time) | P3 | L | Log state transitions |
| 157 | Amy confidence level for current assessment | P2 | S | From sensorium response |
| 158 | Quick actions: "Scan area", "Patrol", "Stand down" | P1 | M | Predefined Lua commands |
| 159 | Amy personality settings (assertiveness, verbosity) | P3 | M | Config exposure |
| 160 | Amy action log (what she's dispatched) | P1 | M | Motor command history |
| 161 | Amy event annotations on map (markers at noted events) | P2 | L | Geo-tagged thought markers |
| 162 | Amy collaboration mode (human + AI decision-making) | P3 | XL | Approval workflow |
| 163 | Amy audio waveform when speaking | P2 | M | AnalyserNode visualization |
| 164 | Amy interruption support (user can break in mid-thought) | P3 | L | Cancel current thinking thread |
| 165 | Amy "explain" button on any decision | P2 | M | /api/amy/chat with context |

---

## 9. Search & Intelligence UX (18 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 166 | Thumbnail grid view (not just list) | P1 | M | Toggle list/grid in search panel |
| 167 | Drag-to-merge UI (drag one thumbnail onto another) | P2 | L | POST /api/search/merge |
| 168 | Label autocomplete from existing labels | P2 | M | Fetch existing labels, show suggestions |
| 169 | Recurring individual alerts (toast when flagged person returns) | P0 | L | Compare new detections against flagged |
| 170 | Suspicion score explanation tooltip | P1 | S | Show score factors on hover |
| 171 | Timeline view per target (all sightings chronologically) | P2 | L | /api/search/sightings/{id} |
| 172 | Camera filter in search results | P1 | S | /api/search/people?channel=X |
| 173 | Date range picker for search | P1 | M | date_from/date_to params |
| 174 | Bulk operations (select multiple, merge all) | P3 | L | Multi-select UI |
| 175 | Export search results as CSV | P2 | M | Client-side generator |
| 176 | Face crop zoom on thumbnail hover | P2 | S | CSS transform: scale(2) |
| 177 | "Last seen" relative timestamp (e.g., "5 min ago") | P1 | S | Date formatting utility |
| 178 | Suspicious pattern notification | P1 | M | Check recurring on new detection |
| 179 | Natural language search tips/examples | P1 | S | Placeholder text suggestions |
| 180 | CLIP search confidence display | P2 | S | Show similarity score |
| 181 | Side-by-side comparison view | P3 | L | Two thumbnails with similarity |
| 182 | Feedback buttons on each detection (correct/wrong) | P1 | M | POST /api/search/feedback |
| 183 | Detection bounding box overlay on video playback | P2 | L | /api/videos/detections/{ch}/{date}/{file} |

---

## 10. Video Playback UX (14 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 184 | Thumbnail previews in video list | P1 | M | GET /api/videos/thumbnail/{ch}/{date}/{file} |
| 185 | Video scrubber timeline with detection markers | P2 | L | Overlay dots at detection timestamps |
| 186 | Speed controls (0.5x, 1x, 2x, 4x) | P1 | S | video.playbackRate |
| 187 | Frame-by-frame stepping (arrow keys) | P2 | M | video.currentTime += 1/fps |
| 188 | Detection annotation toggle (show/hide boxes) | P2 | L | Canvas overlay on video |
| 189 | Export clip (save time range) | P3 | XL | Server-side FFmpeg clip |
| 190 | Picture-in-picture mode | P1 | S | video.requestPictureInPicture() |
| 191 | Video thumbnail on hover in list | P2 | M | Load thumb on mouseenter |
| 192 | Recent videos quick access | P1 | S | GET /api/videos?limit=5 |
| 193 | On-demand analysis button per video | P1 | M | POST /api/videos/analyze/{ch}/{date}/{file} |
| 194 | Multi-channel synchronized playback | P3 | XL | Sync multiple videos by timestamp |
| 195 | Keyboard shortcuts within video player | P1 | S | Space=pause, J/L=seek |
| 196 | Video download button | P1 | S | <a download> link to stream endpoint |
| 197 | Total storage usage display | P2 | S | Sum file sizes from channel list |

---

## 11. Mobile & Responsive (12 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 198 | Responsive panel stacking on small screens | P1 | L | Single-column mode <768px |
| 199 | Touch-optimized panel headers (larger drag area) | P1 | S | Min-height 44px |
| 200 | Swipe gestures for panel switching | P2 | M | Horizontal swipe between panels |
| 201 | Bottom navigation bar for mobile | P2 | L | Fixed bottom with panel icons |
| 202 | Fullscreen map mode (hide all panels) | P1 | S | Toggle via button or gesture |
| 203 | PWA manifest for add-to-homescreen | P2 | M | manifest.json + service worker |
| 204 | Offline mode (cached map tiles, last-known state) | P3 | XL | Service worker + IndexedDB |
| 205 | Mobile-optimized combat controls | P2 | L | Touch buttons for turret placement |
| 206 | Landscape lock during gameplay | P2 | S | screen.orientation.lock() |
| 207 | Notification API for alerts when tab is background | P1 | M | Notification.requestPermission() |
| 208 | Compact mode (smaller fonts, tighter spacing) | P2 | M | CSS class toggle |
| 209 | Mobile viewport meta tag optimization | P0 | S | Verify existing <meta viewport> |

---

## 12. Theming & Visual Polish (15 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 210 | Dark/light theme toggle | P3 | L | CSS custom properties swap |
| 211 | Accent color picker (cyan, magenta, green, custom) | P3 | M | CSS var override |
| 212 | Scanline overlay intensity control | P2 | S | CSS opacity variable |
| 213 | Loading skeleton screens for panels | P1 | M | Animated placeholder content |
| 214 | Smooth transitions on panel open/close (fade+scale) | P1 | M | CSS transition on mount |
| 215 | Toast notification queue (max 3 visible, stack) | P1 | M | Queue manager in EventBus |
| 216 | Toast notification types with distinct icons | P1 | S | Info/alert/success/warning |
| 217 | Panel header accent color per category | P2 | S | Colored left border |
| 218 | Consistent loading states across all panels | P1 | M | Shared CSS loading animation |
| 219 | Error state UI for failed API calls | P1 | M | Retry button + message |
| 220 | Empty state illustrations | P3 | M | SVG illustrations per panel |
| 221 | Micro-interactions (button hover effects, click ripple) | P2 | M | CSS transitions |
| 222 | Status bar polish (consistent typography, spacing) | P1 | S | Audit existing status bar |
| 223 | Header stat counters with animated transitions | P2 | M | CSS counter animation |
| 224 | Consistent icon system (no mixing Unicode + SVG) | P2 | L | Choose one icon approach |

---

## 13. Performance & Infrastructure (14 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 225 | WebSocket reconnection with exponential backoff | P0 | M | Already exists, verify behavior |
| 226 | WebSocket message batching (reduce re-renders) | P1 | M | TelemetryBatcher pattern |
| 227 | Canvas rendering optimization (dirty rect tracking) | P2 | L | Only redraw changed areas |
| 228 | RequestAnimationFrame throttle to 30fps when hidden | P1 | S | Page Visibility API |
| 229 | Lazy panel mounting (don't mount until first open) | P1 | M | Defer mount() call |
| 230 | Image lazy loading for all thumbnails | P1 | S | loading="lazy" (already done) |
| 231 | Memory leak audit (panel mount/unmount cycles) | P1 | L | Verify all listeners cleaned up |
| 232 | Concurrent fetch limiting (max 4 parallel API calls) | P2 | M | Semaphore wrapper |
| 233 | API response caching (short TTL for lists) | P2 | M | Cache-Control or client-side |
| 234 | Service worker for static asset caching | P2 | M | Cache CSS/JS, invalidate on deploy |
| 235 | Bundle analysis (identify large imports) | P3 | M | Import map audit |
| 236 | Map tile request deduplication | P2 | S | Track in-flight tile requests |
| 237 | WebGL context loss recovery | P2 | M | webglcontextlost event handler |
| 238 | DOM node count monitoring | P2 | S | Warn if >10K nodes |

---

## 14. Testing & Quality (12 items)

| # | Item | Priority | Effort | Notes |
|---|------|----------|--------|-------|
| 239 | Panel open/close cycle test for every panel | P0 | L | Playwright: open each, verify no errors |
| 240 | Panel content verification tests | P1 | L | Each panel shows data, not empty |
| 241 | Keyboard shortcut regression test | P1 | M | Press each key, verify action |
| 242 | Layout preset test (apply each, verify positions) | P1 | M | Playwright check panel positions |
| 243 | Mobile viewport test (responsive behavior) | P2 | M | Playwright emulate mobile |
| 244 | Accessibility audit (axe-core integration) | P2 | L | Run axe on /unified |
| 245 | Performance benchmark test (60fps sustained) | P1 | M | Already test_08, extend duration |
| 246 | Memory leak test (open/close panels 100x) | P2 | L | Measure heap size |
| 247 | WebSocket reconnection test | P2 | M | Kill/restart WS, verify recovery |
| 248 | Combat game flow end-to-end test | P1 | L | Already test_game_loop_proof, verify panels |
| 249 | Screenshot regression tests per panel | P2 | L | Playwright screenshot comparison |
| 250 | Cross-browser test (Chrome, Firefox, Safari) | P3 | L | Playwright multi-browser |

---

## 15. Landscape Survey Adoptions (12 items)

From [docs/LANDSCAPE-SURVEY.md](LANDSCAPE-SURVEY.md):

| # | Item | Priority | Effort | Source | Notes |
|---|------|----------|--------|--------|-------|
| 251 | Frigate-style motion pre-filter before YOLO | P2 | L | Frigate NVR | 90% inference reduction |
| 252 | Frigate-style review timeline in video panel | P1 | L | Frigate NVR | Browsable event timeline |
| 253 | OpenMCT domain object model for panels | P3 | XL | NASA OpenMCT | Rich plugin system |
| 254 | Grafana-style JSON layout serialization | P1 | M | Grafana | Already have LayoutManager |
| 255 | Uptime Kuma notification providers | P2 | L | Uptime Kuma | Push notifications |
| 256 | HA-style MQTT auto-discovery | P2 | M | Home Assistant | Auto-register new devices |
| 257 | SharpAI gallery probe/match UI | P2 | L | SharpAI | Side-by-side face match |
| 258 | Cockpit WS channel multiplexing | P3 | L | Cockpit | Single WS, typed channels |
| 259 | RTS mini-map with fog (Screeps-style) | P1 | L | Screeps | Canvas minimap |
| 260 | Kill feed overlay (Overwatch-style) | P0 | M | FPS games | Left-side scrolling feed |
| 261 | OpenSearch RCF anomaly detection | P3 | XL | OpenSearch | Automated pattern detection |
| 262 | Multi-frame GenAI analysis (not single snapshot) | P2 | L | Frigate NVR | Send 3-5 frames to LLM |

---

## Summary

| Category | Count | P0 | P1 | P2 | P3 |
|----------|-------|----|----|----|----|
| Panel System | 27 | 3 | 10 | 8 | 6 |
| Map & Tactical | 28 | 3 | 8 | 10 | 7 |
| Combat & Game | 25 | 3 | 8 | 6 | 8 |
| Audio & Sound | 18 | 3 | 5 | 5 | 5 |
| Accessibility | 16 | 2 | 5 | 6 | 3 |
| Layout & Workspace | 15 | 3 | 5 | 3 | 4 |
| Data Visualization | 20 | 0 | 4 | 10 | 6 |
| Amy AI Commander | 16 | 2 | 4 | 5 | 5 |
| Search & Intel | 18 | 1 | 7 | 5 | 5 |
| Video Playback | 14 | 0 | 5 | 4 | 5 |
| Mobile & Responsive | 12 | 1 | 3 | 5 | 3 |
| Theming & Visual | 15 | 0 | 6 | 5 | 4 |
| Performance | 14 | 1 | 5 | 6 | 2 |
| Testing & Quality | 12 | 1 | 5 | 5 | 1 |
| Landscape Adoptions | 12 | 1 | 3 | 4 | 4 |
| **TOTAL** | **262** | **24** | **83** | **87** | **68** |

### Current Panel Coverage (12 panels)

| Panel | Keyboard | API Endpoints Covered |
|-------|----------|-----------------------|
| Amy | 1 | /api/amy/status, /api/amy/sensorium, /api/amy/thoughts SSE |
| Units | 2 | sim_telemetry WS, /api/amy/simulation/targets |
| Alerts | 3 | escalation_change WS, detection WS |
| Game HUD | 4 | game_state WS, /api/game/* |
| Mesh | 5 | /api/mesh/* |
| Camera Feeds | 6 | /api/synthetic/cameras/* |
| Audio | 7 | /api/audio/effects/* |
| Zones | 8 | /api/zones/* |
| Scenarios | 9 | /api/scenarios/* |
| Intel (Search) | 0 | /api/search/* |
| Recordings (Videos) | -- | /api/videos/* |
| System | -- | /api/cameras/*, /api/discovery/*, /api/telemetry/* |

### Still Uncovered API Endpoints

| Endpoint | Suggested Panel |
|----------|----------------|
| POST /api/amy/chat | Chat panel or Amy panel enhancement |
| POST /api/amy/command | Amy panel command input |
| GET /api/amy/nodes/{id}/video | Camera Feeds panel enhancement |
| POST /api/ai/analyze | System panel or dedicated AI panel |
| GET /api/assets/* | Asset library panel (new) |
| GET /api/tts/* | Audio panel enhancement |
| GET /api/geo/* | Map settings panel |
