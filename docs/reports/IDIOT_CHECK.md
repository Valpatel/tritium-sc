# VILLAGE IDIOT REPORT -- 2026-03-23

**Persona**: Greg Holloway, 54, building manager at a mid-size office complex. Tech skill 2/5. Was told this software could help him monitor his parking lot and lobby. Expects something like his Ring doorbell app. Military acronyms and "tactical" language confuse him. Does not know what MQTT or a "dossier" is.

## Summary Scorecard

```
WEBSITE: works
MAP: visible -- satellite imagery, loads fast, no tile errors
TARGETS ON MAP: yes -- 70 markers appeared after demo started (colored military-style icons)
CLICKING: targets are clickable -- Unit Inspector panel opens with full details
DEMO MODE: started via API, markers appeared within 10 seconds, map auto-panned
APIs: 5 of 5 returned data (targets, fleet, readiness, plugins, dossiers)
JS ERRORS: 0

Loop 1 (First Boot): 6/8 PASS -- SIM menu is empty (BROKEN), header stats confusing
```

---

## Loop 1: First Boot -- "What am I looking at?"

| Step | Expected | Result |
|------|----------|--------|
| 1. Navigate to localhost:8000 | Page loads | PASS -- loads in ~3 seconds |
| 2. See tactical map with satellite imagery | Satellite visible | PASS -- clean satellite view of a neighborhood |
| 3. Understand the UI | Header, map, menu bar | PARTIAL -- header exists but stats are confusing ("0 units / 3 threats / 3 targets" -- what?) |
| 4. Open WINDOWS menu | Browse panels | PASS but OVERWHELMING -- 80+ items in one dropdown |
| 5. Start demo (SIM > Start Demo) | Demo starts | FAIL -- SIM menu dropdown is EMPTY. No Start Demo button visible. |
| 6. See targets appear | Markers on map | PASS (via API workaround) -- 70 markers appeared |
| 7. Click a target | See details | PASS -- Unit Inspector opens showing "Intruder Hotel-2" |
| 8. See target info | Name, type, position | PASS -- name, type, alliance, position, speed, health |

---

## OBVIOUS PROBLEMS

1. **SIM MENU IS EMPTY.** Clicking "SIM" in the menu bar produces NO dropdown. The welcome tooltip says "Click SIM > Start Demo" but the SIM menu literally shows nothing when clicked. The only way to start demo mode is via API (curl POST) or a keyboard shortcut nobody told Greg about. This is the single biggest UX failure -- the product's own instructions point to a broken menu.

2. **WINDOWS MENU IS OVERWHELMING.** There are 80+ items in a single giant dropdown. Categories exist (Operations, Intel, Sensing, Communications, Commander, Map, Simulation, System, Other) but the list is a wall of text. Greg would close the browser immediately. Nobody needs 80 options on first load.

3. **WELCOME TOOLTIP NEVER GOES AWAY.** The cyan "WELCOME TO TRITIUM" box sits at the bottom center of the screen permanently. After demo starts, after clicking targets, after opening panels -- still there. Has a small "Dismiss" button Greg might not notice.

4. **FLOATING BATTLE TEXT ON MAP.** After some time, large cyan glitch-styled text appears floating on the satellite map: "Hostile confirmed! Unknown contact is a threat!" and "We have a confirmed hostile -- Unknown contact!" The text is huge, overlaps everything, and Greg thinks the software is crashing.

5. **HEADER BAR STATS ARE CONFUSING.** Shows "0 units | 3 threats | 3 targets" with colored badges. Greg doesn't know the difference between a "unit" and a "target." Numbers changed during the session with no explanation.

6. **UNIT INSPECTOR USES MILITARY JARGON.** Clicking a target shows "FSM STATE: ADVANCING", "ALLIANCE: HOSTILE", coordinates like "(-306.6, 210.1)". Greg does not know what FSM means. He wants "Person walking north" not "PERSON / HOSTILE / ADVANCING."

7. **BRIGHT CYAN CAMERA FOV LINES.** Bright cyan lines stretch across the entire map from corner to corner. They look like laser beams. Greg thinks something is broken. Probably camera field-of-view cones but visually dominating.

---

## MENUS TESTED

