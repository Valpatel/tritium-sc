// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// MenuBar -- desktop-style dropdown menu bar for the Command Center.
// Replaces command-bar.js with FILE/VIEW/LAYOUT/MAP/HELP menus
// plus quick-access panel toggle buttons on the right side.
//
// Usage:
//   import { createMenuBar, focusSaveInput } from './menu-bar.js';
//   createMenuBar(containerEl, panelManager, layoutManager, mapActions);

import { EventBus } from '/lib/events.js';
import { toggleAdsbOverlay, isAdsbOverlayActive } from './adsb-overlay.js';


// ---------------------------------------------------------------------------
// Menu definitions (data-driven)
// ---------------------------------------------------------------------------

function _fileMenuItems(layoutManager) {
    return [
        { label: 'Addons Manager...', action: () => EventBus.emit('panel:request-open', { id: 'addons-manager' }) },
        { label: 'Settings...', action: () => EventBus.emit('panel:request-open', { id: 'setup-wizard' }) },
        { separator: true },
        { label: 'Save Layout...', shortcut: 'Ctrl+Shift+S',
          action: (bar) => focusSaveInput(bar) },
        { label: 'Export Layout JSON',
          action: (_bar, lm) => {
              const name = lm.currentName || 'default';
              const json = lm.exportJSON(name);
              if (!json) {
                  EventBus.emit('toast:show', { message: 'No layout to export', type: 'alert' });
                  return;
              }
              const blob = new Blob([json], { type: 'application/json' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url; a.download = `tritium-layout-${name}.json`; a.click();
              URL.revokeObjectURL(url);
              EventBus.emit('toast:show', { message: `Layout "${name}" exported`, type: 'info' });
          } },
        { label: 'Import Layout JSON',
          action: (_bar, lm) => {
              const input = document.createElement('input');
              input.type = 'file'; input.accept = '.json,application/json';
              input.style.display = 'none';
              input.addEventListener('change', () => {
                  const file = input.files?.[0];
                  if (!file) return;
                  const reader = new FileReader();
                  reader.onload = () => {
                      const name = lm.importJSON(reader.result);
                      if (name) { lm.apply(name); EventBus.emit('toast:show', { message: `Layout "${name}" imported`, type: 'info' }); }
                      else { EventBus.emit('toast:show', { message: 'Invalid layout file', type: 'alert' }); }
                  };
                  reader.readAsText(file); input.remove();
              });
              document.body.appendChild(input); input.click();
          } },
        { separator: true },
        { label: 'Restart Server', action: () => {
              if (!confirm('Restart the server? The page will reconnect automatically.')) return;
              fetch('/api/server/restart', { method: 'POST' })
                  .then(() => {
                      EventBus.emit('toast:show', { message: 'Server restarting...', type: 'info' });
                      // Auto-reload page after server comes back
                      let attempts = 0;
                      const check = setInterval(async () => {
                          attempts++;
                          try {
                              const r = await fetch('/api/server/status');
                              if (r.ok) { clearInterval(check); location.reload(); }
                          } catch (_) {}
                          if (attempts > 30) { clearInterval(check); location.reload(); }
                      }, 1000);
                  })
                  .catch(() => EventBus.emit('toast:show', { message: 'Restart failed', type: 'alert' }));
          } },
    ];
}

// Panel categories — group all panels into logical sections
const PANEL_CATEGORIES = {
    'Operations':     ['tactical-container', 'ops-dashboard', 'units', 'unit-inspector', 'unified-alerts', 'escalation', 'missions', 'patrol', 'zone-manager', 'sitrep', 'minimap', 'layers', 'bookmarks', 'annotations', 'watchlist', 'swarm-coordination', 'convoy', 'fleet-container', 'fleet-dashboard', 'device-manager', 'assets', 'command-history', 'edge-intelligence', 'edge-diagnostics', 'training-dashboard', 'rl-metrics', 'ar-export'],
    'Intel':          ['intelligence-container', 'search', 'dossiers', 'dossier-groups', 'graph-explorer', 'graphlings', 'timeline', 'target-compare', 'target-merge', 'heatmap', 'automation', 'analytics-panel', 'history-analytics', 'classification-override', 'dwell-monitor', 'behavioral-intelligence', 'reid-matches', 'lpr', 'fusion-dashboard', 'acoustic-intelligence', 'activity-feed', 'trail-export', 'forensics', 'enrichment', 'ontology-explorer'],
    'Sensing':        ['sensors-container', 'edge-tracker', 'camera-feeds', 'cameras', 'multi-camera', 'rf-motion', 'hackrf', 'sensors', 'sensor-health', 'wifi-fingerprint', 'indoor-positioning', 'radar-scope', 'sdr-waterfall', 'adsb-table'],
    'Communications': ['comms-container', 'meshtastic', 'tak', 'mqtt-inspector', 'federation', 'audio', 'voice-command', 'notifications', 'notification-prefs'],
    'Commander':      ['commander-container', 'amy', 'amy-conversation'],
    // Fleet merged into Operations above
    // Collaboration merged into System below
    'Map':            ['map-layer-switcher', 'map-screenshot', 'map-share', 'grid-overlay', 'floorplan', 'building-occupancy', 'weather-overlay', 'map-replay'],
    'Simulation':     ['simulation-container', 'city-sim', 'game', 'battle-stats', 'replay', 'scenarios'],
    'System':         ['system-container', 'system', 'system-health-dashboard', 'operator-activity', 'operator-cursors', 'keyboard-macros', 'security-audit', 'deployment', 'testing', 'export-scheduler', 'events', 'videos', 'quick-start', 'setup-wizard'],
};

function _viewMenuItems(panelManager) {
    const panelMap = new Map(panelManager.getRegisteredPanels().map(p => [p.id, p]));
    const items = [];

    // CLEAN MENU: Containers only + a few standalone essentials.
    // Individual panels are accessed as TABS inside containers, not separate windows.
    const menuEntries = [
        { header: 'Open Container' },
        { id: 'tactical-container',      shortcut: '' },
        { id: 'intelligence-container',  shortcut: '' },
        { id: 'sensors-container',       shortcut: '' },
        { id: 'comms-container',         shortcut: '' },
        { id: 'commander-container',     shortcut: '' },
        { id: 'simulation-container',    shortcut: '' },
        { id: 'system-container',        shortcut: '' },
        { separator: true },
        { header: 'Standalone' },
        { id: 'minimap',    shortcut: 'M' },
        { id: 'layers',     shortcut: '' },
        { id: 'camera-feeds', shortcut: '' },
        { id: 'city-sim',   shortcut: '' },
        { id: 'units',      shortcut: '2' },
        { id: 'unified-alerts', shortcut: '3' },
        { id: 'game',       shortcut: '4' },
        { id: 'search',     shortcut: '7' },
        { separator: true },
        { header: 'Tactical' },
        { id: 'sitrep',    shortcut: '' },
        { id: 'history-analytics', shortcut: '' },
        { id: 'classification-override', shortcut: '' },
        { id: 'ontology-explorer', shortcut: '' },
    ];

    for (const entry of menuEntries) {
        if (entry.separator) { items.push({ separator: true }); continue; }
        if (entry.header) { items.push({ header: entry.header }); continue; }
        const p = panelMap.get(entry.id);
        if (!p) continue;
        items.push({
            label: p.title, shortcut: entry.shortcut || '', checkable: true,
            checked: () => panelManager.isOpen(entry.id),
            action: () => panelManager.toggle(entry.id),
        });
    }

    items.push({ separator: true });
    items.push({ label: 'Hide All', action: () => {
        for (const p of panelManager.getRegisteredPanels()) if (panelManager.isOpen(p.id)) panelManager.close(p.id);
    }});
    items.push({ separator: true });
    items.push({ label: 'Fullscreen', shortcut: 'F11', action: () => {
        if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
        else document.documentElement.requestFullscreen().catch(() => {});
    }});
    return items;
}

function _layoutMenuItems(layoutManager) {
    const items = [];
    const all = layoutManager.listAll();
    for (const l of all.filter(l => l.builtin)) {
        items.push({ label: l.name.charAt(0).toUpperCase() + l.name.slice(1),
                      action: () => layoutManager.apply(l.name) });
    }
    const user = all.filter(l => !l.builtin);
    if (user.length > 0) {
        items.push({ separator: true });
        for (const l of user) {
            items.push({ label: l.name.toUpperCase(), action: () => layoutManager.apply(l.name),
                          deletable: true, onDelete: () => {
                              layoutManager.delete(l.name);
                              EventBus.emit('toast:show', { message: `Layout "${l.name}" deleted`, type: 'info' });
                          } });
        }
    }
    items.push({ separator: true });
    items.push({ label: 'Save Current...', action: (bar) => focusSaveInput(bar) });
    return items;
}

function _mapMenuItems(mapActions) {
    const s = () => mapActions.getMapState();
    return [
        // Layer browser opens the full panel with all 43 layers
        { label: 'Open Layers Window...', shortcut: 'L',
          action: () => EventBus.emit('panel:request-open', { id: 'layers' }) },
        { separator: true },
        { label: 'Show All Layers', action: () => mapActions.setAllLayers(true) },
        { label: 'Hide All Layers', action: () => mapActions.setAllLayers(false) },
        { separator: true },
        // Quick toggles for most-used layers
        { label: 'Satellite', shortcut: 'I', checkable: true, checked: () => s().showSatellite, action: () => mapActions.toggleSatellite() },
        { label: 'Buildings', shortcut: 'K', checkable: true, checked: () => s().showBuildings, action: () => mapActions.toggleBuildings() },
        { label: 'Roads', shortcut: 'G', checkable: true, checked: () => s().showRoads, action: () => mapActions.toggleRoads() },
        { label: 'Trees', checkable: true, checked: () => s().showTrees, action: () => mapActions.toggleTrees?.() },
        { label: 'Water', checkable: true, checked: () => s().showWater, action: () => mapActions.toggleWater?.() },
        { label: 'Barriers', checkable: true, checked: () => s().showBarriers, action: () => mapActions.toggleBarriers?.() },
        { label: 'Entrances', checkable: true, checked: () => s().showEntrances, action: () => mapActions.toggleEntrances?.() },
        { label: 'POIs', checkable: true, checked: () => s().showPOIs, action: () => mapActions.togglePOIs?.() },
        { label: 'Road Graph', checkable: true, checked: () => s().showRoadGraph, action: () => mapActions.toggleRoadGraph?.() },
        { label: 'City Sim', shortcut: 'J', checkable: true, checked: () => s().showCitySim, action: () => mapActions.toggleCitySim?.() },
        { label: 'Grid', checkable: true, checked: () => s().showGrid, action: () => mapActions.toggleGrid() },
        { label: 'Unit Markers', shortcut: 'U', checkable: true, checked: () => s().showUnits, action: () => mapActions.toggleUnits() },
        { label: 'GIS Intelligence', checkable: true, checked: () => s().showGeoLayers, action: () => mapActions.toggleGeoLayers() },
        { separator: true },
        // View
        { label: 'Fog of War', checkable: true, checked: () => s().showFog, action: () => mapActions.toggleFog() },
        { label: 'Prediction Cones', checkable: true, checked: () => s().showPredictionCones, action: () => mapActions.togglePredictionCones() },
        { label: 'ADS-B Aircraft', checkable: true, checked: () => isAdsbOverlayActive(), action: () => toggleAdsbOverlay() },
        { label: 'Asset Coverage', checkable: true, checked: () => s().showAssetCoverage !== false, action: () => mapActions.toggleAssetCoverage?.() },
        { label: 'Terrain', shortcut: 'H', checkable: true, checked: () => s().showTerrain, action: () => mapActions.toggleTerrain() },
        { label: '3D Mode', checkable: true, checked: () => s().tiltMode === 'tilted', action: () => mapActions.toggleTilt() },
        { separator: true },
        // Tools
        { label: 'Crosshairs', checkable: true, checked: () => {
            const el = document.getElementById('map-crosshairs');
            return el && el.style.display !== 'none';
        }, action: () => EventBus.emit('map:crosshairs', {}) },
        { separator: true },
        // Camera
        { label: 'Center on Action', shortcut: 'F', action: () => mapActions.centerOnAction() },
        { label: 'Reset Camera', action: () => mapActions.resetCamera() },
        { label: 'Zoom In', shortcut: ']', action: () => mapActions.zoomIn() },
        { label: 'Zoom Out', shortcut: '[', action: () => mapActions.zoomOut() },
    ];
}

function _gameMenuItems(mapActions) {
    return [
        { label: 'Start Demo', action: async () => {
            try {
                const res = await fetch('/api/demo/start', { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    EventBus.emit('toast:show', { message: 'Demo mode started', type: 'info' });
                    // Also start city simulation for moving vehicles/pedestrians
                    EventBus.emit('city-sim:toggle');
                } else {
                    EventBus.emit('toast:show', { message: data.error || 'Failed to start demo', type: 'alert' });
                }
            } catch (e) {
                EventBus.emit('toast:show', { message: 'Demo start failed: ' + e.message, type: 'alert' });
            }
        }},
        { label: 'Stop Demo', action: async () => {
            try {
                const res = await fetch('/api/demo/stop', { method: 'POST' });
                if (res.ok) {
                    EventBus.emit('toast:show', { message: 'Demo mode stopped', type: 'info' });
                    // Also stop city simulation
                    EventBus.emit('city-sim:stopped');
                }
            } catch (e) {
                EventBus.emit('toast:show', { message: 'Demo stop failed', type: 'alert' });
            }
        }},
        { separator: true },
        { label: 'Start Battle', shortcut: 'B',
          action: () => { if (mapActions.beginWar) mapActions.beginWar(); } },
        { separator: true },
        { label: 'Process Terrain', action: async () => {
            // Process terrain for the current map viewport
            const center = mapActions.getMapCenter ? mapActions.getMapCenter() : null;
            if (!center) {
                EventBus.emit('toast:show', { message: 'Map center not available', type: 'alert' });
                return;
            }
            EventBus.emit('toast:show', { message: 'Processing terrain...', type: 'info' });
            try {
                const res = await fetch('/api/terrain/process', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        min_lat: center.lat - 0.008,
                        min_lon: center.lng - 0.010,
                        max_lat: center.lat + 0.008,
                        max_lon: center.lng + 0.010,
                        zoom: 16,
                        fuse_osm: true,
                    }),
                });
                const data = await res.json();
                if (res.ok) {
                    EventBus.emit('toast:show', {
                        message: `Terrain: ${data.features} features processed`,
                        type: 'info',
                    });
                } else {
                    EventBus.emit('toast:show', {
                        message: data.detail || 'Terrain processing failed',
                        type: 'alert',
                    });
                }
            } catch (e) {
                EventBus.emit('toast:show', { message: 'Terrain error: ' + e.message, type: 'alert' });
            }
        }},
        { label: 'Reset Game',
          action: () => { if (mapActions.resetGame) mapActions.resetGame(); } },
    ];
}

