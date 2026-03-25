// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Target Activity Feed Panel
// Live scrolling feed of ALL target events across all targets.
// Shows: new sightings, classification changes, geofence events,
// correlations, enrichments — like a Twitter feed for the tactical picture.

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

const MAX_FEED_ITEMS = 200;
const FEED_DISPLAY_LIMIT = 50;

// Event type styling
const EVENT_STYLES = {
    sighting:       { dot: 'panel-dot-friendly',  label: 'SIGHTING',     color: '#05ffa1' },
    classification: { dot: 'panel-dot-neutral',   label: 'CLASSIFIED',   color: '#00f0ff' },
    geofence_enter: { dot: 'panel-dot-hostile',   label: 'ZONE ENTER',   color: '#ff2a6d' },
    geofence_exit:  { dot: 'panel-dot-unknown',   label: 'ZONE EXIT',    color: '#fcee0a' },
    correlation:    { dot: 'panel-dot-neutral',   label: 'CORRELATED',   color: '#00f0ff' },
    enrichment:     { dot: 'panel-dot-neutral',   label: 'ENRICHED',     color: '#9d4edd' },
    new_target:     { dot: 'panel-dot-friendly',  label: 'NEW TARGET',   color: '#05ffa1' },
    departed:       { dot: 'panel-dot-unknown',   label: 'DEPARTED',     color: '#666' },
    threat:         { dot: 'panel-dot-hostile',   label: 'THREAT',       color: '#ff2a6d' },
    dispatch:       { dot: 'panel-dot-neutral',   label: 'DISPATCH',     color: '#00f0ff' },
    alliance_change:{ dot: 'panel-dot-hostile',   label: 'ALLIANCE',     color: '#fcee0a' },
    merge:          { dot: 'panel-dot-neutral',   label: 'MERGED',       color: '#9d4edd' },
    default:        { dot: 'panel-dot-neutral',   label: 'EVENT',        color: '#888' },
};

