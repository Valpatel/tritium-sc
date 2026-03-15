// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Operator Activity Panel — shows real-time who is doing what
//
// Displays operator actions: logins, target updates, investigations,
// cursor movements. Polls /api/operator-activity for recent entries.

const POLL_INTERVAL_MS = 5000;
const MAX_ENTRIES = 50;

const ROLE_COLORS = {
    admin: '#fcee0a',
    commander: '#ff2a6d',
    analyst: '#00f0ff',
    operator: '#05ffa1',
    observer: '#8888aa',
};

function _roleColor(role) {
    return ROLE_COLORS[role] || '#888';
}

function _formatTs(ts) {
    if (!ts) return '??:??';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function _renderEntry(entry) {
    const color = _roleColor(entry.role);
    const time = _formatTs(entry.timestamp);
    const action = entry.action || '';
    const detail = entry.detail || '';
    const username = entry.username || 'unknown';

    return `<div style="border-left:3px solid ${color};padding:4px 8px;margin:2px 0;">
        <span style="color:#555;font-size:11px;">${time}</span>
        <span style="color:${color};font-weight:bold;margin:0 4px;">${username}</span>
        <span style="color:#aaa;">${action}</span>
        ${detail ? `<div style="color:#777;font-size:11px;padding-left:8px;">${detail}</div>` : ''}
    </div>`;
}

export const OperatorActivityPanelDef = {
    id: 'operator-activity',
    title: 'OPERATOR ACTIVITY',
    defaultPosition: { x: 280, y: 100 },
    defaultSize: { w: 360, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.innerHTML = `
            <div style="padding:8px;">
                <div style="display:flex;gap:4px;margin-bottom:8px;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                </div>
                <div data-bind="entries" style="overflow-y:auto;max-height:320px;">
                    <div style="color:#555;padding:20px;text-align:center;">Loading operator activity...</div>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const entriesDiv = bodyEl.querySelector('[data-bind="entries"]');
        let entries = [];

        async function poll() {
            try {
                const resp = await fetch('/api/operator-activity?limit=50');
                if (!resp.ok) return;
                const data = await resp.json();
                entries = data.activities || [];
                render();
            } catch (e) { /* silent */ }
        }

        function render() {
            if (entries.length === 0) {
                entriesDiv.innerHTML = '<div style="color:#555;padding:20px;text-align:center;">No operator activity yet</div>';
                return;
            }
            entriesDiv.innerHTML = entries.map(_renderEntry).join('');
        }

        bodyEl.addEventListener('click', (e) => {
            if (e.target.dataset?.action === 'refresh') poll();
        });

        poll();
        panel._opActivityTimer = setInterval(poll, POLL_INTERVAL_MS);
    },

    unmount(bodyEl, panel) {
        if (panel._opActivityTimer) {
            clearInterval(panel._opActivityTimer);
            panel._opActivityTimer = null;
        }
    },
};
