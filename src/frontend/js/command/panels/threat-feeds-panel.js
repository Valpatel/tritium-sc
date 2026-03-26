// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Threat Feeds Panel — known-bad indicator intelligence dashboard.
// Shows active threat indicators, matched targets, severity distribution,
// alert history, and feed source breakdown. Auto-refreshes every 10s.
// Backend: /api/threats/ (list, add, remove, check, import, stats)

import { EventBus } from '/lib/events.js';
import { _esc, _timeAgo } from '/lib/utils.js';

const POLL_INTERVAL = 10000; // 10s
const MAX_INDICATORS = 200;

// Threat level color mapping (cyberpunk palette)
const LEVEL_COLORS = {
    hostile: '#ff2a6d',    // magenta
    suspicious: '#fcee0a', // yellow
    unknown: '#888',
};

const LEVEL_LABELS = {
    hostile: 'HOSTILE',
    suspicious: 'SUSPICIOUS',
    unknown: 'UNKNOWN',
};

const TYPE_ICONS = {
    mac: '\u00b7',          // dot
    ssid: '\u2261',         // triple bar (wifi)
    ip: '\u2302',           // house/network
    device_name: '\u2699',  // gear
};

const TYPE_LABELS = {
    mac: 'MAC',
    ssid: 'SSID',
    ip: 'IP',
    device_name: 'DEVICE',
};

function _levelBadge(level) {
    const color = LEVEL_COLORS[level] || '#888';
    const label = LEVEL_LABELS[level] || (level || 'UNK').toUpperCase().substring(0, 8);
    return `<span class="tf-level-badge" style="background:${color};color:#0a0a0f;font-size:0.38rem;padding:1px 4px;border-radius:2px;font-weight:bold;letter-spacing:0.5px">${label}</span>`;
}

function _typeBadge(type) {
    const icon = TYPE_ICONS[type] || '\u2022';
    const label = TYPE_LABELS[type] || (type || 'UNK').toUpperCase();
    return `<span class="tf-type-badge mono" style="font-size:0.38rem;color:var(--text-dim, #888);margin-left:4px">${icon} ${label}</span>`;
}

function _formatTime(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString().substring(0, 8);
}

function _renderStatsBar(stats) {
    if (!stats) return '';
    const total = stats.total || 0;
    const byLevel = stats.by_level || {};
    const hostile = byLevel.hostile || 0;
    const suspicious = byLevel.suspicious || 0;
    return `
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:6px">
            <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center">
                <div style="font-size:9px;color:#666;text-transform:uppercase">Total</div>
                <div style="font-size:16px;color:#00f0ff;margin-top:2px">${total}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #ff2a6d33;padding:6px;text-align:center">
                <div style="font-size:9px;color:#666;text-transform:uppercase">Hostile</div>
                <div style="font-size:16px;color:#ff2a6d;margin-top:2px">${hostile}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #fcee0a33;padding:6px;text-align:center">
                <div style="font-size:9px;color:#666;text-transform:uppercase">Suspicious</div>
                <div style="font-size:16px;color:#fcee0a;margin-top:2px">${suspicious}</div>
            </div>
        </div>
    `;
}

function _renderTypeDistribution(stats) {
    if (!stats || !stats.by_type) return '';
    const byType = stats.by_type;
    const total = stats.total || 1;
    const types = Object.entries(byType).sort((a, b) => b[1] - a[1]);
    if (types.length === 0) return '';

    let bars = '';
    for (const [type, count] of types) {
        const pct = Math.round((count / total) * 100);
        const color = type === 'mac' ? '#00f0ff' : type === 'ssid' ? '#05ffa1' : type === 'ip' ? '#ff2a6d' : '#fcee0a';
        const label = TYPE_LABELS[type] || type.toUpperCase();
        bars += `
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
                <span class="mono" style="font-size:0.4rem;color:#888;min-width:45px">${_esc(label)}</span>
                <div style="flex:1;height:6px;background:#0e0e14;border-radius:3px;overflow:hidden">
                    <div style="width:${pct}%;height:100%;background:${color};border-radius:3px"></div>
                </div>
                <span class="mono" style="font-size:0.38rem;color:#666;min-width:28px;text-align:right">${count}</span>
            </div>
        `;
    }
    return `
        <div style="margin-bottom:8px">
            <div style="font-size:9px;color:#05ffa1;text-transform:uppercase;margin-bottom:4px">Type Distribution</div>
            ${bars}
        </div>
    `;
}

