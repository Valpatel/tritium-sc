// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC War Room -- Fog of War + Enhanced Minimap
 * Keyboard: F = toggle fog, N = toggle minimap
 *
 * Fog of War: semi-transparent dark overlay with vision circles cut out
 * around friendly units. Each unit type has a vision radius. Hostiles in
 * fog are dimmer. During SETUP mode shows potential vision coverage.
 *
 * Enhanced Minimap: 200x150 overlay in bottom-right with colored dots,
 * viewport rectangle, pulsing alert dots, and click-to-jump.
 *
 * All functions are GLOBAL (function declarations) for vanilla JS script-tag loading.
 * No modules, no exports, no imports.
 */

// ============================================================
// Vision radii per unit type (world units)
// ============================================================

var FOG_VISION_RADII = {
    turret:  50,
    drone:   60,
    rover:   40,
    camera:  30,
    sensor:  30,
    person:  15,
    default: 20,
};

// ============================================================
// Fog state
// ============================================================

var fogState = {
    fogEnabled: true,
    minimapEnabled: true,
    // Offscreen canvas for fog compositing (avoids per-frame alloc)
    _fogCanvas: null,
    _fogCtx: null,
    // Minimap animation
    _alertPulsePhase: 0,
};

// ============================================================
// Vision radius lookup
// ============================================================

function fogGetVisionRadius(target) {
    // Custom override takes precedence
    if (target.vision_range !== undefined && target.vision_range !== null) {
        return target.vision_range;
    }
    var type = (target.asset_type || '').toLowerCase();
    return FOG_VISION_RADII[type] || FOG_VISION_RADII['default'];
}

// ============================================================
// Build vision map (array of {x, y, r} circles from friendlies)
// ============================================================

function fogBuildVisionMap(targets) {
    var circles = [];
    for (var tid in targets) {
        if (!targets.hasOwnProperty(tid)) continue;
        var t = targets[tid];
        // Only friendly units produce vision
        if ((t.alliance || '').toLowerCase() !== 'friendly') continue;
        // Skip destroyed/neutralized units
        var status = (t.status || 'active').toLowerCase();
        if (status === 'neutralized' || status === 'eliminated' || status === 'destroyed') continue;

        var pos;
        if (t.position && t.position.x !== undefined) {
            pos = { x: t.position.x, y: t.position.y };
        } else {
            pos = { x: t.x, y: t.y };
        }
        if (pos.x === undefined || pos.y === undefined) continue;

        circles.push({
            x: pos.x,
            y: pos.y,
            r: fogGetVisionRadius(t),
            tid: tid,
        });
    }
    return circles;
}

// ============================================================
// Point-in-vision test
// ============================================================

function fogIsPointVisible(px, py, visionCircles) {
    for (var i = 0; i < visionCircles.length; i++) {
        var c = visionCircles[i];
        var dx = px - c.x;
        var dy = py - c.y;
        if (dx * dx + dy * dy <= c.r * c.r) return true;
    }
    return false;
}

// ============================================================
// Draw fog of war on Canvas 2D
// ============================================================

