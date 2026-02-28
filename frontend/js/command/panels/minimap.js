// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Minimap Panel
// Tactical overview panel showing all units, zones, and camera viewport.
// Renders via a dedicated canvas. Click to pan the main map.
// Fully managed by PanelManager: resizable, draggable, togglable.

import { EventBus } from '../events.js';
import { TritiumStore } from '../store.js';

const ALLIANCE_COLORS = {
    friendly: '#05ffa1',
    hostile:  '#ff2a6d',
    neutral:  '#00a0ff',
    unknown:  '#fcee0a',
};

export const MinimapPanelDef = {
    id: 'minimap',
    title: 'MINIMAP',
    defaultPosition: { x: -1, y: -1 }, // sentinel: position in _positionBottomRight()
    defaultSize: { w: 220, h: 220 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'minimap-panel-inner';
        el.style.cssText = 'width:100%;height:100%;position:relative;overflow:hidden;';

        const canvas = document.createElement('canvas');
        canvas.id = 'minimap-canvas';
        canvas.style.cssText = 'width:100%;height:100%;display:block;';
        el.appendChild(canvas);

        return el;
    },

    mount(bodyEl, panel) {
        const canvas = bodyEl.querySelector('#minimap-canvas');
        if (!canvas) return;

        // Size canvas buffer to match layout
        _sizeCanvas(canvas, bodyEl);

        // Store reference for map.js to find
        MinimapPanelDef._canvas = canvas;
        MinimapPanelDef._ctx = canvas.getContext('2d');
        MinimapPanelDef._panel = panel;

        // Click-to-pan
        canvas.addEventListener('mousedown', _onMinimapMouseDown);
        canvas.addEventListener('mousemove', _onMinimapMouseMove);

        // Position at bottom-right if sentinel position
        if (panel.x === -1 && panel.y === -1) {
            _positionBottomRight(panel);
        }

        // Emit event so map.js can pick up the new canvas
        EventBus.emit('minimap:mounted', { canvas });
    },

    unmount(bodyEl) {
        const canvas = bodyEl.querySelector('#minimap-canvas');
        if (canvas) {
            canvas.removeEventListener('mousedown', _onMinimapMouseDown);
            canvas.removeEventListener('mousemove', _onMinimapMouseMove);
        }
        MinimapPanelDef._canvas = null;
        MinimapPanelDef._ctx = null;
        MinimapPanelDef._panel = null;
        EventBus.emit('minimap:unmounted');
    },

    onResize(w, h) {
        const canvas = MinimapPanelDef._canvas;
        if (canvas) {
            const body = canvas.parentElement;
            if (body) _sizeCanvas(canvas, body);
        }
    },

    // Public accessors for map.js
    _canvas: null,
    _ctx: null,
    _panel: null,

    getCanvas() { return this._canvas; },
    getContext() { return this._ctx; },
};

// ---- Canvas sizing ----

function _sizeCanvas(canvas, container) {
    const rect = container.getBoundingClientRect();
    const w = Math.max(1, Math.floor(rect.width));
    const h = Math.max(1, Math.floor(rect.height));
    if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
    }
}

// ---- Position helper ----

function _positionBottomRight(panel) {
    const container = panel.manager?.container;
    if (!container) return;
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    panel.setPosition(cw - panel.w - 8, ch - panel.h - 8);
}

// ---- Click-to-pan ----

let _dragging = false;

function _onMinimapMouseDown(e) {
    _dragging = true;
    _panToClick(e);
}

function _onMinimapMouseMove(e) {
    if (!(e.buttons & 1)) { _dragging = false; return; }
    if (_dragging) _panToClick(e);
}

function _panToClick(e) {
    const canvas = MinimapPanelDef._canvas;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    // Get operational bounds from TritiumStore or compute from units
    const ob = _getOperationalBounds();
    const obRangeX = ob.maxX - ob.minX;
    const obRangeY = ob.maxY - ob.minY;
    const wx = ob.minX + (mx / canvas.width) * obRangeX;
    const wy = ob.maxY - (my / canvas.height) * obRangeY;

    // Set camera target via store or event
    const cam = TritiumStore.get('map.viewport') || {};
    TritiumStore.set('map.viewport', {
        ...cam,
        targetX: wx,
        targetY: wy,
    });
    EventBus.emit('minimap:pan', { x: wx, y: wy });
}

