# Testing Notes — Known Issues and Workarounds

## Headless Browser Performance

The SC Command Center page is heavy:
- MapLibre GL JS initializes WebGL context
- Three.js loads for 3D overlays
- Multiple CDN resources (fonts, map tiles)
- 91+ panel definitions registered on load
- WebSocket connection attempts

**Impact**: Page load in headless Chromium takes 15-40 seconds. Tests must use generous timeouts.

**Workarounds**:
- Use `wait_until="domcontentloaded"` not `"load"` (DOM ready is faster than all resources)
- Set `timeout=30000` (30s) for navigation
- Wait 5-8 seconds after navigation before interacting
- Use `--disable-gpu` flag in headless mode
- Consider `--disable-web-security` for CDN timeout issues

## Visual Test Architecture

Three layers, each with a clear job:

| Layer | Tool | What it does | When to use |
|-------|------|-------------|-------------|
| **Pixel diffing** | Playwright `toHaveScreenshot()` | Compare screenshots to baselines | Regression detection |
| **Structural analysis** | OpenCV (tritium-lib) | Detect UI elements, find overlaps, validate layout | Structural validation |
| **Semantic validation** | llava/VLM (Ollama) | "Does this look right?" on cropped elements | Spot-check quality |

## Test Discovery Pattern

Tests should discover UI elements dynamically, not hardcode them:
```python
# GOOD: discover what exists
panels = discover_menu_items(page, "WINDOWS")
for panel in panels:
    open(panel)
    screenshot(panel)
    close(panel)

# BAD: hardcoded list
for panel in ["amy", "units", "alerts"]:
    ...
```

This ensures new panels/layers are automatically tested.

## Known Slow Tests

| Test | Time | Reason |
|------|------|--------|
| Window sweep | ~8 min | Opens/closes each of 90+ panels |
| Layer sweep | ~10 min | Toggles each of 50+ layers |
| Layer visibility | ~2 min | Opens layers panel, clicks buttons |
| Integration (tier 9) | ~70s | Full server lifecycle |
| Visual E2E (tier 7) | ~13 min | Three-layer verification |