function fogDraw(ctx, canvas, worldToScreen, targets, cam, mode) {
    if (!fogState.fogEnabled) return;

    var w = canvas.width;
    var h = canvas.height;

    // Lazy-init offscreen canvas
    if (!fogState._fogCanvas || fogState._fogCanvas.width !== w || fogState._fogCanvas.height !== h) {
        fogState._fogCanvas = document.createElement('canvas');
        fogState._fogCanvas.width = w;
        fogState._fogCanvas.height = h;
        fogState._fogCtx = fogState._fogCanvas.getContext('2d');
    }

    var fCtx = fogState._fogCtx;

    // Fill the entire offscreen canvas with semi-transparent dark fog
    fCtx.globalCompositeOperation = 'source-over';
    fCtx.fillStyle = 'rgba(5, 5, 15, 0.50)';
    fCtx.fillRect(0, 0, w, h);

    // Build vision circles from friendly units
    var circles = fogBuildVisionMap(targets);

    // In SETUP mode, also include ghost placement vision preview
    // (handled externally via fogAddSetupPreview if needed)

    // Cut out vision circles using destination-out compositing
    fCtx.globalCompositeOperation = 'destination-out';

    var now = Date.now();
    for (var i = 0; i < circles.length; i++) {
        var c = circles[i];
        var sp = worldToScreen(c.x, c.y);
        var sr = c.r * cam.zoom;

        // Radial gradient: fully clear in center, fading to fog at edges
        var grad = fCtx.createRadialGradient(sp.x, sp.y, 0, sp.x, sp.y, sr);
        grad.addColorStop(0, 'rgba(0, 0, 0, 1.0)');
        grad.addColorStop(0.7, 'rgba(0, 0, 0, 0.9)');
        grad.addColorStop(1.0, 'rgba(0, 0, 0, 0.0)');

        fCtx.fillStyle = grad;
        fCtx.beginPath();
        fCtx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
        fCtx.fill();
    }

    // Draw the fog layer onto the main canvas
    fCtx.globalCompositeOperation = 'source-over';
    ctx.drawImage(fogState._fogCanvas, 0, 0);

    // Draw neon glow edges on vision boundaries (cyberpunk effect)
    _fogDrawVisionEdges(ctx, circles, worldToScreen, cam, now);
}

// ============================================================
// Neon edge glow on vision boundaries
// ============================================================

function _fogDrawVisionEdges(ctx, circles, worldToScreen, cam, now) {
    ctx.save();
    var pulse = 0.4 + Math.sin(now * 0.003) * 0.15;

    for (var i = 0; i < circles.length; i++) {
        var c = circles[i];
        var sp = worldToScreen(c.x, c.y);
        var sr = c.r * cam.zoom;

        // Outer glow ring (subtle neon cyan)
        ctx.strokeStyle = 'rgba(0, 240, 255, ' + (pulse * 0.3) + ')';
        ctx.lineWidth = 1.5;
        ctx.shadowColor = '#00f0ff';
        ctx.shadowBlur = 6;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
        ctx.stroke();

        // Inner thin ring
        ctx.strokeStyle = 'rgba(0, 240, 255, ' + (pulse * 0.12) + ')';
        ctx.lineWidth = 0.5;
        ctx.shadowBlur = 0;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, sr * 0.95, 0, Math.PI * 2);
        ctx.stroke();
    }

    ctx.shadowBlur = 0;
    ctx.restore();
}

// ============================================================
// Setup mode: draw preview vision for ghost placement
// ============================================================

function fogDrawSetupPreview(ctx, worldToScreen, cam, ghostX, ghostY, assetType) {
    if (!fogState.fogEnabled) return;

    var r = fogGetVisionRadius({ asset_type: assetType });
    var sp = worldToScreen(ghostX, ghostY);
    var sr = r * cam.zoom;

    ctx.save();
    // Dashed circle showing potential vision coverage
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.35)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    // Shaded fill showing coverage area
    var grad = ctx.createRadialGradient(sp.x, sp.y, 0, sp.x, sp.y, sr);
    grad.addColorStop(0, 'rgba(0, 240, 255, 0.06)');
    grad.addColorStop(1, 'rgba(0, 240, 255, 0.01)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
    ctx.fill();

    // Range label
    ctx.fillStyle = 'rgba(0, 240, 255, 0.5)';
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(r + 'm VISION', sp.x, sp.y - sr - 6);

    ctx.restore();
}

// ============================================================
// Enhanced Minimap
// ============================================================

var MINIMAP_W = 200;
var MINIMAP_H = 150;
var MINIMAP_PAD = 12;