function _helpMenuItems() {
    return [
        { label: 'Keyboard Shortcuts', shortcut: '?', action: () => {
            const overlay = document.getElementById('help-overlay');
            if (overlay) overlay.hidden = !overlay.hidden;
        }},
        { separator: true },
        { label: 'Conductor Dashboard', action: () => {
            window.open(`${window.location.protocol}//${window.location.hostname}:9000`, '_blank');
        }},
        { label: 'Submit Feedback...', action: () => {
            const text = prompt('Enter feedback or concern for the development system:');
            if (text) {
                fetch(`${window.location.protocol}//${window.location.hostname}:9000/api/goals`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text }),
                }).then(() => {
                    EventBus.emit('toast:show', { message: 'Feedback submitted to Conductor', type: 'info' });
                }).catch(() => {
                    EventBus.emit('toast:show', { message: 'Conductor not available (port 9000)', type: 'alert' });
                });
            }
        }},
        { separator: true },
        { label: 'About TRITIUM-SC', action: () => {
            EventBus.emit('toast:show', { message: 'TRITIUM-SC v0.1.0 -- Tactical Battlefield Management', type: 'info' });
        }},
    ];
}

// ---------------------------------------------------------------------------
// DOM construction
// ---------------------------------------------------------------------------

/**
 * Create the menu bar and mount it into the given container.
 * @param {HTMLElement} container
 * @param {import('./panel-manager.js').PanelManager} panelManager
 * @param {import('./layout-manager.js').LayoutManager} layoutManager
 * @param {Object} mapActions - { toggleSatellite, toggleRoads, toggleGrid, toggle3DMode,
 *   centerOnAction, resetCamera, zoomIn, zoomOut, getMapState }
 * @returns {HTMLElement} the command-bar root element
 */