export const ActivityFeedPanelDef = {
    id: 'activity-feed',
    title: 'ACTIVITY FEED',
    defaultPosition: { x: null, y: 44 },
    defaultSize: { w: 340, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'activity-feed-panel';
        el.innerHTML = `
            <div class="af-toolbar" style="display:flex;align-items:center;gap:6px;padding:4px 8px;border-bottom:1px solid var(--border, #1a1a2e)">
                <input type="text" class="af-filter-input" placeholder="Filter events..." data-bind="filter"
                    style="flex:1;background:var(--surface-1, #0e0e14);border:1px solid var(--border, #1a1a2e);
                    color:var(--text, #ccc);padding:2px 6px;font-size:0.6rem;font-family:var(--font-mono);
                    border-radius:3px;outline:none">
                <label style="font-size:0.5rem;color:var(--text-ghost, #666);display:flex;align-items:center;gap:2px;cursor:pointer">
                    <input type="checkbox" data-bind="auto-scroll" checked style="margin:0;accent-color:#00f0ff"> AUTO
                </label>
                <span class="af-count mono" data-bind="count" style="font-size:0.5rem;color:var(--text-ghost, #666)">0</span>
            </div>
            <ul class="panel-list af-feed" data-bind="feed" role="log" aria-label="Target activity feed" aria-live="polite"
                style="flex:1;overflow-y:auto;margin:0;padding:0;list-style:none">
                <li class="panel-empty" style="padding:12px;text-align:center;color:var(--text-ghost, #666);font-size:0.6rem">
                    Waiting for target events...
                </li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // Position at right side
        if (panel.def.defaultPosition.x === null) {
            const cw = panel.manager.container.clientWidth || 1200;
            panel.x = cw - panel.w - 8;
            panel._applyTransform();
        }

        const feedEl = bodyEl.querySelector('[data-bind="feed"]');
        const countEl = bodyEl.querySelector('[data-bind="count"]');
        const filterInput = bodyEl.querySelector('[data-bind="filter"]');
        const autoScrollCheckbox = bodyEl.querySelector('[data-bind="auto-scroll"]');

        let feedItems = [];
        let filterText = '';
        let autoScroll = true;

        if (autoScrollCheckbox) {
            autoScrollCheckbox.addEventListener('change', () => {
                autoScroll = autoScrollCheckbox.checked;
            });
        }

        if (filterInput) {
            filterInput.addEventListener('input', () => {
                filterText = filterInput.value.toLowerCase();
                renderFeed();
            });
        }

        function addEvent(evt) {
            feedItems.unshift(evt);
            if (feedItems.length > MAX_FEED_ITEMS) {
                feedItems.length = MAX_FEED_ITEMS;
            }
            renderFeed();
        }

        function renderFeed() {
            const filtered = filterText
                ? feedItems.filter(e =>
                    (e.message || '').toLowerCase().includes(filterText) ||
                    (e.target_id || '').toLowerCase().includes(filterText) ||
                    (e.event_type || '').toLowerCase().includes(filterText))
                : feedItems;

            if (countEl) countEl.textContent = String(filtered.length);

            if (filtered.length === 0) {
                feedEl.innerHTML = '<li class="panel-empty" style="padding:12px;text-align:center;color:var(--text-ghost, #666);font-size:0.6rem">No matching events</li>';
                return;
            }

            const display = filtered.slice(0, FEED_DISPLAY_LIMIT);
            feedEl.innerHTML = display.map(e => {
                const style = EVENT_STYLES[e.event_type] || EVENT_STYLES.default;
                const time = e.time ? new Date(e.time).toLocaleTimeString().substr(0, 8) : '';
                const targetLabel = e.target_id ? `<span style="color:${style.color};font-weight:500">${_esc(e.target_id.substring(0, 16))}</span>` : '';
                return `<li class="panel-list-item af-item" style="cursor:pointer;padding:3px 8px;border-bottom:1px solid rgba(255,255,255,0.03);display:flex;align-items:flex-start;gap:4px"
                    data-target-id="${_esc(e.target_id || '')}" title="${_esc(e.message || '')}">
                    <span class="panel-dot ${style.dot}" style="margin-top:3px;flex-shrink:0"></span>
                    <div style="flex:1;min-width:0;overflow:hidden">
                        <div style="display:flex;justify-content:space-between;align-items:center">
                            <span class="af-type mono" style="font-size:0.45rem;color:${style.color};letter-spacing:0.5px">${style.label}</span>
                            <span class="mono" style="font-size:0.4rem;color:var(--text-ghost, #555)">${time}</span>
                        </div>
                        <div style="font-size:0.55rem;color:var(--text, #ccc);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                            ${targetLabel} ${_esc(e.message || '')}
                        </div>
                        ${e.detail ? `<div style="font-size:0.45rem;color:var(--text-ghost, #666);margin-top:1px">${_esc(e.detail)}</div>` : ''}
                    </div>
                </li>`;
            }).join('');

            // Click to focus target on map
            feedEl.querySelectorAll('[data-target-id]').forEach(li => {
                li.addEventListener('click', () => {
                    const tid = li.dataset.targetId;
                    if (tid) EventBus.emit('target:focus', { target_id: tid });
                });
            });

            if (autoScroll) {
                feedEl.scrollTop = 0;
            }
        }

        // Subscribe to various event bus events
        function handleTargetEvent(eventType, data) {
            addEvent({
                event_type: eventType,
                target_id: data.target_id || data.id || data.mac || '',
                message: data.message || data.text || data.description || '',
                detail: data.detail || data.source || '',
                time: data.time || data.timestamp || new Date().toISOString(),
            });
        }

        // Wire up event subscriptions
        const subscriptions = [
            EventBus.on('target:new', (d) => handleTargetEvent('new_target', {
                ...d, message: `${d.name || d.class || 'New target'} detected`,
                detail: `Source: ${d.source || 'unknown'}`
            })),
            EventBus.on('target:sighting', (d) => handleTargetEvent('sighting', {
                ...d, message: `Sighting from ${d.source || d.node_id || 'sensor'}`,
                detail: `RSSI: ${d.rssi || 'N/A'}`
            })),
            EventBus.on('target:classified', (d) => handleTargetEvent('classification', {
                ...d, message: `Classified as ${d.classification || d.class || 'unknown'}`,
                detail: d.confidence ? `Confidence: ${Math.round(d.confidence * 100)}%` : ''
            })),
            EventBus.on('target:correlated', (d) => handleTargetEvent('correlation', {
                ...d, message: `Correlated with ${d.other_id || 'another target'}`,
                detail: d.method || ''
            })),
            EventBus.on('target:enriched', (d) => handleTargetEvent('enrichment', {
                ...d, message: d.enrichment || 'Enrichment data added',
                detail: d.source || ''
            })),
            EventBus.on('target:departed', (d) => handleTargetEvent('departed', {
                ...d, message: `Target no longer visible`,
                detail: `Last seen: ${d.last_seen || 'unknown'}`
            })),
            EventBus.on('target:alliance_changed', (d) => handleTargetEvent('alliance_change', {
                ...d, message: `Alliance changed to ${d.alliance || 'unknown'}`,
            })),
            EventBus.on('target:merged', (d) => handleTargetEvent('merge', {
                ...d, message: `Merged with ${d.merged_with || 'another target'}`,
            })),
            EventBus.on('geofence:violation', (d) => handleTargetEvent('geofence_enter', {
                ...d, message: `Entered zone: ${d.zone_name || d.zone_id || 'unknown'}`,
            })),
            EventBus.on('geofence:exit', (d) => handleTargetEvent('geofence_exit', {
                ...d, message: `Exited zone: ${d.zone_name || d.zone_id || 'unknown'}`,
            })),
            EventBus.on('escalation:change', (d) => handleTargetEvent('threat', {
                ...d, message: `Threat level: ${d.level || d.threat_level || 'elevated'}`,
            })),
            EventBus.on('dispatch:sent', (d) => handleTargetEvent('dispatch', {
                ...d, message: `${d.unit_name || d.unit_id || 'Unit'} dispatched`,
                detail: d.reason || ''
            })),
            // Also listen for WebSocket-pushed target updates
            EventBus.on('ble:target_update', (d) => handleTargetEvent('sighting', {
                target_id: d.target_id || d.mac || '',
                message: `BLE update: ${d.name || d.mac || 'device'}`,
                detail: `RSSI: ${d.rssi || 'N/A'}, Class: ${d.class || 'unknown'}`
            })),
            EventBus.on('mesh:node_update', (d) => handleTargetEvent('sighting', {
                target_id: d.target_id || `mesh_${d.node_id || ''}`,
                message: `Mesh node: ${d.long_name || d.short_name || d.node_id || 'unknown'}`,
                detail: d.position ? `Lat: ${d.position.lat}, Lng: ${d.position.lng}` : ''
            })),
        ];

        panel._unsubs.push(...subscriptions);

        // Initial render
        renderFeed();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
