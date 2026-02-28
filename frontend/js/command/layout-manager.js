// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// LayoutManager -- named layout save/recall for the panel system.
// Built-in presets (commander, observer, tactical, battle) are constants.
// User layouts persist to localStorage.
//
// Usage:
//   import { LayoutManager } from './layout-manager.js';
//   const lm = new LayoutManager(panelManager);
//   lm.apply('commander');
//   lm.saveCurrent('my-layout');

import { EventBus } from './events.js';

const STORAGE_KEY = 'tritium-user-layouts';

export class LayoutManager {
    constructor(panelManager) {
        this._pm = panelManager;
        this._userLayouts = this._loadUserLayouts();
        this._currentName = null;
    }

    // ------------------------------------------------------------------
    // Built-in layout presets (not editable by users)
    // ------------------------------------------------------------------

    static BUILTIN_LAYOUTS = {
        commander: {
            panels: {
                amy:    { x: 8,  y: -210, w: 320, h: 200, visible: true, minimized: false },
                units:  { x: 8,  y: 8,    w: 260, h: -230, visible: true, minimized: false },
                alerts: { x: -296, y: 8,  w: 280, h: 320, visible: true, minimized: false },
            },
        },
        observer: {
            panels: {
                alerts: { x: -296, y: 8, w: 280, h: 300, visible: true, minimized: false },
            },
        },
        tactical: {
            panels: {
                units:  { x: 8,  y: 8,    w: 260, h: -230, visible: true, minimized: false },
                alerts: { x: -296, y: 8,  w: 280, h: 300, visible: true, minimized: false },
            },
        },
        battle: {
            panels: {
                amy:    { x: 8,  y: -210, w: 320, h: 200, visible: true, minimized: false },
                units:  { x: 8,  y: 8,    w: 260, h: -230, visible: true, minimized: false },
                alerts: { x: -296, y: 8,  w: 280, h: 320, visible: true, minimized: false },
                game:   { x: -296, y: 340, w: 280, h: 250, visible: true, minimized: false },
            },
        },
    };

    /**
     * Get the name of the currently applied layout (or null).
     * @returns {string|null}
     */
    get currentName() {
        return this._currentName;
    }

    /**
     * Save the current panel arrangement as a named user layout.
     * @param {string} name
     */
    saveCurrent(name) {
        if (!name || typeof name !== 'string') return;
        const key = name.trim().toLowerCase();
        if (!key) return;

        const panels = {};
        for (const info of this._pm.getRegisteredPanels()) {
            const panel = this._pm.getPanel(info.id);
            if (panel) {
                panels[info.id] = {
                    x: panel.x,
                    y: panel.y,
                    w: panel.w,
                    h: panel.h,
                    visible: panel._visible,
                    minimized: panel.minimized,
                };
            } else {
                // Panel registered but not yet opened: mark as not visible
                panels[info.id] = { visible: false };
            }
        }

        this._userLayouts[key] = { panels };
        this._saveUserLayouts();
        this._currentName = key;
    }

    /**
     * Apply a named layout (built-in or user).
     * @param {string} name
     */
    apply(name) {
        const key = name.trim().toLowerCase();
        const layout = LayoutManager.BUILTIN_LAYOUTS[key] || this._userLayouts[key];
        if (!layout) {
            console.warn(`[LayoutManager] Unknown layout: ${name}`);
            return;
        }

        const container = this._pm.container;
        const cw = container ? container.clientWidth : 1200;
        const ch = container ? container.clientHeight : 700;

        // Close all panels first
        for (const id of this._pm.registeredIds()) {
            if (this._pm.isOpen(id)) {
                this._pm.close(id);
            }
        }

        // Open and position panels from the layout
        for (const [id, pos] of Object.entries(layout.panels)) {
            if (!pos.visible && pos.visible !== undefined) continue;

            const panel = this._pm.open(id);
            if (!panel) continue;

            // Resolve relative positions (negative = from right/bottom edge)
            const x = pos.x < 0 ? cw + pos.x : pos.x;
            const y = pos.y < 0 ? ch + pos.y : pos.y;
            const w = pos.w || panel.w;
            const h = pos.h < 0 ? ch + pos.h : (pos.h || panel.h);

            panel.setPosition(x, y);
            panel.setSize(w, h);

            if (pos.minimized) {
                panel.minimize();
            }

            panel._clampToBounds();
        }

        this._pm.saveLayout();
        this._currentName = key;
        EventBus.emit('layout:changed', { name: key });
    }

    /**
     * Delete a user layout. Cannot delete built-in layouts.
     * @param {string} name
     * @returns {boolean} true if deleted
     */
    delete(name) {
        const key = name.trim().toLowerCase();
        if (LayoutManager.BUILTIN_LAYOUTS[key]) {
            console.warn(`[LayoutManager] Cannot delete built-in layout: ${key}`);
            return false;
        }
        if (!this._userLayouts[key]) return false;

        delete this._userLayouts[key];
        this._saveUserLayouts();
        if (this._currentName === key) this._currentName = null;
        return true;
    }

    /**
     * List all available layouts (built-in + user).
     * @returns {Array<{name: string, builtin: boolean}>}
     */
    listAll() {
        const list = [];
        for (const name of Object.keys(LayoutManager.BUILTIN_LAYOUTS)) {
            list.push({ name, builtin: true });
        }
        for (const name of Object.keys(this._userLayouts)) {
            list.push({ name, builtin: false });
        }
        return list;
    }

    /**
     * Export a named layout as a JSON string.
     * @param {string} name
     * @returns {string|null}
     */
    exportJSON(name) {
        const key = name.trim().toLowerCase();
        const layout = LayoutManager.BUILTIN_LAYOUTS[key] || this._userLayouts[key];
        if (!layout) return null;
        return JSON.stringify({ name: key, layout }, null, 2);
    }

    /**
     * Import a layout from a JSON string.
     * @param {string} json
     * @returns {string|null} name of imported layout, or null on error
     */
    importJSON(json) {
        try {
            const data = JSON.parse(json);
            if (!data.name || !data.layout || !data.layout.panels) {
                console.error('[LayoutManager] Invalid layout JSON');
                return null;
            }
            const key = data.name.trim().toLowerCase();
            this._userLayouts[key] = data.layout;
            this._saveUserLayouts();
            return key;
        } catch (e) {
            console.error('[LayoutManager] Failed to parse layout JSON:', e);
            return null;
        }
    }

    // ------------------------------------------------------------------
    // Private: localStorage persistence
    // ------------------------------------------------------------------

    _loadUserLayouts() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return {};
            return JSON.parse(raw);
        } catch (_) {
            return {};
        }
    }

    _saveUserLayouts() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(this._userLayouts));
        } catch (_) {
            // localStorage might be full or unavailable
        }
    }
}
