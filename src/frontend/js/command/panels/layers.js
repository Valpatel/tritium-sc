// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Layer Browser Panel
// Google Earth-style layer browser with categorized toggles, color swatches,
// data source info, and descriptions. Makes the map understandable.

import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';

// Mesh layer state reference (populated at runtime from mesh-layer.js global)
function _getMeshState() {
    return (typeof meshState !== 'undefined') ? meshState : null;
}
function _getMeshNodeCount() {
    return (typeof meshGetNodeCount === 'function') ? meshGetNodeCount() : 0;
}

// Layer definitions — categorized with human-readable descriptions.
// Each layer has: id (matches map-maplibre toggle), label, description, color, source.
const LAYER_CATEGORIES = [
    {
        name: 'BASE MAP',
        description: 'Underlying map imagery and features',
        layers: [
            { id: 'satellite', label: 'Satellite Imagery', description: 'Aerial photography of the neighborhood', color: null, source: 'Esri / OpenFreeMap', key: 'showSatellite' },
            { id: 'buildings', label: 'Building Outlines', description: 'Cyan outlines showing building footprints and structures', color: '#00f0ff', source: 'OpenFreeMap', key: 'showBuildings' },
            { id: 'roads', label: 'Road Network', description: 'Streets, highways, and paths', color: '#445566', source: 'OpenFreeMap', key: 'showRoads' },
            { id: 'waterways', label: 'Waterways', description: 'Creeks, channels, and water features', color: '#4488cc', source: 'OpenFreeMap', key: 'showWaterways' },
            { id: 'parks', label: 'Parks & Green Spaces', description: 'Parks, fields, and green areas', color: '#1a5a2a', source: 'OpenFreeMap', key: 'showParks' },
            { id: 'grid', label: 'Coordinate Grid', description: 'Tactical reference grid overlay', color: '#00f0ff', source: 'Generated', key: 'showGrid' },
            { id: 'terrain', label: '3D Terrain', description: 'Elevation mesh from digital elevation models', color: null, source: 'Mapzen DEM', key: 'showTerrain' },
        ],
    },
    {
        name: 'MESH NETWORK',
        description: 'Meshtastic LoRa mesh radio network overlay',
        meshNetwork: true, // Flag for dynamic node count in label
        layers: [
            { id: 'mesh', label: 'Meshtastic Network', description: 'Master toggle for all mesh radio layers. Shows LoRa mesh nodes with GPS positions.', color: '#00d4aa', source: 'Meshtastic API', key: 'showMesh', meshMaster: true },
            { id: 'meshNodes', label: 'Mesh Nodes', description: 'Green radio icons with node name labels, sized by SNR quality', color: '#00d4aa', source: 'Meshtastic API', key: 'showMeshNodes' },
            { id: 'meshLinks', label: 'Mesh Links', description: 'Lines between nodes that have communicated recently, colored by link quality', color: '#00d4aa', source: 'Meshtastic API', key: 'showMeshLinks', legend: [
                { color: 'rgba(5,255,161,0.5)', shape: 'square', label: 'Excellent (SNR > 5 dB)' },
                { color: 'rgba(0,212,170,0.35)', shape: 'square', label: 'Good (SNR 0..5 dB)' },
                { color: 'rgba(252,238,10,0.3)', shape: 'square', label: 'Fair (SNR -5..0 dB)' },
                { color: 'rgba(255,42,109,0.25)', shape: 'square', label: 'Poor (SNR < -5 dB)' },
            ]},
            { id: 'meshCoverage', label: 'Mesh Coverage', description: 'Estimated LoRa coverage circles (~10km radius) per node', color: 'rgba(0,212,170,0.3)', source: 'Meshtastic API', key: 'showMeshCoverage' },
        ],
    },
    {
        name: 'UNITS & FORCES',
        description: 'Friendly, hostile, and neutral forces on the battlefield',
        layers: [
            { id: 'units', label: 'Unit Markers', description: 'Colored icons on the map for each unit. Green = friendly, Red = hostile, Blue = neutral, Yellow = unknown', color: '#05ffa1', source: 'Simulation Engine', key: 'showUnits', legend: [
                { color: '#05ffa1', shape: 'circle', label: 'Friendly (turrets, rovers, drones, tanks)' },
                { color: '#ff2a6d', shape: 'square', label: 'Hostile (enemy combatants)' },
                { color: '#00a0ff', shape: 'circle', label: 'Neutral (civilians, NPCs)' },
                { color: '#fcee0a', shape: 'circle', label: 'Unknown (unidentified)' },
            ]},
            { id: 'models', label: '3D Unit Models', description: 'Three.js 3D models replacing 2D icons when zoomed in', color: null, source: 'Three.js', key: 'showModels3d' },
            { id: 'labels', label: 'Unit Labels', description: 'Callsign text labels under each unit marker', color: null, source: 'Simulation Engine', key: 'showLabels' },
            { id: 'healthBars', label: 'Health Bars', description: 'HP indicator bars and damage glow on units', color: null, source: 'Simulation Engine', key: 'showHealthBars' },
            { id: 'selectionFx', label: 'Selection Effects', description: 'Glow highlight on selected unit + hostile pulse animation', color: null, source: 'UI', key: 'showSelectionFx' },
            { id: 'weaponRange', label: 'Weapon Range', description: 'Circle showing selected unit weapon effective range', color: '#05ffa166', source: 'Simulation Engine', key: 'showWeaponRange' },
            { id: 'thoughts', label: 'Thought Bubbles', description: 'LLM-generated thoughts floating above unit markers', color: null, source: 'Ollama Fleet', key: 'showThoughts' },
        ],
    },
    {
        name: 'TACTICAL OVERLAYS',
        description: 'Combat information and tactical situation display',
        layers: [
            { id: 'patrolRoutes', label: 'Patrol Routes', description: 'Green dashed lines showing friendly unit patrol waypoint paths. Dots mark each waypoint.', color: '#05ffa1', source: 'Simulation Engine', key: 'showPatrolRoutes' },
            { id: 'squadHulls', label: 'Squad Formations', description: 'Convex hull outlines around hostile squads', color: '#ff2a6d', source: 'Squad System', key: 'showSquadHulls' },
            { id: 'swarmHull', label: 'Drone Swarm Hull', description: 'Convex hull around drone swarm formations', color: '#00f0ff', source: 'Swarm System', key: 'showSwarmHull' },
            { id: 'hostileObjectives', label: 'Hostile Objectives', description: 'Dashed lines showing where hostiles are heading', color: '#ff2a6d', source: 'Hostile AI', key: 'showHostileObjectives' },
            { id: 'hostileIntel', label: 'Hostile Intel HUD', description: 'Enemy commander intelligence display', color: '#ff2a6d', source: 'Intel System', key: 'showHostileIntel' },
            { id: 'coverPoints', label: 'Cover Points', description: 'Tactical cover positions with directional protection', color: '#fcee0a', source: 'Cover System', key: 'showCoverPoints' },
            { id: 'hazardZones', label: 'Hazard Zones', description: 'Environmental hazards: fires, floods, roadblocks', color: '#ff8800', source: 'Hazard System', key: 'showHazardZones' },
            { id: 'unitSignals', label: 'Unit Signals', description: 'Communication signals (distress, contact, rally)', color: '#fcee0a', source: 'Comms System', key: 'showUnitSignals' },
            { id: 'fog', label: 'Fog of War', description: 'Areas outside unit vision radius are darkened', color: '#000000', source: 'Vision System', key: 'showFog' },
            { id: 'heatmap', label: 'Combat Heatmap', description: 'Heat overlay showing where combat is concentrated', color: '#ff4400', source: 'Replay System', key: 'showHeatmap' },
            { id: 'crowdDensity', label: 'Crowd Density', description: 'Civilian crowd density heatmap (civil unrest mode)', color: '#ff8800', source: 'Population Model', key: 'showCrowdDensity' },
            { id: 'activityHeatmap', label: 'Activity Heatmap', description: 'Multi-source activity density: BLE, camera, motion sensors', color: '#ff2a6d', source: 'Heatmap Engine', key: 'showActivityHeatmap' },
            { id: 'coverageOverlap', label: 'Coverage Overlap', description: 'Highlights areas covered by 2+ sensors in brighter colors. Shows network redundancy vs gaps.', color: '#05ffa1', source: 'Fleet/Sensors', key: 'showCoverageOverlap', legend: [
                { color: 'rgba(5,255,161,0.08)', shape: 'square', label: '1 sensor (gap risk)' },
                { color: 'rgba(0,240,255,0.20)', shape: 'square', label: '2 sensors (redundant)' },
                { color: 'rgba(252,238,10,0.30)', shape: 'square', label: '3+ sensors (strong)' },
            ]},
        ],
    },
    {
        name: 'COMBAT EFFECTS',
        description: 'Visual effects during battles',
        layers: [
            { id: 'tracers', label: 'Projectile Tracers', description: 'Glowing tracer lines following projectile flight paths', color: '#ffa500', source: 'Three.js', key: 'showTracers' },
            { id: 'explosions', label: 'Explosions', description: 'Explosion effects on unit elimination', color: '#ff4400', source: 'Three.js + DOM', key: 'showExplosions' },
            { id: 'particles', label: 'Debris & Sparks', description: 'Particle effects from hits and explosions', color: '#ffcc00', source: 'Three.js', key: 'showParticles' },
            { id: 'hitFlashes', label: 'Hit Flashes', description: 'Flash effect at projectile impact point', color: '#ffffff', source: 'Three.js + DOM', key: 'showHitFlashes' },
            { id: 'floatingText', label: 'Damage Numbers', description: 'Floating damage numbers and ELIMINATED text', color: '#ff2a6d', source: 'DOM', key: 'showFloatingText' },
            { id: 'killFeed', label: 'Kill Feed', description: 'Combat log in the top-right corner', color: null, source: 'DOM', key: 'showKillFeed' },
            { id: 'screenFx', label: 'Screen Effects', description: 'Screen shake and flash overlays on big events', color: null, source: 'DOM', key: 'showScreenFx' },
            { id: 'banners', label: 'Banners', description: 'Wave start/end and game state announcement banners', color: null, source: 'DOM', key: 'showBanners' },
        ],
    },
    {
        name: 'GIS INTELLIGENCE',
        description: 'Real-world geographic data from government and OpenStreetMap sources',
        layers: [
            { id: 'geoLayers', label: 'All GIS Data', description: 'Master toggle for all geographic intelligence layers below', color: null, source: 'Various', key: 'showGeoLayers' },
            // Individual GIS layers are added dynamically from /api/geo/layers/catalog
        ],
        dynamic: true, // Flag to load from catalog
    },
    {
        name: 'GIS DATA SOURCES',
        description: 'Managed GIS layer providers — tile servers and vector feature sources',
        layers: [],
        gisPlugin: true, // Flag to load from /api/gis/layers
    },
    {
        name: 'INTERFACE',
        description: 'Map interface elements',
        layers: [
            { id: 'layerHud', label: 'Status HUD', description: 'Top-center bar showing active layers and mode', color: null, source: 'UI', key: 'showLayerHud' },
            { id: 'autoFollow', label: 'Auto-Follow Camera', description: 'Camera automatically follows combat action', color: null, source: 'UI', key: 'autoFollow' },
        ],
    },
];

