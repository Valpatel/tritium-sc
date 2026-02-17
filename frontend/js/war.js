/**
 * TRITIUM-SC War Room
 * Full-screen RTS tactical map view
 * Keyboard shortcut: W
 *
 * ARCHITECTURE
 * -----------
 * Single-file module following the project convention (one JS file per view).
 * At ~1200 lines this is comparable to grid.js (1157) and input.js (1192).
 * Splitting into war-canvas/war-input/war-hud would create three tightly
 * coupled files sharing warState with no real isolation benefit.
 *
 * Rendering: Canvas 2D (not Three.js).  The War Room is a 2D tactical map
 * with simple shapes, lines, and text.  Three.js would add scene-graph
 * overhead for no visual gain; Canvas 2D is purpose-built for this.
 *
 * Data flow: WebSocket -> app.js -> assets.js (updateSimTarget) -> war.js
 * reads from assetState.simTargets via getTargets().  One source of truth,
 * no duplication.  warState holds only War Room UI state (camera, selection,
 * mode, alerts) -- never target data.
 *
 * HUD: HTML divs overlaid on canvas (standard RTS pattern).  Canvas draws
 * the map; HTML provides scrollable logs, clickable palette, proper text
 * rendering.
 *
 * Modes: OBSERVE (read-only monitoring), TACTICAL (select + dispatch),
 * SETUP (place/remove assets).  Maps to RTS phases: spectate/command/build.
 *
 * Sections in this file:
 *   - State & constants
 *   - Coordinate transforms
 *   - Init / Destroy
 *   - Render loop & drawing functions
 *   - Target helpers & hit testing
 *   - Mouse events
 *   - Keyboard
 *   - Dispatch
 *   - Setup mode
 *   - HUD panels (mode, Amy, alerts, unit info, palette)
 *   - Amy speech toast
 *   - WebSocket event handlers (called from app.js)
 *   - Utility
 *   - Global exports
 */

// War Room state
const warState = {
    canvas: null,
    ctx: null,
    // Camera
    cam: { x: 0, y: 0, targetX: 0, targetY: 0, zoom: 1.0, targetZoom: 1.0 },
    // Map bounds (same as simulation: -30 to 30)
    mapMin: -30,
    mapMax: 30,
    // Mode: 'observe' | 'tactical' | 'setup'
    mode: 'observe',
    // Selection
    selectedTargets: [],
    hoveredTarget: null,
    // Box select
    boxSelect: null, // { startX, startY, endX, endY } in screen coords
    // Dispatch arrows (fade after 3s)
    dispatchArrows: [], // { fromX, fromY, toX, toY, time }
    // Alert log
    alertLog: [], // { text, type, time }
    // Setup mode
    setupPalette: null,
    placingAsset: null,
    placingGhost: null, // { type, worldX, worldY } when confirming
    // Interaction
    isDragging: false,
    isPanning: false,
    dragStart: null,
    lastMouse: { x: 0, y: 0 },
    // Animation
    animFrame: null,
    initialized: false,
    // Amy data
    amyThoughts: [],
    amyMood: '--',
    amyState: '--',
    amySpeechToast: null,
    amySpeechTimeout: null,
    // Target cycle index
    cycleIndex: -1,
    // Known target IDs (for new hostile detection)
    knownTargetIds: new Set(),
    // Zones from escalation classifier
    zones: [],
    // Threat records from classifier
    threats: {}, // target_id -> { threat_level, in_zone }
    // Visual effects
    effects: [], // { type, x, y, time, data }
    // Score tracking
    stats: { kills: 0, breaches: 0, dispatches: 0, sessionStart: Date.now() },
    // Audio context (lazy init on first user interaction)
    audioCtx: null,
};

// Setup palette categories
const SETUP_PALETTE = [
    {
        title: 'SENSORS',
        items: [
            { type: 'camera', label: 'Camera' },
            { type: 'ptz_camera', label: 'PTZ Camera' },
            { type: 'dome_camera', label: 'Dome Camera' },
            { type: 'motion_sensor', label: 'Motion Sensor' },
            { type: 'microphone_sensor', label: 'Microphone' },
        ],
    },
    {
        title: 'ROBOTS',
        items: [
            { type: 'patrol_rover', label: 'Patrol Rover' },
            { type: 'interceptor_bot', label: 'Interceptor Bot' },
            { type: 'recon_drone', label: 'Recon Drone' },
            { type: 'heavy_drone', label: 'Heavy Drone' },
        ],
    },
    {
        title: 'INFRASTRUCTURE',
        items: [
            { type: 'sentry_turret', label: 'Sentry Turret' },
            { type: 'speaker', label: 'Speaker' },
            { type: 'floodlight', label: 'Floodlight' },
        ],
    },
];

// Alliance colors
const ALLIANCE_COLORS = {
    friendly: '#05ffa1',
    hostile: '#ff2a6d',
    neutral: '#00a0ff',
    unknown: '#fcee0a',
};

// Threat level colors (escalation ladder)
const THREAT_COLORS = {
    none: null,
    unknown: '#fcee0a',
    suspicious: '#ff9800',
    hostile: '#ff2a6d',
};

// ============================================================
// Audio feedback (Web Audio synth)
// ============================================================

function _getAudioCtx() {
    if (!warState.audioCtx) {
        try {
            warState.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        } catch (e) { /* audio unavailable */ }
    }
    return warState.audioCtx;
}

function warPlaySound(type) {
    const ctx = _getAudioCtx();
    if (!ctx) return;
    try {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);

        const now = ctx.currentTime;
        switch (type) {
            case 'dispatch':
                // Two-tone ascending confirmation
                osc.type = 'sine';
                osc.frequency.setValueAtTime(440, now);
                osc.frequency.setValueAtTime(660, now + 0.08);
                gain.gain.setValueAtTime(0.08, now);
                gain.gain.linearRampToValueAtTime(0, now + 0.2);
                osc.start(now);
                osc.stop(now + 0.2);
                break;
            case 'hostile':
                // Harsh alert ping
                osc.type = 'sawtooth';
                osc.frequency.setValueAtTime(880, now);
                osc.frequency.setValueAtTime(440, now + 0.1);
                gain.gain.setValueAtTime(0.06, now);
                gain.gain.linearRampToValueAtTime(0, now + 0.25);
                osc.start(now);
                osc.stop(now + 0.25);
                break;
            case 'neutralized':
                // Satisfying descending sweep
                osc.type = 'sine';
                osc.frequency.setValueAtTime(880, now);
                osc.frequency.exponentialRampToValueAtTime(220, now + 0.3);
                gain.gain.setValueAtTime(0.1, now);
                gain.gain.linearRampToValueAtTime(0, now + 0.4);
                osc.start(now);
                osc.stop(now + 0.4);
                break;
            case 'zone_violation':
                // Quick double-beep warning
                osc.type = 'square';
                osc.frequency.setValueAtTime(600, now);
                gain.gain.setValueAtTime(0.05, now);
                gain.gain.setValueAtTime(0, now + 0.06);
                gain.gain.setValueAtTime(0.05, now + 0.1);
                gain.gain.linearRampToValueAtTime(0, now + 0.16);
                osc.start(now);
                osc.stop(now + 0.2);
                break;
            case 'place':
                // Soft click
                osc.type = 'sine';
                osc.frequency.setValueAtTime(1200, now);
                gain.gain.setValueAtTime(0.06, now);
                gain.gain.linearRampToValueAtTime(0, now + 0.05);
                osc.start(now);
                osc.stop(now + 0.06);
                break;
        }
    } catch (e) { /* audio error, non-fatal */ }
}

// ============================================================
// Coordinate transforms
// ============================================================

function worldToScreen(wx, wy) {
    const cam = warState.cam;
    const canvas = warState.canvas;
    const sx = (wx - cam.x) * cam.zoom + canvas.width / 2;
    const sy = -(wy - cam.y) * cam.zoom + canvas.height / 2;
    return { x: sx, y: sy };
}

function screenToWorld(sx, sy) {
    const cam = warState.cam;
    const canvas = warState.canvas;
    const wx = (sx - canvas.width / 2) / cam.zoom + cam.x;
    const wy = -((sy - canvas.height / 2) / cam.zoom) + cam.y;
    return { x: wx, y: wy };
}

// ============================================================
// Init / Destroy
// ============================================================

