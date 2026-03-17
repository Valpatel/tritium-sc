// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// addon-loader.js — Dynamically loads addon panels from /api/addons/manifests
//
// Usage:
//   import { loadAddons } from './addon-loader.js';
//   await loadAddons(panelManager);

import { EventBus } from './events.js';

/**
 * Load all enabled addon panels and register them with the panel manager.
 * Called after core panels are registered in main.js.
 *
 * @param {import('./panel-manager.js').PanelManager} panelManager
 */
export async function loadAddons(panelManager) {
    try {
        const res = await fetch('/api/addons/manifests');
        if (!res.ok) return;
        const addons = await res.json();

        if (!Array.isArray(addons) || addons.length === 0) return;

        console.log(`%c[ADDONS] Loading ${addons.length} addon(s)`, 'color: #05ffa1');

        for (const addon of addons) {
            if (!addon.id) continue;
            await loadAddonPanels(addon, panelManager);
            registerAddonLayers(addon);
            registerAddonShortcuts(addon);
        }

        EventBus.emit('addons:loaded', { count: addons.length, ids: addons.map(a => a.id) });
    } catch (err) {
        console.warn('[ADDONS] Failed to load addons:', err);
    }
}

/**
 * Dynamically import each panel JS file from an addon and register it.
 *
 * Panel JS files are served from /addons/{addon_id}/frontend/{file}.
 * Each file must export a PanelDef object (either as default or as a named export
 * with an `id` property).
 */
async function loadAddonPanels(addon, panelManager) {
    for (const panel of addon.panels || []) {
        if (!panel.file) continue;
        try {
            const url = `/addons/${addon.id}/frontend/${panel.file}`;
            const module = await import(url);

            // Find the PanelDef: prefer default export, otherwise first export with an id
            const def = module.default || Object.values(module).find(v => v && typeof v === 'object' && v.id);
            if (def) {
                def.addonId = addon.id;
                if (!def.category) def.category = addon.category;
                panelManager.register(def);
                console.log(`[ADDONS] Registered panel: ${def.id} from ${addon.id}`);
            } else {
                console.warn(`[ADDONS] No PanelDef found in ${url}`);
            }
        } catch (err) {
            console.warn(`[ADDONS] Failed to load panel ${panel.file} from ${addon.id}:`, err);
        }
    }
}

/**
 * Emit events for each addon layer so the layer system can pick them up.
 */
function registerAddonLayers(addon) {
    for (const layer of addon.layers || []) {
        EventBus.emit('addon:layer-register', {
            addonId: addon.id,
            ...layer,
        });
    }
}

/**
 * Emit events for each addon keyboard shortcut so the shortcut system can pick them up.
 */
function registerAddonShortcuts(addon) {
    for (const shortcut of addon.shortcuts || []) {
        EventBus.emit('addon:shortcut-register', {
            addonId: addon.id,
            ...shortcut,
        });
    }
}
