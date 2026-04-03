// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// SitAware Panel — unified operating picture overview.
// Shows: target count, alert count, threat level, system health summary.
// Auto-refreshes every 3 seconds from /api/sitaware/picture.

import { _esc } from '/lib/utils.js';

const REFRESH_MS = 3000;

const THREAT_COLORS = {
    green: '#05ffa1',
    yellow: '#fcee0a',
    orange: '#ff8c00',
    red: '#ff2a6d',
};

const THREAT_LABELS = {
    green: 'ALL CLEAR',
    yellow: 'ELEVATED',
    orange: 'HIGH ALERT',
    red: 'CRITICAL',
};

function _threatBadge(level) {
    const color = THREAT_COLORS[level] || '#888';
    const label = THREAT_LABELS[level] || level.toUpperCase();
    return `<span style="color:${color};font-weight:bold;font-size:12px;letter-spacing:1px;">${label}</span>`;
}

function _healthDot(status) {
    if (status === 'up') return '<span style="color:#05ffa1;">UP</span>';
    if (status === 'degraded') return '<span style="color:#fcee0a;">DEGRADED</span>';
    return '<span style="color:#ff2a6d;">DOWN</span>';
}

function _renderPicture(data) {
    if (!data || !data.available) {
        return '<div style="color:#555;padding:12px;text-align:center;">SitAware engine not available</div>';
    }

    const threat = data.threat_level || 'green';
    const summary = data.summary || 'No data';

    // Stat cards
    const stats = `
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;">
            <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                <div style="font-size:10px;color:#666;text-transform:uppercase;">Targets</div>
                <div style="font-size:18px;color:#00f0ff;margin-top:2px;">${data.target_count || 0}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                <div style="font-size:10px;color:#666;text-transform:uppercase;">Multi-Src</div>
                <div style="font-size:18px;color:#05ffa1;margin-top:2px;">${data.multi_source_targets || 0}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                <div style="font-size:10px;color:#666;text-transform:uppercase;">Alerts</div>
                <div style="font-size:18px;color:#fcee0a;margin-top:2px;">${data.active_alert_count || 0}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                <div style="font-size:10px;color:#666;text-transform:uppercase;">Incidents</div>
                <div style="font-size:18px;color:#ff2a6d;margin-top:2px;">${data.incident_count || 0}</div>
            </div>
        </div>
    `;

    // Threat level bar
    const threatBar = `
        <div style="display:flex;align-items:center;gap:8px;padding:6px 8px;margin-bottom:8px;background:#0e0e14;border:1px solid ${THREAT_COLORS[threat] || '#1a1a2e'};">
            <span style="font-size:10px;color:#666;text-transform:uppercase;">THREAT</span>
            ${_threatBadge(threat)}
        </div>
    `;

    // Summary line
    const summaryLine = `
        <div style="padding:4px 8px;margin-bottom:8px;font-size:11px;color:#b0b0c0;border-left:2px solid ${THREAT_COLORS[threat] || '#333'};">
            ${_esc(summary)}
        </div>
    `;

    // Secondary row: anomalies, missions, zones
    const secondary = `
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px;">
            <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:4px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;">Anomalies</div>
                <div style="font-size:14px;color:#ff8c00;margin-top:1px;">${data.active_anomaly_count || 0}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:4px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;">Missions</div>
                <div style="font-size:14px;color:#00f0ff;margin-top:1px;">${data.mission_count || 0}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:4px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;">Zones</div>
                <div style="font-size:14px;color:#05ffa1;margin-top:1px;">${data.zone_count || 0}</div>
            </div>
        </div>
    `;

    // Health subsystem list
    let healthRows = '';
    const components = (data.health && data.health.components) || {};
    for (const [name, comp] of Object.entries(components)) {
        const status = (comp && comp.status) || 'unknown';
        const msg = (comp && comp.message) || '';
        healthRows += `
            <div style="display:flex;align-items:center;gap:6px;padding:2px 0;font-size:11px;">
                <span style="min-width:70px;color:#888;text-transform:uppercase;">${_esc(name)}</span>
                ${_healthDot(status)}
                <span style="color:#555;font-size:10px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(msg)}</span>
            </div>
        `;
    }

    const healthSection = healthRows ? `
        <div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
            <div style="font-size:10px;color:#05ffa1;margin-bottom:4px;text-transform:uppercase;">System Health</div>
            ${healthRows}
        </div>
    ` : '';

    return stats + threatBar + summaryLine + secondary + healthSection;
}

export const SitAwarePanelDef = {
    id: 'sitaware',
    title: 'OPERATING PICTURE',
    defaultPosition: { x: 200, y: 60 },
    defaultSize: { w: 420, h: 440 },

    create(panel) {
        const el = document.createElement('div');
        el.style.padding = '8px';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                <span data-bind="updated" style="font-size:10px;color:#555;margin-left:auto;">--</span>
            </div>
            <div data-bind="picture">
                <div style="color:#555;padding:12px;text-align:center;">Loading...</div>
            </div>
        `;

        return el;
    },

    mount(bodyEl, panel) {
        const pictureEl = bodyEl.querySelector('[data-bind="picture"]');
        const updatedEl = bodyEl.querySelector('[data-bind="updated"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        let timer = null;

        async function fetchPicture() {
            try {
                const resp = await fetch('/api/sitaware/picture');
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                if (pictureEl) pictureEl.innerHTML = _renderPicture(data);
                if (updatedEl) updatedEl.textContent = new Date().toLocaleTimeString();
            } catch (e) {
                console.error('[SitAware] fetch failed:', e);
                if (pictureEl) pictureEl.innerHTML = '<div style="color:#ff2a6d;padding:12px;text-align:center;">Failed to load</div>';
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', fetchPicture);

        fetchPicture();
        timer = setInterval(fetchPicture, REFRESH_MS);
        panel._sitawareTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._sitawareTimer) {
            clearInterval(panel._sitawareTimer);
            panel._sitawareTimer = null;
        }
    },
};