function initWarView() {
    const container = document.getElementById('view-war');
    if (!container) return;

    if (!warState.initialized) {
        warState.canvas = document.getElementById('war-canvas');
        warState.ctx = warState.canvas ? warState.canvas.getContext('2d') : null;

        // Initialize Three.js 3D renderer (war3d.js)
        if (typeof initWar3D === 'function') {
            initWar3D(container);
            warState.use3D = true;
            // Hide the 2D canvas — Three.js creates its own
            if (warState.canvas) warState.canvas.style.display = 'none';
        } else if (!warState.ctx) {
            return; // no 3D renderer and no 2D context
        }

        // Bind canvas events
        bindCanvasEvents();

        // Build HUD content
        buildModeIndicator();
        buildAmyPanel();
        buildAlertLog();
        buildSetupPalette();
        buildUnitInfo();
        buildMinimapHUD();
        buildStatsHUD();

        warState.initialized = true;
    }

    // Resize canvas to fill container
    resizeCanvas();
    // Remove before adding to prevent duplicate listeners on re-entry
    window.removeEventListener('resize', resizeCanvas);
    window.addEventListener('resize', resizeCanvas);

    // Start render loop
    if (!warState.animFrame) {
        renderLoop();
    }

    // Bind war-specific keys (remove first to prevent duplicates)
    document.removeEventListener('keydown', warKeyHandler);
    document.addEventListener('keydown', warKeyHandler);

    // Load initial Amy status
    fetchAmyStatus();

    // Fetch initial SIM/LIVE mode
    _fetchInitialMode();

    // Load geo reference from server — auto-initializes map if configured.
    // This fetches the server-side reference point (real lat/lng from config),
    // initializes the frontend geo engine, and loads satellite tiles + buildings.
    _loadGeoReference();

    // Seed the map with current targets so the user does not see a blank
    // screen while waiting for the next WebSocket tick (100ms at best,
    // but if WS reconnects the gap can be seconds).
    fetchWarState();
}

function fetchWarState() {
    fetch('/api/amy/war/state')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data) return;

            // Seed assetState.simTargets for targets that are not yet
            // present (avoid overwriting fresher WS data).
            if (data.targets && typeof updateSimTarget === 'function') {
                for (const t of data.targets) {
                    if (typeof assetState !== 'undefined'
                        && !assetState.simTargets[t.target_id]) {
                        updateSimTarget(t);
                    }
                }
            }

            // Seed Amy panel
            if (data.amy) {
                warState.amyMood = data.amy.mood || warState.amyMood;
                warState.amyState = data.amy.state || warState.amyState;
                updateAmyPanel();
            }

            // Seed thoughts
            if (data.thoughts && Array.isArray(data.thoughts)) {
                for (const t of data.thoughts) {
                    if (!warState.amyThoughts.includes(t)) {
                        warState.amyThoughts.push(t);
                    }
                }
                if (warState.amyThoughts.length > 20) {
                    warState.amyThoughts = warState.amyThoughts.slice(-20);
                }
                updateAmyPanel();
            }

            // Seed zones
            if (data.zones && Array.isArray(data.zones)) {
                warState.zones = data.zones;
            }

            // Seed threat records
            if (data.threats && Array.isArray(data.threats)) {
                for (const t of data.threats) {
                    warState.threats[t.target_id] = t;
                }
            }
        })
        .catch(() => {});
}

function destroyWarView() {
    if (warState.animFrame) {
        cancelAnimationFrame(warState.animFrame);
        warState.animFrame = null;
    }
    window.removeEventListener('resize', resizeCanvas);
    document.removeEventListener('keydown', warKeyHandler);

    // Destroy 3D renderer
    if (warState.use3D && typeof destroyWar3D === 'function') {
        destroyWar3D();
        warState.use3D = false;
        warState.initialized = false;
        // Re-show 2D canvas for potential fallback
        if (warState.canvas) warState.canvas.style.display = '';
    }
}

function resizeCanvas() {
    // In 3D mode, war3d.js handles its own resize in _handleResize()
    if (warState.use3D) return;

    const canvas = warState.canvas;
    if (!canvas) return;
    const parent = canvas.parentElement;
    canvas.width = parent.clientWidth;
    canvas.height = parent.clientHeight;
}

// ============================================================
// Render loop
// ============================================================

function renderLoop() {
    render();
    warState.animFrame = requestAnimationFrame(renderLoop);
}

function render() {
    // Camera lerp (shared by both renderers)
    const cam = warState.cam;
    cam.x += (cam.targetX - cam.x) * 0.1;
    cam.y += (cam.targetY - cam.y) * 0.1;
    cam.zoom += (cam.targetZoom - cam.zoom) * 0.1;

    // 3D renderer path
    if (warState.use3D && typeof updateWar3D === 'function') {
        updateWar3D();
        updateMinimapHUD();
        updateStatsHUD();
        return;
    }

    // Fallback: Canvas 2D rendering
    const ctx = warState.ctx;
    const canvas = warState.canvas;
    if (!ctx || !canvas || canvas.width === 0) return;

    // Clear
    ctx.fillStyle = '#0a0a12';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Draw layers
    drawGrid(ctx);
    drawMapBoundary(ctx);
    drawZones(ctx);
    drawTargets(ctx);
    drawSelectionIndicators(ctx);
    drawDispatchArrows(ctx);
    drawEffects(ctx);
    drawBoxSelect(ctx);
    drawPlacingGhost(ctx);
    // Editor overlays (FOV cones, ghost, selection) — drawn over targets
    if (typeof warEditorDraw === 'function') warEditorDraw(ctx);
    drawMinimap(ctx);
    drawStats(ctx);
}

// ============================================================
// Drawing functions
// ============================================================

function drawGrid(ctx) {
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.06)';
    ctx.lineWidth = 1;

    const step = 5;
    for (let wx = warState.mapMin; wx <= warState.mapMax; wx += step) {
        const p1 = worldToScreen(wx, warState.mapMin);
        const p2 = worldToScreen(wx, warState.mapMax);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
    }
    for (let wy = warState.mapMin; wy <= warState.mapMax; wy += step) {
        const p1 = worldToScreen(warState.mapMin, wy);
        const p2 = worldToScreen(warState.mapMax, wy);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
    }
}

function drawMapBoundary(ctx) {
    const tl = worldToScreen(warState.mapMin, warState.mapMax);
    const br = worldToScreen(warState.mapMax, warState.mapMin);
    const w = br.x - tl.x;
    const h = br.y - tl.y;

    ctx.strokeStyle = 'rgba(0, 240, 255, 0.15)';
    ctx.lineWidth = 2;
    ctx.strokeRect(tl.x, tl.y, w, h);
}

function drawZones(ctx) {
    for (const zone of warState.zones) {
        const pos = zone.position || {};
        const wx = pos.x || 0;
        const wy = pos.z !== undefined ? pos.z : (pos.y || 0);
        const radius = (zone.properties && zone.properties.radius) || 10;
        const sp = worldToScreen(wx, wy);
        const sr = radius * warState.cam.zoom;
        const isRestricted = (zone.type || '').includes('restricted');
        const color = isRestricted ? 'rgba(255, 42, 109, 0.12)' : 'rgba(0, 240, 255, 0.06)';
        const borderColor = isRestricted ? 'rgba(255, 42, 109, 0.35)' : 'rgba(0, 240, 255, 0.18)';

        // Fill
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
        ctx.fill();

        // Border (dashed for perimeter, solid for restricted)
        ctx.strokeStyle = borderColor;
        ctx.lineWidth = isRestricted ? 2 : 1;
        if (!isRestricted) ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
        ctx.stroke();
        if (!isRestricted) ctx.setLineDash([]);

        // Label
        const name = zone.name || zone.type || '';
        if (name && warState.cam.zoom > 0.6) {
            ctx.fillStyle = isRestricted ? 'rgba(255, 42, 109, 0.5)' : 'rgba(0, 240, 255, 0.3)';
            ctx.font = `${Math.max(8, 10 * Math.min(warState.cam.zoom, 2))}px "JetBrains Mono", monospace`;
            ctx.textAlign = 'center';
            ctx.fillText(name.toUpperCase(), sp.x, sp.y + sr + 14);
        }
    }
}

function drawTargets(ctx) {
    const targets = getTargets();
    for (const [tid, t] of Object.entries(targets)) {
        drawTarget(ctx, tid, t);
    }
}

