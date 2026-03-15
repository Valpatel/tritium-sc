// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Security Audit Trail Panel — shows recent security events: failed auth,
// rate limit hits, CORS rejections, CSP violations, server errors.

import { _esc, _timeAgo } from '../panel-utils.js';


function _severityBadge(severity) {
    const colors = {
        critical: '#ff2a6d',
        error: '#ff4444',
        warning: '#fcee0a',
        info: '#00f0ff',
    };
    const color = colors[severity] || '#888';
    const label = (severity || 'unknown').toUpperCase();
    return `<span style="color:${color};border:1px solid ${color};padding:1px 4px;border-radius:2px;font-size:9px">${label}</span>`;
}

function _eventTypeBadge(eventType) {
    const map = {
        auth_failure: { label: 'AUTH FAIL', color: '#ff2a6d' },
        rate_limit: { label: 'RATE LIMIT', color: '#ff8800' },
        forbidden: { label: 'FORBIDDEN', color: '#fcee0a' },
        server_error: { label: 'SERVER ERR', color: '#ff4444' },
        other_warning: { label: 'WARNING', color: '#888' },
    };
    const info = map[eventType] || { label: eventType || '?', color: '#555' };
    return `<span style="color:${info.color};font-size:9px;font-weight:bold">${info.label}</span>`;
}

function _formatTs(epoch) {
    if (!epoch) return '--';
    const d = new Date(epoch * 1000);
    return d.toLocaleTimeString();
}