export function createMenuBar(container, panelManager, layoutManager, mapActions) {
    const bar = document.createElement('div');
    bar.className = 'command-bar';
    const left = document.createElement('div');
    left.className = 'command-bar-left';
    const right = document.createElement('div');
    right.className = 'command-bar-right';

    let openMenu = null;   // currently open trigger element
    let hoverMode = false; // hover-switch enabled after first click

    const menus = [
        { label: 'FILE',   tip: 'Save and export workspace layouts', getItems: () => _fileMenuItems(layoutManager) },
        { label: 'WINDOWS', tip: 'Show or hide panels (Amy, Units, Alerts, etc.)', getItems: () => _viewMenuItems(panelManager) },
        { label: 'LAYOUT', tip: 'Switch between saved workspace layouts', getItems: () => _layoutMenuItems(layoutManager) },
        { label: 'MAP',    tip: 'Map layers, camera, and display settings', getItems: () => _mapMenuItems(mapActions) },
        { label: 'SIM',    tip: 'Start demo, launch simulations, run battles', getItems: () => _gameMenuItems(mapActions) },
        { label: 'HELP',   tip: 'Keyboard shortcuts and about info', getItems: () => _helpMenuItems() },
    ];

    // Build menu triggers
    for (const menuDef of menus) {
        const wrap = document.createElement('div');
        wrap.className = 'menu-trigger-wrap';
        wrap.style.position = 'relative';

        const trigger = document.createElement('button');
        trigger.className = 'menu-trigger';
        trigger.textContent = menuDef.label;
        if (menuDef.tip) trigger.title = menuDef.tip;

        const dropdown = document.createElement('div');
        dropdown.className = 'menu-dropdown';
        dropdown.hidden = true;

        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            if (openMenu === trigger) { _closeAll(); }
            else { _openMenu(trigger, dropdown, menuDef); }
        });
        trigger.addEventListener('mouseenter', () => {
            if (hoverMode && openMenu && openMenu !== trigger) {
                _openMenu(trigger, dropdown, menuDef);
            }
        });

        wrap.appendChild(trigger);
        wrap.appendChild(dropdown);
        left.appendChild(wrap);
    }

    // Panel search input — filters the quick-access buttons as you type
    const searchInput = document.createElement('input');
    searchInput.className = 'command-bar-search';
    searchInput.type = 'text';
    searchInput.placeholder = 'Search panels...';
    searchInput.maxLength = 32;
    searchInput.title = 'Filter panels by name (Ctrl+/)';
    searchInput.addEventListener('input', () => {
        const q = searchInput.value.trim().toLowerCase();
        for (const [id, btn] of panelButtons) {
            const def = panelManager._registry.get(id);
            const title = def ? def.title.toLowerCase() : id;
            btn.style.display = (!q || title.includes(q) || id.includes(q)) ? '' : 'none';
        }
    });
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            searchInput.value = '';
            searchInput.dispatchEvent(new Event('input'));
            searchInput.blur();
        } else if (e.key === 'Enter') {
            // Open the first visible panel
            const q = searchInput.value.trim().toLowerCase();
            if (q) {
                for (const [id, btn] of panelButtons) {
                    if (btn.style.display !== 'none') {
                        panelManager.toggle(id);
                        searchInput.value = '';
                        searchInput.dispatchEvent(new Event('input'));
                        searchInput.blur();
                        break;
                    }
                }
            }
        }
        e.stopPropagation();
    });
    right.appendChild(searchInput);

    // Panel buttons map — only populated for pinned panels (not all 90+).
    // Use VIEW menu to access panels by category instead.
    const panelButtons = new Map();

    // Ctrl+/ shortcut to focus panel search
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === '/') {
            e.preventDefault();
            searchInput.focus();
        }
    });

    // Hidden save input (activated by Save Layout... or Ctrl+Shift+S)
    const saveInput = document.createElement('input');
    saveInput.className = 'command-bar-save-input';
    saveInput.type = 'text';
    saveInput.placeholder = 'Layout name...';
    saveInput.maxLength = 24;
    saveInput.hidden = true;
    saveInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const name = saveInput.value.trim();
            if (name) {
                layoutManager.saveCurrent(name);
                saveInput.hidden = true;
                EventBus.emit('toast:show', { message: `Layout "${name}" saved`, type: 'info' });
            }
        } else if (e.key === 'Escape') { saveInput.hidden = true; }
        e.stopPropagation();
    });
    saveInput.addEventListener('blur', () => { setTimeout(() => { saveInput.hidden = true; }, 150); });
    right.appendChild(saveInput);

    // Assemble
    bar.appendChild(left);
    bar.appendChild(right);
    container.appendChild(bar);

    // Close on click outside
    document.addEventListener('click', (e) => { if (!bar.contains(e.target)) _closeAll(); });
    // Close on ESC
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && openMenu) _closeAll(); });

    // Sync panel button state from EventBus
    EventBus.on('panel:opened', (data) => {
        const btn = panelButtons.get(data.id);
        if (btn) btn.classList.add('active');
    });
    EventBus.on('panel:closed', (data) => {
        const btn = panelButtons.get(data.id);
        if (btn) btn.classList.remove('active');
    });
    EventBus.on('layout:changed', () => {
        for (const [id, btn] of panelButtons) {
            btn.classList.toggle('active', panelManager.isOpen(id));
        }
    });

    // Internal helpers (closures over openMenu/hoverMode)
    function _openMenu(trigger, dropdown, menuDef) {
        if (openMenu && openMenu !== trigger) {
            const prev = openMenu.parentElement.querySelector('.menu-dropdown');
            if (prev) prev.hidden = true;
            openMenu.classList.remove('active');
        }
        _buildDropdown(dropdown, menuDef.getItems(), bar, layoutManager, _closeAll);
        dropdown.hidden = false;
        trigger.classList.add('active');
        openMenu = trigger;
        hoverMode = true;
    }

    function _closeAll() {
        if (openMenu) {
            const prev = openMenu.parentElement.querySelector('.menu-dropdown');
            if (prev) prev.hidden = true;
            openMenu.classList.remove('active');
        }
        openMenu = null;
        hoverMode = false;
    }

    return bar;
}