function drawTarget(ctx, tid, t) {
    const pos = getTargetPosition(t);
    if (pos.x === undefined || pos.y === undefined) return;

    const sp = worldToScreen(pos.x, pos.y);
    const alliance = (t.alliance || 'unknown').toLowerCase();
    const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
    const isSelected = warState.selectedTargets.includes(tid);
    const isHovered = warState.hoveredTarget === tid;
    const baseRadius = 6 * Math.min(warState.cam.zoom, 3);
    const radius = isSelected ? baseRadius * 1.3 : (isHovered ? baseRadius * 1.15 : baseRadius);

    // Draw waypoint paths for friendlies
    if (t.waypoints && t.waypoints.length > 1) {
        ctx.strokeStyle = `${color}33`;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 6]);
        ctx.beginPath();
        for (let i = 0; i < t.waypoints.length; i++) {
            const wp = t.waypoints[i];
            const wps = worldToScreen(wp.x, wp.y);
            if (i === 0) ctx.moveTo(wps.x, wps.y);
            else ctx.lineTo(wps.x, wps.y);
        }
        ctx.closePath();
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // Shape by alliance
    if (alliance === 'friendly') {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
        ctx.fill();
    } else if (alliance === 'hostile') {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(sp.x, sp.y - radius);
        ctx.lineTo(sp.x + radius, sp.y);
        ctx.lineTo(sp.x, sp.y + radius);
        ctx.lineTo(sp.x - radius, sp.y);
        ctx.closePath();
        ctx.fill();
    } else if (alliance === 'neutral') {
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.6;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius * 0.8, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1.0;
    } else {
        // Unknown: square
        ctx.fillStyle = color;
        const half = radius * 0.8;
        ctx.fillRect(sp.x - half, sp.y - half, half * 2, half * 2);
    }

    // Heading line: heading 0 = north (+y), clockwise (compass bearing)
    // Convert to math angle: math_angle = 90 - heading
    if (t.heading !== undefined && t.heading !== null) {
        const rad = (90 - t.heading) * Math.PI / 180;
        const lineLen = radius * 2.2;
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(sp.x, sp.y);
        // Screen Y is inverted, so subtract sin to point up for north
        ctx.lineTo(sp.x + Math.cos(rad) * lineLen, sp.y - Math.sin(rad) * lineLen);
        ctx.stroke();
    }

    // Neutralized overlay: X mark and faded rendering
    const isNeutralized = (t.status || '').toLowerCase() === 'neutralized';
    if (isNeutralized) {
        ctx.globalAlpha = 0.35;
        // Draw X over target
        const xSize = radius * 1.2;
        ctx.strokeStyle = '#ff2a6d';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(sp.x - xSize, sp.y - xSize);
        ctx.lineTo(sp.x + xSize, sp.y + xSize);
        ctx.moveTo(sp.x + xSize, sp.y - xSize);
        ctx.lineTo(sp.x - xSize, sp.y + xSize);
        ctx.stroke();
        ctx.globalAlpha = 1.0;
    }

    // Threat level ring (escalation indicator)
    const threat = warState.threats[tid];
    if (threat && threat.threat_level && threat.threat_level !== 'none') {
        const threatColor = THREAT_COLORS[threat.threat_level] || '#fcee0a';
        const ringRadius = radius + 6;
        ctx.strokeStyle = threatColor;
        ctx.lineWidth = 2;
        ctx.setLineDash([3, 3]);
        // Animated rotation
        const rotOffset = (Date.now() / 1000) * 2;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, ringRadius, rotOffset, rotOffset + Math.PI * 1.5);
        ctx.stroke();
        ctx.setLineDash([]);

        // Threat label
        if (warState.cam.zoom > 0.8) {
            ctx.fillStyle = threatColor;
            ctx.font = `bold ${Math.max(7, 8 * Math.min(warState.cam.zoom, 2))}px "JetBrains Mono", monospace`;
            ctx.textAlign = 'center';
            ctx.fillText(threat.threat_level.toUpperCase(), sp.x, sp.y + radius + 18);
        }
    }

    // Label
    const name = t.name || tid;
    ctx.fillStyle = isNeutralized ? 'rgba(255, 255, 255, 0.3)' : 'rgba(255, 255, 255, 0.8)';
    ctx.font = `${Math.max(9, 11 * Math.min(warState.cam.zoom, 2))}px "JetBrains Mono", monospace`;
    ctx.textAlign = 'center';
    ctx.fillText(name, sp.x, sp.y - radius - 4);

    // "NEUTRALIZED" label
    if (isNeutralized && warState.cam.zoom > 0.6) {
        ctx.fillStyle = 'rgba(255, 42, 109, 0.6)';
        ctx.font = `bold ${Math.max(8, 9 * Math.min(warState.cam.zoom, 2))}px "JetBrains Mono", monospace`;
        ctx.fillText('NEUTRALIZED', sp.x, sp.y + radius + 14);
    }

    // Battery bar for friendlies
    if (alliance === 'friendly' && t.battery !== undefined) {
        const barW = radius * 3;
        const barH = 3;
        const bx = sp.x - barW / 2;
        const by = sp.y + radius + 4;
        ctx.fillStyle = 'rgba(255,255,255,0.15)';
        ctx.fillRect(bx, by, barW, barH);
        const level = Math.max(0, Math.min(1, t.battery));
        const r = Math.round(255 * (1 - level));
        const g = Math.round(255 * level);
        ctx.fillStyle = `rgb(${r}, ${g}, 0)`;
        ctx.fillRect(bx, by, barW * level, barH);
    }
}

function drawSelectionIndicators(ctx) {
    const targets = getTargets();
    for (const tid of warState.selectedTargets) {
        const t = targets[tid];
        if (!t) continue;
        const pos = getTargetPosition(t);
        if (pos.x === undefined) continue;
        const sp = worldToScreen(pos.x, pos.y);
        const radius = 10 * Math.min(warState.cam.zoom, 3);

        ctx.strokeStyle = '#00f0ff';
        ctx.lineWidth = 2;
        ctx.shadowColor = '#00f0ff';
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius + 4, 0, Math.PI * 2);
        ctx.stroke();
        ctx.shadowBlur = 0;
    }
}

function drawDispatchArrows(ctx) {
    const now = Date.now();
    warState.dispatchArrows = warState.dispatchArrows.filter(a => now - a.time < 3000);

    for (const arrow of warState.dispatchArrows) {
        const alpha = Math.max(0, 1 - (now - arrow.time) / 3000);
        const from = worldToScreen(arrow.fromX, arrow.fromY);
        const to = worldToScreen(arrow.toX, arrow.toY);

        ctx.strokeStyle = `rgba(255, 42, 109, ${alpha})`;
        ctx.lineWidth = 2;
        ctx.setLineDash([8, 4]);
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
        ctx.setLineDash([]);

        // Arrowhead
        const angle = Math.atan2(to.y - from.y, to.x - from.x);
        const headLen = 12;
        ctx.fillStyle = `rgba(255, 42, 109, ${alpha})`;
        ctx.beginPath();
        ctx.moveTo(to.x, to.y);
        ctx.lineTo(to.x - headLen * Math.cos(angle - 0.4), to.y - headLen * Math.sin(angle - 0.4));
        ctx.lineTo(to.x - headLen * Math.cos(angle + 0.4), to.y - headLen * Math.sin(angle + 0.4));
        ctx.closePath();
        ctx.fill();
    }
}

function drawBoxSelect(ctx) {
    if (!warState.boxSelect) return;
    const b = warState.boxSelect;
    const x = Math.min(b.startX, b.endX);
    const y = Math.min(b.startY, b.endY);
    const w = Math.abs(b.endX - b.startX);
    const h = Math.abs(b.endY - b.startY);

    ctx.strokeStyle = 'rgba(0, 240, 255, 0.6)';
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(0, 240, 255, 0.05)';
    ctx.fillRect(x, y, w, h);
}

function drawPlacingGhost(ctx) {
    if (!warState.placingAsset) return;
    const wp = screenToWorld(warState.lastMouse.x, warState.lastMouse.y);
    const sp = worldToScreen(wp.x, wp.y);

    ctx.globalAlpha = 0.5;
    ctx.fillStyle = '#fcee0a';
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1.0;

    ctx.fillStyle = 'rgba(252, 238, 10, 0.7)';
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(warState.placingAsset.toUpperCase(), sp.x, sp.y - 14);
}

function drawMinimap(ctx) {
    const mmSize = 150;
    const mmPad = 12;
    const mmX = mmPad;
    const mmY = ctx.canvas.height - mmSize - mmPad;

    // Background
    ctx.fillStyle = 'rgba(10, 10, 20, 0.85)';
    ctx.fillRect(mmX, mmY, mmSize, mmSize);
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.25)';
    ctx.lineWidth = 1;
    ctx.strokeRect(mmX, mmY, mmSize, mmSize);

    const range = warState.mapMax - warState.mapMin; // 60

    // Helper: world to minimap coords
    function wToMM(wx, wy) {
        const mx = mmX + ((wx - warState.mapMin) / range) * mmSize;
        const my = mmY + ((warState.mapMax - wy) / range) * mmSize; // Y flipped
        return { x: mx, y: my };
    }

    // Draw zones on minimap
    for (const zone of warState.zones) {
        const zpos = zone.position || {};
        const zx = zpos.x || 0;
        const zy = zpos.z !== undefined ? zpos.z : (zpos.y || 0);
        const zr = ((zone.properties && zone.properties.radius) || 10) / range * mmSize;
        const zmp = wToMM(zx, zy);
        const isRestricted = (zone.type || '').includes('restricted');
        ctx.fillStyle = isRestricted ? 'rgba(255, 42, 109, 0.15)' : 'rgba(0, 240, 255, 0.08)';
        ctx.beginPath();
        ctx.arc(zmp.x, zmp.y, zr, 0, Math.PI * 2);
        ctx.fill();
    }

    // Draw all targets as dots
    const targets = getTargets();
    for (const [tid, t] of Object.entries(targets)) {
        const pos = getTargetPosition(t);
        if (pos.x === undefined) continue;
        const mp = wToMM(pos.x, pos.y);
        const alliance = (t.alliance || 'unknown').toLowerCase();
        const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(mp.x, mp.y, 2, 0, Math.PI * 2);
        ctx.fill();
    }

    // Viewport rectangle
    const cam = warState.cam;
    const halfW = (ctx.canvas.width / 2) / cam.zoom;
    const halfH = (ctx.canvas.height / 2) / cam.zoom;
    const vpTL = wToMM(cam.x - halfW, cam.y + halfH);
    const vpBR = wToMM(cam.x + halfW, cam.y - halfH);
    const vpW = vpBR.x - vpTL.x;
    const vpH = vpBR.y - vpTL.y;

    ctx.strokeStyle = 'rgba(0, 240, 255, 0.6)';
    ctx.lineWidth = 1;
    ctx.strokeRect(vpTL.x, vpTL.y, vpW, vpH);
}