// GIS layer color/description mapping for dynamic layers from the catalog
const GIS_LAYER_INFO = {
    'power-lines':      { description: 'High-voltage power transmission lines', source: 'OpenStreetMap' },
    'traffic-signals':  { description: 'Traffic signal locations at intersections', source: 'OpenStreetMap' },
    'waterways':        { description: 'Creeks, streams, and drainage channels', source: 'OpenStreetMap' },
    'water-towers':     { description: 'Municipal water storage towers', source: 'OpenStreetMap' },
    'telecom-lines':    { description: 'Telecommunications cable routes', source: 'OpenStreetMap' },
    'building-heights': { description: 'Building footprints with height data', source: 'OpenStreetMap' },
    'street-lights':    { description: 'Street light pole locations', source: 'OpenStreetMap' },
    'trees':            { description: 'Individual tree locations', source: 'OpenStreetMap' },
    'schools':          { description: 'School building locations', source: 'OpenStreetMap' },
    'fire-stations':    { description: 'Fire station locations', source: 'OpenStreetMap' },
};


export const LayersPanelDef = {
    id: 'layers',
    title: 'LAYERS',
    defaultPosition: { x: 8, y: 60 },
    defaultSize: { w: 320, h: 520 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'layers-panel-inner';
        el.innerHTML = `
            <div class="layers-search-bar">
                <input type="text" class="layers-search" placeholder="Search layers..." data-bind="search" title="Type to filter layers by name, description, or data source" />
            </div>
            <div class="layers-tree" data-bind="tree"></div>
        `;
        return el;
    },

    mount(bodyEl, _panel) {
        const treeEl = bodyEl.querySelector('[data-bind="tree"]');
        const searchEl = bodyEl.querySelector('[data-bind="search"]');
        let mapActions = null;
        let gisCatalog = []; // populated from /api/geo/layers/catalog
        let gisPluginLayers = []; // populated from /api/gis/layers

        // Get map actions via event (set by main.js)
        EventBus.on('layers:set-map-actions', (actions) => { mapActions = actions; render(); });
        // Request map actions
        EventBus.emit('layers:request-map-actions');

        // Fetch GIS catalog for dynamic layer entries
        fetch('/api/geo/layers/catalog')
            .then(r => r.ok ? r.json() : [])
            .then(catalog => { gisCatalog = catalog; render(); })
            .catch(() => {});

        // Fetch GIS plugin layers from /api/gis/layers
        fetch('/api/gis/layers')
            .then(r => r.ok ? r.json() : { layers: [] })
            .then(data => { gisPluginLayers = data.layers || []; render(); })
            .catch(() => {});

        // Track individual GIS layer visibility (off = hidden by user)
        const gisLayerOff = new Set();
        // Track GIS plugin layer visibility and opacity
        const gisPluginEnabled = new Set();
        const gisPluginOpacity = {}; // layer_id -> 0.0-1.0

        // Mesh sub-layer opacity (for the opacity slider)
        let meshLayerOpacity = 1.0;

        function getState(key) {
            if (!mapActions || !mapActions.getMapState) return false;
            // Mesh sub-layer states live in meshState, not mapState
            const ms = _getMeshState();
            if (key === 'showMeshNodes') return ms ? ms.showNodes : true;
            if (key === 'showMeshLinks') return ms ? ms.showLinks : true;
            if (key === 'showMeshCoverage') return ms ? ms.showCoverage : false;
            // Individual GIS layers
            if (key && key.startsWith('_gis_')) {
                return !gisLayerOff.has(key);
            }
            // GIS plugin data source layers
            if (key && key.startsWith('_gis_src_')) {
                return gisPluginEnabled.has(key);
            }
            const s = mapActions.getMapState();
            return !!s[key];
        }

        function toggleLayer(layerDef) {
            // Mesh sub-layer toggles (nodes, links, coverage)
            const ms = _getMeshState();
            if (ms && layerDef.key === 'showMeshNodes') {
                ms.showNodes = !ms.showNodes;
                render();
                return;
            }
            if (ms && layerDef.key === 'showMeshLinks') {
                ms.showLinks = !ms.showLinks;
                render();
                return;
            }
            if (ms && layerDef.key === 'showMeshCoverage') {
                ms.showCoverage = !ms.showCoverage;
                render();
                return;
            }
            // GIS plugin data source layer toggle
            if (layerDef.gisPlugin) {
                const key = layerDef.key;
                if (gisPluginEnabled.has(key)) {
                    gisPluginEnabled.delete(key);
                } else {
                    gisPluginEnabled.add(key);
                    if (gisPluginOpacity[layerDef.gisLayerId] === undefined) {
                        gisPluginOpacity[layerDef.gisLayerId] = 1.0;
                    }
                }
                EventBus.emit('gis:layer-toggle', {
                    layerId: layerDef.gisLayerId,
                    enabled: gisPluginEnabled.has(key),
                    opacity: gisPluginOpacity[layerDef.gisLayerId] ?? 1.0,
                    type: layerDef.gisLayerType,
                });
                render();
                return;
            }
            if (!mapActions) return;
            // Individual GIS layer toggle — directly manipulate MapLibre layer visibility
            if (layerDef.gisChild && layerDef.gisMapLayerId) {
                const map = window._mapState && window._mapState.map;
                if (!map) return;
                const key = layerDef.key;
                const isOff = gisLayerOff.has(key);
                if (isOff) {
                    gisLayerOff.delete(key);
                } else {
                    gisLayerOff.add(key);
                }
                const vis = isOff ? 'visible' : 'none';
                // Some layers have fill+outline variants
                const baseId = layerDef.gisMapLayerId;
                for (const suffix of ['', '-fill', '-outline']) {
                    const layerId = baseId + suffix;
                    if (map.getLayer(layerId)) {
                        try { map.setLayoutProperty(layerId, 'visibility', vis); } catch (e) {}
                    }
                }
                render();
                return;
            }
            // Standard toggle via mapActions
            const toggleName = 'toggle' + layerDef.id.charAt(0).toUpperCase() + layerDef.id.slice(1);
            if (typeof mapActions[toggleName] === 'function') {
                mapActions[toggleName]();
                render();
            }
        }

        function render(filter) {
            if (!treeEl) return;
            const q = (filter || '').toLowerCase();
            let html = '';

            for (const cat of LAYER_CATEGORIES) {
                let layers = [...cat.layers];

                // Inject dynamic GIS layers from catalog
                if (cat.dynamic && gisCatalog.length > 0) {
                    for (const gis of gisCatalog) {
                        const info = GIS_LAYER_INFO[gis.id] || {};
                        layers.push({
                            id: `geo_${gis.id}`,
                            gisMapLayerId: `geo-${gis.id}-layer`,
                            label: gis.name,
                            description: info.description || `${gis.name} layer`,
                            color: gis.color,
                            source: info.source || 'OpenStreetMap',
                            key: `_gis_${gis.id}`, // individual GIS toggle key
                            gisChild: true,
                        });
                    }
                }

                // Inject GIS plugin data source layers
                if (cat.gisPlugin && gisPluginLayers.length > 0) {
                    for (const gpl of gisPluginLayers) {
                        layers.push({
                            id: `gis_src_${gpl.id}`,
                            label: gpl.name,
                            description: gpl.description || `${gpl.name} (${gpl.type})`,
                            color: gpl.type === 'tile' ? null : '#00f0ff',
                            source: gpl.attribution || 'GIS Plugin',
                            key: `_gis_src_${gpl.id}`,
                            gisPlugin: true,
                            gisLayerId: gpl.id,
                            gisLayerType: gpl.type,
                        });
                    }
                }

                // Filter
                if (q) {
                    layers = layers.filter(l =>
                        l.label.toLowerCase().includes(q) ||
                        (l.description && l.description.toLowerCase().includes(q)) ||
                        (l.source && l.source.toLowerCase().includes(q))
                    );
                    if (layers.length === 0) continue;
                }

                const catExpanded = !q; // auto-expand when filtering
                html += `<div class="layer-category${catExpanded ? ' expanded' : ' expanded'}">`;
                html += `<div class="layer-cat-header" data-cat="${_esc(cat.name)}" title="${_esc(cat.description)}">`;
                html += `<span class="layer-cat-chevron">&#9660;</span>`;
                html += `<span class="layer-cat-name">${_esc(cat.name)}</span>`;
                html += `<span class="layer-cat-desc">${_esc(cat.description)}</span>`;
                html += `</div>`;
                html += `<div class="layer-cat-body">`;

                for (const layer of layers) {
                    const on = layer.key ? getState(layer.key) : false;
                    const isGisChild = layer.gisChild;
                    const isMeshSub = (layer.key === 'showMeshNodes' || layer.key === 'showMeshLinks' || layer.key === 'showMeshCoverage');
                    const swatch = layer.color
                        ? `<span class="layer-swatch" style="background:${layer.color}" title="${layer.color}"></span>`
                        : `<span class="layer-swatch layer-swatch-none" title="No color"></span>`;

                    html += `<div class="layer-item${on ? ' active' : ''}${isGisChild ? ' gis-child' : ''}${isMeshSub ? ' mesh-sub' : ''}" `;
                    html += `data-layer-id="${_esc(layer.id)}" `;
                    html += `title="${_esc(layer.description)}">`;
                    if (layer.key) {
                        html += `<label class="layer-toggle">`;
                        html += `<input type="checkbox" ${on ? 'checked' : ''} data-key="${_esc(layer.key)}" />`;
                        html += `<span class="layer-toggle-track"><span class="layer-toggle-thumb"></span></span>`;
                        html += `</label>`;
                    } else {
                        html += `<span class="layer-indent"></span>`;
                    }
                    html += swatch;
                    html += `<span class="layer-label-group">`;
                    // Show node count on mesh master toggle
                    if (layer.meshMaster) {
                        const nodeCount = _getMeshNodeCount();
                        const countStr = nodeCount > 0 ? ` (${nodeCount})` : '';
                        html += `<span class="layer-label">${_esc(layer.label)}${countStr}</span>`;
                    } else {
                        html += `<span class="layer-label">${_esc(layer.label)}</span>`;
                    }
                    html += `<span class="layer-desc">${_esc(layer.description)}</span>`;
                    html += `</span>`;
                    html += `<span class="layer-source" title="Data source: ${_esc(layer.source)}">${_esc(layer.source)}</span>`;
                    html += `</div>`;

                    // Inline legend for unit markers
                    if (layer.legend && on) {
                        html += `<div class="layer-legend">`;
                        for (const entry of layer.legend) {
                            const shape = entry.shape === 'square'
                                ? `<span class="legend-icon legend-square" style="background:${entry.color}"></span>`
                                : `<span class="legend-icon legend-circle" style="background:${entry.color}"></span>`;
                            html += `<div class="legend-entry">${shape}<span>${_esc(entry.label)}</span></div>`;
                        }
                        html += `</div>`;
                    }

                    // Opacity slider for GIS plugin layers when enabled
                    if (layer.gisPlugin && on) {
                        const opVal = gisPluginOpacity[layer.gisLayerId] ?? 1.0;
                        const pct = Math.round(opVal * 100);
                        html += `<div class="layer-opacity-row" data-gis-opacity="${_esc(layer.gisLayerId)}">`;
                        html += `<span class="layer-opacity-label">OPACITY</span>`;
                        html += `<input type="range" class="layer-opacity-slider" min="0" max="100" value="${pct}" data-gis-layer="${_esc(layer.gisLayerId)}" />`;
                        html += `<span class="layer-opacity-value">${pct}%</span>`;
                        html += `</div>`;
                        // Attribution line
                        if (layer.source) {
                            html += `<div class="layer-attribution">${_esc(layer.source)}</div>`;
                        }
                    }

                    // Opacity slider for mesh master toggle when enabled
                    if (layer.meshMaster && on) {
                        const meshPct = Math.round(meshLayerOpacity * 100);
                        html += `<div class="layer-opacity-row" data-mesh-opacity="mesh">`;
                        html += `<span class="layer-opacity-label">OPACITY</span>`;
                        html += `<input type="range" class="layer-opacity-slider mesh-opacity-slider" min="0" max="100" value="${meshPct}" />`;
                        html += `<span class="layer-opacity-value">${meshPct}%</span>`;
                        html += `</div>`;
                    }
                }

                html += `</div></div>`;
            }

            if (!html) {
                html = '<div class="panel-empty">No layers match filter</div>';
            }

            treeEl.innerHTML = html;

            // Build a lookup of all rendered layers (including dynamic GIS children)
            const allRenderedLayers = [];
            for (const cat of LAYER_CATEGORIES) {
                allRenderedLayers.push(...cat.layers);
                if (cat.dynamic && gisCatalog.length > 0) {
                    for (const gis of gisCatalog) {
                        const info = GIS_LAYER_INFO[gis.id] || {};
                        allRenderedLayers.push({
                            id: `geo_${gis.id}`,
                            gisMapLayerId: `geo-${gis.id}-layer`,
                            label: gis.name,
                            key: `_gis_${gis.id}`,
                            gisChild: true,
                        });
                    }
                }
                if (cat.gisPlugin && gisPluginLayers.length > 0) {
                    for (const gpl of gisPluginLayers) {
                        allRenderedLayers.push({
                            id: `gis_src_${gpl.id}`,
                            label: gpl.name,
                            key: `_gis_src_${gpl.id}`,
                            gisPlugin: true,
                            gisLayerId: gpl.id,
                            gisLayerType: gpl.type,
                        });
                    }
                }
            }

            // Bind toggle clicks
            for (const cb of treeEl.querySelectorAll('input[type="checkbox"]')) {
                cb.addEventListener('change', () => {
                    const key = cb.dataset.key;
                    const layer = allRenderedLayers.find(l => l.key === key);
                    if (layer) toggleLayer(layer);
                });
            }

            // Bind opacity sliders for GIS plugin layers
            for (const slider of treeEl.querySelectorAll('.layer-opacity-slider:not(.mesh-opacity-slider)')) {
                slider.addEventListener('input', () => {
                    const layerId = slider.dataset.gisLayer;
                    if (!layerId) return;
                    const val = parseInt(slider.value, 10) / 100;
                    gisPluginOpacity[layerId] = val;
                    const valLabel = slider.parentElement.querySelector('.layer-opacity-value');
                    if (valLabel) valLabel.textContent = `${slider.value}%`;
                    EventBus.emit('gis:layer-opacity', { layerId, opacity: val });
                });
            }

            // Bind mesh opacity slider
            for (const slider of treeEl.querySelectorAll('.mesh-opacity-slider')) {
                slider.addEventListener('input', () => {
                    const val = parseInt(slider.value, 10) / 100;
                    meshLayerOpacity = val;
                    const ms = _getMeshState();
                    if (ms) ms.opacity = val;
                    const valLabel = slider.parentElement.querySelector('.layer-opacity-value');
                    if (valLabel) valLabel.textContent = `${slider.value}%`;
                });
            }

            // Bind category collapse/expand
            for (const hdr of treeEl.querySelectorAll('.layer-cat-header')) {
                hdr.addEventListener('click', () => {
                    hdr.parentElement.classList.toggle('expanded');
                });
            }
        }

        // Search filter
        if (searchEl) {
            searchEl.addEventListener('input', () => render(searchEl.value));
        }

        // Re-render when map state changes (layer toggled elsewhere)
        const stateHandler = () => render(searchEl ? searchEl.value : '');
        EventBus.on('map:layers-changed', stateHandler);

        // Start mesh node auto-refresh if available
        if (typeof meshStartAutoRefresh === 'function') {
            meshStartAutoRefresh();
        }

        // Periodically re-render to update mesh node count in label (every 30s)
        const meshCountInterval = setInterval(() => {
            render(searchEl ? searchEl.value : '');
        }, 30000);

        // Initial render
        render();

        return () => {
            EventBus.off('map:layers-changed', stateHandler);
            clearInterval(meshCountInterval);
            if (typeof meshStopAutoRefresh === 'function') {
                meshStopAutoRefresh();
            }
        };
    },
};
