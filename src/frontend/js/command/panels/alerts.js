// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Alert Feed Panel
// Real-time alert feed with color-coded severity.
// Subscribes to: alerts

import { TritiumStore } from '../store.js';
import { _esc } from '/lib/utils.js';

export const AlertsPanelDef = {
    id: 'alerts',
    title: 'ALERTS',
    defaultPosition: { x: null, y: 44 },  // x calculated in mount (top-right)
    defaultSize: { w: 280, h: 320 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'alerts-panel-inner';
        el.innerHTML = `
            <div class="panel-section-label">
                <span data-bind="count">0</span> UNREAD
            </div>
            <ul class="panel-list" data-bind="feed" role="log" aria-label="Alert feed" aria-live="polite">
                <li class="panel-empty">No alerts</li>
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
        const countEl = bodyEl.querySelector('[data-bind="count"]');

        function render(alerts) {
            if (!alerts || alerts.length === 0) {
                feedEl.innerHTML = '<li class="panel-empty">No alerts</li>';
                if (countEl) countEl.textContent = '0';
                return;
            }

            const unread = alerts.filter(a => !a.read).length;
            if (countEl) countEl.textContent = unread;

            feedEl.innerHTML = alerts.slice(0, 30).map(a => {
                const dotClass = a.type === 'escalation' ? 'panel-dot-hostile'
                    : a.type === 'warning' ? 'panel-dot-unknown'
                    : 'panel-dot-neutral';
                const severityLabel = a.type === 'escalation' ? 'Threat escalation'
                    : a.type === 'warning' ? 'Warning'
                    : 'Info';
                const time = a.time
                    ? new Date(a.time).toLocaleTimeString().substr(0, 5)
                    : '';
                return `<li class="panel-list-item" style="cursor:default" title="${severityLabel}: ${_esc(a.message)}">
                    <span class="panel-dot ${dotClass}" title="${severityLabel}"></span>
                    <span style="flex:1;font-size:0.6rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(a.message)}</span>
                    <span class="panel-stat-value" style="font-size:0.45rem;color:var(--text-ghost)">${time}</span>
                </li>`;
            }).join('');
        }

        // Subscribe
        panel._unsubs.push(
            TritiumStore.on('alerts', render)
        );

        // Initial render
        render(TritiumStore.alerts);
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
