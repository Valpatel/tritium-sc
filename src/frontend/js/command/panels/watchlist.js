// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Target Watch List Panel — curate targets of interest, track real-time
 * status updates, and receive alerts on movement or state changes.
 */

import { EventBus } from '../events.js';
import { TritiumStore } from '../store.js';

let _panel = null;
let _entries = [];
let _alerts = [];
let _refreshTimer = null;

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function _fetchEntries() {
    try {
        const res = await fetch('/api/watchlist');
        if (res.ok) {
            const data = await res.json();
            _entries = data.entries || [];
            _render();
        }
    } catch (e) {
        console.warn('[WATCHLIST] fetch failed:', e);
    }
}

async function _fetchAlerts() {
    try {
        const res = await fetch('/api/watchlist/alerts/history?limit=20');
        if (res.ok) {
            const data = await res.json();
            _alerts = data.alerts || [];
            _renderAlerts();
        }
    } catch (e) {
        console.warn('[WATCHLIST] alerts fetch failed:', e);
    }
}

async function _addTarget(targetId, label) {
    try {
        const res = await fetch('/api/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_id: targetId,
                label: label || targetId,
                alert_on_move: true,
                alert_on_state_change: true,
            }),
        });
        if (res.ok) {
            _fetchEntries();
        }
    } catch (e) {
        console.warn('[WATCHLIST] add failed:', e);
    }
}

async function _removeEntry(entryId) {
    try {
        await fetch(`/api/watchlist/${entryId}`, { method: 'DELETE' });
        _fetchEntries();
    } catch (e) {
        console.warn('[WATCHLIST] remove failed:', e);
    }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
    if (!_panel) return;
    const list = _panel.querySelector('.watchlist-entries');
    if (!list) return;

    if (_entries.length === 0) {
        list.innerHTML = `
            <div class="wl-empty">
                No targets on watch list.<br>
                <span class="wl-hint">Right-click a target on the map to add it, or use the search below.</span>
            </div>
        `;
        return;
    }

    list.innerHTML = _entries.map(e => {
        const state = e.last_state || {};
        const alliance = state.alliance || 'unknown';
        const status = state.status || 'unknown';
        const allianceColor = {
            friendly: '#05ffa1', hostile: '#ff2a6d',
            neutral: '#00a0ff', unknown: '#fcee0a'
        }[alliance] || '#fcee0a';
        const lastSeen = e.last_seen
            ? new Date(e.last_seen * 1000).toLocaleTimeString()
            : 'never';

        return `
            <div class="wl-entry" data-id="${e.id}" data-target="${e.target_id}">
                <div class="wl-entry-header">
                    <span class="wl-priority wl-p${e.priority}">P${e.priority}</span>
                    <span class="wl-label" style="color:${allianceColor}">${e.label}</span>
                    <button class="wl-remove" data-id="${e.id}" title="Remove">\u2715</button>
                </div>
                <div class="wl-entry-detail">
                    <span class="wl-status">${status}</span>
                    <span class="wl-seen">Last: ${lastSeen}</span>
                </div>
                ${e.notes ? `<div class="wl-notes">${e.notes}</div>` : ''}
            </div>
        `;
    }).join('');

    // Event bindings
    list.querySelectorAll('.wl-remove').forEach(btn => {
        btn.onclick = (ev) => {
            ev.stopPropagation();
            _removeEntry(btn.dataset.id);
        };
    });
    list.querySelectorAll('.wl-entry').forEach(el => {
        el.onclick = () => {
            const tid = el.dataset.target;
            EventBus.emit('map:centerOnUnit', { id: tid });
            TritiumStore.set('map.selectedUnitId', tid);
        };
    });
}

function _renderAlerts() {
    if (!_panel) return;
    const alertList = _panel.querySelector('.watchlist-alerts');
    if (!alertList) return;

    if (_alerts.length === 0) {
        alertList.innerHTML = '<div class="wl-empty">No alerts</div>';
        return;
    }

    alertList.innerHTML = _alerts.slice().reverse().map(a => {
        const time = new Date(a.timestamp * 1000).toLocaleTimeString();
        const typeClass = a.type === 'movement' ? 'wl-alert-move' : 'wl-alert-state';
        return `
            <div class="wl-alert ${typeClass}">
                <span class="wl-alert-time">${time}</span>
                <span class="wl-alert-target">${a.target_id}</span>
                <span class="wl-alert-detail">${a.details}</span>
            </div>
        `;
    }).join('');
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function initWatchlistPanel(container) {
    _panel = document.createElement('div');
    _panel.className = 'panel-content watchlist-panel';
    _panel.innerHTML = `
        <div class="panel-header">TARGET WATCH LIST</div>
        <div class="watchlist-entries"></div>
        <div class="wl-add-section">
            <input type="text" class="wl-add-input" placeholder="Target ID to watch...">
            <button class="wl-add-btn">+ Watch</button>
        </div>
        <div class="panel-header wl-alerts-header">ALERTS</div>
        <div class="watchlist-alerts"></div>
    `;
    container.appendChild(_panel);

    // Add target button
    const addBtn = _panel.querySelector('.wl-add-btn');
    const addInput = _panel.querySelector('.wl-add-input');
    addBtn.onclick = () => {
        const val = addInput.value.trim();
        if (val) {
            _addTarget(val);
            addInput.value = '';
        }
    };
    addInput.onkeydown = (e) => {
        if (e.key === 'Enter') addBtn.click();
    };

    // Listen for context menu "watch target" events
    EventBus.on('watchlist:add', (data) => {
        if (data && data.target_id) {
            _addTarget(data.target_id, data.label);
        }
    });

    _fetchEntries();
    _fetchAlerts();

    // Periodic refresh
    _refreshTimer = setInterval(() => {
        _fetchEntries();
        _fetchAlerts();
    }, 5000);

    return _panel;
}

// PanelDef for PanelManager registration
export const WatchlistPanelDef = {
    id: 'watchlist',
    title: 'WATCH LIST',
    label: 'WATCH LIST',
    icon: '\uD83D\uDC41',
    group: 'intel',
    init(container) { return initWatchlistPanel(container); },
    destroy() { destroyWatchlistPanel(); },
};

export function destroyWatchlistPanel() {
    if (_refreshTimer) {
        clearInterval(_refreshTimer);
        _refreshTimer = null;
    }
    if (_panel && _panel.parentNode) {
        _panel.parentNode.removeChild(_panel);
    }
    _panel = null;
}
