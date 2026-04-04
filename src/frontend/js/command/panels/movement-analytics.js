// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Movement Analytics Panel — fleet-wide velocity, direction, and activity.
// Fetches /api/analytics/movement and shows:
//   - Fleet movement summary (moving vs stationary, avg/max speed)
//   - Compass rose direction histogram (SVG)
//   - Per-target movement table with speed, heading, distance
//   - Auto-refreshes every 8 seconds

import { _esc } from '/lib/utils.js';

const REFRESH_MS = 8000;
const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#666';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

// ============================================================
// SVG Compass Rose
// ============================================================

function _compassRoseSvg(dirHist, dominantDir, size) {
    const cx = size / 2;
    const cy = size / 2;
    const r = size / 2 - 20;
    const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    const angles = [270, 315, 0, 45, 90, 135, 180, 225]; // SVG angles (0=E, 90=S)

    let svg = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="display:block;margin:0 auto;">`;

    // Background circles
    for (let i = 1; i <= 3; i++) {
        const cr = (r / 3) * i;
        svg += `<circle cx="${cx}" cy="${cy}" r="${cr}" fill="none" stroke="${BORDER}" stroke-width="0.5" />`;
    }

    // Cross lines
    for (let a = 0; a < 360; a += 45) {
        const rad = (a * Math.PI) / 180;
        const x2 = cx + r * Math.cos(rad);
        const y2 = cy + r * Math.sin(rad);
        svg += `<line x1="${cx}" y1="${cy}" x2="${x2}" y2="${y2}" stroke="${BORDER}" stroke-width="0.5" />`;
    }

    // Direction bars
    const maxVal = Math.max(...dirs.map(d => dirHist[d] || 0), 0.01);
    for (let i = 0; i < dirs.length; i++) {
        const d = dirs[i];
        const val = dirHist[d] || 0;
        const barLen = (val / maxVal) * r * 0.9;
        if (barLen < 2) continue;

        const rad = (angles[i] * Math.PI) / 180;
        const x2 = cx + barLen * Math.cos(rad);
        const y2 = cy + barLen * Math.sin(rad);
        const color = d === dominantDir ? GREEN : CYAN;
        svg += `<line x1="${cx}" y1="${cy}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="4" stroke-linecap="round" opacity="0.8" />`;
    }

    // Direction labels
    for (let i = 0; i < dirs.length; i++) {
        const rad = (angles[i] * Math.PI) / 180;
        const lx = cx + (r + 12) * Math.cos(rad);
        const ly = cy + (r + 12) * Math.sin(rad);
        const color = dirs[i] === dominantDir ? GREEN : DIM;
        svg += `<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="central" fill="${color}" font-size="9" font-family="monospace">${dirs[i]}</text>`;
    }

    // Center dot
    svg += `<circle cx="${cx}" cy="${cy}" r="3" fill="${MAGENTA}" />`;
    svg += '</svg>';
    return svg;
}

// ============================================================
// Speed formatting
// ============================================================

function _speedLabel(mps) {
    if (mps === null || mps === undefined) return '--';
    if (mps < 0.3) return `<span style="color:${DIM}">STOPPED</span>`;
    // Show m/s and approximate km/h
    const kph = (mps * 3.6).toFixed(1);
    const color = mps < 2 ? GREEN : mps < 10 ? YELLOW : MAGENTA;
    return `<span style="color:${color}">${mps.toFixed(1)} m/s (${kph} km/h)</span>`;
}

function _headingArrow(deg) {
    // Unicode arrows for 8 compass directions
    const arrows = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    const symbols = ['\u2191', '\u2197', '\u2192', '\u2198', '\u2193', '\u2199', '\u2190', '\u2196'];
    const idx = Math.round(((deg % 360) + 360) % 360 / 45) % 8;
    return `<span style="color:${CYAN}" title="${deg.toFixed(0)}">${symbols[idx]} ${arrows[idx]}</span>`;
}

// ============================================================
// Panel Definition
// ============================================================

