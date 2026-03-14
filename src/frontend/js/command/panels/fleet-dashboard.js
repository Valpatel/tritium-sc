// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Fleet Dashboard Panel — aggregated fleet device monitoring
// Displays device list with online/offline/stale status badges,
// battery level bars, sighting counts, uptime. Auto-refreshes every 10s.

import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function _timeAgo(ts) {
    if (!ts) return 'never';
    const secs = Math.floor(Date.now() / 1000 - ts);
    if (secs < 5) return 'just now';
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return `${Math.floor(secs / 86400)}d ago`;
}

function _formatUptime(seconds) {
    if (!seconds && seconds !== 0) return '--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

function _statusBadge(status) {
    const colors = {
        online: 'var(--green, #05ffa1)',
        stale: 'var(--yellow, #fcee0a)',
        offline: 'var(--magenta, #ff2a6d)',
    };
    const color = colors[status] || 'var(--text-dim, #888)';
    return `<span class="fleet-dash-status-badge" style="color:${color};border-color:${color}">${(status || 'unknown').toUpperCase()}</span>`;
}

function _batteryBar(pct) {
    if (pct === undefined || pct === null) return '<span class="mono" style="color:var(--text-dim)">--</span>';
    const clamped = Math.max(0, Math.min(100, pct));
    const color = clamped > 50 ? 'var(--green, #05ffa1)' : clamped > 20 ? 'var(--yellow, #fcee0a)' : 'var(--magenta, #ff2a6d)';
    return `<span class="fleet-dash-battery">
        <span class="fleet-dash-battery-fill" style="width:${clamped}%;background:${color}"></span>
        <span class="fleet-dash-battery-label mono">${clamped}%</span>
    </span>`;
}

// ============================================================
// Panel Definition
// ============================================================

export const FleetDashboardPanelDef = {
    id: 'fleet-dashboard',
    title: 'FLEET DASHBOARD',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 560, h: 440 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'fleet-dash-inner';
        el.innerHTML = `
            <div class="fleet-dash-summary" data-bind="summary">
                <div class="fleet-dash-stat">
                    <span class="fleet-dash-stat-value mono" data-bind="total">0</span>
                    <span class="fleet-dash-stat-label">TOTAL</span>
                </div>
                <div class="fleet-dash-stat">
                    <span class="fleet-dash-stat-value mono" style="color:var(--green, #05ffa1)" data-bind="online">0</span>
                    <span class="fleet-dash-stat-label">ONLINE</span>
                </div>
                <div class="fleet-dash-stat">
                    <span class="fleet-dash-stat-value mono" style="color:var(--yellow, #fcee0a)" data-bind="stale">0</span>
                    <span class="fleet-dash-stat-label">STALE</span>
                </div>
                <div class="fleet-dash-stat">
                    <span class="fleet-dash-stat-value mono" style="color:var(--magenta, #ff2a6d)" data-bind="offline">0</span>
                    <span class="fleet-dash-stat-label">OFFLINE</span>
                </div>
                <div class="fleet-dash-stat">
                    <span class="fleet-dash-stat-value mono" data-bind="avg-battery">--</span>
                    <span class="fleet-dash-stat-label">AVG BAT</span>
                </div>
            </div>
            <div class="fleet-dash-table-wrap" data-bind="table-wrap">
                <table class="fleet-dash-table">
                    <thead>
                        <tr>
                            <th>DEVICE</th>
                            <th>STATUS</th>
                            <th>BATTERY</th>
                            <th>UPTIME</th>
                            <th>BLE</th>
                            <th>WIFI</th>
                            <th>LAST SEEN</th>
                        </tr>
                    </thead>
                    <tbody data-bind="device-tbody">
                        <tr><td colspan="7" class="panel-empty">Loading fleet data...</td></tr>
                    </tbody>
                </table>
            </div>
            <div class="fleet-dash-footer">
                <span class="mono" style="color:var(--text-dim)" data-bind="refresh-ts">--</span>
                <button class="panel-action-btn" data-action="refresh">REFRESH</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const totalEl = bodyEl.querySelector('[data-bind="total"]');
        const onlineEl = bodyEl.querySelector('[data-bind="online"]');
        const staleEl = bodyEl.querySelector('[data-bind="stale"]');
        const offlineEl = bodyEl.querySelector('[data-bind="offline"]');
        const avgBatEl = bodyEl.querySelector('[data-bind="avg-battery"]');
        const tbodyEl = bodyEl.querySelector('[data-bind="device-tbody"]');
        const refreshTsEl = bodyEl.querySelector('[data-bind="refresh-ts"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        let refreshInterval = null;

        async function fetchAndRender() {
            try {
                const [devRes, sumRes] = await Promise.all([
                    fetch('/api/fleet/devices'),
                    fetch('/api/fleet/summary'),
                ]);

                if (!devRes.ok || !sumRes.ok) {
                    if (refreshTsEl) refreshTsEl.textContent = 'API error';
                    return;
                }

                const devData = await devRes.json();
                const sumData = await sumRes.json();

                // Update summary
                if (totalEl) totalEl.textContent = sumData.total ?? 0;
                if (onlineEl) onlineEl.textContent = sumData.online ?? 0;
                if (staleEl) staleEl.textContent = sumData.stale ?? 0;
                if (offlineEl) offlineEl.textContent = sumData.offline ?? 0;
                if (avgBatEl) {
                    avgBatEl.textContent = sumData.avg_battery !== null && sumData.avg_battery !== undefined
                        ? `${sumData.avg_battery}%`
                        : '--';
                }

                // Render device table
                const devices = devData.devices || [];
                if (tbodyEl) {
                    if (devices.length === 0) {
                        tbodyEl.innerHTML = '<tr><td colspan="7" class="panel-empty">No fleet devices detected</td></tr>';
                    } else {
                        // Sort: online first, then stale, then offline
                        const order = { online: 0, stale: 1, offline: 2 };
                        devices.sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9));

                        tbodyEl.innerHTML = devices.map(d => {
                            const did = _esc(d.device_id || d.name || '--');
                            return `<tr class="fleet-dash-row">
                                <td class="mono fleet-dash-device-cell" title="${did}">${did}</td>
                                <td>${_statusBadge(d.status)}</td>
                                <td>${_batteryBar(d.battery)}</td>
                                <td class="mono">${_formatUptime(d.uptime)}</td>
                                <td class="mono">${d.ble_count ?? 0}</td>
                                <td class="mono">${d.wifi_count ?? 0}</td>
                                <td class="mono">${_timeAgo(d.last_seen)}</td>
                            </tr>`;
                        }).join('');
                    }
                }

                if (refreshTsEl) {
                    refreshTsEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
                }
            } catch (err) {
                if (refreshTsEl) refreshTsEl.textContent = 'Fetch error';
            }
        }

        // Initial fetch
        fetchAndRender();

        // Auto-refresh every 10s
        refreshInterval = setInterval(fetchAndRender, 10000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Manual refresh button
        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchAndRender);
        }

        // Also refresh on fleet.heartbeat events
        const unsub = EventBus.on('fleet:heartbeat', () => {
            fetchAndRender();
        });
        if (unsub) panel._unsubs.push(unsub);
    },

    unmount(bodyEl) {
        // Cleanup handled by panel._unsubs
    },
};
