// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// addon-loader.js — Dynamically loads addon panels from /api/addons/manifests
//
// Usage:
//   import { loadAddons } from './addon-loader.js';
//   await loadAddons(panelManager);

import { EventBus } from '/lib/events.js';

// Track loaded addon versions for cache-busting on reload
const _addonVersions = {};

/**
 * Load all enabled addon panels and register them with the panel manager.
 * Called after core panels are registered in main.js.
 *
 * @param {import('./panel-manager.js').PanelManager} panelManager
 */
export async function loadAddons(panelManager) {
    // Store panelManager ref for hot-reload
    _panelManagerRef = panelManager;

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

let _panelManagerRef = null;

/**
 * Hot-reload a single addon: tell backend to reload, then re-import frontend panels.
 *
 * @param {string} addonId
 * @returns {Promise<boolean>} true if reload succeeded
 */
export async function reloadAddon(addonId) {
    const pm = _panelManagerRef;
    if (!pm) {
        console.warn('[ADDONS] Cannot reload — panelManager not available');
        return false;
    }

    try {
        // 1. Tell backend to hot-reload (re-read manifest, purge module cache, re-enable)
        const reloadRes = await fetch(`/api/addons/${encodeURIComponent(addonId)}/reload`, { method: 'POST' });
        if (!reloadRes.ok) {
            console.error(`[ADDONS] Backend reload failed for ${addonId}`);
            return false;
        }
        const reloadData = await reloadRes.json();
        const version = reloadData.version || Date.now();
        _addonVersions[addonId] = version;

        // 2. Find open panels from this addon and close them (will re-open after)
        const panelsToReopen = [];
        // Check _panels map for panels with matching addonId
        if (pm._panels) {
            for (const [id, panel] of pm._panels.entries()) {
                const def = pm._registry?.get(id);
                if (def && def.addonId === addonId) {
                    panelsToReopen.push(id);
                }
            }
        }
        for (const pid of panelsToReopen) {
            pm.close(pid);
        }

        // 3. Re-fetch manifest for this addon
        const manifestsRes = await fetch('/api/addons/manifests');
        if (!manifestsRes.ok) return false;
        const manifests = await manifestsRes.json();
        const addon = manifests.find(a => a.id === addonId);
        if (!addon) {
            console.warn(`[ADDONS] Addon ${addonId} not in manifests after reload`);
            return false;
        }

        // 4. Re-import panels with cache-busting query string
        await loadAddonPanels(addon, pm, version);

        // 5. Re-open panels that were open before reload
        for (const pid of panelsToReopen) {
            pm.open(pid);
        }

        console.log(`%c[ADDONS] Hot-reloaded: ${addonId} (v=${version})`, 'color: #05ffa1; font-weight: bold');
        EventBus.emit('addons:reloaded', { id: addonId, version });
        return true;
    } catch (err) {
        console.error(`[ADDONS] Reload failed for ${addonId}:`, err);
        return false;
    }
}

/**
 * Discover new addons (re-scan directories) and load any new ones.
 */
export async function discoverAddons() {
    const pm = _panelManagerRef;
    if (!pm) return [];

    try {
        const res = await fetch('/api/addons/rediscover', { method: 'POST' });
        if (!res.ok) return [];
        const data = await res.json();
        const newIds = data.new_addons || [];

        // Enable and load each new addon
        for (const id of newIds) {
            await fetch(`/api/addons/${encodeURIComponent(id)}/enable`, { method: 'POST' });
        }

        // Re-fetch manifests and load new panels
        if (newIds.length > 0) {
            const manifestsRes = await fetch('/api/addons/manifests');
            if (manifestsRes.ok) {
                const manifests = await manifestsRes.json();
                for (const addon of manifests) {
                    if (newIds.includes(addon.id)) {
                        await loadAddonPanels(addon, pm);
                    }
                }
            }
        }

        return newIds;
    } catch (err) {
        console.error('[ADDONS] Discover failed:', err);
        return [];
    }
}

/**
 * Dynamically import each panel JS file from an addon and register it.
 * Uses cache-busting query param on reload so the browser fetches fresh code.
 */
async function loadAddonPanels(addon, panelManager, version = 0) {
    for (const panel of addon.panels || []) {
        if (!panel.file) continue;
        try {
            // Cache-bust: append ?v=timestamp on reload so browser doesn't serve stale module
            const cacheBust = version ? `?v=${version}` : '';
            const url = `/addons/${addon.id}/frontend/${panel.file}${cacheBust}`;
            const module = await import(url);

            // Find the PanelDef: prefer default export, otherwise first export with an id
            const def = module.default || Object.values(module).find(v => v && typeof v === 'object' && v.id);
            if (def) {
                def.addonId = addon.id;
                if (!def.category) def.category = addon.category;
                panelManager.register(def);  // Overwrites existing def with same id
                console.log(`[ADDONS] Registered panel: ${def.id} from ${addon.id}${version ? ' (reloaded)' : ''}`);
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
