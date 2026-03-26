// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Dwell Time Panel — shows dwell time per target, zone occupancy, and time-in-zone charts.
// Backend: GET /api/dwell/active, GET /api/dwell/history
// Auto-refreshes every 10 seconds.

import { _esc } from '/lib/utils.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_MS = 10000;

const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#666';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

const SEVERITY_COLORS = {
    normal: GREEN,
    extended: YELLOW,
    prolonged: '#ff8c00',
    critical: MAGENTA,
};

// Dwell count history for sparkline
const _dwellCountHistory = [];
const HISTORY_MAX = 60;

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchDwellData() {
    const [activeRes, historyRes] = await Promise.allSettled([
        fetch('/api/dwell/active').then(r => r.ok ? r.json() : null),
        fetch('/api/dwell/history').then(r => r.ok ? r.json() : null),
    ]);

    return {
        active: activeRes.status === 'fulfilled' ? activeRes.value : null,
        history: historyRes.status === 'fulfilled' ? historyRes.value : null,
    };
}

// ---------------------------------------------------------------------------
// SVG sparkline
// ---------------------------------------------------------------------------

function _svgSparkline(data, w, h, color) {
    if (!data || data.length < 2) {
        return `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">
            <text x="${w / 2}" y="${h / 2 + 3}" text-anchor="middle" fill="${DIM}" font-size="9">NO DATA</text>
        </svg>`;
    }
    const max = Math.max(...data, 0.01);
    const pts = data.map((v, i) => {
        const x = (i / (data.length - 1)) * w;
        const y = h - 2 - ((v / max) * (h - 4));
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const area = `${pts.join(' ')} ${w},${h} 0,${h}`;
    return `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="dwell-spark-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="${color}" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="${color}" stop-opacity="0.02"/>
            </linearGradient>
        </defs>
        <polygon points="${area}" fill="url(#dwell-spark-grad)"/>
        <polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>`;
}

// ---------------------------------------------------------------------------
// Stat card helper
// ---------------------------------------------------------------------------

function _statCard(label, value, color) {
    return `<div style="background:${SURFACE};border:1px solid ${BORDER};padding:6px;text-align:center;">
        <div style="font-size:9px;color:${DIM};text-transform:uppercase;letter-spacing:0.5px;">${_esc(label)}</div>
        <div style="font-size:16px;color:${color};margin-top:2px;font-family:monospace;">${_esc(String(value))}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Duration formatting
// ---------------------------------------------------------------------------

function _formatDuration(seconds) {
    if (!seconds && seconds !== 0) return '--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

// ---------------------------------------------------------------------------
// Severity badge
// ---------------------------------------------------------------------------

function _severityBadge(severity) {
    const color = SEVERITY_COLORS[severity] || DIM;
    const label = (severity || 'unknown').toUpperCase();
    return `<span style="color:${color};border:1px solid ${color};padding:1px 4px;border-radius:2px;font-size:9px;">${label}</span>`;
}

// ---------------------------------------------------------------------------
// Active dwell list
// ---------------------------------------------------------------------------

function _activeDwellList(dwells) {
    if (!dwells || !Array.isArray(dwells) || dwells.length === 0) {
        return `<div style="color:#555;padding:8px;text-align:center;font-size:10px;">No active dwells. Targets stationary for 5+ minutes will appear here.</div>`;
    }

    const sorted = dwells.slice().sort((a, b) => (b.duration_s || 0) - (a.duration_s || 0));
    return sorted.map(d => {
        const name = d.target_name || d.target_id || '--';
        const sevColor = SEVERITY_COLORS[d.severity] || DIM;
        const duration = _formatDuration(d.duration_s);

        return `<div style="border:1px solid ${BORDER};padding:5px 6px;margin-bottom:3px;border-left:3px solid ${sevColor};display:flex;align-items:center;gap:8px;">
            <div style="flex-shrink:0;">
                <svg width="16" height="16" style="vertical-align:middle;">
                    <circle cx="8" cy="8" r="6" fill="none" stroke="${sevColor}" stroke-width="2" opacity="0.8">
                        <animate attributeName="opacity" values="0.8;0.4;0.8" dur="2s" repeatCount="indefinite"/>
                    </circle>
                    <circle cx="8" cy="8" r="3" fill="${sevColor}" opacity="0.6"/>
                </svg>
            </div>
            <div style="flex:1;min-width:0;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:${CYAN};font-size:10px;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(name)}</span>
                    <span style="color:${sevColor};font-size:12px;font-family:monospace;font-weight:bold;">${_esc(duration)}</span>
                </div>
                <div style="display:flex;gap:6px;margin-top:2px;font-size:9px;color:#555;">
                    ${_severityBadge(d.severity)}
                    ${d.target_type ? `<span>${_esc(d.target_type)}</span>` : ''}
                    ${d.zone_name ? `<span>Zone: ${_esc(d.zone_name)}</span>` : ''}
                </div>
            </div>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// History dwell list
// ---------------------------------------------------------------------------

function _historyDwellList(dwells, limit) {
    if (!dwells || !Array.isArray(dwells) || dwells.length === 0) {
        return `<div style="color:#555;padding:8px;text-align:center;font-size:10px;">No dwell history yet.</div>`;
    }

    return dwells.slice(0, limit || 20).map(d => {
        const name = d.target_name || d.target_id || '--';
        const sevColor = SEVERITY_COLORS[d.severity] || DIM;
        const duration = _formatDuration(d.duration_s);

        return `<div style="padding:3px 6px;border-bottom:1px solid rgba(255,255,255,0.03);display:flex;align-items:center;gap:8px;font-size:10px;">
            <span style="color:#888;font-family:monospace;min-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(name)}</span>
            <span style="color:${sevColor};font-family:monospace;min-width:50px;">${_esc(duration)}</span>
            ${_severityBadge(d.severity)}
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Zone occupancy chart (horizontal bars by zone or target_type)
// ---------------------------------------------------------------------------

function _zoneOccupancy(dwells) {
    if (!dwells || !Array.isArray(dwells) || dwells.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No zone occupancy data</div>`;
    }

    // Aggregate dwell time by target type
    const typeTotals = {};
    for (const d of dwells) {
        const key = d.target_type || d.zone_name || 'unknown';
        typeTotals[key] = (typeTotals[key] || 0) + (d.duration_s || 0);
    }

    const entries = Object.entries(typeTotals).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No zone data</div>`;
    }

    const maxVal = Math.max(...entries.map(([, v]) => v), 1);
    const palette = [CYAN, GREEN, MAGENTA, YELLOW, '#a855f7', '#f97316'];

    return entries.slice(0, 8).map(([name, totalSec], i) => {
        const pct = Math.max(2, Math.round((totalSec / maxVal) * 100));
        const color = palette[i % palette.length];
        return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
            <span style="color:#888;min-width:80px;font-size:10px;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(name)}</span>
            <div style="flex:1;height:8px;background:#12121a;border-radius:2px;overflow:hidden;">
                <div style="width:${pct}%;height:100%;background:${color};border-radius:2px;transition:width 0.3s;"></div>
            </div>
            <span style="color:${color};font-size:10px;min-width:50px;text-align:right;font-family:monospace;">${_esc(_formatDuration(totalSec))}</span>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Severity distribution
// ---------------------------------------------------------------------------

function _severityDistribution(dwells) {
    if (!dwells || !Array.isArray(dwells) || dwells.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No severity data</div>`;
    }

    const counts = {};
    for (const d of dwells) {
        const sev = d.severity || 'unknown';
        counts[sev] = (counts[sev] || 0) + 1;
    }

    const entries = Object.entries(counts);
    const total = dwells.length;

    return `<div style="display:flex;gap:4px;flex-wrap:wrap;">
        ${entries.map(([sev, count]) => {
            const color = SEVERITY_COLORS[sev] || DIM;
            const pct = ((count / total) * 100).toFixed(0);
            return `<div style="background:${SURFACE};border:1px solid ${color}33;padding:4px 8px;border-radius:3px;text-align:center;">
                <div style="font-size:14px;color:${color};font-family:monospace;">${count}</div>
                <div style="font-size:8px;color:#888;text-transform:uppercase;">${_esc(sev)} (${pct}%)</div>
            </div>`;
        }).join('')}
    </div>`;
}

// ---------------------------------------------------------------------------
// Full render
// ---------------------------------------------------------------------------

function _renderDwell(contentEl, data) {
    const activeData = data.active || {};
    const historyData = data.history || {};

    const activeDwells = activeData.dwells || [];
    const historyDwells = historyData.dwells || [];
    const allDwells = [...activeDwells, ...historyDwells];
    const sourceLabel = activeData.source === 'unavailable' ? 'API unavailable' : '';

    // Track active count over time
    _dwellCountHistory.push(activeDwells.length);
    if (_dwellCountHistory.length > HISTORY_MAX) _dwellCountHistory.shift();

    // Compute aggregate stats
    const totalDwellTime = allDwells.reduce((sum, d) => sum + (d.duration_s || 0), 0);
    const avgDwellTime = allDwells.length > 0 ? totalDwellTime / allDwells.length : 0;
    const maxDwellTime = allDwells.reduce((max, d) => Math.max(max, d.duration_s || 0), 0);

    // Unavailable banner
    let unavailBanner = '';
    if (activeData.source === 'unavailable') {
        unavailBanner = `<div style="color:${MAGENTA};padding:8px;text-align:center;font-size:11px;border:1px solid rgba(255,42,109,0.3);background:rgba(255,42,109,0.05);margin-bottom:8px;">
            Dwell tracker not initialized. Start demo mode or connect sensors.
        </div>`;
    }

    // Stats row
    const statsRow = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;">
        ${_statCard('Active', activeDwells.length, activeDwells.length > 0 ? CYAN : DIM)}
        ${_statCard('History', historyDwells.length, GREEN)}
        ${_statCard('Avg Time', _formatDuration(avgDwellTime), YELLOW)}
        ${_statCard('Max Time', _formatDuration(maxDwellTime), maxDwellTime > 0 ? MAGENTA : DIM)}
    </div>`;

    // Dwell count sparkline
    const sparkHtml = `<div style="margin-bottom:10px;">
        <div style="font-size:9px;color:${DIM};text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">ACTIVE DWELLS TREND</div>
        ${_svgSparkline(_dwellCountHistory, 420, 36, CYAN)}
    </div>`;

    // Severity distribution
    const sevSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${MAGENTA};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">SEVERITY DISTRIBUTION</div>
        ${_severityDistribution(allDwells)}
    </div>`;

    // Zone occupancy chart
    const zoneSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${GREEN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">TIME BY CATEGORY</div>
        ${_zoneOccupancy(allDwells)}
    </div>`;

    // Active dwells list
    const activeSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">ACTIVE DWELLS (${activeDwells.length})</div>
        <div style="max-height:180px;overflow-y:auto;">
            ${_activeDwellList(activeDwells)}
        </div>
    </div>`;

    // History list
    const historySection = `<div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${DIM};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">RECENT HISTORY (${historyDwells.length})</div>
        <div style="max-height:140px;overflow-y:auto;">
            ${_historyDwellList(historyDwells, 20)}
        </div>
    </div>`;

    contentEl.innerHTML = unavailBanner + statsRow + sparkHtml + sevSection + zoneSection + activeSection + historySection;
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const DwellTimePanelDef = {
    id: 'dwell-time',
    title: 'DWELL TIME',
    defaultPosition: { x: 300, y: 90 },
    defaultSize: { w: 480, h: 580 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'dwell-time-panel';
        el.style.cssText = 'padding:8px;overflow-y:auto;height:100%;';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-dwell" style="font-size:0.42rem">REFRESH</button>
                <span data-bind="dwell-timestamp" style="font-size:10px;color:#555;margin-left:auto;font-family:monospace;">--</span>
            </div>
            <div data-bind="dwell-content">
                <div style="color:#555;padding:16px;text-align:center;">Loading dwell time data...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="dwell-content"]');
        const timestampEl = bodyEl.querySelector('[data-bind="dwell-timestamp"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh-dwell"]');
        let timer = null;

        async function refresh() {
            try {
                const data = await _fetchDwellData();
                if (contentEl) _renderDwell(contentEl, data);
                if (timestampEl) timestampEl.textContent = new Date().toLocaleTimeString();
            } catch (err) {
                console.warn('[DwellTime] refresh error:', err);
                if (contentEl) {
                    contentEl.innerHTML = `<div style="color:${MAGENTA};padding:12px;text-align:center;">Failed to load dwell data</div>`;
                }
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', refresh);

        refresh();
        timer = setInterval(refresh, REFRESH_MS);
        panel._dwellTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._dwellTimer) {
            clearInterval(panel._dwellTimer);
            panel._dwellTimer = null;
        }
        _dwellCountHistory.length = 0;
    },
};
