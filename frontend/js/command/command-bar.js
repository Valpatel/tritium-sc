// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// CommandBar -- thin toolbar for panel toggles and layout management.
// Sits between the header and the tactical area (28px height).
//
// Usage:
//   import { createCommandBar } from './command-bar.js';
//   createCommandBar(containerEl, panelManager, layoutManager);

import { EventBus } from './events.js';

/**
 * Create the command bar and mount it into the given container.
 * @param {HTMLElement} container - the parent element to append into
 * @param {import('./panel-manager.js').PanelManager} panelManager
 * @param {import('./layout-manager.js').LayoutManager} layoutManager
 * @returns {HTMLElement} the command-bar root element
 */
export function createCommandBar(container, panelManager, layoutManager) {
    const bar = document.createElement('div');
    bar.className = 'command-bar';

    // ----- Left side: panel toggle buttons -----
    const left = document.createElement('div');
    left.className = 'command-bar-left';

    const panelButtons = new Map();
    const panels = panelManager.getRegisteredPanels();
    for (const p of panels) {
        const btn = document.createElement('button');
        btn.className = 'command-bar-btn';
        if (p.isOpen) btn.classList.add('active');
        btn.dataset.panel = p.id;
        btn.textContent = _shortLabel(p.title);
        btn.title = `Toggle ${p.title} (${_panelKey(p.id)})`;
        btn.addEventListener('click', () => panelManager.toggle(p.id));
        left.appendChild(btn);
        panelButtons.set(p.id, btn);
    }

    // ----- Right side: layout selector + save + help -----
    const right = document.createElement('div');
    right.className = 'command-bar-right';

    // Layout dropdown
    const layoutWrap = document.createElement('div');
    layoutWrap.className = 'command-bar-layout';

    const layoutTrigger = document.createElement('button');
    layoutTrigger.className = 'command-bar-btn command-bar-layout-trigger';
    _updateLayoutLabel(layoutTrigger, layoutManager);

    const dropdown = document.createElement('div');
    dropdown.className = 'command-bar-dropdown';
    dropdown.hidden = true;

    function rebuildDropdown() {
        dropdown.innerHTML = '';
        const layouts = layoutManager.listAll();
        for (const item of layouts) {
            const row = document.createElement('div');
            row.className = 'command-bar-dropdown-item';
            if (layoutManager.currentName === item.name) row.classList.add('active');

            const label = document.createElement('span');
            label.className = 'command-bar-dropdown-label';
            label.textContent = item.name.toUpperCase();
            if (item.builtin) {
                const tag = document.createElement('span');
                tag.className = 'command-bar-dropdown-tag';
                tag.textContent = 'BUILT-IN';
                label.appendChild(tag);
            }
            row.appendChild(label);

            // Delete button for user layouts
            if (!item.builtin) {
                const del = document.createElement('button');
                del.className = 'command-bar-dropdown-delete';
                del.textContent = 'x';
                del.title = `Delete ${item.name}`;
                del.addEventListener('click', (e) => {
                    e.stopPropagation();
                    layoutManager.delete(item.name);
                    rebuildDropdown();
                    _updateLayoutLabel(layoutTrigger, layoutManager);
                });
                row.appendChild(del);
            }

            row.addEventListener('click', () => {
                layoutManager.apply(item.name);
                dropdown.hidden = true;
                _updateLayoutLabel(layoutTrigger, layoutManager);
                _syncPanelButtons(panelManager, panelButtons);
            });
            dropdown.appendChild(row);
        }
    }

    layoutTrigger.addEventListener('click', () => {
        const wasHidden = dropdown.hidden;
        dropdown.hidden = !wasHidden;
        if (!dropdown.hidden) rebuildDropdown();
    });

    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!layoutWrap.contains(e.target)) {
            dropdown.hidden = true;
        }
    });

    layoutWrap.appendChild(layoutTrigger);
    layoutWrap.appendChild(dropdown);
    right.appendChild(layoutWrap);

    // Save button + inline input
    const saveWrap = document.createElement('div');
    saveWrap.className = 'command-bar-save-wrap';

    const saveBtn = document.createElement('button');
    saveBtn.className = 'command-bar-btn command-bar-save-btn';
    saveBtn.textContent = 'SAVE';
    saveBtn.title = 'Save current layout (Ctrl+Shift+S)';

    const saveInput = document.createElement('input');
    saveInput.className = 'command-bar-save-input';
    saveInput.type = 'text';
    saveInput.placeholder = 'Layout name...';
    saveInput.maxLength = 24;
    saveInput.hidden = true;

    saveBtn.addEventListener('click', () => {
        saveInput.hidden = !saveInput.hidden;
        if (!saveInput.hidden) {
            saveInput.value = '';
            saveInput.focus();
        }
    });

    saveInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const name = saveInput.value.trim();
            if (name) {
                layoutManager.saveCurrent(name);
                saveInput.hidden = true;
                _updateLayoutLabel(layoutTrigger, layoutManager);
                EventBus.emit('toast:show', { message: `Layout "${name}" saved`, type: 'info' });
            }
        } else if (e.key === 'Escape') {
            saveInput.hidden = true;
        }
        e.stopPropagation(); // Don't trigger global shortcuts
    });

    saveWrap.appendChild(saveBtn);
    saveWrap.appendChild(saveInput);
    right.appendChild(saveWrap);

    // Help button
    const helpBtn = document.createElement('button');
    helpBtn.className = 'command-bar-btn';
    helpBtn.textContent = '?';
    helpBtn.title = 'Show keyboard shortcuts';
    helpBtn.dataset.action = 'help';
    helpBtn.addEventListener('click', () => {
        const overlay = document.getElementById('help-overlay');
        if (overlay) overlay.hidden = !overlay.hidden;
    });
    right.appendChild(helpBtn);

    // ----- Assemble -----
    bar.appendChild(left);
    bar.appendChild(right);
    container.appendChild(bar);

    // ----- Listen for panel open/close events to sync button state -----
    EventBus.on('panel:opened', (data) => {
        const btn = panelButtons.get(data.id);
        if (btn) btn.classList.add('active');
    });

    EventBus.on('panel:closed', (data) => {
        const btn = panelButtons.get(data.id);
        if (btn) btn.classList.remove('active');
    });

    // ----- Listen for layout changes (e.g. from keyboard shortcuts) -----
    EventBus.on('layout:changed', () => {
        _updateLayoutLabel(layoutTrigger, layoutManager);
        _syncPanelButtons(panelManager, panelButtons);
    });

    return bar;
}

/**
 * Open the save input programmatically (used by Ctrl+Shift+S shortcut).
 * @param {HTMLElement} barEl - the command-bar root element
 */
export function focusSaveInput(barEl) {
    const input = barEl.querySelector('.command-bar-save-input');
    if (input) {
        input.hidden = false;
        input.value = '';
        input.focus();
    }
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function _shortLabel(title) {
    // "AMY COMMANDER" -> "AMY", "UNITS" -> "UNITS", "GAME HUD" -> "GAME"
    return (title || '').split(/\s+/)[0].toUpperCase();
}

function _panelKey(id) {
    const map = { amy: '1', units: '2', alerts: '3', game: '4' };
    return map[id] || '';
}

function _updateLayoutLabel(trigger, layoutManager) {
    const name = layoutManager.currentName || 'default';
    trigger.textContent = `LAYOUT: ${name.toUpperCase()}`;
}

function _syncPanelButtons(panelManager, panelButtons) {
    for (const [id, btn] of panelButtons) {
        if (panelManager.isOpen(id)) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    }
}