// ============================================================
// Visual effects
// ============================================================

function addEffect(type, worldX, worldY, data) {
    warState.effects.push({
        type: type,
        x: worldX,
        y: worldY,
        time: Date.now(),
        data: data || {},
    });
}

function drawEffects(ctx) {
    const now = Date.now();
    warState.effects = warState.effects.filter(e => now - e.time < 2000);

    for (const e of warState.effects) {
        const age = (now - e.time) / 1000; // seconds
        const sp = worldToScreen(e.x, e.y);

        if (e.type === 'neutralized') {
            // Expanding ring flash
            const ringRadius = age * 40 * warState.cam.zoom;
            const alpha = Math.max(0, 1 - age / 1.5);
            ctx.strokeStyle = `rgba(255, 42, 109, ${alpha})`;
            ctx.lineWidth = 3 * (1 - age / 2);
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, ringRadius, 0, Math.PI * 2);
            ctx.stroke();

            // "KILL" text that floats up
            if (age < 1.2) {
                const textAlpha = Math.max(0, 1 - age / 1.2);
                const yOffset = age * 30;
                ctx.fillStyle = `rgba(255, 42, 109, ${textAlpha})`;
                ctx.font = `bold ${14 * Math.min(warState.cam.zoom, 2)}px "Orbitron", monospace`;
                ctx.textAlign = 'center';
                ctx.fillText('NEUTRALIZED', sp.x, sp.y - yOffset);
            }
        } else if (e.type === 'zone_pulse') {
            // Zone border pulse on violation
            const pulseAlpha = Math.max(0, 0.6 - age / 1.5);
            const pulseRadius = (e.data.radius || 10) * warState.cam.zoom;
            ctx.strokeStyle = `rgba(255, 42, 109, ${pulseAlpha})`;
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, pulseRadius + age * 10, 0, Math.PI * 2);
            ctx.stroke();
        }
    }
}

// ============================================================
// Stats HUD (top-left score overlay)
// ============================================================

function drawStats(ctx) {
    const canvas = warState.canvas;
    const targets = getTargets();

    // Compute live stats
    let activeHostiles = 0;
    let activeFriendlies = 0;
    for (const t of Object.values(targets)) {
        const alliance = (t.alliance || '').toLowerCase();
        const status = (t.status || 'active').toLowerCase();
        if (alliance === 'hostile' && status === 'active') activeHostiles++;
        if (alliance === 'friendly' && status !== 'destroyed') activeFriendlies++;
    }

    const x = 12;
    const y = 48;
    const lineH = 16;

    ctx.fillStyle = 'rgba(10, 10, 20, 0.75)';
    ctx.fillRect(x, y, 160, lineH * 5 + 8);
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.15)';
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, 160, lineH * 5 + 8);

    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';

    const rows = [
        { label: 'KILLS', value: warState.stats.kills, color: '#ff2a6d' },
        { label: 'BREACHES', value: warState.stats.breaches, color: '#ff9800' },
        { label: 'DISPATCHES', value: warState.stats.dispatches, color: '#00f0ff' },
        { label: 'HOSTILES', value: activeHostiles, color: activeHostiles > 0 ? '#ff2a6d' : '#05ffa1' },
        { label: 'FRIENDLIES', value: activeFriendlies, color: '#05ffa1' },
    ];

    for (let i = 0; i < rows.length; i++) {
        const ry = y + 4 + i * lineH + lineH * 0.75;
        ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
        ctx.fillText(rows[i].label, x + 8, ry);
        ctx.fillStyle = rows[i].color;
        ctx.textAlign = 'right';
        ctx.fillText(String(rows[i].value), x + 150, ry);
        ctx.textAlign = 'left';
    }
}

// ============================================================
// Target helpers
// ============================================================

function getTargets() {
    // Single source of truth: assets.js owns target data (populated via
    // updateSimTarget from WebSocket telemetry).  War Room reads, never writes.
    return (typeof assetState !== 'undefined' && assetState.simTargets) ? assetState.simTargets : {};
}

function getTargetPosition(t) {
    if (t.position && t.position.x !== undefined) {
        return { x: t.position.x, y: t.position.y };
    }
    return { x: t.x, y: t.y };
}

function hitTestTarget(sx, sy) {
    const targets = getTargets();
    const hitRadius = 14;
    let closest = null;
    let closestDist = Infinity;

    for (const [tid, t] of Object.entries(targets)) {
        const pos = getTargetPosition(t);
        if (pos.x === undefined) continue;
        const sp = worldToScreen(pos.x, pos.y);
        const dx = sp.x - sx;
        const dy = sp.y - sy;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < hitRadius && dist < closestDist) {
            closestDist = dist;
            closest = tid;
        }
    }
    return closest;
}

// ============================================================
// Mouse events
// ============================================================

function bindCanvasEvents() {
    // Use 3D renderer canvas if available, otherwise the 2D canvas
    const canvas = (warState.use3D && typeof war3d !== 'undefined' && war3d.renderer)
        ? war3d.renderer.domElement
        : warState.canvas;
    if (!canvas) return;

    // Store the active canvas for event coordinate calculations
    warState._eventCanvas = canvas;

    canvas.addEventListener('mousedown', onCanvasMouseDown);
    canvas.addEventListener('mousemove', onCanvasMouseMove);
    canvas.addEventListener('mouseup', onCanvasMouseUp);
    canvas.addEventListener('wheel', onCanvasWheel, { passive: false });
    canvas.addEventListener('contextmenu', onCanvasContextMenu);
    canvas.addEventListener('dblclick', onCanvasDblClick);
}

function _getEventCanvas() {
    return warState._eventCanvas || warState.canvas;
}

function onCanvasMouseDown(e) {
    const rect = _getEventCanvas().getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    warState.lastMouse = { x: sx, y: sy };

    if (e.button === 1 || (e.button === 0 && e.altKey)) {
        // Middle click or alt+left = pan
        warState.isPanning = true;
        warState.dragStart = { x: sx, y: sy, camX: warState.cam.targetX, camY: warState.cam.targetY };
        e.preventDefault();
        return;
    }

    if (e.button === 0) {
        // Left click

        // Minimap click-to-pan (2D mode only — in 3D mode minimap is HTML overlay)
        if (!warState.use3D) {
            const mmSize = 150;
            const mmPad = 12;
            const mmX = mmPad;
            const mmY = warState.canvas.height - mmSize - mmPad;
            if (sx >= mmX && sx <= mmX + mmSize && sy >= mmY && sy <= mmY + mmSize) {
                const range = warState.mapMax - warState.mapMin;
                const wx = warState.mapMin + ((sx - mmX) / mmSize) * range;
                const wy = warState.mapMax - ((sy - mmY) / mmSize) * range; // Y flipped
                warState.cam.targetX = wx;
                warState.cam.targetY = wy;
                return;
            }
        }

        // Editor handles placement and asset selection in setup mode
        if (warState.mode === 'setup' && typeof warEditorMouseDown === 'function') {
            if (warEditorMouseDown(sx, sy, e.button, e.shiftKey)) return;
        }

        if (warState.mode === 'setup' && warState.placingAsset) {
            // Place asset (use 3D ground projection or 2D screenToWorld)
            const wp = (warState.use3D && typeof war3dDispatchTo === 'function')
                ? war3dDispatchTo(e.clientX, e.clientY)
                : screenToWorld(sx, sy);
            if (wp) placeSetupAsset(warState.placingAsset, wp.x, wp.y);
            return;
        }

        // Use 3D raycasting if available, otherwise 2D hit test
        const hit = (warState.use3D && typeof war3dSelectAt === 'function')
            ? war3dSelectAt(e.clientX, e.clientY)
            : hitTestTarget(sx, sy);
        if (hit) {
            if (e.shiftKey) {
                // Toggle selection
                const idx = warState.selectedTargets.indexOf(hit);
                if (idx >= 0) warState.selectedTargets.splice(idx, 1);
                else warState.selectedTargets.push(hit);
            } else {
                warState.selectedTargets = [hit];
            }
            updateUnitInfo();
        } else {
            if (!e.shiftKey) {
                warState.selectedTargets = [];
                updateUnitInfo();
            }
            // Start box select
            warState.isDragging = true;
            warState.boxSelect = { startX: sx, startY: sy, endX: sx, endY: sy };
        }
    }
}

function onCanvasMouseMove(e) {
    const rect = _getEventCanvas().getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    warState.lastMouse = { x: sx, y: sy };

    if (warState.isPanning && warState.dragStart) {
        if (warState.use3D) {
            // 3D mode: convert pixel delta to world units via ortho frustum
            const container = document.getElementById('view-war');
            const ch = container ? container.clientHeight : 600;
            const cw = container ? container.clientWidth : 800;
            const frustumH = 15 / warState.cam.zoom;
            const frustumW = frustumH * (cw / Math.max(1, ch));
            const dx = (sx - warState.dragStart.x) / cw * frustumW * 2;
            const dy = (sy - warState.dragStart.y) / ch * frustumH * 2;
            warState.cam.targetX = warState.dragStart.camX - dx;
            warState.cam.targetY = warState.dragStart.camY + dy;
        } else {
            const dx = (sx - warState.dragStart.x) / warState.cam.zoom;
            const dy = (sy - warState.dragStart.y) / warState.cam.zoom;
            warState.cam.targetX = warState.dragStart.camX - dx;
            warState.cam.targetY = warState.dragStart.camY + dy; // Y flipped
        }
        return;
    }

    if (warState.isDragging && warState.boxSelect) {
        warState.boxSelect.endX = sx;
        warState.boxSelect.endY = sy;
        return;
    }

    // Editor hover (placed asset overlays)
    if (typeof warEditorMouseMove === 'function') warEditorMouseMove(sx, sy);

    // Hover detection (3D raycasting or 2D hit test)
    warState.hoveredTarget = (warState.use3D && typeof war3dSelectAt === 'function')
        ? war3dSelectAt(e.clientX, e.clientY)
        : hitTestTarget(sx, sy);
    const evCanvas = _getEventCanvas();
    evCanvas.style.cursor = warState.hoveredTarget ? 'pointer' :
        (warState.placingAsset ? 'cell' : 'crosshair');
}

