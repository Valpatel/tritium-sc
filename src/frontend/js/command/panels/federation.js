// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Federation Site Status Panel — shows connected federation sites with
// sync status, shared target count, last sync timestamp, and connection health.

import { EventBus } from '../events.js';
import { _esc, _timeAgo } from '../panel-utils.js';

const REFRESH_INTERVAL_MS = 10000; // Refresh every 10s

function _connectionBadge(state) {
    const colors = {
        connected: 'var(--green, #05ffa1)',
        connecting: 'var(--yellow, #fcee0a)',
        disconnected: 'var(--magenta, #ff2a6d)',
        error: 'var(--magenta, #ff2a6d)',
    };
    const color = colors[state] || 'var(--text-dim, #888)';
    return `<span class="fed-status-badge" style="color:${color};border-color:${color}">${(state || 'unknown').toUpperCase()}</span>`;
}

function _healthDot(state) {
    const colors = {
        connected: '#05ffa1',
        connecting: '#fcee0a',
        disconnected: '#ff2a6d',
        error: '#ff2a6d',
    };
    const color = colors[state] || '#888';
    const pulse = state === 'connected' ? 'fed-pulse' : '';
    return `<span class="fed-health-dot ${pulse}" style="background:${color}"></span>`;
}

function _roleBadge(role) {
    const colors = {
        peer: '#00f0ff',
        upstream: '#05ffa1',
        downstream: '#fcee0a',
        hub: '#ff2a6d',
    };
    const color = colors[role] || '#888';
    return `<span class="fed-role-badge" style="color:${color};border-color:${color}">${(role || 'peer').toUpperCase()}</span>`;
}

function _sharePolicyLabel(policy) {
    const labels = {
        targets_only: 'Targets Only',
        full_sync: 'Full Sync',
        intelligence: 'Intel Packages',
        alerts_only: 'Alerts Only',
    };
    return labels[policy] || policy || 'Unknown';
}

// ============================================================
// Panel Definition
// ============================================================