// Colors
var MINIMAP_COLORS = {
    friendly: '#05ffa1',
    hostile:  '#ff2a6d',
    neutral:  '#00a0ff',
    unknown:  '#fcee0a',
    bg:       'rgba(5, 5, 15, 0.88)',
    border:   'rgba(0, 240, 255, 0.30)',
    viewport: 'rgba(0, 240, 255, 0.6)',
    alertPulse: '#00f0ff',
};

function minimapWorldToMinimap(wx, wy, mmW, mmH, mapMin, mapMax) {
    var range = mapMax - mapMin;
    return {
        x: ((wx - mapMin) / range) * mmW,
        y: ((mapMax - wy) / range) * mmH,
    };
}

function minimapGetViewportRect(cam, canvasW, canvasH, mmW, mmH, mapMin, mapMax) {
    var halfWWorld = (canvasW / 2) / cam.zoom;
    var halfHWorld = (canvasH / 2) / cam.zoom;
    var tl = minimapWorldToMinimap(cam.x - halfWWorld, cam.y + halfHWorld, mmW, mmH, mapMin, mapMax);
    var br = minimapWorldToMinimap(cam.x + halfWWorld, cam.y - halfHWorld, mmW, mmH, mapMin, mapMax);
    return {
        x: tl.x,
        y: tl.y,
        w: br.x - tl.x,
        h: br.y - tl.y,
    };
}

