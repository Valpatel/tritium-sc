// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- Right-Click Context Menu
 *
 * Provides a context menu for the tactical map. Menu items change
 * depending on whether a unit is selected:
 *   - Unit selected: DISPATCH HERE, SUGGEST TO AMY, SET WAYPOINT, CANCEL
 *   - No unit: DROP MARKER, SUGGEST TO AMY: INVESTIGATE, CANCEL
 *
 * "Suggest to Amy" posts an operator suggestion to /api/amy/command.
 * Amy can accept, override, or ignore the suggestion (One-Straw philosophy).
 *
 * Usage from map-maplibre.js:
 *   import { ContextMenu } from './context-menu.js';
 *   ContextMenu.show(container, selectedUnitId, gameCoords, screenX, screenY);
 *   ContextMenu.hide();
 */

import { EventBus } from './events.js';

// ============================================================
// State
// ============================================================

let _menuEl = null;       // Current menu DOM element
let _keyHandler = null;   // Escape key handler reference
let _outsideHandler = null; // Click-outside dismiss handler

// ============================================================
// Menu item definitions
// ============================================================

/**
 * Return menu items based on whether a unit is selected.
 * @param {string|null} selectedUnitId
 * @returns {Array<{label: string, action: string, icon: string}>}
 */
function getMenuItems(selectedUnitId) {
    const items = [];
    if (selectedUnitId) {
        items.push({ label: 'DISPATCH HERE',  action: 'dispatch',          icon: '>' });
        items.push({ label: 'SUGGEST TO AMY', action: 'suggest_dispatch',  icon: '?' });
        items.push({ label: 'SET WAYPOINT',   action: 'waypoint',          icon: '+' });
    } else {
        items.push({ label: 'DROP MARKER',              action: 'marker',              icon: 'x' });
        items.push({ label: 'SUGGEST TO AMY: INVESTIGATE', action: 'suggest_investigate', icon: '?' });
    }
    items.push({ label: 'CANCEL', action: 'cancel', icon: '-' });
    return items;
}

// ============================================================
// Position computation
// ============================================================

/**
 * Compute menu position, flipping if near screen edge.
 * @param {number} clickX - screen X of click
 * @param {number} clickY - screen Y of click
 * @param {number} menuW  - menu width
 * @param {number} menuH  - menu height
 * @param {number} screenW - viewport width
 * @param {number} screenH - viewport height
 * @returns {{left: number, top: number}}
 */
function computePosition(clickX, clickY, menuW, menuH, screenW, screenH) {
    let left = clickX;
    let top = clickY;

    // Flip if near right edge
    if (left + menuW > screenW) {
        left = clickX - menuW;
    }
    // Flip if near bottom edge
    if (top + menuH > screenH) {
        top = clickY - menuH;
    }
    // Clamp to viewport
    if (left < 0) left = 0;
    if (top < 0) top = 0;

    return { left, top };
}

// ============================================================
// Suggest command builders
// ============================================================

/**
 * Build a natural language suggestion string for Amy's chat endpoint.
 * @param {string} type - 'dispatch' or 'investigate'
 * @param {string|null} unitId
 * @param {{x: number, y: number}} pos - game coordinates
 * @returns {string}
 */
function buildSuggestCommand(type, unitId, pos) {
    const x = Math.round(pos.x);
    const y = Math.round(pos.y);
    if (type === 'dispatch' && unitId) {
        return `Operator suggests: dispatch unit ${unitId} to position (${x}, ${y})`;
    }
    return `Operator suggests: investigate position (${x}, ${y})`;
}

// ============================================================
// Action handler
// ============================================================

/**
 * Handle a menu action.
 * @param {string} action
 * @param {{x: number, y: number}} gamePos - game coordinates
 * @param {string|null} selectedUnitId
 */
function handleAction(action, gamePos, selectedUnitId) {
    switch (action) {
        case 'dispatch':
            if (selectedUnitId) {
                EventBus.emit('unit:dispatch', {
                    unitId: selectedUnitId,
                    target: { x: gamePos.x, y: gamePos.y },
                });
                fetch('/api/amy/command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: 'dispatch',
                        params: [selectedUnitId, gamePos.x, gamePos.y],
                    }),
                }).then(resp => {
                    if (resp.ok) {
                        EventBus.emit('toast:show', { message: 'Dispatch command sent', type: 'info' });
                    } else {
                        EventBus.emit('toast:show', { message: 'Dispatch failed: server error', type: 'alert' });
                    }
                }).catch(() => {
                    EventBus.emit('toast:show', { message: 'Dispatch failed: network error', type: 'alert' });
                });
            }
            break;

        case 'waypoint':
            EventBus.emit('map:waypoint', {
                x: gamePos.x,
                y: gamePos.y,
                unitId: selectedUnitId,
            });
            if (selectedUnitId) {
                // Use the same Lua dispatch command as DISPATCH HERE —
                // the NPC action endpoint requires a control lock and
                // doesn't actually apply waypoints to unit movement.
                fetch('/api/amy/command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: 'dispatch',
                        params: [selectedUnitId, gamePos.x, gamePos.y],
                    }),
                }).then(resp => {
                    if (resp.ok) {
                        EventBus.emit('toast:show', { message: 'Waypoint set', type: 'info' });
                    } else {
                        EventBus.emit('toast:show', { message: 'Waypoint failed: server error', type: 'alert' });
                    }
                }).catch(() => {
                    EventBus.emit('toast:show', { message: 'Failed to set waypoint: network error', type: 'alert' });
                });
            }
            break;

        case 'marker':
            EventBus.emit('map:marker', {
                x: gamePos.x,
                y: gamePos.y,
            });
            break;

        case 'suggest_dispatch': {
            const text = buildSuggestCommand('dispatch', selectedUnitId, gamePos);
            fetch('/api/amy/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            }).then(resp => {
                if (resp.ok) {
                    EventBus.emit('toast:show', {
                        message: 'Suggestion sent to Amy',
                        type: 'info',
                    });
                } else {
                    EventBus.emit('toast:show', {
                        message: 'Amy rejected suggestion',
                        type: 'alert',
                    });
                }
            }).catch(() => {
                EventBus.emit('toast:show', {
                    message: 'Failed to send suggestion',
                    type: 'alert',
                });
            });
            break;
        }

        case 'suggest_investigate': {
            const text = buildSuggestCommand('investigate', null, gamePos);
            fetch('/api/amy/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            }).then(resp => {
                if (resp.ok) {
                    EventBus.emit('toast:show', {
                        message: 'Suggestion sent to Amy',
                        type: 'info',
                    });
                } else {
                    EventBus.emit('toast:show', {
                        message: 'Amy rejected suggestion',
                        type: 'alert',
                    });
                }
            }).catch(() => {
                EventBus.emit('toast:show', {
                    message: 'Failed to send suggestion',
                    type: 'alert',
                });
            });
            break;
        }

        case 'cancel':
            // No-op — menu is hidden by the caller
            break;
    }
}