export const MovementAnalyticsPanelDef = {
    id: 'movement-analytics',
    title: 'MOVEMENT ANALYTICS',
    defaultPosition: { x: 200, y: 80 },
    defaultSize: { w: 520, h: 560 },

    create(panel) {
        const el = document.createElement('div');
        el.innerHTML = `
            <div style="padding:8px;font-size:12px;color:#c0c0c0;">
                <div style="display:flex;gap:4px;margin-bottom:8px;align-items:center;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                    <select data-bind="window-select" style="background:${SURFACE};color:${CYAN};border:1px solid ${BORDER};font-family:monospace;font-size:10px;padding:2px 6px;">
                        <option value="300">5 min</option>
                        <option value="900">15 min</option>
                        <option value="3600" selected>1 hour</option>
                        <option value="86400">24 hours</option>
                    </select>
                    <span data-bind="last-update" style="margin-left:auto;font-size:9px;color:${DIM};font-family:monospace;">--</span>
                </div>

                <!-- Fleet Summary -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Fleet Movement</div>
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px;">
                    <div class="mv-stat-box">
                        <div class="mv-stat-label">Total</div>
                        <div data-bind="total-targets" class="mv-stat-value" style="color:${CYAN}">0</div>
                    </div>
                    <div class="mv-stat-box">
                        <div class="mv-stat-label">Moving</div>
                        <div data-bind="moving-targets" class="mv-stat-value" style="color:${GREEN}">0</div>
                    </div>
                    <div class="mv-stat-box">
                        <div class="mv-stat-label">Avg Speed</div>
                        <div data-bind="avg-speed" class="mv-stat-value" style="color:${YELLOW}">--</div>
                    </div>
                    <div class="mv-stat-box">
                        <div class="mv-stat-label">Max Speed</div>
                        <div data-bind="max-speed" class="mv-stat-value" style="color:${MAGENTA}">--</div>
                    </div>
                </div>

                <!-- Direction Compass -->
                <div style="display:flex;gap:12px;margin-bottom:10px;">
                    <div style="flex:1;">
                        <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Direction</div>
                        <div data-bind="compass" style="background:${SURFACE};border:1px solid ${BORDER};padding:8px;">
                            <div style="color:${DIM};text-align:center;font-size:10px;padding:20px 0;">No data</div>
                        </div>
                    </div>
                    <div style="flex:1;">
                        <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Fleet Stats</div>
                        <div style="background:${SURFACE};border:1px solid ${BORDER};padding:8px;font-size:10px;font-family:monospace;">
                            <div style="margin-bottom:4px;"><span style="color:${DIM}">DOMINANT:</span> <span data-bind="dominant-dir" style="color:${GREEN}">--</span></div>
                            <div style="margin-bottom:4px;"><span style="color:${DIM}">TOTAL DIST:</span> <span data-bind="total-dist" style="color:${CYAN}">--</span></div>
                            <div style="margin-bottom:4px;"><span style="color:${DIM}">STATIONARY:</span> <span data-bind="stationary-count" style="color:${YELLOW}">0</span></div>
                            <div><span style="color:${DIM}">WINDOW:</span> <span data-bind="window-label" style="color:${DIM}">1 hour</span></div>
                        </div>
                    </div>
                </div>

                <!-- Per-Target Table -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Target Movement</div>
                <div data-bind="target-table" style="background:${SURFACE};border:1px solid ${BORDER};max-height:200px;overflow-y:auto;">
                    <div style="color:${DIM};text-align:center;padding:12px;font-size:10px;">Loading movement data...</div>
                </div>
            </div>

            <style>
                .mv-stat-box {
                    background: ${SURFACE};
                    border: 1px solid ${BORDER};
                    padding: 6px;
                    text-align: center;
                }
                .mv-stat-label {
                    font-size: 9px;
                    color: ${DIM};
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                .mv-stat-value {
                    font-size: 14px;
                    margin-top: 2px;
                    font-family: monospace;
                }
                .mv-target-row {
                    display: grid;
                    grid-template-columns: 2fr 1fr 1fr 1fr;
                    gap: 4px;
                    padding: 3px 6px;
                    border-bottom: 1px solid #0f0f1a;
                    font-size: 10px;
                    font-family: monospace;
                    align-items: center;
                }
                .mv-target-row:hover {
                    background: #12121e;
                }
                .mv-target-header {
                    color: ${DIM};
                    text-transform: uppercase;
                    font-size: 9px;
                    letter-spacing: 0.5px;
                    border-bottom: 1px solid ${BORDER};
                }
            </style>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const totalEl = bodyEl.querySelector('[data-bind="total-targets"]');
        const movingEl = bodyEl.querySelector('[data-bind="moving-targets"]');
        const avgSpeedEl = bodyEl.querySelector('[data-bind="avg-speed"]');
        const maxSpeedEl = bodyEl.querySelector('[data-bind="max-speed"]');
        const compassEl = bodyEl.querySelector('[data-bind="compass"]');
        const dominantEl = bodyEl.querySelector('[data-bind="dominant-dir"]');
        const totalDistEl = bodyEl.querySelector('[data-bind="total-dist"]');
        const stationaryEl = bodyEl.querySelector('[data-bind="stationary-count"]');
        const windowLabelEl = bodyEl.querySelector('[data-bind="window-label"]');
        const targetTableEl = bodyEl.querySelector('[data-bind="target-table"]');
        const lastUpdateEl = bodyEl.querySelector('[data-bind="last-update"]');
        const windowSelect = bodyEl.querySelector('[data-bind="window-select"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        let windowSec = 3600;

        async function fetchData() {
            try {
                const resp = await fetch(`/api/analytics/movement?window=${windowSec}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();

                // Summary
                if (totalEl) totalEl.textContent = data.total_targets || 0;
                if (movingEl) movingEl.textContent = data.moving_targets || 0;
                if (avgSpeedEl) avgSpeedEl.textContent = (data.avg_fleet_speed_mps || 0).toFixed(1);
                if (maxSpeedEl) maxSpeedEl.textContent = (data.max_fleet_speed_mps || 0).toFixed(1);
                if (stationaryEl) stationaryEl.textContent = data.stationary_targets || 0;

                // Distance
                const dist = data.total_fleet_distance_m || 0;
                if (totalDistEl) {
                    totalDistEl.textContent = dist > 1000
                        ? `${(dist / 1000).toFixed(1)} km`
                        : `${dist.toFixed(0)} m`;
                }

                // Dominant direction
                if (dominantEl) dominantEl.textContent = data.dominant_direction || '--';

                // Compass rose from per-target data
                const dirHist = {};
                const targets = data.per_target || [];
                const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
                dirs.forEach(d => dirHist[d] = 0);

                // Aggregate direction from per-target headings
                for (const t of targets) {
                    if (t.stationary) continue;
                    const h = ((t.heading || 0) % 360 + 360) % 360;
                    const idx = Math.round(h / 45) % 8;
                    dirHist[dirs[idx]] += 1;
                }

                if (compassEl) {
                    compassEl.innerHTML = _compassRoseSvg(dirHist, data.dominant_direction || '', 160);
                }

                // Per-target table
                if (targetTableEl) {
                    if (targets.length === 0) {
                        targetTableEl.innerHTML = `<div style="color:${DIM};text-align:center;padding:12px;font-size:10px;">No targets with movement data</div>`;
                    } else {
                        let html = `<div class="mv-target-row mv-target-header">
                            <span>TARGET</span>
                            <span>SPEED</span>
                            <span>HEADING</span>
                            <span>DISTANCE</span>
                        </div>`;

                        // Sort by speed descending
                        const sorted = [...targets].sort((a, b) => (b.speed || 0) - (a.speed || 0));

                        for (const t of sorted.slice(0, 50)) {
                            const nameColor = t.stationary ? DIM : '#ccc';
                            const distStr = (t.distance || 0) > 1000
                                ? `${((t.distance || 0) / 1000).toFixed(1)} km`
                                : `${(t.distance || 0).toFixed(0)} m`;
                            html += `<div class="mv-target-row">
                                <span style="color:${nameColor};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${_esc(t.target_id)}">${_esc(t.name || t.target_id)}</span>
                                <span>${_speedLabel(t.speed)}</span>
                                <span>${t.stationary ? `<span style="color:${DIM}">--</span>` : _headingArrow(t.heading || 0)}</span>
                                <span style="color:${CYAN}">${distStr}</span>
                            </div>`;
                        }
                        targetTableEl.innerHTML = html;
                    }
                }

                // Update timestamp
                if (lastUpdateEl) {
                    const d = new Date();
                    lastUpdateEl.textContent = `Updated ${d.toLocaleTimeString()}`;
                }

            } catch (e) {
                console.error('[MovementAnalytics] fetch failed:', e);
                if (targetTableEl) {
                    targetTableEl.innerHTML = `<div style="color:${MAGENTA};text-align:center;padding:12px;font-size:10px;">Failed to load movement data</div>`;
                }
            }
        }

        // Window selector
        if (windowSelect) {
            windowSelect.addEventListener('change', () => {
                windowSec = parseInt(windowSelect.value, 10);
                const labels = { 300: '5 min', 900: '15 min', 3600: '1 hour', 86400: '24 hours' };
                if (windowLabelEl) windowLabelEl.textContent = labels[windowSec] || `${windowSec}s`;
                fetchData();
            });
        }

        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchData);
        }

        // Initial fetch and timer
        fetchData();
        panel._mvTimer = setInterval(fetchData, REFRESH_MS);
    },

    unmount(bodyEl, panel) {
        if (panel && panel._mvTimer) {
            clearInterval(panel._mvTimer);
            panel._mvTimer = null;
        }
    },
};