function fogDrawMinimap(ctx, canvas, targets, cam, mapMin, mapMax, zones, alerts, visionCircles) {
    if (!fogState.minimapEnabled) return;

    var mmX = canvas.width - MINIMAP_W - MINIMAP_PAD;
    var mmY = canvas.height - MINIMAP_H - MINIMAP_PAD;

    // Update animation
    fogState._alertPulsePhase += 0.05;

    // Background
    ctx.save();
    ctx.fillStyle = MINIMAP_COLORS.bg;
    ctx.fillRect(mmX, mmY, MINIMAP_W, MINIMAP_H);

    // Clip to minimap bounds for content
    ctx.beginPath();
    ctx.rect(mmX, mmY, MINIMAP_W, MINIMAP_H);
    ctx.clip();

    var range = mapMax - mapMin;

    // Helper: world to minimap screen coords (includes mmX/mmY offset)
    function wToMM(wx, wy) {
        return {
            x: mmX + ((wx - mapMin) / range) * MINIMAP_W,
            y: mmY + ((mapMax - wy) / range) * MINIMAP_H,
        };
    }

    // Draw fog overlay on minimap (dimmed areas outside vision)
    if (fogState.fogEnabled && visionCircles && visionCircles.length > 0) {
        // Dark overlay
        ctx.fillStyle = 'rgba(5, 5, 15, 0.4)';
        ctx.fillRect(mmX, mmY, MINIMAP_W, MINIMAP_H);

        // Cut out vision circles
        ctx.globalCompositeOperation = 'destination-out';
        for (var vi = 0; vi < visionCircles.length; vi++) {
            var vc = visionCircles[vi];
            var vmp = wToMM(vc.x, vc.y);
            var vr = (vc.r / range) * MINIMAP_W;
            ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
            ctx.beginPath();
            ctx.arc(vmp.x, vmp.y, vr, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.globalCompositeOperation = 'source-over';
    }

    // Draw zones
    if (zones) {
        for (var zi = 0; zi < zones.length; zi++) {
            var zone = zones[zi];
            var zpos = zone.position || {};
            var zx = zpos.x || 0;
            var zy = zpos.z !== undefined ? zpos.z : (zpos.y || 0);
            var zr = ((zone.properties && zone.properties.radius) || 10) / range * MINIMAP_W;
            var zmp = wToMM(zx, zy);
            var isRestricted = (zone.type || '').includes('restricted');
            ctx.fillStyle = isRestricted ? 'rgba(255, 42, 109, 0.15)' : 'rgba(0, 240, 255, 0.08)';
            ctx.beginPath();
            ctx.arc(zmp.x, zmp.y, zr, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    // Draw target dots
    var hasActiveAlert = false;
    for (var tid in targets) {
        if (!targets.hasOwnProperty(tid)) continue;
        var t = targets[tid];
        var pos;
        if (t.position && t.position.x !== undefined) {
            pos = { x: t.position.x, y: t.position.y };
        } else {
            pos = { x: t.x, y: t.y };
        }
        if (pos.x === undefined || pos.y === undefined) continue;

        var mp = wToMM(pos.x, pos.y);
        var alliance = (t.alliance || 'unknown').toLowerCase();
        var color = MINIMAP_COLORS[alliance] || MINIMAP_COLORS.unknown;
        var status = (t.status || 'active').toLowerCase();
        var dotR = 2.5;

        // Dim neutralized/eliminated
        if (status === 'neutralized' || status === 'eliminated' || status === 'destroyed') {
            ctx.globalAlpha = 0.3;
            dotR = 1.5;
        }

        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(mp.x, mp.y, dotR, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1.0;

        // Active hostile alert pulse
        if (alliance === 'hostile' && status === 'active') {
            hasActiveAlert = true;
            var pulseR = dotR + 2 + Math.sin(fogState._alertPulsePhase * 2) * 1.5;
            var pulseAlpha = 0.3 + Math.sin(fogState._alertPulsePhase * 2) * 0.2;
            ctx.strokeStyle = 'rgba(255, 42, 109, ' + pulseAlpha + ')';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(mp.x, mp.y, pulseR, 0, Math.PI * 2);
            ctx.stroke();
        }
    }

    // Draw alert pulsing dots
    if (alerts && alerts.length > 0) {
        var now = Date.now();
        for (var ai = 0; ai < alerts.length; ai++) {
            var alert = alerts[ai];
            if (!alert.position) continue;
            var age = (now - (alert.time || 0)) / 1000;
            if (age > 10) continue; // only show recent alerts
            var amp = wToMM(alert.position.x, alert.position.y);
            var apulse = 3 + Math.sin(fogState._alertPulsePhase * 3 + ai) * 2;
            var aalpha = Math.max(0, 0.6 - age * 0.06);
            ctx.fillStyle = 'rgba(0, 240, 255, ' + aalpha + ')';
            ctx.beginPath();
            ctx.arc(amp.x, amp.y, apulse, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    ctx.restore(); // unclip

    // Viewport rectangle (drawn outside clip to allow clean edges)
    var vpRect = minimapGetViewportRect(cam, canvas.width, canvas.height, MINIMAP_W, MINIMAP_H, mapMin, mapMax);
    ctx.strokeStyle = MINIMAP_COLORS.viewport;
    ctx.lineWidth = 1;
    ctx.strokeRect(mmX + vpRect.x, mmY + vpRect.y, vpRect.w, vpRect.h);

    // Border
    ctx.strokeStyle = MINIMAP_COLORS.border;
    ctx.lineWidth = 1;
    ctx.strokeRect(mmX, mmY, MINIMAP_W, MINIMAP_H);

    // Label
    ctx.fillStyle = 'rgba(0, 240, 255, 0.4)';
    ctx.font = '8px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.fillText('TACTICAL MAP', mmX + 4, mmY - 3);
}

// ============================================================
// Minimap click-to-jump (returns world coords or null)
// ============================================================

function fogMinimapHitTest(sx, sy, canvasW, canvasH, mapMin, mapMax) {
    var mmX = canvasW - MINIMAP_W - MINIMAP_PAD;
    var mmY = canvasH - MINIMAP_H - MINIMAP_PAD;

    if (sx >= mmX && sx <= mmX + MINIMAP_W && sy >= mmY && sy <= mmY + MINIMAP_H) {
        var range = mapMax - mapMin;
        var wx = mapMin + ((sx - mmX) / MINIMAP_W) * range;
        var wy = mapMax - ((sy - mmY) / MINIMAP_H) * range;
        return { x: wx, y: wy };
    }
    return null;
}
