# TRITIUM-SC Control Reference

Complete reference for all keyboard and gamepad controls.

## Quick Reference

| Action | Keyboard | Gamepad |
|--------|----------|---------|
| Navigate | Arrow keys / Tab | D-Pad / Left Stick |
| Select | Enter / Click | A Button |
| Back | ESC | B Button |
| Context Menu | Right Click | X Button |
| Secondary Action | Varies | Y Button |
| Previous View | - | LB |
| Next View | - | RB |
| Help | ? | SELECT/BACK |

---

## Keyboard Shortcuts

### Global Shortcuts

These work from any view:

| Key | Action |
|-----|--------|
| `G` | Switch to Grid View |
| `P` | Switch to Player View |
| `D` | Switch to 3D Property View |
| `Z` | Switch to Zones View |
| `T` | Switch to Targets Gallery |
| `A` | Switch to Assets Control |
| `N` | Switch to Analytics View |
| `Y` | Switch to Amy View |
| `W` | Switch to War Room |
| `S` | Switch to Scenarios View |
| `/` | Focus search input |
| `ESC` | Close modal / Cancel action |
| `?` | Show controls help overlay |

### Grid View (G)

| Key | Action |
|-----|--------|
| `1` | Single camera (1x1) |
| `2` | 2x2 grid |
| `3` | 3x3 grid |
| `Enter` | Select focused camera |
| `Arrow keys` | Navigate cameras |

### Player View (P)

| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `Left` | Seek backward 10 seconds |
| `Right` | Seek forward 10 seconds |
| `Up` | Volume up |
| `Down` | Volume down |
| `F` | Toggle fullscreen |
| `M` | Mute / Unmute |
| `A` | Toggle detection annotations (bounding boxes) |
| `N` | Play next video |
| `B` | Play previous video |
| `<` | Decrease playback speed |
| `>` | Increase playback speed |
| `0-9` | Seek to percentage (0=0%, 5=50%, etc.) |

### 3D View (D)

| Key/Action | Description |
|------------|-------------|
| `Click + Drag` | Orbit camera |
| `Scroll` | Zoom in/out |
| `Click` | Select camera/object |
| `Double Click` | Open camera in list view |
| `Right Click` | Context menu on detection |

### Zones View (Z)

| Key | Action |
|-----|--------|
| `Enter` | Edit selected zone |
| `Delete` | Delete zone (with confirmation) |
| `N` | New zone (start drawing) |

### Targets View (T)

| Key | Action |
|-----|--------|
| `Enter` | View target details |
| `S` | Find similar targets |
| `L` | Label target |
| `Arrow keys` | Navigate gallery |

### Assets View (A)

| Key | Action |
|-----|--------|
| `Enter` | Select asset / Execute task |
| `R` | Recall selected asset |
| `E` | Emergency stop |
| `Arrow keys` | Navigate asset list |

### Analytics View (N)

| Key | Action |
|-----|--------|
| `Arrow keys` | Navigate stat cards |
| `Enter` | Drill down |

### Amy View (Y)

| Key | Action |
|-----|--------|
| `Enter` | Send chat message |
| `Arrow keys` | Navigate panels |

### War Room (W)

| Key | Action |
|-----|--------|
| `O` | Observe mode (read-only) |
| `T` | Tactical mode (select + dispatch) |
| `S` | Setup mode (place/remove assets) |
| `Click` | Select target |
| `Shift+Click` | Add/remove target from selection |
| `Click + Drag` | Box select (friendlies only) |
| `Shift+Drag` | Add to existing selection |
| `Right Click` | Dispatch selected friendlies to location |
| `Middle Click/Alt+Drag` | Pan camera |
| `Scroll` | Zoom in/out (cursor-centered) |
| `Double Click` | Center + zoom on target |
| `Tab` | Cycle through all targets |
| `Space` | Center camera on selection |
| `Escape` | Cancel placement / Deselect all |
| `Delete` | Remove selected asset (Setup mode) |
| `Minimap Click` | Pan camera to minimap location |

Note: `S`, `T`, and `O` keys are intercepted by the War Room for mode
switching. Use sidebar tabs or gamepad LB/RB to navigate away from the War Room.

---

## Gamepad Controls

### Supported Controllers

- Xbox controllers (recommended)
- 8BitDo controllers (in xinput mode)
- PlayStation DualShock/DualSense
- Any standard Gamepad API compatible controller

### Button Layout

```
              [LB]                    [RB]
              [LT]                    [RT]

    ┌───────┐                              ┌───────┐
    │ D-PAD │                              │  (Y)  │
    │   ↑   │                              │(X) (B)│
    │ ←   → │        [SEL]  [START]        │  (A)  │
    │   ↓   │                              └───────┘
    └───────┘

       [L-STICK]                      [R-STICK]
         [L3]                           [R3]
```

