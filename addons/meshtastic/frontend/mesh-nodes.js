// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Meshtastic Addon — Mesh Nodes sortable table panel
// Displays all mesh nodes with sortable columns, battery color-coding
// Click row to center map on that node

import { EventBus } from '../../../src/frontend/js/command/events.js';
import { _esc, _timeAgo } from '../../../src/frontend/js/command/panel-utils.js';

const API_BASE = '/api/addons/meshtastic';
const REFRESH_MS = 10000;

function _batteryColor(bat) {
    if (bat === null || bat === undefined) return 'var(--text-dim, #888)';
    if (bat > 70) return 'var(--green, #05ffa1)';
    if (bat >= 30) return 'var(--yellow, #fcee0a)';
    return 'var(--magenta, #ff2a6d)';
}

function _formatUptime(seconds) {
    if (!seconds && seconds !== 0) return '--';
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h';
    return Math.floor(seconds / 86400) + 'd';
}

const COLUMNS = [
    { key: 'name',       label: 'NAME',     width: '18%' },
    { key: 'short_name', label: 'SHORT',    width: '8%' },
    { key: 'hw_model',   label: 'HW MODEL', width: '14%' },
    { key: 'battery',    label: 'BAT',      width: '7%',  align: 'right' },
    { key: 'voltage',    label: 'VOLT',     width: '7%',  align: 'right' },
    { key: 'snr',        label: 'SNR',      width: '7%',  align: 'right' },
    { key: 'last_heard', label: 'HEARD',    width: '9%',  align: 'right' },
    { key: 'lat',        label: 'LAT',      width: '10%', align: 'right' },
    { key: 'lng',        label: 'LNG',      width: '10%', align: 'right' },
    { key: 'uptime',     label: 'UPTIME',   width: '10%', align: 'right' },
];

