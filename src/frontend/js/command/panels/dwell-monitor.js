// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Dwell Monitor Panel — shows targets that are loitering/dwelling in one location.
// Displays active dwell events with timer, severity, and history.

import { EventBus } from '/lib/events.js';
import { _esc, _timeAgo } from '/lib/utils.js';


function _severityColor(severity) {
    const colors = {
        normal: 'var(--green, #05ffa1)',
        extended: 'var(--yellow, #fcee0a)',
        prolonged: '#ff8800',
        critical: 'var(--magenta, #ff2a6d)',
    };
    return colors[severity] || 'var(--text-dim, #888)';
}

function _severityBadge(severity) {
    const color = _severityColor(severity);
    const label = (severity || 'unknown').toUpperCase();
    return `<span style="color:${color};border:1px solid ${color};padding:1px 4px;border-radius:2px;font-size:10px">${label}</span>`;
}

function _formatDuration(seconds) {
    if (!seconds && seconds !== 0) return '--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function _dwellRingsCSS(severity) {
    const color = _severityColor(severity);
    return `
        display:inline-block;width:16px;height:16px;border-radius:50%;
        border:2px solid ${color};
        box-shadow:0 0 0 3px ${color}33, 0 0 0 6px ${color}1a;
        margin-right:4px;vertical-align:middle;
    `;
}


export const DwellMonitorPanelDef = {
    id: 'dwell-monitor',
    title: 'DWELL MONITOR',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 520, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'dwell-monitor-inner';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%';
        el.innerHTML = `
            <div style="padding:6px 8px;border-bottom:1px solid rgba(0,240,255,0.15);display:flex;gap:16px;align-items:center">
                <div style="text-align:center">
                    <span class="mono" data-bind="active-count" style="color:#00f0ff;font-size:16px;font-weight:bold">0</span>
                    <div style="font-size:9px;color:#555">DWELLING</div>
                </div>
                <div style="flex:1;font-size:10px;color:#555">
                    Targets stationary for 5+ minutes. Concentric rings on map indicate dwell severity.
                </div>
            </div>
            <div style="padding:4px 8px;font-size:10px;color:#555;border-bottom:1px solid rgba(0,240,255,0.08)">
                ACTIVE DWELLS
            </div>
            <div style="flex:1;overflow-y:auto;min-height:0" data-bind="active-list">
                <div style="padding:12px;color:#555;text-align:center">No active dwells</div>
            </div>
            <div style="padding:4px 8px;font-size:10px;color:#555;border-top:1px solid rgba(0,240,255,0.15);border-bottom:1px solid rgba(0,240,255,0.08)">
                RECENT HISTORY
            </div>
            <div style="max-height:120px;overflow-y:auto" data-bind="history-list">
                <div style="padding:8px;color:#555;text-align:center;font-size:10px">No history</div>
            </div>
            <div style="padding:4px 8px;border-top:1px solid rgba(0,240,255,0.1);display:flex;justify-content:space-between;align-items:center">
                <span class="mono" style="color:#555;font-size:10px" data-bind="refresh-ts">--</span>
                <button class="panel-action-btn" data-action="refresh">REFRESH</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const activeCountEl = bodyEl.querySelector('[data-bind="active-count"]');
        const activeListEl = bodyEl.querySelector('[data-bind="active-list"]');
        const historyListEl = bodyEl.querySelector('[data-bind="history-list"]');
        const refreshTsEl = bodyEl.querySelector('[data-bind="refresh-ts"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        let refreshInterval = null;

        async function fetchAndRender() {
            try {
                const [activeRes, histRes] = await Promise.all([
                    fetch('/api/dwell/active'),
                    fetch('/api/dwell/history'),
                ]);

                if (!activeRes.ok || !histRes.ok) {
                    if (refreshTsEl) refreshTsEl.textContent = 'API error';
                    return;
                }

                const activeData = await activeRes.json();
                const histData = await histRes.json();

                // Update active count
                const dwells = activeData.dwells || [];
                if (activeCountEl) activeCountEl.textContent = dwells.length;

                // Render active dwells
                if (activeListEl) {
                    if (dwells.length === 0) {
                        activeListEl.innerHTML = '<div style="padding:12px;color:#555;text-align:center">No active dwells</div>';
                    } else {
                        activeListEl.innerHTML = dwells.map(d => {
                            const name = _esc(d.target_name || d.target_id || '--');
                            const rings = _dwellRingsCSS(d.severity);
                            return `<div style="padding:4px 8px;border-bottom:1px solid rgba(255,255,255,0.03);display:flex;align-items:center;gap:6px">
                                <span style="${rings}"></span>
                                <span class="mono" style="color:#b0b0c0;min-width:100px">${name}</span>
                                <span class="mono" style="color:#00f0ff;min-width:60px">${_formatDuration(d.duration_s)}</span>
                                ${_severityBadge(d.severity)}
                                <span style="color:#555;font-size:10px;margin-left:auto">${_esc(d.target_type || '')}</span>
                            </div>`;
                        }).join('');
                    }
                }

                // Render history (last 20)
                const history = (histData.dwells || []).slice(0, 20);
                if (historyListEl) {
                    if (history.length === 0) {
                        historyListEl.innerHTML = '<div style="padding:8px;color:#555;text-align:center;font-size:10px">No history</div>';
                    } else {
                        historyListEl.innerHTML = history.map(d => {
                            const name = _esc(d.target_name || d.target_id || '--');
                            return `<div style="padding:2px 8px;font-size:10px;color:#555;border-bottom:1px solid rgba(255,255,255,0.02)">
                                <span class="mono" style="color:#888">${name}</span>
                                <span class="mono" style="color:#666;margin-left:8px">${_formatDuration(d.duration_s)}</span>
                                <span style="margin-left:8px">${_severityBadge(d.severity)}</span>
                            </div>`;
                        }).join('');
                    }
                }

                if (refreshTsEl) {
                    refreshTsEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
                }

                // Emit dwell data to map for ring rendering
                EventBus.emit('dwell:active', { dwells });

            } catch (err) {
                if (refreshTsEl) refreshTsEl.textContent = 'Fetch error';
            }
        }

        // Initial fetch
        fetchAndRender();

        // Auto-refresh every 10s
        refreshInterval = setInterval(fetchAndRender, 10000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Manual refresh
        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchAndRender);
        }

        // Listen for dwell WebSocket events
        const unsub1 = EventBus.on('dwell:start', () => fetchAndRender());
        const unsub2 = EventBus.on('dwell:end', () => fetchAndRender());
        if (unsub1) panel._unsubs.push(unsub1);
        if (unsub2) panel._unsubs.push(unsub2);
    },

    unmount(bodyEl) {
        // Cleanup handled by panel._unsubs
    },
};
