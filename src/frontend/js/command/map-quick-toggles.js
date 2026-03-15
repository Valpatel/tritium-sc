// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Map Layer Quick Toggles — floating buttons on the map edge for
 * rapid toggle of common layers without opening the layers panel.
 *
 * Layers: satellite, heatmap, coverage, grid, correlation lines, trails
 *
 * Usage:
 *   import { createMapQuickToggles } from './map-quick-toggles.js';
 *   createMapQuickToggles(tacticalAreaEl);
 */

import { EventBus } from './events.js';

/**
 * Layer toggle definitions.
 * Each entry maps to a toggle function name on mapActions.
 */
const QUICK_TOGGLES = [
    {
        id: 'satellite',
        icon: 'SAT',
        title: 'Toggle satellite imagery (I)',
        stateKey: 'showSatellite',
        toggleFn: 'toggleSatellite',
    },
    {
        id: 'heatmap',
        icon: 'HM',
        title: 'Toggle combat heatmap',
        stateKey: 'showHeatmap',
        toggleFn: 'toggleHeatmap',
    },
    {
        id: 'fog',
        icon: 'FOG',
        title: 'Toggle fog of war (V)',
        stateKey: 'showFog',
        toggleFn: 'toggleFog',
    },
    {
        id: 'grid',
        icon: 'GRD',
        title: 'Toggle coordinate grid',
        stateKey: 'showGrid',
        toggleFn: 'toggleGrid',
    },
    {
        id: 'patrol',
        icon: 'PTR',
        title: 'Toggle patrol routes',
        stateKey: 'showPatrolRoutes',
        toggleFn: 'togglePatrolRoutes',
    },
    {
        id: 'mesh',
        icon: 'MSH',
        title: 'Toggle mesh network overlay',
        stateKey: 'showMesh',
        toggleFn: 'toggleMesh',
    },
    {
        id: 'trails',
        icon: 'TRL',
        title: 'Toggle target movement trails',
        stateKey: null,  // Custom toggle via EventBus
        toggleFn: null,
        eventToggle: 'trails:toggle',
    },
    {
        id: 'prediction-ellipses',
        icon: 'ELP',
        title: 'Toggle prediction confidence ellipses',
        stateKey: null,
        toggleFn: null,
        eventToggle: 'prediction-ellipses:toggle',
    },
];

/**
 * Create the quick toggle bar and attach to the tactical area.
 * @param {HTMLElement} tacticalArea - the map container element
 * @returns {{ destroy: Function }}
 */
export function createMapQuickToggles(tacticalArea) {
    const bar = document.createElement('div');
    bar.className = 'map-quick-toggles';

    let mapActions = null;
    const buttons = new Map();

    for (const toggle of QUICK_TOGGLES) {
        const btn = document.createElement('button');
        btn.className = 'mqt-btn mono';
        btn.dataset.layer = toggle.id;
        btn.title = toggle.title;
        btn.textContent = toggle.icon;

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            // Custom event-based toggle (e.g., trails)
            if (toggle.eventToggle) {
                btn.classList.toggle('active');
                EventBus.emit(toggle.eventToggle);
                return;
            }
            if (!mapActions) return;
            const fn = mapActions[toggle.toggleFn];
            if (typeof fn === 'function') {
                fn();
                syncStates();
            }
        });

        bar.appendChild(btn);
        buttons.set(toggle.id, btn);
    }

    tacticalArea.appendChild(bar);

    function syncStates() {
        if (!mapActions || !mapActions.getMapState) return;
        const state = mapActions.getMapState();
        for (const toggle of QUICK_TOGGLES) {
            if (toggle.eventToggle) continue; // event toggles manage their own state
            const btn = buttons.get(toggle.id);
            if (!btn) continue;
            const isOn = !!state[toggle.stateKey];
            btn.classList.toggle('active', isOn);
        }
    }

    // Get map actions when available
    const onSetActions = (actions) => {
        mapActions = actions;
        syncStates();
    };
    EventBus.on('layers:set-map-actions', onSetActions);
    EventBus.emit('layers:request-map-actions');

    // Re-sync when layers change
    const onLayersChanged = () => syncStates();
    EventBus.on('map:layers-changed', onLayersChanged);

    return {
        destroy() {
            EventBus.off('layers:set-map-actions', onSetActions);
            EventBus.off('map:layers-changed', onLayersChanged);
            bar.remove();
        },
    };
}
