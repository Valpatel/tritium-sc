// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * label-collision.js -- Label collision avoidance for the tactical map.
 *
 * Uses an occupancy bitmap at 1/4 canvas resolution to resolve label
 * positions without overlap.  Priority: selected > hostile > friendly >
 * neutral > dead.  When the preferred position (below the unit) is
 * occluded, the label walks through 7 alternates and sets `displaced`
 * so the renderer can draw a leader line.
 *
 * Performance budget: 50 units * 8 candidates * ~80 bitmap cells =
 * ~32k ops/frame, well under 0.5 ms.
 */

// ---- constants --------------------------------------------------------

const FONT_FAMILY = '"JetBrains Mono", monospace';
const BG_PAD      = 3;      // px padding inside label background box
const BMP_SCALE   = 0.25;   // bitmap is 1/4 canvas resolution
const BODY_RADIUS = 2;      // unit body occupy radius in bitmap cells

// Priority weights (lower = higher priority)
const PRIORITY = {
    selected:    0,
    hostile:     1,
    friendly:    2,
    neutral:     3,
    dead:        4,
};

// ---- offscreen text measurement canvas --------------------------------

let _measureCanvas = null;
let _measureCtx    = null;

function _getCtx() {
    if (!_measureCtx) {
        _measureCanvas        = document.createElement('canvas');
        _measureCanvas.width  = 1;
        _measureCanvas.height = 1;
        _measureCtx           = _measureCanvas.getContext('2d');
    }
    return _measureCtx;
}

// ---- bitmap helpers ---------------------------------------------------

/**
 * Mark a rectangle of cells as occupied.
 * Coordinates are in bitmap space (already scaled by BMP_SCALE).
 */
function _markRect(bitmap, bw, bh, x, y, w, h) {
    const x0 = Math.max(0, x | 0);
    const y0 = Math.max(0, y | 0);
    const x1 = Math.min(bw, (x + w) | 0);
    const y1 = Math.min(bh, (y + h) | 0);
    for (let row = y0; row < y1; row++) {
        const base = row * bw;
        for (let col = x0; col < x1; col++) {
            bitmap[base + col] = 1;
        }
    }
}

/**
 * Test whether any cell inside the rectangle is already occupied.
 * Returns true if there is a collision.
 */
function _testRect(bitmap, bw, bh, x, y, w, h) {
    const x0 = Math.max(0, x | 0);
    const y0 = Math.max(0, y | 0);
    const x1 = Math.min(bw, (x + w) | 0);
    const y1 = Math.min(bh, (y + h) | 0);
    for (let row = y0; row < y1; row++) {
        const base = row * bw;
        for (let col = x0; col < x1; col++) {
            if (bitmap[base + col]) return true;
        }
    }
    return false;
}

// ---- priority sorting -------------------------------------------------

function _priorityOf(entry, selectedId) {
    if (entry.id === selectedId)                           return PRIORITY.selected;
    const s = (entry.status || '').toLowerCase();
    if (s === 'dead' || s === 'neutralized')               return PRIORITY.dead;
    const a = (entry.alliance || '').toLowerCase();
    if (a === 'hostile')                                   return PRIORITY.hostile;
    if (a === 'friendly')                                  return PRIORITY.friendly;
    return PRIORITY.neutral;
}

// ---- candidate offsets ------------------------------------------------

/**
 * Return 8 candidate label positions relative to the unit screen center.
 * Each entry is [dx, dy] where dx/dy are pixel offsets for the label's
 * top-left corner, given the label size (tw x th) and a base unit size.
 */
function _candidates(tw, th) {
    const gapY  = 14;             // vertical gap below/above unit body
    const gapX  = 12;             // horizontal gap beside unit body
    const halfW = tw / 2;

    return [
        // 0: below (preferred)
        [-halfW,           gapY],
        // 1: above
        [-halfW,           -(th + gapY - 6)],
        // 2: right
        [gapX,             -th / 2],
        // 3: left
        [-(tw + gapX),     -th / 2],
        // 4: bottom-right
        [gapX,             gapY],
        // 5: bottom-left
        [-(tw + gapX),     gapY],
        // 6: top-right
        [gapX,             -(th + gapY - 6)],
        // 7: top-left
        [-(tw + gapX),     -(th + gapY - 6)],
    ];
}

// ---- main export ------------------------------------------------------

