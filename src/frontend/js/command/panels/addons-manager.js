// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Addons Manager Panel — Blender-style extensions panel for Tritium SC.
//
// Lists all discovered addons with enable/disable toggles, health status,
// category badges, and version info. Fetches from /api/addons/ and posts
// enable/disable to /api/addons/{id}/enable and /api/addons/{id}/disable.

import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';
import { reloadAddon, discoverAddons } from '../addon-loader.js';

const POLL_INTERVAL_MS = 10000;

const CATEGORY_COLORS = {
    sensor:        '#00f0ff',
    intelligence:  '#ff2a6d',
    communication: '#05ffa1',
    visualization: '#fcee0a',
    integration:   '#b060ff',
    simulation:    '#ff8800',
    security:      '#ff4444',
    ai:            '#ff2a6d',
    system:        '#8888cc',
};

const CATEGORY_ICONS = {
    sensor:        '\u25C9',  // fisheye
    intelligence:  '\u2736',  // six-pointed star
    communication: '\u2637',  // trigram
    visualization: '\u25A3',  // white square containing small black square
    integration:   '\u2B21',  // white hexagon
    simulation:    '\u2338',  // apl quad equal
    security:      '\u2622',  // radioactive
    ai:            '\u2699',  // gear
    system:        '\u2699',  // gear
};

function _catColor(cat) {
    return CATEGORY_COLORS[(cat || '').toLowerCase()] || '#888';
}

function _catIcon(cat) {
    return CATEGORY_ICONS[(cat || '').toLowerCase()] || '\u2B22';
}

function _healthDot(addon) {
    if (addon.error) return '<span class="addmgr-dot addmgr-dot-red" title="Error"></span>';
    if (addon.crash_count > 0) return '<span class="addmgr-dot addmgr-dot-yellow" title="Degraded"></span>';
    if (addon.enabled) return '<span class="addmgr-dot addmgr-dot-green" title="Healthy"></span>';
    return '<span class="addmgr-dot addmgr-dot-off" title="Disabled"></span>';
}

function _renderAddonCard(addon, manifest) {
    const id = _esc(addon.id || '');
    const name = _esc(addon.name || addon.id || 'Unknown');
    const version = _esc(addon.version || '0.0.0');
    const desc = _esc(addon.description || 'No description');
    const cat = (addon.category || 'system').toLowerCase();
    const enabled = addon.enabled;
    const hasError = addon.error;
    const errorMsg = _esc(addon.error || '');
    const catColor = _catColor(cat);
    const catIcon = _catIcon(cat);

    // Get panels from manifest
    const panels = (manifest && manifest.panels) || [];
    const layers = (manifest && manifest.layers) || [];

    const cardClass = enabled
        ? (hasError ? 'addmgr-card addmgr-card-error' : 'addmgr-card addmgr-card-enabled')
        : 'addmgr-card addmgr-card-disabled';

    // Panel quick-open buttons
    let panelButtons = '';
    if (enabled && panels.length > 0) {
        panelButtons = `<div class="addmgr-panels">
            ${panels.map(p => {
                const panelId = _esc(p.id || p.file?.replace('.js', '') || '');
                const panelTitle = _esc(p.title || panelId);
                return `<button class="addmgr-panel-btn" data-open-panel="${panelId}" title="Open ${panelTitle}">${panelTitle}</button>`;
            }).join('')}
        </div>`;
    }

    // Layer info
    let layerInfo = '';
    if (layers.length > 0) {
        layerInfo = `<span class="addmgr-layer-count" title="${layers.map(l => l.label || l.id).join(', ')}">${layers.length} layer${layers.length > 1 ? 's' : ''}</span>`;
    }

    return `<div class="${cardClass}" data-addon-id="${id}">
        <div class="addmgr-card-row">
            <span class="addmgr-icon" style="color:${catColor}">${catIcon}</span>
            <div class="addmgr-info">
                <div class="addmgr-name-row">
                    <span class="addmgr-name">${name}</span>
                    <span class="addmgr-version">v${version}</span>
                    ${_healthDot(addon)}
                </div>
                <div class="addmgr-desc">${desc}</div>
                ${hasError ? `<div class="addmgr-error">${errorMsg}</div>` : ''}
                ${panelButtons}
            </div>
            <div class="addmgr-actions">
                <label class="addmgr-toggle" title="${enabled ? 'Disable' : 'Enable'}">
                    <input type="checkbox" data-toggle="${id}" ${enabled ? 'checked' : ''}>
                    <span class="addmgr-toggle-slider"></span>
                </label>
            </div>
        </div>
        <div class="addmgr-card-footer">
            <span class="addmgr-badge" style="border-color:${catColor};color:${catColor}">${_esc(cat)}</span>
            ${layerInfo}
            <button class="addmgr-reload-btn" data-reload="${id}" title="Hot-reload this addon (re-read code + manifest)">RELOAD</button>
            <button class="addmgr-open-all-btn" data-open-all="${id}" title="Open all panels for this addon"${enabled ? '' : ' disabled'}>OPEN ALL</button>
        </div>
    </div>`;
}

