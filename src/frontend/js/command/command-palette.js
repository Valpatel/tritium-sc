// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// CommandPalette -- VS Code-style fuzzy searchable command palette
// Open with Ctrl+K or / (when not focused on input).
// Searchable list of all actions: open panel, toggle layer, start demo, etc.
//
// Extends tritium-lib's fuzzyScore for search; SC owns command list + DOM rendering.
//
// Usage:
//   import { initCommandPalette } from './command-palette.js';
//   initCommandPalette(panelManager, mapActions);

import { EventBus } from './events.js';
import { _esc } from './panel-utils.js';
import { fuzzyScore } from '/lib/command-palette.js';

let _overlay = null;
let _input = null;
let _list = null;
let _commands = [];
let _filtered = [];
let _selectedIdx = 0;

/**
 * Initialize the command palette.
 * @param {import('./panel-manager.js').PanelManager} panelManager
 * @param {object} mapActions - map toggle functions
 */
export function initCommandPalette(panelManager, mapActions) {
    _commands = _buildCommands(panelManager, mapActions);
    _createDOM();
    _bindKeys();
}

/**
 * Open the command palette.
 */
export function openCommandPalette() {
    if (!_overlay) return;
    _overlay.hidden = false;
    _input.value = '';
    _selectedIdx = 0;
    _filtered = _commands.slice();
    _renderList();
    // Defer focus to next frame to avoid input event from triggering key
    requestAnimationFrame(() => _input.focus());
}

/**
 * Close the command palette.
 */
export function closeCommandPalette() {
    if (!_overlay) return;
    _overlay.hidden = true;
    _input.blur();
}

function _createDOM() {
    _overlay = document.createElement('div');
    _overlay.id = 'command-palette';
    _overlay.className = 'cmd-palette-overlay';
    _overlay.hidden = true;

    const dialog = document.createElement('div');
    dialog.className = 'cmd-palette-dialog';

    // Search input
    _input = document.createElement('input');
    _input.type = 'text';
    _input.className = 'cmd-palette-input';
    _input.placeholder = 'Type a command...';
    _input.spellcheck = false;
    _input.autocomplete = 'off';
    _input.setAttribute('aria-label', 'Command search');

    _input.addEventListener('input', () => {
        _filterCommands(_input.value);
        _selectedIdx = 0;
        _renderList();
    });

    _input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            _selectedIdx = Math.min(_selectedIdx + 1, _filtered.length - 1);
            _renderList();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            _selectedIdx = Math.max(_selectedIdx - 1, 0);
            _renderList();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (_filtered[_selectedIdx]) {
                _executeCommand(_filtered[_selectedIdx]);
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            closeCommandPalette();
        }
        e.stopPropagation();
    });

    // Results list
    _list = document.createElement('div');
    _list.className = 'cmd-palette-list';
    _list.setAttribute('role', 'listbox');

    dialog.appendChild(_input);
    dialog.appendChild(_list);

    // Click backdrop to close
    _overlay.addEventListener('click', (e) => {
        if (e.target === _overlay) closeCommandPalette();
    });

    _overlay.appendChild(dialog);
    document.body.appendChild(_overlay);
}

function _bindKeys() {
    document.addEventListener('keydown', (e) => {
        // Ctrl+K or / (when not in input/textarea)
        const inInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' ||
                        e.target.isContentEditable;

        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            if (_overlay.hidden) {
                openCommandPalette();
            } else {
                closeCommandPalette();
            }
        } else if (e.key === '/' && !inInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            openCommandPalette();
        }
    });
}

function _filterCommands(query) {
    if (!query.trim()) {
        _filtered = _commands.slice();
        return;
    }
    const q = query.toLowerCase().trim();

    _filtered = _commands
        .map(cmd => {
            const text = `${cmd.category} ${cmd.label}`;
            const score = fuzzyScore(q, text);
            return { cmd, score };
        })
        .filter(r => r.score > 0)
        .sort((a, b) => b.score - a.score)
        .map(r => r.cmd);
}

function _renderList() {
    _list.innerHTML = '';
    const maxShow = 20;
    const items = _filtered.slice(0, maxShow);

    items.forEach((cmd, i) => {
        const row = document.createElement('div');
        row.className = 'cmd-palette-item';
        if (i === _selectedIdx) row.classList.add('selected');
        row.setAttribute('role', 'option');

        row.innerHTML = `
            <span class="cmd-cat mono">${_esc(cmd.category)}</span>
            <span class="cmd-label">${_esc(cmd.label)}</span>
            ${cmd.shortcut ? `<span class="cmd-shortcut mono">${_esc(cmd.shortcut)}</span>` : ''}
        `;

        row.addEventListener('click', () => _executeCommand(cmd));
        row.addEventListener('mouseenter', () => {
            _selectedIdx = i;
            _list.querySelectorAll('.cmd-palette-item').forEach((el, j) => {
                el.classList.toggle('selected', j === i);
            });
        });

        _list.appendChild(row);
    });

    if (_filtered.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'cmd-palette-empty mono';
        empty.textContent = 'No matching commands';
        _list.appendChild(empty);
    }

    // Scroll selected into view
    const selected = _list.querySelector('.selected');
    if (selected) selected.scrollIntoView({ block: 'nearest' });
}

