// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Meshtastic Addon — Main overview panel
// Shows connection status, transport, device info, quick stats
// Fetches from /api/addons/meshtastic/status and /api/addons/meshtastic/nodes

import { EventBus } from '../../../src/frontend/js/command/events.js';
import { _esc } from '../../../src/frontend/js/command/panel-utils.js';

const API_BASE = '/api/addons/meshtastic';
const REFRESH_MS = 5000;

export const MeshNetworkPanelDef = {
    id: 'mesh-network',
    title: 'MESHTASTIC',
    defaultPosition: { x: 8, y: 60 },
    defaultSize: { w: 340, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'mesh-network-panel';
        el.innerHTML = `
            <div class="mesh-net-status-section">
                <div class="panel-section-label">CONNECTION</div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">STATUS</span>
                    <span class="panel-stat-value" data-bind="conn-status">
                        <span class="panel-dot panel-dot-neutral" data-bind="status-dot"></span>
                        <span data-bind="status-text">DISCONNECTED</span>
                    </span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">TRANSPORT</span>
                    <span class="panel-stat-value mono" data-bind="transport">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">PORT</span>
                    <span class="panel-stat-value mono" data-bind="port">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">DEVICE</span>
                    <span class="panel-stat-value mono" data-bind="device-name">--</span>
                </div>
            </div>
            <div class="mesh-net-actions" style="display:flex;gap:6px;padding:6px 8px;">
                <button class="panel-action-btn panel-action-btn-primary" data-action="connect"
                        style="flex:1">CONNECT</button>
                <button class="panel-action-btn" data-action="disconnect"
                        style="flex:1">DISCONNECT</button>
            </div>
            <div class="mesh-net-stats-section">
                <div class="panel-section-label">MESH STATS</div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;padding:4px 8px;">
                    <div class="panel-stat-row" style="flex-direction:column;align-items:flex-start;">
                        <span class="panel-stat-label" style="font-size:0.6rem">NODES</span>
                        <span class="panel-stat-value mono" data-bind="node-count"
                              style="font-size:1.4rem;color:var(--cyan, #00f0ff)">0</span>
                    </div>
                    <div class="panel-stat-row" style="flex-direction:column;align-items:flex-start;">
                        <span class="panel-stat-label" style="font-size:0.6rem">WITH GPS</span>
                        <span class="panel-stat-value mono" data-bind="gps-count"
                              style="font-size:1.4rem;color:var(--green, #05ffa1)">0</span>
                    </div>
                    <div class="panel-stat-row" style="flex-direction:column;align-items:flex-start;">
                        <span class="panel-stat-label" style="font-size:0.6rem">AVG BATTERY</span>
                        <span class="panel-stat-value mono" data-bind="avg-battery"
                              style="font-size:1.4rem;color:var(--yellow, #fcee0a)">--%</span>
                    </div>
                    <div class="panel-stat-row" style="flex-direction:column;align-items:flex-start;">
                        <span class="panel-stat-label" style="font-size:0.6rem">MESH UTIL</span>
                        <span class="panel-stat-value mono" data-bind="mesh-util"
                              style="font-size:1.4rem;color:var(--magenta, #ff2a6d)">--%</span>
                    </div>
                </div>
            </div>
            <div class="mesh-net-node-summary" style="padding:4px 8px;">
                <div class="panel-section-label">RECENT ACTIVITY</div>
                <ul class="panel-list" data-bind="recent-nodes" style="max-height:140px;overflow-y:auto;">
                    <li class="panel-empty">No nodes yet</li>
                </ul>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const statusDot = bodyEl.querySelector('[data-bind="status-dot"]');
        const statusText = bodyEl.querySelector('[data-bind="status-text"]');
        const transportEl = bodyEl.querySelector('[data-bind="transport"]');
        const portEl = bodyEl.querySelector('[data-bind="port"]');
        const deviceNameEl = bodyEl.querySelector('[data-bind="device-name"]');
        const nodeCountEl = bodyEl.querySelector('[data-bind="node-count"]');
        const gpsCountEl = bodyEl.querySelector('[data-bind="gps-count"]');
        const avgBatteryEl = bodyEl.querySelector('[data-bind="avg-battery"]');
        const meshUtilEl = bodyEl.querySelector('[data-bind="mesh-util"]');
        const recentNodesEl = bodyEl.querySelector('[data-bind="recent-nodes"]');
        const connectBtn = bodyEl.querySelector('[data-action="connect"]');
        const disconnectBtn = bodyEl.querySelector('[data-action="disconnect"]');

        let connected = false;

        function updateStatus(data) {
            if (!data) return;
            connected = data.connected || false;

            if (statusDot) {
                statusDot.className = connected
                    ? 'panel-dot panel-dot-green'
                    : 'panel-dot panel-dot-neutral';
            }
            if (statusText) {
                statusText.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
                statusText.style.color = connected
                    ? 'var(--green, #05ffa1)'
                    : 'var(--text-dim, #888)';
            }
            if (transportEl) transportEl.textContent = _esc(data.transport || '--');
            if (portEl) portEl.textContent = _esc(data.port || '--');

            const dev = data.device || {};
            const devName = dev.long_name || dev.short_name || dev.hw_model || '--';
            if (deviceNameEl) deviceNameEl.textContent = _esc(devName);

            if (nodeCountEl && data.node_count !== undefined) {
                nodeCountEl.textContent = String(data.node_count);
            }
        }

        function updateNodes(data) {
            if (!data) return;
            const nodes = data.nodes || [];

            if (nodeCountEl) nodeCountEl.textContent = String(nodes.length);

            // GPS count
            const withGps = nodes.filter(n =>
                n.lat !== null && n.lat !== undefined &&
                n.lng !== null && n.lng !== undefined &&
                (n.lat !== 0 || n.lng !== 0)
            ).length;
            if (gpsCountEl) gpsCountEl.textContent = String(withGps);

            // Average battery
            const batteries = nodes
                .map(n => n.battery)
                .filter(b => b !== null && b !== undefined && b > 0);
            if (avgBatteryEl) {
                if (batteries.length > 0) {
                    const avg = Math.round(batteries.reduce((a, b) => a + b, 0) / batteries.length);
                    avgBatteryEl.textContent = avg + '%';
                    avgBatteryEl.style.color = avg > 70
                        ? 'var(--green, #05ffa1)'
                        : avg > 30
                            ? 'var(--yellow, #fcee0a)'
                            : 'var(--magenta, #ff2a6d)';
                } else {
                    avgBatteryEl.textContent = '--%';
                }
            }

            // Mesh utilization (average channel_util)
            const utils = nodes
                .map(n => n.channel_util)
                .filter(u => u !== null && u !== undefined);
            if (meshUtilEl) {
                if (utils.length > 0) {
                    const avg = (utils.reduce((a, b) => a + b, 0) / utils.length).toFixed(1);
                    meshUtilEl.textContent = avg + '%';
                } else {
                    meshUtilEl.textContent = '--%';
                }
            }

            // Recent nodes (last 5 heard)
            if (recentNodesEl) {
                const sorted = [...nodes]
                    .filter(n => n.last_heard)
                    .sort((a, b) => (b.last_heard || 0) - (a.last_heard || 0))
                    .slice(0, 5);

                if (sorted.length === 0) {
                    recentNodesEl.innerHTML = '<li class="panel-empty">No nodes yet</li>';
                } else {
                    const now = Math.floor(Date.now() / 1000);
                    recentNodesEl.innerHTML = sorted.map(n => {
                        const name = _esc(n.short_name || n.long_name || n.node_id || '???');
                        const delta = now - (n.last_heard || 0);
                        let age = '--';
                        if (delta < 60) age = delta + 's ago';
                        else if (delta < 3600) age = Math.floor(delta / 60) + 'm ago';
                        else if (delta < 86400) age = Math.floor(delta / 3600) + 'h ago';
                        else age = Math.floor(delta / 86400) + 'd ago';

                        const bat = n.battery !== null && n.battery !== undefined
                            ? Math.round(n.battery) + '%' : '';
                        return `<li class="panel-list-item" style="padding:3px 4px;font-size:0.75rem;">
                            <span class="panel-icon-badge" style="color:var(--cyan);border-color:var(--cyan);font-size:0.6rem;width:16px;height:16px;line-height:16px">M</span>
                            <span class="mono" style="flex:1">${name}</span>
                            <span class="mono" style="color:var(--text-dim);margin-right:6px">${bat}</span>
                            <span class="mono" style="color:var(--text-dim)">${age}</span>
                        </li>`;
                    }).join('');
                }
            }
        }

        async function fetchAll() {
            try {
                const [statusRes, nodesRes] = await Promise.all([
                    fetch(API_BASE + '/status').then(r => r.ok ? r.json() : null),
                    fetch(API_BASE + '/nodes').then(r => r.ok ? r.json() : null),
                ]);
                updateStatus(statusRes);
                updateNodes(nodesRes);
            } catch (_) {
                // Silent on network errors
            }
        }

        // Connect / disconnect buttons
        if (connectBtn) {
            connectBtn.addEventListener('click', async () => {
                connectBtn.disabled = true;
                connectBtn.textContent = 'CONNECTING...';
                try {
                    const res = await fetch(API_BASE + '/connect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ transport: 'serial', port: '' }),
                    });
                    if (res.ok) {
                        const data = await res.json();
                        updateStatus(data);
                    }
                } catch (_) {}
                connectBtn.disabled = false;
                connectBtn.textContent = 'CONNECT';
            });
        }

        if (disconnectBtn) {
            disconnectBtn.addEventListener('click', async () => {
                try {
                    await fetch(API_BASE + '/disconnect', { method: 'POST' });
                    updateStatus({ connected: false, transport: 'none', port: '', device: {} });
                } catch (_) {}
            });
        }

        // EventBus integration
        panel._unsubs.push(
            EventBus.on('mesh:connected', () => fetchAll()),
            EventBus.on('mesh:disconnected', () => fetchAll()),
            EventBus.on('mesh:telemetry', () => fetchAll()),
        );

        // Auto-refresh
        const refreshTimer = setInterval(fetchAll, REFRESH_MS);
        panel._unsubs.push(() => clearInterval(refreshTimer));

        // Initial fetch
        fetchAll();
    },

    unmount(bodyEl, panel) {
        // _unsubs cleaned up by panel base class
    },
};