function onCanvasMouseUp(e) {
    const rect = _getEventCanvas().getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (warState.isPanning) {
        warState.isPanning = false;
        warState.dragStart = null;
        return;
    }

    if (e.button === 2) {
        // In setup mode, right-click cancels placement via editor
        if (warState.mode === 'setup' && typeof warEditorMouseDown === 'function') {
            if (warEditorMouseDown(sx, sy, 2, e.shiftKey)) return;
        }
        // Right click dispatch (works in any mode when friendlies selected)
        if (warState.selectedTargets.length > 0) {
            // Use 3D ground projection if available
            const wp = (warState.use3D && typeof war3dDispatchTo === 'function')
                ? war3dDispatchTo(e.clientX, e.clientY)
                : screenToWorld(sx, sy);
            if (wp) dispatchSelectedTargets(wp.x, wp.y);
        }
        return;
    }

    if (warState.isDragging && warState.boxSelect) {
        // Finish box select
        const b = warState.boxSelect;
        const bx1 = Math.min(b.startX, b.endX);
        const by1 = Math.min(b.startY, b.endY);
        const bx2 = Math.max(b.startX, b.endX);
        const by2 = Math.max(b.startY, b.endY);

        // Only select if box has meaningful size
        if (bx2 - bx1 > 5 && by2 - by1 > 5) {
            const targets = getTargets();
            const newSelection = [];
            for (const [tid, t] of Object.entries(targets)) {
                const alliance = (t.alliance || '').toLowerCase();
                if (alliance !== 'friendly') continue;
                const pos = getTargetPosition(t);
                if (pos.x === undefined) continue;
                const sp = worldToScreen(pos.x, pos.y);
                if (sp.x >= bx1 && sp.x <= bx2 && sp.y >= by1 && sp.y <= by2) {
                    newSelection.push(tid);
                }
            }
            if (e.shiftKey) {
                for (const tid of newSelection) {
                    if (!warState.selectedTargets.includes(tid)) {
                        warState.selectedTargets.push(tid);
                    }
                }
            } else {
                warState.selectedTargets = newSelection;
            }
            updateUnitInfo();
        }

        warState.boxSelect = null;
        warState.isDragging = false;
    }
}

function onCanvasWheel(e) {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    const newZoom = Math.max(0.3, Math.min(5.0, warState.cam.targetZoom * factor));

    if (warState.use3D && typeof war3dDispatchTo === 'function') {
        // In 3D mode, use raycasting to find world point under cursor
        const wp = war3dDispatchTo(e.clientX, e.clientY);
        if (wp) {
            // Cursor-centered zoom: solve for new camera that keeps wp under cursor
            const evCanvas = _getEventCanvas();
            const rect = evCanvas.getBoundingClientRect();
            const sx = e.clientX - rect.left;
            const sy = e.clientY - rect.top;
            const cw = rect.width;
            const ch = rect.height;
            // Ortho frustum half = 15 / zoom
            const oldHalf = 15 / warState.cam.targetZoom;
            const newHalf = 15 / newZoom;
            const aspect = cw / Math.max(1, ch);
            // NDC of cursor
            const ndcX = (sx / cw) * 2 - 1;
            const ndcY = -((sy / ch) * 2 - 1);
            // new cam position so that wp stays at (ndcX, ndcY) in NDC
            warState.cam.targetX = wp.x - ndcX * newHalf * aspect;
            warState.cam.targetY = wp.y - ndcY * newHalf;
        }
        warState.cam.targetZoom = newZoom;
        return;
    }

    // Fallback: 2D cursor-centered zoom
    const rect = _getEventCanvas().getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const wp = screenToWorld(sx, sy);

    warState.cam.targetX = wp.x - (sx - warState.canvas.width / 2) / newZoom;
    warState.cam.targetY = wp.y + (sy - warState.canvas.height / 2) / newZoom;
    warState.cam.targetZoom = newZoom;
}

function onCanvasContextMenu(e) {
    e.preventDefault();
}

function onCanvasDblClick(e) {
    const rect = _getEventCanvas().getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const hit = (warState.use3D && typeof war3dSelectAt === 'function')
        ? war3dSelectAt(e.clientX, e.clientY)
        : hitTestTarget(sx, sy);

    if (hit) {
        const t = getTargets()[hit];
        if (t) {
            const pos = getTargetPosition(t);
            warState.cam.targetX = pos.x;
            warState.cam.targetY = pos.y;
            warState.cam.targetZoom = Math.min(warState.cam.targetZoom * 1.5, 4.0);
            warState.selectedTargets = [hit];
            updateUnitInfo();
        }
    }
}

// ============================================================
// Keyboard
// ============================================================

function warKeyHandler(e) {
    // Only handle when war view is active
    if (typeof state !== 'undefined' && state.currentView !== 'war') return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    // Delegate to editor first (R to rotate, Delete, Escape in setup mode)
    if (typeof warEditorKey === 'function' && warEditorKey(e)) return;

    switch (e.key) {
        case 'Escape':
            if (warState.placingAsset) {
                warState.placingAsset = null;
                updateSetupPalette();
            } else {
                warState.selectedTargets = [];
                updateUnitInfo();
            }
            break;
        case 's':
            if (e.ctrlKey) return; // Don't intercept Ctrl+S
            setWarMode('setup');
            break;
        case 't':
            setWarMode('tactical');
            break;
        case 'o':
            setWarMode('observe');
            break;
        case 'Tab':
            e.preventDefault();
            cycleTargets();
            break;
        case ' ':
            e.preventDefault();
            centerOnSelected();
            break;
        case 'Delete':
            if (warState.mode === 'setup') {
                removeSelectedSetup();
            }
            break;
        case 'v':
        case 'V':
            // Toggle 3D camera tilt
            if (warState.use3D && typeof war3dToggleTilt === 'function') {
                war3dToggleTilt();
                warAddAlert('Camera: ' + (war3d.camState.tilt ? 'TILTED' : 'TOP-DOWN'), 'info');
            }
            break;
    }
}

function setWarMode(mode) {
    const prevMode = warState.mode;
    warState.mode = mode;
    warState.placingAsset = null;
    updateModeIndicator();
    updateSetupPalette();

    if (mode === 'setup') {
        showSetupPalette(true);
        if (typeof warEditorEnter === 'function') warEditorEnter();
    } else {
        showSetupPalette(false);
        if (prevMode === 'setup' && typeof warEditorExit === 'function') warEditorExit();
    }

    warAddAlert(`Mode: ${mode.toUpperCase()}`, 'info');
}

function cycleTargets() {
    const targets = getTargets();
    const keys = Object.keys(targets);
    if (keys.length === 0) return;
    warState.cycleIndex = (warState.cycleIndex + 1) % keys.length;
    const tid = keys[warState.cycleIndex];
    warState.selectedTargets = [tid];
    const t = targets[tid];
    if (t) {
        const pos = getTargetPosition(t);
        warState.cam.targetX = pos.x;
        warState.cam.targetY = pos.y;
    }
    updateUnitInfo();
}

function centerOnSelected() {
    if (warState.selectedTargets.length === 0) return;
    const targets = getTargets();
    let sumX = 0, sumY = 0, count = 0;
    for (const tid of warState.selectedTargets) {
        const t = targets[tid];
        if (!t) continue;
        const pos = getTargetPosition(t);
        if (pos.x !== undefined) {
            sumX += pos.x;
            sumY += pos.y;
            count++;
        }
    }
    if (count > 0) {
        warState.cam.targetX = sumX / count;
        warState.cam.targetY = sumY / count;
    }
}

// ============================================================
// Dispatch
// ============================================================

function dispatchSelectedTargets(worldX, worldY) {
    const targets = getTargets();
    for (const tid of warState.selectedTargets) {
        const t = targets[tid];
        if (!t) continue;
        const alliance = (t.alliance || '').toLowerCase();
        if (alliance !== 'friendly') continue;

        const pos = getTargetPosition(t);

        // Add dispatch arrow
        warState.dispatchArrows.push({
            fromX: pos.x || 0,
            fromY: pos.y || 0,
            toX: worldX,
            toY: worldY,
            time: Date.now(),
        });

        // Send dispatch command
        fetch('/api/amy/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'dispatch',
                params: [tid, worldX, worldY],
            }),
        }).catch(err => console.error('[WAR] Dispatch failed:', err));

        warAddAlert(`DISPATCH ${t.name || tid} -> (${worldX.toFixed(1)}, ${worldY.toFixed(1)})`, 'dispatch');
        warState.stats.dispatches++;
    }
    warPlaySound('dispatch');
}