function _injectStyles() {
    if (document.getElementById('addmgr-styles')) return;
    const style = document.createElement('style');
    style.id = 'addmgr-styles';
    style.textContent = `
        .addmgr-wrap {
            display: flex;
            flex-direction: column;
            height: 100%;
            font-family: 'Share Tech Mono', 'Fira Code', monospace;
        }
        .addmgr-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 12px;
            border-bottom: 1px solid #00f0ff33;
            flex-shrink: 0;
        }
        .addmgr-header-title {
            font-size: 0.8rem;
            color: #00f0ff;
            font-weight: bold;
            letter-spacing: 0.05em;
            text-shadow: 0 0 6px #00f0ff44;
        }
        .addmgr-header-count {
            font-size: 0.7rem;
            color: #888;
        }
        .addmgr-search {
            padding: 6px 12px;
            flex-shrink: 0;
        }
        .addmgr-search input {
            width: 100%;
            background: #0a0a0f;
            border: 1px solid #00f0ff33;
            color: #ccc;
            padding: 4px 8px;
            font-size: 0.7rem;
            border-radius: 2px;
            outline: none;
            font-family: inherit;
            box-sizing: border-box;
        }
        .addmgr-search input:focus {
            border-color: #00f0ff88;
            box-shadow: 0 0 4px #00f0ff22;
        }
        .addmgr-list {
            flex: 1;
            overflow-y: auto;
            padding: 4px 8px;
            min-height: 0;
        }
        .addmgr-card {
            background: #0e0e14;
            border: 1px solid #1a1a2e;
            border-radius: 3px;
            margin-bottom: 6px;
            padding: 8px 10px 6px;
            transition: border-color 0.2s, opacity 0.2s, box-shadow 0.2s;
        }
        .addmgr-card-enabled {
            border-color: #00f0ff44;
            box-shadow: 0 0 8px #00f0ff11;
        }
        .addmgr-card-disabled {
            opacity: 0.55;
            border-color: #1a1a2e;
        }
        .addmgr-card-error {
            border-color: #ff4444aa;
            box-shadow: 0 0 8px #ff444422;
        }
        .addmgr-card:hover {
            border-color: #00f0ff66;
        }
        .addmgr-card-row {
            display: flex;
            align-items: flex-start;
            gap: 8px;
        }
        .addmgr-icon {
            font-size: 0.6rem;
            line-height: 1;
            flex-shrink: 0;
            margin-top: 2px;
        }
        .addmgr-info {
            flex: 1;
            min-width: 0;
        }
        .addmgr-name-row {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .addmgr-name {
            font-size: 0.75rem;
            color: #eee;
            font-weight: bold;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .addmgr-version {
            font-size: 0.6rem;
            color: #666;
            flex-shrink: 0;
        }
        .addmgr-desc {
            font-size: 0.65rem;
            color: #888;
            margin-top: 2px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .addmgr-error {
            font-size: 0.6rem;
            color: #ff4444;
            margin-top: 2px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .addmgr-actions {
            flex-shrink: 0;
            display: flex;
            align-items: center;
        }
        /* Toggle switch */
        .addmgr-toggle {
            position: relative;
            display: inline-block;
            width: 36px;
            height: 18px;
            cursor: pointer;
        }
        .addmgr-toggle input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        .addmgr-toggle-slider {
            position: absolute;
            inset: 0;
            background: #1a1a2e;
            border-radius: 9px;
            border: 1px solid #333;
            transition: background 0.2s, border-color 0.2s;
        }
        .addmgr-toggle-slider::before {
            content: '';
            position: absolute;
            width: 12px;
            height: 12px;
            left: 2px;
            bottom: 2px;
            background: #555;
            border-radius: 50%;
            transition: transform 0.2s, background 0.2s, box-shadow 0.2s;
        }
        .addmgr-toggle input:checked + .addmgr-toggle-slider {
            background: #00f0ff22;
            border-color: #00f0ff88;
        }
        .addmgr-toggle input:checked + .addmgr-toggle-slider::before {
            transform: translateX(18px);
            background: #00f0ff;
            box-shadow: 0 0 6px #00f0ff88;
        }
        /* Health dots */
        .addmgr-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .addmgr-dot-green {
            background: #05ffa1;
            box-shadow: 0 0 4px #05ffa188;
        }
        .addmgr-dot-yellow {
            background: #fcee0a;
            box-shadow: 0 0 4px #fcee0a88;
        }
        .addmgr-dot-red {
            background: #ff4444;
            box-shadow: 0 0 4px #ff444488;
        }
        .addmgr-dot-off {
            background: #444;
        }
        /* Card footer */
        .addmgr-card-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 6px;
            padding-top: 4px;
            border-top: 1px solid #ffffff08;
        }
        .addmgr-badge {
            font-size: 0.6rem;
            border: 1px solid;
            border-radius: 2px;
            padding: 1px 5px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }
        /* Panel quick-open buttons */
        .addmgr-panels {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 6px;
        }
        .addmgr-panel-btn {
            font-size: 0.65rem;
            font-family: inherit;
            background: rgba(0, 240, 255, 0.06);
            border: 1px solid rgba(0, 240, 255, 0.2);
            border-radius: 3px;
            color: #00f0ff;
            padding: 3px 8px;
            cursor: pointer;
            transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .addmgr-panel-btn:hover {
            background: rgba(0, 240, 255, 0.15);
            border-color: #00f0ff88;
            box-shadow: 0 0 6px rgba(0, 240, 255, 0.2);
        }
        .addmgr-open-all-btn {
            font-size: 0.6rem;
            font-family: inherit;
            background: rgba(5, 255, 161, 0.08);
            border: 1px solid rgba(5, 255, 161, 0.25);
            border-radius: 2px;
            color: #05ffa1;
            padding: 2px 8px;
            cursor: pointer;
            transition: background 0.15s, box-shadow 0.15s;
        }
        .addmgr-open-all-btn:hover {
            background: rgba(5, 255, 161, 0.18);
            box-shadow: 0 0 6px rgba(5, 255, 161, 0.2);
        }
        .addmgr-open-all-btn:disabled {
            opacity: 0.3;
            cursor: not-allowed;
        }
        .addmgr-layer-count {
            font-size: 0.6rem;
            color: #888;
            cursor: help;
        }
        .addmgr-reload-btn {
            font-size: 0.6rem;
            font-family: inherit;
            background: rgba(252, 238, 10, 0.08);
            border: 1px solid rgba(252, 238, 10, 0.25);
            border-radius: 2px;
            color: #fcee0a;
            padding: 2px 8px;
            cursor: pointer;
            transition: background 0.15s, box-shadow 0.15s;
        }
        .addmgr-reload-btn:hover {
            background: rgba(252, 238, 10, 0.18);
            box-shadow: 0 0 6px rgba(252, 238, 10, 0.2);
        }
        .addmgr-reload-btn:disabled {
            opacity: 0.4;
            cursor: wait;
        }
        /* Footer link */
        .addmgr-footer {
            padding: 8px 12px;
            border-top: 1px solid #00f0ff22;
            text-align: center;
            flex-shrink: 0;
        }
        .addmgr-footer a {
            font-size: 0.65rem;
            color: #00f0ff88;
            text-decoration: none;
            cursor: pointer;
        }
        .addmgr-footer a:hover {
            color: #00f0ff;
            text-decoration: underline;
        }
        .addmgr-empty {
            color: #555;
            text-align: center;
            padding: 30px 10px;
            font-size: 0.7rem;
        }
    `;
    document.head.appendChild(style);
}


