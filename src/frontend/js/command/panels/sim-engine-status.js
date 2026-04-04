// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Sim Engine Status Panel — real-time simulation engine dashboard.
// Fetches /api/sim/status and shows:
//   - Engine running/stopped state with animated indicator
//   - Target count by alliance (friendly/hostile/neutral/unknown)
//   - Game mode state, wave, and score
//   - Auto-refreshes every 5 seconds

import { _esc } from '/lib/utils.js';
import { EventBus } from '/lib/events.js';

const REFRESH_MS = 5000;
const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#666';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

// Alliance color mapping
const ALLIANCE_COLORS = {
    friendly: GREEN,
    hostile: MAGENTA,
    neutral: YELLOW,
    unknown: DIM,
    civilian: CYAN,
};

function _allianceColor(alliance) {
    return ALLIANCE_COLORS[alliance] || DIM;
}

function _statusBadge(status) {
    const colors = {
        running: GREEN,
        stopped: DIM,
        error: MAGENTA,
    };
    const color = colors[status] || DIM;
    const pulse = status === 'running' ? 'se-pulse' : '';
    return `<span class="se-status-badge ${pulse}" style="color:${color};border-color:${color}">${(status || 'UNKNOWN').toUpperCase()}</span>`;
}

function _gameStateBadge(state) {
    const colors = {
        setup: YELLOW,
        countdown: YELLOW,
        active: GREEN,
        wave_complete: CYAN,
        game_over: MAGENTA,
        victory: GREEN,
        none: DIM,
        unknown: DIM,
    };
    const color = colors[state] || DIM;
    return `<span style="color:${color};font-weight:bold">${(state || 'none').toUpperCase()}</span>`;
}

// ============================================================
// Alliance Bar Chart (SVG)
// ============================================================

function _allianceBarsSvg(allianceCounts, width, height) {
    const entries = Object.entries(allianceCounts).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
        return `<div style="color:${DIM};text-align:center;padding:8px;font-size:10px;">No targets in simulation</div>`;
    }

    const maxVal = Math.max(...entries.map(e => e[1]), 1);
    const barHeight = Math.min(22, (height - 10) / entries.length);
    const svgHeight = entries.length * (barHeight + 4) + 4;

    let svg = `<svg width="${width}" height="${svgHeight}" style="display:block;width:100%;">`;
    let y = 4;

    for (const [alliance, count] of entries) {
        const color = _allianceColor(alliance);
        const barW = (count / maxVal) * (width - 100);

        // Label
        svg += `<text x="2" y="${y + barHeight / 2 + 3}" fill="${color}" font-size="9" font-family="monospace" text-anchor="start">${alliance.toUpperCase()}</text>`;

        // Bar
        svg += `<rect x="70" y="${y}" width="${Math.max(barW, 2)}" height="${barHeight}" fill="${color}" opacity="0.3" rx="1" />`;
        svg += `<rect x="70" y="${y}" width="${Math.max(barW, 2)}" height="${barHeight}" fill="none" stroke="${color}" stroke-width="1" rx="1" />`;

        // Count label
        svg += `<text x="${70 + barW + 6}" y="${y + barHeight / 2 + 3}" fill="${color}" font-size="10" font-family="monospace">${count}</text>`;

        y += barHeight + 4;
    }

    svg += '</svg>';
    return svg;
}

// ============================================================
// Panel Definition
// ============================================================

