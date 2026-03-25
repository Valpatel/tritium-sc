// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Target Timeline Panel
// Vertical timeline showing all signals for a target over time.
// Subscribes to: map.selectedUnitId, units (Map)

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


const EVENT_TYPE_CONFIG = {
    'sighting':        { label: 'SIGHTING',   color: '#00f0ff', icon: 'S', category: 'ble' },
    'detection':       { label: 'DETECTION',  color: '#05ffa1', icon: 'D', category: 'camera' },
    'geofence_enter':  { label: 'GEO ENTER',  color: '#ff2a6d', icon: '>', category: 'geofence' },
    'geofence_exit':   { label: 'GEO EXIT',   color: '#ff2a6d', icon: '<', category: 'geofence' },
    'geofence_inside': { label: 'GEO INSIDE', color: '#ff2a6d', icon: '=', category: 'geofence' },
    'enrichment':      { label: 'ENRICHMENT', color: '#fcee0a', icon: 'E', category: 'enrichment' },
    'classification':  { label: 'CLASSIFY',   color: '#fcee0a', icon: 'C', category: 'enrichment' },
    'correlation':     { label: 'CORRELATE',  color: '#b48eff', icon: 'F', category: 'correlation' },
};

const FILTER_OPTIONS = [
    { value: 'all',         label: 'ALL' },
    { value: 'ble',         label: 'BLE' },
    { value: 'camera',      label: 'CAMERA' },
    { value: 'geofence',    label: 'GEOFENCE' },
    { value: 'enrichment',  label: 'ENRICHMENT' },
    { value: 'correlation', label: 'CORRELATION' },
];