### Global Controls

| Button | Action |
|--------|--------|
| D-Pad | Navigate (up/down/left/right) |
| Left Stick | Navigate / Scroll |
| A | Confirm / Select |
| B | Back / Cancel |
| X | Context menu |
| Y | Secondary action |
| LB | Previous view |
| RB | Next view |
| LT | Page up / Jump back |
| RT | Page down / Jump forward |
| SELECT | Show controls overlay |
| START | Main menu |
| L3 (press left stick) | Toggle sidebar |
| R3 (press right stick) | Reset view |

### View-Specific Controls

#### Grid View

| Button | Action |
|--------|--------|
| D-Pad | Navigate between cameras |
| A | Select / Fullscreen camera |
| Y | Quick playback (last hour) |
| X | Camera context menu |
| Left Stick | Scroll if more cameras than visible |

#### Player View

| Button | Action |
|--------|--------|
| D-Pad Left/Right | Seek backward/forward 10s |
| D-Pad Up/Down | Volume up/down |
| A | Play / Pause |
| B | Exit to grid |
| Y | Toggle fullscreen |
| X | Playback speed menu |
| LT / RT | Jump -1min / +1min |
| Left Stick | Fine scrub timeline |

#### 3D View

| Button | Action |
|--------|--------|
| Left Stick | Pan camera |
| Right Stick | Orbit / Rotate view |
| D-Pad | Select cameras / Assets |
| A | Select / Focus object |
| B | Deselect / Reset |
| LT / RT | Zoom out / in |
| R3 | Reset view to default |

#### Zones View

| Button | Action |
|--------|--------|
| D-Pad | Navigate zone list |
| A | Edit zone / Select |
| B | Cancel / Close |
| Y | Toggle zone enabled |
| X | Delete zone (with confirm) |
| Right Stick | Pan zone editor canvas |

#### Targets View

| Button | Action |
|--------|--------|
| D-Pad | Navigate target gallery |
| A | View target details |
| B | Close details |
| Y | Label target |
| X | Find similar |
| LB / RB | Filter type (All/People/Vehicles) |
| LT / RT | Page through results |

#### Assets View

| Button | Action |
|--------|--------|
| D-Pad | Navigate asset list |
| A | Select asset / Execute action |
| B | Cancel / Close |
| Y | Quick recall selected asset |
| X | Emergency stop |
| Right Stick | Pan asset map |
| LT / RT | Zoom map |

#### Analytics View

| Button | Action |
|--------|--------|
| D-Pad | Navigate charts / Stats |
| A | Drill down / Select |
| B | Back up |
| LB / RB | Change time range |
| Left Stick | Scroll dashboard |

#### Amy View

| Button | Action |
|--------|--------|
| D-Pad | Navigate panels |
| A | Send chat message / Select |
| B | Close details |
| Left Stick | Scroll thought stream |

#### War Room

| Button | Action |
|--------|--------|
| Left Stick | Pan camera |
| Right Stick | Pan camera (alternative) |
| D-Pad Up/Down | Cycle through targets (prev/next) |
| A | Select nearest target to camera center |
| B | Deselect all targets |
| X | Cycle modes (Observe -> Tactical -> Setup) |
| Y | Center camera on selection |
| LT | Zoom out |
| RT | Zoom in |

---

## Focus Navigation

When using gamepad or keyboard navigation, the currently focused element is highlighted with a cyan glow. Use D-Pad or arrow keys to move focus:

- **Up/Down**: Move focus vertically
- **Left/Right**: Move focus horizontally
- In grid layouts, navigation wraps to next/previous row

### Focus Trapping

When a modal is open, focus is trapped within the modal. Press B or ESC to close and restore previous focus.

---

## Customization

### Deadzone Adjustment

The default stick deadzone is 25%. To adjust, modify `GAMEPAD_DEADZONE` in `frontend/js/input.js`.

### Button Remapping

Button mappings can be customized by modifying the `mapButtonToAction` method in `GamepadHandler` class in `frontend/js/input.js`.

---

## Troubleshooting

### Gamepad Not Detected

1. Ensure controller is connected before loading the page
2. Press any button on the controller to activate it
3. Check browser console for gamepad events
4. Try a different USB port or Bluetooth re-pair

### Input Lag

1. Use wired connection instead of Bluetooth
2. Reduce browser extensions
3. Check for high CPU usage

### Focus Not Visible

1. Ensure CSS is loaded correctly
2. Check for conflicting styles
3. The element may not be focusable (add `data-focusable` attribute)
