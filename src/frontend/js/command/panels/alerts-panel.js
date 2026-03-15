// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Unified Alerts Panel — aggregates all alert sources into one timeline.
// Sources: geofence, BLE, LPR, threat feeds, federation, acoustic, sensor health.
// Backend API: /api/alerts/unified

import { EventBus } from '../events.js';
import { _esc, _timeAgo } from '../panel-utils.js';

const REFRESH_INTERVAL = 15000; // 15s
const MAX_ALERTS = 200;

// Severity color mapping (cyberpunk palette)
const SEVERITY_COLORS = {
    critical: '#ff2a6d', // magenta
    high: '#ff4444',     // red
    medium: '#fcee0a',   // yellow
    low: '#00f0ff',      // cyan
};

const SEVERITY_LABELS = {
    critical: 'CRIT',
    high: 'HIGH',
    medium: 'MED',
    low: 'LOW',
};

const SOURCE_LABELS = {
    geofence: 'GEOFENCE',
    ble: 'BLE',
    lpr: 'LPR',
    threat: 'THREAT',
    federation: 'FEDERATION',
    acoustic: 'ACOUSTIC',
    sensor_health: 'SENSOR',
    notification: 'SYSTEM',
    escalation: 'ESCALATION',
};

const SOURCE_ICONS = {
    geofence: '\u25a0',      // filled square
    ble: '\u00b7',           // middle dot
    lpr: '\u2316',           // position indicator
    threat: '\u26a0',        // warning
    federation: '\u2731',    // heavy asterisk
    acoustic: '\u266b',      // music note (sound)
    sensor_health: '\u2665', // heart
    notification: '\u2709',  // envelope
    escalation: '\u2191',    // up arrow
};

function _severityBadge(severity) {
    const color = SEVERITY_COLORS[severity] || '#888';
    const label = SEVERITY_LABELS[severity] || severity.toUpperCase();
    return `<span class="ua-sev-badge" style="background:${color};color:#0a0a0f;font-size:0.38rem;padding:1px 4px;border-radius:2px;font-weight:bold">${label}</span>`;
}

function _sourceBadge(source) {
    const label = SOURCE_LABELS[source] || source.toUpperCase();
    const icon = SOURCE_ICONS[source] || '?';
    return `<span class="ua-src-badge mono" style="font-size:0.38rem;color:var(--text-dim);margin-left:4px">${icon} ${label}</span>`;
}

// Sound notification for critical alerts
let _criticalSoundEnabled = false;
let _lastSoundTs = 0;
function _playCriticalSound() {
    if (!_criticalSoundEnabled) return;
    const now = Date.now();
    if (now - _lastSoundTs < 5000) return; // throttle: max once per 5s
    _lastSoundTs = now;
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.setValueAtTime(880, ctx.currentTime);
        gain.gain.setValueAtTime(0.15, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.3);
    } catch (_) { /* audio not available */ }
}