// ============================================================
// Setup mode
// ============================================================

function placeSetupAsset(assetType, worldX, worldY) {
    const name = `${assetType}-${Date.now().toString(36).slice(-4)}`;

    fetch('/api/amy/simulation/spawn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: name,
            asset_type: assetType,
            alliance: 'friendly',
            position: { x: worldX, y: worldY },
        }),
    }).then(res => {
        if (res.ok) {
            warAddAlert(`Placed ${assetType} at (${worldX.toFixed(1)}, ${worldY.toFixed(1)})`, 'info');
            warPlaySound('place');
            if (typeof showNotification === 'function') {
                showNotification('PLACED', `${assetType} deployed`, 'success');
            }
        } else {
            warAddAlert(`Failed to place ${assetType}`, 'hostile');
        }
    }).catch(err => {
        console.error('[WAR] Spawn failed:', err);
        warAddAlert('Spawn failed', 'hostile');
    });
}

function removeSelectedSetup() {
    for (const tid of warState.selectedTargets) {
        fetch(`/api/amy/simulation/targets/${tid}`, { method: 'DELETE' })
            .then(res => {
                if (res.ok) warAddAlert(`Removed ${tid}`, 'info');
            })
            .catch(err => console.error('[WAR] Remove failed:', err));
    }
    warState.selectedTargets = [];
    updateUnitInfo();
}

// ============================================================
// HUD: Mode indicator
// ============================================================

function buildModeIndicator() {
    updateModeIndicator(); // Initial render
}

function updateModeIndicator() {
    const el = document.getElementById('war-mode');
    if (!el) return;
    el.textContent = warState.mode.toUpperCase();
    el.className = '';
    if (warState.mode === 'tactical') el.classList.add('mode-tactical');
    else if (warState.mode === 'setup') el.classList.add('mode-setup');
}

// ============================================================
// HUD: Amy panel
// ============================================================

function buildAmyPanel() {
    const panel = document.getElementById('war-amy-panel');
    if (!panel) return;
    panel.innerHTML = `
        <div style="font-size: 0.65rem; letter-spacing: 2px; color: #00f0ff; margin-bottom: 6px; font-weight: 600;">AMY</div>
        <div style="display: flex; gap: 8px; margin-bottom: 6px;">
            <span style="font-size: 0.6rem; color: rgba(255,255,255,0.5);">MOOD:</span>
            <span id="war-amy-mood" style="font-size: 0.7rem; color: #00f0ff;">--</span>
            <span style="font-size: 0.6rem; color: rgba(255,255,255,0.5); margin-left: auto;">STATE:</span>
            <span id="war-amy-state" style="font-size: 0.7rem; color: #05ffa1;">--</span>
        </div>
        <div id="war-amy-thoughts" style="font-size: 0.7rem; color: rgba(255,255,255,0.6); max-height: 200px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: rgba(0,240,255,0.3) transparent;"></div>
    `;
}

function updateAmyPanel() {
    const moodEl = document.getElementById('war-amy-mood');
    const stateEl = document.getElementById('war-amy-state');
    const thoughtsEl = document.getElementById('war-amy-thoughts');

    if (moodEl) moodEl.textContent = warState.amyMood;
    if (stateEl) stateEl.textContent = warState.amyState;

    if (thoughtsEl) {
        const html = warState.amyThoughts.slice(-5).map(t =>
            `<div class="war-amy-thought">${escapeHtml(t)}</div>`
        ).join('');
        thoughtsEl.innerHTML = html;
        thoughtsEl.scrollTop = thoughtsEl.scrollHeight;
    }
}

function fetchAmyStatus() {
    fetch('/api/amy/status')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data) return;
            warState.amyMood = data.mood || '--';
            warState.amyState = data.state || '--';
            updateAmyPanel();
        })
        .catch(() => {});
}

// ============================================================
// HUD: Alert log
// ============================================================

function buildAlertLog() {
    const el = document.getElementById('war-alert-log');
    if (!el) return;
    el.innerHTML = `
        <div style="font-size: 0.65rem; letter-spacing: 2px; color: #00f0ff; margin-bottom: 4px; font-weight: 600;">ALERTS</div>
        <div id="war-alert-entries"></div>
    `;
}

function warAddAlert(text, type) {
    const entry = {
        text: text,
        type: type || 'info',
        time: new Date(),
    };
    warState.alertLog.push(entry);
    if (warState.alertLog.length > 50) warState.alertLog.shift();
    renderAlertLog();
}

function renderAlertLog() {
    const container = document.getElementById('war-alert-entries');
    if (!container) return;

    const recent = warState.alertLog.slice(-15).reverse();
    container.innerHTML = recent.map(a => {
        const timeStr = a.time.toLocaleTimeString('en-US', { hour12: false }).slice(0, 8);
        const cls = a.type === 'hostile' ? 'alert-hostile' :
            a.type === 'dispatch' ? 'alert-dispatch' : 'alert-info';
        return `<div class="alert-entry ${cls}">
            <span class="alert-time">${timeStr}</span>
            <span>${escapeHtml(a.text)}</span>
        </div>`;
    }).join('');
}

// ============================================================
// HUD: Unit info
// ============================================================

function buildUnitInfo() {
    // Built dynamically on selection
}

function updateUnitInfo() {
    const el = document.getElementById('war-unit-info');
    if (!el) return;

    // Prune stale selections (targets that no longer exist)
    const targets = getTargets();
    warState.selectedTargets = warState.selectedTargets.filter(tid => targets[tid]);

    if (warState.selectedTargets.length === 0) {
        el.style.display = 'none';
        return;
    }

    el.style.display = 'block';

    if (warState.selectedTargets.length === 1) {
        const tid = warState.selectedTargets[0];
        const t = targets[tid];
        if (!t) { el.style.display = 'none'; return; }

        const pos = getTargetPosition(t);
        const alliance = (t.alliance || 'unknown').toLowerCase();
        const color = ALLIANCE_COLORS[alliance] || '#fcee0a';

        el.innerHTML = `
            <div style="font-size: 0.65rem; letter-spacing: 2px; color: ${color}; margin-bottom: 6px; font-weight: 600;">${(t.name || tid).toUpperCase()}</div>
            <div style="font-size: 0.7rem; margin-bottom: 3px;"><span style="color: rgba(255,255,255,0.5);">ID:</span> <span style="color: #00f0ff;">${tid}</span></div>
            <div style="font-size: 0.7rem; margin-bottom: 3px;"><span style="color: rgba(255,255,255,0.5);">TYPE:</span> ${t.asset_type || '--'}</div>
            <div style="font-size: 0.7rem; margin-bottom: 3px;"><span style="color: rgba(255,255,255,0.5);">ALLIANCE:</span> <span style="color: ${color};">${alliance.toUpperCase()}</span></div>
            <div style="font-size: 0.7rem; margin-bottom: 3px;"><span style="color: rgba(255,255,255,0.5);">POS:</span> (${(pos.x || 0).toFixed(1)}, ${(pos.y || 0).toFixed(1)})</div>
            ${t.battery !== undefined ? `<div style="font-size: 0.7rem; margin-bottom: 3px;"><span style="color: rgba(255,255,255,0.5);">BATTERY:</span> ${Math.round(t.battery * 100)}%</div>` : ''}
            ${t.status ? `<div style="font-size: 0.7rem; margin-bottom: 3px;"><span style="color: rgba(255,255,255,0.5);">STATUS:</span> ${t.status}</div>` : ''}
            ${t.speed !== undefined ? `<div style="font-size: 0.7rem;"><span style="color: rgba(255,255,255,0.5);">SPEED:</span> ${t.speed.toFixed(1)}</div>` : ''}
        `;
    } else {
        const count = warState.selectedTargets.length;
        const friendlyCount = warState.selectedTargets.filter(tid => {
            const t = targets[tid];
            return t && (t.alliance || '').toLowerCase() === 'friendly';
        }).length;

        el.innerHTML = `
            <div style="font-size: 0.65rem; letter-spacing: 2px; color: #00f0ff; margin-bottom: 6px; font-weight: 600;">SELECTION</div>
            <div style="font-size: 0.7rem; margin-bottom: 3px;">${count} units selected</div>
            <div style="font-size: 0.7rem; color: #05ffa1;">${friendlyCount} friendly</div>
            <div style="font-size: 0.65rem; color: rgba(255,255,255,0.4); margin-top: 6px;">Right-click to dispatch friendlies</div>
        `;
    }
}

// ============================================================
// HUD: Setup palette
// ============================================================

function buildSetupPalette() {
    const el = document.getElementById('war-setup-palette');
    if (!el) return;

    let html = '<div style="font-size: 0.65rem; letter-spacing: 2px; color: #fcee0a; margin-bottom: 8px; font-weight: 600;">DEPLOY ASSETS</div>';

    for (const cat of SETUP_PALETTE) {
        html += `<div class="palette-category">
            <div class="palette-category-title">${cat.title}</div>`;
        for (const item of cat.items) {
            html += `<div class="palette-item" data-type="${item.type}" onclick="selectPaletteItem('${item.type}')">${item.label}</div>`;
        }
        html += '</div>';
    }

    el.innerHTML = html;
}

