// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// System Health Dashboard Panel — subsystem-level health cards with
// color-coded status, key metrics, and auto-refresh.

import { _esc } from '/lib/utils.js';

const REFRESH_MS = 5000;

const STATUS_COLORS = {
    up:       '#05ffa1',
    degraded: '#fcee0a',
    down:     '#ff2a6d',
    unknown:  '#666',
};

const STATUS_GLOW = {
    up:       'rgba(5,255,161,0.25)',
    degraded: 'rgba(252,238,10,0.25)',
    down:     'rgba(255,42,109,0.25)',
    unknown:  'rgba(100,100,100,0.15)',
};

const STATUS_BORDER = {
    up:       'rgba(5,255,161,0.4)',
    degraded: 'rgba(252,238,10,0.4)',
    down:     'rgba(255,42,109,0.4)',
    unknown:  'rgba(100,100,100,0.25)',
};

const STATUS_LABELS = {
    up:       'OPERATIONAL',
    degraded: 'DEGRADED',
    down:     'OFFLINE',
    unknown:  'UNKNOWN',
};

function _statusDotSvg(status) {
    const c = STATUS_COLORS[status] || STATUS_COLORS.unknown;
    return `<svg width="10" height="10" style="flex-shrink:0"><circle cx="5" cy="5" r="4" fill="${c}" opacity="0.9"><animate attributeName="opacity" values="0.9;0.5;0.9" dur="2s" repeatCount="indefinite"/></circle></svg>`;
}