function _renderSourceBreakdown(stats) {
    if (!stats || !stats.by_source) return '';
    const bySrc = stats.by_source;
    const entries = Object.entries(bySrc).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) return '';

    const items = entries.map(([src, count]) => {
        return `<span class="mono" style="font-size:0.4rem;padding:2px 6px;background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;color:#00f0ff">${_esc(src)} <span style="color:#666">${count}</span></span>`;
    }).join(' ');

    return `
        <div style="margin-bottom:8px">
            <div style="font-size:9px;color:#05ffa1;text-transform:uppercase;margin-bottom:4px">Feed Sources</div>
            <div style="display:flex;flex-wrap:wrap;gap:4px">${items}</div>
        </div>
    `;
}

function _renderIndicatorList(indicators, filterType, filterLevel) {
    let filtered = indicators;
    if (filterType) {
        filtered = filtered.filter(i => i.indicator_type === filterType);
    }
    if (filterLevel) {
        filtered = filtered.filter(i => i.threat_level === filterLevel);
    }

    if (filtered.length === 0) {
        return '<li class="panel-empty" style="padding:12px;text-align:center;color:var(--text-ghost, #666);font-size:0.6rem">No indicators matching filters</li>';
    }

    return filtered.slice(0, MAX_INDICATORS).map(ind => {
        const level = ind.threat_level || 'unknown';
        const levelColor = LEVEL_COLORS[level] || '#888';
        const time = _formatTime(ind.last_seen);
        const desc = ind.description || '';

        return `<li class="panel-list-item tf-indicator-item" data-type="${_esc(ind.indicator_type)}" data-value="${_esc(ind.value)}" style="cursor:pointer;border-left:3px solid ${levelColor};padding:4px 6px;margin-bottom:2px" title="${_esc(desc)}">
            <div style="display:flex;align-items:flex-start;gap:4px;width:100%">
                <span style="display:flex;flex-direction:column;align-items:center;min-width:48px;padding-top:2px">
                    ${_levelBadge(level)}
                </span>
                <span style="flex:1;min-width:0;display:flex;flex-direction:column;gap:1px">
                    <span class="mono" style="font-size:0.48rem;color:var(--text-main, #ddd);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:bold">${_esc(ind.value)}</span>
                    <span style="font-size:0.4rem;color:var(--text-dim, #999);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(desc)}</span>
                </span>
                <span style="display:flex;flex-direction:column;align-items:flex-end;min-width:50px;gap:2px">
                    ${_typeBadge(ind.indicator_type)}
                    <span class="mono" style="font-size:0.38rem;color:var(--text-ghost, #666)">${time}</span>
                    <span style="font-size:0.38rem;color:#555">${_esc(ind.source || 'unknown')}</span>
                </span>
            </div>
        </li>`;
    }).join('');
}

