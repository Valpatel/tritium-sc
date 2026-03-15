// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Map Layer Switcher Panel
// Compact per-layer toggle panel for plugin-contributed map layers.
// Toggles individual layer groups (targets, convoys, geofences, RF motion,
// sensor coverage, heatmaps, FOV cones, trails, floor plans, weather).
// Persists preferences in localStorage.

import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';

const STORAGE_KEY = 'tritium-layer-switcher-prefs';

// Layer group definitions — each maps to a map state key or EventBus toggle.
// Groups are organized by functional area for quick access.
const LAYER_GROUPS = [
    {
        section: 'TARGETS',
        icon: '\u25C9',  // bullseye
        layers: [
            { id: 'ble-targets',    label: 'BLE Targets',      stateKey: 'showUnits', toggleFn: 'toggleUnits',     color: '#05ffa1', description: 'BLE device markers (phones, watches, IoT)' },
            { id: 'camera-targets', label: 'Camera Detections', stateKey: 'showUnits', toggleFn: 'toggleUnits',     color: '#00f0ff', description: 'YOLO camera detection overlays' },
            { id: 'mesh-targets',   label: 'Mesh Nodes',        stateKey: 'showMesh',  toggleFn: 'toggleMesh',      color: '#00d4aa', description: 'Meshtastic LoRa mesh radio nodes' },
            { id: 'wifi-targets',   label: 'WiFi Devices',      stateKey: 'showUnits', toggleFn: 'toggleUnits',     color: '#4a9eff', description: 'WiFi probe request and BSSID markers' },
            { id: 'unit-labels',    label: 'Target Labels',     stateKey: 'showLabels', toggleFn: 'toggleLabels',   color: null,      description: 'Callsign text labels on targets' },
        ],
    },
    {
        section: 'OVERLAYS',
        icon: '\u25A3',  // filled square with square inside
        layers: [
            { id: 'convoy-overlay',   label: 'Convoy Overlays',   stateKey: 'showSquadHulls',       toggleFn: 'toggleSquadHulls',       color: '#ff2a6d', description: 'Convex hull outlines around convoy groups' },
            { id: 'geofence-zones',   label: 'Geofence Zones',    stateKey: 'showHazardZones',      toggleFn: 'toggleHazardZones',      color: '#ff8800', description: 'Defined geofence alert boundaries' },
            { id: 'patrol-routes',    label: 'Patrol Routes',     stateKey: 'showPatrolRoutes',     toggleFn: 'togglePatrolRoutes',     color: '#05ffa1', description: 'Friendly patrol waypoint paths' },
            { id: 'hostile-obj',      label: 'Hostile Objectives', stateKey: 'showHostileObjectives', toggleFn: 'toggleHostileObjectives', color: '#ff2a6d', description: 'Enemy movement objective lines' },
            { id: 'prediction-cones', label: 'Prediction Cones',  stateKey: 'showPredictionCones',  toggleFn: 'togglePredictionCones',  color: '#fcee0a', description: 'Movement prediction confidence cones' },
        ],
    },
    {
        section: 'SENSING',
        icon: '\u25CE',  // circle with inner circle
        layers: [
            { id: 'rf-motion',       label: 'RF Motion',          stateKey: null,                    eventToggle: 'rf-motion:toggle',     color: '#ff2a6d', description: 'RF-based motion detection indicators' },
            { id: 'sensor-coverage', label: 'Sensor Coverage',    stateKey: 'showCoverageOverlap',  toggleFn: 'toggleCoverageOverlap',  color: '#05ffa1', description: 'Multi-sensor coverage overlap areas' },
            { id: 'mesh-coverage',   label: 'Mesh Coverage',      stateKey: 'showMeshCoverage',     toggleFn: 'toggleMeshCoverage',     color: 'rgba(0,212,170,0.3)', description: 'LoRa radio coverage radius circles' },
            { id: 'weapon-range',    label: 'Weapon/FOV Range',   stateKey: 'showWeaponRange',      toggleFn: 'toggleWeaponRange',      color: '#05ffa166', description: 'Field of view cones and weapon range circles' },
            { id: 'fog-of-war',      label: 'Fog of War',         stateKey: 'showFog',              toggleFn: 'toggleFog',              color: '#333333', description: 'Darkens areas outside sensor vision' },
        ],
    },
    {
        section: 'ANALYTICS',
        icon: '\u2593',  // dark shade
        layers: [
            { id: 'combat-heatmap',  label: 'Combat Heatmap',   stateKey: 'showHeatmap',           toggleFn: 'toggleHeatmap',         color: '#ff4400', description: 'Heat overlay of combat concentration' },
            { id: 'activity-heatmap', label: 'Activity Heatmap', stateKey: null,                    eventToggle: 'activity-heatmap:toggle', color: '#ff2a6d', description: 'Multi-source activity density map' },
            { id: 'crowd-density',   label: 'Crowd Density',    stateKey: 'showCrowdDensity',      toggleFn: 'toggleCrowdDensity',    color: '#ff8800', description: 'Civilian crowd density heatmap' },
            { id: 'trails',          label: 'Movement Trails',  stateKey: null,                    eventToggle: 'trails:toggle',      color: '#05ffa1', description: 'Speed-colored target movement paths' },
            { id: 'pred-ellipses',   label: 'Pred. Ellipses',   stateKey: null,                    eventToggle: 'prediction-ellipses:toggle', color: '#fcee0a', description: 'Prediction confidence ellipses' },
        ],
    },
    {
        section: 'ENVIRONMENT',
        icon: '\u25A1',  // white square
        layers: [
            { id: 'floor-plans',    label: 'Floor Plans',      stateKey: null,               eventToggle: 'floorplan:toggle',    color: '#00f0ff', description: 'Indoor floor plan overlays' },
            { id: 'weather',        label: 'Weather Overlay',  stateKey: null,               eventToggle: 'weather:toggle',      color: '#4488cc', description: 'Live weather conditions layer' },
            { id: 'buildings',      label: 'Buildings',        stateKey: 'showBuildings',    toggleFn: 'toggleBuildings',        color: '#00f0ff', description: 'Building outline footprints' },
            { id: 'terrain-3d',     label: '3D Terrain',       stateKey: 'showTerrain',      toggleFn: 'toggleTerrain',          color: null,      description: 'Elevation mesh from DEM data' },
            { id: 'satellite',      label: 'Satellite',        stateKey: 'showSatellite',    toggleFn: 'toggleSatellite',        color: null,      description: 'Aerial satellite imagery' },
            { id: 'geo-layers',     label: 'GIS Intelligence', stateKey: 'showGeoLayers',    toggleFn: 'toggleGeoLayers',        color: '#00f0ff', description: 'Government and OSM geographic data' },
        ],
    },
];

