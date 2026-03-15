// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Operator Cursors — renders other operators' cursor positions on the map
//
// When multiple operators are connected, shows their cursor positions
// as colored dots with username labels. Sends the local user's cursor
// position via WebSocket when it moves on the map.

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

let _canvas = null;
let _ctx = null;
let _animFrame = null;
let _sessionInfo = null;
let _wsManager = null;
let _lastSent = 0;
const SEND_THROTTLE_MS = 200;
const CURSOR_SIZE = 8;
const LABEL_FONT = '11px monospace';

/**
 * Initialize the cursor sharing overlay.
 * @param {HTMLCanvasElement} canvas - overlay canvas on top of the map
 * @param {Object} wsManager - WebSocketManager instance for sending cursor updates
 * @param {Object} sessionInfo - {session_id, username, display_name, role, color}
 */
export function initCursorSharing(canvas, wsManager, sessionInfo) {
    _canvas = canvas;
    _ctx = canvas.getContext('2d');
    _wsManager = wsManager;
    _sessionInfo = sessionInfo;

    // Listen for map mouse moves and send cursor position
    EventBus.on('map:mousemove', _onMapMouseMove);

    // Start render loop
    _startRender();

    return { destroy: destroyCursorSharing };
}

function _onMapMouseMove(data) {
    if (!_wsManager || !_sessionInfo) return;

    const now = Date.now();
    if (now - _lastSent < SEND_THROTTLE_MS) return;
    _lastSent = now;

    const lat = data.lat || data.latlng?.lat;
    const lng = data.lng || data.latlng?.lng;
    if (lat == null || lng == null) return;

    // Include viewport data for operator presence on map
    const msg = {
        type: 'cursor_update',
        session_id: _sessionInfo.session_id,
        username: _sessionInfo.username,
        display_name: _sessionInfo.display_name,
        role: _sessionInfo.role,
        color: _sessionInfo.color,
        lat,
        lng,
    };

    // Attach viewport bounds and zoom if available from store
    const mapZoom = TritiumStore.get('map.zoom');
    const mapBounds = TritiumStore.get('map.bounds');
    if (mapZoom != null) msg.zoom = mapZoom;
    if (mapBounds) msg.bounds = mapBounds; // {north, south, east, west}

    _wsManager.send(msg);
}

function _startRender() {
    function frame() {
        _renderCursors();
        _animFrame = requestAnimationFrame(frame);
    }
    _animFrame = requestAnimationFrame(frame);
}

function _renderCursors() {
    if (!_ctx || !_canvas) return;

    const cursors = TritiumStore.getOperatorCursors();
    const w = _canvas.width;
    const h = _canvas.height;

    // Clear the overlay
    _ctx.clearRect(0, 0, w, h);

    if (cursors.length === 0) return;

    // We need a function to convert lat/lng to screen coordinates.
    // This depends on the map implementation. We emit an event to get
    // the projection, or use a stored function.
    const project = TritiumStore.get('map.projectLatLng');
    if (!project) return;

    for (const cursor of cursors) {
        if (cursor.lat == null || cursor.lng == null) continue;

        let screenPos;
        try {
            screenPos = project(cursor.lat, cursor.lng);
        } catch {
            continue;
        }
        if (!screenPos) continue;

        const x = screenPos.x;
        const y = screenPos.y;
        if (x < -50 || x > w + 50 || y < -50 || y > h + 50) continue;

        const color = cursor.color || '#00f0ff';
        const name = cursor.display_name || cursor.username || '?';

        // Draw cursor dot
        _ctx.beginPath();
        _ctx.arc(x, y, CURSOR_SIZE, 0, Math.PI * 2);
        _ctx.fillStyle = color + '44';
        _ctx.fill();
        _ctx.strokeStyle = color;
        _ctx.lineWidth = 2;
        _ctx.stroke();

        // Draw inner dot
        _ctx.beginPath();
        _ctx.arc(x, y, 3, 0, Math.PI * 2);
        _ctx.fillStyle = color;
        _ctx.fill();

        // Draw username label
        _ctx.font = LABEL_FONT;
        _ctx.fillStyle = color;
        _ctx.textAlign = 'left';
        const labelX = x + CURSOR_SIZE + 4;
        const labelY = y + 4;

        // Background for readability
        const textWidth = _ctx.measureText(name).width;
        _ctx.fillStyle = '#0a0a0fcc';
        _ctx.fillRect(labelX - 2, labelY - 11, textWidth + 4, 14);
        _ctx.fillStyle = color;
        _ctx.fillText(name, labelX, labelY);

        // Draw viewport rectangle if bounds are available
        if (cursor.bounds && project) {
            _renderViewportRect(project, cursor, color, name, w, h);
        }
    }
}

/**
 * Render an operator's viewport as a dashed rectangle on the map.
 * Shows where each operator is looking for coordination awareness.
 */
function _renderViewportRect(project, cursor, color, name, canvasW, canvasH) {
    const b = cursor.bounds;
    if (!b || b.north == null || b.south == null || b.east == null || b.west == null) return;

    let nw, se;
    try {
        nw = project(b.north, b.west);
        se = project(b.south, b.east);
    } catch {
        return;
    }
    if (!nw || !se) return;

    const rx = Math.min(nw.x, se.x);
    const ry = Math.min(nw.y, se.y);
    const rw = Math.abs(se.x - nw.x);
    const rh = Math.abs(se.y - nw.y);

    // Skip if viewport rect is too large (covers most of screen) or too small
    if (rw < 10 || rh < 10) return;
    if (rw > canvasW * 0.95 && rh > canvasH * 0.95) return;

    // Draw dashed rectangle
    _ctx.setLineDash([6, 4]);
    _ctx.strokeStyle = color + '88';
    _ctx.lineWidth = 1.5;
    _ctx.strokeRect(rx, ry, rw, rh);
    _ctx.setLineDash([]);

    // Fill with very faint tint
    _ctx.fillStyle = color + '0a';
    _ctx.fillRect(rx, ry, rw, rh);

    // Label at top of viewport rect
    const roleLabel = cursor.role || 'observer';
    const viewLabel = cursor.viewport_label || `${name} [${roleLabel}]`;
    _ctx.font = '10px monospace';
    const lblWidth = _ctx.measureText(viewLabel).width;
    const lblX = rx + 4;
    const lblY = ry + 12;

    _ctx.fillStyle = '#0a0a0fcc';
    _ctx.fillRect(lblX - 2, lblY - 10, lblWidth + 4, 13);
    _ctx.fillStyle = color + 'cc';
    _ctx.fillText(viewLabel, lblX, lblY);
}

export function destroyCursorSharing() {
    EventBus.off('map:mousemove', _onMapMouseMove);
    if (_animFrame) {
        cancelAnimationFrame(_animFrame);
        _animFrame = null;
    }
    _canvas = null;
    _ctx = null;
    _wsManager = null;
    _sessionInfo = null;
}