| Menu | Works? | Contents |
|------|--------|----------|
| WINDOWS | YES | 80+ items in 9 categories (Operations, Intel, Sensing, Communications, Commander, Map, Simulation, System, Other) |
| SIM | BROKEN | Dropdown is EMPTY -- nothing appears |
| MAP | YES | Layers toggle (Satellite, Buildings, Roads, Trees, Water, etc.), Grid, Unit Markers, Fog of War, 3D Mode, Zoom controls |
| LAYOUT | YES | 4 presets: Commander, Observer, Tactical, Battle, plus "Save Current..." |

---

## 5 API Endpoint Checks

| Endpoint | Result |
|----------|--------|
| `/api/targets` | 2 targets (much less than 70 on map -- simulation targets use different path?) |
| `/api/fleet/devices` | Demo device "Alpha-Node" with battery 87.6%, uptime, sensor counts |
| `/api/system/readiness` | "partially_ready" 4/9 -- MQTT yellow, demo green, auth yellow (disabled) |
| `/api/plugins` | 27 plugins loaded |
| `/api/dossiers` | Dossier list with UUIDs, entity types, threat levels |

APIs: 5/5 returned real data. No 500 errors.

---

## KEYBOARD SHORTCUTS TESTED

| Key | Expected | Result |
|-----|----------|--------|
| J | City Sim | WORKS -- map zoomed out, cyan dots (vehicles/NPCs) appeared across city |
| \ | Protest | WORKS -- floating narration text appeared |
| 1 | Amy panel | WORKS -- Amy Commander panel opened on right side |
| 2 | Units panel | WORKS -- Units panel opened on left side |

---

## THINGS THAT ACTUALLY WORK

1. Map loads fast with real satellite imagery -- no tile errors, looks professional
2. Keyboard shortcuts work reliably (J, \, 1, 2)
3. Clicking a target marker opens Unit Inspector with actual data (name, type, alliance, health, speed)
4. Amy panel opened and shows status information
5. City sim (J key) populated the map with many moving cyan markers
6. Zero JavaScript errors during entire 10+ minute test session
7. All 5 API endpoints returned real data
8. 27 plugins loaded without errors
9. MAP menu has useful layer toggles
10. LAYOUT menu has 4 sensible presets
11. WINDOWS menu has organized categories (9 of them)
12. 70 MapLibre markers rendered and are interactive

---

## MY HONEST IMPRESSION

The map looks really cool and the fact that it loads with real satellite imagery is impressive. But as Greg the building manager, I have no idea what I'm looking at or how to use it. The SIM menu being empty means I literally cannot start the demo without someone telling me a keyboard shortcut or an API command. The WINDOWS menu with 80+ items makes me feel like I accidentally opened a nuclear submarine control panel. The floating battle text on the map makes it look like a video game, not a security tool.

That said -- once someone SHOWED me how to start things and click targets, the interaction actually works. The bones are good. The first-time experience is terrible because the main entry point (SIM menu) is broken and everything else assumes you already know what you're doing.

Compared to previous report (Wave 178): the visual clutter from prediction ellipses and traffic signals seems to be LESS of a problem now -- the default view was clean satellite imagery without the "opaque blob" described last time. The main regression is the SIM menu being completely empty.

---

## Screenshots Saved

- `tests/.baselines/idiot_step1_firstload.png` -- first load, clean satellite map
- `tests/.baselines/idiot_step2_windows_menu.png` -- WINDOWS menu open (overwhelming)
- `tests/.baselines/idiot_step2b_menu_closeup.png` -- WINDOWS menu closeup
- `tests/.baselines/idiot_step3_sim_menu.png` -- SIM menu (nothing visible)
- `tests/.baselines/idiot_step4_after_demo.png` -- after demo start, targets on map
- `tests/.baselines/idiot_step5_click_map.png` -- after clicking on map
- `tests/.baselines/idiot_step6_J_citysim.png` -- city sim active (cyan dots)
- `tests/.baselines/idiot_step6_protest.png` -- protest narration floating text
- `tests/.baselines/idiot_step6_amy.png` -- Amy panel visible
- `tests/.baselines/idiot_click_target.png` -- Unit Inspector with target details
- `tests/.baselines/idiot_menu_map.png` -- MAP menu open
- `tests/.baselines/idiot_menu_layout.png` -- LAYOUT menu open
- `tests/.baselines/idiot_panel_units.png` -- Units panel open
- `tests/.baselines/idiot_panel_amy.png` -- Amy panel open
