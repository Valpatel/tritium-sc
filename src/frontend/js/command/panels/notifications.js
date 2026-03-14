// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Notifications Panel
// Bell icon with unread count badge, dropdown showing notification cards
// with severity colors. Click to navigate to related entity.
// Subscribes to: WebSocket notification:new events

import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

const SEVERITY_COLORS = {
    critical: '#ff2a6d',
    warning:  '#fcee0a',
    info:     '#00f0ff',
};

const SEVERITY_LABELS = {
    critical: 'CRITICAL',
    warning:  'WARNING',
    info:     'INFO',
};

export const NotificationsPanelDef = {
    id: 'notifications',
    title: 'NOTIFICATIONS',
    defaultPosition: { x: null, y: 44 },
    defaultSize: { w: 320, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'notifications-panel-inner';
        el.innerHTML = `
            <div class="panel-section-label" style="display:flex;justify-content:space-between;align-items:center">
                <span>
                    <span class="notif-bell" title="Notifications">&#x1F514;</span>
                    <span data-bind="count" class="notif-badge">0</span> UNREAD
                </span>
                <button class="panel-action-btn" data-action="mark-all" title="Mark all as read">MARK ALL READ</button>
            </div>
            <ul class="panel-list notif-list" data-bind="feed" role="log" aria-label="Notification feed" aria-live="polite">
                <li class="panel-empty">No notifications</li>
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
        const markAllBtn = bodyEl.querySelector('[data-action="mark-all"]');

        let notifications = [];

        function render() {
            if (!feedEl) return;
            const unread = notifications.filter(n => !n.read).length;
            if (countEl) {
                countEl.textContent = unread;
                countEl.style.background = unread > 0 ? '#ff2a6d' : '';
                countEl.style.color = unread > 0 ? '#fff' : '';
            }

            if (notifications.length === 0) {
                feedEl.innerHTML = '<li class="panel-empty">No notifications</li>';
                return;
            }

            feedEl.innerHTML = notifications.slice(0, 50).map(n => {
                const color = SEVERITY_COLORS[n.severity] || SEVERITY_COLORS.info;
                const label = SEVERITY_LABELS[n.severity] || 'INFO';
                const time = n.timestamp
                    ? new Date(n.timestamp * 1000).toLocaleTimeString().substring(0, 8)
                    : '';
                const readClass = n.read ? 'notif-read' : 'notif-unread';
                const entityAttr = n.entity_id ? `data-entity="${_esc(n.entity_id)}"` : '';
                return `<li class="panel-list-item notif-card ${readClass}" data-notif-id="${_esc(n.id)}" ${entityAttr}
                            style="cursor:pointer;border-left:3px solid ${color};margin-bottom:4px;padding:4px 6px">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="font-size:0.65rem;font-weight:bold;color:${color}">${label}</span>
                        <span class="panel-stat-value" style="font-size:0.45rem;color:var(--text-ghost)">${time}</span>
                    </div>
                    <div style="font-size:0.6rem;font-weight:bold;margin:2px 0">${_esc(n.title)}</div>
                    <div style="font-size:0.55rem;color:var(--text-ghost);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(n.message)}</div>
                    <div style="font-size:0.45rem;color:var(--text-ghost);margin-top:2px">Source: ${_esc(n.source)}</div>
                </li>`;
            }).join('');
        }

        // Click handler: mark read + navigate to entity
        feedEl.addEventListener('click', async (e) => {
            const card = e.target.closest('[data-notif-id]');
            if (!card) return;

            const nid = card.dataset.notifId;
            const entityId = card.dataset.entity;

            // Mark read locally
            const notif = notifications.find(n => n.id === nid);
            if (notif && !notif.read) {
                notif.read = true;
                render();
                // Mark read on server
                try {
                    await fetch('/api/notifications/read', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ notification_id: nid }),
                    });
                } catch (_) { /* best effort */ }
            }

            // Navigate to entity if available
            if (entityId) {
                EventBus.emit('entity:navigate', { id: entityId });
            }
        });

        // Mark all read
        if (markAllBtn) {
            markAllBtn.addEventListener('click', async () => {
                notifications.forEach(n => { n.read = true; });
                render();
                try {
                    await fetch('/api/notifications/read', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({}),
                    });
                } catch (_) { /* best effort */ }
            });
        }

        // Load existing notifications
        async function loadNotifications() {
            try {
                const resp = await fetch('/api/notifications?limit=100');
                if (resp.ok) {
                    notifications = await resp.json();
                    render();
                }
            } catch (_) { /* offline */ }
        }

        loadNotifications();

        // Listen for new notifications via WebSocket
        const unsubNew = EventBus.on('notification:new', (data) => {
            // Prepend new notification
            notifications.unshift(data);
            if (notifications.length > 200) notifications.pop();
            render();
        });

        panel._unsubs.push(unsubNew);

        // Re-fetch on reconnect
        const unsubWs = EventBus.on('ws:connected', () => {
            loadNotifications();
        });
        panel._unsubs.push(unsubWs);
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