// ============================================================
// DOM creation
// ============================================================

/**
 * Create the context menu DOM element, append it to container, and
 * wire up click handlers. Hides any existing menu first.
 *
 * @param {HTMLElement} container - parent element to append menu to
 * @param {string|null} selectedUnitId
 * @param {{x: number, y: number}} gamePos - game coordinates of click
 * @param {number} screenX - screen X of click (relative to viewport)
 * @param {number} screenY - screen Y of click (relative to viewport)
 * @returns {HTMLElement} the menu element
 */
function createMenuElement(container, selectedUnitId, gamePos, screenX, screenY) {
    // Remove existing menu
    hide();

    const items = getMenuItems(selectedUnitId);

    const menu = document.createElement('div');
    menu.className = 'map-context-menu';
    menu.style.position = 'fixed';
    menu.style.zIndex = '9999';

    // Build items
    for (const item of items) {
        const el = document.createElement('div');
        el.className = 'map-context-item';
        el.textContent = item.icon + ' ' + item.label;
        el.dataset.action = item.action;
        menu.appendChild(el);
    }

    // Click handler on items
    menu.addEventListener('click', (e) => {
        const target = e.target.closest ? e.target.closest('.map-context-item') : e.target;
        if (!target || !target.dataset || !target.dataset.action) return;
        handleAction(target.dataset.action, gamePos, selectedUnitId);
        hide();
    });

    // Compute position (estimate menu size: 200x(items*32))
    const menuW = 200;
    const menuH = items.length * 32;
    const vw = (typeof window !== 'undefined' && window.innerWidth) || 1920;
    const vh = (typeof window !== 'undefined' && window.innerHeight) || 1080;
    const pos = computePosition(screenX, screenY, menuW, menuH, vw, vh);
    menu.style.left = pos.left + 'px';
    menu.style.top = pos.top + 'px';

    // Store reference
    _menuEl = menu;

    // Escape key closes menu
    _keyHandler = (e) => {
        if (e.key === 'Escape') {
            hide();
        }
    };
    document.addEventListener('keydown', _keyHandler);

    // Click outside menu dismisses it (panels, menu bar, etc.)
    _outsideHandler = (e) => {
        if (_menuEl && !_menuEl.contains(e.target)) {
            hide();
        }
    };
    // Use setTimeout so the current right-click event doesn't immediately dismiss
    setTimeout(() => {
        document.addEventListener('mousedown', _outsideHandler);
    }, 0);

    // Append to container
    container.appendChild(menu);

    return menu;
}

// ============================================================
// Show / Hide
// ============================================================

/**
 * Show the context menu. This is the main entry point from map code.
 *
 * @param {HTMLElement} container - parent element
 * @param {string|null} selectedUnitId
 * @param {{x: number, y: number}} gamePos - game coordinates
 * @param {number} screenX
 * @param {number} screenY
 * @returns {HTMLElement}
 */
function show(container, selectedUnitId, gamePos, screenX, screenY) {
    return createMenuElement(container, selectedUnitId, gamePos, screenX, screenY);
}

/**
 * Hide and remove the current context menu.
 */
function hide() {
    if (_menuEl) {
        _menuEl.remove();
        _menuEl = null;
    }
    if (_keyHandler) {
        document.removeEventListener('keydown', _keyHandler);
        _keyHandler = null;
    }
    if (_outsideHandler) {
        document.removeEventListener('mousedown', _outsideHandler);
        _outsideHandler = null;
    }
}

/**
 * Returns true if the context menu is currently visible.
 */
function isVisible() {
    return _menuEl !== null;
}

// ============================================================
// Export
// ============================================================

export const ContextMenu = {
    getMenuItems,
    computePosition,
    buildSuggestCommand,
    handleAction,
    createMenuElement,
    show,
    hide,
    isVisible,
};
