// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// LPR (License Plate Recognition) Panel — live plate feed, watchlist
// management, plate search, and watchlist match alerts.
// Backend API: /api/lpr (detections, watchlist, search, stats)

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


// Priority-based color coding
const PRIORITY_COLORS = {
    critical: '#ff2a6d',   // magenta — stolen/amber alert
    high:     '#ff2a6d',   // magenta — wanted
    normal:   '#fcee0a',   // yellow  — BOLO/surveillance
    low:      '#05ffa1',   // green   — VIP/minor
};

function _priorityColor(priority) {
    return PRIORITY_COLORS[priority] || '#00f0ff';
}

function _priorityLabel(priority) {
    const labels = { critical: 'STOLEN', high: 'WANTED', normal: 'BOLO', low: 'VIP' };
    return labels[priority] || priority.toUpperCase();
}

export const LprPanelDef = {
    id: 'lpr',
    title: 'LPR / PLATE READER',
    defaultPosition: { x: 340, y: 60 },
    defaultSize: { w: 420, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'lpr-panel-inner';
        el.innerHTML = `
            <div class="lpr-toolbar" style="display:flex;gap:4px;padding:4px;align-items:center">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" title="Refresh">REFRESH</button>
                <span class="lpr-alert-indicator" data-bind="alert-indicator" style="display:none;color:#ff2a6d;font-weight:bold;font-size:0.44rem;animation:lpr-blink 0.8s infinite alternate" title="Watchlist match detected">ALERT</span>
                <span class="lpr-stats" data-bind="stats" style="font-size:0.42rem;color:#888;flex:1;text-align:right"></span>
            </div>
            <div class="lpr-tab-bar" style="display:flex;gap:2px;margin:2px 4px">
                <button class="panel-action-btn panel-action-btn-primary lpr-tab" data-tab="detections" style="flex:1;font-size:0.43rem">LIVE FEED</button>
                <button class="panel-action-btn lpr-tab" data-tab="watchlist" style="flex:1;font-size:0.43rem">WATCHLIST</button>
                <button class="panel-action-btn lpr-tab" data-tab="search" style="flex:1;font-size:0.43rem">SEARCH</button>
            </div>
            <div class="lpr-search-bar" data-bind="search-bar" style="display:none;padding:4px">
                <input type="text" class="panel-input" data-bind="search-input" placeholder="Search plate (partial match)..."
                    style="width:100%;background:#12121a;border:1px solid #333;color:#ccc;padding:4px 8px;font-family:monospace;font-size:0.45rem;text-transform:uppercase">
            </div>
            <div class="lpr-add-form" data-bind="add-form" style="display:none;padding:4px;border-bottom:1px solid #222">
                <div style="display:flex;gap:4px;margin-bottom:4px">
                    <input type="text" class="panel-input" data-bind="add-plate" placeholder="PLATE NUMBER"
                        style="flex:2;background:#12121a;border:1px solid #333;color:#05ffa1;padding:4px 6px;font-family:monospace;font-size:0.45rem;text-transform:uppercase">
                    <select data-bind="add-priority" style="flex:1;background:#12121a;border:1px solid #333;color:#ccc;padding:4px;font-size:0.42rem">
                        <option value="normal">BOLO</option>
                        <option value="critical">STOLEN</option>
                        <option value="high">WANTED</option>
                        <option value="low">VIP</option>
                    </select>
                </div>
                <div style="display:flex;gap:4px;margin-bottom:4px">
                    <input type="text" class="panel-input" data-bind="add-reason" placeholder="Reason..."
                        style="flex:1;background:#12121a;border:1px solid #333;color:#ccc;padding:4px 6px;font-size:0.42rem">
                </div>
                <div style="display:flex;gap:4px;margin-bottom:4px">
                    <input type="text" class="panel-input" data-bind="add-owner" placeholder="Owner..."
                        style="flex:1;background:#12121a;border:1px solid #333;color:#ccc;padding:4px 6px;font-size:0.42rem">
                    <input type="text" class="panel-input" data-bind="add-vehicle" placeholder="Vehicle description..."
                        style="flex:1;background:#12121a;border:1px solid #333;color:#ccc;padding:4px 6px;font-size:0.42rem">
                </div>
                <div style="display:flex;gap:4px;justify-content:flex-end">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="add-plate" style="font-size:0.42rem">+ ADD TO WATCHLIST</button>
                </div>
            </div>
            <ul class="panel-list lpr-list" data-bind="list" role="listbox" aria-label="LPR data"
                style="flex:1;overflow-y:auto;margin:0;padding:0;list-style:none">
                <li class="panel-empty">Loading...</li>
            </ul>
            <style>
                @keyframes lpr-blink {
                    from { opacity: 1; }
                    to { opacity: 0.3; }
                }
            </style>
        `;
        return el;
    },

    init(panel) {
        const el = panel.contentEl;
        let activeTab = 'detections';
        let pollTimer = null;
        let lastWatchlistHits = 0;

        // Tab switching
        el.querySelectorAll('.lpr-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                el.querySelectorAll('.lpr-tab').forEach(b =>
                    b.classList.remove('panel-action-btn-primary')
                );
                btn.classList.add('panel-action-btn-primary');
                activeTab = btn.dataset.tab;

                // Show/hide contextual bars
                const searchBar = el.querySelector('[data-bind="search-bar"]');
                const addForm = el.querySelector('[data-bind="add-form"]');
                searchBar.style.display = activeTab === 'search' ? 'block' : 'none';
                addForm.style.display = activeTab === 'watchlist' ? 'block' : 'none';

                refresh();
            });
        });

        // Toolbar refresh
        el.querySelector('[data-action="refresh"]').addEventListener('click', refresh);

        // Search input with debounce
        let searchDebounce = null;
        const searchInput = el.querySelector('[data-bind="search-input"]');
        searchInput.addEventListener('input', () => {
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(() => searchPlates(searchInput.value), 300);
        });

        // Add plate button
        el.querySelector('[data-action="add-plate"]').addEventListener('click', addPlate);

        async function refresh() {
            try {
                if (activeTab === 'detections') await loadDetections();
                else if (activeTab === 'watchlist') await loadWatchlist();
                else if (activeTab === 'search') await searchPlates(searchInput.value);
                await loadStats();
            } catch (err) {
                console.warn('[lpr] refresh error:', err);
            }
        }

        async function loadStats() {
            try {
                const res = await fetch('/api/lpr/');
                if (!res.ok) return;
                const data = await res.json();
                const stats = data.stats || {};
                const statsEl = el.querySelector('[data-bind="stats"]');
                const alertEl = el.querySelector('[data-bind="alert-indicator"]');

                if (statsEl) {
                    const total = stats.total_detections || 0;
                    const unique = stats.unique_plates || 0;
                    const hits = stats.watchlist_hits || 0;
                    const wlSize = stats.watchlist_size || 0;
                    statsEl.textContent = `${total} reads | ${unique} plates | ${hits} hits | WL:${wlSize}`;
                    statsEl.style.color = hits > 0 ? '#ff2a6d' : '#888';
                }

                // Flash alert indicator when new watchlist hits occur
                if (alertEl) {
                    const hits = stats.watchlist_hits || 0;
                    if (hits > lastWatchlistHits && lastWatchlistHits > 0) {
                        alertEl.style.display = 'inline';
                        setTimeout(() => { alertEl.style.display = 'none'; }, 8000);
                    }
                    lastWatchlistHits = hits;
                }
            } catch (_) { /* ignore */ }
        }

        async function loadDetections() {
            const list = el.querySelector('[data-bind="list"]');
            try {
                const res = await fetch('/api/lpr/detections?count=50');
                if (!res.ok) {
                    list.innerHTML = '<li class="panel-empty">API unavailable</li>';
                    return;
                }
                const data = await res.json();
                const detections = data.detections || [];
                if (!detections.length) {
                    list.innerHTML = '<li class="panel-empty">No plate detections yet</li>';
                    return;
                }
                // Show newest first
                list.innerHTML = detections.slice().reverse().map(d => {
                    const ts = new Date(d.timestamp * 1000).toLocaleTimeString();
                    const conf = Math.round((d.confidence || 0) * 100);
                    const isHit = d.watchlist_match;
                    const priority = d.watchlist_priority || 'normal';
                    const hitColor = isHit ? _priorityColor(priority) : '#333';
                    const hitBadge = isHit
                        ? `<span style="color:${_esc(hitColor)};font-weight:bold;font-size:0.42rem;margin-left:4px">[${_esc(_priorityLabel(priority))}]</span>`
                        : '';
                    const reason = d.watchlist_reason
                        ? `<div style="color:${_esc(hitColor)};font-size:0.38rem;margin-top:1px;padding-left:2px">${_esc(d.watchlist_reason)}</div>`
                        : '';
                    const vehicle = d.vehicle_type
                        ? `<span style="color:#888;font-size:0.4rem"> ${_esc(d.vehicle_color || '')} ${_esc(d.vehicle_type)}</span>`
                        : '';
                    return `<li class="panel-list-item" style="border-left:3px solid ${_esc(hitColor)};padding-left:6px;cursor:pointer;margin-bottom:1px" data-plate="${_esc(d.plate_number)}">
                        <span style="color:#05ffa1;font-weight:bold;font-family:monospace;font-size:0.5rem;letter-spacing:1px">${_esc(d.plate_number)}</span>
                        ${hitBadge}${vehicle}
                        <span style="color:#888;font-size:0.38rem;margin-left:4px">${conf}%</span>
                        <span style="color:#555;font-size:0.38rem;float:right">${_esc(d.camera_id || '?')} ${ts}</span>
                        ${reason}
                    </li>`;
                }).join('');

                // Click detection to search for that plate
                list.querySelectorAll('[data-plate]').forEach(li => {
                    li.addEventListener('click', () => {
                        const plate = li.dataset.plate;
                        searchInput.value = plate;
                        // Switch to search tab
                        el.querySelectorAll('.lpr-tab').forEach(b =>
                            b.classList.remove('panel-action-btn-primary')
                        );
                        const searchTab = el.querySelector('[data-tab="search"]');
                        if (searchTab) searchTab.classList.add('panel-action-btn-primary');
                        activeTab = 'search';
                        el.querySelector('[data-bind="search-bar"]').style.display = 'block';
                        el.querySelector('[data-bind="add-form"]').style.display = 'none';
                        searchPlates(plate);
                    });
                });
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Error loading detections</li>';
            }
        }

        async function loadWatchlist() {
            const list = el.querySelector('[data-bind="list"]');
            try {
                const res = await fetch('/api/lpr/watchlist');
                if (!res.ok) {
                    list.innerHTML = '<li class="panel-empty">API unavailable</li>';
                    return;
                }
                const data = await res.json();
                const watchlist = data.watchlist || [];
                if (!watchlist.length) {
                    list.innerHTML = '<li class="panel-empty">Watchlist empty — add plates above</li>';
                    return;
                }
                list.innerHTML = watchlist.map(e => {
                    const color = _priorityColor(e.priority);
                    const label = _priorityLabel(e.priority);
                    const added = new Date(e.added_at * 1000).toLocaleDateString();
                    const lastSeen = e.last_seen
                        ? new Date(e.last_seen * 1000).toLocaleString()
                        : 'Never';
                    const hits = e.hit_count || 0;
                    return `<li class="panel-list-item" style="border-left:3px solid ${_esc(color)};padding-left:6px;margin-bottom:1px">
                        <div style="display:flex;align-items:center;gap:4px">
                            <span style="color:#05ffa1;font-weight:bold;font-family:monospace;font-size:0.48rem;letter-spacing:1px">${_esc(e.plate_number)}</span>
                            <span style="color:${_esc(color)};font-size:0.42rem;font-weight:bold">[${_esc(label)}]</span>
                            <span style="flex:1"></span>
                            <span style="color:#888;font-size:0.38rem">${hits} hits</span>
                            <button class="panel-action-btn lpr-remove-btn" data-remove-plate="${_esc(e.plate_number)}"
                                style="font-size:0.38rem;padding:1px 4px;color:#ff2a6d;border-color:#ff2a6d" title="Remove from watchlist">X</button>
                        </div>
                        <div style="color:#aaa;font-size:0.38rem;margin-top:2px">${_esc(e.reason || 'No reason')}</div>
                        <div style="color:#666;font-size:0.36rem;margin-top:1px">
                            ${e.owner ? _esc(e.owner) + ' | ' : ''}${e.vehicle_description ? _esc(e.vehicle_description) + ' | ' : ''}Added: ${added} | Last: ${lastSeen}
                        </div>
                    </li>`;
                }).join('');

                // Wire remove buttons
                list.querySelectorAll('.lpr-remove-btn').forEach(btn => {
                    btn.addEventListener('click', async (ev) => {
                        ev.stopPropagation();
                        const plate = btn.dataset.removePlate;
                        try {
                            await fetch(`/api/lpr/watchlist/${encodeURIComponent(plate)}`, { method: 'DELETE' });
                            refresh();
                        } catch (err) {
                            console.warn('[lpr] remove error:', err);
                        }
                    });
                });
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Error loading watchlist</li>';
            }
        }

        async function searchPlates(query) {
            const list = el.querySelector('[data-bind="list"]');
            if (!query || query.length < 2) {
                list.innerHTML = '<li class="panel-empty">Type at least 2 characters to search</li>';
                return;
            }
            try {
                const res = await fetch(`/api/lpr/search?q=${encodeURIComponent(query)}`);
                if (!res.ok) {
                    list.innerHTML = '<li class="panel-empty">API unavailable</li>';
                    return;
                }
                const data = await res.json();
                const results = data.results || [];
                if (!results.length) {
                    list.innerHTML = `<li class="panel-empty">No plates matching "${_esc(query.toUpperCase())}"</li>`;
                    return;
                }
                list.innerHTML = `<li style="color:#888;font-size:0.38rem;padding:2px 6px;border-bottom:1px solid #222">${results.length} result${results.length !== 1 ? 's' : ''} for "${_esc(data.query)}"</li>` +
                    results.map(d => {
                    const ts = new Date(d.timestamp * 1000).toLocaleString();
                    const conf = Math.round((d.confidence || 0) * 100);
                    const isHit = d.watchlist_match;
                    const priority = d.watchlist_priority || 'normal';
                    const hitColor = isHit ? _priorityColor(priority) : '#333';
                    const hitBadge = isHit
                        ? `<span style="color:${_esc(hitColor)};font-weight:bold;font-size:0.42rem">[${_esc(_priorityLabel(priority))}]</span>`
                        : '';
                    const vehicle = d.vehicle_type
                        ? `<span style="color:#888;font-size:0.4rem"> ${_esc(d.vehicle_color || '')} ${_esc(d.vehicle_type)}</span>`
                        : '';
                    return `<li class="panel-list-item" style="border-left:3px solid ${_esc(hitColor)};padding-left:6px;margin-bottom:1px">
                        <span style="color:#05ffa1;font-weight:bold;font-family:monospace;font-size:0.5rem;letter-spacing:1px">${_esc(d.plate_number)}</span>
                        ${hitBadge}${vehicle}
                        <span style="color:#888;font-size:0.38rem;margin-left:4px">${conf}%</span>
                        <span style="color:#555;font-size:0.38rem;float:right">${_esc(d.camera_id || '?')} ${ts}</span>
                    </li>`;
                }).join('');
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Search error</li>';
            }
        }

        async function addPlate() {
            const plateInput = el.querySelector('[data-bind="add-plate"]');
            const prioritySelect = el.querySelector('[data-bind="add-priority"]');
            const reasonInput = el.querySelector('[data-bind="add-reason"]');
            const ownerInput = el.querySelector('[data-bind="add-owner"]');
            const vehicleInput = el.querySelector('[data-bind="add-vehicle"]');
            const plateNumber = plateInput.value.trim();

            if (!plateNumber) return;

            try {
                const res = await fetch('/api/lpr/watchlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        plate_number: plateNumber,
                        priority: prioritySelect.value,
                        reason: reasonInput.value.trim(),
                        owner: ownerInput.value.trim(),
                        vehicle_description: vehicleInput.value.trim(),
                        alert_on_match: true,
                    }),
                });
                if (res.ok) {
                    plateInput.value = '';
                    reasonInput.value = '';
                    ownerInput.value = '';
                    vehicleInput.value = '';
                    refresh();
                    EventBus.emit('toast:show', {
                        message: `Plate ${plateNumber.toUpperCase()} added to watchlist`,
                        type: 'info',
                    });
                }
            } catch (err) {
                console.warn('[lpr] add plate error:', err);
            }
        }

        // WebSocket events for real-time LPR updates
        EventBus.on('lpr:detection', () => {
            if (activeTab === 'detections') refresh();
        });
        EventBus.on('lpr:watchlist_match', (data) => {
            // Flash alert indicator on watchlist hit
            const alertEl = el.querySelector('[data-bind="alert-indicator"]');
            if (alertEl) {
                alertEl.style.display = 'inline';
                setTimeout(() => { alertEl.style.display = 'none'; }, 10000);
            }
            refresh();
        });

        // Initial load
        refresh();

        // Poll every 5 seconds for live feed
        pollTimer = setInterval(refresh, 5000);

        panel._lprCleanup = () => {
            if (pollTimer) clearInterval(pollTimer);
        };
    },

    destroy(panel) {
        if (panel._lprCleanup) panel._lprCleanup();
    },
};
