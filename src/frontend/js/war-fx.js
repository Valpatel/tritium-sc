// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC War Room — Visual Effects & Math Utilities
 * Smooth interpolation, trails, vision cones, scanlines, event log, cinematic camera
 *
 * All functions are GLOBAL (function declarations) for vanilla JS script-tag loading.
 * No modules, no exports, no imports.
 */

// ============================================================
// Math utilities
// ============================================================

function fadeToward(current, target, rate, dt) {
    var diff = target - current;
    if (Math.abs(diff) < 0.01) return target;
    return current + diff * (1 - Math.exp(-rate * dt));
}

function lerpAngle(current, target, rate, dt) {
    var diff = target - current;
    // Normalize to [-180, 180]
    while (diff > 180) diff -= 360;
    while (diff < -180) diff += 360;
    if (Math.abs(diff) < 0.1) return target;
    var result = current + diff * (1 - Math.exp(-rate * dt));
    // Normalize to [0, 360)
    while (result < 0) result += 360;
    while (result >= 360) result -= 360;
    return result;
}

function easeInOut(t) {
    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

// ============================================================
// Trail system
// ============================================================

var _trails = new Map();        // targetId -> [{x, y, time}, ...]
var TRAIL_LIFETIME = 5;         // seconds
var TRAIL_MIN_DIST = 0.5;       // min distance to add new point

function warFxUpdateTrails(targets, dt) {
    var now = performance.now() / 1000;
    for (var tid in targets) {
        if (!targets.hasOwnProperty(tid)) continue;
        var t = targets[tid];
        var pos = { x: t.x !== undefined ? t.x : (t.position ? t.position.x : 0),
                    y: t.y !== undefined ? t.y : (t.position ? t.position.y : 0) };
        var trail = _trails.get(tid);
        if (!trail) { trail = []; _trails.set(tid, trail); }
        // Add point if moved enough
        var last = trail[trail.length - 1];
        if (!last || Math.hypot(pos.x - last.x, pos.y - last.y) > TRAIL_MIN_DIST) {
            trail.push({ x: pos.x, y: pos.y, time: now });
        }
        // Prune old
        while (trail.length > 0 && now - trail[0].time > TRAIL_LIFETIME) trail.shift();
    }
    // Clean up trails for targets that no longer exist
    _trails.forEach(function(trail, tid) {
        if (!targets[tid]) _trails.delete(tid);
    });
}

function warFxDrawTrails(ctx, worldToScreen) {
    var now = performance.now() / 1000;
    _trails.forEach(function(trail, tid) {
        if (trail.length < 2) return;
        var color = _getTrailColor(tid);
        for (var i = 0; i < trail.length; i++) {
            var age = now - trail[i].time;
            var alpha = Math.max(0, 1 - age / TRAIL_LIFETIME) * 0.6;
            var sp = worldToScreen(trail[i].x, trail[i].y);
            ctx.fillStyle = color.replace(')', ', ' + alpha + ')').replace('rgb', 'rgba');
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, 2, 0, Math.PI * 2);
            ctx.fill();
        }
    });
}

// Track alliance for trail coloring
var _trailColors = new Map();

function _getTrailColor(tid) {
    return _trailColors.get(tid) || 'rgb(0, 240, 255)';
}

function _updateTrailColor(tid, alliance) {
    var colors = {
        friendly: 'rgb(5, 255, 161)',
        hostile: 'rgb(255, 42, 109)',
        neutral: 'rgb(0, 160, 255)',
        unknown: 'rgb(252, 238, 10)',
    };
    _trailColors.set(tid, colors[alliance] || colors.unknown);
}

// ============================================================
// Vision cones
// ============================================================

function warFxDrawVisionCones(ctx, worldToScreen, targets, zoom) {
    for (var tid in targets) {
        if (!targets.hasOwnProperty(tid)) continue;
        var t = targets[tid];
        var type = (t.asset_type || '').toLowerCase();
        if (!type.includes('turret') && !type.includes('camera') && !type.includes('sensor')) continue;
        if ((t.alliance || '').toLowerCase() !== 'friendly') continue;

        var pos = { x: t.x !== undefined ? t.x : (t.position ? t.position.x : 0),
                    y: t.y !== undefined ? t.y : (t.position ? t.position.y : 0) };
        var sp = worldToScreen(pos.x, pos.y);
        var heading = t.heading || 0;
        // *12 converts game units to approximate screen pixels at base zoom
        var range = (t.weapon_range || t.fov_range || 15) * zoom * 12;
        var fov = (t.fov_angle || 60) * Math.PI / 180;
        var rad = (90 - heading) * Math.PI / 180;

        ctx.save();
        ctx.translate(sp.x, sp.y);
        ctx.rotate(-rad);

        var gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, range);
        gradient.addColorStop(0, 'rgba(5, 255, 161, 0.15)');
        gradient.addColorStop(1, 'rgba(5, 255, 161, 0.0)');

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.arc(0, 0, range, -fov / 2, fov / 2);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
    }
}