function selectPaletteItem(type) {
    warState.placingAsset = type;
    updateSetupPalette();
}

function updateSetupPalette() {
    const items = document.querySelectorAll('#war-setup-palette .palette-item');
    items.forEach(item => {
        item.classList.toggle('selected', item.dataset.type === warState.placingAsset);
    });
}

function showSetupPalette(show) {
    const el = document.getElementById('war-setup-palette');
    if (el) {
        el.style.display = show ? 'block' : 'none';
        // Hide unit info when setup palette is visible
        if (show) {
            const unitInfo = document.getElementById('war-unit-info');
            if (unitInfo) unitInfo.style.display = 'none';
        }
    }
}

// ============================================================
// Amy speech toast
// ============================================================

function showAmySpeechToast(text) {
    const el = document.getElementById('war-amy-toast');
    if (!el) return;

    el.textContent = text;
    el.style.opacity = '1';

    if (warState.amySpeechTimeout) clearTimeout(warState.amySpeechTimeout);
    warState.amySpeechTimeout = setTimeout(() => {
        el.style.opacity = '0';
    }, 5000);
}

// ============================================================
// WebSocket event handlers (called from app.js)
// ============================================================

function warHandleZoneViolation(data) {
    warAddAlert(`ZONE VIOLATION: ${data.zone_name || 'unknown zone'}`, 'hostile');
    warPlaySound('zone_violation');
    warState.stats.breaches++;

    // Pulse effect on the zone
    if (data.position) {
        addEffect('zone_pulse', data.position.x, data.position.y, { radius: 10 });
    }
}

function warHandleThreatEscalation(data) {
    const id = data.target_id ? data.target_id.slice(0, 8) : '?';
    const msg = data.old_level && data.new_level
        ? `${id}: ${data.old_level} -> ${data.new_level}`
        : (data.message || 'Escalation detected');
    warAddAlert(`THREAT: ${msg}`, 'hostile');

    // Update local threat record
    if (data.target_id) {
        warState.threats[data.target_id] = {
            target_id: data.target_id,
            threat_level: data.new_level || 'unknown',
            in_zone: data.reason || '',
        };
    }
}

function warHandleDispatch(data) {
    if (data.target_id && data.destination) {
        const targets = getTargets();
        const t = targets[data.target_id];
        if (t) {
            const pos = getTargetPosition(t);
            warState.dispatchArrows.push({
                fromX: pos.x || 0,
                fromY: pos.y || 0,
                toX: data.destination.x,
                toY: data.destination.y,
                time: Date.now(),
            });
        }
        warAddAlert(`DISPATCH: ${data.name || data.target_id}`, 'dispatch');
        warPlaySound('dispatch');
        warState.stats.dispatches++;
    }
}

function warHandleAmySpeech(data) {
    const text = data.text || data.content || '';
    if (text) {
        showAmySpeechToast(text);
        warState.amyThoughts.push(text);
        if (warState.amyThoughts.length > 20) warState.amyThoughts.shift();
        updateAmyPanel();
    }
}

function warHandleAmyThought(data) {
    const text = data.text || data.content || '';
    if (text) {
        warState.amyThoughts.push(text);
        if (warState.amyThoughts.length > 20) warState.amyThoughts.shift();
        updateAmyPanel();
    }
}

function warHandleSimTelemetry(data) {
    if (!data || !data.target_id) return;
    // Track known targets locally (updateSimTarget in assets.js runs before us,
    // so checking assetState.simTargets would always find the target)
    const isNew = !warState.knownTargetIds.has(data.target_id);
    warState.knownTargetIds.add(data.target_id);

    if (isNew && data.alliance && data.alliance.toLowerCase() === 'hostile') {
        warAddAlert(`NEW HOSTILE: ${data.name || data.target_id}`, 'hostile');
        warPlaySound('hostile');
    }
}

function warHandleTargetNeutralized(data) {
    if (!data) return;
    const hostileName = data.hostile_name || data.hostile_id || 'hostile';
    const interceptorName = data.interceptor_name || data.interceptor_id || 'unit';
    warAddAlert(`NEUTRALIZED: ${hostileName} by ${interceptorName}`, 'dispatch');
    warPlaySound('neutralized');
    warState.stats.kills++;

    // Visual flash at position
    if (data.position) {
        addEffect('neutralized', data.position.x, data.position.y);
    }

    // Gamepad rumble for tactile feedback
    if (typeof tritiumInput !== 'undefined' && tritiumInput.gamepadHandler) {
        tritiumInput.gamepadHandler.vibrate(200, 0.4, 0.6);
    }
}

// ============================================================
// HUD: HTML Minimap (for 3D mode — replaces Canvas minimap)
// ============================================================

function buildMinimapHUD() {
    const hud = document.getElementById('war-hud');
    if (!hud || document.getElementById('war-minimap-hud')) return;

    const mmDiv = document.createElement('div');
    mmDiv.id = 'war-minimap-hud';
    mmDiv.style.cssText = 'position:absolute; bottom:12px; left:12px; width:150px; height:150px; pointer-events:auto; cursor:pointer;';
    mmDiv.innerHTML = '<canvas id="war-minimap-canvas" width="150" height="150" style="width:100%;height:100%;display:block;background:rgba(10,10,20,0.85);border:1px solid rgba(0,240,255,0.25);"></canvas>';
    hud.appendChild(mmDiv);

    // Click to pan
    mmDiv.addEventListener('click', (e) => {
        const rect = mmDiv.getBoundingClientRect();
        const rx = (e.clientX - rect.left) / rect.width;
        const ry = (e.clientY - rect.top) / rect.height;
        const range = warState.mapMax - warState.mapMin;
        warState.cam.targetX = warState.mapMin + rx * range;
        warState.cam.targetY = warState.mapMax - ry * range;
    });
}

function updateMinimapHUD() {
    const canvas = document.getElementById('war-minimap-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = 'rgba(10, 10, 20, 0.85)';
    ctx.fillRect(0, 0, w, h);

    const range = warState.mapMax - warState.mapMin;
    function wToMM(wx, wy) {
        return {
            x: ((wx - warState.mapMin) / range) * w,
            y: ((warState.mapMax - wy) / range) * h,
        };
    }

    // Zones
    for (const zone of warState.zones) {
        const zpos = zone.position || {};
        const zx = zpos.x || 0;
        const zy = zpos.z !== undefined ? zpos.z : (zpos.y || 0);
        const zr = ((zone.properties && zone.properties.radius) || 10) / range * w;
        const zmp = wToMM(zx, zy);
        const isRestricted = (zone.type || '').includes('restricted');
        ctx.fillStyle = isRestricted ? 'rgba(255,42,109,0.15)' : 'rgba(0,240,255,0.08)';
        ctx.beginPath();
        ctx.arc(zmp.x, zmp.y, zr, 0, Math.PI * 2);
        ctx.fill();
    }

    // Targets
    const targets = getTargets();
    for (const [tid, t] of Object.entries(targets)) {
        const pos = getTargetPosition(t);
        if (pos.x === undefined) continue;
        const mp = wToMM(pos.x, pos.y);
        const alliance = (t.alliance || 'unknown').toLowerCase();
        const colorMap = { friendly: '#05ffa1', hostile: '#ff2a6d', neutral: '#00a0ff', unknown: '#fcee0a' };
        ctx.fillStyle = colorMap[alliance] || '#fcee0a';
        ctx.beginPath();
        ctx.arc(mp.x, mp.y, 2, 0, Math.PI * 2);
        ctx.fill();
    }

    // Viewport rectangle
    const cam = warState.cam;
    const frustumH = 15 / cam.zoom;
    const container = document.getElementById('view-war');
    const aspect = container ? container.clientWidth / Math.max(1, container.clientHeight) : 1;
    const frustumW = frustumH * aspect;
    const vpTL = wToMM(cam.x - frustumW, cam.y + frustumH);
    const vpBR = wToMM(cam.x + frustumW, cam.y - frustumH);
    ctx.strokeStyle = 'rgba(0,240,255,0.6)';
    ctx.lineWidth = 1;
    ctx.strokeRect(vpTL.x, vpTL.y, vpBR.x - vpTL.x, vpBR.y - vpTL.y);
}

// ============================================================
// HUD: HTML Stats panel (for 3D mode — replaces Canvas stats)
// ============================================================

function buildStatsHUD() {
    const hud = document.getElementById('war-hud');
    if (!hud || document.getElementById('war-stats-hud')) return;

    const statsDiv = document.createElement('div');
    statsDiv.id = 'war-stats-hud';
    statsDiv.style.cssText = 'position:absolute; top:48px; left:12px; width:160px; pointer-events:none; background:rgba(10,10,20,0.75); border:1px solid rgba(0,240,255,0.15); padding:6px 8px; font-size:10px; font-family:"JetBrains Mono",monospace; border-radius:3px;';
    hud.appendChild(statsDiv);
}

function updateStatsHUD() {
    const el = document.getElementById('war-stats-hud');
    if (!el) return;

    const targets = getTargets();
    let activeHostiles = 0, activeFriendlies = 0;
    for (const t of Object.values(targets)) {
        const alliance = (t.alliance || '').toLowerCase();
        const status = (t.status || 'active').toLowerCase();
        if (alliance === 'hostile' && status === 'active') activeHostiles++;
        if (alliance === 'friendly' && status !== 'destroyed') activeFriendlies++;
    }

    const rows = [
        { label: 'KILLS', value: warState.stats.kills, color: '#ff2a6d' },
        { label: 'BREACHES', value: warState.stats.breaches, color: '#ff9800' },
        { label: 'DISPATCHES', value: warState.stats.dispatches, color: '#00f0ff' },
        { label: 'HOSTILES', value: activeHostiles, color: activeHostiles > 0 ? '#ff2a6d' : '#05ffa1' },
        { label: 'FRIENDLIES', value: activeFriendlies, color: '#05ffa1' },
    ];

    el.innerHTML = rows.map(r =>
        `<div style="display:flex;justify-content:space-between;padding:1px 0;"><span style="color:rgba(255,255,255,0.4)">${r.label}</span><span style="color:${r.color}">${r.value}</span></div>`
    ).join('');
}

// ============================================================
// Utility
// ============================================================

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============================================================
// Address bar: geocode + satellite tiles + buildings
// ============================================================

function warLoadAddress() {
    const input = document.getElementById('war-address-input');
    const statusEl = document.getElementById('war-address-status');
    if (!input || !input.value.trim()) return;

    const address = input.value.trim();
    if (statusEl) statusEl.textContent = 'Geocoding...';

    if (typeof geo === 'undefined' || !geo.initGeoFromAddress) {
        if (statusEl) statusEl.textContent = 'Geo engine not loaded';
        return;
    }

    // Use geocode-and-set-reference to both geocode AND update the
    // server-side reference point.  This ensures all simulation targets
    // get real lat/lng relative to this address.
    fetch('/api/geo/geocode-and-set-reference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address }),
    })
        .then(r => {
            if (!r.ok) throw new Error(`Geocoding failed: HTTP ${r.status}`);
            return r.json();
        })
        .then(data => {
            // Initialize frontend geo engine
            geo.initGeo(data.lat, data.lng);

            if (statusEl) statusEl.textContent = data.display_name || address;
            warAddAlert(`Map: ${data.display_name || address}`, 'info');

            // Load satellite tiles + buildings using shared helper
            _loadMapData(data.lat, data.lng);
        })
        .catch(err => {
            if (statusEl) statusEl.textContent = 'Geocoding failed';
            warAddAlert('Geocoding failed: ' + (err.message || err), 'hostile');
        });
}