export const SecurityAuditPanelDef = {
    id: 'security-audit',
    title: 'SECURITY AUDIT TRAIL',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 680, h: 500 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'security-audit-inner';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%';
        el.innerHTML = `
            <div style="display:flex;gap:12px;padding:6px 8px;border-bottom:1px solid rgba(0,240,255,0.15);flex-wrap:wrap;align-items:center">
                <div style="text-align:center">
                    <span class="mono" data-bind="total" style="color:#b0b0c0">0</span>
                    <div style="font-size:9px;color:#555">TOTAL</div>
                </div>
                <div style="text-align:center">
                    <span class="mono" data-bind="auth-fail" style="color:#ff2a6d">0</span>
                    <div style="font-size:9px;color:#555">AUTH FAIL</div>
                </div>
                <div style="text-align:center">
                    <span class="mono" data-bind="rate-limit" style="color:#ff8800">0</span>
                    <div style="font-size:9px;color:#555">RATE LIM</div>
                </div>
                <div style="text-align:center">
                    <span class="mono" data-bind="forbidden" style="color:#fcee0a">0</span>
                    <div style="font-size:9px;color:#555">FORBIDDEN</div>
                </div>
                <div style="text-align:center">
                    <span class="mono" data-bind="server-err" style="color:#ff4444">0</span>
                    <div style="font-size:9px;color:#555">SRV ERR</div>
                </div>
                <div style="text-align:center">
                    <span class="mono" data-bind="recent-hour" style="color:#05ffa1">0</span>
                    <div style="font-size:9px;color:#555">LAST HR</div>
                </div>
                <div style="flex:1"></div>
                <select data-bind="filter" style="background:#1a1a2e;color:#b0b0c0;border:1px solid rgba(0,240,255,0.2);padding:2px 6px;font-size:10px;border-radius:2px">
                    <option value="">ALL EVENTS</option>
                    <option value="auth_failure">AUTH FAILURES</option>
                    <option value="rate_limit">RATE LIMITS</option>
                    <option value="forbidden">FORBIDDEN</option>
                </select>
            </div>
            <div style="flex:1;overflow-y:auto;min-height:0">
                <table style="width:100%;border-collapse:collapse;font-size:11px">
                    <thead>
                        <tr style="color:#555;border-bottom:1px solid rgba(0,240,255,0.1)">
                            <th style="text-align:left;padding:4px 6px">TIME</th>
                            <th style="text-align:left;padding:4px 6px">TYPE</th>
                            <th style="text-align:left;padding:4px 6px">SEVERITY</th>
                            <th style="text-align:left;padding:4px 6px">SOURCE IP</th>
                            <th style="text-align:left;padding:4px 6px">ACTION</th>
                            <th style="text-align:left;padding:4px 6px">DETAIL</th>
                        </tr>
                    </thead>
                    <tbody data-bind="event-tbody">
                        <tr><td colspan="6" style="padding:12px;color:#555;text-align:center">Loading security events...</td></tr>
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
        const authFailEl = bodyEl.querySelector('[data-bind="auth-fail"]');
        const rateLimitEl = bodyEl.querySelector('[data-bind="rate-limit"]');
        const forbiddenEl = bodyEl.querySelector('[data-bind="forbidden"]');
        const serverErrEl = bodyEl.querySelector('[data-bind="server-err"]');
        const recentHourEl = bodyEl.querySelector('[data-bind="recent-hour"]');
        const filterEl = bodyEl.querySelector('[data-bind="filter"]');
        const tbodyEl = bodyEl.querySelector('[data-bind="event-tbody"]');
        const refreshTsEl = bodyEl.querySelector('[data-bind="refresh-ts"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        let refreshInterval = null;

        async function fetchAndRender() {
            try {
                const filterVal = filterEl ? filterEl.value : '';
                const trailUrl = filterVal
                    ? `/api/security/audit-trail?event_type=${filterVal}&limit=200`
                    : '/api/security/audit-trail?limit=200';

                const [trailRes, statsRes] = await Promise.all([
                    fetch(trailUrl),
                    fetch('/api/security/audit-stats'),
                ]);

                if (!trailRes.ok || !statsRes.ok) {
                    if (refreshTsEl) refreshTsEl.textContent = 'API error';
                    return;
                }

                const trailData = await trailRes.json();
                const statsData = await statsRes.json();

                // Update stats
                if (totalEl) totalEl.textContent = statsData.total_security_events ?? 0;
                const byType = statsData.by_type || {};
                if (authFailEl) authFailEl.textContent = byType.auth_failure ?? 0;
                if (rateLimitEl) rateLimitEl.textContent = byType.rate_limit ?? 0;
                if (forbiddenEl) forbiddenEl.textContent = byType.forbidden ?? 0;
                if (serverErrEl) serverErrEl.textContent = byType.server_error ?? 0;
                if (recentHourEl) recentHourEl.textContent = statsData.recent_hour ?? 0;

                // Render event table
                const events = trailData.events || [];
                if (tbodyEl) {
                    if (events.length === 0) {
                        tbodyEl.innerHTML = '<tr><td colspan="6" style="padding:12px;color:#05ffa1;text-align:center">No security events — system is clean</td></tr>';
                    } else {
                        tbodyEl.innerHTML = events.map(e => {
                            const ts = _formatTs(e.timestamp);
                            const ip = _esc(e.ip_address || '--');
                            const action = _esc((e.action || '--').substring(0, 40));
                            const detail = _esc((e.detail || '--').substring(0, 50));
                            return `<tr style="border-bottom:1px solid rgba(255,255,255,0.03)">
                                <td class="mono" style="padding:3px 6px;color:#888">${ts}</td>
                                <td style="padding:3px 6px">${_eventTypeBadge(e.event_type)}</td>
                                <td style="padding:3px 6px">${_severityBadge(e.severity)}</td>
                                <td class="mono" style="padding:3px 6px;color:#b0b0c0">${ip}</td>
                                <td class="mono" style="padding:3px 6px;color:#b0b0c0">${action}</td>
                                <td style="padding:3px 6px;color:#888">${detail}</td>
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

        // Manual refresh
        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchAndRender);
        }

        // Filter change triggers refresh
        if (filterEl) {
            filterEl.addEventListener('change', fetchAndRender);
        }
    },

    unmount(bodyEl) {
        // Cleanup handled by panel._unsubs
    },
};
