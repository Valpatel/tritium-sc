# TRITIUM-SC Gamepad Guide

Complete guide for setting up and using gamepad controllers with TRITIUM-SC.

## Supported Controllers

TRITIUM-SC uses the standard Web Gamepad API, supporting most modern controllers:

### Fully Tested

| Controller | Connection | Notes |
|------------|------------|-------|
| Xbox One Controller | USB / Bluetooth | Recommended, native support |
| Xbox Series X/S Controller | USB / Bluetooth | Recommended, native support |
| 8BitDo Pro 2 | USB / Bluetooth | Use xinput mode (START+X) |
| 8BitDo SN30 Pro+ | USB / Bluetooth | Use xinput mode |

### Should Work

| Controller | Connection | Notes |
|------------|------------|-------|
| PlayStation DualShock 4 | USB / Bluetooth | May need DS4Windows on Windows |
| PlayStation DualSense | USB / Bluetooth | Native in Chrome/Edge |
| Nintendo Switch Pro Controller | USB / Bluetooth | May need driver |
| Generic USB Gamepads | USB | Mapping may vary |

---

## Quick Start

### 1. Connect Your Controller

**USB**: Simply plug in. The controller should be detected immediately.

**Bluetooth**:
1. Put controller in pairing mode
2. Pair via your operating system's Bluetooth settings
3. Once paired, controller is ready

### 2. Open TRITIUM-SC

1. Navigate to http://localhost:8000 (or your server URL)
2. Press any button on the controller to activate it
3. You should see a "Gamepad Connected" notification
4. The gamepad indicator in the bottom-right shows connection status

### 3. Basic Navigation

- **D-Pad**: Move between elements
- **A Button**: Select/Confirm
- **B Button**: Back/Cancel
- **SELECT**: Show controls overlay

---

## Controller Setup by Type

### Xbox Controllers

Xbox controllers work natively on most systems.

**Windows**: Native support, no additional drivers needed.

**Linux**: Install `xboxdrv` or `xpad` driver:
```bash
# Ubuntu/Debian
sudo apt install xboxdrv

# Or use xpad kernel module
sudo modprobe xpad
```

