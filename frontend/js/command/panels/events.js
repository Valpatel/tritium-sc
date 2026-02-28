// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Events Timeline Panel
// Chronological stream of all system events with type filtering.
// Subscribes to: EventBus '*' (all events), filtered to relevant types.

import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

const EVENT_TYPES = {
    'alert:new':          { label: 'ALERT',   color: '#fcee0a', icon: '!' },
    'game:elimination':   { label: 'ELIM',    color: '#ff2a6d', icon: 'X' },
    'combat:hit':         { label: 'HIT',     color: '#ff6b35', icon: '*' },
    'game:wave_start':    { label: 'WAVE',    color: '#05ffa1', icon: 'W' },
    'game:wave_complete': { label: 'WAVE OK', color: '#05ffa1', icon: 'V' },
    'game:state':         { label: 'GAME',    color: '#00f0ff', icon: 'G' },
    'amy:thought':        { label: 'AMY',     color: '#00f0ff', icon: 'A' },
    'amy:speech':         { label: 'SPEECH',  color: '#00a0ff', icon: 'S' },
    'unit:selected':      { label: 'SELECT',  color: '#05ffa1', icon: '>' },
    'unit:dispatched':    { label: 'DISPATCH', color: '#05ffa1', icon: 'D' },
    'combat:streak':      { label: 'STREAK',  color: '#fcee0a', icon: 'K' },
    'robot:thought':      { label: 'ROBOT',   color: '#00a0ff', icon: 'R' },
};

const FILTER_OPTIONS = [
    { value: 'all', label: 'ALL' },
    { value: 'combat', label: 'COMBAT' },
    { value: 'game', label: 'GAME' },
    { value: 'amy', label: 'AMY' },
    { value: 'alert', label: 'ALERTS' },
];

const COMBAT_EVENTS = new Set(['game:elimination', 'combat:hit', 'combat:streak']);
const GAME_EVENTS = new Set(['game:wave_start', 'game:wave_complete', 'game:state']);
const AMY_EVENTS = new Set(['amy:thought', 'amy:speech']);
const ALERT_EVENTS = new Set(['alert:new']);

export const EventsPanelDef = {
    id: 'events',
    title: 'EVENTS TIMELINE',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 300, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'events-panel-inner';
        el.innerHTML = `
            <div class="events-toolbar">
                <select class="events-filter" data-bind="filter" title="Filter events by type">
                    ${FILTER_OPTIONS.map(o =>
                        `<option value="${o.value}">${o.label}</option>`
                    ).join('')}
                </select>
                <span class="events-count mono" data-bind="count">0 events</span>
                <button class="panel-action-btn" data-action="clear" title="Clear event log">CLEAR</button>
            </div>
            <ul class="panel-list events-list" data-bind="list" role="log" aria-label="Events timeline">
                <li class="panel-empty">Waiting for events...</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const listEl = bodyEl.querySelector('[data-bind="list"]');
        const filterEl = bodyEl.querySelector('[data-bind="filter"]');
        const countEl = bodyEl.querySelector('[data-bind="count"]');
        const clearBtn = bodyEl.querySelector('[data-action="clear"]');

        const MAX_EVENTS = 200;
        let events = [];
        let activeFilter = 'all';
        let autoScroll = true;

        function _matchesFilter(eventName) {
            if (activeFilter === 'all') return true;
            if (activeFilter === 'combat') return COMBAT_EVENTS.has(eventName);
            if (activeFilter === 'game') return GAME_EVENTS.has(eventName);
            if (activeFilter === 'amy') return AMY_EVENTS.has(eventName);
            if (activeFilter === 'alert') return ALERT_EVENTS.has(eventName);
            return true;
        }

        function _formatTime(d) {
            return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
        }

        function _extractText(eventName, data) {
            if (!data) return eventName;
            if (eventName === 'game:elimination') {
                return `${data.interceptor_name || '?'} >> ${data.target_name || '?'}`;
            }
            if (eventName === 'combat:hit') {
                return `Hit ${data.target_name || data.target_id || '?'} for ${data.damage || '?'} dmg`;
            }
            if (eventName === 'amy:thought') return data.text || '...';
            if (eventName === 'amy:speech') return data.text || '...';
            if (eventName === 'alert:new') return data.message || data.type || 'Alert';
            if (eventName === 'game:wave_start') return `Wave ${data.wave || data.wave_number || '?'} started`;
            if (eventName === 'game:wave_complete') return `Wave ${data.wave || data.wave_number || '?'} complete`;
            if (eventName === 'game:state') return `Phase: ${data.phase || '?'}`;
            if (eventName === 'combat:streak') return `${data.streak || '?'}x streak!`;
            if (eventName === 'robot:thought') return `${data.name || '?'}: ${data.text || '...'}`;
            if (eventName === 'unit:dispatched') return `Dispatched to (${Math.round(data.target?.x || 0)}, ${Math.round(data.target?.y || 0)})`;
            return JSON.stringify(data).slice(0, 60);
        }

        function render() {
            if (!listEl) return;
            const filtered = events.filter(e => _matchesFilter(e.event));
            if (countEl) countEl.textContent = `${filtered.length} events`;

            if (filtered.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No events matching filter</li>';
                return;
            }

            // Show last 50 for performance
            const visible = filtered.slice(-50);
            listEl.innerHTML = visible.map(e => {
                const cfg = EVENT_TYPES[e.event] || { label: '?', color: '#888', icon: '?' };
                return `<li class="events-entry">
                    <span class="events-ts mono">${_esc(e.ts)}</span>
                    <span class="events-badge" style="color:${cfg.color};border-color:${cfg.color}">${cfg.icon}</span>
                    <span class="events-text">${_esc(e.text)}</span>
                </li>`;
            }).join('');

            if (autoScroll) listEl.scrollTop = listEl.scrollHeight;
        }

        function addEvent(eventName, data) {
            if (!EVENT_TYPES[eventName]) return;
            const now = new Date();
            events.push({
                event: eventName,
                ts: _formatTime(now),
                text: _extractText(eventName, data),
                time: now.getTime(),
            });
            if (events.length > MAX_EVENTS) events.shift();
            render();
        }

        // Subscribe to all tracked event types
        const unsubs = [];
        for (const eventName of Object.keys(EVENT_TYPES)) {
            unsubs.push(EventBus.on(eventName, (data) => addEvent(eventName, data)));
        }

        // Filter change
        if (filterEl) {
            filterEl.addEventListener('change', () => {
                activeFilter = filterEl.value;
                render();
            });
        }

        // Clear button
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                events = [];
                render();
            });
        }

        // Auto-scroll toggle on hover
        if (listEl) {
            listEl.addEventListener('mouseenter', () => { autoScroll = false; });
            listEl.addEventListener('mouseleave', () => { autoScroll = true; listEl.scrollTop = listEl.scrollHeight; });
        }

        // Store unsubs for cleanup
        for (const u of unsubs) panel._unsubs.push(u);

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