function _compositeTiles(tiles, radiusMeters) {
    if (tiles.length === 0) return null;

    // Find bounds in game coords
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const t of tiles) {
        if (t.bounds.minX < minX) minX = t.bounds.minX;
        if (t.bounds.minY < minY) minY = t.bounds.minY;
        if (t.bounds.maxX > maxX) maxX = t.bounds.maxX;
        if (t.bounds.maxY > maxY) maxY = t.bounds.maxY;
    }

    const rangeX = maxX - minX;
    const rangeY = maxY - minY;
    if (rangeX <= 0 || rangeY <= 0) return null;

    // Target resolution: 2048px or less
    const pixelsPerMeter = Math.min(2048 / Math.max(rangeX, rangeY), 10);
    const canvasW = Math.ceil(rangeX * pixelsPerMeter);
    const canvasH = Math.ceil(rangeY * pixelsPerMeter);

    const canvas = document.createElement('canvas');
    canvas.width = canvasW;
    canvas.height = canvasH;
    const ctx = canvas.getContext('2d');

    // Fill with ground color
    ctx.fillStyle = '#0a0a12';
    ctx.fillRect(0, 0, canvasW, canvasH);

    for (const t of tiles) {
        const dx = (t.bounds.minX - minX) / rangeX * canvasW;
        // Y is flipped: maxY is north (top of canvas)
        const dy = (maxY - t.bounds.maxY) / rangeY * canvasH;
        const dw = (t.bounds.maxX - t.bounds.minX) / rangeX * canvasW;
        const dh = (t.bounds.maxY - t.bounds.minY) / rangeY * canvasH;

        ctx.drawImage(t.image, dx, dy, dw, dh);
    }

    return canvas;
}

// Bind Enter key in address input
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('war-address-input');
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                warLoadAddress();
            }
            // Stop propagation so war.js key handler doesn't fire
            e.stopPropagation();
        });
    }
});

// ============================================================
// Mode selector: SIM / LIVE
// ============================================================

function warSetSimMode(mode) {
    fetch('/api/amy/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
    })
    .then(r => r.ok ? r.json() : Promise.reject('Mode switch failed'))
    .then(data => {
        _updateModeSelector(data.mode);
        warAddAlert(`Mode: ${data.mode.toUpperCase()}`, 'info');
    })
    .catch(err => {
        console.error('[WAR] Mode switch failed:', err);
        warAddAlert('Mode switch failed', 'hostile');
    });
}

function _updateModeSelector(mode) {
    const simBtn = document.getElementById('war-mode-sim');
    const liveBtn = document.getElementById('war-mode-live');
    if (simBtn) simBtn.classList.toggle('active', mode === 'sim');
    if (liveBtn) liveBtn.classList.toggle('active', mode === 'live');
}

function warHandleModeChange(data) {
    if (data && data.mode) {
        _updateModeSelector(data.mode);
        warAddAlert(`Mode changed: ${data.mode.toUpperCase()}`, 'info');
    }
}

// Fetch initial mode on War Room init
function _fetchInitialMode() {
    fetch('/api/amy/mode')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (data && data.mode) _updateModeSelector(data.mode);
        })
        .catch(() => {});
}

// Load geo reference from server and auto-initialize the map.
// If the server has a configured reference (from .env MAP_CENTER_LAT/LNG),
// this initializes the frontend geo engine, populates the address bar,
// and loads satellite tiles + building footprints.
function _loadGeoReference() {
    if (typeof geo === 'undefined') return;

    fetch('/api/geo/reference')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data || !data.initialized) return;

            // Initialize frontend geo engine with the server's reference
            geo.initGeo(data.lat, data.lng);

            // Update address bar to show the reference
            const input = document.getElementById('war-address-input');
            const statusEl = document.getElementById('war-address-status');
            if (input && !input.value.trim()) {
                input.value = `${data.lat.toFixed(6)}, ${data.lng.toFixed(6)}`;
            }
            if (statusEl) statusEl.textContent = `Reference: ${data.lat.toFixed(6)}, ${data.lng.toFixed(6)}`;

            warAddAlert(`Geo reference loaded: ${data.lat.toFixed(4)}, ${data.lng.toFixed(4)}`, 'info');

            // Load satellite tiles and buildings
            _loadMapData(data.lat, data.lng);
        })
        .catch(err => {
            console.warn('[WAR] Geo reference fetch failed:', err);
        });
}

// Load satellite tiles + building footprints for the given center.
// Called from _loadGeoReference() (auto-init) or warLoadAddress() (manual).
function _loadMapData(lat, lng) {
    const radiusMeters = 200;
    const zoom = 19;

    geo.loadSatelliteTiles(lat, lng, radiusMeters, zoom)
        .then(tiles => {
            if (tiles.length === 0) return;
            const canvas = _compositeTiles(tiles, radiusMeters);
            if (canvas && typeof war3dSetGroundTexture === 'function') {
                war3dSetGroundTexture(canvas);
            }
            warAddAlert(`Loaded ${tiles.length} satellite tiles`, 'info');
        })
        .catch(err => {
            console.error('[WAR] Satellite tiles failed:', err);
            warAddAlert('Satellite tiles failed', 'hostile');
        });

    geo.loadBuildings(lat, lng, radiusMeters)
        .then(buildings => {
            if (buildings.length > 0 && typeof war3dAddBuildings === 'function') {
                war3dAddBuildings(buildings);
                warAddAlert(`Loaded ${buildings.length} buildings`, 'info');
            }
        })
        .catch(err => {
            console.error('[WAR] Buildings failed:', err);
        });
}

// ============================================================
// Expose globally
// ============================================================

window.initWarView = initWarView;
window.destroyWarView = destroyWarView;
window.warHandleZoneViolation = warHandleZoneViolation;
window.warHandleThreatEscalation = warHandleThreatEscalation;
window.warHandleDispatch = warHandleDispatch;
window.warHandleAmySpeech = warHandleAmySpeech;
window.warHandleAmyThought = warHandleAmyThought;
window.warHandleSimTelemetry = warHandleSimTelemetry;
window.warHandleTargetNeutralized = warHandleTargetNeutralized;
window.selectPaletteItem = selectPaletteItem;
// Exposed for gamepad input handler
window.warState = warState;
window.setWarMode = setWarMode;
window.cycleTargets = cycleTargets;
window.centerOnSelected = centerOnSelected;
window.getTargets = getTargets;
window.getTargetPosition = getTargetPosition;
window.updateUnitInfo = updateUnitInfo;
// Address bar + mode selector
window.warLoadAddress = warLoadAddress;
window.warSetSimMode = warSetSimMode;
window.warHandleModeChange = warHandleModeChange;