export const MeshNodesPanelDef = {
    id: 'mesh-nodes',
    title: 'MESH NODES',
    defaultPosition: { x: 8, y: 470 },
    defaultSize: { w: 620, h: 380 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'mesh-nodes-panel';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;';

        // Build header row
        const headerCells = COLUMNS.map(col =>
            `<th class="mesh-nodes-th" data-sort="${col.key}"
                style="width:${col.width};text-align:${col.align || 'left'};cursor:pointer;padding:3px 4px;font-size:0.65rem;color:var(--text-dim,#888);border-bottom:1px solid var(--border,#1a1a2e);user-select:none;white-space:nowrap;">
                ${col.label} <span class="mesh-sort-arrow" data-arrow="${col.key}"></span>
            </th>`
        ).join('');

        el.innerHTML = `
            <div class="mesh-nodes-count mono" style="padding:4px 8px;font-size:0.7rem;color:var(--text-dim,#888);">
                <span data-bind="count">0 nodes</span>
            </div>
            <div style="flex:1;overflow-y:auto;overflow-x:hidden;">
                <table class="mesh-nodes-table" style="width:100%;border-collapse:collapse;font-size:0.7rem;">
                    <thead>
                        <tr>${headerCells}</tr>
                    </thead>
                    <tbody data-bind="tbody">
                        <tr><td colspan="${COLUMNS.length}" class="panel-empty" style="text-align:center;padding:20px;">No nodes discovered</td></tr>
                    </tbody>
                </table>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const tbodyEl = bodyEl.querySelector('[data-bind="tbody"]');
        const countEl = bodyEl.querySelector('[data-bind="count"]');
        const headerRow = bodyEl.querySelector('thead tr');

        let nodes = [];
        let sortKey = 'last_heard';
        let sortDir = -1; // -1 = descending, 1 = ascending

        // Sort click handler
        if (headerRow) {
            headerRow.addEventListener('click', (e) => {
                const th = e.target.closest('[data-sort]');
                if (!th) return;
                const key = th.dataset.sort;
                if (sortKey === key) {
                    sortDir *= -1;
                } else {
                    sortKey = key;
                    sortDir = -1;
                }
                updateArrows();
                renderTable();
            });
        }

        function updateArrows() {
            const arrows = bodyEl.querySelectorAll('.mesh-sort-arrow');
            arrows.forEach(a => {
                if (a.dataset.arrow === sortKey) {
                    a.textContent = sortDir === -1 ? 'v' : '^';
                    a.style.color = 'var(--cyan, #00f0ff)';
                } else {
                    a.textContent = '';
                }
            });
        }

        function sortNodes(arr) {
            return [...arr].sort((a, b) => {
                let va = a[sortKey];
                let vb = b[sortKey];

                // Name columns: sort alphabetically
                if (sortKey === 'name' || sortKey === 'short_name' || sortKey === 'hw_model') {
                    va = (va || '').toLowerCase();
                    vb = (vb || '').toLowerCase();
                    return va.localeCompare(vb) * sortDir;
                }

                // Numeric columns: null goes to bottom
                if (va === null || va === undefined) va = -Infinity;
                if (vb === null || vb === undefined) vb = -Infinity;
                return (va - vb) * sortDir;
            });
        }

        function renderTable() {
            if (!tbodyEl) return;

            const sorted = sortNodes(nodes);

            if (sorted.length === 0) {
                tbodyEl.innerHTML = `<tr><td colspan="${COLUMNS.length}" class="panel-empty" style="text-align:center;padding:20px;">No nodes discovered</td></tr>`;
                return;
            }

            tbodyEl.innerHTML = sorted.map(n => {
                const name = _esc(n.long_name || n.node_id || '???');
                const shortName = _esc(n.short_name || '--');
                const hw = _esc(n.hw_model || '--');
                const bat = n.battery !== null && n.battery !== undefined
                    ? Math.round(n.battery) + '%' : '--';
                const batColor = _batteryColor(n.battery);
                const volt = n.voltage !== null && n.voltage !== undefined
                    ? Number(n.voltage).toFixed(2) + 'V' : '--';
                const snr = n.snr !== null && n.snr !== undefined
                    ? Number(n.snr).toFixed(1) : '--';
                const heard = n.last_heard ? _timeAgo(n.last_heard) : '--';
                const lat = n.lat !== null && n.lat !== undefined
                    ? Number(n.lat).toFixed(4) : '--';
                const lng = n.lng !== null && n.lng !== undefined
                    ? Number(n.lng).toFixed(4) : '--';
                const uptime = _formatUptime(n.uptime);
                const nid = _esc(n.node_id || '');

                const hasGps = n.lat !== null && n.lat !== undefined &&
                               n.lng !== null && n.lng !== undefined &&
                               (n.lat !== 0 || n.lng !== 0);

                return `<tr class="mesh-nodes-row" data-node-id="${nid}"
                            style="cursor:${hasGps ? 'pointer' : 'default'};border-bottom:1px solid rgba(255,255,255,0.04);"
                            title="${hasGps ? 'Click to center map' : 'No GPS position'}">
                    <td class="mono" style="padding:3px 4px;color:var(--cyan,#00f0ff);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:0;">${name}</td>
                    <td class="mono" style="padding:3px 4px;color:var(--text-dim,#888)">${shortName}</td>
                    <td class="mono" style="padding:3px 4px;color:var(--text-dim,#888);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:0;">${hw}</td>
                    <td class="mono" style="padding:3px 4px;text-align:right;color:${batColor}">${bat}</td>
                    <td class="mono" style="padding:3px 4px;text-align:right;color:var(--text-dim,#888)">${volt}</td>
                    <td class="mono" style="padding:3px 4px;text-align:right">${snr}</td>
                    <td class="mono" style="padding:3px 4px;text-align:right;color:var(--text-dim,#888)">${heard}</td>
                    <td class="mono" style="padding:3px 4px;text-align:right;color:var(--text-dim,#888)">${lat}</td>
                    <td class="mono" style="padding:3px 4px;text-align:right;color:var(--text-dim,#888)">${lng}</td>
                    <td class="mono" style="padding:3px 4px;text-align:right;color:var(--text-dim,#888)">${uptime}</td>
                </tr>`;
            }).join('');

            // Click to center map
            tbodyEl.querySelectorAll('.mesh-nodes-row').forEach(row => {
                row.addEventListener('click', () => {
                    const nodeId = row.dataset.nodeId;
                    const node = nodes.find(n => n.node_id === nodeId);
                    if (node && node.lat !== null && node.lat !== undefined &&
                        node.lng !== null && node.lng !== undefined &&
                        (node.lat !== 0 || node.lng !== 0)) {
                        EventBus.emit('mesh:center-on-node', {
                            id: nodeId,
                            lat: node.lat,
                            lng: node.lng,
                        });
                    }
                });

                // Hover highlight
                row.addEventListener('mouseenter', () => {
                    row.style.background = 'rgba(0, 240, 255, 0.06)';
                });
                row.addEventListener('mouseleave', () => {
                    row.style.background = '';
                });
            });
        }

        async function fetchNodes() {
            try {
                const res = await fetch(API_BASE + '/nodes');
                if (!res.ok) return;
                const data = await res.json();
                nodes = data.nodes || [];

                // Normalize name field for sorting
                nodes.forEach(n => {
                    if (!n.name) n.name = n.long_name || n.short_name || n.node_id || '';
                });

                if (countEl) countEl.textContent = nodes.length + ' node' + (nodes.length !== 1 ? 's' : '');
                renderTable();
            } catch (_) {}
        }

        // Initial sort arrow
        updateArrows();

        // EventBus subscriptions
        panel._unsubs.push(
            EventBus.on('mesh:telemetry', () => fetchNodes()),
            EventBus.on('mesh:position', () => fetchNodes()),
        );

        // Auto-refresh
        const refreshTimer = setInterval(fetchNodes, REFRESH_MS);
        panel._unsubs.push(() => clearInterval(refreshTimer));

        // Initial fetch
        fetchNodes();
    },

    unmount(bodyEl, panel) {
        // _unsubs cleaned up by panel base class
    },
};