**macOS**: Native Bluetooth support in macOS 11+. For older versions, use [360Controller](https://github.com/360Controller/360Controller).

### 8BitDo Controllers

8BitDo controllers support multiple modes. For TRITIUM-SC, use **xinput mode**:

1. Turn off the controller
2. Hold **START + X** while turning on
3. LED should show the xinput pattern (depends on model)
4. Connect via USB or Bluetooth

**Mode Reference**:
| Mode | Hold on startup | LED pattern |
|------|-----------------|-------------|
| xinput (Xbox) | START + X | Usually solid |
| dinput (generic) | START + B | Usually blinking |
| Switch | START + Y | Varies |
| macOS | START + A | Varies |

### PlayStation Controllers

**DualShock 4**:
- Chrome/Edge: Native support on macOS, Linux. Windows may need [DS4Windows](https://ds4-windows.com/)
- Firefox: May have limited support

**DualSense (PS5)**:
- Chrome 89+: Native support
- Requires Bluetooth 4.0+ for wireless

---

## Calibration

TRITIUM-SC includes automatic deadzone handling, but you may need to adjust for your controller.

### Testing Your Controller

1. Connect controller
2. Open browser developer tools (F12)
3. Go to Console tab
4. Type: `navigator.getGamepads()` and press Enter
5. Move sticks and press buttons to see values

### Adjusting Deadzone

The default deadzone is 25% (0.25). To change:

1. Open `frontend/js/input.js`
2. Find `const GAMEPAD_DEADZONE = 0.25;`
3. Adjust value (0.1 = 10%, 0.3 = 30%)
4. Refresh the page

**Signs you need to adjust**:
- Stick drift (cursor moves without touching): Increase deadzone
- Unresponsive sticks: Decrease deadzone

---

## Vibration / Haptic Feedback

TRITIUM-SC uses vibration for feedback on certain actions:
- Controller connected: Short vibration
- Selection confirmed: Brief pulse

**Enable/Disable Vibration**:
Currently always enabled when supported. To disable, modify the `vibrate()` method in `frontend/js/input.js`.

**Not Working?**
- Not all controllers support vibration via Web API
- Some browsers (Firefox) have limited vibration support
- Bluetooth connections may have less reliable vibration

---

## Troubleshooting

### Controller Not Detected

1. **Press a button first**: Browsers require user interaction to detect gamepads
2. **Refresh the page**: Try refreshing after connecting controller
3. **Check other apps**: Make sure no other application is monopolizing the controller
4. **Try different browser**: Chrome typically has best support
5. **Check permissions**: Some browsers require gamepad permission

**Debug in Console**:
```javascript
// Check if Gamepad API is supported
console.log('Gamepad API supported:', 'getGamepads' in navigator);

// List connected gamepads
console.log(navigator.getGamepads());

// Listen for connections
window.addEventListener('gamepadconnected', (e) => {
    console.log('Gamepad connected:', e.gamepad.id);
});
```

### Wrong Button Mapping

Different controllers may have different button indices. The standard mapping is:

| Index | Xbox | PlayStation | 8BitDo |
|-------|------|-------------|--------|
| 0 | A | Cross | A |
| 1 | B | Circle | B |
| 2 | X | Square | X |
| 3 | Y | Triangle | Y |
| 4 | LB | L1 | LB |
| 5 | RB | R1 | RB |
| 6 | LT | L2 | LT |
| 7 | RT | R2 | RT |
| 8 | Back/View | Share | Select |
| 9 | Start/Menu | Options | Start |
| 10 | L3 | L3 | L3 |
| 11 | R3 | R3 | R3 |
| 12 | D-Up | D-Up | D-Up |
| 13 | D-Down | D-Down | D-Down |
| 14 | D-Left | D-Left | D-Left |
| 15 | D-Right | D-Right | D-Right |

If your controller has different mapping, modify `GAMEPAD_BUTTONS` in `frontend/js/input.js`.

### Input Lag

1. **Use wired connection**: Bluetooth adds latency
2. **Close other tabs**: Browser performance affects input responsiveness
3. **Reduce refresh rate**: The polling interval is 16ms (~60fps). Increase if needed:
   ```javascript
   const GAMEPAD_POLL_INTERVAL = 32; // ~30fps
   ```
4. **Check monitor refresh**: High refresh rate monitors may show lag more noticeably

### Stick Drift

If your sticks register input without being touched:

1. **Increase deadzone**: Set `GAMEPAD_DEADZONE = 0.3` or higher
2. **Calibrate in OS**: Use your operating system's controller calibration
3. **Controller issue**: May indicate hardware wear

### Multiple Controllers

TRITIUM-SC currently supports one controller at a time (first connected). To switch controllers:

1. Disconnect current controller
2. Connect new controller
3. Refresh page if needed

---

## Browser Compatibility

| Browser | Support Level | Notes |
|---------|---------------|-------|
| Chrome 21+ | Full | Recommended |
| Edge (Chromium) | Full | Recommended |
| Firefox 29+ | Good | Vibration limited |
| Safari 10.1+ | Basic | Limited button support |
| Opera 15+ | Full | Same as Chrome |

### Mobile Browsers

Gamepad API is generally not available on mobile browsers, even when controllers are connected via Bluetooth.

---

## Security Notes

- Gamepad API requires secure context (HTTPS) or localhost
- No special permissions needed (unlike webcam/microphone)
- Gamepad data is not accessible until user presses a button (privacy protection)

---

## Further Reading

- [MDN Gamepad API](https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API)
- [Gamepad Tester](https://gamepad-tester.com/) - Test your controller online
- [HTML5 Gamepad Spec](https://w3c.github.io/gamepad/)