/**
 * Open the save input programmatically (used by Ctrl+Shift+S shortcut).
 * @param {HTMLElement} barEl - the command-bar root element
 */
export function focusSaveInput(barEl) {
    const input = barEl.querySelector('.command-bar-save-input');
    if (input) { input.hidden = false; input.value = ''; input.focus(); }
}

// ---------------------------------------------------------------------------
// Build dropdown items
// ---------------------------------------------------------------------------

function _buildDropdown(dropdown, items, barEl, layoutManager, closeAll) {
    dropdown.innerHTML = '';
    for (const item of items) {
        if (item.separator) {
            const sep = document.createElement('div');
            sep.className = 'menu-separator';
            dropdown.appendChild(sep);
            continue;
        }
        if (item.header) {
            const hdr = document.createElement('div');
            hdr.className = 'menu-category-header';
            hdr.textContent = item.header;
            dropdown.appendChild(hdr);
            continue;
        }

        const row = document.createElement('div');
        row.className = 'menu-item';

        // Check indicator (cyan dot when active)
        const check = document.createElement('span');
        check.className = 'menu-item-check';
        if (item.checkable && item.checked && item.checked()) check.textContent = '\u2022';
        row.appendChild(check);

        // Label
        const label = document.createElement('span');
        label.className = 'menu-item-label';
        label.textContent = item.label;
        row.appendChild(label);

        // Spacer pushes shortcut/delete right
        const spacer = document.createElement('span');
        spacer.style.flex = '1';
        row.appendChild(spacer);

        // Delete button for user layouts
        if (item.deletable && item.onDelete) {
            const del = document.createElement('button');
            del.className = 'menu-item-delete';
            del.textContent = '\u00d7'; del.title = `Delete ${item.label}`;
            del.addEventListener('click', (e) => {
                e.stopPropagation();
                item.onDelete();
                _buildDropdown(dropdown, _layoutMenuItems(layoutManager), barEl, layoutManager, closeAll);
            });
            row.appendChild(del);
        }

        // Shortcut text (right-aligned, dim)
        if (item.shortcut) {
            const sc = document.createElement('span');
            sc.className = 'menu-item-shortcut';
            sc.textContent = item.shortcut;
            row.appendChild(sc);
        }

        row.addEventListener('click', (e) => {
            e.stopPropagation();
            if (item.action) item.action(barEl, layoutManager);
            if (!item.checkable) {
                // Use the closure-aware closeAll to properly reset internal state
                if (closeAll) closeAll();
                else _closeAllDropdowns(barEl);
            } else if (item.checked) {
                check.textContent = item.checked() ? '\u2022' : '';
            }
        });
        dropdown.appendChild(row);
    }
}

function _closeAllDropdowns(barEl) {
    barEl.querySelectorAll('.menu-dropdown').forEach(d => { d.hidden = true; });
    barEl.querySelectorAll('.menu-trigger.active').forEach(t => { t.classList.remove('active'); });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _shortLabel(title) {
    return (title || '').split(/\s+/)[0].toUpperCase();
}

function _panelKey(id) {
    const map = {
        amy: '1', units: '2', 'unified-alerts': '3', game: '4', meshtastic: '5',
        cameras: '6', search: '7', tak: '8', videos: '9', 'zone-manager': '0',
        minimap: 'M', replay: 'R', sensors: 'E', 'battle-stats': 'P',
        'unit-inspector': 'J', layers: 'L',
    };
    return map[id] || '';
}
