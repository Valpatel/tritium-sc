// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Situation Report (SITREP) Panel
// Displays a real-time tactical situation report from /api/sitrep.
// Shows: threat level, target counts by alliance/type/source, active threats,
// fleet status, geofence breaches, Amy assessment, and system uptime.
// Auto-refreshes every 10 seconds. Operator can request LLM-enhanced narrative.
// UX Loop 6 (Investigate Target) — provides tactical context for investigation.

import { _esc } from '/lib/utils.js';
import { EventBus } from '/lib/events.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_MS = 10000;
const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#888';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

const THREAT_COLORS = {
    GREEN: GREEN,
    YELLOW: YELLOW,
    ORANGE: '#ff8c00',
    RED: MAGENTA,
};

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchSitrep(enhance = false) {
    try {
        const url = enhance ? '/api/sitrep?enhance=true' : '/api/sitrep';
        const r = await fetch(url);
        if (!r.ok) return null;
        return await r.json();
    } catch {
        return null;
    }
}

async function _fetchThreatHistory() {
    try {
        const r = await fetch('/api/threat-level/history?hours=1');
        if (!r.ok) return null;
        return await r.json();
    } catch {
        return null;
    }
}

// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------

function _threatBadge(level) {
    const color = THREAT_COLORS[level] || DIM;
    return `<span style="background:${color};color:#0a0a0f;font-size:0.6rem;padding:2px 10px;border-radius:3px;font-weight:bold;letter-spacing:1px">${_esc(level)}</span>`;
}

function _statBox(label, value, color) {
    return `<div style="text-align:center;flex:1;min-width:60px">
        <div class="mono" style="font-size:0.8rem;color:${color};font-weight:bold">${value}</div>
        <div style="font-size:0.38rem;color:${DIM};text-transform:uppercase;letter-spacing:0.5px">${_esc(label)}</div>
    </div>`;
}