export const UnifiedAlertsPanelDef = {
    id: 'unified-alerts',
    title: 'UNIFIED ALERTS',
    defaultPosition: { x: null, y: 44 },
    defaultSize: { w: 380, h: 480 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'ua-panel-inner';
        el.innerHTML = `
            <div class="ua-header">
                <div class="ua-counts" data-bind="counts">
                    <span class="ua-count-badge ua-count-critical" data-bind="count-critical" title="Critical">0</span>
                    <span class="ua-count-badge ua-count-high" data-bind="count-high" title="High">0</span>
                    <span class="ua-count-badge ua-count-medium" data-bind="count-medium" title="Medium">0</span>
                    <span class="ua-count-badge ua-count-low" data-bind="count-low" title="Low">0</span>
                    <span class="ua-count-total mono" data-bind="count-total" style="color:var(--text-dim);font-size:0.42rem;margin-left:4px">0 total</span>
                </div>
                <div class="ua-controls">
                    <button class="panel-action-btn" data-action="sound-toggle" title="Toggle critical alert sound" style="font-size:0.42rem;padding:2px 4px">\u266b OFF</button>
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem;padding:2px 6px">REFRESH</button>
                </div>
            </div>
            <div class="ua-filters" data-bind="filters">
                <div class="ua-filter-row">
                    <select class="ua-filter-select" data-filter="source" title="Filter by source">
                        <option value="">ALL SOURCES</option>
                        <option value="geofence">Geofence</option>
                        <option value="ble">BLE</option>
                        <option value="lpr">LPR</option>
                        <option value="threat">Threat Feed</option>
                        <option value="federation">Federation</option>
                        <option value="acoustic">Acoustic</option>
                        <option value="sensor_health">Sensor Health</option>
                        <option value="escalation">Escalation</option>
                    </select>
                    <select class="ua-filter-select" data-filter="severity" title="Filter by severity">
                        <option value="">ALL SEVERITY</option>
                        <option value="critical">Critical</option>
                        <option value="high">High</option>
                        <option value="medium">Medium</option>
                        <option value="low">Low</option>
                    </select>
                    <select class="ua-filter-select" data-filter="time" title="Filter by time range">
                        <option value="0">ALL TIME</option>
                        <option value="300">Last 5 min</option>
                        <option value="900">Last 15 min</option>
                        <option value="3600">Last 1 hour</option>
                        <option value="86400">Last 24 hours</option>
                    </select>
                </div>
            </div>
            <ul class="panel-list ua-feed" data-bind="feed" role="log" aria-label="Unified alert feed" aria-live="polite">
                <li class="panel-empty">Loading alerts...</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // Position at top-right if no saved layout
        if (panel.def.defaultPosition.x === null) {
            const cw = panel.manager.container.clientWidth || 1200;
            panel.x = cw - panel.w - 8;
            panel._applyTransform();
        }

        const feedEl = bodyEl.querySelector('[data-bind="feed"]');
        const countCritical = bodyEl.querySelector('[data-bind="count-critical"]');
        const countHigh = bodyEl.querySelector('[data-bind="count-high"]');
        const countMedium = bodyEl.querySelector('[data-bind="count-medium"]');
        const countLow = bodyEl.querySelector('[data-bind="count-low"]');
        const countTotal = bodyEl.querySelector('[data-bind="count-total"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const soundBtn = bodyEl.querySelector('[data-action="sound-toggle"]');
        const sourceFilter = bodyEl.querySelector('[data-filter="source"]');
        const severityFilter = bodyEl.querySelector('[data-filter="severity"]');
        const timeFilter = bodyEl.querySelector('[data-filter="time"]');

        let alerts = [];
        let timer = null;
        let previousCriticalCount = 0;

        // Sound toggle
        if (soundBtn) {
            soundBtn.addEventListener('click', () => {
                _criticalSoundEnabled = !_criticalSoundEnabled;
                soundBtn.textContent = _criticalSoundEnabled ? '\u266b ON' : '\u266b OFF';
                soundBtn.classList.toggle('panel-action-btn-primary', _criticalSoundEnabled);
            });
        }

        function getFilterParams() {
            const params = new URLSearchParams();
            params.set('limit', String(MAX_ALERTS));

            const src = sourceFilter ? sourceFilter.value : '';
            const sev = severityFilter ? severityFilter.value : '';
            const timeSecs = timeFilter ? parseInt(timeFilter.value, 10) : 0;

            if (src) params.set('source', src);
            if (sev) params.set('severity', sev);
            if (timeSecs > 0) {
                const since = Math.floor(Date.now() / 1000) - timeSecs;
                params.set('since', String(since));
            }
            return params.toString();
        }

        async function fetchAlerts() {
            try {
                const qs = getFilterParams();
                const resp = await fetch(`/api/alerts/unified?${qs}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                alerts = await resp.json();
                if (!Array.isArray(alerts)) alerts = [];

                // Count by severity
                const counts = { critical: 0, high: 0, medium: 0, low: 0 };
                for (const a of alerts) {
                    const sev = a.severity || 'low';
                    if (counts[sev] !== undefined) counts[sev]++;
                }

                if (countCritical) countCritical.textContent = counts.critical;
                if (countHigh) countHigh.textContent = counts.high;
                if (countMedium) countMedium.textContent = counts.medium;
                if (countLow) countLow.textContent = counts.low;
                if (countTotal) countTotal.textContent = `${alerts.length} total`;

                // Update panel title badge
                const totalAlerts = alerts.length;
                if (panel && panel.el) {
                    const titleEl = panel.el.querySelector('.panel-title');
                    if (titleEl) {
                        let badge = titleEl.querySelector('.ua-title-badge');
                        if (totalAlerts > 0) {
                            if (!badge) {
                                badge = document.createElement('span');
                                badge.className = 'ua-title-badge';
                                badge.style.cssText = 'background:#ff2a6d;color:#0a0a0f;font-size:0.38rem;padding:1px 4px;border-radius:6px;margin-left:6px;font-weight:bold';
                                titleEl.appendChild(badge);
                            }
                            badge.textContent = totalAlerts > 99 ? '99+' : totalAlerts;
                        } else if (badge) {
                            badge.remove();
                        }
                    }
                }

                // Sound notification for new critical alerts
                if (counts.critical > previousCriticalCount) {
                    _playCriticalSound();
                }
                previousCriticalCount = counts.critical;

                render();
            } catch (e) {
                console.error('[UnifiedAlerts] fetch failed:', e);
                if (feedEl) feedEl.innerHTML = '<li class="panel-empty">Failed to load alerts</li>';
            }
        }

        function render() {
            if (!feedEl) return;
            if (alerts.length === 0) {
                feedEl.innerHTML = '<li class="panel-empty">No alerts matching filters</li>';
                return;
            }

            feedEl.innerHTML = alerts.slice(0, MAX_ALERTS).map(a => {
                const time = a.timestamp
                    ? new Date(a.timestamp * 1000).toLocaleTimeString().substring(0, 8)
                    : '';
                const sevColor = SEVERITY_COLORS[a.severity] || '#888';
                const clickData = a.entity_id ? `data-entity="${_esc(a.entity_id)}"` : '';
                const zoneData = a.zone_id ? `data-zone="${_esc(a.zone_id)}"` : '';

                return `<li class="panel-list-item ua-alert-item" style="cursor:pointer;border-left:2px solid ${sevColor};padding-left:6px" ${clickData} ${zoneData} title="${_esc(a.message)}">
                    <div style="display:flex;align-items:center;gap:4px;width:100%">
                        <span style="display:flex;flex-direction:column;align-items:center;min-width:36px">
                            ${_severityBadge(a.severity)}
                        </span>
                        <span style="flex:1;min-width:0;display:flex;flex-direction:column;gap:1px">
                            <span style="font-size:0.5rem;color:var(--text-main);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(a.title || '')}</span>
                            <span style="font-size:0.42rem;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(a.message || '')}</span>
                        </span>
                        <span style="display:flex;flex-direction:column;align-items:flex-end;min-width:50px">
                            ${_sourceBadge(a.source)}
                            <span class="mono" style="font-size:0.38rem;color:var(--text-ghost)">${time}</span>
                        </span>
                    </div>
                </li>`;
            }).join('');

            // Click handlers -- navigate to entity/zone
            feedEl.querySelectorAll('.ua-alert-item').forEach(item => {
                item.addEventListener('click', () => {
                    const entityId = item.dataset.entity;
                    const zoneId = item.dataset.zone;
                    if (entityId) {
                        // Try to navigate to the target on the map
                        EventBus.emit('target:focus', { id: entityId });
                        EventBus.emit('map:centerOnUnit', { id: entityId });
                    } else if (zoneId) {
                        EventBus.emit('zone:selected', { id: zoneId });
                    }
                });
            });
        }

        // Filter change handlers
        [sourceFilter, severityFilter, timeFilter].forEach(el => {
            if (el) el.addEventListener('change', fetchAlerts);
        });

        if (refreshBtn) refreshBtn.addEventListener('click', fetchAlerts);

        // Initial fetch and auto-refresh
        fetchAlerts();
        timer = setInterval(fetchAlerts, REFRESH_INTERVAL);
        panel._uaTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._uaTimer) {
            clearInterval(panel._uaTimer);
            panel._uaTimer = null;
        }
    },
};