export const FederationPanelDef = {
    id: 'federation',
    title: 'FEDERATION SITES',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 520, h: 480 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'fed-panel-inner';
        el.innerHTML = `
            <div class="fed-summary" data-bind="summary">
                <div class="fed-stat">
                    <span class="fed-stat-value mono" data-bind="total">0</span>
                    <span class="fed-stat-label">SITES</span>
                </div>
                <div class="fed-stat">
                    <span class="fed-stat-value mono" data-bind="connected" style="color:var(--green, #05ffa1)">0</span>
                    <span class="fed-stat-label">CONNECTED</span>
                </div>
                <div class="fed-stat">
                    <span class="fed-stat-value mono" data-bind="shared" style="color:var(--cyan, #00f0ff)">0</span>
                    <span class="fed-stat-label">SHARED TARGETS</span>
                </div>
                <div class="fed-stat">
                    <span class="fed-stat-value mono" data-bind="packages" style="color:var(--yellow, #fcee0a)">0</span>
                    <span class="fed-stat-label">INTEL PKGS</span>
                </div>
            </div>

            <div class="fed-actions">
                <button class="fed-btn fed-btn-add" data-action="add-site">+ ADD SITE</button>
                <button class="fed-btn fed-btn-refresh" data-action="refresh">REFRESH</button>
            </div>

            <div class="fed-site-list" data-bind="site-list">
                <div class="fed-empty mono">No federation sites configured</div>
            </div>

            <div class="fed-add-form" data-bind="add-form" style="display:none">
                <div class="fed-form-title mono">ADD FEDERATION SITE</div>
                <div class="fed-form-row">
                    <label class="fed-form-label mono">NAME</label>
                    <input class="fed-form-input" data-field="name" placeholder="Remote Site Alpha" />
                </div>
                <div class="fed-form-row">
                    <label class="fed-form-label mono">MQTT HOST</label>
                    <input class="fed-form-input" data-field="mqtt_host" placeholder="192.168.1.100" />
                </div>
                <div class="fed-form-row">
                    <label class="fed-form-label mono">MQTT PORT</label>
                    <input class="fed-form-input" data-field="mqtt_port" type="number" value="1883" />
                </div>
                <div class="fed-form-row">
                    <label class="fed-form-label mono">ROLE</label>
                    <select class="fed-form-input" data-field="role">
                        <option value="peer">Peer</option>
                        <option value="upstream">Upstream</option>
                        <option value="downstream">Downstream</option>
                        <option value="hub">Hub</option>
                    </select>
                </div>
                <div class="fed-form-row">
                    <label class="fed-form-label mono">SHARE POLICY</label>
                    <select class="fed-form-input" data-field="share_policy">
                        <option value="targets_only">Targets Only</option>
                        <option value="full_sync">Full Sync</option>
                        <option value="intelligence">Intel Packages</option>
                        <option value="alerts_only">Alerts Only</option>
                    </select>
                </div>
                <div class="fed-form-actions">
                    <button class="fed-btn fed-btn-save" data-action="save-site">SAVE</button>
                    <button class="fed-btn fed-btn-cancel" data-action="cancel-add">CANCEL</button>
                </div>
            </div>
        `;

        // --- State ---
        let _refreshTimer = null;
        const _siteList = el.querySelector('[data-bind="site-list"]');
        const _addForm = el.querySelector('[data-bind="add-form"]');
        const _totalEl = el.querySelector('[data-bind="total"]');
        const _connectedEl = el.querySelector('[data-bind="connected"]');
        const _sharedEl = el.querySelector('[data-bind="shared"]');
        const _packagesEl = el.querySelector('[data-bind="packages"]');

        // --- Fetch data ---
        async function _fetchAndRender() {
            try {
                const [sitesRes, statsRes, pkgsRes] = await Promise.all([
                    fetch('/api/federation/sites').then(r => r.json()).catch(() => ({ sites: [] })),
                    fetch('/api/federation/stats').then(r => r.json()).catch(() => ({})),
                    fetch('/api/federation/intel-packages').then(r => r.json()).catch(() => ({ count: 0 })),
                ]);

                const sites = sitesRes.sites || [];
                const stats = statsRes || {};

                // Update summary
                _totalEl.textContent = String(stats.total_sites || sites.length);
                _connectedEl.textContent = String(stats.connected_sites || 0);
                _sharedEl.textContent = String(stats.shared_targets || 0);
                _packagesEl.textContent = String(pkgsRes.count || 0);

                // Render site list
                if (sites.length === 0) {
                    _siteList.innerHTML = '<div class="fed-empty mono">No federation sites configured</div>';
                    return;
                }

                let html = '';
                for (const site of sites) {
                    const conn = site.connection || {};
                    const state = conn.state || 'disconnected';
                    const lastHb = conn.last_heartbeat;
                    const lastHbStr = lastHb ? _timeAgo(lastHb * 1000) : 'never';
                    const sharedCount = conn.shared_target_count || 0;
                    const lastSync = conn.last_sync || site.last_sync;
                    const lastSyncStr = lastSync ? _timeAgo(lastSync * 1000) : 'never';

                    html += `
                        <div class="fed-site-card" data-site-id="${_esc(site.site_id)}">
                            <div class="fed-site-header">
                                ${_healthDot(state)}
                                <span class="fed-site-name mono">${_esc(site.name || 'Unknown Site')}</span>
                                ${_roleBadge(site.role)}
                                ${_connectionBadge(state)}
                            </div>
                            <div class="fed-site-details">
                                <div class="fed-detail-row">
                                    <span class="fed-detail-label mono">MQTT</span>
                                    <span class="fed-detail-value mono">${_esc(site.mqtt_host || '--')}:${site.mqtt_port || 1883}</span>
                                </div>
                                <div class="fed-detail-row">
                                    <span class="fed-detail-label mono">POLICY</span>
                                    <span class="fed-detail-value mono">${_sharePolicyLabel(site.share_policy)}</span>
                                </div>
                                <div class="fed-detail-row">
                                    <span class="fed-detail-label mono">SHARED</span>
                                    <span class="fed-detail-value mono" style="color:var(--cyan, #00f0ff)">${sharedCount} targets</span>
                                </div>
                                <div class="fed-detail-row">
                                    <span class="fed-detail-label mono">LAST SYNC</span>
                                    <span class="fed-detail-value mono">${lastSyncStr}</span>
                                </div>
                                <div class="fed-detail-row">
                                    <span class="fed-detail-label mono">HEARTBEAT</span>
                                    <span class="fed-detail-value mono">${lastHbStr}</span>
                                </div>
                                ${site.description ? `<div class="fed-detail-row"><span class="fed-detail-label mono">DESC</span><span class="fed-detail-value mono">${_esc(site.description)}</span></div>` : ''}
                            </div>
                            <div class="fed-site-actions">
                                <button class="fed-btn-sm" data-action="remove-site" data-site-id="${_esc(site.site_id)}">REMOVE</button>
                                <span class="fed-site-id mono" style="color:var(--text-dim, #666)">${_esc(site.site_id.slice(0, 8))}...</span>
                            </div>
                        </div>
                    `;
                }

                _siteList.innerHTML = html;

            } catch (err) {
                console.error('[federation] fetch error:', err);
                _siteList.innerHTML = '<div class="fed-empty mono" style="color:var(--magenta)">Error fetching federation data</div>';
            }
        }

        // --- Event handlers ---
        el.addEventListener('click', async (e) => {
            const action = e.target.dataset.action;
            if (!action) return;

            if (action === 'add-site') {
                _addForm.style.display = '';
            } else if (action === 'cancel-add') {
                _addForm.style.display = 'none';
            } else if (action === 'refresh') {
                _fetchAndRender();
            } else if (action === 'save-site') {
                const name = _addForm.querySelector('[data-field="name"]').value;
                const mqttHost = _addForm.querySelector('[data-field="mqtt_host"]').value;
                const mqttPort = parseInt(_addForm.querySelector('[data-field="mqtt_port"]').value || '1883', 10);
                const role = _addForm.querySelector('[data-field="role"]').value;
                const sharePolicy = _addForm.querySelector('[data-field="share_policy"]').value;

                if (!name || !mqttHost) {
                    EventBus.emit('toast', { message: 'Name and MQTT host are required', type: 'error' });
                    return;
                }

                try {
                    const resp = await fetch('/api/federation/sites', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name,
                            mqtt_host: mqttHost,
                            mqtt_port: mqttPort,
                            role,
                            share_policy: sharePolicy,
                        }),
                    });
                    if (resp.ok) {
                        _addForm.style.display = 'none';
                        // Clear form
                        _addForm.querySelector('[data-field="name"]').value = '';
                        _addForm.querySelector('[data-field="mqtt_host"]').value = '';
                        EventBus.emit('toast', { message: 'Federation site added', type: 'success' });
                        _fetchAndRender();
                    } else {
                        const err = await resp.json();
                        EventBus.emit('toast', { message: err.detail || 'Failed to add site', type: 'error' });
                    }
                } catch (err) {
                    EventBus.emit('toast', { message: 'Network error adding site', type: 'error' });
                }
            } else if (action === 'remove-site') {
                const siteId = e.target.dataset.siteId;
                if (!siteId) return;
                if (!confirm('Remove this federation site?')) return;
                try {
                    const resp = await fetch(`/api/federation/sites/${siteId}`, { method: 'DELETE' });
                    if (resp.ok) {
                        EventBus.emit('toast', { message: 'Site removed', type: 'info' });
                        _fetchAndRender();
                    }
                } catch (err) {
                    EventBus.emit('toast', { message: 'Failed to remove site', type: 'error' });
                }
            }
        });

        // --- Lifecycle ---
        _fetchAndRender();
        _refreshTimer = setInterval(_fetchAndRender, REFRESH_INTERVAL_MS);

        // Store cleanup ref
        panel._fedCleanup = () => {
            if (_refreshTimer) clearInterval(_refreshTimer);
        };

        return el;
    },

    destroy(panel) {
        if (panel._fedCleanup) panel._fedCleanup();
    },
};
