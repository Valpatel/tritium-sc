# User Stories — TRITIUM-SC Command Center

> What it actually feels like to use this system, from first launch to full battle.

These stories define the **intended user experience**. Every feature, every panel, every pixel should serve one of these stories. If a feature doesn't appear here, it doesn't belong. If a story describes something that doesn't work yet, that's a bug.

---

## Story 1: First Launch

**As a new operator**, I want to start the system and immediately see something alive.

I clone the repo, run `./setup.sh install && ./start.sh`, and open `http://localhost:8000` in my browser. The page loads in under 2 seconds.

**What I see immediately:**
- A dark, refined interface fills my entire screen. The background is near-black (#0a0a0f) with a subtle cyan grid overlay. It looks like a military command center, not a web dashboard.
- Real satellite imagery of a neighborhood is visible as the map ground layer. I can see actual rooftops, streets, and yards from aerial photography.
- Colored icons are already moving on the map. Green triangles (drones) sweep in wide arcs. Green rounded rectangles (rovers) patrol along streets. Green triangles-pointing-up (turrets) sit stationary at defensive positions.
- A thin header bar shows "TRITIUM-SC" on the left, "SIM" mode badge, a UTC clock ticking, and unit counts: "6 friendly" in green, "0 threats" in amber.
- Three floating panels are open by default:
  - **AMY COMMANDER** (bottom-left): Shows Amy's portrait, her state ("OBSERVING"), and her latest thought scrolling in as I watch. She's thinking: *"Two rovers on perimeter patrol. All sectors quiet. The neighborhood sleeps."*
  - **UNITS** (top-left): A scrollable list of all 6 friendly units with colored badges, health bars, and type icons.
  - **ALERTS** (top-right): Empty for now. No threats detected.
- A minimap in the bottom-right corner shows a zoomed-out overview with colored dots.
- A status bar at the very bottom shows: FPS, "6 alive", "0 threats", "ONLINE" with a green dot.

**What I do next:**
- I scroll my mouse wheel to zoom in. The map zooms smoothly toward my cursor. Street details become visible. I can see individual houses.
- I click a green rover icon. A pulsing cyan ring appears around it. The Units panel highlights "Rover Alpha" with its details: health 100%, heading 045, speed 2.0 m/s, battery 94%.
- I right-click somewhere on the map. A dashed cyan arrow appears from the rover to where I clicked — the rover changes course and heads toward that point.
- I press `?`. A help overlay appears with all keyboard shortcuts.
- I press `Escape` to close it. I press `C` and a chat panel slides out from the right. I type "Amy, what's the situation?" and she responds with a brief tactical summary.

**What I feel:** This is alive. Things are moving without me doing anything. Amy is thinking on her own. The units patrol on their own. I'm not operating a dashboard — I'm observing a living system.

---

## Story 2: Setting Up My Neighborhood

**As an operator configuring for my actual location**, I want to set the map to my real address so the satellite imagery matches my property.

I open the browser console (or eventually a settings panel) and call:
```
POST /api/geo/geocode-and-set-reference { "address": "123 Oak Street, Springfield, IL" }
```

The map immediately updates. Real ESRI satellite tiles of my actual neighborhood load as the ground layer. I can see my house, my driveway, my neighbor's fence. The simulation units are now patrolling over real aerial imagery of my street.

I zoom in close. At high zoom (level 19), I can see individual cars in driveways. The grid overlay shifts to 5-meter squares. I can place turrets at specific locations on my actual property — the front gate, the side yard, the roof corner.

The coordinate display in the bottom-left shows real-world meters from my house center. When I hover over a unit, I can see its position as both game coordinates and GPS lat/lng.

**What matters:** The simulation is grounded in reality. These aren't abstract dots on a black canvas — they're defenders positioned at real locations on my actual property, seen from space.

---

## Story 3: Playing a Full Battle

**As a player**, I want to fight a 10-wave Nerf battle and feel like I'm commanding a real-time strategy game.

### Setup Phase

I press `4` to open the Game HUD panel. It shows "PHASE: SETUP" and a prominent **[ BEGIN WAR ]** button. I press `S` to enter Setup mode.

I click on the map where I want to place a turret. A ghost turret appears under my cursor with a translucent weapon range circle showing its 20-meter coverage. I click to confirm placement. The turret materializes with a satisfying audio cue. I place two more turrets at choke points and a drone for mobile response.

I can see the pre-existing patrol units from the default layout — rovers sweeping the perimeter, a scout drone on the east flank. My new placements complement the existing force.

I review the Units panel. 9 friendlies total. Health bars all green. I'm ready.

### Countdown

I press `B` (or click BEGIN WAR). The button disappears. A massive "5" appears center-screen in bold mono text. Amy shouts through the speakers (and the announcement bar): **"FIVE!"** The number counts down. **"FOUR!"** **"THREE!"** **"TWO!"** **"ONE!"**

**"ALL UNITS — WEAPONS FREE!"**

The game score HUD appears in the header: Wave 1 / Score 0 / Eliminations 0.

### Wave 1: Scout Party (3 hostiles)

Three red diamond icons appear at the map edges — hostile kids with Nerf blasters. They move inward along waypoint paths. Amy announces: **"WAVE ONE: Scout Party! 3 hostiles incoming!"**

My nearest turret rotates toward the first hostile. A nerf dart projectile streaks across the map — a small animated dot with a fading trail. It connects. The hostile's health bar drops. Another shot. **ELIMINATED.** The hostile icon fades and gets an X overlay. A toast notification says "Turret NW takes down Intruder Alpha!"

The kill feed appears: short text entries stacking in the corner, each showing who killed whom. Score jumps to 100.

Two more hostiles fall. **"WAVE ONE COMPLETE! 3 eliminated!"** A brief wave-complete banner sweeps across the screen. Score bonus: +200.

### Wave 5: Blitz Attack (10 hostiles)

By wave 5, things are intense. 10 hostiles rush in at 1.3x speed. Projectile trails crisscross the map. My turrets are firing continuously — I can see their cooldown arcs resetting between shots.

Amy calls out: **"TURRET SE IS ON A STREAK! THREE ELIMINATIONS!"**

I right-click to dispatch a rover toward a breach in the south where hostiles are slipping past my turret coverage.

A drone takes damage. Its health bar turns yellow, then orange. I can see it's at 40% health. It keeps fighting — drones are fragile but fast.

**"RAMPAGE! TURRET NW WITH FIVE ELIMINATIONS!"**

The minimap shows the battle at a glance — green dots clustered at my defensive positions, red dots streaming in from the edges, some red dots blinking as they take hits.

### Wave 10: FINAL STAND (25 hostiles)

This is chaos. 25 hostile kids, 2x health, 1.5x speed. They flood in from every direction. Multiple turrets are under fire simultaneously. A rover goes down — **"Rover Bravo has been eliminated!"** — its icon turns grey with an X.

Amy is shouting rapid-fire announcements. The kill feed scrolls continuously. Projectiles everywhere.

**"GODLIKE! TURRET NW WITH TEN ELIMINATIONS!"**

The last hostile falls. A brief pause — then the victory overlay:

```
╔══════════════════════════════════════╗
║          V I C T O R Y               ║
║   NEIGHBORHOOD SECURED               ║
║                                      ║
║   Final Score:  12,450               ║
║   Waves:        10/10                ║
║   Eliminations: 107                  ║
║                                      ║
║        [ PLAY AGAIN ]               ║
╚══════════════════════════════════════╝
```

I press PLAY AGAIN. Everything resets. My turrets are healed. Dead units respawn. I'm back in setup mode, ready to try a different strategy.

**What I feel:** That was an RTS game. Not a tech demo. Real combat with projectile physics, tactical positioning, AI commentary, and victory or defeat. I want to play again with different turret placement.

---

## Story 4: Amy as Companion

**As an operator**, I want Amy to feel like a real presence — not a chatbot behind a button.

I'm watching the tactical map during a quiet patrol period. No threats. The Amy panel shows her state cycling between OBSERVING and THINKING.

Toast notifications appear every few seconds with Amy's inner thoughts:
- *"Mrs. Henderson walking her dog again. Same route as yesterday."*
- *"All perimeter sensors nominal. Wind picking up from the west."*
- *"Rover Alpha's battery at 73%. Should return to charge within the hour."*

These thoughts float in from the top-right as small cyan-bordered cards, visible for 6 seconds, then fade. They don't interrupt my view of the map — they overlay it.

I press `C` to open the chat panel. It slides in from the right, semi-transparent so I can still see the map behind it. I type: "Amy, have you seen anything unusual today?"

Amy responds, referencing things she's actually observed through her cameras and sensorium:
*"Nothing out of the ordinary. The mail carrier came at 14:22. Two vehicles passed through — the regular red sedan and an unfamiliar white van. I tracked the van for 45 seconds before it left the area. The jogger did their usual loop at 15:10."*

I ask: "Keep an eye on white vans." Amy acknowledges and sets an internal goal.

Later, a hostile spawns. Amy's panel border flashes yellow, then red. Her state changes to ALERT. A toast appears in red:
*"Hostile detected! Northeast sector. Dispatching nearest unit."*

Without me doing anything, Amy has already dispatched Rover Alpha toward the hostile. A dispatch arrow appears on the map. Amy announces on the audio channel: **"Contact! Northeast sector! Rover Alpha, intercept!"**

**What I feel:** Amy is a colleague, not a tool. She's watching when I'm not. She remembers things. She acts on her own judgment. I trust her to handle routine situations.

---

## Story 5: The Living Neighborhood

**As an observer**, I want to see a neighborhood that feels alive even when no battle is happening.

It's a weekday afternoon simulation. No game running. The map shows:

- **Mrs. Henderson** (blue circle, neutral) walking her dog along the north sidewalk. A small name label floats above her icon.
- **The Red Sedan** (blue car icon) driving east on the main road at 8 m/s.
- **Amazon Delivery** (blue person icon) walking from the road to a house, pausing for 20 seconds, then walking back.
- **Mr. Kowalski** (blue circle) working in his yard — position barely changes.
- A **Golden Retriever** (blue dot) wandering around a backyard.

My friendly units coexist with these civilians:
- Rovers patrol the perimeter, green routes visible as fading trails.
- A turret sits stationary at the front gate, its heading slowly tracking the nearest moving entity.
- A drone circles high over the property.

The ambient population changes through the day. In the morning, more foot traffic and deliveries. In the evening, dog walkers and joggers. At 3 AM, almost nothing — just one rover on patrol and the cameras watching empty streets.

If I switch to the legacy War Room view (press `W` from `index.html`), I see fog of war darkening areas outside unit vision ranges. Hostiles could be hiding in the fog. This creates natural tension even without a game running.

**What I feel:** This neighborhood is alive. The simulation isn't just a combat arena — it's a living world with patterns, routines, and surprises.

---

## Story 6: Panel Management

**As a power user**, I want to arrange my workspace and have it persist.

I press `1` through `4` to toggle panels on and off. Each panel appears as a floating window that I can:
- **Drag** by the header to any position
- **Resize** by the bottom-right corner handle
- **Minimize** to just the header bar (collapse button)
- **Close** with the X button (hides it, doesn't destroy — I can reopen with the number key)

I arrange my panels: Amy bottom-left, Units top-left, Game HUD top-right. I close Alerts (I'll reopen it when threats appear).

I close the browser and come back later. My panel layout is exactly as I left it — positions, sizes, which panels are open and closed. All saved to localStorage.

If I want a fresh start, I open the console and call `panelManager.applyPreset('commander')` — panels snap to pre-defined positions optimized for active command. Or `'observer'` for minimal panels, or `'tactical'` for unit-focused layout.

**What matters:** The panel system is my workspace. It adapts to how I work, not the other way around.

---

## Story 7: Robot Integration

**As a hardware builder**, I want to connect my real robot and see it appear on the tactical map alongside simulated units.

I've built a Raspberry Pi rover with a USB camera and a motor controller. I flash it with the robot-template from `examples/robot-template/`. I edit `config.yaml`:

```yaml
robot_id: my-pi-rover
site_id: home
mqtt_host: 192.168.1.50
mqtt_port: 1883
hardware:
  type: raspberry_pi  # my custom hardware module
thinker:
  enabled: true
  model: qwen2.5:3b
  ollama_host: http://192.168.1.50:11434
```

I start the robot: `python robot.py`. It connects to the MQTT broker.

On the tactical map, a new green rover icon appears at position (0, 0). As my physical robot drives around (GPS → game coordinates), its icon moves on the map in real-time. Its battery level, heading, and speed update live.

The robot's onboard camera runs YOLO. When it spots a person, the detection appears in Amy's awareness. Amy's sensorium now includes: *"My-Pi-Rover reports a person detected at bearing 270, range 8 meters."*

If I enabled the thinker, the robot also thinks autonomously. Toast notifications in green borders show the robot's thoughts:
- *"Interesting. Person approaching from the west. Should I investigate?"*
- *"Battery at 64%. I should think about returning to base soon."*

The robot is indistinguishable from a simulated rover in Amy's view. Same tracker, same sensorium, same WebSocket telemetry. She dispatches it alongside her virtual units.

**What I feel:** My physical robot just joined the game. Same interface, same protocols. Real and virtual are peers.

---

## Story 8: Observing From Across the Room

**As a casual observer**, I want to glance at a screen on the wall and understand the situation instantly.

I have TRITIUM-SC running on a TV in my home office. I'm working at my desk. I glance up.

**In 2 seconds I know:**
- Green dots are moving on familiar satellite imagery — all friendlies patrolling normally.
- "0 threats" in amber in the header. All clear.
- Amy's latest thought in the bottom-left corner: something mundane about weather.

**If something happens:**
- A red dot appears. The header changes: "1 THREAT" in red.
- Amy's panel border flashes red.
- A red toast notification appears at the top.
- If audio is on, Amy's voice says: "Contact! Hostile approaching from the south!"
- Even across the room, the shift from all-green to red-alert is instantly visible.

**What matters:** The interface communicates state through color and spatial patterns, not text. Green = safe. Red = danger. Moving = alive. Static = dead. I don't need to read anything.

---

## Story 9: The Developer Loop

**As a developer**, I want to change code and verify it works without manual testing.

I make a change to `frontend/js/command/map.js`. I want to know if I broke anything.

```bash
# Quick check (60 seconds): syntax + unit tests + JS tests + infra
./test.sh fast

# Just the JS tests (5 seconds)
./test.sh 3

# Integration tests against a live server (70 seconds)
./test.sh 9

# Visual quality check of Command Center (requires server + Playwright)
./test.sh 10

# Everything including visual E2E (15 minutes)
./test.sh all
```

For Python backend changes:
```bash
# Unit tests for a specific module
.venv/bin/python3 -m pytest tests/amy/test_combat.py -v

# All unit tests
.venv/bin/python3 -m pytest tests/amy/ -m unit -v
```

For visual changes, I open `http://localhost:8000` in my browser and look at it. Then I take a screenshot and check it against the user stories above. Does it look like what Story 1 describes? If not, it's wrong.

**What matters:** The test suite runs in 60 seconds for fast iteration. Visual changes require human eyes (or llava for automated visual regression). The user stories are the spec — if the screen doesn't match the story, the code is wrong.

---

## Story 10: Parallel Agent Development

**As a Claude Code instance**, I want to work on one part of the system without breaking another.

The codebase is structured for parallel agent work:

| Agent Focus | Owns | Can Read | Test Command |
|------------|------|----------|--------------|
| Backend | `src/amy/`, `src/app/` | Everything | `./test.sh 2` |
| Frontend map | `frontend/js/command/map.js` | `frontend/`, `app/routers/` | `./test.sh 3` |
| Frontend panels | `frontend/js/command/panels/` | `frontend/`, store.js, events.js | `./test.sh 3` |
| Frontend CSS | `frontend/css/` | `frontend/` | `./test.sh 3` |
| Tests | `tests/` | Everything | `./test.sh fast` |

**Rules:**
1. One agent, one focus area. Read anything, edit only your files.
2. Run `./test.sh fast` after every change. If it breaks, fix it before moving on.
3. Don't create new files unless absolutely necessary. Edit existing files.
4. The user stories above are the spec. If you're not sure what something should look like, read the stories.

---

## What "Done" Looks Like

A feature is done when:

1. **Story match**: A human can perform the user story and it works as described.
2. **Tests pass**: `./test.sh fast` passes with zero regressions.
3. **Visual check**: Opening `http://localhost:8000` in a browser shows what the stories describe.
4. **No dead features**: Every button does something. Every keyboard shortcut works. Every panel contains real data.

A feature is NOT done when:
- Tests pass but the screen shows a dark void with dots
- Agents edited files but nobody opened a browser
- Code was written but never executed
- Panels exist but contain placeholder text
- Keyboard shortcuts are documented but don't work