function _getOperationalBounds() {
    const units = TritiumStore.units;
    let minX = -100, maxX = 100, minY = -100, maxY = 100;

    if (units && units.size > 0) {
        minX = Infinity; maxX = -Infinity;
        minY = Infinity; maxY = -Infinity;
        for (const [, unit] of units) {
            const pos = unit.position;
            if (!pos || pos.x === undefined) continue;
            if (pos.x < minX) minX = pos.x;
            if (pos.x > maxX) maxX = pos.x;
            if (pos.y < minY) minY = pos.y;
            if (pos.y > maxY) maxY = pos.y;
        }
        // Ensure minimum extent
        if (maxX - minX < 50) { minX -= 25; maxX += 25; }
        if (maxY - minY < 50) { minY -= 25; maxY += 25; }
        // Add padding
        const padX = (maxX - minX) * 0.1;
        const padY = (maxY - minY) * 0.1;
        minX -= padX; maxX += padX;
        minY -= padY; maxY += padY;
    }

    return { minX, maxX, minY, maxY };
}


// ---- Drawing (called from map.js render loop) ----

/**
 * Draw the minimap contents onto the panel canvas.
 * Called by map.js _drawMinimap() when the panel canvas is available.
 * @param {Object} opts - { cam, zones, canvas, dpr }
 */
export function drawMinimapContent(opts) {
    const canvas = MinimapPanelDef._canvas;
    const ctx = MinimapPanelDef._ctx;
    if (!canvas || !ctx) return;

    const mmW = canvas.width;
    const mmH = canvas.height;
    if (mmW === 0 || mmH === 0) return;

    // Clear
    ctx.fillStyle = 'rgba(10, 10, 20, 0.92)';
    ctx.fillRect(0, 0, mmW, mmH);

    // Border
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.25)';
    ctx.lineWidth = 1;
    ctx.strokeRect(0, 0, mmW, mmH);

    // Dynamic bounds
    const ob = _getOperationalBounds();
    const obRangeX = ob.maxX - ob.minX;
    const obRangeY = ob.maxY - ob.minY;

    function wToMM(wx, wy) {
        const mmx = ((wx - ob.minX) / obRangeX) * mmW;
        const mmy = ((ob.maxY - wy) / obRangeY) * mmH;
        return { x: mmx, y: mmy };
    }

    // Zones
    const zones = opts?.zones || [];
    for (const zone of zones) {
        const zpos = zone.position || {};
        const zx = zpos.x || 0;
        const zy = zpos.z !== undefined ? zpos.z : (zpos.y || 0);
        const zr = ((zone.properties && zone.properties.radius) || 10) / obRangeX * mmW;
        const zmp = wToMM(zx, zy);
        const isRestricted = (zone.type || '').includes('restricted');
        ctx.fillStyle = isRestricted ? 'rgba(255, 42, 109, 0.15)' : 'rgba(0, 240, 255, 0.08)';
        ctx.beginPath();
        ctx.arc(zmp.x, zmp.y, zr, 0, Math.PI * 2);
        ctx.fill();
    }

    // Units as colored dots
    const units = TritiumStore.units;
    if (units) {
        for (const [, unit] of units) {
            const pos = unit.position;
            if (!pos || pos.x === undefined) continue;
            const mp = wToMM(pos.x, pos.y);
            const alliance = (unit.alliance || 'unknown').toLowerCase();
            const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
            const status = (unit.status || 'active').toLowerCase();
            const isNeutralized = status === 'neutralized' || status === 'eliminated';

            ctx.fillStyle = color;
            ctx.globalAlpha = isNeutralized ? 0.3 : 1.0;
            ctx.beginPath();
            ctx.arc(mp.x, mp.y, 2.5, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.globalAlpha = 1.0;
    }

    // Camera viewport rectangle
    // Option A: viewportBounds in game coords (from MapLibre map.getBounds())
    const vpBounds = opts?.viewportBounds;
    if (vpBounds) {
        const vpTL = wToMM(vpBounds.minX, vpBounds.maxY);
        const vpBR = wToMM(vpBounds.maxX, vpBounds.minY);
        const vpW = vpBR.x - vpTL.x;
        const vpH = vpBR.y - vpTL.y;
        ctx.strokeStyle = 'rgba(0, 240, 255, 0.6)';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(vpTL.x, vpTL.y, vpW, vpH);
    }
    // Option B: legacy Canvas 2D cam + canvas
    else {
        const cam = opts?.cam;
        const mainCanvas = opts?.canvas;
        const dpr = opts?.dpr || 1;
        if (cam && mainCanvas && mainCanvas.width > 0) {
            const cssW = mainCanvas.width / dpr;
            const cssH = mainCanvas.height / dpr;
            const halfW = (cssW / 2) / cam.zoom;
            const halfH = (cssH / 2) / cam.zoom;
            const vpTL = wToMM(cam.x - halfW, cam.y + halfH);
            const vpBR = wToMM(cam.x + halfW, cam.y - halfH);
            const vpW = vpBR.x - vpTL.x;
            const vpH = vpBR.y - vpTL.y;
            ctx.strokeStyle = 'rgba(0, 240, 255, 0.6)';
            ctx.lineWidth = 1.5;
            ctx.strokeRect(vpTL.x, vpTL.y, vpW, vpH);
        }
    }
}
