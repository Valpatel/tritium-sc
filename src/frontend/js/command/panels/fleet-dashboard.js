// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Fleet Dashboard Panel — aggregated fleet device monitoring
// Displays device list with online/offline/stale status badges,
// battery level bars, sighting counts, uptime. Auto-refreshes every 10s.

import { EventBus } from '/lib/events.js';
import { _esc, _timeAgo } from '/lib/utils.js';



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
                            <th>INDOOR POS</th>
                            <th>FIRST SEEN</th>
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
                const [devRes, sumRes, indoorRes] = await Promise.all([
                    fetch('/api/fleet/devices'),
                    fetch('/api/fleet/summary'),
                    fetch('/api/indoor/positions?limit=500').catch(() => null),
                ]);

                if (!devRes.ok || !sumRes.ok) {
                    if (refreshTsEl) refreshTsEl.textContent = 'API error';
                    return;
                }

                const devData = await devRes.json();
                const sumData = await sumRes.json();

                // Build indoor position lookup by target_id
                const indoorMap = {};
                if (indoorRes && indoorRes.ok) {
                    try {
                        const indoorData = await indoorRes.json();
                        for (const pos of (indoorData.positions || [])) {
                            if (pos.target_id) indoorMap[pos.target_id] = pos;
                        }
                    } catch (_) { /* indoor API optional */ }
                }

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
                        tbodyEl.innerHTML = '<tr><td colspan="9" class="panel-empty">No fleet devices detected</td></tr>';
                    } else {
                        // Sort: online first, then stale, then offline
                        const order = { online: 0, stale: 1, offline: 2 };
                        devices.sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9));

                        tbodyEl.innerHTML = devices.map(d => {
                            const did = _esc(d.device_id || d.name || '--');
                            // Highlight potentially offline (not seen in >1 hour)
                            const lastSeenTs = d.last_seen || 0;
                            const ageSec = lastSeenTs > 0 ? (Date.now() / 1000 - lastSeenTs) : Infinity;
                            const offlineWarn = ageSec > 3600;
                            const rowClass = offlineWarn ? 'fleet-dash-row fleet-dash-warn' : 'fleet-dash-row';

                            // Indoor position for this device
                            const ipos = indoorMap[d.device_id] || indoorMap['ble_' + (d.device_id || '')];
                            let indoorCell = '<span style="color:var(--text-dim)">--</span>';
                            if (ipos) {
                                const room = ipos.room_name || ipos.room_id || '';
                                const conf = Math.round((ipos.confidence || 0) * 100);
                                const unc = ipos.uncertainty_m != null ? `\u00b1${ipos.uncertainty_m.toFixed(1)}m` : '';
                                const mColor = ipos.method === 'fused' ? '#05ffa1' : ipos.method === 'fingerprint' ? '#00f0ff' : '#ff2a6d';
                                indoorCell = room
                                    ? `<span style="color:${mColor}" title="${conf}% ${unc}">${_esc(room)}</span>`
                                    : `<span style="color:${mColor}" title="${conf}% ${unc}">${conf}% ${unc}</span>`;
                            }

                            return `<tr class="${rowClass}">
                                <td class="mono fleet-dash-device-cell" title="${did}">${did}</td>
                                <td>${_statusBadge(d.status)}</td>
                                <td>${_batteryBar(d.battery)}</td>
                                <td class="mono">${_formatUptime(d.uptime)}</td>
                                <td class="mono">${d.ble_count ?? 0}</td>
                                <td class="mono">${d.wifi_count ?? 0}</td>
                                <td class="mono" style="font-size:0.4rem">${indoorCell}</td>
                                <td class="mono">${_timeAgo(d.first_seen)}</td>
                                <td class="mono">${_timeAgo(d.last_seen)}${offlineWarn ? ' <span style="color:var(--magenta)">[!]</span>' : ''}</td>
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