function _formatBytes(bytes) {
    if (bytes == null) return '--';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function _formatUptime(seconds) {
    if (seconds == null) return '--';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

/**
 * Build a single subsystem card HTML.
 */
function _renderCard(name, status, message, details) {
    const s = status || 'unknown';
    const color = STATUS_COLORS[s] || STATUS_COLORS.unknown;
    const glow = STATUS_GLOW[s] || STATUS_GLOW.unknown;
    const border = STATUS_BORDER[s] || STATUS_BORDER.unknown;
    const label = STATUS_LABELS[s] || s.toUpperCase();

    let metricsHtml = '';
    if (details && typeof details === 'object') {
        const entries = Object.entries(details);
        for (const [key, val] of entries) {
            // Skip nested objects and internal keys
            if (val === null || val === undefined) continue;
            if (typeof val === 'object') continue;

            const displayKey = key.replace(/_/g, ' ').toUpperCase();
            let displayVal = val;
            if (key.includes('bytes') || key === 'db_size_bytes') {
                displayVal = _formatBytes(val);
            } else if (typeof val === 'number' && !Number.isInteger(val)) {
                displayVal = val.toFixed(2);
            }

            metricsHtml += `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:1px 0;">
                    <span style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;">${_esc(displayKey)}</span>
                    <span style="font-size:10px;color:#b0b0c0;font-family:monospace;">${_esc(String(displayVal))}</span>
                </div>`;
        }
    }

    return `
        <div class="shd-card" style="
            background:#0a0a12;
            border:1px solid ${border};
            border-radius:4px;
            padding:8px 10px;
            box-shadow:0 0 8px ${glow};
            transition:box-shadow 0.3s, border-color 0.3s;
        ">
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                ${_statusDotSvg(s)}
                <span style="font-size:11px;color:#ddd;font-weight:bold;text-transform:uppercase;letter-spacing:0.5px;flex:1;">${_esc(name)}</span>
                <span style="font-size:9px;color:${color};font-weight:bold;letter-spacing:1px;">${label}</span>
            </div>
            ${message ? `<div style="font-size:10px;color:#888;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${_esc(message)}">${_esc(message)}</div>` : ''}
            ${metricsHtml ? `<div style="border-top:1px solid rgba(255,255,255,0.05);padding-top:4px;margin-top:2px;">${metricsHtml}</div>` : ''}
        </div>
    `;
}

/**
 * Render the overall status banner.
 */
function _renderOverallBanner(overall, healthyCount, degradedCount, downCount, totalCount) {
    const s = overall || 'unknown';
    const color = STATUS_COLORS[s] || STATUS_COLORS.unknown;
    const label = STATUS_LABELS[s] || s.toUpperCase();

    return `
        <div style="
            display:flex;
            align-items:center;
            gap:10px;
            padding:6px 10px;
            margin-bottom:8px;
            background:rgba(0,0,0,0.3);
            border:1px solid ${STATUS_BORDER[s] || '#333'};
            border-radius:4px;
        ">
            ${_statusDotSvg(s)}
            <span style="font-size:12px;color:${color};font-weight:bold;letter-spacing:1px;">${label}</span>
            <span style="margin-left:auto;font-size:10px;color:#666;font-family:monospace;">
                <span style="color:#05ffa1">${healthyCount}</span> UP
                <span style="color:#666;margin:0 3px;">|</span>
                <span style="color:#fcee0a">${degradedCount}</span> DEG
                <span style="color:#666;margin:0 3px;">|</span>
                <span style="color:#ff2a6d">${downCount}</span> DOWN
                <span style="color:#666;margin:0 3px;">|</span>
                ${totalCount} TOTAL
            </span>
        </div>
    `;
}

/**
 * Render the high-level metrics row (targets, events, uptime, etc.)
 */
function _renderMetricsRow(healthData) {
    const uptime = healthData.uptime_seconds != null
        ? _formatUptime(healthData.uptime_seconds) : '--';
    const targets = healthData.targets_processed ?? '--';
    const events = healthData.events_logged ?? '--';
    const version = healthData.version || '--';

    return `
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;">
            <div style="background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;padding:5px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;">UPTIME</div>
                <div style="font-size:13px;color:#00f0ff;margin-top:2px;font-family:monospace;">${_esc(uptime)}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;padding:5px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;">TARGETS</div>
                <div style="font-size:13px;color:#05ffa1;margin-top:2px;font-family:monospace;">${_esc(String(targets))}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;padding:5px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;">EVENTS</div>
                <div style="font-size:13px;color:#fcee0a;margin-top:2px;font-family:monospace;">${_esc(String(events))}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;padding:5px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;">VERSION</div>
                <div style="font-size:13px;color:#b0b0c0;margin-top:2px;font-family:monospace;">${_esc(version)}</div>
            </div>
        </div>
    `;
}


export const SystemHealthDashboardPanelDef = {
    id: 'system-health-dashboard',
    title: 'SYSTEM HEALTH DASHBOARD',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 480, h: 520 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'shd-panel-inner';
        el.style.cssText = 'padding:8px;overflow-y:auto;height:100%;';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-shd" style="font-size:0.42rem">REFRESH</button>
                <span data-bind="shd-timestamp" style="font-size:10px;color:#555;margin-left:auto;font-family:monospace;">--</span>
            </div>
            <div data-bind="shd-content">
                <div style="color:#555;padding:20px;text-align:center;">Loading system health...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="shd-content"]');
        const timestampEl = bodyEl.querySelector('[data-bind="shd-timestamp"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh-shd"]');
        let timer = null;

        async function fetchData() {
            if (!contentEl) return;

            // Fetch both health endpoints in parallel
            const [healthResp, sitawareResp] = await Promise.allSettled([
                fetch('/api/health').then(r => r.ok ? r.json() : null).catch(() => null),
                fetch('/api/sitaware/health').then(r => r.ok ? r.json() : null).catch(() => null),
            ]);

            const healthData = healthResp.status === 'fulfilled' ? healthResp.value : null;
            const sitawareData = sitawareResp.status === 'fulfilled' ? sitawareResp.value : null;

            if (!healthData && !sitawareData) {
                contentEl.innerHTML = '<div style="color:#ff2a6d;padding:20px;text-align:center;">Failed to load health data</div>';
                return;
            }

            let html = '';

            // High-level metrics row from /api/health
            if (healthData) {
                html += _renderMetricsRow(healthData);
            }

            // Build component list from sitaware health (HealthMonitor components)
            // and supplement with /api/health subsystems
            const components = {};

            // Components from /api/sitaware/health (HealthMonitor — structured)
            if (sitawareData && sitawareData.available && sitawareData.components) {
                for (const [name, comp] of Object.entries(sitawareData.components)) {
                    components[name] = {
                        status: comp.status || 'unknown',
                        message: comp.message || '',
                        details: comp.details || {},
                    };
                }
            }

            // Subsystems from /api/health (basic string statuses)
            if (healthData && healthData.subsystems) {
                for (const [name, val] of Object.entries(healthData.subsystems)) {
                    // Skip hint keys
                    if (name.endsWith('_hint')) continue;

                    // Don't overwrite richer sitaware data
                    if (components[name]) continue;

                    // Map the basic string status to up/degraded/down
                    let status = 'unknown';
                    const v = String(val).toLowerCase();
                    if (v === 'connected' || v === 'running' || v === 'reachable' || v.includes('running')) {
                        status = 'up';
                    } else if (v === 'disabled') {
                        status = 'unknown';
                    } else if (v === 'disconnected' || v === 'unreachable') {
                        status = 'down';
                    }

                    components[name] = {
                        status,
                        message: String(val),
                        details: {},
                    };
                }
            }

            // Compute totals
            const entries = Object.entries(components);
            const totalCount = entries.length;
            let healthyCount = 0;
            let degradedCount = 0;
            let downCount = 0;
            for (const [, c] of entries) {
                if (c.status === 'up') healthyCount++;
                else if (c.status === 'degraded') degradedCount++;
                else if (c.status === 'down') downCount++;
            }

            // Overall status
            let overall = 'unknown';
            if (sitawareData && sitawareData.overall) {
                overall = sitawareData.overall;
            } else if (downCount > 0) {
                overall = 'down';
            } else if (degradedCount > 0) {
                overall = 'degraded';
            } else if (healthyCount > 0) {
                overall = 'up';
            }

            html += _renderOverallBanner(overall, healthyCount, degradedCount, downCount, totalCount);

            // Render subsystem cards in a grid
            if (entries.length > 0) {
                html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:6px;">';
                for (const [name, comp] of entries) {
                    html += _renderCard(name, comp.status, comp.message, comp.details);
                }
                html += '</div>';
            } else {
                html += '<div style="color:#555;padding:20px;text-align:center;">No subsystems registered</div>';
            }

            // RL Training section from /api/health
            if (healthData && healthData.rl_training) {
                const rl = healthData.rl_training;
                const rlEntries = Object.entries(rl).filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object');
                if (rlEntries.length > 0) {
                    html += `<div style="margin-top:8px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">`;
                    html += `<div style="font-size:10px;color:#00f0ff;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">RL TRAINING</div>`;
                    html += `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:4px;">`;
                    for (const [key, val] of rlEntries) {
                        const displayKey = key.replace(/_/g, ' ').toUpperCase();
                        let displayVal = val;
                        if (typeof val === 'number' && !Number.isInteger(val)) {
                            displayVal = val.toFixed(3);
                        }
                        html += `
                            <div style="display:flex;justify-content:space-between;padding:2px 6px;background:#0e0e14;border-radius:2px;">
                                <span style="font-size:9px;color:#666;">${_esc(displayKey)}</span>
                                <span style="font-size:10px;color:#b0b0c0;font-family:monospace;">${_esc(String(displayVal))}</span>
                            </div>`;
                    }
                    html += '</div></div>';
                }
            }

            contentEl.innerHTML = html;

            // Update timestamp
            if (timestampEl) {
                timestampEl.textContent = new Date().toLocaleTimeString();
            }
        }

        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchData);
        }

        // Initial fetch
        fetchData();

        // Auto-refresh every 5 seconds
        timer = setInterval(fetchData, REFRESH_MS);
        panel._shdTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._shdTimer) {
            clearInterval(panel._shdTimer);
            panel._shdTimer = null;
        }
    },
};