function _formatTimestamp(ts) {
    if (!ts || ts <= 0) return '--:--:--';
    const d = new Date(ts * 1000);
    if (isNaN(d.getTime())) return '--:--:--';
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

function _formatEventDetail(event) {
    const data = event.data || {};
    const type = event.event_type;

    if (type === 'sighting') {
        const speed = data.speed != null ? ` | SPD ${data.speed.toFixed(1)}` : '';
        return `POS (${(data.x || 0).toFixed(1)}, ${(data.y || 0).toFixed(1)})${speed}`;
    }
    if (type === 'detection') {
        const conf = data.confidence != null ? ` ${(data.confidence * 100).toFixed(0)}%` : '';
        return `${_esc(data.asset_type || 'unknown')}${conf} [${_esc(data.alliance || '?')}]`;
    }
    if (type.startsWith('geofence_')) {
        return `${_esc(data.zone_name || 'Zone')} (${_esc(data.zone_type || '?')})`;
    }
    if (type === 'enrichment') {
        return `${_esc(data.provider || 'unknown')}: ${_esc(data.summary || data.result || 'result')}`;
    }
    if (type === 'classification') {
        return `${_esc(data.old_alliance || '?')} -> ${_esc(data.new_alliance || '?')}`;
    }
    if (type === 'correlation') {
        return `Fused with ${_esc(data.other_target_id || '?')}`;
    }
    return JSON.stringify(data).slice(0, 80);
}

export const TimelinePanelDef = {
    id: 'timeline',
    title: 'TARGET TIMELINE',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 340, h: 500 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'timeline-panel-inner';
        el.innerHTML = `
            <div class="timeline-toolbar">
                <span class="timeline-target mono" data-bind="target-label">No target selected</span>
                <select class="timeline-filter" data-bind="filter" title="Filter by event type">
                    ${FILTER_OPTIONS.map(o =>
                        `<option value="${o.value}">${o.label}</option>`
                    ).join('')}
                </select>
                <button class="panel-action-btn" data-action="refresh" title="Refresh timeline">REFRESH</button>
            </div>
            <div class="timeline-list" data-bind="list" role="log" aria-label="Target timeline">
                <div class="panel-empty">Select a target to view timeline</div>
            </div>
            <div class="timeline-status mono" data-bind="status">0 events</div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const listEl = bodyEl.querySelector('[data-bind="list"]');
        const filterEl = bodyEl.querySelector('[data-bind="filter"]');
        const targetLabel = bodyEl.querySelector('[data-bind="target-label"]');
        const statusEl = bodyEl.querySelector('[data-bind="status"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        let currentTargetId = null;
        let allEvents = [];
        let activeFilter = 'all';
        let autoScroll = true;
        let fetchAbort = null;

        async function fetchTimeline(targetId) {
            if (!targetId) {
                allEvents = [];
                render();
                return;
            }

            // Cancel any in-flight request
            if (fetchAbort) fetchAbort.abort();
            fetchAbort = new AbortController();

            try {
                const resp = await fetch(`/api/targets/${encodeURIComponent(targetId)}/timeline?limit=500`, {
                    signal: fetchAbort.signal,
                });
                if (!resp.ok) {
                    allEvents = [];
                    render();
                    return;
                }
                const data = await resp.json();
                allEvents = data.events || [];
                if (targetLabel) {
                    const name = data.target?.name || targetId;
                    targetLabel.textContent = _esc(name).slice(0, 20);
                }
                render();
            } catch (err) {
                if (err.name !== 'AbortError') {
                    console.warn('[Timeline] fetch error:', err);
                    allEvents = [];
                    render();
                }
            }
        }

        function render() {
            if (!listEl) return;

            const filtered = activeFilter === 'all'
                ? allEvents
                : allEvents.filter(e => {
                    const cfg = EVENT_TYPE_CONFIG[e.event_type];
                    return cfg && cfg.category === activeFilter;
                });

            if (statusEl) statusEl.textContent = `${filtered.length} events`;

            if (!currentTargetId) {
                listEl.innerHTML = '<div class="panel-empty">Select a target to view timeline</div>';
                return;
            }

            if (filtered.length === 0) {
                listEl.innerHTML = '<div class="panel-empty">No events for this target</div>';
                return;
            }

            // Show last 100 for performance
            const visible = filtered.slice(-100);
            listEl.innerHTML = visible.map(e => {
                const cfg = EVENT_TYPE_CONFIG[e.event_type] || { label: '?', color: '#888', icon: '?', category: 'unknown' };
                const hasPosition = e.position && (e.position.x !== 0 || e.position.y !== 0);
                const posClass = hasPosition ? 'timeline-card-clickable' : '';
                const posData = hasPosition
                    ? `data-pos-x="${e.position.x}" data-pos-y="${e.position.y}"`
                    : '';
                return `<div class="timeline-card ${posClass}" style="border-left-color: ${cfg.color}" ${posData}>
                    <div class="timeline-card-header">
                        <span class="timeline-card-ts mono">${_formatTimestamp(e.timestamp)}</span>
                        <span class="timeline-card-badge" style="color:${cfg.color};border-color:${cfg.color}">${cfg.icon}</span>
                        <span class="timeline-card-type" style="color:${cfg.color}">${cfg.label}</span>
                    </div>
                    <div class="timeline-card-detail">${_formatEventDetail(e)}</div>
                </div>`;
            }).join('');

            if (autoScroll) listEl.scrollTop = listEl.scrollHeight;
        }

        function onTargetChange() {
            const selectedId = TritiumStore.get('map.selectedUnitId');
            if (selectedId === currentTargetId) return;
            currentTargetId = selectedId;
            if (targetLabel) {
                targetLabel.textContent = selectedId ? selectedId.slice(0, 20) : 'No target selected';
            }
            fetchTimeline(selectedId);
        }

        // Filter change
        if (filterEl) {
            filterEl.addEventListener('change', () => {
                activeFilter = filterEl.value;
                render();
            });
        }

        // Refresh button
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                if (currentTargetId) fetchTimeline(currentTargetId);
            });
        }

        // Click event card to center map on position
        if (listEl) {
            listEl.addEventListener('click', (ev) => {
                const card = ev.target.closest('.timeline-card-clickable');
                if (!card) return;
                const x = parseFloat(card.dataset.posX);
                const y = parseFloat(card.dataset.posY);
                if (!isNaN(x) && !isNaN(y)) {
                    EventBus.emit('map:center', { x, y });
                }
            });

            // Auto-scroll toggle on hover
            listEl.addEventListener('mouseenter', () => { autoScroll = false; });
            listEl.addEventListener('mouseleave', () => { autoScroll = true; listEl.scrollTop = listEl.scrollHeight; });
        }

        // Subscribe to store changes
        panel._unsubs.push(
            TritiumStore.on('map.selectedUnitId', onTargetChange),
        );

        // Cleanup filter/refresh listeners
        panel._unsubs.push(() => {
            if (filterEl) filterEl.removeEventListener('change', () => {});
            if (refreshBtn) refreshBtn.removeEventListener('click', () => {});
            if (fetchAbort) fetchAbort.abort();
        });

        // Initial render
        onTargetChange();

        // Position at right side if no saved layout
        if (panel.def.defaultPosition.x === null) {
            const cw = panel.manager.container.clientWidth || 1200;
            panel.x = cw - panel.w - 8;
            panel.y = 44;
            panel._applyTransform();
        }
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