// ============================================================
// CRT scanlines
// ============================================================

function warFxDrawScanlines(ctx, w, h) {
    var t = Date.now() * 0.001;
    var breathe = 0.03 + Math.sin(t * 0.5) * 0.01;
    ctx.fillStyle = 'rgba(0, 0, 0, ' + breathe + ')';
    for (var y = 0; y < h; y += 4) {
        ctx.fillRect(0, y, w, 1);
    }
}

// ============================================================
// Event log
// ============================================================

var _eventLog = [];             // {text, color, time}
var EVENT_LOG_MAX = 8;
var EVENT_LOG_DURATION = 8;     // seconds

function warFxAddEvent(text, color) {
    _eventLog.push({ text: text, color: color || '#00f0ff', time: performance.now() / 1000 });
    if (_eventLog.length > EVENT_LOG_MAX * 2) _eventLog.splice(0, _eventLog.length - EVENT_LOG_MAX);
}

function warFxDrawEventLog(ctx, w, h) {
    var now = performance.now() / 1000;
    var active = _eventLog.filter(function(e) { return now - e.time < EVENT_LOG_DURATION; });
    if (active.length === 0) return;

    var x = 12, startY = h - 20;
    ctx.font = '11px "JetBrains Mono", monospace';
    var visible = active.slice(-EVENT_LOG_MAX);
    for (var i = 0; i < visible.length; i++) {
        var e = visible[visible.length - 1 - i];
        var age = now - e.time;
        var alpha = Math.max(0, 1 - age / EVENT_LOG_DURATION);
        // Handle both rgb() and hex colors
        if (e.color.startsWith('rgb')) {
            ctx.fillStyle = e.color.replace(')', ', ' + alpha + ')').replace('rgb', 'rgba');
        } else {
            ctx.globalAlpha = alpha;
            ctx.fillStyle = e.color;
        }
        ctx.fillText(e.text, x, startY - i * 16);
    }
    ctx.globalAlpha = 1.0;
}

// ============================================================
// Cinematic camera
// ============================================================

var _cinema = {
    enabled: false,
    shot: 'overview',
    timer: 0,
    duration: 8,
    targetId: null,
    transitionProgress: 0,
};

function warFxCinematicTick(dt, cam, targets, gameState) {
    if (!_cinema.enabled) return;
    _cinema.timer += dt;
    if (_cinema.timer > _cinema.duration) {
        _cinema.timer = 0;
        _nextShot(targets, gameState);
    }
    _applyShotToCamera(cam, targets, dt);
}

function warFxToggleCinematic() {
    _cinema.enabled = !_cinema.enabled;
    _cinema.timer = 0;
    return _cinema.enabled;
}

function warFxIsCinematic() {
    return _cinema.enabled;
}

function _nextShot(targets, gameState) {
    var hostiles = [];
    if (targets) {
        for (var tid in targets) {
            if (!targets.hasOwnProperty(tid)) continue;
            if ((targets[tid].alliance || '').toLowerCase() === 'hostile') {
                hostiles.push([tid, targets[tid]]);
            }
        }
    }
    var isActive = gameState && (gameState.gameState === 'active' || gameState.phase === 'active');

    if (isActive && hostiles.length > 0) {
        var pick = hostiles[Math.floor(Math.random() * hostiles.length)];
        _cinema.shot = 'follow_unit';
        _cinema.targetId = pick[0];
        _cinema.duration = 5 + Math.random() * 3;
    } else {
        _cinema.shot = 'overview';
        _cinema.targetId = null;
        _cinema.duration = 8 + Math.random() * 4;
    }
}

function _applyShotToCamera(cam, targets, dt) {
    switch (_cinema.shot) {
        case 'follow_unit': {
            var t = targets && targets[_cinema.targetId];
            if (t) {
                var pos = { x: t.x !== undefined ? t.x : (t.position ? t.position.x : 0),
                            y: t.y !== undefined ? t.y : (t.position ? t.position.y : 0) };
                cam.targetX = pos.x;
                cam.targetY = pos.y;
                cam.targetZoom = 2.0;
            } else {
                _cinema.shot = 'overview';
            }
            break;
        }
        case 'overview': {
            cam.targetX = fadeToward(cam.targetX, 0, 0.3, dt);
            cam.targetY = fadeToward(cam.targetY, 0, 0.3, dt);
            cam.targetZoom = 0.7;
            break;
        }
    }
}
