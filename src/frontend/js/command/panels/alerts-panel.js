// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Unified Alerts Panel — real-time alert feed from the SitAware AlertEngine.
// Polls /api/sitaware/updates?type=alert_fired for incremental updates.
// Each alert shows: severity badge, message, time, source.
// Color-coded: critical=red, high=orange, medium=yellow, low=cyan.
// Acknowledge/dismiss buttons, optional critical alert sound, auto-scroll.

import { EventBus } from '/lib/events.js';
import { _esc, _timeAgo } from '/lib/utils.js';

const POLL_INTERVAL = 5000; // 5s
const MAX_ALERTS = 200;
const DISPLAY_LIMIT = 100;

// Severity color mapping (cyberpunk palette)
const SEVERITY_COLORS = {
    critical: '#ff2a6d', // magenta
    high: '#ff8c00',     // orange
    medium: '#fcee0a',   // yellow
    low: '#00f0ff',      // cyan
    warning: '#ff8c00',  // orange alias
    info: '#00f0ff',     // cyan alias
};

const SEVERITY_LABELS = {
    critical: 'CRIT',
    high: 'HIGH',
    medium: 'MED',
    low: 'LOW',
    warning: 'WARN',
    info: 'INFO',
};

const SEVERITY_ORDER = { critical: 0, high: 1, warning: 2, medium: 3, low: 4, info: 5 };

const SOURCE_ICONS = {
    alerting: '\u26a0',
    geofence: '\u25a0',
    fusion: '\u2731',
    anomaly: '\u25c6',
    sensor: '\u2665',
    ble: '\u00b7',
    acoustic: '\u266b',
    threat: '\u26a0',
    escalation: '\u2191',
};

function _severityBadge(severity) {
    const color = SEVERITY_COLORS[severity] || '#888';
    const label = SEVERITY_LABELS[severity] || (severity || 'UNK').toUpperCase().substring(0, 4);
    return `<span class="ua-sev-badge" style="background:${color};color:#0a0a0f;font-size:0.38rem;padding:1px 4px;border-radius:2px;font-weight:bold;letter-spacing:0.5px">${label}</span>`;
}

function _sourceBadge(source) {
    const icon = SOURCE_ICONS[source] || '\u2022';
    const label = (source || 'system').toUpperCase();
    return `<span class="ua-src-badge mono" style="font-size:0.38rem;color:var(--text-dim, #888);margin-left:4px">${icon} ${label}</span>`;
}