/**
 * Load saved layer preferences from localStorage.
 * @returns {Object} - map of layer id -> boolean (true = on)
 */
function loadPrefs() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) return JSON.parse(raw);
    } catch (_) { /* ignore */ }
    return {};
}

/**
 * Save layer preferences to localStorage.
 * @param {Object} prefs - map of layer id -> boolean
 */
function savePrefs(prefs) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch (_) { /* ignore */ }
}


export const MapLayerSwitcherPanelDef = {
    id: 'map-layer-switcher',
    title: 'LAYER SWITCHER',
    defaultPosition: { x: 8, y: 100 },
    defaultSize: { w: 280, h: 560 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'layer-switcher-panel';
        el.innerHTML = `
            <div class="layer-switcher-header">
                <span class="layer-switcher-title mono">MAP LAYERS</span>
                <button class="layer-switcher-btn-all" data-action="all-on" title="Enable all layers">ALL</button>
                <button class="layer-switcher-btn-none" data-action="all-off" title="Disable all layers">NONE</button>
            </div>
            <div class="layer-switcher-body" data-bind="body"></div>
        `;
        return el;
    },

    mount(bodyEl, _panel) {
        const container = bodyEl.querySelector('[data-bind="body"]');
        let mapActions = null;
        const prefs = loadPrefs();
        // Track event-toggle states locally (since they have no stateKey in mapState)
        const eventStates = {};

        // Get map actions via event
        EventBus.on('layers:set-map-actions', (actions) => { mapActions = actions; render(); });
        EventBus.emit('layers:request-map-actions');

        function isLayerOn(layer) {
            // Check local event toggle state first
            if (layer.eventToggle && eventStates[layer.id] !== undefined) {
                return eventStates[layer.id];
            }
            // Check saved prefs for event-toggle layers
            if (layer.eventToggle && prefs[layer.id] !== undefined) {
                return prefs[layer.id];
            }
            // Check map state
            if (layer.stateKey && mapActions && mapActions.getMapState) {
                const state = mapActions.getMapState();
                return !!state[layer.stateKey];
            }
            // Default to saved pref or true
            return prefs[layer.id] !== undefined ? prefs[layer.id] : true;
        }

        function toggleLayer(layer) {
            if (layer.eventToggle) {
                const newState = !isLayerOn(layer);
                eventStates[layer.id] = newState;
                prefs[layer.id] = newState;
                savePrefs(prefs);
                EventBus.emit(layer.eventToggle);
                render();
                return;
            }
            if (!mapActions) return;
            if (layer.toggleFn && typeof mapActions[layer.toggleFn] === 'function') {
                mapActions[layer.toggleFn]();
                // Save current state after toggle
                setTimeout(() => {
                    if (mapActions.getMapState && layer.stateKey) {
                        prefs[layer.id] = !!mapActions.getMapState()[layer.stateKey];
                        savePrefs(prefs);
                    }
                    render();
                }, 50);
                return;
            }
            render();
        }

        function setAll(on) {
            for (const group of LAYER_GROUPS) {
                for (const layer of group.layers) {
                    const currentlyOn = isLayerOn(layer);
                    if (currentlyOn !== on) {
                        toggleLayer(layer);
                    }
                }
            }
        }

        function render() {
            if (!container) return;
            let html = '';

            for (const group of LAYER_GROUPS) {
                // Count active layers in group
                const activeCount = group.layers.filter(l => isLayerOn(l)).length;
                const totalCount = group.layers.length;

                html += `<div class="lsw-section">`;
                html += `<div class="lsw-section-header" data-section="${_esc(group.section)}">`;
                html += `<span class="lsw-section-icon">${group.icon}</span>`;
                html += `<span class="lsw-section-name">${_esc(group.section)}</span>`;
                html += `<span class="lsw-section-count">${activeCount}/${totalCount}</span>`;
                html += `</div>`;
                html += `<div class="lsw-section-body">`;

                for (const layer of group.layers) {
                    const on = isLayerOn(layer);
                    const swatch = layer.color
                        ? `<span class="lsw-swatch" style="background:${layer.color}"></span>`
                        : `<span class="lsw-swatch lsw-swatch-none"></span>`;

                    html += `<div class="lsw-layer${on ? ' active' : ''}" data-layer="${_esc(layer.id)}" title="${_esc(layer.description)}">`;
                    html += `<label class="lsw-toggle">`;
                    html += `<input type="checkbox" ${on ? 'checked' : ''} data-layer-id="${_esc(layer.id)}" />`;
                    html += `<span class="lsw-toggle-track"><span class="lsw-toggle-thumb"></span></span>`;
                    html += `</label>`;
                    html += swatch;
                    html += `<span class="lsw-label">${_esc(layer.label)}</span>`;
                    html += `</div>`;
                }

                html += `</div></div>`;
            }

            container.innerHTML = html;

            // Bind checkbox toggles
            for (const cb of container.querySelectorAll('input[type="checkbox"]')) {
                cb.addEventListener('change', () => {
                    const layerId = cb.dataset.layerId;
                    for (const group of LAYER_GROUPS) {
                        const layer = group.layers.find(l => l.id === layerId);
                        if (layer) { toggleLayer(layer); break; }
                    }
                });
            }

            // Bind section header collapse/expand
            for (const hdr of container.querySelectorAll('.lsw-section-header')) {
                hdr.addEventListener('click', () => {
                    hdr.parentElement.classList.toggle('collapsed');
                });
            }
        }

        // Bind all-on / all-off buttons
        const allOnBtn = bodyEl.querySelector('[data-action="all-on"]');
        const allOffBtn = bodyEl.querySelector('[data-action="all-off"]');
        if (allOnBtn) allOnBtn.addEventListener('click', () => setAll(true));
        if (allOffBtn) allOffBtn.addEventListener('click', () => setAll(false));

        // Apply saved prefs on mount — restore event-toggle layers
        function applySavedPrefs() {
            for (const group of LAYER_GROUPS) {
                for (const layer of group.layers) {
                    if (layer.eventToggle && prefs[layer.id] !== undefined) {
                        eventStates[layer.id] = prefs[layer.id];
                    }
                }
            }
        }
        applySavedPrefs();

        // Re-render when map layers change externally
        const stateHandler = () => render();
        EventBus.on('map:layers-changed', stateHandler);

        render();

        return () => {
            EventBus.off('map:layers-changed', stateHandler);
        };
    },
};
