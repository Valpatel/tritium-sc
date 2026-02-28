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

import { EventBus } from './events.js';

/**
 * Get the currently selected battle scenario name.
 * Deprecated: always returns null. All missions route through MissionModal.
 * @returns {null}
 */
export function getSelectedScenario() {
    return null;
}

// ---------------------------------------------------------------------------
// Menu definitions (data-driven)
// ---------------------------------------------------------------------------

function _fileMenuItems(layoutManager) {
    return [
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
    ];
}

function _viewMenuItems(panelManager) {
    const keyMap = { amy: '1', units: '2', alerts: '3', game: '4' };
    const items = panelManager.getRegisteredPanels().map(p => ({
        label: p.title, shortcut: keyMap[p.id] || '', checkable: true,
        checked: () => panelManager.isOpen(p.id),
        action: () => panelManager.toggle(p.id),
    }));
    items.push({ separator: true });
    items.push({ label: 'Show All', action: () => {
        for (const p of panelManager.getRegisteredPanels()) panelManager.open(p.id);
    }});
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
        { label: 'Toggle All', action: () => mapActions.toggleAllLayers() },
        { separator: true },
        // Base map layers
        { label: 'Satellite', shortcut: 'I', checkable: true, checked: () => s().showSatellite, action: () => mapActions.toggleSatellite() },
        { label: 'Roads', shortcut: 'G', checkable: true, checked: () => s().showRoads, action: () => mapActions.toggleRoads() },
        { label: 'Buildings', shortcut: 'K', checkable: true, checked: () => s().showBuildings, action: () => mapActions.toggleBuildings() },
        { label: 'Waterways', checkable: true, checked: () => s().showWaterways, action: () => mapActions.toggleWaterways() },
        { label: 'Parks', checkable: true, checked: () => s().showParks, action: () => mapActions.toggleParks() },
        { label: 'Grid', checkable: true, checked: () => s().showGrid, action: () => mapActions.toggleGrid() },
        { separator: true },
        // Unit layers
        { label: '3D Models', checkable: true, checked: () => s().showModels3d, action: () => mapActions.toggleModels() },
        { label: 'Labels', checkable: true, checked: () => s().showLabels, action: () => mapActions.toggleLabels() },
        { label: 'Mesh Network', checkable: true, checked: () => s().showMesh, action: () => mapActions.toggleMesh() },
        { label: 'Thought Bubbles', checkable: true, checked: () => s().showThoughts, action: () => mapActions.toggleThoughts() },
        { separator: true },
        // Combat FX layers
        { label: 'Tracers', checkable: true, checked: () => s().showTracers, action: () => mapActions.toggleTracers() },
        { label: 'Explosions', checkable: true, checked: () => s().showExplosions, action: () => mapActions.toggleExplosions() },
        { label: 'Particles', checkable: true, checked: () => s().showParticles, action: () => mapActions.toggleParticles() },
        { label: 'Hit Flashes', checkable: true, checked: () => s().showHitFlashes, action: () => mapActions.toggleHitFlashes() },
        { label: 'Floating Text', checkable: true, checked: () => s().showFloatingText, action: () => mapActions.toggleFloatingText() },
        { separator: true },
        // Overlay layers
        { label: 'Kill Feed', checkable: true, checked: () => s().showKillFeed, action: () => mapActions.toggleKillFeed() },
        { label: 'Screen FX', checkable: true, checked: () => s().showScreenFx, action: () => mapActions.toggleScreenFx() },
        { label: 'Banners', checkable: true, checked: () => s().showBanners, action: () => mapActions.toggleBanners() },
        { label: 'Layer HUD', checkable: true, checked: () => s().showLayerHud, action: () => mapActions.toggleLayerHud() },
        { separator: true },
        // Unit decorations
        { label: 'Health Bars', checkable: true, checked: () => s().showHealthBars, action: () => mapActions.toggleHealthBars() },
        { label: 'Selection FX', checkable: true, checked: () => s().showSelectionFx, action: () => mapActions.toggleSelectionFx() },
        { separator: true },
        // Environment
        { label: 'Fog', checkable: true, checked: () => s().showFog, action: () => mapActions.toggleFog() },
        { label: 'Terrain', shortcut: 'H', checkable: true, checked: () => s().showTerrain, action: () => mapActions.toggleTerrain() },
        { label: '3D Mode', checkable: true, checked: () => s().tiltMode === 'tilted', action: () => mapActions.toggleTilt() },
        { separator: true },
        // Camera controls
        { label: 'Center on Action', shortcut: 'F', action: () => mapActions.centerOnAction() },
        { label: 'Reset Camera', shortcut: 'R', action: () => mapActions.resetCamera() },
        { label: 'Zoom In', shortcut: ']', action: () => mapActions.zoomIn() },
        { label: 'Zoom Out', shortcut: '[', action: () => mapActions.zoomOut() },
    ];
}

function _gameMenuItems(mapActions) {
    return [
        { label: 'New Mission', shortcut: 'B',
          action: () => { if (mapActions.beginWar) mapActions.beginWar(); } },
        { separator: true },
        { label: 'Reset Game', shortcut: 'R',
          action: () => { if (mapActions.resetGame) mapActions.resetGame(); } },
    ];
}

function _helpMenuItems() {
    return [
        { label: 'Keyboard Shortcuts', shortcut: '?', action: () => {
            const overlay = document.getElementById('help-overlay');
            if (overlay) overlay.hidden = !overlay.hidden;
        }},
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
        { label: 'FILE',   getItems: () => _fileMenuItems(layoutManager) },
        { label: 'VIEW',   getItems: () => _viewMenuItems(panelManager) },
        { label: 'LAYOUT', getItems: () => _layoutMenuItems(layoutManager) },
        { label: 'MAP',    getItems: () => _mapMenuItems(mapActions) },
        { label: 'GAME',   getItems: () => _gameMenuItems(mapActions) },
        { label: 'HELP',   getItems: () => _helpMenuItems() },
    ];

    // Build menu triggers
    for (const menuDef of menus) {
        const wrap = document.createElement('div');
        wrap.className = 'menu-trigger-wrap';
        wrap.style.position = 'relative';

        const trigger = document.createElement('button');
        trigger.className = 'menu-trigger';
        trigger.textContent = menuDef.label;

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

    // Right side: quick-access panel toggle buttons
    const panelButtons = new Map();
    for (const p of panelManager.getRegisteredPanels()) {
        const btn = document.createElement('button');
        btn.className = 'command-bar-btn';
        if (p.isOpen) btn.classList.add('active');
        btn.dataset.panel = p.id;
        btn.textContent = _shortLabel(p.title);
        btn.title = `Toggle ${p.title} (${_panelKey(p.id)})`;
        btn.addEventListener('click', () => panelManager.toggle(p.id));
        right.appendChild(btn);
        panelButtons.set(p.id, btn);
    }

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
    const map = { amy: '1', units: '2', alerts: '3', game: '4' };
    return map[id] || '';
}
