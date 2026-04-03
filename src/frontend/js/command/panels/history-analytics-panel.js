// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// History Analytics Panel
// Displays historical tactical analytics from /api/analytics/history.
// Shows: event counts by type/severity/source, busiest hours chart,
// top targets, correlation success rate, and time window selector.
// Supports look-back windows: 1h, 6h, 12h, 24h.
// UX Loop 6 (Investigate Target) — provides historical context for investigations.

import { _esc } from '/lib/utils.js';
import { EventBus } from '/lib/events.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_MS = 15000;
const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#888';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';
const PALETTE = [CYAN, MAGENTA, GREEN, YELLOW, '#a855f7', '#f97316', '#06b6d4', '#ec4899'];

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchAnalytics(hours) {
    try {
        const r = await fetch(`/api/analytics/history?hours=${hours}`);
        if (!r.ok) return null;
        return await r.json();
    } catch {
        return null;
    }
}

// ---------------------------------------------------------------------------
// Chart helpers
// ---------------------------------------------------------------------------

function _barChart(data, maxEntries = 10) {
    if (!data || Object.keys(data).length === 0) {
        return `<div style="color:${DIM};font-size:0.42rem;padding:4px 0">No data</div>`;
    }
    const entries = Object.entries(data)
        .sort((a, b) => b[1] - a[1])
        .slice(0, maxEntries);
    const max = Math.max(...entries.map(e => e[1]), 1);
    let html = '';
    entries.forEach(([key, val], i) => {
        const pct = (val / max) * 100;
        const color = PALETTE[i % PALETTE.length];
        html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
            <span class="mono" style="font-size:0.38rem;color:${DIM};min-width:80px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(key.toUpperCase())}</span>
            <div style="flex:1;height:10px;background:#111;border-radius:2px;overflow:hidden">
                <div style="width:${pct}%;height:100%;background:${color};border-radius:2px;transition:width 0.3s"></div>
            </div>
            <span class="mono" style="font-size:0.38rem;color:${color};min-width:30px;text-align:right">${val}</span>
        </div>`;
    });
    return html;
}

function _hourlyChart(hourlyData) {
    if (!hourlyData || Object.keys(hourlyData).length === 0) {
        return `<div style="color:${DIM};font-size:0.42rem;padding:4px 0">No hourly data</div>`;
    }
    // Build full 24-hour array
    const hours = [];
    for (let h = 0; h < 24; h++) {
        hours.push({ hour: h, count: hourlyData[String(h)] || hourlyData[h] || 0 });
    }
    const max = Math.max(...hours.map(h => h.count), 1);
    const barW = 100 / 24;
    const svgW = 280;
    const svgH = 60;
    const currentHour = new Date().getHours();

    let bars = '';
    hours.forEach((h, i) => {
        const barH = Math.max((h.count / max) * (svgH - 14), 1);
        const x = (i / 24) * svgW + 1;
        const y = svgH - 12 - barH;
        const isCurrent = h.hour === currentHour;
        const color = isCurrent ? MAGENTA : CYAN;
        const opacity = isCurrent ? '1' : '0.6';
        bars += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${((svgW / 24) - 2).toFixed(1)}" height="${barH.toFixed(1)}" fill="${color}" opacity="${opacity}" rx="1"/>`;
        // Hour labels every 6 hours
        if (h.hour % 6 === 0) {
            bars += `<text x="${(x + (svgW / 48)).toFixed(1)}" y="${svgH - 1}" text-anchor="middle" fill="${DIM}" font-size="7" font-family="monospace">${String(h.hour).padStart(2, '0')}</text>`;
        }
    });

    return `<svg width="${svgW}" height="${svgH}" style="display:block;margin:0 auto" xmlns="http://www.w3.org/2000/svg">
        ${bars}
    </svg>`;
}

function _statBox(label, value, color) {
    return `<div style="text-align:center;flex:1;min-width:50px">
        <div class="mono" style="font-size:0.7rem;color:${color};font-weight:bold">${value}</div>
        <div style="font-size:0.36rem;color:${DIM};text-transform:uppercase;letter-spacing:0.5px">${_esc(label)}</div>
    </div>`;
}