export const AddonsManagerPanelDef = {
    id: 'addons-manager',
    title: 'ADDONS MANAGER',
    defaultPosition: { x: 200, y: 100 },
    defaultSize: { w: 500, h: 600 },

    create(panel) {
        _injectStyles();
        const el = document.createElement('div');
        el.className = 'addmgr-wrap';
        el.innerHTML = `
            <div class="addmgr-header">
                <span class="addmgr-header-title">ADDONS MANAGER</span>
                <span class="addmgr-header-count" data-bind="count"></span>
            </div>
            <div class="addmgr-search">
                <input type="text" placeholder="Filter addons..." data-bind="filter">
            </div>
            <div class="addmgr-list" data-bind="list"></div>
            <div class="addmgr-footer">
                <a data-action="discover">Scan for new addons</a>
                <span style="margin:0 6px;color:#333;">|</span>
                <a data-action="restart-server" style="color:#fcee0a88;">Restart Server</a>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        let addons = [];
        let manifests = {};  // id → manifest data (panels, layers, shortcuts)
        let filterText = '';
        const listEl = bodyEl.querySelector('[data-bind="list"]');
        const countEl = bodyEl.querySelector('[data-bind="count"]');
        const filterInput = bodyEl.querySelector('[data-bind="filter"]');

        async function fetchAddons() {
            try {
                // Fetch addon list and manifests in parallel
                const [addonsResp, manifestsResp] = await Promise.all([
                    fetch('/api/addons/'),
                    fetch('/api/addons/manifests'),
                ]);

                if (addonsResp.ok) {
                    const data = await addonsResp.json();
                    addons = data.addons || [];
                }

                if (manifestsResp.ok) {
                    const mList = await manifestsResp.json();
                    manifests = {};
                    for (const m of (Array.isArray(mList) ? mList : [])) {
                        if (m.id) manifests[m.id] = m;
                    }
                }

                render();
            } catch (e) {
                console.warn('[AddonsManager] Fetch failed:', e);
                if (addons.length === 0) {
                    listEl.innerHTML = '<div class="addmgr-empty">Failed to load addons</div>';
                }
            }
        }

        function render() {
            const filtered = filterText
                ? addons.filter(a => {
                    const text = `${a.id} ${a.name} ${a.description} ${a.category}`.toLowerCase();
                    return text.includes(filterText.toLowerCase());
                })
                : addons;

            const total = addons.length;
            const enabled = addons.filter(a => a.enabled).length;
            countEl.textContent = `${enabled} / ${total} enabled`;

            if (filtered.length === 0) {
                listEl.innerHTML = filterText
                    ? '<div class="addmgr-empty">No addons match filter</div>'
                    : '<div class="addmgr-empty">No addons discovered</div>';
                return;
            }

            // Sort: enabled first, then alphabetical
            const sorted = [...filtered].sort((a, b) => {
                if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;
                return (a.name || a.id || '').localeCompare(b.name || b.id || '');
            });

            listEl.innerHTML = sorted.map(a => _renderAddonCard(a, manifests[a.id])).join('');
        }

        async function toggleAddon(addonId, shouldEnable) {
            const action = shouldEnable ? 'enable' : 'disable';
            try {
                const resp = await fetch(`/api/addons/${encodeURIComponent(addonId)}/${action}`, {
                    method: 'POST',
                });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const result = await resp.json();
                if (result.error) {
                    EventBus.emit('toast:show', {
                        message: `Failed to ${action} ${addonId}: ${result.error}`,
                        type: 'alert',
                    });
                } else {
                    EventBus.emit('toast:show', {
                        message: `Addon "${addonId}" ${action}d`,
                        type: 'info',
                    });
                }
                // Refresh the list
                await fetchAddons();
            } catch (e) {
                console.error(`[AddonsManager] Toggle ${action} failed:`, e);
                EventBus.emit('toast:show', {
                    message: `Failed to ${action} ${addonId}`,
                    type: 'alert',
                });
                // Re-fetch to reset toggle state
                await fetchAddons();
            }
        }

        // Event delegation for toggle switches
        bodyEl.addEventListener('change', (e) => {
            const toggle = e.target.closest('[data-toggle]');
            if (toggle) {
                const addonId = toggle.dataset.toggle;
                const shouldEnable = toggle.checked;
                toggleAddon(addonId, shouldEnable);
            }
        });

        // Event delegation for clicks
        bodyEl.addEventListener('click', (e) => {
            // Open a single addon panel
            const panelBtn = e.target.closest('[data-open-panel]');
            if (panelBtn) {
                const panelId = panelBtn.dataset.openPanel;
                EventBus.emit('panel:request-open', { id: panelId });
                return;
            }

            // Open ALL panels for an addon
            const openAllBtn = e.target.closest('[data-open-all]');
            if (openAllBtn) {
                const addonId = openAllBtn.dataset.openAll;
                const manifest = manifests[addonId];
                if (manifest && manifest.panels) {
                    for (const p of manifest.panels) {
                        const pid = p.id || p.file?.replace('.js', '') || '';
                        if (pid) EventBus.emit('panel:request-open', { id: pid });
                    }
                    EventBus.emit('toast:show', {
                        message: `Opened ${manifest.panels.length} panel(s) for ${addonId}`,
                        type: 'info',
                    });
                }
                return;
            }

            // Reload addon (hot-reload backend + frontend)
            const reloadBtn = e.target.closest('[data-reload]');
            if (reloadBtn) {
                const addonId = reloadBtn.dataset.reload;
                reloadBtn.disabled = true;
                reloadBtn.textContent = 'RELOADING...';
                const ok = await reloadAddon(addonId);
                EventBus.emit('toast:show', {
                    message: ok ? `Addon "${addonId}" reloaded` : `Reload failed for "${addonId}"`,
                    type: ok ? 'info' : 'alert',
                });
                reloadBtn.disabled = false;
                reloadBtn.textContent = 'RELOAD';
                await fetchAddons();
                return;
            }

            // Restart server (for route changes that need full restart)
            if (e.target.closest('[data-action="restart-server"]')) {
                if (!confirm('Restart the server? The page will reconnect automatically.')) return;
                fetch('/api/server/restart', { method: 'POST' }).then(() => {
                    EventBus.emit('toast:show', { message: 'Server restarting...', type: 'info' });
                    let attempts = 0;
                    const check = setInterval(async () => {
                        attempts++;
                        try {
                            const r = await fetch('/api/server/status');
                            if (r.ok) { clearInterval(check); location.reload(); }
                        } catch (_) {}
                        if (attempts > 30) { clearInterval(check); location.reload(); }
                    }, 1000);
                }).catch(() => EventBus.emit('toast:show', { message: 'Restart failed', type: 'alert' }));
                return;
            }

            // Discover new addons (scan directories)
            if (e.target.closest('[data-action="discover"]')) {
                e.target.textContent = 'Scanning...';
                const newIds = await discoverAddons();
                if (newIds.length > 0) {
                    EventBus.emit('toast:show', {
                        message: `Found ${newIds.length} new addon(s): ${newIds.join(', ')}`,
                        type: 'info',
                    });
                } else {
                    EventBus.emit('toast:show', {
                        message: 'No new addons found',
                        type: 'info',
                    });
                }
                e.target.textContent = 'Scan for new addons';
                await fetchAddons();
            }
        });

        // Filter input
        filterInput.addEventListener('input', () => {
            filterText = filterInput.value.trim();
            render();
        });

        // Initial load + polling
        fetchAddons();
        panel._addmgrTimer = setInterval(fetchAddons, POLL_INTERVAL_MS);
    },

    unmount(bodyEl, panel) {
        if (panel._addmgrTimer) {
            clearInterval(panel._addmgrTimer);
            panel._addmgrTimer = null;
        }
    },
};