function _barChart(data, maxWidth) {
    if (!data || Object.keys(data).length === 0) {
        return `<div style="color:${DIM};font-size:0.42rem;padding:4px 0">No data</div>`;
    }
    const max = Math.max(...Object.values(data), 1);
    const colors = [CYAN, MAGENTA, GREEN, YELLOW, '#a855f7', '#f97316'];
    let html = '';
    let ci = 0;
    for (const [key, val] of Object.entries(data).sort((a, b) => b[1] - a[1])) {
        const pct = (val / max) * 100;
        const color = colors[ci % colors.length];
        ci++;
        html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
            <span class="mono" style="font-size:0.38rem;color:${DIM};min-width:70px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(key.toUpperCase())}</span>
            <div style="flex:1;height:10px;background:#111;border-radius:2px;overflow:hidden">
                <div style="width:${pct}%;height:100%;background:${color};border-radius:2px;transition:width 0.3s"></div>
            </div>
            <span class="mono" style="font-size:0.38rem;color:${color};min-width:24px;text-align:right">${val}</span>
        </div>`;
    }
    return html;
}

function _threatSparkline(history) {
    if (!history || history.length < 2) return '';
    const w = 200;
    const h = 30;
    const max = Math.max(...history.map(h => h.score || 0), 0.01);
    const pts = history.map((h, i) => {
        const x = (i / (history.length - 1)) * w;
        const y = (h - 2) - ((h.score || 0) / max) * (h - 4);
        return `${x.toFixed(1)},${(30 - 2 - ((h.score || 0) / max) * 26).toFixed(1)}`;
    });
    return `<svg width="${w}" height="${h}" style="display:block;margin:4px auto">
        <polyline points="${pts.join(' ')}" fill="none" stroke="${MAGENTA}" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>`;
}

function _formatUptime(seconds) {
    if (!seconds || seconds <= 0) return '0s';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

function _renderSitrep(bodyEl, sitrep, threatHistory) {
    if (!bodyEl) return;
    const content = bodyEl.querySelector('[data-bind="sitrep-content"]');
    if (!content) return;

    if (!sitrep) {
        content.innerHTML = `<div style="padding:20px;text-align:center;color:${DIM}">
            <div style="font-size:0.6rem;margin-bottom:4px">SITREP UNAVAILABLE</div>
            <div style="font-size:0.42rem">Server may be starting up...</div>
        </div>`;
        return;
    }

    const t = sitrep.targets || {};
    const fleet = sitrep.fleet || {};
    const geo = sitrep.geofence || {};
    const uptime = _formatUptime(sitrep.system?.uptime_s || 0);

    let html = '';

    // Header: Threat Level + ID + Timestamp
    html += `<div style="padding:8px 10px;border-bottom:1px solid ${BORDER};display:flex;justify-content:space-between;align-items:center">
        <div>
            ${_threatBadge(sitrep.threat_level || 'GREEN')}
        </div>
        <div style="text-align:right">
            <div class="mono" style="font-size:0.38rem;color:${DIM}">${_esc(sitrep.sitrep_id || '')}</div>
            <div class="mono" style="font-size:0.36rem;color:${DIM}">Uptime: ${_esc(uptime)}</div>
        </div>
    </div>`;

    // Stats row: Total, Hostile, Friendly, Unknown
    const hostile = t.by_alliance?.hostile || 0;
    const friendly = t.by_alliance?.friendly || 0;
    const neutral = t.by_alliance?.neutral || 0;
    const unknown = (t.total || 0) - hostile - friendly - neutral;

    html += `<div style="display:flex;gap:4px;padding:8px 10px;border-bottom:1px solid ${BORDER}">
        ${_statBox('Total', t.total || 0, CYAN)}
        ${_statBox('Hostile', hostile, MAGENTA)}
        ${_statBox('Friendly', friendly, GREEN)}
        ${_statBox('Unknown', unknown > 0 ? unknown : 0, YELLOW)}
    </div>`;

    // Threat sparkline (if history available)
    if (threatHistory && threatHistory.history && threatHistory.history.length > 1) {
        html += `<div style="padding:4px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.38rem;color:${DIM};margin-bottom:2px;text-transform:uppercase">Threat Level (1h)</div>
            ${_threatSparkline(threatHistory.history)}
        </div>`;
    }

    // By Type
    if (t.by_type && Object.keys(t.by_type).length > 0) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">By Type</div>
            ${_barChart(t.by_type)}
        </div>`;
    }

    // By Source
    if (t.by_source && Object.keys(t.by_source).length > 0) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">By Source</div>
            ${_barChart(t.by_source)}
        </div>`;
    }

    // Active Threats
    if (t.active_threats && t.active_threats.length > 0) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${MAGENTA};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Active Threats (${t.threat_count})</div>`;
        for (const threat of t.active_threats.slice(0, 10)) {
            const name = threat.name || threat.target_id || 'Unknown';
            const pos = (threat.lat && threat.lng)
                ? `${threat.lat.toFixed(4)}, ${threat.lng.toFixed(4)}`
                : 'No position';
            html += `<div class="sitrep-threat-item" data-target="${_esc(threat.target_id || '')}" style="display:flex;justify-content:space-between;align-items:center;padding:2px 4px;margin:1px 0;cursor:pointer;border-radius:2px;border-left:2px solid ${MAGENTA}" title="Click to focus">
                <span style="font-size:0.42rem;color:#ddd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(name)} <span style="color:${DIM}">[${_esc(threat.type || '?')}]</span></span>
                <span class="mono" style="font-size:0.36rem;color:${DIM}">${_esc(pos)}</span>
            </div>`;
        }
        html += `</div>`;
    }

    // Fleet Status
    if (fleet.total_nodes > 0) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Fleet Status</div>
            <div style="display:flex;gap:8px">
                ${_statBox('Online', fleet.online || 0, GREEN)}
                ${_statBox('Offline', fleet.offline || 0, MAGENTA)}
                ${_statBox('Total', fleet.total_nodes, CYAN)}
            </div>
        </div>`;
    }

    // Geofence
    if (geo.zone_count > 0) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Geofence (${geo.zone_count} zones, ${geo.breach_count} events)</div>`;
        if (geo.recent_breaches && geo.recent_breaches.length > 0) {
            for (const b of geo.recent_breaches.slice(0, 5)) {
                const icon = b.event_type === 'enter' ? '\u25b6' : '\u25c0';
                html += `<div style="font-size:0.42rem;color:#ccc;padding:1px 4px">
                    ${icon} <span style="color:${YELLOW}">${_esc(b.target_id)}</span> ${_esc(b.event_type)} <span style="color:${DIM}">${_esc(b.zone)}</span>
                </div>`;
            }
        }
        html += `</div>`;
    }

    // Amy Assessment
    if (sitrep.amy_assessment) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${MAGENTA};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Amy Assessment</div>
            <div style="font-size:0.42rem;color:#ccc;font-style:italic;padding:2px 4px;border-left:2px solid ${MAGENTA}">${_esc(sitrep.amy_assessment)}</div>
        </div>`;
    }

    // LLM Narrative Summary
    if (sitrep.llm_summary) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${GREEN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Narrative Summary</div>
            <div style="font-size:0.42rem;color:#ccc;padding:2px 4px;border-left:2px solid ${GREEN}">${_esc(sitrep.llm_summary)}</div>
        </div>`;
    }

    content.innerHTML = html;

    // Wire threat item click handlers
    content.querySelectorAll('.sitrep-threat-item').forEach(item => {
        item.addEventListener('click', () => {
            const tid = item.dataset.target;
            if (tid) {
                EventBus.emit('target:focus', { id: tid });
                EventBus.emit('map:centerOnUnit', { id: tid });
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

export const SitrepPanelDef = {
    id: 'sitrep',
    title: 'SITUATION REPORT',
    defaultPosition: { x: 20, y: 60 },
    defaultSize: { w: 360, h: 520 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'sitrep-panel-inner';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;background:#0a0a1a';
        el.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid ${BORDER}">
                <span style="font-size:0.42rem;color:${DIM};text-transform:uppercase">Live SITREP</span>
                <div style="display:flex;gap:4px">
                    <button class="panel-action-btn" data-action="enhance" title="Request LLM-enhanced narrative" style="font-size:0.38rem;padding:2px 6px">AI ENHANCE</button>
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.38rem;padding:2px 6px">REFRESH</button>
                </div>
            </div>
            <div data-bind="sitrep-content" style="flex:1;overflow-y:auto">
                <div style="padding:20px;text-align:center;color:${DIM};font-size:0.5rem">Loading SITREP...</div>
            </div>
            <div style="padding:3px 8px;border-top:1px solid ${BORDER};display:flex;justify-content:space-between;align-items:center">
                <span class="mono" data-bind="last-update" style="font-size:0.36rem;color:${DIM}">--</span>
                <span class="mono" style="font-size:0.36rem;color:${DIM}">Auto-refresh: 10s</span>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const enhanceBtn = bodyEl.querySelector('[data-action="enhance"]');
        const lastUpdateEl = bodyEl.querySelector('[data-bind="last-update"]');
        let timer = null;

        async function refresh(enhance = false) {
            const [sitrep, threatHistory] = await Promise.all([
                _fetchSitrep(enhance),
                _fetchThreatHistory(),
            ]);
            _renderSitrep(bodyEl, sitrep, threatHistory);
            if (lastUpdateEl) {
                lastUpdateEl.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
            }
        }

        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => refresh(false));
        }
        if (enhanceBtn) {
            enhanceBtn.addEventListener('click', () => {
                enhanceBtn.textContent = 'ENHANCING...';
                enhanceBtn.disabled = true;
                refresh(true).finally(() => {
                    enhanceBtn.textContent = 'AI ENHANCE';
                    enhanceBtn.disabled = false;
                });
            });
        }

        refresh(false);
        timer = setInterval(() => refresh(false), REFRESH_MS);
        panel._sitrepTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._sitrepTimer) {
            clearInterval(panel._sitrepTimer);
            panel._sitrepTimer = null;
        }
    },
};