export const SimEngineStatusPanelDef = {
    id: 'sim-engine-status',
    title: 'SIM ENGINE',
    defaultPosition: { x: 120, y: 90 },
    defaultSize: { w: 420, h: 460 },

    create(panel) {
        const el = document.createElement('div');
        el.innerHTML = `
            <div style="padding:8px;font-size:12px;color:#c0c0c0;">
                <div style="display:flex;gap:4px;margin-bottom:8px;align-items:center;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                    <span data-bind="engine-status" style="margin-left:auto;"></span>
                </div>

                <!-- Engine Status -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Engine Status</div>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px;">
                    <div class="se-stat-box">
                        <div class="se-stat-label">Status</div>
                        <div data-bind="status-value" class="se-stat-value" style="color:${DIM}">--</div>
                    </div>
                    <div class="se-stat-box">
                        <div class="se-stat-label">Targets</div>
                        <div data-bind="target-count" class="se-stat-value" style="color:${CYAN}">0</div>
                    </div>
                    <div class="se-stat-box">
                        <div class="se-stat-label">Available</div>
                        <div data-bind="available" class="se-stat-value" style="color:${DIM}">--</div>
                    </div>
                </div>

                <!-- Game Mode -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Game Mode</div>
                <div style="background:${SURFACE};border:1px solid ${BORDER};padding:8px;margin-bottom:10px;">
                    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-family:monospace;font-size:11px;">
                        <div>
                            <div style="font-size:9px;color:${DIM};text-transform:uppercase;margin-bottom:2px;">State</div>
                            <div data-bind="game-state">--</div>
                        </div>
                        <div>
                            <div style="font-size:9px;color:${DIM};text-transform:uppercase;margin-bottom:2px;">Wave</div>
                            <div data-bind="game-wave" style="color:${YELLOW};font-size:18px;">0</div>
                        </div>
                        <div>
                            <div style="font-size:9px;color:${DIM};text-transform:uppercase;margin-bottom:2px;">Score</div>
                            <div data-bind="game-score" style="color:${GREEN};font-size:18px;">0</div>
                        </div>
                    </div>
                </div>

                <!-- Alliance Breakdown -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Alliance Breakdown</div>
                <div data-bind="alliance-chart" style="background:${SURFACE};border:1px solid ${BORDER};padding:6px;margin-bottom:10px;">
                    <div style="color:${DIM};text-align:center;padding:8px;font-size:10px;">Loading...</div>
                </div>

                <!-- Engine History (simple status log) -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Status Log</div>
                <div data-bind="status-log" style="background:${SURFACE};border:1px solid ${BORDER};padding:6px;max-height:120px;overflow-y:auto;font-family:monospace;font-size:10px;color:${DIM};">
                    <div>Waiting for data...</div>
                </div>

                <div style="margin-top:8px;text-align:right;">
                    <span data-bind="last-update" style="font-size:9px;color:${DIM};font-family:monospace;">--</span>
                </div>
            </div>

            <style>
                .se-stat-box {
                    background: ${SURFACE};
                    border: 1px solid ${BORDER};
                    padding: 6px;
                    text-align: center;
                }
                .se-stat-label {
                    font-size: 9px;
                    color: ${DIM};
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                .se-stat-value {
                    font-size: 16px;
                    margin-top: 2px;
                    font-family: monospace;
                }
                .se-status-badge {
                    padding: 2px 8px;
                    border: 1px solid;
                    border-radius: 2px;
                    font-size: 10px;
                    font-family: monospace;
                    letter-spacing: 1px;
                }
                @keyframes se-pulse-anim {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.5; }
                }
                .se-pulse {
                    animation: se-pulse-anim 1.5s ease-in-out infinite;
                }
            </style>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const statusValueEl = bodyEl.querySelector('[data-bind="status-value"]');
        const targetCountEl = bodyEl.querySelector('[data-bind="target-count"]');
        const availableEl = bodyEl.querySelector('[data-bind="available"]');
        const engineStatusEl = bodyEl.querySelector('[data-bind="engine-status"]');
        const gameStateEl = bodyEl.querySelector('[data-bind="game-state"]');
        const gameWaveEl = bodyEl.querySelector('[data-bind="game-wave"]');
        const gameScoreEl = bodyEl.querySelector('[data-bind="game-score"]');
        const allianceChartEl = bodyEl.querySelector('[data-bind="alliance-chart"]');
        const statusLogEl = bodyEl.querySelector('[data-bind="status-log"]');
        const lastUpdateEl = bodyEl.querySelector('[data-bind="last-update"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        const logEntries = [];
        const LOG_MAX = 20;
        let lastStatus = null;

        async function fetchData() {
            try {
                const resp = await fetch('/api/sim/status');
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();

                // Engine status
                const status = data.status || 'stopped';
                if (statusValueEl) {
                    statusValueEl.textContent = status.toUpperCase();
                    statusValueEl.style.color = status === 'running' ? GREEN : status === 'error' ? MAGENTA : DIM;
                }

                if (engineStatusEl) engineStatusEl.innerHTML = _statusBadge(status);

                // Available
                if (availableEl) {
                    availableEl.textContent = data.available ? 'YES' : 'NO';
                    availableEl.style.color = data.available ? GREEN : DIM;
                }

                // Target count
                if (targetCountEl) targetCountEl.textContent = data.target_count || 0;

                // Game state
                if (gameStateEl) gameStateEl.innerHTML = _gameStateBadge(data.game_state || 'none');
                if (gameWaveEl) gameWaveEl.textContent = data.wave || 0;
                if (gameScoreEl) gameScoreEl.textContent = data.score || 0;

                // Alliance chart
                const allianceCounts = data.alliance_counts || {};
                if (allianceChartEl) {
                    if (Object.keys(allianceCounts).length === 0) {
                        allianceChartEl.innerHTML = `<div style="color:${DIM};text-align:center;padding:8px;font-size:10px;">No targets in simulation</div>`;
                    } else {
                        allianceChartEl.innerHTML = _allianceBarsSvg(allianceCounts, 380, 120);
                    }
                }

                // Status log
                if (status !== lastStatus) {
                    const now = new Date().toLocaleTimeString();
                    const color = status === 'running' ? GREEN : status === 'error' ? MAGENTA : YELLOW;
                    logEntries.unshift(`<span style="color:${DIM}">[${now}]</span> <span style="color:${color}">${status.toUpperCase()}</span> targets=${data.target_count || 0} wave=${data.wave || 0}`);
                    if (logEntries.length > LOG_MAX) logEntries.pop();
                    lastStatus = status;
                }
                if (statusLogEl) {
                    statusLogEl.innerHTML = logEntries.length > 0
                        ? logEntries.map(e => `<div style="padding:1px 0;">${e}</div>`).join('')
                        : `<div style="color:${DIM}">No status changes yet</div>`;
                }

                // Update timestamp
                if (lastUpdateEl) {
                    lastUpdateEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
                }

            } catch (e) {
                console.error('[SimEngineStatus] fetch failed:', e);
                if (statusValueEl) {
                    statusValueEl.textContent = 'ERROR';
                    statusValueEl.style.color = MAGENTA;
                }
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', fetchData);

        // Initial fetch and timer
        fetchData();
        panel._seTimer = setInterval(fetchData, REFRESH_MS);
    },

    unmount(bodyEl, panel) {
        if (panel && panel._seTimer) {
            clearInterval(panel._seTimer);
            panel._seTimer = null;
        }
    },
};
