// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Operator Cursors Panel — toggle panel for showing/hiding other operators'
// cursor positions on the tactical map. Wraps the cursor-sharing overlay
// with a simple enable/disable UI and connected-operator list.

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';

const POLL_MS = 3000;

function _renderCursorList() {
    const cursors = (typeof TritiumStore.getOperatorCursors === 'function')
        ? TritiumStore.getOperatorCursors()
        : [];
    if (cursors.length === 0) {
        return '<div style="color:#555;padding:12px;text-align:center;">No other operators connected</div>';
    }
    return cursors.map(c => {
        const color = c.color || '#00f0ff';
        const name = c.display_name || c.username || '?';
        const role = c.role || 'observer';
        const zoom = c.zoom != null ? `z${Math.round(c.zoom)}` : '';
        return `<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;border-left:3px solid ${color};">
            <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};"></span>
            <span style="color:${color};font-weight:bold;">${name}</span>
            <span style="color:#666;font-size:11px;">[${role}]</span>
            ${zoom ? `<span style="color:#555;font-size:10px;margin-left:auto;">${zoom}</span>` : ''}
        </div>`;
    }).join('');
}

export const OperatorCursorsPanelDef = {
    id: 'operator-cursors',
    title: 'OPERATOR CURSORS',
    defaultPosition: { x: 320, y: 120 },
    defaultSize: { w: 300, h: 260 },

    create(panel) {
        const el = document.createElement('div');
        el.style.padding = '8px';

        const enabled = TritiumStore.get('cursors.enabled') !== false;

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <label style="color:#b0b0c0;font-size:12px;cursor:pointer;">
                    <input type="checkbox" data-toggle="cursors" ${enabled ? 'checked' : ''} style="margin-right:6px;">
                    Show operator cursors on map
                </label>
            </div>
            <div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
                <div style="color:#00f0ff;font-size:11px;margin-bottom:4px;">CONNECTED OPERATORS</div>
                <div data-bind="cursor-list">${_renderCursorList()}</div>
            </div>
        `;

        const toggle = el.querySelector('[data-toggle="cursors"]');
        if (toggle) {
            toggle.addEventListener('change', () => {
                TritiumStore.set('cursors.enabled', toggle.checked);
                EventBus.emit('cursors:toggle', { enabled: toggle.checked });
            });
        }

        // Periodically refresh the operator list
        const listEl = el.querySelector('[data-bind="cursor-list"]');
        let timer = null;
        if (listEl) {
            timer = setInterval(() => {
                listEl.innerHTML = _renderCursorList();
            }, POLL_MS);
        }

        panel._cursorTimer = timer;
        return el;
    },

    destroy(panel) {
        if (panel._cursorTimer) {
            clearInterval(panel._cursorTimer);
            panel._cursorTimer = null;
        }
    },
};
