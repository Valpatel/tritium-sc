// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Fleet Command History Panel — audit log of all commands sent to edge devices.
// Shows command, target device/group, timestamp, and result (acked/failed/timeout).

import { EventBus } from '/lib/events.js';
import { _esc, _timeAgo } from '/lib/utils.js';


function _resultBadge(result) {
    const colors = {
        acknowledged: 'var(--green, #05ffa1)',
        pending: 'var(--yellow, #fcee0a)',
        failed: 'var(--magenta, #ff2a6d)',
        timed_out: '#ff8800',
    };
    const color = colors[result] || 'var(--text-dim, #888)';
    const label = (result || 'unknown').toUpperCase().replace('_', ' ');
    return `<span style="color:${color};border:1px solid ${color};padding:1px 4px;border-radius:2px;font-size:10px">${label}</span>`;
}

function _formatTimestamp(epoch) {
    if (!epoch) return '--';
    const d = new Date(epoch * 1000);
    return d.toLocaleTimeString();
}


export const CommandHistoryPanelDef = {
    id: 'command-history',
    title: 'COMMAND HISTORY',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 620, h: 440 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'cmd-history-inner';
        el.innerHTML = `
            <div class="cmd-history-stats" style="display:flex;gap:12px;padding:6px 8px;border-bottom:1px solid rgba(0,240,255,0.15)">
                <div style="text-align:center">
                    <span class="mono" data-bind="total" style="color:#b0b0c0">0</span>
                    <div style="font-size:9px;color:#555">TOTAL</div>
                </div>
                <div style="text-align:center">
                    <span class="mono" data-bind="acked" style="color:var(--green,#05ffa1)">0</span>
                    <div style="font-size:9px;color:#555">ACKED</div>
                </div>
                <div style="text-align:center">
                    <span class="mono" data-bind="pending" style="color:var(--yellow,#fcee0a)">0</span>
                    <div style="font-size:9px;color:#555">PENDING</div>
                </div>
                <div style="text-align:center">
                    <span class="mono" data-bind="failed" style="color:var(--magenta,#ff2a6d)">0</span>
                    <div style="font-size:9px;color:#555">FAILED</div>
                </div>
                <div style="text-align:center">
                    <span class="mono" data-bind="timeout" style="color:#ff8800">0</span>
                    <div style="font-size:9px;color:#555">TIMEOUT</div>
                </div>
            </div>
            <div style="flex:1;overflow-y:auto;min-height:0">
                <table style="width:100%;border-collapse:collapse;font-size:11px">
                    <thead>
                        <tr style="color:#555;border-bottom:1px solid rgba(0,240,255,0.1)">
                            <th style="text-align:left;padding:4px 6px">COMMAND</th>
                            <th style="text-align:left;padding:4px 6px">DEVICE</th>
                            <th style="text-align:left;padding:4px 6px">SENT</th>
                            <th style="text-align:left;padding:4px 6px">RESULT</th>
                            <th style="text-align:left;padding:4px 6px">LATENCY</th>
                        </tr>
                    </thead>
                    <tbody data-bind="cmd-tbody">
                        <tr><td colspan="5" style="padding:12px;color:#555;text-align:center">Loading command history...</td></tr>
                    </tbody>
                </table>
            </div>
            <div style="padding:4px 8px;border-top:1px solid rgba(0,240,255,0.1);display:flex;justify-content:space-between;align-items:center">
                <span class="mono" style="color:#555;font-size:10px" data-bind="refresh-ts">--</span>
                <button class="panel-action-btn" data-action="refresh">REFRESH</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const totalEl = bodyEl.querySelector('[data-bind="total"]');
        const ackedEl = bodyEl.querySelector('[data-bind="acked"]');
        const pendingEl = bodyEl.querySelector('[data-bind="pending"]');
        const failedEl = bodyEl.querySelector('[data-bind="failed"]');
        const timeoutEl = bodyEl.querySelector('[data-bind="timeout"]');
        const tbodyEl = bodyEl.querySelector('[data-bind="cmd-tbody"]');
        const refreshTsEl = bodyEl.querySelector('[data-bind="refresh-ts"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        let refreshInterval = null;

        async function fetchAndRender() {
            try {
                const [histRes, statsRes] = await Promise.all([
                    fetch('/api/fleet/commands/history?limit=100'),
                    fetch('/api/fleet/commands/stats'),
                ]);

                if (!histRes.ok || !statsRes.ok) {
                    if (refreshTsEl) refreshTsEl.textContent = 'API error';
                    return;
                }

                const histData = await histRes.json();
                const statsData = await statsRes.json();

                // Update stats
                if (totalEl) totalEl.textContent = statsData.total_sent ?? 0;
                if (ackedEl) ackedEl.textContent = statsData.acknowledged ?? 0;
                if (pendingEl) pendingEl.textContent = statsData.pending ?? 0;
                if (failedEl) failedEl.textContent = statsData.failed ?? 0;
                if (timeoutEl) timeoutEl.textContent = statsData.timed_out ?? 0;

                // Render command table
                const commands = histData.commands || [];
                if (tbodyEl) {
                    if (commands.length === 0) {
                        tbodyEl.innerHTML = '<tr><td colspan="5" style="padding:12px;color:#555;text-align:center">No commands sent yet</td></tr>';
                    } else {
                        tbodyEl.innerHTML = commands.map(c => {
                            const latency = (c.acked_at && c.sent_at)
                                ? `${((c.acked_at - c.sent_at) * 1000).toFixed(0)}ms`
                                : '--';
                            const target = c.device_group
                                ? `<span style="color:#00f0ff">[${_esc(c.device_group)}]</span>`
                                : _esc(c.device_id || '--');
                            return `<tr style="border-bottom:1px solid rgba(255,255,255,0.03)">
                                <td class="mono" style="padding:3px 6px;color:#b0b0c0">${_esc(c.command || '--')}</td>
                                <td class="mono" style="padding:3px 6px">${target}</td>
                                <td class="mono" style="padding:3px 6px;color:#888">${_formatTimestamp(c.sent_at)}</td>
                                <td style="padding:3px 6px">${_resultBadge(c.result)}</td>
                                <td class="mono" style="padding:3px 6px;color:#888">${latency}</td>
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

        // Auto-refresh every 5s
        refreshInterval = setInterval(fetchAndRender, 5000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Manual refresh
        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchAndRender);
        }
    },

    unmount(bodyEl) {
        // Cleanup handled by panel._unsubs
    },
};