export const ThreatFeedsPanelDef = {
    id: 'threat-feeds',
    title: 'THREAT FEEDS',
    defaultPosition: { x: 80, y: 80 },
    defaultSize: { w: 400, h: 520 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'tf-panel-inner';
        el.innerHTML = `
            <div class="tf-header" style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid var(--border, #1a1a2e)">
                <div class="tf-status" style="display:flex;align-items:center;gap:6px">
                    <span class="tf-count-total mono" data-bind="count-total" style="font-size:0.42rem;color:var(--text-dim, #888)">0 indicators</span>
                    <span class="tf-status-dot" data-bind="status-dot" style="width:6px;height:6px;border-radius:50%;background:#555;display:inline-block" title="Feed status"></span>
                </div>
                <div class="tf-controls" style="display:flex;gap:4px;align-items:center">
                    <button class="panel-action-btn" data-action="add" title="Add indicator" style="font-size:0.42rem;padding:2px 4px">+ ADD</button>
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem;padding:2px 6px">REFRESH</button>
                </div>
            </div>
            <div class="tf-stats" data-bind="stats" style="padding:6px 8px;border-bottom:1px solid var(--border, #1a1a2e)">
                <div style="color:#555;padding:4px;text-align:center;font-size:0.5rem">Loading stats...</div>
            </div>
            <div class="tf-filters" style="padding:4px 8px;border-bottom:1px solid var(--border, #1a1a2e)">
                <div class="tf-filter-row" style="display:flex;gap:4px">
                    <select class="tf-filter-select" data-filter="type" title="Filter by type" style="flex:1;background:var(--surface-1, #0e0e14);border:1px solid var(--border, #1a1a2e);color:var(--text, #ccc);padding:2px 4px;font-size:0.42rem;font-family:var(--font-mono)">
                        <option value="">ALL TYPES</option>
                        <option value="mac">MAC Address</option>
                        <option value="ssid">SSID</option>
                        <option value="ip">IP Address</option>
                        <option value="device_name">Device Name</option>
                    </select>
                    <select class="tf-filter-select" data-filter="level" title="Filter by threat level" style="flex:1;background:var(--surface-1, #0e0e14);border:1px solid var(--border, #1a1a2e);color:var(--text, #ccc);padding:2px 4px;font-size:0.42rem;font-family:var(--font-mono)">
                        <option value="">ALL LEVELS</option>
                        <option value="hostile">Hostile</option>
                        <option value="suspicious">Suspicious</option>
                    </select>
                </div>
            </div>
            <ul class="panel-list tf-feed" data-bind="feed" role="log" aria-label="Threat indicator feed" aria-live="polite" style="flex:1;overflow-y:auto;margin:0;padding:0;list-style:none">
                <li class="panel-empty" style="padding:12px;text-align:center;color:var(--text-ghost, #666);font-size:0.6rem">Loading threat indicators...</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const feedEl = bodyEl.querySelector('[data-bind="feed"]');
        const statsEl = bodyEl.querySelector('[data-bind="stats"]');
        const countTotal = bodyEl.querySelector('[data-bind="count-total"]');
        const statusDot = bodyEl.querySelector('[data-bind="status-dot"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const addBtn = bodyEl.querySelector('[data-action="add"]');
        const typeFilter = bodyEl.querySelector('[data-filter="type"]');
        const levelFilter = bodyEl.querySelector('[data-filter="level"]');

        let indicators = [];
        let stats = null;
        let timer = null;

        async function fetchData() {
            try {
                // Fetch indicators and stats in parallel
                const [indResp, statsResp] = await Promise.all([
                    fetch('/api/threats/'),
                    fetch('/api/threats/stats'),
                ]);

                if (!indResp.ok || !statsResp.ok) throw new Error('HTTP error');

                const indData = await indResp.json();
                const statsData = await statsResp.json();

                indicators = indData.indicators || [];
                stats = statsData;

                // Update status dot
                if (statusDot) {
                    statusDot.style.background = '#05ffa1';
                    statusDot.title = 'Feed active';
                }

                updateDisplay();

            } catch (e) {
                console.error('[ThreatFeeds] fetch failed:', e);
                if (statusDot) {
                    statusDot.style.background = '#ff2a6d';
                    statusDot.title = 'Feed error: ' + e.message;
                }
                if (feedEl && indicators.length === 0) {
                    feedEl.innerHTML = '<li class="panel-empty" style="padding:12px;text-align:center;color:#ff2a6d;font-size:0.6rem">Failed to load threat feeds</li>';
                }
            }
        }

        function updateDisplay() {
            // Update stats section
            if (statsEl && stats) {
                statsEl.innerHTML = _renderStatsBar(stats) + _renderTypeDistribution(stats) + _renderSourceBreakdown(stats);
            }

            // Update count
            if (countTotal) {
                countTotal.textContent = (stats ? stats.total : indicators.length) + ' indicators';
            }

            // Update panel title badge
            if (panel && panel.el) {
                const titleEl = panel.el.querySelector('.panel-title');
                if (titleEl) {
                    let badge = titleEl.querySelector('.tf-title-badge');
                    const hostileCount = stats && stats.by_level ? (stats.by_level.hostile || 0) : 0;
                    if (hostileCount > 0) {
                        if (!badge) {
                            badge = document.createElement('span');
                            badge.className = 'tf-title-badge';
                            badge.style.cssText = 'background:#ff2a6d;color:#0a0a0f;font-size:0.38rem;padding:1px 4px;border-radius:6px;margin-left:6px;font-weight:bold';
                            titleEl.appendChild(badge);
                        }
                        badge.textContent = hostileCount;
                    } else if (badge) {
                        badge.remove();
                    }
                }
            }

            // Render indicator list
            renderIndicators();
        }

        function renderIndicators() {
            if (!feedEl) return;
            const filterType = typeFilter ? typeFilter.value : '';
            const filterLevel = levelFilter ? levelFilter.value : '';
            feedEl.innerHTML = _renderIndicatorList(indicators, filterType, filterLevel);

            // Wire click handlers for indicator items
            feedEl.querySelectorAll('.tf-indicator-item').forEach(item => {
                item.addEventListener('click', () => {
                    const type = item.dataset.type;
                    const value = item.dataset.value;
                    if (type && value) {
                        EventBus.emit('threat:indicator_selected', { type, value });
                    }
                });
            });
        }

        // Add indicator dialog
        if (addBtn) {
            addBtn.addEventListener('click', () => {
                EventBus.emit('threat:add_indicator_request', {});
            });
        }

        // Filter handlers
        [typeFilter, levelFilter].forEach(el => {
            if (el) el.addEventListener('change', renderIndicators);
        });

        if (refreshBtn) refreshBtn.addEventListener('click', fetchData);

        // Initial fetch and auto-refresh
        fetchData();
        timer = setInterval(fetchData, POLL_INTERVAL);
        panel._tfTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._tfTimer) {
            clearInterval(panel._tfTimer);
            panel._tfTimer = null;
        }
    },
};