function _formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString().substring(0, 8);
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
            <div class="ua-header" style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid var(--border, #1a1a2e)">
                <div class="ua-counts" data-bind="counts" style="display:flex;align-items:center;gap:4px">
                    <span class="ua-count-badge ua-count-critical" data-bind="count-critical" title="Critical" style="background:#ff2a6d;color:#0a0a0f;font-size:0.38rem;padding:1px 5px;border-radius:8px;font-weight:bold;min-width:14px;text-align:center">0</span>
                    <span class="ua-count-badge ua-count-high" data-bind="count-high" title="High" style="background:#ff8c00;color:#0a0a0f;font-size:0.38rem;padding:1px 5px;border-radius:8px;font-weight:bold;min-width:14px;text-align:center">0</span>
                    <span class="ua-count-badge ua-count-medium" data-bind="count-medium" title="Medium" style="background:#fcee0a;color:#0a0a0f;font-size:0.38rem;padding:1px 5px;border-radius:8px;font-weight:bold;min-width:14px;text-align:center">0</span>
                    <span class="ua-count-badge ua-count-low" data-bind="count-low" title="Low" style="background:#00f0ff;color:#0a0a0f;font-size:0.38rem;padding:1px 5px;border-radius:8px;font-weight:bold;min-width:14px;text-align:center">0</span>
                    <span class="ua-count-total mono" data-bind="count-total" style="color:var(--text-dim, #888);font-size:0.42rem;margin-left:4px">0 total</span>
                </div>
                <div class="ua-controls" style="display:flex;gap:4px;align-items:center">
                    <button class="panel-action-btn" data-action="sound-toggle" title="Toggle critical alert sound" style="font-size:0.42rem;padding:2px 4px">\u266b OFF</button>
                    <button class="panel-action-btn" data-action="dismiss-all" title="Dismiss all alerts" style="font-size:0.42rem;padding:2px 4px">CLEAR</button>
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem;padding:2px 6px">REFRESH</button>
                </div>
            </div>
            <div class="ua-filters" data-bind="filters" style="padding:4px 8px;border-bottom:1px solid var(--border, #1a1a2e)">
                <div class="ua-filter-row" style="display:flex;gap:4px">
                    <select class="ua-filter-select" data-filter="severity" title="Filter by severity" style="flex:1;background:var(--surface-1, #0e0e14);border:1px solid var(--border, #1a1a2e);color:var(--text, #ccc);padding:2px 4px;font-size:0.42rem;font-family:var(--font-mono)">
                        <option value="">ALL SEVERITY</option>
                        <option value="critical">Critical</option>
                        <option value="high">High</option>
                        <option value="medium">Medium</option>
                        <option value="low">Low</option>
                    </select>
                    <select class="ua-filter-select" data-filter="source" title="Filter by source" style="flex:1;background:var(--surface-1, #0e0e14);border:1px solid var(--border, #1a1a2e);color:var(--text, #ccc);padding:2px 4px;font-size:0.42rem;font-family:var(--font-mono)">
                        <option value="">ALL SOURCES</option>
                        <option value="alerting">Alerting</option>
                        <option value="geofence">Geofence</option>
                        <option value="fusion">Fusion</option>
                        <option value="anomaly">Anomaly</option>
                        <option value="sensor">Sensor</option>
                    </select>
                </div>
            </div>
            <ul class="panel-list ua-feed" data-bind="feed" role="log" aria-label="Real-time alert feed" aria-live="polite" style="flex:1;overflow-y:auto;margin:0;padding:0;list-style:none">
                <li class="panel-empty" style="padding:12px;text-align:center;color:var(--text-ghost, #666);font-size:0.6rem">Loading alerts...</li>
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
        const dismissAllBtn = bodyEl.querySelector('[data-action="dismiss-all"]');
        const severityFilter = bodyEl.querySelector('[data-filter="severity"]');
        const sourceFilter = bodyEl.querySelector('[data-filter="source"]');

        let alerts = [];
        let dismissedIds = new Set();
        let acknowledgedIds = new Set();
        let timer = null;
        let lastTimestamp = 0;
        let previousCriticalCount = 0;
        let autoScroll = true;

        // Sound toggle
        if (soundBtn) {
            soundBtn.addEventListener('click', () => {
                _criticalSoundEnabled = !_criticalSoundEnabled;
                soundBtn.textContent = _criticalSoundEnabled ? '\u266b ON' : '\u266b OFF';
                soundBtn.classList.toggle('panel-action-btn-primary', _criticalSoundEnabled);
            });
        }

        // Dismiss all
        if (dismissAllBtn) {
            dismissAllBtn.addEventListener('click', () => {
                alerts.forEach(a => dismissedIds.add(a.update_id));
                render();
            });
        }

        function getVisibleAlerts() {
            let visible = alerts.filter(a => !dismissedIds.has(a.update_id));

            // Apply severity filter
            const sevVal = severityFilter ? severityFilter.value : '';
            if (sevVal) {
                visible = visible.filter(a => a.severity === sevVal);
            }

            // Apply source filter
            const srcVal = sourceFilter ? sourceFilter.value : '';
            if (srcVal) {
                visible = visible.filter(a => a.source === srcVal);
            }

            return visible;
        }

        async function fetchAlerts() {
            try {
                const params = new URLSearchParams();
                params.set('type', 'alert_fired');
                params.set('limit', String(MAX_ALERTS));
                if (lastTimestamp > 0) {
                    params.set('since', String(lastTimestamp));
                }

                const resp = await fetch(`/api/sitaware/updates?${params.toString()}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();

                if (!data.available) {
                    if (feedEl) feedEl.innerHTML = '<li class="panel-empty" style="padding:12px;text-align:center;color:var(--text-ghost, #666);font-size:0.6rem">SitAware engine not available</li>';
                    return;
                }

                const newUpdates = data.updates || [];
                if (newUpdates.length > 0) {
                    // Merge new alerts (prepend, newest first)
                    for (const u of newUpdates) {
                        // Avoid duplicates
                        if (!alerts.find(a => a.update_id === u.update_id)) {
                            alerts.unshift(u);
                        }
                    }

                    // Trim to max
                    if (alerts.length > MAX_ALERTS) {
                        alerts = alerts.slice(0, MAX_ALERTS);
                    }

                    // Track latest timestamp for delta polling
                    const maxTs = Math.max(...newUpdates.map(u => u.timestamp || 0));
                    if (maxTs > lastTimestamp) {
                        lastTimestamp = maxTs;
                    }
                }

                // Update server time for next poll if no updates
                if (data.server_time && lastTimestamp === 0) {
                    // On first empty fetch, use server time - window
                    lastTimestamp = data.server_time - 3600; // last hour
                }

                updateCounts();
                render();

            } catch (e) {
                console.error('[UnifiedAlerts] fetch failed:', e);
                if (feedEl && alerts.length === 0) {
                    feedEl.innerHTML = '<li class="panel-empty" style="padding:12px;text-align:center;color:#ff2a6d;font-size:0.6rem">Failed to load alerts</li>';
                }
            }
        }

        function updateCounts() {
            const visible = alerts.filter(a => !dismissedIds.has(a.update_id));
            const counts = { critical: 0, high: 0, medium: 0, low: 0 };
            for (const a of visible) {
                const sev = a.severity || 'low';
                if (counts[sev] !== undefined) counts[sev]++;
                // Map 'warning' to high for counting
                if (sev === 'warning' && counts.high !== undefined) counts.high++;
                if (sev === 'info' && counts.low !== undefined) counts.low++;
            }

            if (countCritical) countCritical.textContent = counts.critical;
            if (countHigh) countHigh.textContent = counts.high;
            if (countMedium) countMedium.textContent = counts.medium;
            if (countLow) countLow.textContent = counts.low;
            if (countTotal) countTotal.textContent = `${visible.length} total`;

            // Update panel title badge
            const totalAlerts = visible.length;
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
        }

        function render() {
            if (!feedEl) return;
            const visible = getVisibleAlerts();

            if (visible.length === 0) {
                feedEl.innerHTML = '<li class="panel-empty" style="padding:12px;text-align:center;color:var(--text-ghost, #666);font-size:0.6rem">No alerts matching filters</li>';
                return;
            }

            const shouldScrollToBottom = autoScroll && feedEl.scrollTop >= feedEl.scrollHeight - feedEl.clientHeight - 20;

            feedEl.innerHTML = visible.slice(0, DISPLAY_LIMIT).map(a => {
                const sev = a.severity || 'info';
                const sevColor = SEVERITY_COLORS[sev] || '#888';
                const time = _formatTime(a.timestamp);
                const source = a.source || 'system';
                const acked = acknowledgedIds.has(a.update_id);

                // Extract message and title from the alert data
                const alertData = a.data || {};
                const title = alertData.rule_name || alertData.title || a.update_type || 'Alert';
                const message = alertData.message || alertData.detail || '';
                const targetId = a.target_id || alertData.target_id || '';
                const zoneId = a.zone_id || alertData.zone_id || '';
                const clickData = targetId ? `data-entity="${_esc(targetId)}"` : '';
                const zoneData = zoneId ? `data-zone="${_esc(zoneId)}"` : '';
                const ackedStyle = acked ? 'opacity:0.5;' : '';

                return `<li class="panel-list-item ua-alert-item" data-update-id="${_esc(a.update_id)}" style="cursor:pointer;border-left:3px solid ${sevColor};padding:4px 6px;margin-bottom:2px;${ackedStyle}" ${clickData} ${zoneData} title="${_esc(message)}">
                    <div style="display:flex;align-items:flex-start;gap:4px;width:100%">
                        <span style="display:flex;flex-direction:column;align-items:center;min-width:36px;padding-top:2px">
                            ${_severityBadge(sev)}
                        </span>
                        <span style="flex:1;min-width:0;display:flex;flex-direction:column;gap:1px">
                            <span style="font-size:0.5rem;color:var(--text-main, #ddd);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:bold">${_esc(title)}</span>
                            <span style="font-size:0.42rem;color:var(--text-dim, #999);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(message)}</span>
                            ${targetId ? `<span class="mono" style="font-size:0.38rem;color:var(--text-ghost, #666)">Target: ${_esc(targetId)}</span>` : ''}
                        </span>
                        <span style="display:flex;flex-direction:column;align-items:flex-end;min-width:50px;gap:2px">
                            ${_sourceBadge(source)}
                            <span class="mono" style="font-size:0.38rem;color:var(--text-ghost, #666)">${time}</span>
                            <span style="display:flex;gap:2px">
                                <button class="ua-ack-btn" data-action="ack" data-uid="${_esc(a.update_id)}" title="Acknowledge" style="font-size:0.32rem;padding:0 3px;background:none;border:1px solid ${acked ? '#333' : '#05ffa1'};color:${acked ? '#333' : '#05ffa1'};border-radius:2px;cursor:pointer;line-height:1.4">${acked ? 'ACK' : 'ACK'}</button>
                                <button class="ua-dismiss-btn" data-action="dismiss" data-uid="${_esc(a.update_id)}" title="Dismiss" style="font-size:0.32rem;padding:0 3px;background:none;border:1px solid #ff2a6d;color:#ff2a6d;border-radius:2px;cursor:pointer;line-height:1.4">X</button>
                            </span>
                        </span>
                    </div>
                </li>`;
            }).join('');

            // Auto-scroll to newest (top of feed)
            if (autoScroll) {
                feedEl.scrollTop = 0;
            }

            // Wire click handlers
            feedEl.querySelectorAll('.ua-alert-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    // Ignore button clicks
                    if (e.target.closest('[data-action="ack"]') || e.target.closest('[data-action="dismiss"]')) return;

                    const entityId = item.dataset.entity;
                    const zoneId = item.dataset.zone;
                    if (entityId) {
                        EventBus.emit('target:focus', { id: entityId });
                        EventBus.emit('map:centerOnUnit', { id: entityId });
                    } else if (zoneId) {
                        EventBus.emit('zone:selected', { id: zoneId });
                    }
                });
            });

            // Acknowledge buttons
            feedEl.querySelectorAll('[data-action="ack"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const uid = btn.dataset.uid;
                    if (uid) {
                        acknowledgedIds.add(uid);
                        render();
                    }
                });
            });

            // Dismiss buttons
            feedEl.querySelectorAll('[data-action="dismiss"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const uid = btn.dataset.uid;
                    if (uid) {
                        dismissedIds.add(uid);
                        render();
                    }
                });
            });
        }

        // Filter change handlers
        [severityFilter, sourceFilter].forEach(el => {
            if (el) el.addEventListener('change', render);
        });

        if (refreshBtn) refreshBtn.addEventListener('click', () => {
            lastTimestamp = 0;
            alerts = [];
            dismissedIds.clear();
            acknowledgedIds.clear();
            fetchAlerts();
        });

        // Initial fetch and auto-refresh
        fetchAlerts();
        timer = setInterval(fetchAlerts, POLL_INTERVAL);
        panel._uaTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._uaTimer) {
            clearInterval(panel._uaTimer);
            panel._uaTimer = null;
        }
    },
};