function _executeCommand(cmd) {
    closeCommandPalette();
    if (typeof cmd.action === 'function') {
        try { cmd.action(); } catch (e) {
            console.warn('[CMD] Action failed:', e);
        }
    }
}

function _buildCommands(panelManager, mapActions) {
    const cmds = [];

    // Panel toggles
    if (panelManager) {
        for (const p of panelManager.getRegisteredPanels()) {
            cmds.push({
                category: 'PANEL',
                label: `Toggle ${p.title}`,
                action: () => panelManager.toggle(p.id),
            });
        }
    }

    // Map layer toggles
    if (mapActions) {
        const layers = [
            ['Satellite', 'toggleSatellite'], ['Roads', 'toggleRoads'],
            ['Grid', 'toggleGrid'], ['Buildings', 'toggleBuildings'],
            ['Fog of War', 'toggleFog'], ['Terrain', 'toggleTerrain'],
            ['Units', 'toggleUnits'], ['Labels', 'toggleLabels'],
            ['3D Models', 'toggleModels'], ['Mesh Network', 'toggleMesh'],
            ['NPC Thoughts', 'toggleThoughts'], ['All Layers', 'toggleAllLayers'],
            ['Tracers', 'toggleTracers'], ['Explosions', 'toggleExplosions'],
            ['Particles', 'toggleParticles'], ['Health Bars', 'toggleHealthBars'],
            ['Kill Feed', 'toggleKillFeed'], ['Geo Layers', 'toggleGeoLayers'],
            ['Patrol Routes', 'togglePatrolRoutes'], ['Weapon Range', 'toggleWeaponRange'],
            ['Heatmap', 'toggleHeatmap'], ['Hazard Zones', 'toggleHazardZones'],
        ];
        for (const [name, fn] of layers) {
            if (typeof mapActions[fn] === 'function') {
                cmds.push({
                    category: 'LAYER',
                    label: `Toggle ${name}`,
                    action: mapActions[fn],
                });
            }
        }

        // Map controls
        if (mapActions.centerOnAction) {
            cmds.push({ category: 'MAP', label: 'Center on Action', shortcut: 'F', action: mapActions.centerOnAction });
        }
        if (mapActions.resetCamera) {
            cmds.push({ category: 'MAP', label: 'Reset Camera', action: mapActions.resetCamera });
        }
        if (mapActions.zoomIn) {
            cmds.push({ category: 'MAP', label: 'Zoom In', shortcut: '+', action: mapActions.zoomIn });
        }
        if (mapActions.zoomOut) {
            cmds.push({ category: 'MAP', label: 'Zoom Out', shortcut: '-', action: mapActions.zoomOut });
        }

        // Map modes
        ['observe', 'tactical', 'setup'].forEach(mode => {
            if (mapActions.setMapMode) {
                cmds.push({
                    category: 'MODE',
                    label: `Map Mode: ${mode.charAt(0).toUpperCase() + mode.slice(1)}`,
                    shortcut: mode[0].toUpperCase(),
                    action: () => mapActions.setMapMode(mode),
                });
            }
        });

        // Battle controls
        if (mapActions.beginWar) {
            cmds.push({ category: 'SIMULATION', label: 'Begin Battle', shortcut: 'B', action: mapActions.beginWar });
        }
        if (mapActions.resetGame) {
            cmds.push({ category: 'SIMULATION', label: 'Reset Battle', action: mapActions.resetGame });
        }
    }

    // System actions
    cmds.push({
        category: 'SYSTEM',
        label: 'Start Demo Mode',
        action: () => fetch('/api/demo/start', { method: 'POST' }).catch(() => {}),
    });
    cmds.push({
        category: 'SYSTEM',
        label: 'Stop Demo Mode',
        action: () => fetch('/api/demo/stop', { method: 'POST' }).catch(() => {}),
    });
    cmds.push({
        category: 'SYSTEM',
        label: 'Fullscreen',
        shortcut: 'F11',
        action: () => {
            if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
            else document.documentElement.requestFullscreen().catch(() => {});
        },
    });
    cmds.push({
        category: 'NAV',
        label: 'Show Keyboard Shortcuts',
        shortcut: '?',
        action: () => {
            const overlay = document.getElementById('help-overlay');
            if (overlay) overlay.hidden = !overlay.hidden;
        },
    });
    cmds.push({
        category: 'NAV',
        label: 'Toggle Chat',
        shortcut: 'C',
        action: () => {
            const chat = document.getElementById('chat-overlay');
            if (chat) chat.hidden = !chat.hidden;
        },
    });

    return cmds;
}