/**
 * Resolve label positions to avoid overlap using an occupancy bitmap.
 *
 * @param {Array}        entries       - { id, text, worldX, worldY, alliance, status, isSelected }
 * @param {number}       canvasW       - Canvas width in CSS pixels
 * @param {number}       canvasH       - Canvas height in CSS pixels
 * @param {number}       zoom          - Current camera zoom level
 * @param {string|null}  selectedId    - Currently selected unit ID (highest priority)
 * @param {Function}     worldToScreen - (wx, wy) => { x, y }
 * @returns {Array} { id, text, labelX, labelY, anchorX, anchorY,
 *                     displaced, bgWidth, bgHeight, alliance, status }
 */
export function resolveLabels(entries, canvasW, canvasH, zoom, selectedId, worldToScreen) {
    if (!entries || entries.length === 0) return [];

    // -- font size (matches map.js formula) --
    const fontSize = Math.max(9, 11 * Math.min(zoom, 2));
    const ctx      = _getCtx();
    ctx.font       = `${fontSize}px ${FONT_FAMILY}`;

    // -- bitmap allocation --
    const bw     = Math.max(1, (canvasW * BMP_SCALE) | 0);
    const bh     = Math.max(1, (canvasH * BMP_SCALE) | 0);
    const bitmap = new Uint8Array(bw * bh);  // initialized to 0

    // -- pre-compute screen positions and text metrics --
    const items = [];
    for (let i = 0; i < entries.length; i++) {
        const e  = entries[i];
        const sp = worldToScreen(e.worldX, e.worldY);

        // Skip units entirely off-screen (generous margin)
        if (sp.x < -100 || sp.x > canvasW + 100 ||
            sp.y < -100 || sp.y > canvasH + 100) continue;

        const tw = ctx.measureText(e.text).width + BG_PAD * 2;
        const th = fontSize + BG_PAD * 2;

        items.push({
            id:       e.id,
            text:     e.text,
            sx:       sp.x,
            sy:       sp.y,
            tw:       tw,
            th:       th,
            alliance: e.alliance || 'neutral',
            status:   e.status   || 'active',
            priority: _priorityOf(e, selectedId),
        });
    }

    // -- priority sort (lower value = placed first) --
    items.sort((a, b) => a.priority - b.priority);

    // -- mark unit body positions as occupied --
    for (let i = 0; i < items.length; i++) {
        const it = items[i];
        const bx = (it.sx * BMP_SCALE) | 0;
        const by = (it.sy * BMP_SCALE) | 0;
        _markRect(bitmap, bw, bh,
                  bx - BODY_RADIUS, by - BODY_RADIUS,
                  BODY_RADIUS * 2,  BODY_RADIUS * 2);
    }

    // -- place labels --
    const results = [];

    for (let i = 0; i < items.length; i++) {
        const it   = items[i];
        const cands = _candidates(it.tw, it.th);

        let placed    = false;
        let displaced = false;
        let lx = 0;
        let ly = 0;

        for (let c = 0; c < cands.length; c++) {
            const cx = it.sx + cands[c][0];
            const cy = it.sy + cands[c][1];

            // bitmap-space rectangle for this candidate
            const bx = (cx * BMP_SCALE) | 0;
            const by = (cy * BMP_SCALE) | 0;
            const bwLabel = Math.max(1, (it.tw * BMP_SCALE) | 0);
            const bhLabel = Math.max(1, (it.th * BMP_SCALE) | 0);

            if (!_testRect(bitmap, bw, bh, bx, by, bwLabel, bhLabel)) {
                lx = cx;
                ly = cy;
                displaced = c > 0;
                _markRect(bitmap, bw, bh, bx, by, bwLabel, bhLabel);
                placed = true;
                break;
            }
        }

        // Fallback: preferred position regardless of overlap
        if (!placed) {
            lx = it.sx + cands[0][0];
            ly = it.sy + cands[0][1];
            displaced = false;
            const bx = (lx * BMP_SCALE) | 0;
            const by = (ly * BMP_SCALE) | 0;
            const bwLabel = Math.max(1, (it.tw * BMP_SCALE) | 0);
            const bhLabel = Math.max(1, (it.th * BMP_SCALE) | 0);
            _markRect(bitmap, bw, bh, bx, by, bwLabel, bhLabel);
        }

        results.push({
            id:       it.id,
            text:     it.text,
            labelX:   lx,
            labelY:   ly,
            anchorX:  it.sx,
            anchorY:  it.sy,
            displaced: displaced,
            bgWidth:  it.tw,
            bgHeight: it.th,
            alliance: it.alliance,
            status:   it.status,
        });
    }

    return results;
}