function _correlationGauge(stats) {
    if (!stats) return '';
    const rate = (stats.rate || 0) * 100;
    const color = rate >= 80 ? GREEN : rate >= 50 ? YELLOW : MAGENTA;
    const total = stats.total_correlations || 0;
    const success = stats.successful || 0;
    const failed = stats.failed || 0;

    // SVG arc gauge
    const cx = 40, cy = 40, r = 30;
    const circumference = Math.PI * r; // half circle
    const offset = circumference - (rate / 100) * circumference;

    return `<div style="display:flex;align-items:center;gap:12px;padding:4px 0">
        <svg width="80" height="50" viewBox="0 0 80 50" xmlns="http://www.w3.org/2000/svg">
            <path d="M 10 45 A 30 30 0 0 1 70 45" fill="none" stroke="#222" stroke-width="6" stroke-linecap="round"/>
            <path d="M 10 45 A 30 30 0 0 1 70 45" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round"
                  stroke-dasharray="${circumference.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}" style="transition:stroke-dashoffset 0.5s"/>
            <text x="40" y="40" text-anchor="middle" fill="${color}" font-size="14" font-weight="bold" font-family="monospace">${rate.toFixed(0)}%</text>
        </svg>
        <div style="display:flex;flex-direction:column;gap:2px">
            <div style="font-size:0.38rem;color:${DIM}">Total: <span style="color:${CYAN}">${total}</span></div>
            <div style="font-size:0.38rem;color:${DIM}">Success: <span style="color:${GREEN}">${success}</span></div>
            <div style="font-size:0.38rem;color:${DIM}">Failed: <span style="color:${MAGENTA}">${failed}</span></div>
        </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

function _render(bodyEl, data, hours) {
    if (!bodyEl) return;
    const content = bodyEl.querySelector('[data-bind="analytics-content"]');
    if (!content) return;

    if (!data) {
        content.innerHTML = `<div style="padding:20px;text-align:center;color:${DIM}">
            <div style="font-size:0.6rem;margin-bottom:4px">NO ANALYTICS DATA</div>
            <div style="font-size:0.42rem">Event store may not be configured or no events recorded yet.</div>
        </div>`;
        return;
    }

    const tr = data.time_range || {};
    const activity = data.target_activity || {};
    let html = '';

    // Summary row
    html += `<div style="display:flex;gap:4px;padding:8px 10px;border-bottom:1px solid ${BORDER}">
        ${_statBox('Events', data.total_events || 0, CYAN)}
        ${_statBox('Sightings', activity.sightings || 0, GREEN)}
        ${_statBox('Alerts', activity.alerts || 0, YELLOW)}
        ${_statBox('Geofence', activity.geofence_events || 0, MAGENTA)}
    </div>`;

    // Time range info
    html += `<div style="padding:4px 10px;border-bottom:1px solid ${BORDER};display:flex;justify-content:space-between">
        <span class="mono" style="font-size:0.36rem;color:${DIM}">Window: ${tr.duration_hours || hours}h</span>
        <span class="mono" style="font-size:0.36rem;color:${DIM}">${data.source === 'no_store' ? 'No event store' : 'Live data'}</span>
    </div>`;

    // Busiest Hours
    html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
        <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Activity by Hour</div>
        ${_hourlyChart(data.busiest_hours)}
    </div>`;

    // Events by Type
    if (data.events_by_type && Object.keys(data.events_by_type).length > 0) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Events by Type</div>
            ${_barChart(data.events_by_type)}
        </div>`;
    }

    // Events by Severity
    if (data.events_by_severity && Object.keys(data.events_by_severity).length > 0) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${YELLOW};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Events by Severity</div>
            ${_barChart(data.events_by_severity)}
        </div>`;
    }

    // Events by Source
    if (data.events_by_source && Object.keys(data.events_by_source).length > 0) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${GREEN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Events by Source</div>
            ${_barChart(data.events_by_source)}
        </div>`;
    }

    // Top Targets
    if (data.top_targets && data.top_targets.length > 0) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${MAGENTA};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Top Targets</div>`;
        for (const t of data.top_targets.slice(0, 8)) {
            const tid = t.target_id || t.id || 'unknown';
            const count = t.count || t.events || 0;
            html += `<div class="ha-target-item" data-target="${_esc(tid)}" style="display:flex;justify-content:space-between;align-items:center;padding:2px 4px;margin:1px 0;cursor:pointer;border-radius:2px" title="Click to investigate">
                <span class="mono" style="font-size:0.42rem;color:#ddd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(tid)}</span>
                <span class="mono" style="font-size:0.38rem;color:${CYAN}">${count} events</span>
            </div>`;
        }
        html += `</div>`;
    }

    // Correlation Stats
    if (data.correlation_stats) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${GREEN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Correlation Success Rate</div>
            ${_correlationGauge(data.correlation_stats)}
        </div>`;
    }

    // Target Activity Summary
    html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
        <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Target Activity</div>
        <div style="display:flex;gap:4px;flex-wrap:wrap">
            ${_statBox('Detected', activity.detected || 0, GREEN)}
            ${_statBox('Lost', activity.lost || 0, MAGENTA)}
            ${_statBox('Sightings', activity.sightings || 0, CYAN)}
        </div>
    </div>`;

    content.innerHTML = html;

    // Wire target item click handlers
    content.querySelectorAll('.ha-target-item').forEach(item => {
        item.addEventListener('click', () => {
            const tid = item.dataset.target;
            if (tid) {
                EventBus.emit('target:focus', { id: tid });
                EventBus.emit('panel:open', { id: 'dossiers', targetId: tid });
            }
        });
        item.addEventListener('mouseenter', () => {
            item.style.background = '#1a1a2e';
        });
        item.addEventListener('mouseleave', () => {
            item.style.background = 'transparent';
        });
    });
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const HistoryAnalyticsPanelDef = {
    id: 'history-analytics',
    title: 'HISTORY ANALYTICS',
    defaultPosition: { x: 40, y: 80 },
    defaultSize: { w: 380, h: 560 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'history-analytics-inner';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;background:#0a0a1a';
        el.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid ${BORDER}">
                <div style="display:flex;gap:4px;align-items:center">
                    <span style="font-size:0.38rem;color:${DIM};text-transform:uppercase">Window:</span>
                    <select data-bind="hours-select" style="background:${SURFACE};border:1px solid ${BORDER};color:${CYAN};padding:2px 6px;font-size:0.38rem;font-family:var(--font-mono);border-radius:2px">
                        <option value="1">1 Hour</option>
                        <option value="6" selected>6 Hours</option>
                        <option value="12">12 Hours</option>
                        <option value="24">24 Hours</option>
                    </select>
                </div>
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.38rem;padding:2px 6px">REFRESH</button>
            </div>
            <div data-bind="analytics-content" style="flex:1;overflow-y:auto">
                <div style="padding:20px;text-align:center;color:${DIM};font-size:0.5rem">Loading analytics...</div>
            </div>
            <div style="padding:3px 8px;border-top:1px solid ${BORDER};display:flex;justify-content:space-between;align-items:center">
                <span class="mono" data-bind="last-update" style="font-size:0.36rem;color:${DIM}">--</span>
                <span class="mono" style="font-size:0.36rem;color:${DIM}">Auto-refresh: 15s</span>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const hoursSelect = bodyEl.querySelector('[data-bind="hours-select"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const lastUpdateEl = bodyEl.querySelector('[data-bind="last-update"]');
        let timer = null;

        function getHours() {
            return parseFloat(hoursSelect?.value || '6');
        }

        async function refresh() {
            const hours = getHours();
            const data = await _fetchAnalytics(hours);
            _render(bodyEl, data, hours);
            if (lastUpdateEl) {
                lastUpdateEl.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
            }
        }

        if (refreshBtn) {
            refreshBtn.addEventListener('click', refresh);
        }
        if (hoursSelect) {
            hoursSelect.addEventListener('change', refresh);
        }

        refresh();
        timer = setInterval(refresh, REFRESH_MS);
        panel._haTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._haTimer) {
            clearInterval(panel._haTimer);
            panel._haTimer = null;
        }
    },
};
